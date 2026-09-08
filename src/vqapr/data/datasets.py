"""의미 — logical dataset 등록과 그 검증.

물리 배치는 `sources.py`가 알고 여기는 **그 값이 무엇인지**를 안다. 등록이 요구하는 것은 일곱
개가 전부이며(PRD §4.1; `grain`은 기록 `137`에서 더해졌다), 그 이상은 그것을 필요로 하는
operation이 호출될 때 요구한다.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from vqapr.data import scan
from vqapr.data.lookback import InstantsLookback
from vqapr.data.scan import ColumnType
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import (
    Diagnosis,
    Failure,
    FailureSource,
    Stage,
    Status,
    collector,
)
from vqapr.domain.identifiers import DatasetId, SourceId, dataset_id, source_id
from vqapr.domain.shapes import Grain

_BARE_COLUMN = re.compile(r"[^\W\d]\w*", re.UNICODE)
"""A field expression that is nothing but a name, which is what every registration wrote before
one could be an expression.

A name this source does not have is refused by name, as it was when `fields` mapped ids to
columns -- and in the same round trip as every other schema problem. Anything more than a name is
an expression nobody here can check on its own, so it gets duckdb's message from the bind attempt,
untouched.
"""

# `Grain` -- what one row of the dataset IS -- lives in `domain/shapes.py` since record `183`:
# it is the fact the shapes are derived from, and it belongs beside them.
GRAIN_NAMES = ", ".join(member.value for member in Grain)

ROWS_LOOKBACK_MEANING = (
    "on a panel grain (instrument_instant, instant) a RowsLookback(n) is the last n rows of the "
    "pivoted table -- the same instants for every name -- not each name's own last n; per-name "
    "counting is InstantsLookback, and it belongs to grain: rows"
)
"""Said wherever a grain is refused, because the same word changed meaning (design §2.4, §7-1).

