"""Stable errors for agents and users."""

from __future__ import annotations

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
