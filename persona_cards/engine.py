"""Role-independent prompt, trigger, relation and corpus behavior."""
import re
import time


def trigger_hit(role, trigger_name, text):
    text = text or ''
    triggers = getattr(role, 'triggers', None)
    if triggers is None:
        data = getattr(role, 'data', {}) or {}
        triggers = data.get('triggers', {}) if isinstance(data, dict) else {}
    if not isinstance(triggers, dict):
        return None
    for word in triggers.get(trigger_name, []):
        if not isinstance(word, str) or not word or word not in text:
            continue
        if getattr(role, 'id', None) == 'xiaozayu' and trigger_name == 'flirt':
            # Third-person or negated remarks are not praise addressed to her.
            if word in ('喜欢你', '爱你') and re.search(
                    r'(?:不|没|他|她|别人|谁).{0,2}' + re.escape(word), text):
                continue
            if word == '喜欢你' and re.search(r'喜欢你(?:的|写|做|提|这|那)', text):
                continue
        return word
    return None


def limit_for(role, intent=None):
    limits = role.reply_limits
    tiers = limits.get('tiers') if isinstance(limits.get('tiers'), dict) else {}
    if isinstance(intent, str):
        value = tiers.get(intent)
        if isinstance(value, int) and value > 0:
            return value
    value = limits.get('default_max')
    if isinstance(value, int) and value > 0:
        return value
    return int(limits['max_chars'])


def output_instruction(role, intent=None):
    limit = limit_for(role, intent)
    base = str(role.reply_limits['instruction']).rstrip('。')
    leads = role.reply_limits.get('lead')
    template = leads.get('short' if limit <= 80 else 'long') if isinstance(leads, dict) else None
    if isinstance(template, str) and template.count('{}') == 1:
        lead = template.format(limit)
    elif limit <= 80:
        lead = '日常一两句、约30字内；解释技术或安抚情绪最多{}字，先答对再带口吻。'.format(limit)
    else:
        lead = '先答对再带口吻；当前情境最多{}字，复杂问题可分点说明。'.format(limit)
    return lead + base + '；回复严格控制在{}字内，超出的内容会被直接截掉。'.format(limit)


def behavior_block(role, intent=None):
    behaviors = role.data.get('behaviors')
    if not isinstance(behaviors, dict) or not behaviors:
        return role.data['social_behavior']
    current = behaviors.get(intent) or behaviors.get('chat') or role.data['social_behavior']
    order = ('greeting', 'tech_help', 'emotional', 'uncertain', 'correction',
             'clarify', 'identity', 'memory', 'boundary', 'chat', 'flirt', 'insult')
    index = []
    for name in order:
        if name == intent or name not in behaviors:
            continue
        summary = behaviors[name].replace('。', '；').split('；')[0]
        index.append(name+'：'+summary)
    return current + ('\n其他情境索引：' + '；'.join(index) if index else '')


_OOC_KEYS = ('hard', 'service_tone', 'sweet_tone', 'care_tone', 'soft', 'soft_allow')


def _ooc_config(role):
    data = role.data if isinstance(getattr(role, 'data', None), dict) else {}
    config = data.get('ooc')
    if not isinstance(config, dict):
        config = {}
    merged = {}
    for key in _OOC_KEYS:
        values = config.get(key)
        merged[key] = [str(value) for value in values] if isinstance(values, list) else []
    legacy = data.get('ooc_words')
    if isinstance(legacy, list):
        for word in legacy:
            word = str(word)
            if word and word not in merged['hard']:
                merged['hard'].append(word)
    return merged


def _regex_hit(patterns, text):
    for pattern in patterns:
        if not pattern:
            continue
        try:
            if re.search(pattern, text):
                return pattern
        except re.error:
            if pattern in text:
                return pattern
    return None


