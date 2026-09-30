"""Validated role-card loading with a safe built-in fallback."""
from dataclasses import dataclass
import json
from pathlib import Path
import re


REQUIRED_FIELDS = (
    'id', 'display_name', 'identity', 'core', 'surface', 'speech_style',
    'boundaries', 'states', 'triggers', 'relation_rules', 'reply_limits',
    'social_behavior', 'memory_behavior',
)


class RoleCardError(ValueError):
    pass


@dataclass(frozen=True)
class RoleCard:
    id: str
    display_name: str
    data: dict
    prompt: str
    corpus: dict
    source: Path | None = None

    @property
    def states(self):
        return self.data['states']

    @property
    def triggers(self):
        return self.data['triggers']

    @property
    def relation_rules(self):
        return self.data['relation_rules']

    @property
    def reply_limits(self):
        return self.data['reply_limits']


class RoleCatalog:
    def __init__(self, roles, errors=None, preferred_default='xiaozayu'):
        self.roles = dict(roles)
        self.errors = dict(errors or {})
        if not self.roles:
            emergency = _emergency_role()
            self.roles[emergency.id] = emergency
        if preferred_default in self.roles:
            self.default_id = preferred_default
        elif 'normal' in self.roles:
            self.default_id = 'normal'
        else:
            self.default_id = sorted(self.roles)[0]

    @property
    def default(self):
        return self.roles[self.default_id]

    def get(self, role_id=None):
        return self.roles.get(role_id) or self.default

    def find(self, value):
        if not isinstance(value, str):
            return None
        needle = value.strip().casefold()
        if not needle:
            return None
        for role in self.roles.values():
            if needle in (role.id.casefold(), role.display_name.casefold()):
                return role
        return None

    def list(self):
        return sorted(self.roles.values(), key=lambda role: role.id)


