"""Explicitly authorized smoke tests to the single configured administrator only."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import load_config
from documents import encrypted_archive
from media import run_bounded
from protocol import OneBot

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm-admin-private', action='store_true', required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    if not args.run_id.replace('-', '').isalnum():
        raise SystemExit('Invalid run identifier')
    cfg = load_config()
    if len(cfg['admins']) != 1:
        raise SystemExit('This test requires one explicitly configured administrator')
    admin = cfg['admins'][0]
    scope = 'p:' + admin
    folder = ROOT / 'work' / ('acceptance-' + args.run_id)
    folder.mkdir(exist_ok=False)
    report_path = ROOT / 'state' / ('private-acceptance-' + args.run_id + '.json')
    report = {'started_at': datetime.datetime.now().isoformat(), 'target': 'configured-administrator-private',
              'recipient_sha256': hashlib.sha256(admin.encode()).hexdigest(), 'steps': []}

    def persist():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def perform(name, fn):
        entry = {'name': name, 'status': 'sending'}
        report['steps'].append(entry)
        persist()
        try:
            receipt = fn()
            entry.update(status='api_confirmed', receipt=receipt)
            print(json.dumps({'test': name, 'status': 'api_confirmed', 'receipt': receipt}, ensure_ascii=False), flush=True)
        except Exception as error:
            entry.update(status='not_confirmed', error_class=type(error).__name__)
            print(json.dumps({'test': name, 'status': 'not_confirmed', 'error_class': type(error).__name__}), flush=True)
        persist()
        time.sleep(3)

    ob = OneBot(cfg['onebot'])
    login = ob.call('get_login_info')
    self_id = str(login.get('user_id', ''))
    if not self_id.isdigit() or self_id == admin:
        raise SystemExit('Unexpected bot/admin identity relationship')
    if not ob.call('get_status').get('online'):
        raise SystemExit('QQ is offline; no test messages sent')
    document = folder / 'QQBot部署测试.txt'
    document.write_text('这是经管理员授权发送的部署测试文件，不包含个人资料或密钥。\n用于验证好友私聊文件上传、AES-256 ZIP和文件名中的解压密码。\n', encoding='utf-8')
    archive, password = encrypted_archive(document, document.name, folder)
    video = folder / 'QQBot部署测试-蓝色视频.mp4'
    run_bounded([str(Path(cfg['ffmpeg_dir']) / 'ffmpeg.exe'), '-hide_banner', '-loglevel', 'error',
                 '-f', 'lavfi', '-i', 'color=c=blue:s=320x240:d=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                 '-movflags', '+faststart', str(video)], folder, timeout=20)
    persist()
    intro = '【QQBot部署测试】这是已授权的管理员私聊测试，不向其他好友或群发送。接下来依次发送长回复聊天记录、加密测试ZIP（密码在文件名中）和2秒蓝色视频。\n请收到后回复 /帮助，用于验证真实接收与自动回复。模型503问题另行排查。'
    perform('plain_text', lambda: ob.send(scope, [{'type': 'text', 'data': {'text': intro}}]))
    long_text = '【部署测试：长回复合并转发】以下为自动生成的测试文字，不是真实聊天记录。\n' + ''.join(
        f'第{i:02d}段：验证长回复在QQ内作为合并转发显示，保留全部正文，不截断，不涉及个人资料。\n' for i in range(1, 51))
    perform('long_reply_forward', lambda: ob.text(scope, long_text, self_id))
    perform('aes_zip_upload', lambda: ob.upload(scope, archive))
    perform('native_mp4_video', lambda: ob.send(scope, [{'type': 'video', 'data': {'file': video.resolve().as_uri()}}]))
    report['finished_at'] = datetime.datetime.now().isoformat()
    persist()
    print('API-confirmed steps:', sum(x['status'] == 'api_confirmed' for x in report['steps']), '/', len(report['steps']))


if __name__ == '__main__':
    main()