def ooc_scan(role, text, intent=None):
    text = text or ''
    config = _ooc_config(role)
    for word in config['hard']:
        if word and word in text:
            return {'retry': True, 'soft': False, 'kind': 'hard', 'matched': word}
    service = _regex_hit(config['service_tone'], text)
    if service:
        return {'retry': True, 'soft': False, 'kind': 'service_tone', 'matched': service}
    # Care is intentionally warmer; a role's sugary-voice rules must not
    # discard a genuine supportive answer just for being gentle.
    if intent not in ('emotional', 'boundary'):
        sweet = _regex_hit(config['sweet_tone'], text)
        if sweet:
            return {'retry': True, 'soft': False, 'kind': 'sweet_tone', 'matched': sweet}
    # Decorative hearts are allowed in teasing, never in comfort or in answers to affection.
    if intent in ('emotional', 'flirt'):
        care = _regex_hit(config['care_tone'], text)
        if care:
            return {'retry': True, 'soft': False, 'kind': 'care_tone', 'matched': care}
    soft = next((word for word in config['soft'] if word and word in text), None)
    if soft and not _regex_hit(config['soft_allow'], text):
        return {'retry': False, 'soft': True, 'kind': 'soft', 'matched': soft}
    return {'retry': False, 'soft': False, 'kind': None, 'matched': None}


def ooc_check(role, text, intent=None):
    return bool(ooc_scan(role, text, intent)['retry'])


_HEARTS = '♡♥❤'


def soften_hearts(role, text, recent_replies=()):
    """Heart cooldown: drop decorative hearts when a recent reply in the group already used one."""
    data = role.data if isinstance(getattr(role, 'data', None), dict) else {}
    style = data.get('style') if isinstance(data.get('style'), dict) else {}
    cooldown = style.get('heart_cooldown')
    if not isinstance(cooldown, int) or cooldown < 1 or not isinstance(text, str):
        return text
    if not any(ch in text for ch in _HEARTS):
        return text
    recent = [item for item in (recent_replies or ()) if isinstance(item, str)][-cooldown:]
    if not any(ch in item for item in recent for ch in _HEARTS):
        return text
    cleaned = re.sub('[' + _HEARTS + '\\ufe0f]+', '', text)
    cleaned = re.sub(r'[ \t]+(?=[~～，。！？!?])', '', cleaned)
    cleaned = re.sub(r' {2,}', ' ', cleaned).strip()
    return cleaned or text


def retry_guidance(role):
    data = role.data if isinstance(getattr(role, 'data', None), dict) else {}
    custom = data.get('retry_guidance')
    return custom.strip() if isinstance(custom, str) and custom.strip() else '保持当前角色的行为规则。'


def _opener(text):
    text = re.sub(r'^[\s"“”「」()（）]+', '', str(text or ''))
    match = re.match(r'[^，,。！？!?~～…—\s]{1,3}[？?！!~～]?', text)
    return match.group(0) if match else ''


def style_fatigue_notes(role, recent_replies=(), intent=None):
    """Prompt nudges against monotony: habits over-used in the last few replies and a repeated opening."""
    data = role.data if isinstance(getattr(role, 'data', None), dict) else {}
    style = data.get('style') if isinstance(data.get('style'), dict) else {}
    cfg = style.get('fatigue')
    if not isinstance(cfg, dict):
        return []
    recent_all = [item for item in (recent_replies or ()) if isinstance(item, str)]

    def positive(value, default):
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default

    notes = []
    for item in cfg.get('items', []) if isinstance(cfg.get('items'), list) else []:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ('regex', 'label', 'avoid')):
            continue
        window, hits = positive(item.get('window'), 3), positive(item.get('hits'), 1)
        try:
            used = sum(1 for text in recent_all[-window:] if re.search(item['regex'], text))
        except re.error:
            continue
        if used >= hits:
            notes.append('最近几条回复已经用过{}，{}'.format(item['label'], item['avoid']))
    for item in cfg.get('suggest', []) if isinstance(cfg.get('suggest'), list) else []:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ('regex', 'label', 'text')):
            continue
        if isinstance(item.get('intents'), list) and intent not in item['intents']:
            continue
        try:
            used = any(re.search(item['regex'], text) for text in recent_all[-positive(item.get('window'), 4):])
        except re.error:
            continue
        if not used:
            notes.append('最近几条回复没用过{}，{}'.format(item['label'], item['text']))
    opener_cfg = cfg.get('opener')
    if isinstance(opener_cfg, dict):
        window, hits = positive(opener_cfg.get('window'), 3), positive(opener_cfg.get('hits'), 2)
        recent = recent_all[-window:]
        openers = [_opener(text) for text in recent]
        if len(recent) >= hits:
            for opener in dict.fromkeys(openers):
                if opener and openers.count(opener) >= hits:
                    notes.append('最近几条都以“{}”开头，这条换个开头。'.format(opener))
    return notes