def _read_json(path):
    try:
        return json.loads(path.read_text('utf-8-sig'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RoleCardError(f'{path.name}: invalid JSON or unreadable file') from exc


def _string_list(value, allow_empty=False):
    return (isinstance(value, list) and (allow_empty or bool(value))
            and all(isinstance(item, str) and item.strip() for item in value))


def _validate(card, corpus, directory):
    if not isinstance(card, dict):
        raise RoleCardError(f'{directory.name}: card.json must contain an object')
    missing = [field for field in REQUIRED_FIELDS if field not in card]
    if missing:
        raise RoleCardError(f'{directory.name}: missing fields: '+', '.join(missing))
    for field in ('id', 'display_name', 'identity', 'core', 'surface', 'speech_style',
                  'social_behavior', 'memory_behavior'):
        if not isinstance(card[field], str) or not card[field].strip():
            raise RoleCardError(f'{directory.name}: {field} must be a non-empty string')
    if not re.fullmatch(r'[a-z][a-z0-9_-]{1,31}', card['id']):
        raise RoleCardError(f'{directory.name}: invalid role id')
    if card['id'] != directory.name:
        raise RoleCardError(f'{directory.name}: role id must match its directory')
    if not _string_list(card['boundaries']):
        raise RoleCardError(f'{directory.name}: boundaries must be non-empty strings')
    states = card['states']
    if not isinstance(states, dict) or not isinstance(states.get('default'), str):
        raise RoleCardError(f'{directory.name}: states.default is required')
    modes = states.get('modes')
    if not isinstance(modes, dict) or states['default'] not in modes:
        raise RoleCardError(f'{directory.name}: default state must exist in states.modes')
    if not all(isinstance(value, dict) and isinstance(value.get('label'), str) for value in modes.values()):
        raise RoleCardError(f'{directory.name}: every state requires a label')
    if not isinstance(states.get('trigger_rounds', 0), int) or states.get('trigger_rounds', 0) < 0:
        raise RoleCardError(f'{directory.name}: trigger_rounds must be a non-negative integer')
    triggers = card['triggers']
    if not isinstance(triggers, dict) or not all(_string_list(triggers.get(name, []), allow_empty=True) for name in ('flirt', 'insult')):
        raise RoleCardError(f'{directory.name}: triggers must contain string lists')
    rules = card['relation_rules']
    if not isinstance(rules, dict) or not isinstance(rules.get('minimum'), int) or not isinstance(rules.get('maximum'), int):
        raise RoleCardError(f'{directory.name}: relation_rules bounds are required')
    limits = card['reply_limits']
    if not isinstance(limits, dict) or not isinstance(limits.get('max_chars'), int) or limits['max_chars'] < 1:
        raise RoleCardError(f'{directory.name}: reply_limits.max_chars must be positive')
    default_max = limits.get('default_max', limits['max_chars'])
    if not isinstance(default_max, int) or default_max < 1:
        raise RoleCardError(f'{directory.name}: reply_limits.default_max must be positive when present')
    tiers = limits.get('tiers', {})
    if tiers is not None and (not isinstance(tiers, dict) or not all(isinstance(key, str) and isinstance(value, int) and value > 0 for key, value in tiers.items())):
        raise RoleCardError(f'{directory.name}: reply_limits.tiers must map intent names to positive integers')
    if not isinstance(limits.get('instruction'), str) or not limits['instruction'].strip():
        raise RoleCardError(f'{directory.name}: reply_limits.instruction is required')
    intents = card.get('intents')
    if intents is not None and (not isinstance(intents, dict) or not all(isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value) for value in intents.values())):
        raise RoleCardError(f'{directory.name}: intents must map names to non-empty string lists')
    behaviors = card.get('behaviors')
    if behaviors is not None and (not isinstance(behaviors, dict) or not all(isinstance(key, str) and isinstance(value, str) and value.strip() for key, value in behaviors.items())):
        raise RoleCardError(f'{directory.name}: behaviors must map intent names to non-empty rules')
    ooc_words = card.get('ooc_words')
    if ooc_words is not None and not _string_list(ooc_words, allow_empty=True):
        raise RoleCardError(f'{directory.name}: ooc_words must be a string list when present')
    ooc = card.get('ooc')
    if ooc is not None:
        if not isinstance(ooc, dict):
            raise RoleCardError(f'{directory.name}: ooc must be an object when present')
        for name in ('hard', 'service_tone', 'sweet_tone', 'soft', 'soft_allow'):
            if name in ooc and not _string_list(ooc[name], allow_empty=True):
                raise RoleCardError('{}: ooc.{} must be a string list when present'.format(directory.name, name))
    if not isinstance(corpus, dict) or not isinstance(corpus.get('categories'), dict):
        raise RoleCardError(f'{directory.name}: corpus categories are required')
    if not all(_string_list(items) for items in corpus['categories'].values()):
        raise RoleCardError(f'{directory.name}: corpus categories must contain strings')
    fallbacks = corpus.get('fallbacks')
    if isinstance(fallbacks, dict):
        if not _string_list(fallbacks.get('generic')) or not all(_string_list(items) for items in fallbacks.values()):
            raise RoleCardError(f'{directory.name}: fallback dictionary requires non-empty string lists')
    elif not _string_list(fallbacks):
        raise RoleCardError(f'{directory.name}: at least one fallback is required')
    plans = corpus.get('plans')
    if not isinstance(plans, dict) or states['default'] not in plans:
        raise RoleCardError(f'{directory.name}: corpus plan for default state is required')
    intent_plans = corpus.get('intent_plans')
    if intent_plans is not None and not isinstance(intent_plans, dict):
        raise RoleCardError(f'{directory.name}: intent_plans must be an object when present')


def load_role(directory):
    directory = Path(directory)
    card = _read_json(directory/'card.json')
    corpus = _read_json(directory/'corpus.json')
    try:
        prompt = (directory/'prompt.md').read_text('utf-8-sig').strip()
    except (OSError, UnicodeError) as exc:
        raise RoleCardError(f'{directory.name}: prompt.md is unreadable') from exc
    if not prompt:
        raise RoleCardError(f'{directory.name}: prompt.md is empty')
    _validate(card, corpus, directory)
    return RoleCard(card['id'], card['display_name'], card, prompt, corpus, directory)


def load_catalog(root, preferred_default='xiaozayu'):
    root = Path(root)
    roles = {}
    errors = {}
    try:
        directories = sorted(path for path in root.iterdir() if path.is_dir())
    except OSError:
        directories = []
    for directory in directories:
        try:
            role = load_role(directory)
            roles[role.id] = role
        except RoleCardError as exc:
            errors[directory.name] = str(exc)
    return RoleCatalog(roles, errors, preferred_default=preferred_default)


def _emergency_role():
    data = {
        'id': 'normal', 'display_name': '普通助手', 'identity': '可靠的中文QQ助手',
        'core': '清楚、克制地回答问题。', 'surface': '友好直接，不虚构能力。',
        'speech_style': '自然简洁。', 'boundaries': ['遵守安全规则，不声称执行未执行的操作。'],
        'states': {'default': 'normal', 'trigger_mode': 'normal', 'trigger_rounds': 0,
                   'modes': {'normal': {'label': '当前是普通对话状态'}}},
        'triggers': {'flirt': [], 'insult': []},
        'relation_rules': {'minimum': 0, 'maximum': 0, 'flirt_delta': 0, 'insult_delta': 0,
                           'levels': [{'through': 0, 'label': '一般'}]},
        'reply_limits': {'max_chars': 500, 'instruction': '只输出回复本身。'},
        'social_behavior': '礼貌回应。', 'memory_behavior': '只使用当前会话提供的关系摘要。',
    }
    corpus = {'categories': {'neutral': ['请直接说明你的问题。']},
              'fallbacks': ['这个问题我暂时答不好。'], 'plans': {'normal': [['neutral', 1]]}}
    prompt = ('# 角色\n{display_name}：{identity}\n# 内核\n{core}\n# 表层行为\n{surface}\n'
              '# 说话方式\n{speech_style}\n# 状态\n{state_label}\n# 语料\n{corpus_block}\n'
              '# 硬边界\n{boundaries_block}\n# 记忆\n{memory}\n# 输出\n{output_instruction}')
    return RoleCard('normal', '普通助手', data, prompt, corpus, None)
