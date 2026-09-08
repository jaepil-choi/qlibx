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
def execution_parquet(tmp_path_factory, _con) -> Path:
    """실제 execution 계약 모양의 2종목 x 3세션 parquet."""
    out = tmp_path_factory.mktemp("execution") / "krx_daily.parquet"
    _con.execute(
        f"""COPY (
            SELECT * FROM (VALUES
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true,  99.0, 100.0),
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'B', true,  48.0,  50.0),
              (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', true, 101.0, 103.0),
              (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'B', false, 51.0,  51.0),
              (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'A', true, 104.0, 105.0),
              (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'B', true,  52.0,  53.0)
            ) AS t(trade_at, instrument, is_tradable, open, close)
        ) TO '{out.as_posix()}' (FORMAT PARQUET)"""
    )
    return out


@pytest.fixture(scope="session")
def model_price_parquet(tmp_path_factory, _con) -> Path:
    """PIT window와 DataModel materialization용 sparse-field 가격 parquet."""
    out = tmp_path_factory.mktemp("model-price") / "price_daily.parquet"
    _con.execute(
        f"""COPY (
            SELECT * FROM (VALUES
              (DATE '2024-03-05', TIMESTAMPTZ '2024-03-05 15:30:00+09',
               'A', 100.0, 10.0),
              (DATE '2024-03-06', TIMESTAMPTZ '2024-03-06 15:30:00+09',
               'A', 103.0, NULL),
              (DATE '2024-03-07', TIMESTAMPTZ '2024-03-07 15:30:00+09',
               'A', 105.0, 12.0),
              (DATE '2024-03-08', TIMESTAMPTZ '2024-03-08 15:30:00+09',
               'A', 999.0, 99.0),
              (DATE '2024-03-05', TIMESTAMPTZ '2024-03-05 15:30:00+09',
               'B',  50.0, 20.0),
              (DATE '2024-03-06', TIMESTAMPTZ '2024-03-06 15:30:00+09',
               'B',  51.0, NULL),
              (DATE '2024-03-07', TIMESTAMPTZ '2024-03-07 15:30:00+09',
               'B',  53.0, 22.0),
              (DATE '2024-03-08', TIMESTAMPTZ '2024-03-08 15:30:00+09',
               'B', 999.0, 99.0)
            ) AS t(session_date, available_at, instrument, close, volume)
        ) TO '{out.as_posix()}' (FORMAT PARQUET)"""
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
def unprepared_parquet(tmp_path_factory, _con) -> Path:
    """준비가 덜 된 원천. 등록이 거절해야 하는 것들을 한 파일에 모아 둔다.

    `available_at`은 멀쩡하다 -- 여기서 재는 것은 **노출되는 field 컬럼**이고, 각 테스트는
    자기가 말하는 컬럼 하나만 `fields`로 지목한다. 그래서 이 파일은 "무엇이든 거절된다"가
    아니라 "지목된 것만 검사된다"도 같이 보인다.

    close   NaN과 inf를 담은 numeric      -> 값 단계가 거절
    volume  NULL을 담은 numeric           -> 통과한다. NULL은 없는 관측이지 틀린 수가 아니다
    stamped_at  tz 없는 timestamp         -> 스키마 단계가 거절, I/O 없이
    payload     scalar가 아닌 값          -> 스키마 단계가 거절, I/O 없이
    """
    out = tmp_path_factory.mktemp("unprepared") / "unprepared.parquet"
    _con.execute(
        f"""COPY (
            SELECT * FROM (VALUES
              ('A005930', DATE '2024-01-02', TIMESTAMPTZ '2024-01-02 15:30:00+09',
               71000.0, 12.0, TIMESTAMP '2024-01-02 15:30:00', {{'unit': 'KRW'}}),
              ('A005930', DATE '2024-01-03', TIMESTAMPTZ '2024-01-03 15:30:00+09',
               'nan'::DOUBLE, NULL, TIMESTAMP '2024-01-03 15:30:00', {{'unit': 'KRW'}}),
              ('BRK/B',   DATE '2024-01-02', TIMESTAMPTZ '2024-01-02 15:30:00+09',
               410.0, 20.0, TIMESTAMP '2024-01-02 15:30:00', {{'unit': 'USD'}}),
              ('BRK/B',   DATE '2024-01-03', TIMESTAMPTZ '2024-01-03 15:30:00+09',
               'inf'::DOUBLE, 21.0, TIMESTAMP '2024-01-03 15:30:00', {{'unit': 'USD'}})
            ) AS t(instrument, session_date, available_at, close, volume, stamped_at, payload)
        ) TO '{out.as_posix()}' (FORMAT PARQUET)"""
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
def sample_panel(tmp_path_factory):
    """The shipped sample panel, built ONCE per session from the local warehouse.

    The build reads the warehouse CSV and writes two parquet files, about 36 seconds; nine tests
    used to build it each, which was five minutes of a `test_all` doing the same thing over and
    over (record `169`). The panel is read-only parquet, so every test registers the same files
    into its own project through `journey.install(project, panel=sample_panel)`.
    """
    from tests.sample.build import WAREHOUSE, build

    if not WAREHOUSE.exists():
        pytest.skip(f"warehouse {WAREHOUSE} is not provisioned")
    return build(tmp_path_factory.mktemp("sample-panel"))


@pytest.fixture(scope="session")
def dev_dataset() -> Path:
    if not DEV_DATASET.exists():
        pytest.skip(f"{DEV_DATASET} not provisioned — run scripts/prepare_dev_data.py")
    return DEV_DATASET
