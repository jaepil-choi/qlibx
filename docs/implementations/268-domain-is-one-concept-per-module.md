# 268 — domain은 개념 하나에 모듈 하나다

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 개념 트리 (`redesign/concept-tree`), M2 — 계획 `.agent/plans/active/concept-tree-campaign.md` |
| **설계 근거** | `docs/vqapr-architecture.md` §5 · §13 · 부록 A (새 목표 설계, `debdf803`), 오너 결정 D1 · D2 · D5 (2026-09-11) |
| **브랜치** | `redesign/concept-tree` |
| **앞선 기록** | `162`(values.py로 다섯 모듈을 접음), `183`(shapes.py), `192`-`197`(레이어링), `211`(원장 한 모양) |

---

## 왜 이 변경이 있는가

오너가 `src/vqapr/`를 프레임워크의 고리(데이터 → 판단 → 거래소 → 계좌 → 다시 판단)에 대응시키지 못했다. 원인은
고리가 아니라 **폴더를 import 고도로 가른 것**이었다. "두 패키지가 주고받는 값은 `domain/`에"라는 레이어링 규칙이 순환을
없앴지만 개념을 흩었다: 계좌 하나가 `domain/ledger.py` · `domain/account_state.py` · `account/account.py` ·
`account/marking.py` · `domain/values.py`(Mark)에, 목표 포트폴리오가 `portfolio/intents.py` · `portfolio/budgets.py`에,
주문 계획이 `exchange/planning.py`에, `values.py`는 시각 · memory · Side · Mark라는 서로 무관한 넷을 한 파일에 담았다.

이 기록은 캠페인의 첫 코드 단계다. `domain/`을 DDD의 뜻대로 — 값, 불변식을 지키는 aggregate, 순수 도메인 서비스 —
**개념 하나 = 모듈 하나, 모듈 이름 = 안의 주 클래스**로 평평하게 둔다. 계산하는 숫자는 하나도 바뀌지 않는다.

## 무엇이 어떻게 바뀌었는가

| 새 모듈 | 무엇이 들어왔나 |
|---|---|
| `domain/instants.py` | `values.py`의 시각 절 (시간대 · 현지 시각 선언 · 달력 이동) |
| `domain/memory.py` | `values.py`의 memory 절 + `model_state.py` |
| `domain/rows.py` | `shapes.py`의 행 절 (`Scalar` · `Row` · `Rows` · `normalize_*`). 나머지 `shapes.py`는 data 단계(M3)에서 흩어진다 |
| `domain/errors.py` | 그대로 + `inputs.py` (입력 파일 거절) |
| `domain/instrument.py` · `schedule.py` · `cost.py` | `instruments.py` · `agendas.py` · `costs.py`의 이름만 바꿈 (`agenda` 어휘 자체는 깨지는 단계 M11) |
| `domain/intent.py` | `portfolio/budgets.py` + `portfolio/intents.py` — `Budget`은 intent의 필드다 |
| `domain/listing.py` | `values.py`의 `Side` · `side_of` + `exchange/listings.py` |
| `domain/order.py` | `domain/orders.py` + `exchange/planning.py` (`plan_orders`) |
| `domain/fill.py` | `domain/fills.py` + `ledger.py`의 `fill_entries` — 체결을 원장 항목으로 바꾸는 것은 만드는 쪽의 일 |
| `domain/account.py` | `values.py`의 `Mark` · `MarkBatch` · `MarkSummary` + `ledger.py`의 `LedgerEntry` · `FILL_ORIGIN` + `account_state.py` + `account/account.py` |
| `domain/valuation.py` | `account/marking.py` |

사라진 것: `domain/values.py` · `model_state.py` · `inputs.py` · `orders.py` · `fills.py` · `ledger.py` ·
`account_state.py`, 패키지 `account/`, `portfolio/intents.py` · `budgets.py`, `exchange/listings.py` · `planning.py`.

- **원장은 체결을 모른다.** `domain/account.py`는 `domain/fill.py`를 import하지 않는다. 0.15.0에서는 원장 모듈이
  `Fill` · `FillBatch` · `OrderBatch`를 import해서 변환했다. 이제 쿠폰이든 funding이든 새 출처가 생겨도 계좌 모듈은
  바뀌지 않는다(개방-폐쇄).
- 새로 합친 모듈의 docstring은 지금 하는 일을 말한다(D12). "어디서 옮겨 왔나"는 이 기록과 git의 몫이다.
- 호출자 137개 파일(src · tests · showcases · scripts)의 import를 이름 단위로 다시 썼다. 도구는 캠페인 도구
  (`rewrite_imports.py` — 옛 모듈의 이름마다 새 모듈을 적은 표로 `from … import …`를 다시 쓰고, 표에 없는 이름이면 멈춘다;
  `compose_module.py` — 여러 원본의 이름 붙은 정의로 모듈 하나를 짓고, 같은 이름이 두 번 정의되면 멈춘다). 세션
  scratchpad에 있고 저장소에는 넣지 않았다.