def ooc_prompt_words(role):
    config = _ooc_config(role)
    words = config['hard'] + config['service_tone']
    return '／'.join(words) or '不得跳出角色自述模型身份'


def fallback_line(role, used, intent=None):
    fallbacks = role.corpus['fallbacks']
    if isinstance(fallbacks, dict):
        pool = fallbacks.get(intent) if isinstance(intent, str) else None
        if not pool:
            pool = fallbacks.get('generic') or []
    else:
        pool = fallbacks
    return next((line for line in pool if line not in used), pool[0])


_LEVEL_ORDER = ('mild', 'standard', 'spicy')


def _strength_rank(role, text):
    provenance = role.corpus.get('provenance') if isinstance(role.corpus, dict) else None
    lines = provenance.get('lines') if isinstance(provenance, dict) else None
    info = lines.get(text) if isinstance(lines, dict) else None
    value = info.get('strength') if isinstance(info, dict) else None
    return _LEVEL_ORDER.index(value) if value in _LEVEL_ORDER else 0


def tease_settings(role, level=None):
    """Return (key, label, rule) of the tease level; (None, '', '') for roles without the setting."""
    data = role.data if isinstance(getattr(role, 'data', None), dict) else {}
    tease = data.get('tease')
    levels = tease.get('levels') if isinstance(tease, dict) else None
    if not isinstance(levels, dict) or not levels:
        return None, '', ''
    key = level if level in levels else tease.get('default')
    if key not in levels:
        key = next(iter(levels))
    item = levels[key] if isinstance(levels[key], dict) else {}
    return key, str(item.get('label', key)), str(item.get('rule', ''))


def _rotate(items, shift):
    if not items:
        return items
    shift %= len(items)
    return items[shift:] + items[:shift]


def _pick(role, category, used, count, variation=0, level=None):
    source = role.corpus['categories'].get(category, [])
    pool = [line for line in source if line not in used] or source
    shift = variation if isinstance(variation, int) else 0
    if level in _LEVEL_ORDER:
        # Prefer lines at or below the tease level, then fill up from the stronger ones.
        cap = _LEVEL_ORDER.index(level)
        allowed = [line for line in pool if _strength_rank(role, line) <= cap]
        rest = [line for line in pool if line not in allowed]
        return (_rotate(allowed, shift) + _rotate(rest, shift))[:count]
    return _rotate(pool, shift)[:count]


_TASK_INTENTS = frozenset(('tech_help', 'emotional', 'identity', 'memory',
                           'correction', 'boundary', 'unclear'))


