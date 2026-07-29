"""Stable errors for agents and users."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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


def requirement_gap(context: Mapping[str, Any]) -> QlibxError:
    """Build the stable error envelope for one typed requirement resolution."""
    payload = dict(context)
    capability = payload.get("capability", {})
    capability_id = capability.get("id", "unknown")
    missing = list(payload.get("missing_requirements", ()))
    commands = list(payload.get("next_commands", ()))
    action = (
        f"Resolve the requirement gap, then rerun the same capability. Next: {commands[0]}"
        if commands
        else "Resolve the reported requirements, then rerun the same capability."
    )
    return QlibxError(
        "QLIBX_CAPABILITY_REQUIREMENT_GAP",
        f"Capability {capability_id!r} has unsatisfied requirements: {missing}",
        action=action,
        context=payload,
    )


__all__ = ["QlibxError", "requirement_gap", "unknown_name"]
