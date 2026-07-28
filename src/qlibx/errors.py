"""Stable errors for agents and users."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class QlibxError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.action = action
        self.context = context or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "action": self.action,
            "context": self.context,
        }


def unknown_name(
    code: str,
    kind: str,
    requested: str,
    available: Iterable[str],
) -> QlibxError:
    """Build the standard 'name is not registered, here is what is' failure.

    Every named-lookup surface in qlibx fails the same shape, so an agent can list the
    alternatives from ``context['available']`` without special-casing the lookup kind.
    """
    options = sorted(available)
    return QlibxError(
        code,
        f"Unknown {kind}: {requested!r}",
        action=f"Choose one of {options}.",
        context={"kind": kind, "requested": requested, "available": options},
    )


__all__ = ["QlibxError", "unknown_name"]
