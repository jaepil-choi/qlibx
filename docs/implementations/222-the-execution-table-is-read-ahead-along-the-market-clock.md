# 222 — The execution table is read ahead along the market clock

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 루프 캠페인 P3 (`docs/refactoring/2026-09-10-the-one-loop-campaign.md`) |
| **측정** | `experiments/exp_221_the_market_clock_cost/` |
| **브랜치** | `redesign/one-loop` |
| **앞선 기록** | `221` (Rows are collected as rows and travel as columns) |

---

## 왜 이 변경이 있는가

시장 시계의 점마다 `exact_execution_snapshot`이 duckdb 쿼리 하나를 보냈다 — `WHERE trade_at = ?
AND instrument IN (…3,000개…)`. 체결에서 한 번, 보유 장부 평가에서 한 번. 분봉이면 하루 390번이고
3,000 종목에서 그 쿼리 하나가 32 ms, 하루 12.5초였다(exp_221, P1 뒤 기준 `snapshot` 19.6초).

**시장 시계는 정적 병합이다**(기록 `206`). 루프가 첫 점을 걷기 전에 모든 점을 안다. 그러면
점마다 물을 이유가 없다 — 앞으로 걸을 점들을 한 번에 읽어 두고 점마다 잘라 쓰면 된다.

## 무엇이 어떻게 바뀌었는가

- `data/scan.py` — `execution_window_table(since, until, instruments, fields)`: 한 구간의 모든
  행을 `trade_at, instrument` 순서의 Arrow 테이블 하나로. `exact_snapshot_rows`와 같은 projection,
  같은 실패 코드.
- `exchange/execution_table.py` — **`ExecutionSnapshots`**: 시장 시계의 점 목록과 run의 종목
  집합을 들고, `at(instant, target, held)`가 호출되면 그 점을 포함하는 창(기본 20만 행 ≈ 3,000
  종목에서 66점)을 한 쿼리로 읽고 점마다 슬라이스한다. 점의 경계는 `pc.value_counts`로 C에서
  잡고(정렬된 테이블에서 첫 등장 순서), 슬라이스는 행 dict를 만들지 않고 열 셋(넷)만 변환해
  `ExactExecutionRow`를 바로 만든다 — `trade_at`은 슬라이스의 모든 행이 그 점이므로 변환하지
  않는다. 돌려주는 것은 `exact_execution_snapshot`이 그 점에 돌려주던 것과 같다: 같은 행, 같은
  partition(`duplicate`·`missing_target`·`missing_held`). 시계에 없는 점이나 창에 없는 종목은
  `exact_execution_snapshot`으로 떨어진다. 두 경로의 partition 계산은 `_partitioned` 하나다.
- `flow/run/context.py` — `FlowContext.execution_snapshot(...)`: 체결과 평가가 지나는 **한 문**.
  `snapshots`는 horizon이 있을 때 첫 호출에서 세워진다(`events()`가 첫 시장 시계 점보다 먼저
  horizon을 읽는다). 종목 집합은 `frozen_run.instruments ∪ 초기 보유` — 체결 대상은 전자 안
  (`_validate_intent_authority`), 보유는 그 합 안이다. horizon이 없거나 다른 가격을 물으면 정확
  읽기가 답한다.
- `flow/run/execution.py`·`valuation.py` — 그 문으로. 평가는 `with_reference=False`로 전처럼
  reference 가격 없이 받는다.

record는 바뀌지 않는다. digest 81/81.

## 첫 판은 더 느렸다

쿼리는 390 → 4개가 됐는데 run은 62초에서 80초로 **늘었다.** 창의 `trade_at` 30만 개를
`to_pylist`로 Python datetime으로 바꾸고 Python `while`로 경계를 찾은 것(창마다 7초), 그리고
점마다 슬라이스를 `to_pylist()`로 행 dict 3,000개로 바꾼 것(8.6초)이 아낀 쿼리(12.5초)보다
비쌌다. Arrow에서 Python으로 건너오는 셀 하나가 duckdb 쿼리의 행 하나보다 비싸다는 것이
이 기록이 남기는 사실이다. 고친 판이 위의 모양이다.

## 측정 — exp_221, 3,000 종목 × 1일

| | 기준선 | P1 | **P3** |
|---|---|---|---|
| run | 117.4 s | 62.3 s | **45.7 s** |
| `snapshot` | 17.4 s | 19.6 s | **3.9 s** |
| `compliance` | 14.5 s | 15.9 s | 15.7 s (P4) |
| `account_mark` | 68.4 s | 9.5 s | 9.2 s |

## 가드 — `tests/flow/test_hot_path_costs.py`

- 여섯 점이 한 창 안이면 `execution_window_table` 호출 **1회**이고, 점마다의 답이
  `exact_execution_snapshot`과 같다 — 중복 종목과 결측 종목의 partition까지.
- 창이 넷이면 여섯 점에 읽기 2회. 시계 밖의 점과 창 밖의 종목은 정확 읽기로 떨어진다(2회).
- `tests/acceptance/test_time_002.py`의 fault-boundary 테스트는 `data` seam을
  `FlowContext.execution_snapshot`으로 옮겼다 — 체결이 스냅샷을 읽는 자리가 거기다.

## 검증

```text
uv run ruff check src/                 All checks passed
uv run pyright                          0 errors
uv run pytest tests/ -q                 1645 passed, 4 skipped
showcase digest                         81/81 (show_003 제외)
```
