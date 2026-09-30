"""Explicit admin import of the caller's already downloaded, bounded document."""
import json
from pathlib import Path
import sys
import persona
from media import run_bounded
from safe_net import Rejected


def handle(bot, event, arg, directory):
    scope = event['scope']
    action, _, value = arg.partition(' ')
    value = value.strip()
    if action in ('', '状态', '列表'):
        rows = bot.knowledge.list(scope)
        if action != '列表':
            return '当前可管理知识来源：{}；仅明确导入的资料，不包含聊天历史。'.format(len(rows))
        return '\n'.join(r['source_id']+' ['+r['namespace']+'] '+r['title'] for r in rows) or '暂无知识资料。'
    if action in ('删除', '重建') and value:
        bot.knowledge.mutate(scope, value, rebuild=action=='重建')
        return '知识来源已'+action+'。'
    if action == '导入':
        namespace = value or ('group:'+scope[2:] if scope.startswith('g:') else 'common')
        bot.knowledge.import_target(scope, namespace)
        if namespace.startswith('role:') and persona.find_role(namespace[5:]) is None:
            raise Rejected('未知角色 namespace')
        record = bot.store.file(scope, event['owner'])
        if not record:
            raise Rejected('请先上传文件，再明确执行 /知识库 导入 [namespace]；只导入本人在当前会话的最近文件')
        path = bot.validate_output_path(record['path'])
        if path.stat().st_size > bot.config_loader()['limits']['file_bytes']:
            raise Rejected('文件超过大小限制')
        if Path(record['name']).suffix.lower() not in {'.txt', '.md', '.pdf', '.docx', '.xlsx', '.pptx'}:
            raise Rejected('知识库只导入 txt/md/pdf/docx/xlsx/pptx')
        output = run_bounded([sys.executable, str(Path(__file__).with_name('documents.py')), str(path), record['name'], '40000'],
                             directory, timeout=30, max_output=1024*1024)
        try:
            data = json.loads(output)
        except (ValueError, TypeError):
            raise Rejected('资料抽取失败') from None
        if data.get('error'):
            raise Rejected('资料无法安全抽取')
        # Revocation may occur during extraction; decide again before durable import.
        if event['owner'] not in bot.config_loader()['admins']:
            raise Rejected('管理员权限已撤销')
        ident, added = bot.knowledge.add(scope, namespace, record['name'], data.get('text', ''))
        return ('已导入：' if added else '资料已存在：')+ident
    return '用法：/知识库 状态|列表|导入 [namespace]|删除 <id>|重建 <id>'
