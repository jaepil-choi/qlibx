"""The two kinds of failure qlibx can have, and the one it tells an agent about.

A **public** failure is a message to the agent layer. It always says what happened and what
to do next, because an agent that cannot act on a failure cannot recover from it. Its code
names the *kind* of failure -- one of seven -- and everything specific to the occurrence
travels in ``message``, ``action`` and ``context``, written where the check actually ran.

An **internal** failure is a defect in qlibx. It carries no code and no action, because
there is no action: the caller did nothing wrong and can do nothing but stop and report.
Giving it a stable code and a recovery would be a lie, and would pad the agent's vocabulary
with entries it can never act on.

The seven codes are the whole public vocabulary. They are deliberately coarse: nothing in
qlibx branches on a code, so a finer code set only duplicates, in a static table, the
guidance each raise site already writes. That duplication is what previously grew this
vocabulary to 144 names for 126 distinct failures.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal

ErrorCode = Literal[
    "NOT_FOUND",
    "MISSING",
    "INVALID",
    "BOUNDARY",
    "CONFLICT",
    "CORRUPT",
    "UNSUPPORTED",
]

# What a code alone tells a caller, before reading the occurrence. `qlibx errors <code>`
# serves these; everything specific rides on the error itself.
CODE_GUIDANCE: Mapping[str, str] = {
    "NOT_FOUND": (
        "A name is not registered. Read context['available'] and choose from it, or restore "
        "the thing it names. Never substitute something that merely looks similar."
    ),
    "MISSING": (
        "A declaration the operation needs was never made. Declare, register, or bind it and "
        "run the same command again. qlibx supplies no default in its place."
    ),
    "INVALID": (
        "A supplied value breaks a rule the contract declares. Correct the value at its "
        "source rather than working around the check."
    ),
    "BOUNDARY": (
        "Something reached outside a boundary qlibx enforces -- a configured root, the "
        "decision time, or a child's inherited scope. Bring the operation back inside it. "
        "Widening the boundary to admit the data is never the fix."
    ),
    "CONFLICT": (
        "Stored state already holds this identity, or moved while you worked. Re-read the "
        "current state and derive a new identity; never overwrite what is committed."
    ),
    "CORRUPT": (
        "Stored bytes do not match the digest recorded for them. Do not consume the content. "
        "Reproduce it from its declared inputs, then investigate the store."
    ),
    "UNSUPPORTED": (
        "The installed build does not implement this version or format. Use one it supports, "
        "or convert the input outside qlibx with the user's approval."
    ),
}


class QlibxError(RuntimeError):
    """A failure the agent layer is meant to act on.

    ``action`` is required rather than optional. A public failure that cannot say what to do
    next is an internal failure wearing the wrong type.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        action: str,
        context: dict[str, Any] | None = None,
        requires_user_confirmation: bool = False,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.action = action
        self.context = context or {}
        self.requires_user_confirmation = requires_user_confirmation

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "action": self.action,
            "context": self.context,
            "requires_user_confirmation": self.requires_user_confirmation,
        }


class QlibxInternalError(RuntimeError):
    """An invariant inside qlibx broke. Not part of the agent-facing contract.

    Raise this where the caller could not have caused the failure and cannot repair it: a
    computation disagreeing with itself, a branch that should be unreachable. No code and no
    action, on purpose -- the only response is to stop and report the state.
    """

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}

    def to_dict(self) -> dict[str, Any]:
        return {"internal": True, "message": self.message, "context": self.context}


def unknown_name(kind: str, requested: str, available: Iterable[str]) -> QlibxError:
    """Build the standard 'name is not registered, here is what is' failure.

    Every named-lookup surface in qlibx fails the same shape, so an agent can list the
    alternatives from ``context['available']`` without special-casing the lookup kind.
    """
    options = sorted(available)
    return QlibxError(
        "NOT_FOUND",
        f"Unknown {kind}: {requested!r}",
        action=f"Choose one of {options}.",
        context={"kind": kind, "requested": requested, "available": options},
    )


def requirement_gap(context: Mapping[str, Any]) -> QlibxError:
    """Build the stable envelope for one typed capability requirement resolution."""
    payload = dict(context)
    capability = payload.get("capability", {})
    capability_id = capability.get("id", "unknown")
    missing = list(payload.get("missing_requirements", ()))
    commands = list(payload.get("next_commands", ()))
    action = (
        "Read context.missing_requirements and every alternative, explain them to the user, "
        "inspect the named source data, then register or configure the alternative the user "
        "selects and rerun the same capability. Never choose a proxy silently."
    )
    if commands:
        action = f"{action} Next: {commands[0]}"
    return QlibxError(
        "MISSING",
        f"Capability {capability_id!r} has unsatisfied requirements: {missing}",
        action=action,
        context=payload,
        requires_user_confirmation=True,
    )


__all__ = [
    "CODE_GUIDANCE",
    "ErrorCode",
    "QlibxError",
    "QlibxInternalError",
    "requirement_gap",
    "unknown_name",
]
