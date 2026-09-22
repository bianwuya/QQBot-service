"""Loadable role cards and the shared persona runtime."""
from .engine import (build_prompt, examples_for, fallback_line, ooc_check,
                     relation_level, reply_limit, touch, trigger_hit)
from .intents import INTENTS, classify, serious_marker_hit
from .loader import RoleCard, RoleCardError, RoleCatalog, load_catalog, load_role
from .state import (begin_turn, finish_turn, load_runtime, resolve_role,
                    save_runtime, selection_scope)

__all__ = [
    'INTENTS', 'RoleCard', 'RoleCardError', 'RoleCatalog', 'begin_turn',
    'build_prompt', 'classify', 'examples_for', 'fallback_line', 'finish_turn',
    'load_catalog', 'load_role', 'load_runtime', 'ooc_check', 'relation_level',
    'reply_limit', 'resolve_role', 'save_runtime', 'selection_scope',
    'serious_marker_hit', 'touch', 'trigger_hit',
]
