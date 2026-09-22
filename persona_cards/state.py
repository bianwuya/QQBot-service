"""Role selection and per-scope runtime-state helpers."""
from .engine import trigger_hit


ROLE_SETTING = 'persona_role'


def selection_scope(scope):
    return scope if str(scope).startswith('g:') else '*'


def resolve_role(catalog, store, scope):
    selected = store.get(scope, ROLE_SETTING) if str(scope).startswith('g:') else None
    if not isinstance(selected, str) or selected not in catalog.roles:
        selected = store.get('*', ROLE_SETTING)
    return catalog.get(selected if isinstance(selected, str) else None)


def _state_key(role):
    return 'persona_state' if role.id == 'xiaozayu' else 'persona_state:'+role.id


def _used_key(role):
    return 'persona_used' if role.id == 'xiaozayu' else 'persona_used:'+role.id


def _react_key(role):
    return 'persona_react:'+role.id


def _mood_key(role):
    return 'persona_mood:'+role.id


def _valid_state(role, value):
    if not isinstance(value, dict) or value.get('mode') not in role.states['modes']:
        return {'mode': role.states['default'], 'left': 0}
    return {'mode': value['mode'], 'left': max(0, int(value.get('left', 0)))}


def _valid_mood(value):
    if not isinstance(value, dict) or value.get('vibe') not in ('flustered', 'hurt'):
        return {'vibe': 'calm', 'left': 0}
    left = max(0, min(2, int(value.get('left', 0))))
    if not left:
        return {'vibe': 'calm', 'left': 0}
    return {'vibe': value['vibe'], 'left': left}


def _reacts(store, scope, role):
    value = store.get(scope, _react_key(role))
    return value if isinstance(value, dict) else {}


def load_runtime(store, scope, role, owner=None):
    used = store.get(scope, _used_key(role))
    if not isinstance(used, list):
        used = []
    used = [line for line in used if isinstance(line, str)][-20:]
    if owner is None:
        return _valid_state(role, store.get(scope, _state_key(role))), used
    reacts = _reacts(store, scope, role)
    raw = reacts.get(owner)
    if raw is None and not reacts:
        # One-time migration read source. The legacy key is intentionally left
        # untouched; new turns write the per-owner bucket below.
        raw = store.get(scope, _state_key(role))
    return _valid_state(role, raw), used


def save_runtime(store, scope, role, state, used, owner=None):
    state = _valid_state(role, state)
    store.set(scope, _used_key(role), [line for line in used if isinstance(line, str)][-20:])
    if owner is None:
        store.set(scope, _state_key(role), state)
        return
    reacts = _reacts(store, scope, role)
    reacts[owner] = state
    store.set(scope, _react_key(role), reacts)
    # Compatibility mirror for legacy readers and the pre-P7.1 test surface;
    # authoritative per-owner state lives in persona_react:<role>.
    store.set(scope, _state_key(role), state)


def load_mood(store, scope, role):
    return _valid_mood(store.get(scope, _mood_key(role)))


def mood_line(role, mood):
    mood = _valid_mood(mood)
    if mood['vibe'] == 'flustered':
        return '刚才被人起哄，耳朵还热着——只影响语气，不影响你回答的内容。'
    if mood['vibe'] == 'hurt':
        return '刚才有人越界，群里还沉着一点——只影响语气，不改事实。'
    return ''


def finish_mood(store, scope, role, mood, triggered, intent=None):
    if triggered:
        value = {'vibe': 'flustered', 'left': 2}
    elif intent == 'boundary':
        value = {'vibe': 'hurt', 'left': 1}
    else:
        mood = _valid_mood(mood)
        left = max(0, int(mood.get('left', 0))-1)
        value = {'vibe': mood['vibe'] if left else 'calm', 'left': left}
    store.set(scope, _mood_key(role), value)
    return value


def begin_turn(role, state, text):
    trigger_mode = role.states.get('trigger_mode', role.states['default'])
    rounds = int(role.states.get('trigger_rounds', 0))
    triggered = bool(rounds and trigger_hit(role, 'flirt', text))
    if triggered and trigger_mode in role.states['modes']:
        state = {'mode': trigger_mode, 'left': rounds}
    return state, triggered


def finish_turn(role, state, triggered):
    trigger_mode = role.states.get('trigger_mode', role.states['default'])
    if state.get('mode') == trigger_mode and trigger_mode != role.states['default'] and not triggered:
        left = max(0, int(state.get('left', 0))-1)
        return {'mode': trigger_mode if left else role.states['default'], 'left': left}
    return state
