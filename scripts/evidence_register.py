"""슬라이스 3 증거 — 등록 선언을 실데이터로 검증한다.

uv run python scripts/evidence_register.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

from vqapr.data.dataset import DatasetRegistration, validate
from vqapr.data.source import SourceSpec
from vqapr.domain.errors import VqaprError

DEV = Path("data/vqapr-dev/price_daily")


def head(n: int, title: str) -> None:
    print(f"\n{'=' * 78}\n[{n}] {title}\n{'=' * 78}")


def report(diagnosis, timing, measured=None) -> None:
    """`validate` returns the registration with its measured span third; splats land it here."""
    stages = f"1단계 {timing.schema_seconds:.2f}s"
    stages += "  2단계 건너뜀" if timing.key_was_skipped else f"  2단계 {timing.key_seconds:.2f}s"
    print(f"    ok={diagnosis.ok}   stage={diagnosis.stage}   ({stages})")
    for failure in diagnosis.failures:
        print(f"    [{failure.code}]")
        print(f"      요구: {failure.requirement}")
        if failure.observed:
            shown = failure.observed
            if len(shown) > 110:
                shown = shown[:110] + " …"
            print(f"      관측: {shown}")
        for example in failure.examples:
            print(f"        · {example}")
        if failure.example_total > len(failure.examples):
            print(f"        … 전체 {failure.example_total:,}건 중 {len(failure.examples)}건")


def main() -> int:
    if not DEV.exists():
        print(f"missing {DEV} — run scripts/prepare_dev_data.py first")
        return 1
    spec = SourceSpec.of("fng_prices", DEV, hive_partitioned=True)

    head(1, "성공 — 실데이터 등록 선언이 계약을 만족한다")
    good = DatasetRegistration.of(
        "price_daily",
        "fng_prices",
        instrument_field="종목약코드",
        available_at="available_at",
        key_fields=("거래일자", "종목약코드"),
        fields={"close": "종가", "open": "시가", "volume": "거래량", "session_date": "거래일자"},
    )
    report(*validate(good, spec))

    head(2, "실패 — 1단계에서 두 문제가 **한 번에** 나온다")
    print("    없는 컬럼을 지목하고, available_at을 DATE 컬럼으로 지목했다")
    both = DatasetRegistration.of(
        "price_daily",
        "fng_prices",
        instrument_field="종목약코드",
        available_at="거래일자",
        key_fields=("거래일자", "종목약코드"),
        fields={"close": "종가2", "volume": "거래량"},
    )
    diagnosis, timing, _measured = validate(both, spec)
    report(diagnosis, timing)
    print("    -> 왕복 한 번에 고칠 것을 전부 받았다")

    head(3, "실패 — 1단계가 막히면 2단계 전체 스캔이 돌지 않는다")
    print("    위 [2]의 2단계 소요를 보라. 없는 컬럼 때문에 8.7M행을 읽을 이유가 없다")
    print(f"    key_was_skipped = {timing.key_was_skipped}")

    head(4, "실패 — available_at이 tz 없는 timestamp면 거부한다")
    print("    실데이터에는 naive 컬럼이 없으므로 그 상황을 따로 만든다.")
    print("    naive timestamp는 저장도 조회도 완벽히 되고 **조용히 틀린다** —")
    print("    등록 시점에 잡지 않으면 아무도 알아채지 못한다")
    naive_path = Path("data/vqapr-dev/_naive_probe.parquet")
    con = duckdb.connect()
    con.execute(
        f"""COPY (SELECT * FROM (VALUES
              ('A005930', TIMESTAMP '2024-01-02 15:30:00', 71000),
              ('A005930', TIMESTAMP '2024-01-03 15:30:00', 72000)
            ) AS t(종목약코드, available_at, 종가))
            TO '{naive_path.as_posix()}' (FORMAT PARQUET)"""
    )
    con.close()
    try:
        naive_spec = SourceSpec.of("naive_probe", naive_path)
        naive = DatasetRegistration.of(
            "naive_probe",
            "naive_probe",
            instrument_field="종목약코드",
            available_at="available_at",
            key_fields=("available_at", "종목약코드"),
            fields={"close": "종가"},
        )
        report(*validate(naive, naive_spec))
    finally:
        naive_path.unlink(missing_ok=True)

    head(5, "실패 — 2단계. key가 유일하지 않다")
    weak = DatasetRegistration.of(
        "price_daily",
        "fng_prices",
        instrument_field="종목약코드",
        available_at="available_at",
        key_fields=("종목약코드",),
        fields={"close": "종가"},
    )
    report(*validate(weak, spec))

    head(6, "실패 — 2단계. key에 null이 있고 유일하지도 않다. 둘 다 나온다")
    nulled = DatasetRegistration.of(
        "price_daily",
        "fng_prices",
        instrument_field="종목약코드",
        available_at="available_at",
        key_fields=("거래일자", "상장구분"),
        fields={"close": "종가"},
    )
    diagnosis, timing, _measured = validate(nulled, spec)
    report(diagnosis, timing)

    head(7, "agent가 읽는 형태")
    try:
        diagnosis.raise_if_failed()
    except VqaprError as err:
        payload = err.as_dict()
        for failure in payload["failures"]:
            failure["examples"] = failure["examples"][:2]
        print(
            "      " + json.dumps(payload, ensure_ascii=False, indent=2).replace("\n", "\n      ")
        )

    print("\n" + "=" * 78)
    print("모든 시나리오 실행 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