def scenario_categories(role, intent, text):
    """Return corpus categories whose scenario rule matches this chat message.

    Rules live in corpus.json under scenario_rules; task intents never use them,
    so help, comfort, identity and memory prompts keep their fixed exemplars.
    """
    corpus = role.corpus if isinstance(role.corpus, dict) else {}
    config = corpus.get('scenario_rules')
    if not isinstance(config, dict) or intent in _TASK_INTENTS:
        return []
    text = text if isinstance(text, str) else ''
    if not text.strip():
        return []
    allowed = config.get('intents')
    if isinstance(allowed, list) and intent not in allowed:
        return []
    limit = config.get('max_hits', 2)
    limit = limit if isinstance(limit, int) and limit > 0 else 2
    categories = corpus.get('categories', {})
    hits = []
    for rule in config.get('rules') or []:
        if not isinstance(rule, dict):
            continue
        category = rule.get('category')
        if not isinstance(category, str) or category in hits or not categories.get(category):
            continue
        patterns = rule.get('patterns')
        patterns = [item for item in patterns if isinstance(item, str) and item] if isinstance(patterns, list) else []
        rule_intents = rule.get('intents')
        if isinstance(rule_intents, list):
            matched = intent in rule_intents and (not patterns or _regex_hit(patterns, text))
        else:
            matched = bool(patterns) and _regex_hit(patterns, text)
        if matched:
            hits.append(category)
            if len(hits) >= limit:
                break
    return hits


def examples_for(role, mode, used, intent=None, identity_path=None, variation=0, tease_level=None, text=None):
    # Identity probes rely on stable deflect/admit exemplars; keep those fixed.
    if intent == 'identity':
        variation = 0
    plans = role.corpus.get('plans', {})
    plan = plans.get(mode) or plans.get(role.states['default']) or []
    # A generic mood plan used to leak cheerful/bragging examples into every
    # task. Only playful chat/greetings/flirt/insults need those examples.
    if intent in _TASK_INTENTS:
        plan = []
    elif role.id == 'xiaozayu' and intent == 'greeting':
        # A plain hello supplies no premise to attack; do not hallucinate a
        # previous exchange just because the generic chat plan suggests one.
        plan = [['daily', 1]]
    elif mode == role.states.get('trigger_mode') and intent != 'flirt' and role.id == 'xiaozayu':
        # After the actual compliment, keep a trace of embarrassment without
        # feeding the model two more rounds of blush-and-stammer examples.
        plan = [['recover', 1], ['provocation', 1]]
    intent_plans = role.corpus.get('intent_plans', {})
    intent_plan = intent_plans.get(intent) if isinstance(intent, str) else None
    if intent == 'identity' and identity_path in ('deflect', 'admit'):
        category = 'identity_deflect' if identity_path == 'deflect' else 'honest_admit'
        intent_plan = [[category, 2]]
    chosen = []
    # A matching chat scenario (morning greeting, lost gacha pull, thanks...)
    # contributes one exemplar each and takes the place of generic ones, so the
    # prompt keeps the same number of examples.
    scenario = scenario_categories(role, intent, text)
    cap = None
    if scenario:
        budget = sum(max(0, int(entry[1])) for entry in list(plan) + list(intent_plan or [])
                     if isinstance(entry, list) and len(entry) == 2)
        for category in scenario:
            chosen += _pick(role, category, used+chosen, 1, variation+len(chosen) if isinstance(variation,int) else 0, tease_level)
        cap = max(budget, len(chosen))
    for entry in list(plan) + list(intent_plan or []):
        if not isinstance(entry, list) or len(entry) != 2:
            continue
        category, count = entry
        count = max(0, int(count))
        if cap is not None:
            count = min(count, cap-len(chosen))
            if count <= 0:
                continue
        chosen += _pick(role, category, used+chosen, count, variation+len(chosen) if isinstance(variation,int) else 0, tease_level)
    state = role.states.get('modes', {}).get(mode) or role.states['modes'][role.states['default']]
    return state['label'], '\n'.join('· '+line for line in chosen), chosen


def relation_level(role, affinity):
    levels = role.relation_rules.get('levels') or []
    for item in levels:
        if affinity <= int(item.get('through', affinity)):
            return str(item.get('label', '一般'))
    return str(levels[-1].get('label', '一般')) if levels else '一般'


