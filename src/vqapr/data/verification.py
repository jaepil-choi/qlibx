"""The one door a physical read is measured at, and the one check every later read makes.

**A file is measured once, where it enters the workspace; every later reader verifies identity,
not content.** Until record `234` (`docs/issues/095`) validation lived in three modules with three
shapes -- `data/datasets.py::validate` for a dataset, `exchange/execution_table.py::
validate_execution_table` for the same table again at preflight and at run, and a bare
`read_roster_table` that raised -- and the execution table was scanned four times for facts
registration had already established. This module is the whole of it:

    verify_source(registration, spec)   measure a source: schema, key, span, values, execution
                                        prices, digest. Registration keeps what it measured.
    require_verified(registration, spec) the later reader's check: was it measured, and are these
                                        the bytes it measured. A digest compare, no scan.
    verify_roster(tables)               the instrument roster, read through the same door.

The stages are the ones `datasets.py` held, moved here whole; what changed is that the execution
role's facts are measured here too, for every candidate price at once, so the run's choice of
price is judged against a stored fact rather than a fresh scan (`run/preflight/facts.py::
bound_execution_table`). `tests/boundaries/test_physical_reads_pass_one_door.py` holds the door:
no module outside this one calls the scan's check kernels.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vqapr.data import scan
from vqapr.data.dataset import DatasetRegistration, Grain, execution_price_fields
from vqapr.data.scan import ColumnType
from vqapr.data.source import SourceSpec, physical_digest
from vqapr.domain.errors import (
    Diagnosis,
    Failure,
    FailureSource,
    Stage,
    Status,
    VqaprError,
    collector,
)
from vqapr.domain.instrument import INSTRUMENT_ID_FIELD, KIND_FIELD

_RETRY = "fix the prepared dataset, then register again"


def execution_role_failures(
    registration: DatasetRegistration, columns: Mapping[str, ColumnType]
) -> tuple[Failure, ...]:
    """What an execution table must additionally satisfy: a boolean tradable flag, a VARCHAR
    instrument column, and at least one numeric field a run could bind as its trade price."""
    role = registration.execution
    if role is None:
        return ()
    failures: list[Failure] = []
    tradable_column = registration.fields[role.is_tradable].strip()
    observed = columns.get(tradable_column)
    if observed is not ColumnType.BOOLEAN:
        failures.append(
            Failure.bounded(
                code="dataset.execution_tradable_not_boolean",
                status=Status.INVALID,
                requirement=(
                    f"execution.is_tradable field {role.is_tradable!r} (column "
                    f"{tradable_column!r}) must be BOOLEAN"
                ),
                observed="missing" if observed is None else str(observed),
                source=FailureSource(
                    key_path=f"datasets.{registration.dataset_id}.execution.is_tradable"
                ),
                fix=(
                    f"make column {tradable_column!r} a boolean in the prepared source, or point "
                    "execution.is_tradable at a boolean field"
                ),
            )
        )
    instrument = registration.instrument_field
    if instrument is not None and columns.get(instrument) is not ColumnType.VARCHAR:
        # The venue reads the instrument column by name at the fill instant; a non-text column
        # would compare ids to numbers. Moved here from the execution table's own schema check
        # (record `234`), which ran the same question again at preflight.
        seen = columns.get(instrument)
        failures.append(
            Failure.bounded(
                code="dataset.execution_instrument_not_text",
                status=Status.INVALID,
                requirement=(
                    f"an execution table's instrument_field {instrument!r} must be VARCHAR"
                ),
                observed="missing" if seen is None else str(seen),
                source=FailureSource(
                    key_path=f"datasets.{registration.dataset_id}.instrument_field"
                ),
                fix=f"store {instrument!r} as text in the prepared source, then register again",
            )
        )
    if not execution_price_fields(registration):
        failures.append(
            Failure.bounded(
                code="dataset.execution_no_price",
                status=Status.INVALID,
                requirement=(
                    "an execution table must expose at least one numeric field a run can bind "
                    "as its trade_price"
                ),
                observed=", ".join(
                    f"{name}: {type_.value}"
                    for name, type_ in sorted((registration.field_types or {}).items())
                )
                or "(no fields typed)",
                source=FailureSource(key_path=f"datasets.{registration.dataset_id}.fields"),
                fix=(
                    "declare the venue's price columns as DOUBLE or INTEGER fields of this dataset"
                ),
            )
        )
    return tuple(failures)


def check_schema(
    registration: DatasetRegistration,
    columns: Mapping[str, ColumnType],
    spec: SourceSpec,
) -> tuple[Diagnosis, scan.ProjectionSchema | None]:
    """1단계 — 지목한 컬럼이 존재하나, projection이 bind되나, 그 타입을 model에 건넬 수 있나.

    **하나 나왔다고 멈추지 않는다.** 다만 뒤의 두 검사는 앞이 통과했을 때만 돈다: 지목한
    컬럼이 없으면 binder도 그 컬럼을 못 찾았다고 말할 뿐이고, 같은 사실을 duckdb의 말로 한 번
    더 적는 것은 진단을 늘리는 게 아니라 흐리는 것이다.

    노출되는 **field의 타입까지** 여기서 본다. 읽기 경로가 셀마다 타입을 되묻던 시절에는 그
    질문이 조회 시각에 답해졌지만, 이제 답하는 자리는 여기다 (`044`). field가 표현식이 된
    뒤로 그 타입은 원천 컬럼의 성질이 아니라 **합성된 projection의 성질**이므로, 잴 때 물어볼
    상대는 스키마가 아니라 `DESCRIBE`다 (`049`). 그리고 잰 것은 **author의 선언과 대조된다**
    (`088`): naive timestamp · scalar 아님 · DECIMAL은 각자 이름으로, 그 밖의 불일치는
    `field_type_mismatch`로 거부한다. 논거는 그대로다 -- 한 컬럼에 대해 참이면 그 컬럼의
    **모든** 행에 대해 참이다.

    두 번째 반환값은 **잰 projection 스키마**다(grouping 판정이 여기서 나온다). 무엇이든
    실패했다면 붙일 것이 없으므로 `None`이다.
    """
    found = collector(Stage.REGISTER)
    observed = ", ".join(sorted(columns)) or "(no columns)"
    identity_ok = True

    for column, role in registration.declared_columns().items():
        if column not in columns:
            identity_ok = False
            found.add(
                Failure.bounded(
                    code="dataset.field_missing",
                    status=Status.INVALID,
                    requirement=f"{role} declares column {column!r}, which must exist",
                    observed=observed,
                    source=FailureSource(key_path=f"datasets.{registration.dataset_id}.{role}"),
                    fix=(
                        f"add column {column!r} to the prepared source, or point {role} at a "
                        "column it already has"
                    ),
                )
            )

    actual = columns.get(registration.available_at)
    if actual is not None and actual is not ColumnType.TIMESTAMP_TZ:
        identity_ok = False
        suffix = "not_tz" if actual is ColumnType.TIMESTAMP_NAIVE else "not_a_timestamp"
        found.add(
            Failure.bounded(
                code=f"dataset.available_at_{suffix}",
                status=Status.INVALID,
                requirement=(
                    f"available_at column {registration.available_at!r} must be a "
                    f"timezone-aware timestamp. Localize it while preparing the source, at the "
                    f"instant the row became knowable: a daily close is available at that "
                    f"session's close in the venue's timezone, not at midnight. Registration "
                    f"does not convert it, because only you know which instant the value means"
                ),
                observed=str(actual),
                source=FailureSource(key_path=f"datasets.{registration.dataset_id}.available_at"),
                fix=(
                    f"localize {registration.available_at!r} to the venue timezone while "
                    "preparing the source, then register again"
                ),
            )
        )

    for name, expression in registration.fields.items():
        keyword = scan.statement_keyword(expression)
        if keyword is None:
            continue
        identity_ok = False
        found.add(
            Failure.bounded(
                code="dataset.field_not_an_expression",
                status=Status.INVALID,
                requirement=(
                    f"field {name!r} must be a value expression, not a statement. An expression "
                    "is evaluated within one instant, which is what makes it impossible to write "
                    "a look-ahead here; a subquery carries its own FROM and can read rows the "
                    "window excludes. A field that needs a join or a subquery is a DataModel"
                ),
                observed=f"{name} = {expression!r} contains {keyword}",
                source=FailureSource(key_path=f"datasets.{registration.dataset_id}.fields.{name}"),
                fix=(
                    f"express {name!r} over this source's own columns, or compute it in a "
                    "DataModel where reading across instants is declared"
                ),
            )
        )

    if not identity_ok:
        return found.done(retry=_RETRY), None

    projection = scan.describe_projection(
        spec,
        instrument_field=registration.instrument_field,
        available_at_field=registration.available_at,
        fields=registration.fields,
    )
    if not projection.ok:
        found.add(
            Failure.bounded(
                code="dataset.projection_unbindable",
                status=Status.INVALID,
                requirement=(
                    "every declared field must be an expression this source can evaluate, and "
                    "the whole set must be one shape: either every field is row-wise, or every "
                    "field aggregates the rows an instant holds. A registration that mixes the "
                    "two has no grain"
                ),
                observed="; ".join(
                    f"{shape}: {message}"
                    for shape, message in zip(
                        ("row-wise", "grouped"), projection.errors, strict=False
                    )
                ),
                source=FailureSource(
                    file=str(spec.path), key_path=f"datasets.{registration.dataset_id}.fields"
                ),
                fix=(
                    "fix the expression the message names, or wrap the row-wise fields in an "
                    "aggregate so the whole projection groups"
                ),
            )
        )
        return found.done(retry=_RETRY), None

    typed_ok = True
    declared_types = registration.field_types or {}
    for name, exposed in projection.field_types.items():
        expression = registration.fields[name]
        spelled = projection.observed.get(name, str(exposed))
        if exposed is ColumnType.DECIMAL:
            typed_ok = False
            found.add(
                Failure.bounded(
                    code="dataset.field_decimal",
                    status=Status.INVALID,
                    requirement=(
                        f"field {name!r} evaluates {expression!r}, which must not be a DECIMAL. "
                        f"A model does arithmetic in one numeric type, and a DECIMAL column "
                        f"reaches it as `Decimal` while a DOUBLE one reaches it as `float`; "
                        f"exact arithmetic belongs on the money side of the execution boundary, "
                        f"not in the data. Declarable types: {scan.DECLARABLE_FIELD_TYPE_NAMES}"
                    ),
                    observed=spelled,
                    source=FailureSource(
                        key_path=f"datasets.{registration.dataset_id}.fields.{name}",
                    ),
                    fix=(
                        f"cast {name!r} to DOUBLE (or INTEGER) while preparing the source, then "
                        f"register again"
                    ),
                )
            )
        elif exposed is ColumnType.TIMESTAMP_NAIVE:
            typed_ok = False
            found.add(
                Failure.bounded(
                    code="dataset.field_not_tz",
                    status=Status.INVALID,
                    requirement=(
                        f"field {name!r} evaluates {expression!r}, whose timestamps must be "
                        f"timezone-aware. A naive timestamp reaches a model as an instant nobody "
                        f"can place on a venue's clock, and it compares silently wrong against "
                        f"every value that can"
                    ),
                    observed=str(exposed),
                    source=FailureSource(
                        key_path=f"datasets.{registration.dataset_id}.fields.{name}",
                    ),
                    fix=(
                        f"localize what {name!r} reads to the venue timezone while preparing the "
                        f"source, or stop exposing it as a field"
                    ),
                )
            )
        elif exposed is ColumnType.OTHER:
            typed_ok = False
            found.add(
                Failure.bounded(
                    code="dataset.field_not_portable",
                    status=Status.INVALID,
                    requirement=(
                        f"field {name!r} evaluates {expression!r}, which must produce a portable "
                        f"scalar -- a boolean, number, string, date or timestamp. A model "
                        f"receives rows of scalars, and there is nothing portable to hand it for "
                        f"this type"
                    ),
                    observed=str(exposed),
                    source=FailureSource(
                        key_path=f"datasets.{registration.dataset_id}.fields.{name}",
                    ),
                    fix=(
                        f"flatten what {name!r} reads into scalar columns while preparing the "
                        f"source, or stop exposing it as a field"
                    ),
                )
            )
        elif name in declared_types and exposed is not declared_types[name]:
            # The declaration and the file disagree, and neither is inferred: the author wrote
            # both (`docs/issues/088`). Which one is wrong is theirs to decide, so the refusal
            # quotes both and names both fixes.
            typed_ok = False
            declared = declared_types[name]
            found.add(
                Failure.bounded(
                    code="dataset.field_type_mismatch",
                    status=Status.INVALID,
                    requirement=(
                        f"field {name!r} is declared {declared.value}, so {expression!r} must "
                        f"evaluate to a {declared.value} on the source"
                    ),
                    observed=f"{spelled} (class {exposed.value})",
                    source=FailureSource(
                        file=str(spec.path),
                        key_path=f"datasets.{registration.dataset_id}.field_types.{name}",
                    ),
                    fix=(
                        f"cast {name!r} to {declared.value} while preparing the source, or "
                        f"declare field_types.{name}: {exposed.value} if the file is right"
                    ),
                )
            )

    return found.done(retry=_RETRY), (projection if typed_ok else None)


def check_key(registration: DatasetRegistration, spec: SourceSpec) -> Diagnosis:
    """2단계 — 선언한 grain의 축이 null 없이 유일한가. 전체 스캔이다.

    The axis is the grain's (`key_axis`), not the author's `key_fields` alone: `instrument_instant`
    proves `(available_at, instrument)`, `instant` proves `available_at`, and `rows` proves the
    declared `key_fields` exactly as before (architecture §17.1.2). A grouped projection on a panel
    grain has nothing to prove -- `GROUP BY` yields one row per pair by construction -- so the scan
    is skipped rather than run against source rows the projection collapses.

    For an execution table this is the key the venue reads by (`trade_at, instrument`), proved
    here once (record `234`); nothing at preflight proves it again.
    """
    found = collector(Stage.REGISTER)
    if registration.grain is not Grain.ROWS and registration.aggregated:
        return found.done(retry=_RETRY)
    axis = registration.key_axis()
    result = scan.key_check(spec, axis)
    declared = ", ".join(axis)
    if result.null_groups:
        found.add(
            Failure.bounded(
                code="dataset.key_null",
                status=Status.INVALID,
                requirement=f"logical key ({declared}) must not contain nulls",
                observed=f"{result.null_groups} key group(s) with a null",
                examples=result.null_examples,
                example_total=result.null_groups,
                source=FailureSource(file=str(spec.path), key_path="key_fields"),
                fix=(
                    f"drop or repair the rows whose ({declared}) is null, or declare a key "
                    "whose columns are always present"
                ),
            )
        )
    if result.duplicate_groups:
        found.add(
            Failure.bounded(
                code="dataset.key_duplicate",
                status=Status.INVALID,
                requirement=f"logical key ({declared}) must be unique",
                observed=f"{result.duplicate_groups} duplicated key group(s)",
                examples=result.duplicate_examples,
                example_total=result.duplicate_groups,
                source=FailureSource(file=str(spec.path), key_path="key_fields"),
                fix=(
                    f"deduplicate the source on ({declared}), or widen the key until it "
                    "identifies one row"
                ),
            )
        )
    return found.done(retry=_RETRY)


def check_values(registration: DatasetRegistration, spec: SourceSpec) -> Diagnosis:
    """4단계 — 노출되는 numeric field에 NaN이나 inf가 있는가. 전체 스캔이다.

    **이 단계는 읽기 경로에서 옮겨 온 것이지 새로 생긴 요구가 아니다.** `normalize_scalar`이
    읽는 셀마다 묻던 질문이고, `035`의 addendum이 그것을 그냥 지우면 평가당 1.6s를 조용한
    NaN과 맞바꾸는 것이라고 정확히 지목했다. 그래서 `044`는 제거가 아니라 이동으로 닫힌다 --
    질문은 남고, 묻는 자리가 셀당 한 번에서 **field당 한 번**으로 바뀐다.

    묻는 대상은 원천 컬럼이 아니라 **field가 내는 값**이다. field가 표현식이 된 뒤로 둘은 같지
    않고, 모델에 건너가는 것은 뒤쪽이다 (`049`). 그래서 타입은 등록이 유도해 둔
    `field_types`에서 읽고, 스캔은 projection 위에서 돈다.

    수천 번 읽힐 파일을 등록 때 한 번 더 읽는 값이다. 스캔 한 번이며 컬럼 폭을 따라 늘지
    않는다(`scan.finite_check`).

    numeric이 아닌 field는 애초에 NaN을 담을 수 없으므로 묻지 않는다. 노출되는 field가 전부
    비-numeric이면 **이 단계는 I/O 없이 통과한다.**
    """
    if registration.field_types is None:
        raise ValueError("check_values needs the field types check_schema derives")
    found = collector(Stage.REGISTER)
    numeric = tuple(
        name
        for name, column_type in registration.field_types.items()
        if column_type is ColumnType.DOUBLE
    )
    if not numeric:
        return found.done()

    identity_fields = ("available_at",)
    if registration.instrument_field is not None:
        identity_fields = ("available_at", "instrument")
    result = scan.finite_check(
        spec,
        columns=numeric,
        identity_fields=identity_fields,
        relation=scan.projection_relation(
            spec,
            instrument_field=registration.instrument_field,
            available_at_field=registration.available_at,
            fields=registration.fields,
            aggregated=registration.aggregated,
        ),
    )
    examples = dict(result.examples)
    for name, count in result.non_finite:
        expression = registration.fields[name]
        found.add(
            Failure.bounded(
                code="dataset.value_not_finite",
                status=Status.INVALID,
                requirement=(
                    f"field {name!r} evaluates {expression!r}, whose values must be finite. A "
                    f"NaN or an infinity reaching a model does not fail there -- it propagates "
                    f"through every number it touches and the run reports a result"
                ),
                observed=f"{count} row(s) with a non-finite {name!r}",
                examples=examples.get(name, ()),
                example_total=count,
                source=FailureSource(
                    file=str(spec.path),
                    key_path=f"datasets.{registration.dataset_id}.fields.{name}",
                ),
                fix=(
                    f"drop or repair the rows whose {name!r} is NaN or infinite while preparing "
                    f"the source; a value that is genuinely absent belongs as NULL, which is "
                    f"read as a missing observation rather than a number"
                ),
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
    found = collector(Stage.REGISTER)
    measured = scan.span_check(spec, registration.available_at)

    if measured.rows == 0:
        found.add(
            Failure.bounded(
                code="dataset.span_empty",
                status=Status.INVALID,
                requirement="a registered dataset must carry at least one row to have a span",
                observed=f"{spec.source_id} resolved to 0 rows",
                source=FailureSource(file=str(spec.path)),
                fix="prepare the source with at least one row, then register again",
            )
        )
        return found.done(retry=_RETRY), None

    first, last = measured.first, measured.last
    if first is None or last is None:
        found.add(
            Failure.bounded(
                code="dataset.span_empty",
                status=Status.INVALID,
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
            )
        )
        return found.done(retry=_RETRY), None

    # tz-awareness is not re-checked here, and deliberately so. Stage 1 already refused a
    # non-TIMESTAMP_TZ `available_at` (`check_schema`), and min/max cannot change a column's
    # type, so a naive endpoint is unreachable by construction rather than merely unlikely. A
    # second refusal for it would be a code no fixture could ever produce -- the kind of branch
    # that looks like coverage and is really dead. `with_span` still enforces the invariant at
    # the boundary, which is where a caller bypassing validation would hit it.
    for endpoint in (first, last):
        assert endpoint.tzinfo is not None and endpoint.utcoffset() is not None, (
            f"stage 1 admitted a non-tz-aware {registration.available_at!r}"
        )
    return found.done(), (first, last)


def check_execution_prices(
    registration: DatasetRegistration, spec: SourceSpec
) -> tuple[str, ...] | None:
    """5단계 — 집행 역할이 있으면, 후보 가격 필드마다 tradable 행에서 유한·양수인지 잰다.

    A measurement, not a refusal: which of the table's numeric fields a run may fill at. The
    run's choice of `trade_price` is judged against this at preflight
    (`execution.price_not_positive`), where the choice is made -- until record `234` the chosen
    price alone was scanned again at preflight and at run. `None` for a dataset with no execution
    role; the empty tuple for a table none of whose prices qualify.
    """
    role = registration.execution
    if role is None or registration.instrument_field is None:
        return None
    tradable = registration.fields[role.is_tradable].strip()
    identity = (registration.available_at, registration.instrument_field)
    passing: list[str] = []
    for semantic, physical in sorted(execution_price_fields(registration).items()):
        result = scan.positive_finite_when_true(
            spec,
            value_field=physical,
            condition_field=tradable,
            identity_fields=identity,
        )
        if not result.invalid_rows:
            passing.append(semantic)
    return tuple(passing)


def verify_source(
    registration: DatasetRegistration, spec: SourceSpec
) -> tuple[Diagnosis, ValidationTiming, DatasetRegistration]:
    """선언이 실제 parquet과 맞는지 판정하고, 통과하면 잰 것을 전부 붙여 돌려준다.

    **다섯 단계다.** 값싼 검사를 먼저 전부 모아서 돌려주고, 통과했을 때만 전체 스캔으로 넘어간다.

        1단계  스키마   지목한 컬럼이 존재하나 · projection이 bind되나 · 그 타입이
                         model에 건넬 수 있는가 (field 타입과 grouping 판정이 여기서 나온다)
                         집행 역할이면: tradable은 BOOLEAN, instrument는 VARCHAR, 가격 후보가 있나
        2단계  key      null 없이 유일한가                          ← 전체 스캔
        3단계  span     실제로 덮는 구간은 어디인가                 ← 전체 스캔
        4단계  값       노출되는 numeric에 NaN·inf가 있는가         ← 전체 스캔
        5단계  가격     집행 역할이면, 후보 가격마다 tradable 행에서 양수·유한한가  ← 전체 스캔

    한 단계 안에서는 하나 나왔다고 멈추지 않는다. agent는 문제를 한 번에 다 받아야 자기 준비를
    한 번에 고친다. 단계를 가르는 이유는 **순서 의존**이다 — 컬럼이 없으면 유일성을 물을 수 없고,
    없는 컬럼 때문에 전체를 스캔할 이유는 더더욱 없다.

    세 번째 반환값은 **잰 것이 붙은 등록**이다: span · aggregated · 집행 가격 후보 · 그리고 잰
    바이트의 digest. 그 digest가 나중의 모든 읽기가 대조하는 신원이다(`require_verified`).
    실패했다면 붙일 것이 없으므로 받은 것을 그대로 돌려준다.
    """
    started = time.perf_counter()
    if registration.source != spec.source_id:
        found = collector(Stage.REGISTER)
        found.add(
            Failure.bounded(
                code="dataset.source_mismatch",
                status=Status.INVALID,
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
            )
        )
        return (
            found.done(retry=_RETRY),
            ValidationTiming(time.perf_counter() - started, None),
            registration,
        )

    columns = scan.describe(spec)
    schema, projection = check_schema(registration, columns, spec)
    schema_seconds = time.perf_counter() - started
    if not schema.ok:
        return schema, ValidationTiming(schema_seconds, None), registration
    role_failures = execution_role_failures(registration, columns)
    if role_failures:
        role = Diagnosis(stage=Stage.REGISTER, failures=role_failures, retry_precondition=_RETRY)
        return role, ValidationTiming(time.perf_counter() - started, None), registration
    assert projection is not None
    described = registration.with_aggregation(projection.aggregated)

    key_started = time.perf_counter()
    # The DESCRIBED registration: whether the projection is grouped is what decides if the
    # panel grain's uniqueness is proved by scan or by construction.
    key = check_key(described, spec)
    if not key.ok:
        key_timing = ValidationTiming(schema_seconds, time.perf_counter() - key_started)
        return key, key_timing, registration

    span, measured = check_span(registration, spec)
    if not span.ok:
        span_timing = ValidationTiming(schema_seconds, time.perf_counter() - key_started)
        return span, span_timing, registration
    if measured is None:
        raise RuntimeError("check_span passed without measuring a span")

    values = check_values(described, spec)
    timing = ValidationTiming(schema_seconds, time.perf_counter() - key_started)
    if not values.ok:
        return values, timing, registration
    prices = check_execution_prices(described, spec)
    verified = described.with_span(*measured).with_verification(physical_digest(spec.path), prices)
    return values, timing, verified


def require_verified(
    registration: DatasetRegistration, spec: SourceSpec, *, digest: str | None = None
) -> str:
    """The later reader's check: the source was measured, and these are the bytes it measured.

    No content scan. A registration that carries no digest was written before record `234` (or
    by a path that skipped the door) and is refused by name until it is registered again; one
    whose file has changed since is refused with both digests, because every fact registration
    stored -- span, key, prices -- was measured on the other bytes. `digest` lets a caller that
    already hashed the file (the workspace, once per command) pass it instead of hashing again.
    Returns the digest verified.
    """
    stored = registration.source_digest
    dataset_id = str(registration.dataset_id)
    again, command = _measured_again(registration)
    if stored is None:
        raise VqaprError(
            stage=Stage.FREEZE,
            failures=[
                Failure.bounded(
                    code="dataset.unverified",
                    status=Status.PRECONDITION,
                    requirement=(
                        "a dataset a run reads must have been measured at registration -- its "
                        "span, its key and the digest of its bytes -- and this registration "
                        "carries no such measurement"
                    ),
                    observed=(
                        f"dataset {dataset_id!r} was "
                        + (
                            f"published by run {registration.produced_by!r}"
                            if registration.produced_by is not None
                            else "registered"
                        )
                        + " before the measurement existed"
                    ),
                    source=FailureSource(file=str(spec.path), key_path=f"datasets.{dataset_id}"),
                    fix=f"{again} -- the command is {command}",
                )
            ],
            mutation=False,
            retry_precondition=f"{again} ({command}), then retry",
        )
    actual = physical_digest(spec.path) if digest is None else digest
    if actual != stored:
        raise VqaprError(
            stage=Stage.FREEZE,
            failures=[
                Failure.bounded(
                    code="dataset.source_changed",
                    status=Status.PRECONDITION,
                    requirement=(
                        "the bytes a run reads must be the bytes registration measured; every "
                        "fact the registration carries (span, key, prices) was measured on them"
                    ),
                    observed=(
                        f"dataset {dataset_id!r}: registered digest "
                        f"{stored[:12]}…, file now {actual[:12]}…"
                    ),
                    source=FailureSource(file=str(spec.path), key_path=f"datasets.{dataset_id}"),
                    fix=(
                        f"{again} so its facts are measured on the file as it is now -- "
                        f"the command is {command}"
                    ),
                )
            ],
            mutation=False,
            retry_precondition=f"{again} ({command}), then retry",
        )
    return actual


def _measured_again(registration: DatasetRegistration) -> tuple[str, str]:
    """What to do and the one command that does it: measure this registration again.

    A declared dataset is registered by `vqapr register <declaration>`. A dataset a run published
    through its `writes` has no declaration file: the run is what registered it, and the only
    command that registers it again is the run, told to replace what it published. Telling the
    reader of a run-published dataset to "register it again" named a command that does not exist
    for it, and the reader spent half an hour establishing that before trying the run
    (`docs/issues/report-2026-09-10-unverified-fix-names-no-command-for-a-run-published-dataset`).
    """
    dataset_id = str(registration.dataset_id)
    if registration.produced_by is not None:
        return (
            f"publish dataset {dataset_id!r} again",
            f"`vqapr run {registration.produced_by} --force`",
        )
    return f"register dataset {dataset_id!r} again", "`vqapr register <its declaration file>`"


def verify_roster(tables: Mapping[str, Path]) -> tuple[Diagnosis, dict[str, dict[str, str]]]:
    """Read the roster's tables through the door: `{kind: {instrument_id: kind}}`, or refusals.

    One failure per table that cannot be read, naming the file and what it lacks, collected
    rather than raised on the first -- the same rule the dataset stages follow. What the rows
    then must satisfy together (one kind per instrument across tables, kinds the package knows)
    is `domain.instruments.build_roster`'s, which the caller applies to what this returned.
    """
    import pyarrow.parquet as pq

    found = collector(Stage.REGISTER)
    rows: dict[str, dict[str, str]] = {}
    for kind, path in sorted(tables.items()):
        source = Path(path)
        if not source.is_file():
            found.add(
                Failure.bounded(
                    code="roster.table_missing",
                    status=Status.MISSING,
                    requirement=f"instruments.tables.{kind} must name a readable instrument table",
                    observed=f"instrument table is missing: {source}",
                    source=FailureSource(file=str(source)),
                    fix=(
                        f"write {source.name} with {INSTRUMENT_ID_FIELD} and {KIND_FIELD} "
                        "columns, then re-register"
                    ),
                )
            )
            continue
        table = pq.read_table(source)
        columns = set(table.column_names)
        missing = [field for field in (INSTRUMENT_ID_FIELD, KIND_FIELD) if field not in columns]
        if missing:
            found.add(
                Failure.bounded(
                    code="roster.table_invalid",
                    status=Status.INVALID,
                    requirement=f"instruments.tables.{kind} must name a readable instrument table",
                    observed=(
                        f"instrument table {source.name!r} is missing required column(s) "
                        f"{', '.join(missing)}; it must carry {INSTRUMENT_ID_FIELD} and "
                        f"{KIND_FIELD}"
                    ),
                    source=FailureSource(file=str(source)),
                    fix=(
                        f"write {source.name} with {INSTRUMENT_ID_FIELD} and {KIND_FIELD} "
                        "columns, then re-register"
                    ),
                )
            )
            continue
        ids = [str(value) for value in table.column(INSTRUMENT_ID_FIELD).to_pylist()]
        kinds = [str(value) for value in table.column(KIND_FIELD).to_pylist()]
        if not ids:
            found.add(
                Failure.bounded(
                    code="roster.table_invalid",
                    status=Status.INVALID,
                    requirement=f"instruments.tables.{kind} must name a readable instrument table",
                    observed=f"instrument table {source.name!r} declares no instruments",
                    source=FailureSource(file=str(source)),
                    fix=f"write at least one row to {source.name}, then re-register",
                )
            )
            continue
        resolved: dict[str, str] = {}
        conflict: str | None = None
        for instrument_id, declared_kind in zip(ids, kinds, strict=True):
            if instrument_id in resolved and resolved[instrument_id] != declared_kind:
                conflict = (
                    f"instrument {instrument_id!r} appears twice in {source.name!r} with "
                    f"different kinds ({resolved[instrument_id]!r} and {declared_kind!r})"
                )
                break
            resolved[instrument_id] = declared_kind
        if conflict is not None:
            found.add(
                Failure.bounded(
                    code="roster.table_invalid",
                    status=Status.INVALID,
                    requirement=f"instruments.tables.{kind} must name a readable instrument table",
                    observed=conflict,
                    source=FailureSource(file=str(source)),
                    fix=f"give {instrument_id!r} one kind in {source.name}, then re-register",
                )
            )
            continue
        rows[str(kind)] = resolved
    return found.done(retry="fix the instrument tables, then register again"), rows


__all__ = [
    "ValidationTiming",
    "check_execution_prices",
    "check_key",
    "check_schema",
    "check_span",
    "check_values",
    "execution_role_failures",
    "require_verified",
    "verify_roster",
    "verify_source",
]
