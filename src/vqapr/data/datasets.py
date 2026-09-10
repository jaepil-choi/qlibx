"""의미 — logical dataset 등록: 선언이 무엇을 뜻하는가.

물리 배치는 `sources.py`가 알고, 그 파일이 선언대로인지 **재는** 것은 `validation.py`가
한다(기록 `234`, `docs/issues/095`). 여기는 **그 값이 무엇인지**를 안다. 등록이 요구하는 것은 일곱
개가 전부이며(PRD §4.1; `grain`은 기록 `137`에서 더해졌다), 그 이상은 그것을 필요로 하는
operation이 호출될 때 요구한다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from vqapr.data import scan
from vqapr.data.lookback import InstantsLookback, Lookback
from vqapr.data.scan import ColumnType
from vqapr.domain.errors import (
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
    produced_by_record: str | None = None
    """The record that wrote it -- `<component_id>@<fp8>`, the ref `list datamodels` and
    `rm datamodel` address -- when a run did (`docs/issues/091`). The run id says WHICH run; only
    the record ref says which VERSION of the component, and in a tuning loop several versions
    write the same dataset id in turn. Without it the parquet on disk could not be told apart
    from the file on disk, and five of eight pooled alphas in the reporting testbed held a
    version other than the one restored. `None` when `produced_by` is."""
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

    source_digest: str | None = None
    """sha256 of the bytes `verify_source` measured (record `234`). **측정값**이다: 등록이 잰 파일의
    신원이며, 뒤의 모든 읽기(`require_verified`)가 내용을 다시 스캔하는 대신 이것과 대조한다.
    `None`은 기록 `234` 이전 문서에서 읽혔거나 아직 재지 않았다는 뜻이고, 그런 등록은 run이
    이름을 대며 거절한다 -- 다시 등록하면 잰다."""

    execution_prices: tuple[str, ...] | None = None
    """For an execution-role table, the numeric fields whose value is finite and positive on every
    tradable row (record `234`) -- **측정값**, 등록이 후보 가격마다 한 번씩 잰다. A run's
    `trade_price` must be one of them (`execution.price_not_positive`, at preflight). `None` for a
    dataset with no execution role; `()` for a table none of whose prices qualify."""

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

    def with_producer(self, run_id: str, record_ref: str | None = None) -> DatasetRegistration:
        """The same registration, naming the run that wrote it and, when known, its record.

        `record_ref` is `<component_id>@<fp8>` (`docs/issues/091`). Optional only for a document
        written before the field existed: a producing run always knows its record ref.
        """
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("produced_by must be a non-empty run id")
        if record_ref is not None and (
            not isinstance(record_ref, str) or "@" not in record_ref or record_ref.startswith("@")
        ):
            raise ValueError("produced_by_record must be a record ref `<component_id>@<fp8>`")
        return replace(self, produced_by=run_id, produced_by_record=record_ref)

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

    def with_verification(
        self, source_digest: str, execution_prices: tuple[str, ...] | None
    ) -> DatasetRegistration:
        """The measured identity and price facts attached: what `verify_source` hands back."""
        if not isinstance(source_digest, str) or len(source_digest) != 64:
            raise ValueError("source_digest must be a sha256 hex digest")
        if execution_prices is not None and not all(
            isinstance(name, str) and name for name in execution_prices
        ):
            raise ValueError("execution_prices must name fields")
        return replace(
            self,
            source_digest=source_digest,
            execution_prices=None if execution_prices is None else tuple(execution_prices),
        )

    @property
    def verified(self) -> bool:
        """Whether `verify_source` measured this registration: the digest is there."""
        return self.source_digest is not None

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


def lookback_fits_grain(lookback: Lookback, grain: Grain | None) -> str | None:
    """`None` when the lookback is the grain's own kind; else the refusal, naming the right one.

    The types steer (design §2.4): a `rows` dataset takes only a `SeriesLookback`, a panel dataset
    only a `PanelLookback`. Said in one place so registration, preflight and the read agree.
    """
    if grain is None:
        # `require_declared` refuses a grain-less registration before any lookback is judged.
        raise RuntimeError("a lookback was judged against a registration that declares no grain")
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
