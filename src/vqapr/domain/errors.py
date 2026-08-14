"""실패를 기계가 읽을 수 있게 한다.

첫 사용자가 agent이므로 실패는 **읽는 것이 아니라 파싱하는 것**이어야 한다. 그리고 agent가 자기
준비 과정을 고치려면 문제를 하나씩이 아니라 **한 번에 다** 받아야 한다 — 그래서 예외 하나가
`Failure` 여럿을 담는다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

MAX_EXAMPLES = 5
"""위반 예시 상한. 8.7M행짜리 원천에서 예시가 무한히 실려 나가면 안 된다(PRD §2.6)."""


class FailureFamily(StrEnum):
    """어느 단계의 실패인가. 집합은 미리 닫아둔다 (architecture §8.3)."""

    DATA = "DATA"
    CALENDAR = "CALENDAR"
    INTENT = "INTENT"
    ORDER = "ORDER"
    EXCHANGE = "EXCHANGE"
    ACCOUNT = "ACCOUNT"
    VALUATION = "VALUATION"
    PUBLICATION = "PUBLICATION"


@dataclass(frozen=True, slots=True)
class Failure:
    """충족되지 않은 요구 하나.

    code        점으로 구분된 stage path. 접두사로 분류할 수 있어야 한다
                예: "dataset.register.schema.field_missing"
    requirement 무엇을 요구했나
    observed    실제로 무엇을 봤나. 없으면 None
    examples    위반 예시. MAX_EXAMPLES개로 잘린다
    example_total 잘리기 전 전체 개수. 예시가 전부인지 일부인지 알 수 있어야 한다
    """

    code: str
    requirement: str
    observed: str | None = None
    examples: tuple[str, ...] = ()
    example_total: int = 0

    def __post_init__(self) -> None:
        if not self.code or " " in self.code:
            raise ValueError(f"failure code must be a dotted path without spaces: {self.code!r}")
        if len(self.examples) > MAX_EXAMPLES:
            raise ValueError(
                f"examples must be bounded to {MAX_EXAMPLES}, got {len(self.examples)}"
            )

    @classmethod
    def bounded(
        cls,
        code: str,
        requirement: str,
        *,
        observed: str | None = None,
        examples: Sequence[str] = (),
        example_total: int | None = None,
    ) -> Failure:
        """예시를 상한까지 잘라 만든다. 호출자가 자르는 것을 잊지 않게 하려는 것."""
        kept = tuple(str(e) for e in examples[:MAX_EXAMPLES])
        total = example_total if example_total is not None else len(examples)
        return cls(
            code=code,
            requirement=requirement,
            observed=observed,
            examples=kept,
            example_total=total,
        )


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """한 operation이 끝난 자리에서 모인 결과.

    `failures`가 비어 있으면 통과다. 비어 있지 않으면 `raise_if_failed()`가 던진다.
    """

    stage: str
    family: FailureFamily
    failures: tuple[Failure, ...] = ()
    mutation: bool = False
    retry_precondition: str | None = None

    @property
    def ok(self) -> bool:
        return not self.failures

    def raise_if_failed(self) -> None:
        if self.failures:
            raise VqaprError(
                stage=self.stage,
                family=self.family,
                failures=self.failures,
                mutation=self.mutation,
                retry_precondition=self.retry_precondition,
            )


class VqaprError(Exception):
    """package가 내는 모든 실패의 뿌리.

    `mutation`이 왜 지금부터 있나: 등록에서는 언제나 False라 쓸모없어 보이지만, commit 이후에
    실패할 수 있는 단계가 생겼을 때 뒤늦게 붙이면 그것 없이 짜인 호출부를 전부 고쳐야 한다.
    """

    def __init__(
        self,
        *,
        stage: str,
        family: FailureFamily,
        failures: Sequence[Failure],
        mutation: bool = False,
        retry_precondition: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self.stage = stage
        self.family = family
        self.failures: tuple[Failure, ...] = tuple(failures)
        self.mutation = mutation
        self.retry_precondition = retry_precondition
        self.correlation_id = correlation_id or uuid.uuid4().hex
        super().__init__(self._summary())

    def _summary(self) -> str:
        head = f"{self.family}:{self.stage} — {len(self.failures)} failure(s)"
        return head + "".join(f"\n  [{f.code}] {f.requirement}" for f in self.failures)

    def as_dict(self) -> dict[str, object]:
        """agent가 읽는 형태. 사람이 읽는 것은 `str(err)`."""
        return {
            "stage": self.stage,
            "family": str(self.family),
            "mutation": self.mutation,
            "retry_precondition": self.retry_precondition,
            "correlation_id": self.correlation_id,
            "failures": [
                {
                    "code": f.code,
                    "requirement": f.requirement,
                    "observed": f.observed,
                    "examples": list(f.examples),
                    "example_total": f.example_total,
                }
                for f in self.failures
            ],
        }


@dataclass(frozen=True, slots=True)
class _Collector:
    """단계 안에서 실패를 모은다. 하나 나왔다고 멈추지 않는다."""

    stage: str
    family: FailureFamily
    _found: list[Failure] = field(default_factory=list)

    def add(self, failure: Failure) -> None:
        self._found.append(failure)

    def done(self, *, mutation: bool = False, retry: str | None = None) -> Diagnosis:
        return Diagnosis(
            stage=self.stage,
            family=self.family,
            failures=tuple(self._found),
            mutation=mutation,
            retry_precondition=retry,
        )


def collector(stage: str, family: FailureFamily = FailureFamily.DATA) -> _Collector:
    return _Collector(stage=stage, family=family)
