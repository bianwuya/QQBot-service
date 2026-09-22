"""Compatibility facade for the validated, data-driven role-card system."""
from pathlib import Path

from persona_cards import (RoleCard, begin_turn as _begin_turn,
                           build_prompt as _build_prompt,
                           examples_for as _examples_for,
                           fallback_line as _fallback_line,
                           finish_turn as _finish_turn, load_catalog,
                           load_runtime as _load_runtime,
                           ooc_check as _ooc_check,
                           relation_level as _relation_level,
                           reply_limit as _reply_limit,
                           resolve_role as _resolve_role,
                           save_runtime as _save_runtime,
                           selection_scope, touch as _touch,
                           trigger_hit as _trigger_hit)


ROLE_ROOT = Path(__file__).resolve().parent/'persona_cards'/'roles'
CATALOG = load_catalog(ROLE_ROOT)
DEFAULT_ROLE_ID = CATALOG.default_id
XIAOZAYU = CATALOG.roles.get('xiaozayu', CATALOG.default)

# Legacy exports remain available for existing tests and operational scripts.
CORE = XIAOZAYU.data['core']
SURFACE = XIAOZAYU.data['surface']+' '+XIAOZAYU.data['speech_style']
REACTION_CHAIN = XIAOZAYU.states.get('reaction_chain', '')
CORPUS = XIAOZAYU.corpus['categories']
OOC_WORDS = tuple(XIAOZAYU.data.get('ooc_words', []))
FALLBACKS = list(XIAOZAYU.corpus['fallbacks'])
FLIRT_WORDS = tuple(XIAOZAYU.triggers.get('flirt', []))
INSULT_WORDS = tuple(XIAOZAYU.triggers.get('insult', []))
FR_ROUNDS = int(XIAOZAYU.states.get('trigger_rounds', 0))


def roles():
    return CATALOG.list()


def find_role(value):
    return CATALOG.find(value)


def role_for(store, scope):
    return _resolve_role(CATALOG, store, scope)


def role_selection_scope(scope):
    return selection_scope(scope)


def flirt_hit(text, role=None):
    return _trigger_hit(role or XIAOZAYU, 'flirt', text)


def insult_hit(text, role=None):
    return _trigger_hit(role or XIAOZAYU, 'insult', text)


def ooc_check(text, role=None):
    return _ooc_check(role or XIAOZAYU, text)


def fallback_line(used, role=None):
    return _fallback_line(role or XIAOZAYU, used)


def examples_for(mode, used, role=None):
    return _examples_for(role or XIAOZAYU, mode, used)


def relation_level(affinity, role=None):
    return _relation_level(role or XIAOZAYU, affinity)


def touch(store, scope, owner, text, role=None):
    return _touch(role or XIAOZAYU, store, scope, owner, text)


def build_prompt(role, state, relation, context=None):
    """New signature: build_prompt(role, state, relation, context).

    The previous build_prompt(mode, relation, used) form remains supported.
    """
    if isinstance(role, RoleCard):
        return _build_prompt(role, state, relation, context or {})
    legacy_mode = role
    legacy_relation = state
    legacy_used = relation
    return _build_prompt(XIAOZAYU, {'mode': legacy_mode, 'left': 0},
                         legacy_relation, {'used': legacy_used})


def load_runtime(store, scope, role):
    return _load_runtime(store, scope, role)


def save_runtime(store, scope, role, state, used):
    return _save_runtime(store, scope, role, state, used)


def begin_turn(role, state, text):
    return _begin_turn(role, state, text)


def finish_turn(role, state, triggered):
    return _finish_turn(role, state, triggered)


def reply_limit(role):
    return _reply_limit(role)
