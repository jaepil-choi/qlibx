"""Temporary forwarding adapter for `vqapr.extension.registration`.

Internal-transition: the implementation now lives in `vqapr._internal.extensions.registration`.
This module re-exports it unchanged so existing `vqapr.extension.registration` imports keep
working exactly as before. It carries no logic of its own and will be deleted when the
internal-transition closes; do not add deprecation warnings, fallbacks, or new behaviour here.

**This module is the only door.** Every caller in `src/` reaches the registration authority through
here rather than through `_internal`. The rule and the deletion's admission conditions are in
`docs/design/agent-first-surface.md`; `tests/boundaries/test_internal_has_one_door.py` enforces the
first. Cited by document rather than by goal id: this note named a goal id until 2026-08-30, and
that id had been reassigned twice by then (`docs/issues/029`).
"""

from __future__ import annotations

from vqapr._internal.extensions.registration import (
    register_constraint,
    register_data_model,
    register_exchange,
    register_strategy_model,
)

__all__ = [
    "register_constraint",
    "register_data_model",
    "register_exchange",
    "register_strategy_model",
]
