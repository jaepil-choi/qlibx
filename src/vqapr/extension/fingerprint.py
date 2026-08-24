"""Temporary forwarding adapter for `vqapr.extension.fingerprint`.

Internal-transition: the implementation now lives in `vqapr._internal.extensions.fingerprint`.
This module re-exports it unchanged so existing `vqapr.extension.fingerprint` imports keep
working exactly as before. It carries no logic of its own and will be deleted in G004; do not
add deprecation warnings, fallbacks, or new behaviour here.
"""

from __future__ import annotations

from vqapr._internal.extensions.fingerprint import fingerprint_component

__all__ = ["fingerprint_component"]