Every registration written before `grain` existed is edited once, by hand, to add it; that edit
is the one sure moment to tell the author that `RowsLookback` on their table now means something
else. Nothing decodes a grain-less registration as `rows` silently (§7-3).
"""

_RETRY = "fix the prepared dataset, then register again"


@dataclass(frozen=True, slots=True)
class ExecutionRole:
    """What makes a dataset an execution table: which field says a name was tradable.

    **The execution table is data** (owner ruling, 2026-09-08; record `185`). A venue table is
    registered like every other dataset -- `available_at` is the instant its row is a fact
    about, `instrument_field` names the instrument, its numeric fields are the prices it
    published -- and this role is the one thing it declares beyond that. Which price a run
    fills at is the RUN's choice (`runs.<id>.execution.fill.trade_price`), so one table serves
    a close-fill run and an open-fill run without being registered twice.

    The role is a property of the table, not of a read: the venue reads the table exactly at
    the fill instant, a Strategy may read it as ordinary point-in-time data, and the grain
    (`instrument_instant`, required) is the same for both.
    """

    is_tradable: str
    """The declared field (a `fields:` key, BOOLEAN) that says whether a name could be filled at
    that instant. A halted row still carries a price -- a halt suspends trading, not valuation."""

    def __post_init__(self) -> None:
        if not isinstance(self.is_tradable, str) or not self.is_tradable.strip():
            raise ValueError("execution.is_tradable must name a declared field")


@dataclass(frozen=True, slots=True)
class DatasetRegistration:
    """소비자가 `dataset_id`와 framework 이름으로 읽게 만드는 선언.

    instrument_field · available_at · key_fields 는 **물리 컬럼 이름**이고,
    `fields`는 framework 이름 → **값 표현식** 매핑이다 (`docs/issues/049`의 ruling). 맨 컬럼은
    축퇴된 표현식이므로 이 ruling 이전에 쓰인 등록은 글자 하나 바뀌지 않는다.

    `available_at`은 컬럼 이름이지 규칙이 아니다. user가 준비 단계에서 계산해 넣은 값이며
    (PRD §4.0), 우리는 그것이 tz-aware인지만 본다.

    `instrument_field`는 **선택**이다. 없는 dataset은 instrument 축이 없고 (`docs/issues/038`),
    선언된 instrument 목록이 적용되지 않는다 -- 어떤 표가 instrument로 키잉되는가는 그 표에
    대한 사실이지 읽는 쪽에 대한 사실이 아니다.
    """

    dataset_id: DatasetId
    source: SourceId
    instrument_field: str | None
    available_at: str
    key_fields: tuple[str, ...]
    fields: Mapping[str, str]
    grain: Grain | None = None
    """Declared, never derived. `None` only for a registration decoded from a document written
    before grain existed: it opens, it lists, it can be removed or re-registered, and every
    read on it is refused (`require_declared`) until it is registered again with one.
    """
    span: tuple[datetime, datetime] | None = None
    produced_by: str | None = None
    """The run that wrote this dataset, when a datamodel run did (`docs/issues/082`). Set by
    `DataModelOutput.register` from the run it serves; `None` for a dataset registered from the
    author's own file. A fact about provenance a reader could otherwise only reconstruct by
    opening every run record."""
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

    field_types: Mapping[str, ColumnType] | None = None
    """field id → author가 선언한 타입. **선언이고, 등록이 1회 대조한다** (`docs/issues/088`).

    2026-09-08 이전에는 유도값이었다(`049`: "author는 타입을 쓰지 않는다"). 그 판정은 뒤집혔다:
    parquet을 만드는 쪽이 author이므로 타입도 author가 말하고, `check_schema`가 `DESCRIBE`와
    대조해 다르면 거부한다. 파일과 어긋날 수 있는 "두 번째 사실"은 대조 1회로 사실 하나가 된다.
    값은 `scan.DECLARABLE_FIELD_TYPES` 안이어야 한다 -- `DECIMAL`은 잴 수는 있어도 선언할 수 없다.

    `None`은 선언 이전 shape로 쓰인 문서를 읽을 때만 나오며, 그 등록은 grain 없는 등록과 같은
    격리 상태다: 열리고, 나열되고, 지워지고, 다시 등록되지만 읽히지는 않는다(`require_declared`).
    """

    aggregated: bool = False
    """이 등록의 projection이 한 instant 안에서 묶이는가. **duckdb가 판정한 값**이다.

    `False`면 행 단위 -- 오늘까지의 모든 등록이 여기다 -- 이고 읽기 쿼리는 GROUP BY 없이,
    ruling 이전과 **같은 SQL**로 나간다. `True`면 `GROUP BY`가 붙어 (instrument, available_at)
    하나당 한 행이 나온다.

    둘은 배타적이고 그래서 binder가 심판이 될 수 있다 -- `scan.describe_projection` 참조.
    Python이 표현식을 파싱해 집계 여부를 추측하지 않는다.
    """

    execution: ExecutionRole | None = None
    """The execution role, when this table is one a run may fill against (record `185`).
    `None` for every other dataset. Declared, never derived: a table with a boolean column is
    not thereby a venue table."""

    @classmethod
    def of(
        cls,
        raw_dataset_id: str,
        raw_source_id: str,
        *,
        instrument_field: str | None = None,
        available_at: str,
        key_fields: Sequence[str],
        fields: Mapping[str, str],
        field_types: Mapping[str, ColumnType | str],
        grain: Grain | str | None = None,
        execution: ExecutionRole | Mapping[str, str] | None = None,
    ) -> DatasetRegistration:
        declared_grain = parse_grain(grain, dataset_id=raw_dataset_id)
        role = parse_execution_role(execution, fields=fields, dataset_id=raw_dataset_id)
        if role is not None and declared_grain is not Grain.INSTRUMENT_INSTANT:
            raise ValueError(
                f"dataset {raw_dataset_id!r}: an execution table is grain instrument_instant -- "
                "one row per (available_at, instrument) -- and this one declares "
                f"{declared_grain.value if declared_grain else 'no grain'}"
            )
        if declared_grain is Grain.INSTRUMENT_INSTANT and instrument_field is None:
            raise ValueError(
                f"dataset {raw_dataset_id!r}: grain instrument_instant needs an instrument_field; "
                "declare one, or declare grain: instant for a table with no instrument axis"
            )
        if declared_grain is Grain.INSTANT and instrument_field is not None:
            raise ValueError(
                f"dataset {raw_dataset_id!r}: grain instant has no instrument axis; drop "
                "instrument_field, or declare grain: instrument_instant"
            )
        if not key_fields:
            raise ValueError("key_fields must declare at least one column")
        if not fields:
            raise ValueError("fields must select at least one value to expose")
        for name, expression in fields.items():
            if not name or any(c.isspace() for c in name):
                raise ValueError(f"framework field name must not contain whitespace: {name!r}")
            # The expression itself is not inspected here beyond being present. What it means is
            # duckdb's answer, taken once at registration by `check_schema`; guessing at it in
            # Python would be a second opinion that can disagree with the one that runs.
            if not isinstance(expression, str) or not expression.strip():
                raise ValueError(f"field {name!r} must declare a non-empty value expression")
        return cls(
            dataset_id=dataset_id(raw_dataset_id),
            source=source_id(raw_source_id),
            instrument_field=instrument_field,
            available_at=available_at,
            key_fields=tuple(key_fields),
            fields=dict(fields),
            field_types=parse_field_types(field_types, fields=fields, dataset_id=raw_dataset_id),
            grain=declared_grain,
            execution=role,
        )

    @classmethod
    def undeclared(
        cls,
        raw_dataset_id: str,
        raw_source_id: str,
        *,
        instrument_field: str | None = None,
        available_at: str,
        key_fields: Sequence[str],
        fields: Mapping[str, str],
        field_types: Mapping[str, ColumnType] | None = None,
        grain: Grain | None = None,
        execution: ExecutionRole | None = None,
    ) -> DatasetRegistration:
        """A registration read back from a document written before `grain` or `field_types` was
        declared.

        Named, not defaulted: the only caller is the workspace codec, and the object it builds is
        unusable for reads until the dataset is registered again with what it lacks. Neither is
        defaulted -- not `rows`, not a type derived from the file -- because deciding either
        silently is the one path the design forbids (§7-3, `docs/issues/088`).
        """
        declared = cls.of(
            raw_dataset_id,
            raw_source_id,
            instrument_field=instrument_field,
            available_at=available_at,
            key_fields=key_fields,
            fields=fields,
            # Placeholders so `of` can run its shape checks; both are removed on the next line.
            field_types=(
                dict.fromkeys(fields, ColumnType.VARCHAR) if field_types is None else field_types
            ),
            grain=Grain.ROWS if grain is None else grain,
            execution=execution,
        )
        return replace(declared, grain=grain, field_types=field_types)

    def key_axis(self) -> tuple[str, ...]:
        """The columns registration proves unique, decided by the grain (design §2.2)."""
        if self.grain is Grain.INSTRUMENT_INSTANT:
            return (self.available_at, self.instrument_field)  # type: ignore[return-value]
        if self.grain is Grain.INSTANT:
            return (self.available_at,)
        return self.key_fields

    def with_aggregation(self, aggregated: bool) -> DatasetRegistration:
        """duckdb가 판정한 grouping을 붙인 사본. 판정하는 쪽은 `validate`다.

        field 타입은 여기 오지 않는다: 그것은 선언이고, `check_schema`가 잰 것과 대조했을 뿐이다.
        """
        return replace(self, aggregated=bool(aggregated))

    def with_producer(self, run_id: str) -> DatasetRegistration:
        """The same registration, naming the run that wrote it."""
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("produced_by must be a non-empty run id")
        return replace(self, produced_by=run_id)

    def spoken(self) -> list[str]:
        """The point-in-time meaning of this declaration, in one sentence (`docs/issues/027`).

        `available_at` is a column name and a rule at once: a row is knowable to a model at the
        instant that column says, and not one second earlier. Said once here, when the
        declaration is registered, so an author who wrote the column name has heard what it
        commits them to.
        """
        return [
            f"dataset {self.dataset_id!r}: a row is knowable at its {self.available_at!r} value "
            "and never earlier; a model reading it at instant t sees rows with "
            f"{self.available_at} <= t"
        ]

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
        """물리 컬럼 이름 → 그것이 어떤 역할로 지목되었는가. 진단 메시지에 쓴다.

        **이름뿐인 field만 여기 온다.** field 값은 이제 표현식이라 일반적으로는 "이 이름이
        스키마에 있나"로 물을 수 없고, 그 답은 `scan.describe_projection`이 duckdb에게 받는다.
        다만 이름 하나짜리 표현식은 ruling 이전의 모든 등록이 쓰던 축퇴형이고, 그것이 없는
        컬럼일 때 **컬럼 이름을 대며 거절하는 것**이 이 패키지가 하던 일이다. 그 진단을 표현식
        문법과 맞바꾸지 않는다 -- 한 왕복에 다 받는 성질도 여기 걸려 있다.
        """
        roles: dict[str, str] = {}
        if self.instrument_field is not None:
            roles.setdefault(self.instrument_field, "instrument_field")
        roles.setdefault(self.available_at, "available_at")
        for column in self.key_fields:
            roles.setdefault(column, "key_fields")
        for framework_name, expression in self.fields.items():
            column = expression.strip()
            if _BARE_COLUMN.fullmatch(column):
                roles.setdefault(column, f"fields[{framework_name}]")
        return roles


def parse_field_types(
    value: object, *, fields: Mapping[str, str], dataset_id: str
) -> dict[str, ColumnType]:
    """The declared type of every field, or a refusal that names what is missing or not permitted.

    One type per declared field, no more and no fewer: a field with no type is a field the file
    could hold as anything, and a type for a field that does not exist is a declaration about
    nothing. Values are matched case-insensitively against `ColumnType` and must be in
    `scan.DECLARABLE_FIELD_TYPES` (`docs/issues/088`).
    """
    if not isinstance(value, Mapping):
        observed = "absent" if value is None else type(value).__name__
        raise ValueError(
            f"dataset {dataset_id!r} must declare field_types, a mapping of every field to one "
            f"of: {scan.DECLARABLE_FIELD_TYPE_NAMES} ({observed})"
        )
    missing = sorted(set(fields) - set(value))
    extra = sorted(set(value) - set(fields))
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"fields without a type: {', '.join(missing)}")
        if extra:
            parts.append(f"types for fields not declared: {', '.join(extra)}")
        raise ValueError(
            f"dataset {dataset_id!r}: field_types must type every field in `fields` and nothing "
            f"else -- {'; '.join(parts)}"
        )
    parsed: dict[str, ColumnType] = {}
    for name in fields:
        declared = value[name]
        column_type: ColumnType | None = None
        if isinstance(declared, ColumnType):
            column_type = declared
        elif isinstance(declared, str):
            try:
                column_type = ColumnType(declared.strip().upper())
            except ValueError:
                column_type = None
        if column_type is None or column_type not in scan.DECLARABLE_FIELD_TYPES:
            raise ValueError(
                f"dataset {dataset_id!r}: field_types[{name!r}] must be one of "
                f"{scan.DECLARABLE_FIELD_TYPE_NAMES}; got {declared!r}"
            )
        parsed[name] = column_type
    return parsed


def parse_execution_role(
    value: object, *, fields: Mapping[str, str], dataset_id: str
) -> ExecutionRole | None:
    """The declared execution role, or a refusal naming what it must be.

    `is_tradable` must be one of the dataset's own fields and that field must be a bare column
    (record `185`): the venue reads it exactly at the fill instant by column name, and a boolean
    expression would be a rule about tradability the registration cannot check.
    """
    if value is None:
        return None
    if isinstance(value, ExecutionRole):
        role = value
    elif isinstance(value, Mapping):
        unknown = sorted(set(value) - {"is_tradable"})
        if unknown:
            raise ValueError(
                f"dataset {dataset_id!r}: execution declares unknown key(s) {unknown}; the one "
                "key is is_tradable"
            )
        role = ExecutionRole(str(value.get("is_tradable", "")))
    else:
        raise TypeError(f"dataset {dataset_id!r}: execution must be a mapping with is_tradable")
    if role.is_tradable not in fields:
        raise ValueError(
            f"dataset {dataset_id!r}: execution.is_tradable names {role.is_tradable!r}, which is "
            f"not one of its fields: {', '.join(sorted(fields))}"
        )
    if not _BARE_COLUMN.fullmatch(fields[role.is_tradable].strip()):
        raise ValueError(
            f"dataset {dataset_id!r}: execution.is_tradable field {role.is_tradable!r} must be a "
            "bare column, not an expression; the venue reads it by column name at the fill instant"
        )
    return role


def execution_role_failures(
    registration: DatasetRegistration, columns: Mapping[str, ColumnType]
) -> tuple[Failure, ...]:
    """What an execution table must additionally satisfy: a boolean tradable flag, and at least
    one numeric field a run could bind as its trade price."""
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
                    "declare the venue's price columns as DOUBLE or INTEGER fields of this "
                    "dataset"
                ),
            )
        )
    return tuple(failures)


def execution_price_fields(registration: DatasetRegistration) -> dict[str, str]:
    """The fields a run may bind as `trade_price`: the numeric ones, by field id.

    A field is an expression, as every dataset field is (`docs/issues/049`); the venue reads
    it through the same projection a model would, so `CAST(close AS DOUBLE)` over a DECIMAL
    column is a price like any other.
    """
    numeric = {ColumnType.INTEGER, ColumnType.DOUBLE}
    types = registration.field_types or {}
    return {
        name: expression.strip()
        for name, expression in registration.fields.items()
        if types.get(name) in numeric
    }


def parse_grain(value: object, *, dataset_id: str) -> Grain:
    """The declared grain, or a refusal that names the three values and what changed."""
    if isinstance(value, Grain):
        return value
    if isinstance(value, str):
        try:
            return Grain(value)
        except ValueError:
            pass
    observed = "absent" if value is None else repr(value)
    raise ValueError(
        f"dataset {dataset_id!r} must declare grain, one of: {GRAIN_NAMES} ({observed}). "
        f"Note: {ROWS_LOOKBACK_MEANING}"
    )


def lookback_fits_grain(lookback: object, grain: object) -> str | None:
    """`None` when the lookback is the grain's own kind; else the refusal, naming the right one.

    The types steer (design §2.4): a `rows` dataset takes only a `SeriesLookback`, a panel dataset
    only a `PanelLookback`. Said in one place so registration, preflight and the read agree.
    """
    if grain is Grain.ROWS:
        if isinstance(lookback, InstantsLookback):
            return None
        return (
            f"{type(lookback).__name__} is a panel lookback and this dataset declares grain: "
            "rows; per-name counting on a rows-grain table is InstantsLookback(n)"
        )
    if isinstance(lookback, InstantsLookback):
        return (
            "InstantsLookback counts each name's own instants and this dataset declares grain: "
            f"{grain.value}; on a panel grain use RowsLookback(n) for the table's last n rows "
            "(the same instants for every name) or CalendarLookback for a period"
        )
    return None


def require_declared(registration: DatasetRegistration) -> None:
    """Refuse a read on a registration that predates `grain` or `field_types`, by name.

    The workspace still opens with such an entry, so `list`, `remove` and re-registration work;
    what does not work is reading it -- through a run, a materialization or `check` -- because
    which lookback means what on it, or what type each field reaches a model as, is exactly the
    fact its author has not yet stated.
    """
    if registration.grain is not None and registration.field_types is not None:
        return
    if registration.grain is None:
        found = collector(Stage.REGISTER)
        found.add(
            Failure.bounded(
                code="dataset.grain_undeclared",
                status=Status.INVALID,
                requirement=(
                    f"a dataset must declare its grain before it can be read: {GRAIN_NAMES}"
                ),
                observed=(
                    f"dataset {str(registration.dataset_id)!r} was registered before grain "
                    "existed and declares none"
                ),
                source=FailureSource(key_path=f"datasets.{registration.dataset_id}.grain"),
                fix=(
                    f"add `grain: <{GRAIN_NAMES}>` to the dataset's declaration and register it "
                    f"again. Note: {ROWS_LOOKBACK_MEANING}"
                ),
            )
        )
        found.done(retry="declare the dataset's grain and register it again").raise_if_failed()
    found = collector(Stage.REGISTER)
    found.add(
        Failure.bounded(
            code="dataset.field_types_undeclared",
            status=Status.INVALID,
            requirement=(
                "a dataset must declare the type of every field before it can be read: "
                f"{scan.DECLARABLE_FIELD_TYPE_NAMES}"
            ),
            observed=(
                f"dataset {str(registration.dataset_id)!r} was registered before field_types "
                "was declared and declares none"
            ),
            source=FailureSource(key_path=f"datasets.{registration.dataset_id}.field_types"),
            fix=(
                "add `field_types:` mapping every field to its type to the dataset's declaration "
                "and register it again"
            ),
        )
    )
    found.done(retry="declare the dataset's field types and register it again").raise_if_failed()


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
                source=FailureSource(
                    key_path=f"datasets.{registration.dataset_id}.available_at"
                ),
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
                source=FailureSource(
                    key_path=f"datasets.{registration.dataset_id}.fields.{name}"
                ),
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

    if not measured.measured:
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
    for endpoint in (measured.first, measured.last):
        assert endpoint.tzinfo is not None and endpoint.utcoffset() is not None, (
            f"stage 1 admitted a non-tz-aware {registration.available_at!r}"
        )
    return found.done(), (measured.first, measured.last)


def validate(
    registration: DatasetRegistration, spec: SourceSpec
) -> tuple[Diagnosis, ValidationTiming, DatasetRegistration]:
    """선언이 실제 parquet과 맞는지 판정하고, 통과하면 잰 span을 붙여 돌려준다.

    **네 단계다.** 값싼 검사를 먼저 전부 모아서 돌려주고, 통과했을 때만 전체 스캔으로 넘어간다.

        1단계  스키마   지목한 컬럼이 존재하나 · projection이 bind되나 · 그 타입이
                         model에 건넬 수 있는가 (field 타입과 grouping 판정이 여기서 나온다)
        2단계  key      null 없이 유일한가                          ← 전체 스캔
        3단계  span     실제로 덮는 구간은 어디인가                 ← 전체 스캔
        4단계  값       노출되는 numeric에 NaN·inf가 있는가         ← 전체 스캔

    한 단계 안에서는 하나 나왔다고 멈추지 않는다. agent는 문제를 한 번에 다 받아야 자기 준비를
    한 번에 고친다. 단계를 가르는 이유는 **순서 의존**이다 — 컬럼이 없으면 유일성을 물을 수 없고,
    없는 컬럼 때문에 전체를 스캔할 이유는 더더욱 없다.

    세 번째 반환값은 **잰 span이 붙은 등록**이다. 실패했다면 붙일 것이 없으므로 받은 것을 그대로
    돌려준다.
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

    values = check_values(described, spec)
    timing = ValidationTiming(schema_seconds, time.perf_counter() - key_started)
    if not values.ok:
        return values, timing, registration
    return values, timing, described.with_span(*measured)
