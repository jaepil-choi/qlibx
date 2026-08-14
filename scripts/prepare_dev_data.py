"""개발용 dataset 준비 — FnGuide 일별 시세 CSV를 등록 가능한 parquet으로.

이 스크립트는 **package가 아니라 user 쪽 일을 흉내 낸 것**이다. vqapr는 csv를 읽지 않으며
(PRD §4.0), 원천을 등록 가능한 형태로 바꾸는 것은 user project와 그 agent의 책임이다.
개발 중 실데이터가 필요해서 그 역할을 직접 해본 결과를 남긴다.

    입력   data/DW/fng_stock_daily_prices.csv        721MB, UTF-8, 한글 헤더
    출력   data/vqapr-dev/price_daily/year=YYYY/     220MB, 12개 파티션
    소요   약 2초

출력은 `/data/`가 gitignore되어 있어 커밋되지 않는다. 필요하면 다시 돌린다.

    uv run --with pytz python scripts/prepare_dev_data.py

## 여기서 내린 결정과 그 근거

**available_at = 거래일자 + 15:30 Asia/Seoul.**
    KRX 정규장 종가 시각이다. tz-aware timestamp로 만드는 것이 등록 계약의 요구이며, naive
    timestamp는 저장은 되지만 조용히 틀린다.

    실제로는 2016-08-01에 15:00 -> 15:30으로 바뀌었으므로 그 이전 907,818행은 30분 늦게
    잡힌다. 보수적인 방향(더 늦게 알게 됨)이라 look-ahead는 아니고, 그 30분이 문제가 되는
    연구를 하게 되면 그때 고친다.

**거래일자를 DATE로 변환.**
    원천은 `BIGINT 20150102`다. calendar 유도가 날짜를 요구하므로 정수로는 쓸 수 없다.

**연도 hive 파티션.**
    등록 config에 `hive_partitioned`로 선언해야 한다. 선언하지 않고 읽으면 `year` 컬럼이
    나타나지 않고 가지치기도 일어나지 않는다 — 읽는 방법 자체가 달라진다.

**전 행 유지. 필터링하지 않는다.**
    등록 시점에 정리하고 싶은 것이 몇 가지 보였지만 전부 남겨뒀다. 등록을 막는 것이 아니고,
    그것을 요구하는 operation이 나올 때 실패시키는 것이 PRD §4.3의 progressive requirement
    discovery다. 지금 아는 것만 적어둔다.

        거래정지구분에 NULL 57,956행     체결 테이블을 만들 때 결정해야 한다
        J접두사 708종목 (ELW로 보임)      가격 계보가 달라 대부분 컬럼이 비어 있다
        종가 <= 0 인 375행 (전부 J)       execution이 그 종목에 닿을 때 문제가 된다
        거래량 0 인 393,016행             `거래대금 > 0`을 tradability로 쓰면 정지와 뒤섞인다
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb

SRC = Path("data/DW/fng_stock_daily_prices.csv")
OUT = Path("data/vqapr-dev/price_daily")
SESSION_CLOSE = "INTERVAL 15 HOUR + INTERVAL 30 MINUTE"
TIMEZONE = "Asia/Seoul"


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.sql("SET preserve_insertion_order=false")

    started = time.time()
    con.sql(f"""
        COPY (
          SELECT
            종목약코드,
            CAST(strptime(CAST(거래일자 AS VARCHAR), '%Y%m%d') AS DATE) AS 거래일자,
            (strptime(CAST(거래일자 AS VARCHAR), '%Y%m%d') + {SESSION_CLOSE})
              AT TIME ZONE '{TIMEZONE}' AS available_at,
            기준가, 시가, 고가, 저가, 종가, 전일종가, 수정계수,
            거래량, 거래대금, 유통주식수, 상장구분, 락구분, 거래정지구분, 관리감리구분,
            year(strptime(CAST(거래일자 AS VARCHAR), '%Y%m%d')) AS year
          FROM read_csv_auto('{SRC.as_posix()}')
        ) TO '{OUT.as_posix()}' (FORMAT PARQUET, PARTITION_BY (year), OVERWRITE_OR_IGNORE)
    """)
    elapsed = time.time() - started

    written = sum(f.stat().st_size for f in OUT.rglob("*.parquet"))
    partitions = sorted(p.name for p in OUT.iterdir() if p.is_dir())
    print(f"{OUT}  {written / 1e6:.0f}MB  partitions={len(partitions)}  {elapsed:.1f}s")
    print(f"  {partitions[0]} .. {partitions[-1]}")


if __name__ == "__main__":
    build()
