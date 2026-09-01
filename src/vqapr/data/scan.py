"""물리 층을 여는 유일한 곳 — 창도 점도 아닌 **스캔**.

등록 검증은 창 조회로 답할 수 없는 것을 묻는다 — *"이 컬럼이 있나"*, *"이 key가 전체에서
유일한가"*. 그래서 `store.py`(창 포트)와 별개다. 여기 없으면 검증이 lookback 없는 전체 조회를
요구하게 되고, 그 구멍이 곧 look-ahead 경로가 된다.

**의미를 모른다.** 어느 컬럼이 `available_at`인지는 `datasets.py`가 정한다.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

import duckdb

from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import ExplainTopic, Failure, FailureFamily, FailureSource, VqaprError

_EXAMPLE_LIMIT = 5


class ColumnType(StrEnum):
    """정규화된 컬럼 타입.

    backend 어휘를 위로 올리지 않는다. `datasets.py`가 duckdb 타입 문자열을 매칭하면 backend를
    바꾸는 순간 검증이 깨진다(§4.6).

    `TIMESTAMP_TZ`와 `TIMESTAMP_NAIVE`를 가르는 것이 이 enum의 존재 이유다 — naive timestamp는
    저장도 되고 조회도 되지만 **조용히 틀린다.**
    """

    TIMESTAMP_TZ = "TIMESTAMP_TZ"
    TIMESTAMP_NAIVE = "TIMESTAMP_NAIVE"
    DATE = "DATE"
    INTEGER = "INTEGER"
    DOUBLE = "DOUBLE"
    VARCHAR = "VARCHAR"
    BOOLEAN = "BOOLEAN"
    OTHER = "OTHER"


_INTEGER_TYPES = frozenset(
    {
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
        "UHUGEINT",
    }
)
_DOUBLE_TYPES = frozenset({"FLOAT", "DOUBLE", "REAL"})


def _normalize(duck_type: str) -> ColumnType:
    t = duck_type.upper().strip()
    if t.startswith("TIMESTAMP") and "WITH TIME ZONE" in t:
        return ColumnType.TIMESTAMP_TZ
    if t.startswith("TIMESTAMP"):
        return ColumnType.TIMESTAMP_NAIVE
    if t == "DATE":
        return ColumnType.DATE
    if t in _INTEGER_TYPES:
        return ColumnType.INTEGER
    if t in _DOUBLE_TYPES or t.startswith("DECIMAL"):
        return ColumnType.DOUBLE
    if t == "VARCHAR":
        return ColumnType.VARCHAR
    if t == "BOOLEAN":
        return ColumnType.BOOLEAN
    return ColumnType.OTHER


@dataclass(frozen=True, slots=True)
class KeyCheck:
    """logical key가 null 없이 유일한가.

    null과 중복을 한 번의 group-by로 함께 센다. 예시는 위반이 있을 때만 추가로 조회하므로
    **통과하는 경우가 한 번의 스캔**이다.
    """

    fields: tuple[str, ...]
    null_groups: int
    duplicate_groups: int
    null_examples: tuple[str, ...] = ()
    duplicate_examples: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.null_groups == 0 and self.duplicate_groups == 0


@dataclass(frozen=True, slots=True)
class SpanCheck:
    """The first and last instant a dataset carries, and how many rows it carries at all.

    `rows` is what tells an empty dataset apart from one whose availability column is entirely
    null. Both leave `first`/`last` as `None`, and they are different problems: the first has
    nothing to register, the second has rows nobody can date.
    """

    rows: int
    first: datetime | None
    last: datetime | None

    @property
    def measured(self) -> bool:
        return self.first is not None and self.last is not None


@dataclass(frozen=True, slots=True)
class ConditionalPositiveCheck:
    """boolean field가 true일 때 numeric field가 유한한 양수인지의 bounded summary."""

    invalid_rows: int
    examples: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.invalid_rows == 0


@dataclass(frozen=True, slots=True)
class FiniteCheck:
    """등록이 노출하는 numeric 컬럼에 NaN이나 inf가 있는가.

    읽기 경로가 셀마다 묻던 질문을 등록이 컬럼마다 한 번 묻는 자리다(044). null은 위반이
    아니다 -- 희소한 field는 정상이고, 읽기 경로는 이미 non-null만 센다. 유한하지 **않은**
    값만 세며, 그것은 준비 단계의 실수이지 데이터의 모양이 아니다.
    """

    columns: tuple[str, ...]
    non_finite: tuple[tuple[str, int], ...] = ()
    examples: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def ok(self) -> bool:
        return not self.non_finite


def _quote(field: str) -> str:
    if not isinstance(field, str) or not field.strip():
        raise ValueError("field must be a non-empty column name")
    return '"' + field.replace('"', '""') + '"'


def _relation(spec: SourceSpec) -> str:
    """SourceSpec을 duckdb가 읽을 수 있는 표현으로.

    `hive_partitioned`가 여기서 실제로 갈린다 — False면 파티션 키가 컬럼으로 살아나지 않는다.
    """
    path = spec.path
    target = (path / "**" / "*.parquet").as_posix() if path.is_dir() else path.as_posix()
    target = target.replace("'", "''")
    hive = 1 if spec.hive_partitioned else 0
    return f"read_parquet('{target}', hive_partitioning={hive})"


def _open(spec: SourceSpec) -> duckdb.DuckDBPyConnection:
    _require_path(spec)
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    return con


def _require_path(spec: SourceSpec) -> None:
    """경로 존재를 typed failure로 확인한다.

    `_open`에서 분리한 이유: 세션이 커넥션을 재사용해도 이 검사는 **조회마다** 돌아야 한다.
    검사를 커넥션 생성에 묶어두면 재사용 경로에서 조용히 사라지고, 그때 에러 메시지가
    typed failure에서 duckdb 내부 예외로 바뀐다.
    """
    if not spec.path.exists():
        raise VqaprError(
            stage="source.scan.open",
            family=FailureFamily.DATA,
            failures=[
                Failure.bounded(
                    code="source.scan.path_missing",
                    requirement=f"source '{spec.source_id}' must point at an existing path",
                    observed=str(spec.path),
                    source=FailureSource(file=str(spec.path)),
                    fix=(
                        f"check the path declared for source '{spec.source_id}', then create "
                        "or restore the file or directory at it"
                    ),
                    explain=ExplainTopic.SOURCE_ACCESS,
                )
            ],
            retry_precondition="create the path, then retry the same operation",
        )


class ScanSession:
    """한 run 동안 살아 있는 물리 층 핸들.

    duckdb 커넥션은 **이 모듈 밖으로 나가지 않는다**. 모듈 docstring이 선언한 "물리 층을 여는
    유일한 곳"이라는 경계가 수명을 늘린다고 깨지면 안 되므로, 소유권은 `scan.py` 안에 남는다.
    호출부는 세션을 들고 다니되 커넥션은 만지지 않는다.

    커넥션을 재사용하는 이유는 고정비(연결 셋업)만이 아니다. duckdb는 커넥션 수명 동안
    parquet 메타데이터(footer, row-group 통계)를 캐시하는데, 조회마다 닫으면 그 캐시가
    매번 버려진다.
    """

    __slots__ = ("_bounds", "_connections", "_database", "_grids", "_sizes")

    def __init__(self) -> None:
        self._database: duckdb.DuckDBPyConnection | None = None
        self._connections: dict[str, duckdb.DuckDBPyConnection] = {}
        self._grids: dict[tuple[str, str], tuple[object, ...]] = {}
        self._sizes: dict[str, int] = {}
        self._bounds: dict[tuple[object, ...], _RowsBound] = {}

    def connection(self, spec: SourceSpec) -> duckdb.DuckDBPyConnection:
        _require_path(spec)
        key = spec.path.as_posix()
        con = self._connections.get(key)
        if con is None:
            # One database for the run, one cursor per source. `duckdb.connect()` with no path
            # builds a whole in-memory database -- its own buffer pool, its own thread pool --
            # so opening one per source made a run's sources compete for memory instead of
            # sharing it. A cursor is an independent connection to the same database, so a
            # statement running against one source still does not touch another's.
            database = self._database
            if database is None:
                database = self._database = duckdb.connect()
            con = database.cursor()
            con.execute("SET preserve_insertion_order=false")
            self._connections[key] = con
        return con

    def instant_grid(self, spec: SourceSpec, available_at_field: str) -> tuple[object, ...]:
        """Every distinct availability instant in one source, ascending, read once per run.

        A source is frozen for the life of a run, so this grid is too. It exists to turn "how far
        back must a query reach for N rows" into arithmetic instead of a query: without it every
        `RowsLookback` callback would pay a scan just to guess its own lower bound.

        Deliberately not filtered by instrument. The grid is a *guess* -- the caller re-reads
        whatever the guess came up short on -- and an unfiltered grid is a superset, so the guess
        it produces is at worst tighter than necessary, never wider than the data supports.
        """
        key = (spec.path.as_posix(), available_at_field)
        grid = self._grids.get(key)
        if grid is None:
            column = _quote(available_at_field)
            rows = (
                self.connection(spec)
                .execute(
                    f"SELECT DISTINCT {column} FROM {_relation(spec)} "
                    f"WHERE {column} IS NOT NULL ORDER BY {column}"
                )
                .fetchall()
            )
            grid = self._grids[key] = tuple(row[0] for row in rows)
        return grid

    def rows_bound(self, key: tuple[object, ...]) -> _RowsBound | None:
        """The lower bound already proved for one declared read, if this run has proved one.

        Keyed by everything the proof is about -- source, fields, instruments, declared rows --
        so a read that asks a different question does not inherit another's answer. What makes
        one answer serve a later callback is argued in `_rows_bound`.
        """
        return self._bounds.get(key)

    def remember_rows_bound(self, key: tuple[object, ...], bound: _RowsBound) -> None:
        self._bounds[key] = bound

    def source_bytes(self, spec: SourceSpec) -> int:
        """Total parquet bytes behind one source, measured once per run."""
        key = spec.path.as_posix()
        size = self._sizes.get(key)
        if size is None:
            path = spec.path
            files = (path,) if path.is_file() else path.glob("**/*.parquet")
            size = self._sizes[key] = sum(item.stat().st_size for item in files)
        return size

    def close(self) -> None:
        self._grids.clear()
        self._sizes.clear()
        self._bounds.clear()
        while self._connections:
            _, con = self._connections.popitem()
            con.close()
        if self._database is not None:
            self._database.close()
            self._database = None

    def __enter__(self) -> ScanSession:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class _Borrowed:
    """세션 커넥션은 빌리고, 자기 커넥션은 닫는다.

    각 스캔 함수의 `finally: con.close()`를 그대로 두면 세션 커넥션까지 닫힌다. 이 래퍼가
    소유권을 표현해서 호출부 구조를 바꾸지 않고도 두 경로를 하나로 유지한다.
    """

    __slots__ = ("_owned", "connection")

    def __init__(self, spec: SourceSpec, session: ScanSession | None) -> None:
        if session is None:
            self.connection = _open(spec)
            self._owned = True
        else:
            self.connection = session.connection(spec)
            self._owned = False

    def close(self) -> None:
        if self._owned:
            self.connection.close()


def describe(spec: SourceSpec) -> dict[str, ColumnType]:
    """컬럼 이름 → 정규화된 타입. 데이터를 읽지 않고 스키마만 본다."""
    con = _open(spec)
    try:
        rows = con.execute(f"DESCRIBE SELECT * FROM {_relation(spec)}").fetchall()
    except duckdb.Error as exc:
        raise VqaprError(
            stage="source.scan.describe",
            family=FailureFamily.DATA,
            failures=[
                Failure.bounded(
                    code="source.scan.unreadable",
                    requirement=f"source '{spec.source_id}' must be readable parquet",
                    observed=str(exc).splitlines()[0],
                    source=FailureSource(file=str(spec.path)),
                    fix=(
                        f"open '{spec.path}' with duckdb directly to see the underlying error, "
                        "then repair or re-export the parquet at that path"
                    ),
                    explain=ExplainTopic.SOURCE_ACCESS,
                )
            ],
        ) from exc
    finally:
        con.close()
    return {name: _normalize(dtype) for name, dtype, *_ in rows}


_SQL_QUOTED = re.compile("'(?:''|[^'])*'" + '|"(?:""|[^"])*"')
_SUBQUERY = re.compile("(?<![A-Za-z0-9_])select(?![A-Za-z0-9_])", re.IGNORECASE)


def statement_keyword(expression: str) -> str | None:
    """The keyword that makes a field expression a statement rather than a value, if any.

    A field is an expression, and an expression is evaluated within one instant by construction --
    that property is what makes a registration-time look-ahead test unnecessary rather than
    merely skipped (`docs/issues/049`). **A scalar subquery is the one expression form that breaks
    it**: it carries its own `FROM`, so it can read rows the window excludes.

    Refusing the `SELECT` token refuses every subquery without a parser, and refuses nothing else:
    `extract(year FROM date)` and `sum(x) FILTER (WHERE ...)` are ordinary expressions that happen
    to contain SQL keywords, and both keep working. Quoted text is removed first, so a literal
    that spells the keyword is a value like any other.
    """
    if not isinstance(expression, str):
        raise TypeError("expression must be a string")
    return "SELECT" if _SUBQUERY.search(_SQL_QUOTED.sub(" ", expression)) else None


@dataclass(frozen=True, slots=True)
class ProjectionSchema:
    """What a registration's projection produces, and whether it groups within an instant.

    `errors` carries duckdb's own first line for each shape that failed to bind, in the order they
    were tried, and is empty exactly when the projection bound. Nothing here turns one into a
    refusal -- `datasets.py` owns what a failure means, as it does for every other check in this
    module.
    """

    field_types: Mapping[str, ColumnType]
    aggregated: bool
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def identity_projections(instrument_field: str | None, available_at_field: str) -> tuple[str, ...]:
    """The identity columns every projection carries, aliased to their framework names.

    `instrument_field` is optional, and a dataset registered without one has **no instrument
    axis** (`docs/issues/038`): no output column and, at read time, no instrument predicate
    either. Whether a table is keyed by instrument is a fact about the table.
    """
    projections = [f"{_quote(available_at_field)} AS {_quote('available_at')}"]
    if instrument_field is not None:
        projections.append(f"{_quote(instrument_field)} AS {_quote('instrument')}")
    return tuple(projections)


def value_projections(fields: Mapping[str, str]) -> tuple[str, ...]:
    """One aliased expression per declared field.

    Parenthesised, so a value cannot become a clause: anything that tried to close the projection
    and open a second one is a syntax error rather than a second statement.
    """
    return tuple(f"({expression}) AS {_quote(name)}" for name, expression in fields.items())


def projection_relation(
    spec: SourceSpec,
    *,
    instrument_field: str | None,
    available_at_field: str,
    fields: Mapping[str, str],
    aggregated: bool,
) -> str:
    """The registration's projection as a relation, parenthesised for use as a subquery.

    **Anything that must look at what a model will receive reads this, not the source.** Once a
    field is an expression those are different things: the column an expression reads is not the
    value it produces, and only the value crosses the boundary.

    `aggregated` picks the shape the binder settled on at registration -- see
    `describe_projection`. Nothing decides it here, because deciding it twice is how the read path
    and the registration come to disagree.
    """
    identity = identity_projections(instrument_field, available_at_field)
    select = ", ".join((*identity, *value_projections(fields)))
    tail = ""
    if aggregated:
        grouping = ", ".join(str(position) for position in range(1, len(identity) + 1))
        tail = f" GROUP BY {grouping}"
    return f"(SELECT {select} FROM {_relation(spec)}{tail})"


def describe_projection(
    spec: SourceSpec,
    *,
    instrument_field: str | None,
    available_at_field: str,
    fields: Mapping[str, str],
) -> ProjectionSchema:
    """Type every declared field, and decide whether the projection groups, by asking duckdb.

    A field is an expression, so what it is typed as -- and whether it aggregates the rows an
    instant holds -- are facts about the composed query rather than about any source column. Both
    are read off `DESCRIBE`, which is why an author never writes a type.

    **The two shapes are mutually exclusive, and that is what lets the binder be the judge.** The
    identity columns are projected bare, so the grouped shape binds only when every field is an
    aggregate, and the row-wise shape binds only when no field is. A registration is therefore one
    or the other, one that mixes the two is neither, and nothing here parses SQL to decide which.

    Grouped is the shape `049` rules for: one row per instrument per instant, the expression
    evaluated inside that group. Row-wise is what every registration written before that ruling
    already is -- a bare column is a row-wise expression -- so those keep the query they had,
    byte for byte, including the rows a finer key admits.
    """
    errors: list[str] = []
    con = _open(spec)
    try:
        for aggregated in (False, True):
            relation = projection_relation(
                spec,
                instrument_field=instrument_field,
                available_at_field=available_at_field,
                fields=fields,
                aggregated=aggregated,
            )
            try:
                rows = con.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
            except duckdb.Error as exc:
                errors.append(str(exc).splitlines()[0])
                continue
            described = {name: _normalize(dtype) for name, dtype, *_ in rows}
            return ProjectionSchema({name: described[name] for name in fields}, aggregated)
    finally:
        con.close()
    return ProjectionSchema({}, False, errors=tuple(errors))


def row_count(spec: SourceSpec) -> int:
    """How many rows the source holds, without reading them."""
    con = _open(spec)
    try:
        return int(con.execute(f"SELECT count(*) FROM {_relation(spec)}").fetchone()[0])
    finally:
        con.close()


def head(spec: SourceSpec, *, limit: int = 100) -> list[dict[str, object]]:
    """The first rows of a source, as plain dicts. `limit=0` reads every row.

    A scan primitive for a reader, not an observation query: no point-in-time cutoff, no lookback,
    no dataset semantics. `show dataset` is the caller, and what it answers is "what is in this
    file" rather than "what would a model have seen" -- conflating the two would make an inspection
    command quietly disagree with the windows a run actually reads.
    """
    con = _open(spec)
    try:
        sql = f"SELECT * FROM {_relation(spec)}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cursor = con.execute(sql)
        names = [column[0] for column in cursor.description]
        return [
            {name: (str(value) if isinstance(value, Decimal) else value)
             for name, value in zip(names, row, strict=True)}
            for row in cursor.fetchall()
        ]
    finally:
        con.close()


def distinct_values(spec: SourceSpec, field: str) -> tuple[object, ...]:
    """Read one physical column as sorted distinct values for a non-Model consumer.

    This is a scan primitive, not an observation query. It does not apply PIT, lookback, or
    dataset semantics; callers such as the execution-table boundary own those meanings.
    """
    quoted = _quote(field)
    con = _open(spec)
    try:
        rows = con.execute(
            f"SELECT DISTINCT {quoted} FROM {_relation(spec)} ORDER BY {quoted}"
        ).fetchall()
    except duckdb.Error as exc:
        raise VqaprError(
            stage="source.scan.distinct",
            family=FailureFamily.DATA,
            failures=[
                Failure.bounded(
                    code="source.scan.distinct.unreadable",
                    requirement=f"field {field!r} must be readable from source '{spec.source_id}'",
                    observed=str(exc).splitlines()[0],
                    source=FailureSource(file=str(spec.path), key_path=field),
                    fix=(
                        f"confirm column {field!r} exists with that exact name in "
                        f"'{spec.path}', then retry"
                    ),
                    explain=ExplainTopic.SOURCE_ACCESS,
                )
            ],
        ) from exc
    finally:
        con.close()
    return tuple(row[0] for row in rows)


def candidate_instants(
    spec: SourceSpec,
    *,
    trade_at_field: str,
    decision_time: object,
    end_time: object,
    session: ScanSession | None = None,
) -> tuple[object, ...]:
    """Return only distinct candidate execution instants in the causal run interval."""

    trade_at = _quote(trade_at_field)
    borrowed = _Borrowed(spec, session)
    try:
        rows = borrowed.connection.execute(
            f"SELECT DISTINCT {trade_at} FROM {_relation(spec)} "
            f"WHERE {trade_at} > ? AND {trade_at} <= ? ORDER BY {trade_at}",
            [decision_time, end_time],
        ).fetchall()
    except duckdb.Error as exc:
        raise VqaprError(
            stage="source.scan.execution_candidates",
            family=FailureFamily.DATA,
            failures=[
                Failure.bounded(
                    code="source.scan.execution_candidates.unreadable",
                    requirement="the execution instant field must be queryable",
                    observed=str(exc).splitlines()[0],
                    source=FailureSource(file=str(spec.path), key_path=trade_at_field),
                    fix=(
                        f"confirm column {trade_at_field!r} exists with that exact name in "
                        f"'{spec.path}', then retry"
                    ),
                    explain=ExplainTopic.SOURCE_ACCESS,
                )
            ],
            mutation=False,
        ) from exc
    finally:
        borrowed.close()
    return tuple(row[0] for row in rows)


def exact_snapshot_rows(
    spec: SourceSpec,
    *,
    trade_at_field: str,
    instrument_field: str,
    target_at: object,
    instruments: Sequence[str],
    fields: Mapping[str, str],
    session: ScanSession | None = None,
) -> tuple[dict[str, object], ...]:
    """Read one exact execution snapshot; never substitutes a nearby row or price."""

    if not instruments:
        return ()
    if not fields:
        raise ValueError("exact snapshot requires at least one field")
    trade_at = _quote(trade_at_field)
    instrument = _quote(instrument_field)
    placeholders = ", ".join("?" for _ in instruments)
    projections = [
        f"{trade_at} AS {_quote('trade_at')}",
        f"{instrument} AS {_quote('instrument')}",
        *(f"{_quote(physical)} AS {_quote(semantic)}" for semantic, physical in fields.items()),
    ]
    borrowed = _Borrowed(spec, session)
    try:
        cursor = borrowed.connection.execute(
            f"SELECT {', '.join(projections)} FROM {_relation(spec)} "
            f"WHERE {trade_at} = ? AND {instrument} IN ({placeholders}) ORDER BY {instrument}",
            [target_at, *instruments],
        )
        names = tuple(description[0] for description in cursor.description)
        return tuple(dict(zip(names, row, strict=True)) for row in cursor.fetchall())
    except duckdb.Error as exc:
        raise VqaprError(
            stage="source.scan.execution_snapshot",
            family=FailureFamily.DATA,
            failures=[
                Failure.bounded(
                    code="source.scan.execution_snapshot.unreadable",
                    requirement="the exact execution snapshot fields must be queryable",
                    observed=str(exc).splitlines()[0],
                    source=FailureSource(file=str(spec.path)),
                    fix=(
                        f"confirm {trade_at_field!r}, {instrument_field!r}, and the requested "
                        f"fields all exist with those exact names in '{spec.path}', then retry"
                    ),
                    explain=ExplainTopic.SOURCE_ACCESS,
                )
            ],
            mutation=False,
        ) from exc
    finally:
        borrowed.close()


def key_check(spec: SourceSpec, fields: Sequence[str]) -> KeyCheck:
    """logical key가 null 없이 유일한지 확인한다.

    통과하면 스캔 한 번. 위반이 있을 때만 예시를 위해 한 번 더 읽는다 — 실패는 드물고 그때는
    느려도 되지만, 성공 경로는 매 등록마다 도는 자리다.
    """
    if not fields:
        raise ValueError("key_check requires at least one field")
    cols = ", ".join(_quote(field) for field in fields)
    null_pred = " OR ".join(f"{_quote(field)} IS NULL" for field in fields)
    con = _open(spec)
    try:
        grouped = (
            f"SELECT {cols}, count(*) AS n, ({null_pred}) AS has_null "
            f"FROM {_relation(spec)} GROUP BY {cols}"
        )
        null_groups, dup_groups = con.execute(
            f"SELECT coalesce(sum(CASE WHEN has_null THEN 1 ELSE 0 END), 0), "
            f"       coalesce(sum(CASE WHEN n > 1 THEN 1 ELSE 0 END), 0) FROM ({grouped})"
        ).fetchone()

        null_examples: tuple[str, ...] = ()
        dup_examples: tuple[str, ...] = ()
        if null_groups:
            rows = con.execute(
                f"SELECT {cols} FROM ({grouped}) WHERE has_null LIMIT {_EXAMPLE_LIMIT}"
            ).fetchall()
            null_examples = tuple(repr(r) for r in rows)
        if dup_groups:
            rows = con.execute(
                f"SELECT {cols}, n FROM ({grouped}) WHERE n > 1 "
                f"ORDER BY n DESC LIMIT {_EXAMPLE_LIMIT}"
            ).fetchall()
            dup_examples = tuple(f"{r[:-1]} x{r[-1]}" for r in rows)
    finally:
        con.close()

    return KeyCheck(
        fields=tuple(fields),
        null_groups=int(null_groups),
        duplicate_groups=int(dup_groups),
        null_examples=null_examples,
        duplicate_examples=dup_examples,
    )


def span_check(spec: SourceSpec, available_at: str) -> SpanCheck:
    """The first and last instant the availability column carries, plus the row count.

    This is a SECOND aggregate over the source, not a free rider on the key scan, and it is worth
    naming rather than glossing: measured on the 7.5M-row testbed source it cost 0.055s against
    the key check's 0.209s, so roughly a quarter more registration time. It is a separate query
    because the two answer differently-shaped questions -- the key check groups by the logical
    key, and folding min/max into that grouping would compute per-group extrema nobody wants,
    then need a second pass to collapse them anyway.

    What it buys is that the span is measured ONCE, at registration, instead of on every later
    read: `Workspace.span` then answers from the stored declaration without opening the file at
    all. Paying a quarter of one registration to make every subsequent lookup free is the trade.
    """
    column = _quote(available_at)
    con = _open(spec)
    try:
        rows, first, last = con.execute(
            f"SELECT count(*), min({column}), max({column}) FROM {_relation(spec)}"
        ).fetchone()
    finally:
        con.close()
    return SpanCheck(rows=int(rows), first=first, last=last)


def positive_finite_when_true(
    spec: SourceSpec,
    *,
    value_field: str,
    condition_field: str,
    identity_fields: Sequence[str],
) -> ConditionalPositiveCheck:
    """조건이 true인 행의 선택 numeric value가 null/NaN/inf/비양수인지 센다."""
    value = _quote(value_field)
    condition = _quote(condition_field)
    identities = tuple(identity_fields)
    if not identities:
        raise ValueError("identity_fields must not be empty")
    identity_sql = ", ".join(_quote(field) for field in identities)
    invalid = (
        f"{condition} IS TRUE AND "
        f"({value} IS NULL OR NOT isfinite(CAST({value} AS DOUBLE)) OR {value} <= 0)"
    )
    con = _open(spec)
    try:
        count = int(
            con.execute(f"SELECT count(*) FROM {_relation(spec)} WHERE {invalid}").fetchone()[0]
        )
        examples: tuple[str, ...] = ()
        if count:
            rows = con.execute(
                f"SELECT {identity_sql}, {value} FROM {_relation(spec)} "
                f"WHERE {invalid} LIMIT {_EXAMPLE_LIMIT}"
            ).fetchall()
            examples = tuple(repr(row) for row in rows)
    except duckdb.Error as exc:
        raise VqaprError(
            stage="source.scan.conditional_positive",
            family=FailureFamily.DATA,
            failures=[
                Failure.bounded(
                    code="source.scan.conditional_positive.unreadable",
                    requirement=(
                        f"fields {condition_field!r} and {value_field!r} must be readable "
                        f"from source '{spec.source_id}'"
                    ),
                    observed=str(exc).splitlines()[0],
                    source=FailureSource(file=str(spec.path)),
                    fix=(
                        f"confirm {condition_field!r} and {value_field!r} exist with those "
                        f"exact names in '{spec.path}', then retry"
                    ),
                    explain=ExplainTopic.SOURCE_ACCESS,
                )
            ],
        ) from exc
    finally:
        con.close()
    return ConditionalPositiveCheck(invalid_rows=count, examples=examples)


def finite_check(
    spec: SourceSpec,
    *,
    columns: Sequence[str],
    identity_fields: Sequence[str],
    relation: str | None = None,
) -> FiniteCheck:
    """노출되는 numeric 컬럼 전부의 NaN/inf를 **한 번의 스캔**으로 센다.

    컬럼당 스캔이 아니라 컬럼당 aggregate다. `048`이 등록 비용이 key 폭을 따라간다고 지목한
    자리이므로, 폭이 넓다고 파일을 여러 번 읽지 않는다.

    `key_check`와 같은 모양으로 예시는 위반이 있을 때만 추가로 읽는다 -- 통과 경로가 매
    등록마다 도는 자리이고, 실패는 드물며 그때는 느려도 된다.

    `relation`이 주어지면 원천 대신 그것을 읽는다. field가 표현식이 된 뒤로 물어야 하는 것은
    "이 컬럼에 NaN이 있나"가 아니라 **"이 field가 내는 값에 NaN이 있나"**이고, 둘은 같지
    않다 (`projection_relation`).
    """
    selected = tuple(columns)
    if not selected:
        raise ValueError("finite_check requires at least one column")
    identities = tuple(identity_fields)
    if not identities:
        raise ValueError("identity_fields must not be empty")

    def invalid(column: str) -> str:
        quoted = _quote(column)
        return f"{quoted} IS NOT NULL AND NOT isfinite(CAST({quoted} AS DOUBLE))"

    counts_sql = ", ".join(
        f"coalesce(sum(CASE WHEN {invalid(column)} THEN 1 ELSE 0 END), 0)" for column in selected
    )
    identity_sql = ", ".join(_quote(field) for field in identities)
    read = _relation(spec) if relation is None else relation
    con = _open(spec)
    try:
        counted = con.execute(f"SELECT {counts_sql} FROM {read}").fetchone()
        non_finite = tuple(
            (column, int(total)) for column, total in zip(selected, counted, strict=True) if total
        )
        examples: list[tuple[str, tuple[str, ...]]] = []
        for column, _total in non_finite:
            rows = con.execute(
                f"SELECT {identity_sql}, {_quote(column)} FROM {read} "
                f"WHERE {invalid(column)} LIMIT {_EXAMPLE_LIMIT}"
            ).fetchall()
            examples.append((column, tuple(repr(row) for row in rows)))
    except duckdb.Error as exc:
        raise VqaprError(
            stage="source.scan.finite",
            family=FailureFamily.DATA,
            failures=[
                Failure.bounded(
                    code="source.scan.finite.unreadable",
                    requirement=(
                        f"columns {', '.join(repr(c) for c in selected)} must be readable "
                        f"from source '{spec.source_id}'"
                    ),
                    observed=str(exc).splitlines()[0],
                    source=FailureSource(file=str(spec.path)),
                    fix=(
                        f"confirm those columns exist with those exact names in '{spec.path}', "
                        "then retry"
                    ),
                    explain=ExplainTopic.SOURCE_ACCESS,
                )
            ],
        ) from exc
    finally:
        con.close()
    return FiniteCheck(columns=selected, non_finite=non_finite, examples=tuple(examples))


_ROWS_BOUND_FACTOR = 3
"""How many times the declared row count the first lower-bound guess reaches back.

