# 223 — A framework-built view proves nothing twice

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 루프 캠페인 P4 (`docs/refactoring/2026-09-10-the-one-loop-campaign.md`) |
| **측정** | `experiments/exp_221_the_market_clock_cost/` |
| **브랜치** | `redesign/one-loop` |
| **앞선 기록** | `222` (The execution table is read ahead along the market clock) |

---

## 왜 이 변경이 있는가

Compliance 단계가 3,000 종목 하루에 15.7초였고 그중 규칙 자체(`NoShort.observe`)는 거의 없었다.
시간은 규칙에 **건네는 것을 만드는 데** 들었다:

```text
build_account_view → EconomicAccountView.__post_init__ → _copy_weights × 2      9.8 s
    positions 3,000개와 values 3,000개의 id를 _identifier로, 값을 _finite_decimal로 다시 검사
ModelWindow.__init__ → instrument_id × 3,000                                     4.5 s
    점마다 frozen_run.instruments 를 다시 검사
```

둘 다 **이미 증명된 값을 다시 증명하는 것**이었다. `AccountSnapshot`은 커밋될 때 id와 수량을
검증했고, `MarkBatch`는 마킹될 때 값을 검증했고, `frozen_run.instruments`는 preflight가 검증했다.
`EconomicAccountView`의 생성자는 **저자**가 손으로 만들 때를 위한 것인데, 엔진이 점마다 그 문을
지나고 있었다.

## 무엇이 어떻게 바뀌었는가

- `authoring/view.py` — `EconomicAccountView._trusted(...)`: 검증 없이 같은 모양을 만든다.
  `CrossSection._trusted`(기록 `183`)와 같은 관례, 같은 정렬, 같은 읽기 전용 매핑. 저자의
  생성자는 그대로 검증한다.
- `compliance/evaluation.py::build_account_view`, `flow/run/callback.py::_callback_account_view`
  — 엔진이 만드는 두 view가 `_trusted`를 지난다.
- `domain/identifiers.py`·`authoring/_validation.py` — 공백 검사가 문자마다 도는 generator
  (`any(c.isspace() for c in value)`)에서 컴파일된 `\s` 검색 하나로. 판정은 같다 — Python `re`의
  `\s`는 `str.isspace`와 같은 문자 집합이다. `ModelWindow`가 점마다 하던 3,000번의 `instrument_id`가
  그만큼 싸진다. 검증을 없앤 것이 아니라 C로 내린 것이다.

## 측정 — exp_221, 3,000 종목 × 1일

| | 기준선 | P1 | P3 | **P4** |
|---|---|---|---|---|
| run | 117.4 s | 62.3 s | 45.7 s | **32.7 s** |
| `compliance` | 14.5 s | 15.9 s | 15.7 s | **3.8 s** |

실행 간 잡음이 크다(같은 코드로 ±25%). 이 기록부터 벤치마크는 두 번 돌려 작은 값을 적는다.

남은 compliance 3.8초는 규칙의 `observe`와 창(`ModelWindow`) 생성, finding 행이다.

## 가드 — `tests/flow/test_hot_path_costs.py`

- `build_account_view`는 `_copy_weights`를 **0번** 부르고, 저자의 생성자는 두 번 부른다. 두 view는
  같다(`==`, `weight()`).
- `_identifier`·`instrument_id`가 좋은 id(`BRK/B`, `_KOSPI`, 비ASCII)를 받고 공백(탭·NBSP·EM
  SPACE 포함)을 거부한다 — `str.isspace`와 같은 집합.

## 검증

```text
uv run ruff check src/                 All checks passed
uv run pyright                          0 errors
uv run pytest tests/ -q                 1647 passed, 4 skipped
showcase digest                         81/81 (show_003 제외)
```
