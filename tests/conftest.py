"""테스트가 220MB 실데이터에 의존하지 않게 하는 픽스처.

실데이터 대상 테스트는 `@pytest.mark.real_data`로 표시하고, `data/vqapr-dev/price_daily`가
없으면 건너뛴다.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

DEV_DATASET = Path("data/vqapr-dev/price_daily")

# 실데이터와 같은 모양의 최소 픽스처. 종목 2개 x 3세션.
_ROWS = """
    SELECT * FROM (VALUES
      ('A005930', DATE '2024-01-02', TIMESTAMPTZ '2024-01-02 15:30:00+09', 71000, 2024),
      ('A005930', DATE '2024-01-03', TIMESTAMPTZ '2024-01-03 15:30:00+09', 72000, 2024),
      ('A005930', DATE '2025-01-02', TIMESTAMPTZ '2025-01-02 15:30:00+09', 73000, 2025),
      ('BRK/B',   DATE '2024-01-02', TIMESTAMPTZ '2024-01-02 15:30:00+09',    410, 2024),
      ('BRK/B',   DATE '2024-01-03', TIMESTAMPTZ '2024-01-03 15:30:00+09',    412, 2024),
      ('BRK/B',   DATE '2025-01-02', TIMESTAMPTZ '2025-01-02 15:30:00+09',    420, 2025)
    ) AS t(instrument, session_date, available_at, close, year)
"""


@pytest.fixture(scope="session")
def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    return con


@pytest.fixture(scope="session")
def hive_parquet(tmp_path_factory, _con) -> Path:
    """year로 hive 파티션된 디렉터리."""
    out = tmp_path_factory.mktemp("hive") / "price_daily"
    _con.execute(
        f"COPY ({_ROWS}) TO '{out.as_posix()}' "
        "(FORMAT PARQUET, PARTITION_BY (year), OVERWRITE_OR_IGNORE)"
    )
    return out


@pytest.fixture(scope="session")
def flat_parquet(tmp_path_factory, _con) -> Path:
    """파티션 없는 단일 파일. 같은 내용이되 `year`가 없다.

    `year`는 hive 파티션이 **경로에서 되살려내는** 컬럼이지 데이터가 원래 갖고 있던 것이
    아니다. 단일 파일에 그것을 남겨두면 두 배치의 차이가 사라져 비교가 무의미해진다.
    """
    out = tmp_path_factory.mktemp("flat") / "price_daily.parquet"
    _con.execute(
        f"COPY (SELECT instrument, session_date, available_at, close FROM ({_ROWS})) "
        f"TO '{out.as_posix()}' (FORMAT PARQUET)"
    )
    return out


@pytest.fixture(scope="session")
def naive_parquet(tmp_path_factory, _con) -> Path:
    """available_at이 tz 없는 timestamp. 조용히 틀리는 경우를 재현한다."""
    out = tmp_path_factory.mktemp("naive") / "bad.parquet"
    _con.execute(
        f"COPY (SELECT instrument, session_date, "
        f"CAST(available_at AS TIMESTAMP) AS available_at, close FROM ({_ROWS})) "
        f"TO '{out.as_posix()}' (FORMAT PARQUET)"
    )
    return out


@pytest.fixture(scope="session")
def dup_parquet(tmp_path_factory, _con) -> Path:
    """(session_date, instrument)가 유일하지 않고 instrument에 null이 있다."""
    out = tmp_path_factory.mktemp("dup") / "bad.parquet"
    _con.execute(
        f"""COPY (
              SELECT instrument, session_date, available_at, close FROM ({_ROWS})
              UNION ALL
              SELECT instrument, session_date, available_at, close FROM ({_ROWS})
                WHERE instrument = 'BRK/B'
              UNION ALL
              SELECT NULL, DATE '2024-01-04', TIMESTAMPTZ '2024-01-04 15:30:00+09', 1
            ) TO '{out.as_posix()}' (FORMAT PARQUET)"""
    )
    return out


@pytest.fixture(scope="session")
def dev_dataset() -> Path:
    if not DEV_DATASET.exists():
        pytest.skip(f"{DEV_DATASET} not provisioned — run scripts/prepare_dev_data.py")
    return DEV_DATASET
