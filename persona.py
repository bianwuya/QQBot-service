"""Compatibility facade for the validated, data-driven role-card system."""
from pathlib import Path

from persona_cards import (RoleCard, begin_turn as _begin_turn,
                           build_prompt as _build_prompt,
                           examples_for as _examples_for,
                           fallback_line as _fallback_line,
                           finish_turn as _finish_turn, load_catalog,
                           classify as _classify_intent,
                           serious_marker_hit as _serious_marker_hit,
                           limit_for as _limit_for,
                           finish_mood as _finish_mood,
                           load_mood as _load_mood,
                           load_identity_probe as _load_identity_probe,
                           load_runtime as _load_runtime,
                           mood_line as _mood_line,
                           note_identity_probe as _note_identity_probe,
                           ooc_check as _ooc_check,
                           ooc_scan as _ooc_scan,
                           relation_level as _relation_level,
                           reply_limit as _reply_limit,
                           resolve_role as _resolve_role,
                           retry_guidance as _retry_guidance,
                           save_runtime as _save_runtime,
                           selection_scope, soften_hearts as _soften_hearts,
                           touch as _touch,
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
OOC_WORDS = tuple((XIAOZAYU.data.get('ooc') or {}).get('hard')
                 or XIAOZAYU.data.get('ooc_words', []))
_FALLBACK_SOURCE = XIAOZAYU.corpus['fallbacks']
FALLBACKS = (list(_FALLBACK_SOURCE.get('generic', [])) if isinstance(_FALLBACK_SOURCE, dict)
             else list(_FALLBACK_SOURCE))
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


def classify_intent(role, text):
    return _classify_intent(role, text)


def flirt_hit(text, role=None):
    return _trigger_hit(role or XIAOZAYU, 'flirt', text)


def insult_hit(text, role=None):
    return _trigger_hit(role or XIAOZAYU, 'insult', text)


def ooc_check(text, role=None, intent=None):
    return _ooc_check(role or XIAOZAYU, text, intent)


def ooc_scan(text, role=None, intent=None):
    return _ooc_scan(role or XIAOZAYU, text, intent)


def retry_guidance(role=None):
    return _retry_guidance(role or XIAOZAYU)


def soften_hearts(text, role=None, recent_replies=()):
    return _soften_hearts(role or XIAOZAYU, text, recent_replies)


def fallback_line(used, role=None, intent=None):
    return _fallback_line(role or XIAOZAYU, used, intent)


def examples_for(mode, used, role=None, intent=None):
    return _examples_for(role or XIAOZAYU, mode, used, intent)


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


def load_runtime(store, scope, role, owner=None):
    return _load_runtime(store, scope, role, owner)


def save_runtime(store, scope, role, state, used, owner=None):
    return _save_runtime(store, scope, role, state, used, owner)


def begin_turn(role, state, text):
    return _begin_turn(role, state, text)


def finish_turn(role, state, triggered):
    return _finish_turn(role, state, triggered)


def load_mood(store, scope, role):
    return _load_mood(store, scope, role)


def mood_line(role, mood):
    return _mood_line(role, mood)


def finish_mood(store, scope, role, mood, triggered, intent=None):
    return _finish_mood(store, scope, role, mood, triggered, intent)


def reply_limit(role, intent=None):
    return _limit_for(role, intent) if intent is not None else _reply_limit(role)

def serious_marker_hit(role, text):
    return _serious_marker_hit(role, text)


def identity_probe(store, scope, owner):
    return _load_identity_probe(store, scope, owner)


def note_identity_probe(store, scope, owner):
    return _note_identity_probe(store, scope, owner)

