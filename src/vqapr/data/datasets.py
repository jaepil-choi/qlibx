"""의미 — logical dataset 등록과 그 검증.

물리 배치는 `sources.py`가 알고 여기는 **그 값이 무엇인지**를 안다. 등록이 요구하는 것은 여섯
개가 전부이며(PRD §4.1), 그 이상은 그것을 필요로 하는 operation이 호출될 때 요구한다.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from vqapr.data import scan
from vqapr.data.scan import ColumnType
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import Diagnosis, Failure, FailureFamily, collector
from vqapr.domain.identifiers import DatasetId, SourceId, dataset_id, source_id

SCHEMA_STAGE = "dataset.register.schema"
KEY_STAGE = "dataset.register.key"
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
                    f"timezone-aware timestamp"
                ),
                observed=str(actual),
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


def validate(
    registration: DatasetRegistration, spec: SourceSpec
) -> tuple[Diagnosis, ValidationTiming]:
    """선언이 실제 parquet과 맞는지 판정한다.

    **두 단계다.** 값싼 검사를 먼저 전부 모아서 돌려주고, 통과했을 때만 전체 스캔으로 넘어간다.

        1단계  스키마   지목한 컬럼이 존재하나 · available_at이 tz-aware인가
        2단계  key      null 없이 유일한가                          ← 전체 스캔

    한 단계 안에서는 하나 나왔다고 멈추지 않는다. agent는 문제를 한 번에 다 받아야 자기 준비를
    한 번에 고친다. 단계를 가르는 이유는 **순서 의존**이다 — 컬럼이 없으면 유일성을 물을 수 없고,
    없는 컬럼 때문에 전체를 스캔할 이유는 더더욱 없다.
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
            )
        )
        return found.done(retry=_RETRY), ValidationTiming(time.perf_counter() - started, None)

    columns = scan.describe(spec)
    schema = check_schema(registration, columns)
    schema_seconds = time.perf_counter() - started
    if not schema.ok:
        return schema, ValidationTiming(schema_seconds, None)

    key_started = time.perf_counter()
    key = check_key(registration, spec)
    return key, ValidationTiming(schema_seconds, time.perf_counter() - key_started)
