"""Failures qlibx reports to the agent layer, and defects it reports to nobody.

PRD section 5.6. The division is the same one section 1.2 sets for capabilities: the core
package reports **what it observed and where**, and the agent layer decides what to do about
it by reading the skill for that stage.

The code names a **stage of the user journey**, not a kind of rule. That is deliberate. "A
value was invalid" is a question the core can answer and the agent cannot use -- it says
nothing about where in a workflow the agent is stuck. "Universe registration refused this"
selects a skill and bounds which repairs are legitimate.

The core does not prescribe a repair, because a repair is rarely unique. A Strategy that
fails on a string-typed column can be fixed by casting inside the Strategy or by
preprocessing and re-registering the dataset; which is right depends on whether that string
is a data defect or an intended column, and the core cannot know. So a public failure
reports ``expected`` -- what the contract required -- and never an instruction.

A failure raised by user code inside a Strategy is passed through, not classified. Deciding
whether someone else's TypeError is "invalid" or "corrupt" is both unanswerable and lossy.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal

Stage = Literal[
    "ONBOARDING",
    "PROJECT",
    "DATA_REGISTRATION",
    "UNIVERSE",
    "STRATEGY_CONTRACT",
    "STRATEGY_RUN",
    "ALPHA",
    "PORTFOLIO",
    "EXECUTION",
    "RESEARCH_RECORD",
    "REPORTING",
]

# What each stage is responsible for. This is where the agent is, not what went wrong there;
# the failure itself carries that. Ordered as the journey runs.
STAGES: Mapping[str, str] = {
    "ONBOARDING": (
        "Preparing the agent: installed documentation, schemas, examples, generated skills "
        "and instruction files."
    ),
    "PROJECT": (
        "Initializing or loading a project, and keeping every configured path inside the "
        "selected project root."
    ),
    "DATA_REGISTRATION": (
        "Inspecting a source read-only and registering it as a logical dataset: keys, "
        "availability, dtypes and the opaque information columns."
    ),
    "UNIVERSE": (
        "Registering the research universe, which every Strategy inherits and which must be "
        "boolean, point-in-time, unique per (available_at, ticker) and complete."
    ),
    "STRATEGY_CONTRACT": (
        "Authoring a Strategy manifest and binding its declared inputs to registered fields."
    ),
    "STRATEGY_RUN": (
        "Running a decision: the point-in-time boundary, the child-context scope, and the "
        "Strategy callable on its bound inputs."
    ),
    "ALPHA": "Applying signal transforms and budget policies to a signed alpha.",
    "PORTFOLIO": "Combining stored alpha and constructing an enhanced index portfolio.",
    "EXECUTION": "Submitting weights into the Qlib order, fill, position and account loop.",
    "RESEARCH_RECORD": (
        "Staging, publishing and reading research records, artifacts and the catalog."
    ),
    "REPORTING": "Analyzing a stored run and rendering a report from it.",
}


class QlibxError(RuntimeError):
    """A failure the agent layer is meant to act on.

    ``expected`` states what the stage's contract required. It is not an instruction: the
    repair belongs to the skill for this stage, because more than one repair is usually
    valid and only the user knows which fits their data.
    """

    def __init__(
        self,
        stage: Stage,
        message: str,
        *,
        expected: str,
        context: dict[str, Any] | None = None,
        requires_user_confirmation: bool = False,
    ) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message
        self.expected = expected
        self.context = context or {}
        self.requires_user_confirmation = requires_user_confirmation

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "message": self.message,
            "expected": self.expected,
            "context": self.context,
            "requires_user_confirmation": self.requires_user_confirmation,
        }


class QlibxInternalError(RuntimeError):
    """An invariant inside qlibx broke. Not part of the agent-facing contract.

    Raise this where the caller could not have caused the failure and cannot repair it: a
    computation disagreeing with itself, a branch that should be unreachable. No stage and
    no ``expected``, on purpose -- there is no step of the journey to send anyone back to.
    """

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}

    def to_dict(self) -> dict[str, Any]:
        return {"internal": True, "message": self.message, "context": self.context}


def unknown_name(stage: Stage, kind: str, requested: str, available: Iterable[str]) -> QlibxError:
    """Build the standard 'name is not registered, here is what is' failure.

    Every named-lookup surface in qlibx fails the same shape, so an agent can list the
    alternatives from ``context['available']`` without special-casing the lookup kind.
    """
    options = sorted(available)
    return QlibxError(
        stage,
        f"Unknown {kind}: {requested!r}",
        expected=f"One of the registered {kind}s: {options}.",
        context={"kind": kind, "requested": requested, "available": options},
    )


def passthrough(stage: Stage, error: BaseException, *, expected: str, **context: Any) -> QlibxError:
    """Report a failure raised by user code without classifying it.

    The original type and text are carried verbatim. Judging whether someone else's
    exception is a data defect, a contract breach or a bug is not something the core can do
    from inside the call, and attempting it discards the one description that was accurate.
    """
    return QlibxError(
        stage,
        f"{type(error).__name__}: {error}",
        expected=expected,
        context={"raised": type(error).__name__, **context},
    )


def requirement_gap(stage: Stage, context: Mapping[str, Any]) -> QlibxError:
    """Build the stable envelope for one typed capability requirement resolution."""
    payload = dict(context)
    capability = payload.get("capability", {})
    capability_id = capability.get("id", "unknown")
    missing = list(payload.get("missing_requirements", ()))
    return QlibxError(
        stage,
        f"Capability {capability_id!r} has unsatisfied requirements: {missing}",
        expected=(
            "Every mandatory requirement resolves to a registered dataset through one of its "
            "declared alternatives."
        ),
        context=payload,
        requires_user_confirmation=True,
    )


__all__ = [
    "STAGES",
    "QlibxError",
    "QlibxInternalError",
    "Stage",
    "passthrough",
    "requirement_gap",
    "unknown_name",
]
