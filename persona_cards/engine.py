"""Role-independent prompt, trigger, relation and corpus behavior."""
import time


def trigger_hit(role, trigger_name, text):
    text = text or ''
    return next((word for word in role.triggers.get(trigger_name, []) if word in text), None)


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
    if limit <= 80:
        lead = '日常一两句、约30字内；解释技术或安抚情绪最多{}字，先答对再带口吻。'.format(limit)
    else:
        lead = '先答对再带口吻；当前情境最多{}字，复杂问题可分点说明。'.format(limit)
    return lead + base + '。'


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


def ooc_check(role, text):
    return any(word in (text or '') for word in role.data.get('ooc_words', []))


def fallback_line(role, used, intent=None):
    fallbacks = role.corpus['fallbacks']
    if isinstance(fallbacks, dict):
        pool = fallbacks.get(intent) if isinstance(intent, str) else None
        if not pool:
            pool = fallbacks.get('generic') or []
    else:
        pool = fallbacks
    return next((line for line in pool if line not in used), pool[0])


def _pick(role, category, used, count):
    source = role.corpus['categories'].get(category, [])
    pool = [line for line in source if line not in used] or source
    return pool[:count]


def examples_for(role, mode, used, intent=None):
    plans = role.corpus.get('plans', {})
    plan = plans.get(mode) or plans.get(role.states['default']) or []
    intent_plans = role.corpus.get('intent_plans', {})
    intent_plan = intent_plans.get(intent) if isinstance(intent, str) else None
    chosen = []
    for entry in list(plan) + list(intent_plan or []):
        if not isinstance(entry, list) or len(entry) != 2:
            continue
        category, count = entry
        chosen += _pick(role, category, used+chosen, max(0, int(count)))
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
    state_label, corpus_block, chosen = examples_for(role, mode, used)
    memory = '互动次数：{}｜亲密度：{}｜最后见面：{}'.format(
        relation.get('n', 0), relation_level(role, relation.get('a', 0)), relation.get('last') or '初次')
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
        'ooc_words': '／'.join(role.data.get('ooc_words', [])) or '不得跳出角色自述模型身份',
        'memory': memory,
        'social_behavior': role.data['social_behavior'],
        'behavior_block': behavior_block(role, context.get('intent')),
        'memory_behavior': role.data['memory_behavior'],
        'output_instruction': output_instruction(role, context.get('intent')),
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
