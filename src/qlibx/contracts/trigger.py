"""Pure schedule-shaped decision trigger contracts."""

import hashlib
import json
from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field, model_validator

from qlibx.data import ComponentRequirement
from qlibx.models import QlibxModel
from qlibx.view import AccessRecord


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("trigger timestamps must be timezone-aware")
    return value


class TriggerContext(QlibxModel):
    """Immutable inputs available to a schedule-shaped trigger evaluation."""

    candidate_time: datetime
    candidate_index: int = Field(ge=0)
    fired_at: tuple[datetime, ...] = ()

    @model_validator(mode="after")
    def validate_history(self) -> "TriggerContext":
        candidate = _require_aware(self.candidate_time)
        fired = tuple(_require_aware(value) for value in self.fired_at)
        if fired != tuple(sorted(set(fired))):
            raise ValueError("trigger FIRE history must be unique and sorted")
        if any(value >= candidate for value in fired):
            raise ValueError("trigger FIRE history must precede the candidate time")
        return self


class TriggerDecision(QlibxModel):
    """One successful FIRE/SKIP evaluation; SKIP is not a failure artifact."""

    policy_id: str = Field(min_length=1)
    decision: Literal["FIRE", "SKIP"]
    candidate_time: datetime
    reason: str = Field(min_length=1)
    accesses: tuple[AccessRecord, ...] = ()

    @model_validator(mode="after")
    def validate_candidate_time(self) -> "TriggerDecision":
        _require_aware(self.candidate_time)
        return self


class TriggerPolicy(Protocol):
    """Pure policy chosen by a Strategy and evaluated by a Flow."""

    policy_id: str

    def requirements(self) -> tuple[ComponentRequirement, ...]: ...

    def evaluate(self, context: TriggerContext) -> TriggerDecision: ...

    def frozen_config_fingerprint(self) -> str: ...


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class EveryCandidate(QlibxModel):
    """Fire on every candidate supplied by the owning Flow."""

    trigger_schema_version: Literal[1] = 1
    policy_id: Literal["every-candidate"] = "every-candidate"

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return ()

    def evaluate(self, context: TriggerContext) -> TriggerDecision:
        return TriggerDecision(
            policy_id=self.policy_id,
            decision="FIRE",
            candidate_time=context.candidate_time,
            reason=f"candidate {context.candidate_index} is enabled by the default policy",
        )

    def frozen_config_fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


class EveryNSessions(QlibxModel):
    """Fire on the first eligible candidate and every ``n`` candidates thereafter."""

    trigger_schema_version: Literal[1] = 1
    policy_id: Literal["every-n-sessions"] = "every-n-sessions"
    n: int = Field(gt=0)

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return ()

    def evaluate(self, context: TriggerContext) -> TriggerDecision:
        next_fire_index = len(context.fired_at) * self.n
        if context.candidate_index > next_fire_index:
            raise ValueError(
                "EveryNSessions candidates must be evaluated sequentially from index zero"
            )
        action: Literal["FIRE", "SKIP"] = (
            "FIRE" if context.candidate_index == next_fire_index else "SKIP"
        )
        return TriggerDecision(
            policy_id=self.policy_id,
            decision=action,
            candidate_time=context.candidate_time,
            reason=(
                f"candidate {context.candidate_index}; next FIRE index {next_fire_index}; "
                f"interval {self.n}"
            ),
        )

    def frozen_config_fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))
