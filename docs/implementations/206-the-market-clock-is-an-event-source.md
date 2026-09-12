# 206 — The market clock is an event source

| | |
|---|---|
| **작성 시각** | 2026-09-09 KST (+09:00) |
| **캠페인** | 두 시계 캠페인 M6 (`docs/refactoring/2026-09-09-the-two-clocks-campaign.md` 2a·2b) — Stage 2 시작 |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §3 (시계는 둘이다) · §3.1 (한 시각의 순서) |
| **브랜치** | `redesign/two-clocks` |
| **앞선 기록** | `205` (결정은 다음 시장 시계 점에서 체결된다) |

---

## 왜 이 변경이 있는가

M0가 적어 둔 사실: *"pending 슬롯이 하나이고 `AcceptedIntent`와 `PendingValuation` 둘 다 담는다.
Hold는 `_accept_valuation`으로 평가를 예약한다 — 평가에 자기 시계가 없어서 pending 슬롯에 얹혀 탄
것이다."* 루프에는 시계가 하나뿐이었고(전략의 occurrence), 체결 시각은 콜백이 **만들어내는** due
이벤트였다. 그래서 평가는 "어떤 결정이 그 시각을 가리켰을 때"만 일어났다 — Hold조차 다음 print를
가리키는 `PendingValuation`을 예약해야 그 날의 NAV가 생겼다.

설계 §3은 시계를 둘로 나눈다. **시장 시계는 execution table이 가진 모든 timestamp**이고 데이터에서
오며 이미 얼려 있다. 전략 시계는 agenda다. 한 시각에서의 순서(§3.1)는 ACCRUE → EXECUTE → VALUATION →
COMPLIANCE → DECIDE. 평가는 결정이 가리켜서가 아니라 **시장 시계가 그 점을 가지기 때문에** 일어난다.

---

## 무엇이 어떻게 바뀌었는가

### `EventLoop`: 정적 소스 둘, 동적 소스 없음

```
이전   schedule = occurrence 들  +  pending() 이 실행 중에 민팅하는 DueEvent 하나
이후   events()  = OccurrenceEvent 들  ∪  MarketEvent 들   (정렬된 병합, 루프 시작 전에 전부 안다)
```

`flow/engine/loop.py`에서 `DueEvent`와 `pending()`이 사라지고 `MarketEvent(instant)`가 들어왔다.
정렬 키는 `(utc, -1, "")` — 같은 시각에서 시장 시계가 전략 시계보다 먼저다(§3.1: 먼저 결정된 것을
정산하고 평가한 뒤에 새 결정). `run()`은 `events()`를 정렬해 순서대로 `handle`한다. progress 신호는
이벤트마다 그대로 울린다(`test_run_records`가 소스를 읽어 확인하는 것을 새 모양에 맞췄다).

`StrategyEventLoop.events()`가 occurrence에 시장 시계를 합친다 — `ExecutionHorizon.instants`, M5가
"instant 튜플과 `after()` 하나"로 남겨 둔 바로 그것. 결정이 체결할 수 있는 시각의 집합과 장부가
평가되는 시각의 집합이 **하나의 읽기**다. execution authority 없이 선언된 run(연구용)은 시장 시계가
없고 결정의 나열이다. horizon은 `run()` 안에서 게으르게 읽는다 — `StrategyEventLoop` 생성이 물리
소스를 여는 일은 여전히 없다.

### 시장 시계 점 하나에서 일어나는 일

```python
def _handle_market(event):
    pending = state.current.pending_accepted_intent
    if pending is not None and pending.target.target_at == event.instant:
        result = execution.execute_due(pending)        # EXECUTE (+ 그 안의 VALUATION · COMPLIANCE)
    else:
        result = valuation.value_at(event.instant)     # VALUATION · COMPLIANCE
```

pending intent의 target이 **이미 지난** 시각이면 `RuntimeError` — target은 이 시계에서 골랐으므로 그
점은 반드시 걸었어야 한다. 늦은 체결이 아니라 깨진 불변식이다.

`value_at(instant)`는 옛 `value_due(pending)`의 몸통이고 두 가지가 다르다: (1) pending id를
소비하지 않는다 — `prepare_valuation_only`가 `pending_accepted_intent`를 **그대로 둔다.** target이
나중인 결정은 사이의 시장 시계 점들을 지나 살아남아야 한다. (2) `ValuationEvidence.occurrence`가
`None`이다 — 이 평가를 부른 결정은 없다. `monitor_after_commit(pending)`은 `monitor_at(cutoff,
occurrence=)`가 됐다.

### `PendingValuation`이 없어졌다

`context.py`의 타입, `_VALUATION_NAMESPACE`, `callback.py`의 `_accept_valuation`·
`_pending_valuation_key`, `_prepare_callback_publication`의 pending_valuation 분기, `loop.py`의
`_dispatch_pending`이 전부 나갔다. **Hold는 아무것도 예약하지 않는다.** pending 슬롯은 `AcceptedIntent`만
담는다. `DueExecutionTrace.due`는 `MarketEvent`다(이름은 남겼다 — 테스트와 record가 그 이름으로
"체결 쪽 trace"를 세고, 시장 시계 점 하나가 남기는 흔적이라는 뜻은 그대로다).

### 무엇이 같고 무엇이 다른가

- **일별 격자에서는 같다** (AC-7, 아래 검증). 매일 결정하고 매일 15:30에 한 행이 있는 테이블이면
  "결정이 가리킨 시각의 집합"과 "테이블의 시각 집합"이 같은 집합이다. `test_valuation_clock`의 네
  테스트(세션마다 NAV 하나 · 체결 시각에 VALUATION 단계로 · 콜백 행 없이 한 번 · 보유 중 NAV가
  가격을 따라 움직인다)가 손대지 않고 통과했다.
