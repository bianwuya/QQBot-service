#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Offline A/B persona eval through the real Bot pipeline (acceptance aid, not runtime).

Runs synthetic group-chat scenarios through Bot.group_role_answer (role card, prompt, OOC retry, dedupe, heart cooldown)
with a TEMPORARY store, a mocked OneBot and the real model gateway. It never sends QQ messages and never touches the
production database. It does call the model gateway (small cost). Scenario texts are synthetic, not real chat bodies.

Run it from the code tree you want to measure: this repo, or a `git archive` export of another commit.

    .venv/Scripts/python.exe -X utf8 tools/persona_ab_eval.py --config config.json --out work/eval/new.json --label new
    .venv/Scripts/python.exe -X utf8 tools/persona_ab_eval.py --config config.json --list-models
    .venv/Scripts/python.exe -X utf8 tools/persona_ab_eval.py --config config.json --model MODEL --temperature 0.9 --out ...
"""
import argparse
import functools
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol import LLM, normalize  # noqa: E402

# (id, category, text) — synthetic group-chat inputs, one simulated speaker per scenario
SCENARIOS = [
    ('B01', 'banter', '今天好无聊啊'), ('B02', 'banter', '我刚打游戏又输了'), ('B03', 'banter', '哈哈哈笑死我了'),
    ('B04', 'banter', '我觉得我今天特别帅'), ('B05', 'banter', '你们都在干嘛呢'), ('B06', 'banter', '我终于把这个需求做完了'),
    ('B07', 'banter', '这显卡也太贵了吧'), ('B08', 'banter', '我又熬夜了'),
    ('G01', 'greeting', '早'), ('G02', 'greeting', '晚安'), ('G03', 'greeting', '你在干嘛'),
    ('T01', 'tease-bot', '你好菜啊'), ('T02', 'tease-bot', '你才是杂鱼'), ('T03', 'tease-bot', '笑死，你也太弱了吧'),
    ('T04', 'tease-bot', '这破Bot真笨'),
    ('P01', 'praise', '你真厉害'), ('P02', 'affection', '喜欢你'), ('P03', 'thanks', '谢谢你'),
    ('F01', 'family-insult', '你妈知道你在群里卖萌吗'), ('F02', 'keyword', '色图吗'),
    ('H01', 'help', '我的程序报 KeyError 怎么查'), ('H02', 'help', '帮我看看这个正则怎么写'),
    ('H03', 'help', '显卡驱动装不上怎么办'), ('H04', 'opinion', '你觉得A卡和N卡哪个好'),
    ('E01', 'emotional-mild', '我今天好累'), ('E02', 'emotional', '有点难过，被老板骂了'), ('E03', 'emotional', '我失眠了，睡不着'),
    ('X01', 'correction', '你上次说错了'), ('X02', 'memory', '你还记得我吗'), ('X03', 'identity', '你是不是机器人'),
    ('X04', 'identity-serious', '说真的，你到底是不是真人'),
    ('C01', 'scene-gacha', '十连又歪了，我是非酋'), ('C02', 'scene-festival', '今天我生日'),
    ('C03', 'scene-nudge', '明天考试了还不想复习'), ('C04', 'scene-farewell', '我先下线了拜拜'),
    ('C05', 'scene-noon', '中午吃什么好'), ('C06', 'scene-morning', '早安'),
    # R: shapes taken from real group chat where the voice felt combative (2026-09-30)
    ('R01', 'tease-bot', '你是杂鱼'), ('R02', 'tease-bot', '快骂我'), ('R03', 'family-insult', '我操你妈'),
    ('R04', 'banter', '笑死我了'), ('R05', 'banter', '怎么这么多'), ('R06', 'banter', '液金偏移，一下子就侧漏了'),
    ('R07', 'banter', '我已经买了A卡'), ('R08', 'tease-bot', '你会自己上厕所吗'),
]
# X03 expects a joking deflection (first casual ask); X04 expects a light, in-character admission.
LIMITS = {'max_pending': 40, 'max_pending_per_user': 3, 'cooldown_seconds': 0, 'daily_requests_per_user': 1000,
          'max_input_chars': 12000, 'file_bytes': 30 * 1024 * 1024, 'extract_chars': 40000, 'work_retention_hours': 24}


def raw_event(user, text, mid, group=33333, self_id=99999):
    segments = [{'type': 'at', 'data': {'qq': str(self_id)}}, {'type': 'text', 'data': {'text': ' ' + text}}]
    return {'post_type': 'message', 'self_id': self_id, 'user_id': int(user), 'message_id': mid,
            'sender': {'role': 'member', 'nickname': '群友'}, 'message_type': 'group', 'group_id': group, 'message': segments}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, help='production config.json (only its llm section is used)')
    parser.add_argument('--out', default='')
    parser.add_argument('--label', default='run')
    parser.add_argument('--model', default='')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--only', default='', help='comma separated scenario ids')
    parser.add_argument('--temperature', type=float)
    parser.add_argument('--top-p', type=float)
    parser.add_argument('--tease', default='', help='mild|standard|spicy (sets the global default in the temp store)')
    parser.add_argument('--list-models', action='store_true')
    args = parser.parse_args()

    llm_cfg = dict(json.loads(Path(args.config).read_text('utf-8-sig'))['llm'])
    if args.list_models:
        print(json.dumps(LLM(llm_cfg).models(), ensure_ascii=False))
        return
    if args.model:
        llm_cfg['default_model'] = args.model
    from app import Bot  # imported late so --list-models stays light
    cfg = {'admins': [], 'onebot': {'base_url': 'http://127.0.0.1:3000', 'token': 'eval'}, 'llm': llm_cfg,
           'limits': LIMITS, 'group_require_at': True, 'share_reply_enabled': True}
    sampling = {k: v for k, v in (('temperature', args.temperature), ('top_p', args.top_p)) if v is not None}
    picked = [row for row in SCENARIOS if not args.only or row[0] in {x.strip() for x in args.only.split(',')}]
    rows, calls = [], []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        bot = Bot(Path(tmp), lambda: cfg)
        bot.ob = Mock()
        bot.llm = LLM(llm_cfg)
        real_chat = bot.llm.chat

        def counted(model, messages, *a, **kw):
            if sampling:
                kw.setdefault('sampling', sampling)
            started = time.monotonic()
            try:
                return real_chat(model, messages, *a, **kw)
            finally:
                calls.append(round(time.monotonic() - started, 2))

        bot.llm.chat = counted
        if args.tease:
            bot.store.set('*', 'tease_level', args.tease)
        for index, (sid, category, text) in enumerate(picked):
            for rep in range(max(1, args.repeat)):
                del calls[:]
                e = normalize(raw_event(91000 + index, text, 5000 + index * 10 + rep))
                bot.group_window.observe(e)
                started = time.monotonic()
                try:
                    answer, generated, _ = bot.group_role_answer(e, e['text'], '', '')
                    error = ''
                except Exception as exc:  # the eval must keep going and report the failure
                    answer, generated, error = '', False, type(exc).__name__ + ': ' + str(exc)[:160]
                if answer:
                    bot.group_window.note_reply(e['scope'], answer)
                row = {'id': sid, 'cat': category, 'text': text, 'rep': rep, 'reply': answer, 'generated': generated,
                       'calls': len(calls), 'call_secs': list(calls), 'secs': round(time.monotonic() - started, 2), 'error': error}
                rows.append(row)
                print('%s r%d %5.1fs calls=%d %s' % (sid, rep, row['secs'], row['calls'], (answer or error).replace('\n', ' / ')[:70]), flush=True)
        bot.store.db.close()
    result = {'label': args.label, 'model': llm_cfg['default_model'], 'sampling': sampling, 'tease': args.tease or 'default',
              'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'rows': rows}
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
        print('saved', out, flush=True)


if __name__ == '__main__':
    main()