The guess is counted in *instants*; the declaration is counted in *rows*, and an instrument does
not publish on every instant. Three is deliberately loose. A guess that is too tight is not wrong
-- the second stage re-reads every instrument that came up short -- it only costs an extra query,
while a guess that is too loose merely gives back part of the saving.
"""

ROWS_BOUND_MIN_BYTES = 16 * 1024 * 1024
"""Below this much parquet, a `RowsLookback` query is read without estimating a bound.

Estimating costs a statement -- the check that says which instruments the bound would have
changed the answer for -- and the bounded query carries the aggregate that keeps that check
current. On a real warehouse the check is worth it: 210 MB of daily prices went from 165 ms to
88 ms per query. On a small source it is pure overhead, because duckdb reads the whole thing in
less time than deciding not to takes; measured on a 200 KB fixture panel, and against the earlier
form that re-checked on every query, estimating made a 2,940-occurrence run 28% *slower*. So the
estimate is gated on the only thing that decides which regime a source is in, and the gate is
measured once per run.
"""

_PROOF_PREFIX = "__vqapr_proof_"
"""Column prefix for the counts a bounded read carries for the next one. Stripped before return."""


@dataclass(frozen=True, slots=True)
class _RowsBound:
    """A lower bound for a `RowsLookback` query, and what it is not safe for.

    A `RowsLookback` declares a count, not a span, so there is no bound to push down and the
    window is evaluated over the whole history of the source on every callback. Applied naively a
    bound silently corrupts the result: a halted or delisted name whose last observation predates
    the bound simply disappears, and the run values that holding from a price that is no longer
    there. No error is raised; the number just changes.

    So the bound is a guess and the guess is proved. An instrument that already has `rows`
    non-null values of *every* declared field inside the bound is provably unaffected by it --
    its newest `rows` values all lie above the bound, which is exactly what the window keeps.
    Every other instrument, including one that published nothing in the window at all, is listed
    in `unbounded` and read without a bound, in the same statement, so the result is the one the
    unbounded query would have produced.

    `cut` is the position `lower` was taken at in the source's instant grid, and it is what makes
    the proof outlive the callback that took it -- see `_rows_bound`.
    """

    lower: object
    unbounded: tuple[str, ...]
    cut: int


def _rows_bound_guess(
    spec: SourceSpec,
    *,
    available_at_field: str,
    evaluation_time: object,
    rows: int,
    session: ScanSession,
) -> tuple[object, int] | None:
    """The bound to aim for, and the grid position it was taken at. Arithmetic, not a statement.

    Returns `None` when there is not enough history to bound, or when the source is small enough
    that reading all of it is cheaper than deciding not to.
    """
    if session.source_bytes(spec) < ROWS_BOUND_MIN_BYTES:
        return None
    grid = session.instant_grid(spec, available_at_field)
    wanted = rows * _ROWS_BOUND_FACTOR
    if len(grid) <= wanted:
        return None
    try:
        cut = bisect_right(grid, evaluation_time)  # type: ignore[type-var]
    except TypeError:
        # A naive availability column against an aware evaluation time, or vice versa. The
        # unbounded query lets duckdb resolve that; guessing here must not be what raises.
        return None
    if cut <= wanted:
        return None
    return grid[cut - wanted], cut


def _prove_rows_bound(
    spec: SourceSpec,
    *,
    instrument_field: str,
    available_at_field: str,
    physical_fields: tuple[str, ...],
    instruments: Sequence[str],
    evaluation_time: object,
    rows: int,
    lower: object,
    cut: int,
    session: ScanSession,
) -> _RowsBound:
    """Ask the source which instruments `lower` would have changed the answer for. One statement.

    This runs once per declared read per run. Afterwards the read carries its own proof forward
    (`_rows_bound`), so this is the cold start rather than a per-callback cost.
    """
    instrument = _quote(instrument_field)
    available = _quote(available_at_field)
    counts = ", ".join(f"count({_quote(physical)})" for physical in physical_fields)
    placeholders = ", ".join("?" for _ in instruments)
    observed = {
        row[0]: row[1:]
        for row in session.connection(spec)
        .execute(
            f"SELECT {instrument}, {counts} FROM {_relation(spec)} "
            f"WHERE {available} <= ? AND {available} >= ? AND {instrument} IN ({placeholders}) "
            f"GROUP BY {instrument}",
            [evaluation_time, lower, *instruments],
        )
        .fetchall()
    }
    unbounded = tuple(
        name
        for name in instruments
        if name not in observed or any(count < rows for count in observed[name])
    )
    return _RowsBound(lower, unbounded, cut)


def _rows_bound(
    spec: SourceSpec,
    *,
    key: tuple[object, ...],
    instrument_field: str,
    available_at_field: str,
    physical_fields: tuple[str, ...],
    instruments: Sequence[str],
    evaluation_time: object,
    rows: int,
    cut: int,
    lower: object,
    session: ScanSession,
) -> _RowsBound:
    """The proof this read applies, taken from the run when one it already holds still covers it.

    A proof is a claim about a *pair*: this bound, at that grid position. It survives to a later
    position without being re-taken, because both halves of what it says are monotone in
    evaluation time.

    Read the claim as "these instruments have `rows` non-null values of every field between
    `lower` and here". Move the near end forward and the window only grows, so an instrument that
    had `rows` values still has them: what was proved safe stays safe, and the exempt list stays a
    superset of what is unsafe now -- which is the direction that keeps the answer right. An
    instrument that has since become safe is merely read unbounded for nothing.

    The far end does not move on its own. `lower` stays where it was proved, one callback's worth
    of grid behind the bound this callback could have guessed, so a reused proof gives back a
    little of the saving and never any of the result. The bound the caller aims for next is proved
    by the read itself (`_PROOF_PREFIX`), so the trailing distance is one callback's, not the
    run's.

    Positions rather than instants because the grid is every distinct availability instant in the
    source: between two adjacent positions there are no rows to count, so equal positions are the
    same claim.
    """
    held = session.rows_bound(key)
    if held is not None and held.cut <= cut:
        return held
    proved = _prove_rows_bound(
        spec,
        instrument_field=instrument_field,
        available_at_field=available_at_field,
        physical_fields=physical_fields,
        instruments=instruments,
        evaluation_time=evaluation_time,
        rows=rows,
        lower=lower,
        cut=cut,
        session=session,
    )
    session.remember_rows_bound(key, proved)
    return proved


def observation_rows(
    spec: SourceSpec,
    *,
    instrument_field: str,
    available_at_field: str,
    key_fields: Sequence[str],
    fields: dict[str, str],
    instruments: Sequence[str],
    evaluation_time: object,
    rows: int | None = None,
    lower_bound: object | None = None,
    session: ScanSession | None = None,
) -> tuple[dict[str, object], ...]:
    """Execute one physical PIT observation query with its lookback pushed into SQL."""
    if (rows is None) == (lower_bound is None):
        raise ValueError("declare exactly one rows or calendar lower bound")
    if not instruments:
        raise ValueError("observation query requires at least one instrument")
    if not fields:
        raise ValueError("observation query requires at least one field")

    instrument = _quote(instrument_field)
    available = _quote(available_at_field)
    ordering_fields = tuple(dict.fromkeys((available_at_field, *key_fields)))
    ascending = ", ".join(_quote(field) for field in ordering_fields)
    descending = ", ".join(f"{_quote(field)} DESC" for field in ordering_fields)
    placeholders = ", ".join("?" for _ in instruments)
    predicates = [f"{available} <= ?", f"{instrument} IN ({placeholders})"]
    parameters: list[object] = [evaluation_time, *instruments]
    physical_fields = tuple(dict.fromkeys(fields.values()))
    aimed: tuple[object, int] | None = None
    bound_key: tuple[object, ...] = ()
    if lower_bound is not None:
        predicates.append(f"{available} >= ?")
        parameters.append(lower_bound)
    elif rows is not None and session is not None:
        # A RowsLookback carries no bound of its own, so without this the window below is
        # evaluated over the source's entire history on every callback. `_rows_bound` returns a
        # bound together with the instruments it would have changed the answer for; those are
        # read with no bound at all, in the same statement, so the result is the one the
        # unbounded query would have produced -- see `_RowsBound`. The bound needs a session
        # because it is only worth taking when the grid it reads, and the proof it takes, can be
        # kept for the rest of the run.
        aimed = _rows_bound_guess(
            spec,
            available_at_field=available_at_field,
            evaluation_time=evaluation_time,
            rows=rows,
            session=session,
        )
        if aimed is not None:
            bound_key = (
                spec.path.as_posix(),
                instrument_field,
                available_at_field,
                physical_fields,
                rows,
                tuple(instruments),
            )
            applied = _rows_bound(
                spec,
                key=bound_key,
                instrument_field=instrument_field,
                available_at_field=available_at_field,
                physical_fields=physical_fields,
                instruments=instruments,
                evaluation_time=evaluation_time,
                rows=rows,
                cut=aimed[1],
                lower=aimed[0],
                session=session,
            )
            if len(applied.unbounded) < len(instruments):
                if applied.unbounded:
                    exempt = ", ".join("?" for _ in applied.unbounded)
                    predicates.append(f"({available} >= ? OR {instrument} IN ({exempt}))")
                    parameters.append(applied.lower)
                    parameters.extend(applied.unbounded)
                else:
                    predicates.append(f"{available} >= ?")
                    parameters.append(applied.lower)
    where = " AND ".join(predicates)

    proofs: list[str] = []
    proof_parameters: list[object] = []
    projections = [
        f"{available} AS {_quote('available_at')}",
        f"{instrument} AS {_quote('instrument')}",
    ]
    if rows is None:
        projections.extend(
            f"{_quote(physical)} AS {_quote(semantic)}" for semantic, physical in fields.items()
        )
        sql = (
            f"SELECT {', '.join(projections)} FROM {_relation(spec)} WHERE {where} "
            f"ORDER BY {ascending}"
        )
    else:
        ranks: list[str] = []
        keep: list[str] = []
        for index, (semantic, physical) in enumerate(fields.items()):
            column = _quote(physical)
            rank = _quote(f"__vqapr_rank_{index}")
            ranks.append(
                f"count({column}) OVER (PARTITION BY {instrument} ORDER BY {descending} "
                f"ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS {rank}"
            )
            selected = f"{column} IS NOT NULL AND {rank} <= {int(rows)}"
            keep.append(f"({selected})")
            projections.append(
                f"CASE WHEN {selected} THEN {column} ELSE NULL END AS {_quote(semantic)}"
            )
        if aimed is not None:
            # The proof for the *next* callback, taken from rows this one is reading anyway. The
            # bound it proves is at or above the one applied above, so the rows that decide it
            # are all inside the window already scanned, and counting them costs no statement.
            # An instrument that keeps no row here is absent from the answer and is treated as
            # unproved, which is the safe direction.
            for index, physical in enumerate(physical_fields):
                proofs.append(
                    f"count(CASE WHEN {available} >= ? THEN {_quote(physical)} END) "
                    f"OVER (PARTITION BY {instrument}) AS {_quote(f'{_PROOF_PREFIX}{index}')}"
                )
                proof_parameters.append(aimed[0])
                projections.append(_quote(f"{_PROOF_PREFIX}{index}"))
        sql = (
            f"WITH gated AS (SELECT *, {', '.join((*ranks, *proofs))} FROM {_relation(spec)} "
            f"WHERE {where}) "
            f"SELECT {', '.join(projections)} FROM gated WHERE {' OR '.join(keep)} "
            f"ORDER BY {ascending}"
        )

    borrowed = _Borrowed(spec, session)
    try:
        cursor = borrowed.connection.execute(sql, [*proof_parameters, *parameters])
        names = tuple(description[0] for description in cursor.description)
        fetched = cursor.fetchall()
    except duckdb.Error as exc:
        raise VqaprError(
            stage="source.scan.observations",
            family=FailureFamily.DATA,
            failures=[
                Failure.bounded(
                    code="source.scan.observations.unreadable",
                    requirement=(
                        "the registered source and physical field bindings must be queryable"
                    ),
                    observed=str(exc).splitlines()[0],
                    source=FailureSource(file=str(spec.path)),
                    fix=(
                        f"confirm every registered physical field name still exists in "
                        f"'{spec.path}', then re-register or fix the source"
                    ),
                    explain=ExplainTopic.SOURCE_ACCESS,
                )
            ],
            mutation=False,
            retry_precondition="fix the registered source or fields, then retry",
        ) from exc
    finally:
        borrowed.close()

    if aimed is None or session is None:
        return tuple(dict(zip(names, row, strict=True)) for row in fetched)

    # A bound was aimed for, so the answer carries its proof: one count per physical field,
    # appended after the declared ones. Read it, keep it for the next callback, drop it here.
    carried = names[: len(names) - len(proofs)]
    counts = range(len(carried), len(names))
    column = names.index("instrument")
    proved = {row[column] for row in fetched if all(row[index] >= rows for index in counts)}
    session.remember_rows_bound(
        bound_key,
        _RowsBound(aimed[0], tuple(name for name in instruments if name not in proved), aimed[1]),
    )
    # Not strict: the proof columns ride past the end of `carried` and are dropped here.
    return tuple(dict(zip(carried, row, strict=False)) for row in fetched)