- **촘촘한 격자에서 처음으로 다르다** (그것이 의도). 1분 테이블 위의 `every: 1m` 전략(AC-1
  acceptance): 열한 개 시각 전부에 VALUATION 행이 생기고, 보유 중 NAV가 분마다 오른다.
  `fill: {after: 5m}`으로 결정과 체결 사이에 시장 시계 점을 넷 두면, 그 넷은 보유 장부를 평가할 뿐
  pending 결정을 소비하지 않고, 뒤이은 결정이 pending을 **교체**하므로 체결은 마지막 결정의 target
  09:10에 한 번 난다 — pending 교체 규칙은 이미 옳았다는 M0의 발견이 여기서도 확인됐다.

---

## 무엇을 잃었나

- `DueEvent`, `EventLoop.pending()`, `PendingValuation`, `ValuationHandler.value_due`,
  `monitor_after_commit`, `CallbackHandler._accept_valuation`, `_pending_valuation_key`.
- `prepare_valuation_only`의 `pending_id` 인자. 평가는 더 이상 pending을 소비하지 않는다.
- `tests/domain/test_agendas.py`의 "due가 같은 시각 occurrence보다 앞" → "market instant가 앞".

---

## 검증

```
uv run python -m pytest tests/ -q -m ""       1641 passed + show_001 (아래) → 재실행 9/9 showcase
uv run ruff check src/                         All checks passed
uv run python -m pyright                       0 errors
scripts/showcase_record_digest.py --check      81/81 — 재기록 없이 (AC-7)
```

**AC-7이 그대로 섰다.** showcase 6개의 record 81개 entry가 M5 기준선과 digest까지 같다 — run.json도,
`vqapr.account`·`vqapr.fill`·`vqapr.weight`도. 일별 격자에서 시장 시계가 결정이 가리키던 시각의 집합과
같기 때문이고, 그것이 이 마일스톤의 위험을 재는 자였다.

**첫 스위트에서 떨어진 것은 하나, show_001이었고 그것이 옳은 실패였다.** `UC-TIME-002`의 showcase는
"비선택 행이 더 촘촘한 테이블"과 "정리된 테이블"의 결과 서명을 통째로 비교했는데, 서명 안에 `MARKED`
개수와 trace 개수가 있었다. 시장 시계 점이 셋에서 여섯이 되니 MARKED가 3→6, trace가 6→9 — 계좌는
글자까지 같았다. 설계 §3.3의 보장은 *"frozen callback occurrence 집합이 변하지 않는다"*이지 평가
횟수가 아니므로, 서명을 `outcome`(계좌·결정·체결·피드백)과 `market_clock`(평가 횟수·시장 시계 점 수)
두 반으로 갈랐다. 전자는 같아야 하고 후자는 **커져야** 한다 — 둘 다 단언한다.

**AC-1 acceptance 확장** (`tests/acceptance/test_a_minute_strategy_fills_at_the_next_minute.py`):
열한 개 시장 시계 점 전부에 VALUATION 행, 보유 중 NAV가 분마다 오름; `fill: {after: 5m}`으로 결정과
체결 사이의 시장 시계 점 넷이 pending을 보존하고, 뒤이은 결정이 pending을 교체해 체결은 09:10에 한 번.

---

## 남긴 흔적 — 다음 사람이 같은 구덩이를 피하도록

- **평가만 하는 전이가 pending을 지우면 안 된다.** 옛 `prepare_valuation_only`는 `PendingValuation`을
  소비하려고 `pending_accepted_intent=None`을 썼다. 시장 시계 점마다 평가하는 지금, 그 한 줄이 남아
  있었다면 `after: 5m` 결정은 첫 평가에서 조용히 사라졌을 것이다. AC-1의 둘째 테스트가 정확히 그
  줄을 지킨다.
- **`edit()`의 앵커가 두 함수에 같은 꼴로 있었다.** `prepare_valuation_only`와 `prepare_marked`의
  root 복사 블록이 글자까지 같아 문자열 치환이 2건을 만나 멈췄다. 함수 범위를 먼저 자르고 그 안에서
  치환했다. 같은 파일 안에 복사된 블록이 있을 때의 규칙.
- **빈 end 마커는 "끝까지"가 아니다.** `text.index("", a)`는 `a`를 돌려준다. 꼬리를 자를 때는 슬라이스.

---

## 다음 기록이 이어받을 것

- **M7.** 단계 순서 ACCRUE → EXECUTE → VALUATION → COMPLIANCE → DECIDE를 코드로 고정하고 ACCRUE
  자리를 만든다. 지금 `_handle_market`은 EXECUTE(그 안에 VALUATION·COMPLIANCE) 또는 VALUATION·COMPLIANCE
  두 갈래다 — 체결 경로 안의 평가(`execute_due`의 후반부)와 `value_at`이 같은 단계를 두 벌로 갖고
  있다. M7이 그것을 한 순서표로 편다.
- `SimulationStage.DUE_*` 이름들은 "due"라는 옛 말을 쓴다. 시장 시계의 단계로 이름을 바꾸는 것은
  record의 `timing` 키와 실패 코드(`strategy.due.*`)를 바꾸므로 M7과 함께.
- 시장 시계 점마다 `exact_execution_snapshot` 질의 하나. 1분 격자 250일이면 97,500번 — 설계가 받아들인
  비용이지만, 보유 종목이 없을 때의 스냅샷은 건너뛸 수 있다. Stage 5 후보.