- 테스트가 문자열로 쓰는 사용자 컴포넌트 코드(테스트가 파일로 써서 등록하는 거래소 · 전략) 열 곳이 옛 경로
  `vqapr.exchange.listings` · `vqapr.portfolio.budgets`를 import했다. 새 내부 경로가 아니라 **`vqapr.public`**으로 바꿨다 —
  사용자 코드의 표면은 public이고(D8), 이후 단계의 이동에도 깨지지 않는다.
- showcase 컴포넌트 세 파일(`show_001` · `show_004` · `show_009`)이 `Budget` · `PortfolioDirection`을 `vqapr.portfolio.budgets`에서
  가져왔다. 이것도 사용자 코드이므로 `vqapr.public`으로 바꿨다. 이후 단계의 이동이 이 파일들을 다시 건드리지 않는다
  (`vqapr.authoring` 제거는 깨지는 단계 M11의 일이다).
- 테스트 미러: `tests/exchange/test_planning.py` · `test_a_cut_buy_keeps_what_it_sized_to.py` → `tests/domain/` (둘 다
  domain만 본다). 층 표에서 `account`가 빠졌다.

## 목표 설계에서 달라진 셋

설계(`debdf803`)는 `fill.py`에 비용과 `FillRule`까지, `order.py`에 `Side`를 두었다. 옮기면서 확인한 의존이 셋을 바꿨다.
아키텍처 문서의 §5 표 · §13.1 트리 · 부록 A를 같은 커밋에서 고쳤다.

1. **비용은 `domain/cost.py`로 따로.** `listing.py`가 `SideCost`를 쓰고 `order.py`가 `listing.py`를 쓰고 `fill.py`가
   `fill_entries` 때문에 `order.py`(`OrderBatch`)를 쓴다. 비용이 `fill.py`에 있으면 `fill → order → listing → fill` 순환이다.
2. **`Side`는 `domain/listing.py`에.** 상장이 방향을 허용하고 방향마다 비용을 매긴다. `order.py`에 두면 `listing ↔ order`
   순환이다.
3. **`FillRule`은 data 단계(M3)에서 `fill.py`로.** `exchange/conventions.py`가 `vqapr.data`를 import한다 —
   `FillRule.build_horizon`과 horizon 없이 부른 `select_target`이 소스를 스캔한다. 그 두 경로가 `data/execution_table.py`로
   가야 `FillRule`이 층 0에 들어갈 수 있다.

## 트레이드오프

- 합치면서 이름이 겹친 비공개 helper 하나: `_decimal`. `values.py`(Mark의 것)와 `orders.py`의 것은 유한성만 보고 값을
  돌려주지 않고, `account_state.py`와 `planning.py`의 것은 타입도 보고 값을 돌려준다. 어느 하나로 합치면 동작이 바뀌므로
  유한성만 보는 쪽을 **`_check_finite`**로 이름을 바꿨다. 호출은 전부 전과 같이 동작한다.
- `tests/flow/run/test_session_callbacks.py::test_a_callback_frames_its_memory_once`는 `normalize_memory`를 세 모듈에서
  바꿔 끼워 호출 수를 센다. `opening_memory`가 이제 `prepare_model_state`와 같은 `domain/memory.py`에 있으므로, 전에는
  세지 않던(바꿔 끼우지 않은 `values.py`에서 일어나던) 한 번이 세어진다. **두 트리에서 전체 호출을 직접 셌다**: 모든
  vqapr 모듈에서 바꿔 끼우면 옛 트리 12회, 새 트리 12회, 호출한 함수와 횟수가 같다(`opening_memory` 1 ·
  `prepare_model_state` 3 · `_normalized` 1 · `load_model_state` 3 · `_validate_candidate_payload` 4). 한도를
  `5 × callbacks + 1`에서 `+ 2`로 올리고 이 측정을 주석에 적었다. 테스트가 막는 회귀(record `239` 이전: 콜백마다 두 번 더)는
  여전히 걸린다 — 16 > 12.

## 검증

| 검사 | 결과 |
|---|---|
| 기준선 (이 브랜치, 옮기기 전) | test_all 1794 통과 · 5 skip (230 s) · ruff 통과 · pyright 0 · digest 차이 2 (둘 다 `show_003`, test_all이 돌리지 않는 수동 showcase) |
| `uv run python -m pytest tests/ -q -m ""` (test_all) | 1794 통과 · 5 skip (209 s) |
| `scripts/showcase_record_digest.py --check tests/showcases/baseline-record-digest.json` | 0.15.0 기준선 대비 차이 5: `show_003` 2 (수동 showcase) + `show_004` 3 — 그 showcase의 컴포넌트 파일(`show004_models.py`)의 import 한 줄이 바뀌어 datamodel 지문이 바뀌었고, 지문으로 이름 붙는 record 디렉터리와 `run.json`이 따라 바뀌었다. **표는 하나도 다르지 않다.** M3-M10은 이 브랜치에서 새로 기록한 campaign 기준선(81 항목)과 정확히 같아야 한다 |
| `uv run ruff check src/` | 통과 |
| `uv run pyright` | 0 errors |
| `tests/boundaries/test_the_layers_hold.py` | 새 모듈 전부 층 0 안에서만 import, `OPEN` 비어 있음 (test_all에 포함) |
| `normalize_memory` 전체 호출 수, 옛 · 새 트리 | 12 · 12, 호출자 동일 (위 트레이드오프) |