def touch(role, store, scope, owner, text):
    relations = store.get(scope, 'relations') or {}
    if not isinstance(relations, dict):
        relations = {}
    relation = relations.get(owner)
    if not isinstance(relation, dict):
        relation = {'a': 0, 'n': 0, 'last': ''}
    relation = {'a': int(relation.get('a', 0)), 'n': int(relation.get('n', 0)),
                'last': str(relation.get('last', ''))}
    relation['n'] += 1
    relation['last'] = time.strftime('%Y-%m-%d')
    rules = role.relation_rules
    if trigger_hit(role, 'flirt', text):
        relation['a'] = min(int(rules['maximum']), relation['a']+int(rules.get('flirt_delta', 0)))
    elif trigger_hit(role, 'insult', text):
        relation['a'] = max(int(rules['minimum']), relation['a']+int(rules.get('insult_delta', 0)))
    relations[owner] = relation
    store.set(scope, 'relations', relations)
    return relation


def build_prompt(role, state, relation, context):
    context = context if isinstance(context, dict) else {}
    used = context.get('used') if isinstance(context.get('used'), list) else []
    mode = state.get('mode', role.states['default']) if isinstance(state, dict) else role.states['default']
    if mode not in role.states['modes']:
        mode = role.states['default']
    tease_key, _tease_label, tease_rule = tease_settings(role, context.get('tease_level'))
    state_label, corpus_block, chosen = examples_for(
        role, mode, used, context.get('intent'), context.get('identity_path'), context.get('variation_seed', 0), tease_key,
        context.get('text'))
    if (role.id == 'xiaozayu' and mode == role.states.get('trigger_mode')
            and context.get('intent') != 'flirt'):
        recovered = role.states.get('recovered_label')
        state_label = (recovered if isinstance(recovered, str) and recovered.strip() else
                       '刚才失过半拍，现在已收拾好场面：不要再结巴、脸红或撒娇；'
                       '先回应眼前的问题，轻松话题可嘴硬一句。')
    mood_line = str(context.get('mood_line', '')).strip()
    if mood_line:
        state_label += '\n'+mood_line
    for note in style_fatigue_notes(role, context.get('recent_replies'), context.get('intent')):
        state_label += '\n'+note
    count = relation.get('n', 0)
    memory = '互动次数：{}｜亲密度：{}｜最后见面：{}'.format(
        count, relation_level(role, relation.get('a', 0)),
        relation.get('last') if count > 1 and relation.get('last') else '初次')
    values = {
        'display_name': role.display_name,
        'identity': role.data['identity'],
        'core': role.data['core'],
        'surface': role.data['surface'],
        'speech_style': role.data['speech_style'],
        'reaction_chain': role.states.get('reaction_chain', ''),
        'state_label': state_label,
        'corpus_block': corpus_block or '· 保持自然、简洁并贴合角色定义。',
        'boundaries_block': '\n'.join('- '+line for line in role.data['boundaries']),
        'ooc_words': ooc_prompt_words(role),
        'memory': memory,
        'social_behavior': role.data['social_behavior'],
        'behavior_block': behavior_block(role, context.get('intent')),
        'memory_behavior': role.data['memory_behavior'],
        'output_instruction': output_instruction(role, context.get('intent')),
        'tease_rule': tease_rule,
    }
    try:
        prompt = role.prompt.format(**values)
    except (KeyError, ValueError):
        prompt = ('# 角色\n{display_name}：{identity}\n# 内核\n{core}\n# 表层行为\n{surface}\n'
                  '# 状态\n{state_label}\n# 语料\n{corpus_block}\n# 硬边界\n{boundaries_block}\n'
                  '# 记忆\n{memory}\n# 输出\n{output_instruction}').format(**values)
    return prompt, chosen


def reply_limit(role):
    return int(role.reply_limits['max_chars'])
