"""물리 층을 여는 유일한 곳 — 창도 점도 아닌 **스캔**.

등록 검증은 창 조회로 답할 수 없는 것을 묻는다 — *"이 컬럼이 있나"*, *"이 key가 전체에서
유일한가"*. 그래서 `store.py`(창 포트)와 별개다. 여기 없으면 검증이 lookback 없는 전체 조회를
요구하게 되고, 그 구멍이 곧 look-ahead 경로가 된다.

**의미를 모른다.** 어느 컬럼이 `available_at`인지는 `datasets.py`가 정한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import duckdb

from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import Failure, FailureFamily, VqaprError

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
class ConditionalPositiveCheck:
    """boolean field가 true일 때 numeric field가 유한한 양수인지의 bounded summary."""

    invalid_rows: int
    examples: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.invalid_rows == 0


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
    if not spec.path.exists():
        raise VqaprError(
            stage="source.scan.open",
            family=FailureFamily.DATA,
            failures=[
                Failure.bounded(
                    code="source.scan.path_missing",
                    requirement=f"source '{spec.source_id}' must point at an existing path",
                    observed=str(spec.path),
                )
            ],
            retry_precondition="create the path, then retry the same operation",
        )
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    return con


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
                )
            ],
        ) from exc
    finally:
        con.close()
    return {name: _normalize(dtype) for name, dtype, *_ in rows}


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
                )
            ],
        ) from exc
    finally:
        con.close()
    return tuple(row[0] for row in rows)


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
                )
            ],
        ) from exc
    finally:
        con.close()
    return ConditionalPositiveCheck(invalid_rows=count, examples=examples)


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
    if lower_bound is not None:
        predicates.append(f"{available} >= ?")
        parameters.append(lower_bound)
    where = " AND ".join(predicates)

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
        sql = (
            f"WITH gated AS (SELECT *, {', '.join(ranks)} FROM {_relation(spec)} WHERE {where}) "
            f"SELECT {', '.join(projections)} FROM gated WHERE {' OR '.join(keep)} "
            f"ORDER BY {ascending}"
        )

    con = _open(spec)
    try:
        cursor = con.execute(sql, parameters)
        names = tuple(description[0] for description in cursor.description)
        return tuple(dict(zip(names, row, strict=True)) for row in cursor.fetchall())
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
                )
            ],
            mutation=False,
            retry_precondition="fix the registered source or fields, then retry",
        ) from exc
    finally:
        con.close()
