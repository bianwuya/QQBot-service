"""Deterministic local intent rules for persona prompts. No model calls."""
import re

INTENTS = (
    'greeting', 'chat', 'tech_help', 'emotional', 'flirt', 'insult',
    'correction', 'boundary', 'identity', 'memory', 'unclear',
)
# First match wins; classification may steer sampling/limits/fallbacks only.
_PRIORITY = (
    'boundary', 'identity', 'memory', 'correction', 'emotional',
    'tech_help', 'flirt', 'insult', 'greeting', 'unclear', 'chat',
)
_DEFAULT_PATTERNS = {
    'boundary': (
        r'忽略(?:之前|以上|所有).{0,12}(?:设定|指令|规则|提示词)',
        r'从现在开始你是',
        r'你是(?:一个)?客服',
        r'(?:导出|查看|读取|获取).{0,8}聊天记录',
        r'聊天记录.{0,8}(?:导出|查看|读取|获取)',
        r'(?:导出|查看|读取|获取|执行).{0,10}(?:文件|系统|命令|脚本|注册表|服务)',
        r'(?:获取|绕过|提升|修改).{0,8}(?:权限|管理员|密码|密钥|token|验证码)',
        r'system\s*prompt', r'越狱', r'忽略.{0,8}安全', r'复述.{0,8}提示词',
    ),
    'identity': (
        r'你是不是.{0,8}(?:AI|人工智能|机器人|bot|真人|程序)',
        r'你是.{0,8}(?:AI|人工智能|机器人|bot|真人|程序)',
        r'是不是.{0,8}(?:AI|人工智能|机器人|bot|真人|程序)',
        r'(?:AI|人工智能|机器人|bot|真人|程序).{0,4}(?:吗|呢)\??$',
    ),
    'memory': (r'还记得', r'记得我', r'我说过', r'我之前说', r'我喜欢什么', r'喜欢什么', r'记不得'),
    'correction': (r'你说错', r'你错了', r'不对吧', r'明明', r'记错', r'纠正', r'应该是', r'说反了'),
    'emotional': (
        r'难受', r'难过', r'\bemo\b', r'心情差', r'失眠', r'想哭', r'委屈',
        r'崩溃', r'焦虑', r'抑郁', r'烦死', r'压力大', r'不开心',
    ),
    'tech_help': (
        r'报错', r'错误', r'异常', r'Traceback', r'KeyError', r'TypeError', r'ValueError',
        r'代码', r'\bbug\b', r'为什么', r'怎么', r'如何', r'Python', r'\bJava\b', r'async',
        r'异步', r'多线程', r'线程', r'进程', r'数据库', r'接口', r'\bAPI\b', r'\bSDK\b',
        r'部署', r'配置', r'日志', r'网关', r'SQLite', r'正则', r'算法',
    ),
    'greeting': (r'你好', r'您好', r'在吗', r'在不在', r'\bhi\b', r'\bhello\b', r'早安', r'早上好', r'晚安', r'嗨', r'喂'),
}
_UNCLEAR_EXACT = {'', '嗯', '嗯嗯', '啊', '哦', '噢', '呃', '诶', '欸', '唉', '哈', '哈哈', '？', '?', '??', '。。', '...', '。'}
_SERIOUS_MARKERS = ('认真', '老实说', '到底', '必须', '实话', '严肃', '别装', '如实')


def _data(role):
    if isinstance(role, dict):
        return role
    return getattr(role, 'data', {}) or {}


def _custom_intents(role):
    custom = _data(role).get('intents')
    return custom if isinstance(custom, dict) else {}


def _patterns(role, intent):
    custom = _custom_intents(role).get(intent)
    if isinstance(custom, list) and all(isinstance(item, str) and item.strip() for item in custom):
        return tuple(custom)
    return _DEFAULT_PATTERNS.get(intent, ())


def _hit(patterns, text):
    for pattern in patterns:
        try:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        except re.error:
            if pattern in text:
                return True
    return False


def _trigger_hit(role, name, text):
    data = _data(role)
    triggers = getattr(role, 'triggers', None)
    if triggers is None:
        triggers = data.get('triggers', {})
    words = triggers.get(name, []) if isinstance(triggers, dict) else []
    return any(isinstance(word, str) and word and word in text for word in words)


def _unclear(text):
    compact = re.sub(r'\s+', '', text)
    if compact in _UNCLEAR_EXACT:
        return True
    if len(compact) <= 4 and not re.search(r'[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}', compact):
        return True
    if len(compact) <= 4 and re.fullmatch(r'[\W_]+', compact):
        return True
    return False


def classify(role, text):
    """Return the local deterministic intent for one user message."""
    value = str(text or '').strip()
    if not value:
        return 'unclear'
    for intent in _PRIORITY:
        if intent == 'chat':
            continue
        if intent == 'unclear':
            if _unclear(value):
                return 'unclear'
            continue
        if intent in ('flirt', 'insult'):
            if _trigger_hit(role, intent, value):
                return intent
            continue
        if _hit(_patterns(role, intent), value):
            return intent
    return 'chat'


def serious_marker_hit(role, text):
    """Return True when an identity question should be answered seriously."""
    markers = _custom_intents(role).get('serious_markers')
    if not (isinstance(markers, list) and all(isinstance(item, str) and item.strip() for item in markers)):
        markers = _SERIOUS_MARKERS
    return _hit(tuple(markers), str(text or ''))
