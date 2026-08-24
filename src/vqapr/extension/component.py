"""Temporary forwarding adapter for `vqapr.extension.component`.

Internal-transition: the implementation now lives in `vqapr._internal.extensions.component`.
This module re-exports it unchanged so existing `vqapr.extension.component` imports keep working
exactly as before. It carries no logic of its own and will be deleted in G004; do not add
deprecation warnings, fallbacks, or new behaviour here.
"""

from __future__ import annotations

from vqapr._internal.extensions.component import ComponentKind, ComponentRef

__all__ = ["ComponentKind", "ComponentRef"]
