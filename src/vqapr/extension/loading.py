"""Temporary forwarding adapter for `vqapr.extension.loading`.

Internal-transition: the implementation now lives in `vqapr._internal.extensions.loading`. This
module re-exports it unchanged so existing `vqapr.extension.loading` imports keep working exactly
as before. It carries no logic of its own and will be deleted in G004; do not add deprecation
warnings, fallbacks, or new behaviour here.
"""

from __future__ import annotations

from vqapr._internal.extensions.loading import (
    SHIPPED_EXECUTION_PROFILES,
    accepts_contract_call,
    load_constraint,
    load_data_model,
    load_exchange,
    load_strategy_model,
    positional_arity,
)

__all__ = [
    "SHIPPED_EXECUTION_PROFILES",
    "accepts_contract_call",
    "load_constraint",
    "load_data_model",
    "load_exchange",
    "load_strategy_model",
    "positional_arity",
]
