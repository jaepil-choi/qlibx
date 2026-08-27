"""의미 — logical dataset 등록과 그 검증.

물리 배치는 `sources.py`가 알고 여기는 **그 값이 무엇인지**를 안다. 등록이 요구하는 것은 여섯
개가 전부이며(PRD §4.1), 그 이상은 그것을 필요로 하는 operation이 호출될 때 요구한다.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from vqapr.data import scan
from vqapr.data.scan import ColumnType
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import (
    Diagnosis,
    ExplainTopic,
    Failure,
    FailureFamily,
    FailureSource,
    collector,
)
from vqapr.domain.identifiers import DatasetId, SourceId, dataset_id, source_id

SCHEMA_STAGE = "dataset.register.schema"
KEY_STAGE = "dataset.register.key"
SPAN_STAGE = "dataset.register.span"
_RETRY = "fix the prepared dataset, then register again"


@dataclass(frozen=True, slots=True)
class DatasetRegistration:
    """소비자가 `dataset_id`와 framework 이름으로 읽게 만드는 선언.

    instrument_field · available_at · key_fields 는 **물리 컬럼 이름**이고,
    `fields`만 framework 이름 → 물리 위치 매핑이다.

    `available_at`은 컬럼 이름이지 규칙이 아니다. user가 준비 단계에서 계산해 넣은 값이며
    (PRD §4.0), 우리는 그것이 tz-aware인지만 본다.
    """

    dataset_id: DatasetId
    source: SourceId
    instrument_field: str
    available_at: str
    key_fields: tuple[str, ...]
    fields: Mapping[str, str]
    span: tuple[datetime, datetime] | None = None
    """첫 · 마지막 `available_at`. **선언이 아니라 측정값**이다.

    author가 쓰는 값이 아니다. `validate`가 등록 중에 재어 `with_span`으로 붙인다 -- author가
    선언했다면 그것은 파일이 실제로 담은 것과 어긋날 수 있는 두 번째 사실이 된다.

    공짜는 아니다. 7.5M행 원천에서 span 집계는 key 스캔 0.209s에 0.055s를 더했다(약 1/4).
    그 값으로 사는 것은 **이후의 모든 조회**다: 저장해 두면 `Workspace.span`이 파일을 열지
    않고 답한다.

    `None`은 아직 재지 않았다는 뜻이며, workspace에 그대로 저장되는 일은 없다:
    `register_dataset`이 잰 것만 받는다. 둘 다 tz-aware여야 한다 -- naive endpoint는 어느
    venue의 시각인지 말하지 않으므로 다른 dataset의 span과 비교할 수 없다.
    """

    @classmethod
    def of(
        cls,
        raw_dataset_id: str,
        raw_source_id: str,
        *,
        instrument_field: str,
        available_at: str,
        key_fields: Sequence[str],
        fields: Mapping[str, str],
    ) -> DatasetRegistration:
        if not key_fields:
            raise ValueError("key_fields must declare at least one column")
        if not fields:
            raise ValueError("fields must select at least one column to expose")
        for name in fields:
            if not name or any(c.isspace() for c in name):
                raise ValueError(f"framework field name must not contain whitespace: {name!r}")
        return cls(
            dataset_id=dataset_id(raw_dataset_id),
            source=source_id(raw_source_id),
            instrument_field=instrument_field,
            available_at=available_at,
            key_fields=tuple(key_fields),
            fields=dict(fields),
        )

    def with_span(self, first: datetime, last: datetime) -> DatasetRegistration:
        """측정된 span을 붙인 사본. 재는 쪽은 `validate`, 쓰는 쪽은 `register_dataset`이다."""
        for endpoint, role in ((first, "first"), (last, "last")):
            if not isinstance(endpoint, datetime):
                raise TypeError(f"span {role} must be a datetime; got {type(endpoint).__name__}")
            if endpoint.tzinfo is None or endpoint.utcoffset() is None:
                raise ValueError(f"span {role} must be timezone-aware")
        if last < first:
            raise ValueError("span must be ordered: last must not precede first")
        return replace(self, span=(first, last))

    def declared_columns(self) -> dict[str, str]:
        """물리 컬럼 이름 → 그것이 어떤 역할로 지목되었는가. 진단 메시지에 쓴다."""
        roles: dict[str, str] = {}
        roles.setdefault(self.instrument_field, "instrument_field")
        roles.setdefault(self.available_at, "available_at")
        for column in self.key_fields:
            roles.setdefault(column, "key_fields")
        for framework_name, column in self.fields.items():
            roles.setdefault(column, f"fields[{framework_name}]")
        return roles


def check_schema(registration: DatasetRegistration, columns: Mapping[str, ColumnType]) -> Diagnosis:
    """1단계 — 지목한 컬럼이 존재하나, available_at이 tz-aware인가.

    I/O가 없다. `describe()`가 준 스키마만 본다. **하나 나왔다고 멈추지 않는다.**
    """
    found = collector(SCHEMA_STAGE, FailureFamily.DATA)
    observed = ", ".join(sorted(columns)) or "(no columns)"

    for column, role in registration.declared_columns().items():
        if column not in columns:
            found.add(
                Failure.bounded(
                    code=f"{SCHEMA_STAGE}.field_missing",
                    requirement=f"{role} declares column {column!r}, which must exist",
                    observed=observed,
                    source=FailureSource(key_path=f"datasets.{registration.dataset_id}.{role}"),
                    fix=(
                        f"add column {column!r} to the prepared source, or point {role} at a "
                        "column it already has"
                    ),
                    explain=ExplainTopic.DATASET_PREPARATION,
                )
            )

    actual = columns.get(registration.available_at)
    if actual is not None and actual is not ColumnType.TIMESTAMP_TZ:
        suffix = "not_tz" if actual is ColumnType.TIMESTAMP_NAIVE else "not_a_timestamp"
        found.add(
            Failure.bounded(
                code=f"{SCHEMA_STAGE}.available_at_{suffix}",
                requirement=(
                    f"available_at column {registration.available_at!r} must be a "
                    f"timezone-aware timestamp. Localize it while preparing the source, at the "
                    f"instant the row became knowable: a daily close is available at that "
                    f"session's close in the venue's timezone, not at midnight. Registration "
                    f"does not convert it, because only you know which instant the value means"
                ),
                observed=str(actual),
                source=FailureSource(
                    key_path=f"datasets.{registration.dataset_id}.available_at"
                ),
                fix=(
                    f"localize {registration.available_at!r} to the venue timezone while "
                    "preparing the source, then register again"
                ),
                explain=ExplainTopic.DATASET_PREPARATION,
            )
        )
    return found.done(retry=_RETRY)


def check_key(registration: DatasetRegistration, spec: SourceSpec) -> Diagnosis:
    """2단계 — logical key가 null 없이 유일한가. 전체 스캔이다."""
    found = collector(KEY_STAGE, FailureFamily.DATA)
    result = scan.key_check(spec, registration.key_fields)
    declared = ", ".join(registration.key_fields)
    if result.null_groups:
        found.add(
            Failure.bounded(
                code=f"{KEY_STAGE}.null",
                requirement=f"logical key ({declared}) must not contain nulls",
                observed=f"{result.null_groups} key group(s) with a null",
                examples=result.null_examples,
                example_total=result.null_groups,
                source=FailureSource(file=str(spec.path), key_path="key_fields"),
                fix=(
                    f"drop or repair the rows whose ({declared}) is null, or declare a key "
                    "whose columns are always present"
                ),
                explain=ExplainTopic.DATASET_PREPARATION,
            )
        )
    if result.duplicate_groups:
        found.add(
            Failure.bounded(
                code=f"{KEY_STAGE}.duplicate",
                requirement=f"logical key ({declared}) must be unique",
                observed=f"{result.duplicate_groups} duplicated key group(s)",
                examples=result.duplicate_examples,
                example_total=result.duplicate_groups,
                source=FailureSource(file=str(spec.path), key_path="key_fields"),
                fix=(
                    f"deduplicate the source on ({declared}), or widen the key until it "
                    "identifies one row"
                ),
                explain=ExplainTopic.DATASET_PREPARATION,
            )
        )
    return found.done(retry=_RETRY)


@dataclass(frozen=True, slots=True)
class ValidationTiming:
    """어느 단계가 실제로 돌았는지. 2단계가 건너뛰어졌는지 보이게 한다."""

    schema_seconds: float
    key_seconds: float | None

    @property
    def key_was_skipped(self) -> bool:
        return self.key_seconds is None


def check_span(
    registration: DatasetRegistration, spec: SourceSpec
) -> tuple[Diagnosis, tuple[datetime, datetime] | None]:
    """3단계 — dataset이 실제로 덮는 구간을 잰다. key 스캔과 같은 자리에서 한 번.

    재는 것이지 선언을 검사하는 것이 아니다. 그래서 실패는 하나뿐이다: 잴 행이 없는 경우
    (`span.empty`). 빈 dataset의 span은 존재하지 않으므로, 나중에 조용히 틀린 답을 주느니
    지금 거절한다.
    """
    found = collector(SPAN_STAGE, FailureFamily.DATA)
    measured = scan.span_check(spec, registration.available_at)

    if measured.rows == 0:
        found.add(
            Failure.bounded(
                code=f"{SPAN_STAGE}.empty",
                requirement="a registered dataset must carry at least one row to have a span",
                observed=f"{spec.source_id} resolved to 0 rows",
                source=FailureSource(file=str(spec.path)),
                fix="prepare the source with at least one row, then register again",
                explain=ExplainTopic.DATASET_PREPARATION,
            )
        )
        return found.done(retry=_RETRY), None

    if not measured.measured:
        found.add(
            Failure.bounded(
                code=f"{SPAN_STAGE}.empty",
                requirement=(
                    f"available_at column {registration.available_at!r} must carry a value on "
                    "at least one row, so the dataset can say when it begins and ends"
                ),
                observed=f"{measured.rows} row(s), every available_at null",
                source=FailureSource(file=str(spec.path), key_path="available_at"),
                fix=(
                    f"fill {registration.available_at!r} while preparing the source; a row "
                    "nobody can date cannot be read point-in-time"
                ),
                explain=ExplainTopic.DATASET_PREPARATION,
            )
        )
        return found.done(retry=_RETRY), None

    # tz-awareness is not re-checked here, and deliberately so. Stage 1 already refused a
    # non-TIMESTAMP_TZ `available_at` (`check_schema`), and min/max cannot change a column's
    # type, so a naive endpoint is unreachable by construction rather than merely unlikely. A
    # second refusal for it would be a code no fixture could ever produce -- the kind of branch
    # that looks like coverage and is really dead. `with_span` still enforces the invariant at
    # the boundary, which is where a caller bypassing validation would hit it.
    for endpoint in (measured.first, measured.last):
        assert endpoint.tzinfo is not None and endpoint.utcoffset() is not None, (
            f"stage 1 admitted a non-tz-aware {registration.available_at!r}"
        )
    return found.done(), (measured.first, measured.last)


def validate(
    registration: DatasetRegistration, spec: SourceSpec
) -> tuple[Diagnosis, ValidationTiming, DatasetRegistration]:
    """선언이 실제 parquet과 맞는지 판정하고, 통과하면 잰 span을 붙여 돌려준다.

    **세 단계다.** 값싼 검사를 먼저 전부 모아서 돌려주고, 통과했을 때만 전체 스캔으로 넘어간다.

        1단계  스키마   지목한 컬럼이 존재하나 · available_at이 tz-aware인가
        2단계  key      null 없이 유일한가                          ← 전체 스캔
        3단계  span     실제로 덮는 구간은 어디인가                 ← 전체 스캔

    한 단계 안에서는 하나 나왔다고 멈추지 않는다. agent는 문제를 한 번에 다 받아야 자기 준비를
    한 번에 고친다. 단계를 가르는 이유는 **순서 의존**이다 — 컬럼이 없으면 유일성을 물을 수 없고,
    없는 컬럼 때문에 전체를 스캔할 이유는 더더욱 없다.

    세 번째 반환값은 **잰 span이 붙은 등록**이다. 실패했다면 붙일 것이 없으므로 받은 것을 그대로
    돌려준다.
    """
    started = time.perf_counter()
    if registration.source != spec.source_id:
        found = collector(SCHEMA_STAGE, FailureFamily.DATA)
        found.add(
            Failure.bounded(
                code=f"{SCHEMA_STAGE}.source_mismatch",
                requirement="DatasetRegistration.source must match SourceSpec.source_id",
                observed=(
                    f"registration source={registration.source!r}, source spec={spec.source_id!r}"
                ),
                source=FailureSource(
                    key_path=f"datasets.{registration.dataset_id}.source", file=str(spec.path)
                ),
                fix=(
                    f"declare source_id {str(spec.source_id)!r} on the dataset, or pass the "
                    f"SourceSpec whose id is {str(registration.source)!r}"
                ),
                explain=ExplainTopic.DECLARATION_SHAPE,
            )
        )
        return (
            found.done(retry=_RETRY),
            ValidationTiming(time.perf_counter() - started, None),
            registration,
        )

    columns = scan.describe(spec)
    schema = check_schema(registration, columns)
    schema_seconds = time.perf_counter() - started
    if not schema.ok:
        return schema, ValidationTiming(schema_seconds, None), registration

    key_started = time.perf_counter()
    key = check_key(registration, spec)
    if not key.ok:
        key_timing = ValidationTiming(schema_seconds, time.perf_counter() - key_started)
        return key, key_timing, registration

    span, measured = check_span(registration, spec)
    timing = ValidationTiming(schema_seconds, time.perf_counter() - key_started)
    if not span.ok:
        return span, timing, registration
    return span, timing, registration.with_span(*measured)
