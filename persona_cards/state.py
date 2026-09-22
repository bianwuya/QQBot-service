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


def load_runtime(store, scope, role):
    state = store.get(scope, _state_key(role))
    if not isinstance(state, dict) or state.get('mode') not in role.states['modes']:
        state = {'mode': role.states['default'], 'left': 0}
    else:
        state = {'mode': state['mode'], 'left': max(0, int(state.get('left', 0)))}
    used = store.get(scope, _used_key(role))
    if not isinstance(used, list):
        used = []
    return state, [line for line in used if isinstance(line, str)][-20:]


def save_runtime(store, scope, role, state, used):
    store.set(scope, _state_key(role), state)
    store.set(scope, _used_key(role), [line for line in used if isinstance(line, str)][-20:])


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
