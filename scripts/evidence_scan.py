"""슬라이스 1·2 증거 — 실데이터로 성공/실패 시나리오를 돌린다.

    uv run python scripts/evidence_scan.py

`data/vqapr-dev/price_daily`가 있어야 한다. 없으면 먼저:

    uv run --with pytz python scripts/prepare_dev_data.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from vqapr.data import scan
from vqapr.data.source import SourceSpec
from vqapr.domain.errors import VqaprError
from vqapr.domain.identifiers import instrument_id

DEV = Path("data/vqapr-dev/price_daily")


def head(n: int, title: str) -> None:
    print(f"\n{'=' * 78}\n[{n}] {title}\n{'=' * 78}")


def timed(label: str, fn):
    t0 = time.time()
    out = fn()
    print(f"    ({label}: {time.time() - t0:.2f}s)")
    return out


def main() -> int:
    if not DEV.exists():
        print(f"missing {DEV} — run scripts/prepare_dev_data.py first")
        return 1

    # ---------------------------------------------------------------- 성공
    head(1, "성공 — 실데이터 스키마를 정규화된 타입으로 읽는다")
    spec = SourceSpec.of("fng_prices", DEV, hive_partitioned=True)
    cols = timed("describe", lambda: scan.describe(spec))
    for name, ctype in cols.items():
        mark = "  <-- 시간 축" if ctype is scan.ColumnType.TIMESTAMP_TZ else ""
        print(f"    {name:<14} {ctype}{mark}")

    head(2, "성공 — logical key가 null 없이 유일하다")
    ok = timed("key_check", lambda: scan.key_check(spec, ("거래일자", "종목약코드")))
    print(
        f"    fields={ok.fields}  null_groups={ok.null_groups}  "
        f"duplicate_groups={ok.duplicate_groups}  ok={ok.ok}"
    )

    head(3, "성공 — hive_partitioned 선언이 읽는 방법을 바꾼다")
    off = SourceSpec.of("fng_prices", DEV, hive_partitioned=False)
    cols_off = scan.describe(off)
    print(f"    hive_partitioned=True   컬럼 {len(cols)}개, 'year' 있음: {'year' in cols}")
    print(f"    hive_partitioned=False  컬럼 {len(cols_off)}개, 'year' 있음: {'year' in cols_off}")
    print("    -> 장식이 아니다. 선언하지 않으면 파티션 키가 컬럼으로 살아나지 않는다")

    head(4, "성공 — instrument_id는 venue가 주는 형태를 그대로 받는다")
    for raw in ("A005930", "BRK/B", "_KOSPI", "BRK.B"):
        print(f"    {raw!r:<12} -> {instrument_id(raw)!r}")
    for bad in ("", "  ", "A005930 "):
        try:
            instrument_id(bad)
        except ValueError as e:
            print(f"    {bad!r:<12} -> 거부: {e}")

    # ---------------------------------------------------------------- 실패
    head(5, "실패 — key가 유일하지 않다 (종목코드만 key로 지목)")
    bad = timed("key_check", lambda: scan.key_check(spec, ("종목약코드",)))
    print(f"    ok={bad.ok}  duplicate_groups={bad.duplicate_groups:,}")
    print("    위반 예시 (bounded):")
    for e in bad.duplicate_examples:
        print(f"      {e}")

    head(6, "실패 — key 컬럼에 null이 있다 (상장구분을 key로 지목)")
    nul = timed("key_check", lambda: scan.key_check(spec, ("거래일자", "상장구분")))
    print(
        f"    ok={nul.ok}  null_groups={nul.null_groups}  duplicate_groups={nul.duplicate_groups:,}"
    )
    print("    null 예시 (bounded):")
    for e in nul.null_examples:
        print(f"      {e}")

    head(7, "실패 — 경로가 없다. 기계 판독 형태로 나온다")
    missing = SourceSpec.of("nope", Path("data/vqapr-dev/does_not_exist"))
    try:
        scan.describe(missing)
    except VqaprError as err:
        print("    사람이 읽는 것:")
        for line in str(err).splitlines():
            print(f"      {line}")
        print("    agent가 읽는 것:")
        print(
            "      "
            + json.dumps(err.as_dict(), ensure_ascii=False, indent=2).replace("\n", "\n      ")
        )

    head(8, "실패 — parquet이 아니다")
    junk = Path("data/vqapr-dev/_not_parquet.txt")
    junk.write_text("not a parquet", encoding="utf-8")
    try:
        scan.describe(SourceSpec.of("junk", junk))
    except VqaprError as err:
        d = err.as_dict()
        print(f"    stage={d['stage']}  mutation={d['mutation']}")
        for f in d["failures"]:
            print(f"    [{f['code']}] {f['requirement']}")
            print(f"      observed: {f['observed']}")
    finally:
        junk.unlink(missing_ok=True)

    print("\n" + "=" * 78)
    print("모든 시나리오 실행 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
