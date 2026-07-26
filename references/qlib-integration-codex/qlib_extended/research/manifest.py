from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
import json
import math
from typing import Any


RUN_KINDS = frozenset({"atomic", "cohort", "family", "portfolio"})
RESEARCH_TRACKS = frozenset({"trusted", "financial_shadow", "legacy"})
RUN_STATUSES = frozenset({"complete", "failed", "invalid"})


@dataclass(frozen=True)
class MetricValue:
    segment: str
    metric: str
    value: float

    def __post_init__(self) -> None:
        _require_text(self.segment, "metric.segment")
        _require_text(self.metric, "metric.metric")
        if not math.isfinite(float(self.value)):
            raise ValueError("metric.value must be finite.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment": self.segment,
            "metric": self.metric,
            "value": float(self.value),
        }


@dataclass(frozen=True)
class MemberWeight:
    member_run_id: str
    weight: float

    def __post_init__(self) -> None:
        _require_text(self.member_run_id, "member.member_run_id")
        if not math.isfinite(float(self.weight)):
            raise ValueError("member.weight must be finite.")

    def to_dict(self) -> dict[str, Any]:
        return {"member_run_id": self.member_run_id, "weight": float(self.weight)}


@dataclass(frozen=True)
class RunSpec:
    alpha_key: str
    family: str
    run_kind: str
    research_track: str
    order_calendar_key: str
    rebalance_days: int
    status: str
    config_hash: str
    data_fingerprint: str
    attempt: int = 0
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )

    def __post_init__(self) -> None:
        for value, name in (
            (self.alpha_key, "alpha_key"),
            (self.family, "family"),
            (self.order_calendar_key, "order_calendar_key"),
            (self.config_hash, "config_hash"),
            (self.data_fingerprint, "data_fingerprint"),
            (self.created_at, "created_at"),
        ):
            _require_text(value, name)
        if self.run_kind not in RUN_KINDS:
            raise ValueError(f"run_kind must be one of {sorted(RUN_KINDS)}.")
        if self.research_track not in RESEARCH_TRACKS:
            raise ValueError(
                f"research_track must be one of {sorted(RESEARCH_TRACKS)}."
            )
        if self.status not in RUN_STATUSES:
            raise ValueError(f"status must be one of {sorted(RUN_STATUSES)}.")
        if not isinstance(self.rebalance_days, int) or self.rebalance_days < 1:
            raise ValueError("rebalance_days must be a positive integer.")
        if self.research_track in {"trusted", "financial_shadow"} and self.rebalance_days > 63:
            raise ValueError(
                f"{self.research_track} run rebalance_days must not exceed 63."
            )
        if not isinstance(self.attempt, int) or self.attempt < 0:
            raise ValueError("attempt must be a non-negative integer.")
        datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))

    @property
    def run_id(self) -> str:
        payload = self.identity_dict()
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return f"research-{sha256(encoded).hexdigest()[:24]}"

    def identity_dict(self) -> dict[str, Any]:
        return {
            "alpha_key": self.alpha_key,
            "family": self.family,
            "run_kind": self.run_kind,
            "research_track": self.research_track,
            "order_calendar_key": self.order_calendar_key,
            "rebalance_days": self.rebalance_days,
            "config_hash": self.config_hash,
            "data_fingerprint": self.data_fingerprint,
            "attempt": self.attempt,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            **self.identity_dict(),
            "status": self.status,
            "created_at": self.created_at,
        }


def _require_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string.")
    return value
