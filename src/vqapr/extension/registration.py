"""Temporary forwarding adapter for `vqapr.extension.registration`.

Internal-transition: the implementation now lives in `vqapr._internal.extensions.registration`.
This module re-exports it unchanged so existing `vqapr.extension.registration` imports keep
working exactly as before. It carries no logic of its own and will be deleted in G004; do not
add deprecation warnings, fallbacks, or new behaviour here.
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
