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


class ExplainTopic(StrEnum):
    """복구 방법을 설명하는 skill 절(節)의 안정된 id. **닫힌 집합**이다.

    실패는 진단이 아니라 지시여야 한다. `fix`가 이번 한 번을 고치는 문장이라면, `explain`은
    "이 부류의 실패는 왜 나며 어떻게 예방하는가"가 적힌 자리를 가리킨다. 그 자리는
    `agent/skill/SKILL.md`이고, 그래서 이 enum은 package와 skill이 **공동 소유**한다.

    id가 자유 문자열이면 skill에 없는 절을 가리키는 오타가 조용히 실려 나간다. 닫아 두면
    양방향으로 검사할 수 있다: 모든 topic이 SKILL.md에 있고, SKILL.md의 모든 topic 절이
    최소 하나의 code에서 참조된다.
    """

    DECLARATION_SHAPE = "declaration-shape"
    """선언 문서의 키·값 모양이 계약과 다르다."""

    DATASET_PREPARATION = "dataset-preparation"
    """등록하려는 parquet 자체가 요구를 만족하지 않는다 — 컬럼, 키, tz, span."""

    SOURCE_ACCESS = "source-access"
    """선언은 옳으나 그 경로를 읽을 수 없다."""

    COMPONENT_CONTRACT = "component-contract"
    """사용자 코드가 framework가 부를 수 있는 모양이 아니다."""

    RUN_PRECONDITION = "run-precondition"
    """실행 전에 갖춰졌어야 할 조건이 없다 — 상장, 체결 가격, 지평."""

    WORKSPACE_STATE = "workspace-state"
    """workspace에 이미 있는 것과 지금 등록하려는 것이 충돌한다."""

    PUBLICATION = "publication"
    """산출물을 쓰는 단계에서 거절됐다."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FailureSource:
    """실패가 가리키는 자리. 포맷된 문자열이 아니라 **구조**다.

    `check`·`show`·skill이 이것을 다시 파싱하지 않고 쓰기 때문이다. "file.yaml:12의 datasets.x"
    같은 한 줄로 실으면 읽는 쪽이 정규식을 짜야 하고, 그 정규식은 문구가 바뀌는 날 조용히
    틀린다.

    셋 다 없을 수 있다: 실패가 파일이 아니라 값에서 났다면 `file`이 없고, 문서 전체에
    해당하면 `key_path`가 없으며, YAML이 줄 번호를 주지 않으면 `line`이 없다. 없는 것을
    지어내는 것보다 없다고 말하는 편이 낫다.
    """

    file: str | None = None
    key_path: str | None = None
    line: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {"file": self.file, "key_path": self.key_path, "line": self.line}


class FailureFamily(StrEnum):
    """어느 단계의 실패인가. 집합은 미리 닫아둔다 (architecture §8.3)."""

    DATA = "DATA"
    INTENT = "INTENT"
    ORDER = "ORDER"
    EXCHANGE = "EXCHANGE"
    ACCOUNT = "ACCOUNT"
    VALUATION = "VALUATION"
    PUBLICATION = "PUBLICATION"


@dataclass(frozen=True, slots=True, kw_only=True)
class Failure:
    """충족되지 않은 요구 하나. **진단이 아니라 지시**다.

    code        점으로 구분된 stage path. 접두사로 분류할 수 있어야 한다
                예: "dataset.register.schema.field_missing"
    source      어느 자리인가 — 파일·키·줄. 포맷된 문자열이 아니라 구조다
    requirement 무엇을 요구했나
    observed    실제로 무엇을 봤나. 없으면 None
    fix         **이번 한 번을 고치는 문장.** 다음에 무엇을 할지가 여기 있다
    explain     이 부류를 설명하는 skill 절의 id. 닫힌 집합에서 온다
    examples    위반 예시. MAX_EXAMPLES개로 잘린다
    example_total 잘리기 전 전체 개수. 예시가 전부인지 일부인지 알 수 있어야 한다

    `kw_only=True`가 붙은 이유는 문법이지 취향이 아니다: `observed`·`examples`·`example_total`이
    기본값을 갖고 있으므로, 기본값 없는 `source`·`fix`·`explain`을 그 뒤에 붙이면 dataclass가
    **클래스 정의 시점에** TypeError를 낸다. 모듈이 아예 import되지 않는다.
    """

    code: str
    requirement: str
    fix: str
    explain: ExplainTopic
    source: FailureSource = FailureSource()
    observed: str | None = None
    examples: tuple[str, ...] = ()
    example_total: int = 0

    def __post_init__(self) -> None:
        if not self.code or " " in self.code:
            raise ValueError(f"failure code must be a dotted path without spaces: {self.code!r}")
        if not self.requirement:
            raise ValueError(f"{self.code}: requirement must say what was required")
        if not self.fix:
            raise ValueError(f"{self.code}: fix must name the next action, not restate the problem")
        if not isinstance(self.explain, ExplainTopic):
            raise TypeError(
                f"{self.code}: explain must be an ExplainTopic, got {type(self.explain).__name__}"
            )
        if not isinstance(self.source, FailureSource):
            raise TypeError(
                f"{self.code}: source must be a FailureSource, got {type(self.source).__name__}"
            )
        if len(self.examples) > MAX_EXAMPLES:
            raise ValueError(
                f"examples must be bounded to {MAX_EXAMPLES}, got {len(self.examples)}"
            )

    def as_dict(self) -> dict[str, object]:
        """The one failure entry every envelope carries, in the one key order.

        `VqaprError.as_dict`, `InputError`, `SimulationFailure` and `check` all emit this entry,
        and each used to write the eight keys out by hand -- six literals that agreed only as
        long as nobody edited one. A reader parses these by name (`SKILL.md`), so the shape is a
        contract, and a contract has one implementation. Anything that renders a failure builds
        a `Failure` and calls this; nothing else spells the keys.
        """
        return {
            "code": self.code,
            "source": self.source.as_dict(),
            "requirement": self.requirement,
            "observed": self.observed,
            "fix": self.fix,
            "explain": str(self.explain),
            "examples": list(self.examples),
            "example_total": self.example_total,
        }

    @classmethod
    def bounded(
        cls,
        code: str,
        requirement: str,
        *,
        fix: str,
        explain: ExplainTopic,
        source: FailureSource | None = None,
        observed: str | None = None,
        examples: Sequence[str] = (),
        example_total: int | None = None,
    ) -> Failure:
        """예시를 상한까지 잘라 만든다. 호출자가 자르는 것을 잊지 않게 하려는 것.

        `code`와 `requirement`만 위치 인자로 남겨 둔 것은 기존 호출부 49곳의 모양을 유지하기
        위해서다. 새로 요구되는 셋은 키워드로만 받는다.
        """
        kept = tuple(str(e) for e in examples[:MAX_EXAMPLES])
        total = example_total if example_total is not None else len(examples)
        return cls(
            code=code,
            requirement=requirement,
            fix=fix,
            explain=explain,
            source=source if source is not None else FailureSource(),
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

    def __reduce__(self) -> tuple[object, ...]:
        """Rebuild through the keyword-only constructor, so the error crosses a process boundary.

        The default pickling of an exception calls `cls(*args)` with the message, which this
        constructor refuses; a `--jobs` worker's refusal then came back to the parent as
        `TypeError: ... takes 1 positional argument` and rendered `stage: "unhandled"` with no
        failures (`docs/issues/073`, closed for strategies by returning an outcome instead; the
        datamodel worker raises, so its exception has to travel as itself -- record `170`).
        """
        return (
            _rebuild_error,
            (
                type(self),
                self.stage,
                self.family,
                self.failures,
                self.mutation,
                self.retry_precondition,
                self.correlation_id,
            ),
        )

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
            "failures": [f.as_dict() for f in self.failures],
        }


def _rebuild_error(
    cls: type[VqaprError],
    stage: str,
    family: FailureFamily,
    failures: tuple[Failure, ...],
    mutation: bool,
    retry_precondition: str | None,
    correlation_id: str,
) -> VqaprError:
    """The unpickling half of `VqaprError.__reduce__`: the same error, same correlation id."""
    return cls(
        stage=stage,
        family=family,
        failures=failures,
        mutation=mutation,
        retry_precondition=retry_precondition,
        correlation_id=correlation_id,
    )


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
