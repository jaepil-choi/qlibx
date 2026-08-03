# qlibx Architecture

Status: draft
Canonical requirements: `docs/qlibx-prd.md`
Borrow research: `docs/research/engine-borrow-benchmark-map.md`

이 문서는 PRD가 규정한 product requirement를 만족하는 **구현 설계**를 기술한다. PRD가 정본이고 이
문서는 그것을 만족하는 하나의 구조다. 둘이 충돌하면 PRD가 우선한다.

이 문서가 정하는 것: layer 경계, 책임 배분, 불변식, 핵심 계약의 shape, 의존 방향, 차용 출처.
이 문서가 정하지 않는 것: 최종 public name, 함수 시그니처의 세부, 파일 분할 단위.

---

## 1. 설계 명제

> **qlibx는 backtester가 아니라 정보 통제 장치다. Backtest는 그 장치가 하는 일 중 하나다.**

체결 계산, 손익 누적, 성과 지표는 어렵지 않다. 검증된 구현이 reference에 이미 있고 차용하면 된다.
어려운 것은 이것이다.

> **지금 이 시점에, 이 코드가, 이 데이터를 봐도 되는가?**

PRD 요구사항의 압도적 다수가 이 문제다 — §4.4 PIT, §7.6 no-look-ahead, §2.4 monitoring authority,
§4.3 actual state authority, §9.4 path-dependency. 전부 "무엇을 무엇에게 보여줄 것인가"다.

그리고 경계는 계산과 달리 **틀려도 예외가 발생하지 않는다.** 결과가 좋아질 뿐이다. 따라서 경계는
관습이나 코드 리뷰가 아니라 **구조**로 강제해야 한다.

이 명제에서 아키텍처의 중심에 **gate**가 놓인다는 결론이 나온다.

---

## 2. 멘탈 모델

### 2.1 상태를 가진 것은 셋뿐이다

```
① Clock     지금 몇 시인가        — 시간을 움직이는 유일한 주체
③ Gate      무엇을 볼 수 있는가    — 시야를 정하는 유일한 주체
⑤ Ledger    무엇을 갖고 있는가    — 상태를 갖는 유일한 주체
```

나머지 전부는 **순수 함수**다.

- 시간을 모른다 (`datetime.now()`를 부르지 않는다)
- 상태를 갖지 않는다 (`self`에 저장하지 않는다)
- 준 것만 본다 (전역 접근을 하지 않는다)

부품이 몇 개로 늘어나든 규율을 지킬 곳은 셋이다. 나머지는 자유롭게 교체·확장·테스트할 수 있다.

### 2.2 여섯 layer

```
┌──────────────────────────────────────────────────────┐
│ ① kernel    Clock · Event · Queue                    │  시간
├──────────────────────────────────────────────────────┤
│ ② flow      on_decision / on_mark / on_monitor       │  순서
│             Executor (sub-flow)                       │
├──────────────────────────────────────────────────────┤
│ ③ gate      Context 생성 · cutoff · bounded load     │  시야  ★
├──────────────────────────────────────────────────────┤
│ ④ judge     alpha · construct · convert              │  계산
│             validate · exchange.match                 │
├──────────────────────────────────────────────────────┤
│ ⑤ ledger    Position · Account                        │  상태
├──────────────────────────────────────────────────────┤
│ ⑥ evidence  Artifact · Catalog · Lineage             │  증거
└──────────────────────────────────────────────────────┘
```

부수효과는 **② flow에만** 있다. ③④는 순수하고, ⑤⑥은 변경 경로가 좁게 정의된 저장소다.

`on_decision`이 길어지면 계산이 flow로 흘러들어온 신호다.

### 2.3 흐름과 되먹임

```
   Clock ──tick──→ Gate ──context──→ Judge ──(result, diag)──→ Ledger ──→ Evidence
                     ↑                                            │
                     └────────── 다음 tick의 bounded input ────────┘
```

되먹임 edge가 PRD §2.4 closed loop이다. 다음 decision은 requested target이 아니라 **ledger의 실제
상태**를 gate를 통해 받는다.

---

## 3. 반복 원자

모든 event 처리가 같은 모양이다.

```
시각이 온다
  ① gate가 context를 만든다          ← 여기서만 "볼 수 있는 것"이 정해진다
  ② 순수 함수에 넣는다                ← 부수효과 없음
  ③ (result, diagnostics)가 나온다   ← 진단이 항상 동반
  ④ ledger에 반영하고 기록한다        ← 유일한 부수효과 지점
```

| event | context cutoff | 순수 함수 | 결과 | ledger |
|---|---|---|---|---|
| `DECISION` | t-1 close | alpha → construct → convert → validate | orders + diagnostics | executor에 위임 |
| `EXECUTION` | 체결 시점 | exchange.match | fills + diagnostics | apply |
| `MARK` | t close | valuation | NAV | mark |
| `MONITOR` | monitoring time | constraint evaluation | findings | **건드리지 않음** |
| `FUNDING`* | 정산 시점 | carry 계산 | cash delta | apply |

`MONITOR`만 ④에서 ledger를 변경하지 않는다. PRD §4.3 "monitoring finding은 account를 소급 변경하지
않는다"가 표에서 직접 보인다.

\* `FUNDING`은 perpetual 확장 시 추가되는 event다. §16 참조.

새 event를 추가할 때 이 표의 행을 채우면 설계가 끝난다.

---

## 4. 불변식

아키텍처의 실체는 부품 목록이 아니라 어겨서는 안 되는 규칙이다. 각 항목은 테스트 가능해야 한다.

| # | 불변식 | 검증 방법 |
|---|---|---|
| **I1** | Clock만 시간을 움직인다. 어떤 부품도 `datetime.now()`를 부르지 않는다 | 소스 스캔 테스트 |
| **I2** | Judge는 context 밖 데이터에 접근하지 않는다. 전역 provider/cache/모듈 상태 금지 | import 방향 테스트 + context 필드 검사 |
| **I3** | 자식 context의 cutoff는 부모보다 넓어질 수 없다 | `derive()` 속성 테스트 |
| **I4** | Ledger가 유일한 mutable state. 변경 경로는 `apply`/`mark` 둘뿐 | 공개 API 표면 테스트 |
| **I5** | 모든 judge 함수는 `(result, diagnostics)`를 반환한다 | 시그니처 테스트 |
| **I6** | Catalog는 append-only. 같은 identity + 다른 content는 conflict 실패 | 발행 테스트 |
| **I7** | 같은 frozen config + 같은 데이터 → 같은 event 순서 → 같은 결과 | 2회 실행 비교 |

**I1**이 가장 자주 깨진다. Backtest에서 wall clock을 읽는 것은 조용한 재현성 파괴다.

**I5**는 PRD §4.6과 §11.3을 타입으로 강제하는 장치다. 진단을 버리려면 `_`로 명시적으로 받아야 하고,
그러면 코드 리뷰에서 잡힌다.

---

## 5. ① kernel

### 책임

시간을 앞으로 감고, 등록된 timer가 만든 event를 시각순으로 뱉는다. 그것뿐이다.

Kernel은 alpha, order, market이 무엇인지 모른다. `Callable`만 안다.

### 계약

```python
@dataclass(frozen=True, slots=True)
class Event:
    name: str            # "DECISION" | "MARK" | "MONITOR" | ...
    ts: Timestamp
    priority: int        # 동시각 결정론
    payload: object | None = None

class Handler(NamedTuple):
    event: Event
    callback: Callable[[Event], None]

class Clock(Protocol):
    def set_timer(self, name, schedule, callback, priority) -> None: ...
    def advance_to_next(self) -> list[Handler]: ...   # 시각순 정렬 보장
    def is_finished(self) -> bool: ...
```

### event / callback / handler 의 소속

| | layer | 정체 | 생성자 | 수명 |
|---|---|---|---|---|
| `Event` | ① kernel | 불변 데이터 | Clock | 기록 가능 |
| `Handler` | ① kernel | `(event, callback)` 묶음 | Clock | 일회용 |
| callback | ② flow | 함수 | **우리가 작성** | 상태 없음 |

Kernel은 callback이 무엇을 하는지 모른다. 따라서 가짜 callback으로 순서만 검증하는 독립 테스트가
가능하다.

### 동시각 순서

같은 timestamp의 event는 `priority` 오름차순으로 처리한다. `MARK`(10)가 `MONITOR`(20)보다 먼저여야
monitoring이 갱신된 account를 읽는다. 시각을 인위적으로 벌리는 대신 priority로 표현한다 — 순서의
이유가 코드에 남기 때문이다.

### backtest / live 교체

```
BacktestClock   데이터 끝까지 즉시 감는다
LiveClock       실제 시각을 기다린다
```

이 교체가 backtest와 production을 가르는 **유일한 지점**이다. ②~⑥은 변경되지 않는다.

### 채택하지 않는 것

qlib `TradeCalendarManager`(`backtest/utils.py` L23)는 `freq` 하나와 `trade_step` 하나를 갖는다.
독립 cadence를 가진 병렬 clock을 표현할 수 없다. `NestedExecutor`(`backtest/executor.py` L310)는
계층만 제공하며 형제 관계를 표현하지 못한다.

---

## 6. ② flow

### 책임

원자를 실행한다. 무엇을 어떤 순서로 부를지만 안다. 계산하지 않는다.

```python
def on_decision(ev: Event) -> None:
    ctx      = gate.decision_context(ev.ts)
    w,  d1   = alpha(ctx)
    tgt, d2  = construct(w, ctx)
    orders, d3 = convert(tgt, ctx)
    verdict, findings = validate(orders, ctx)

    recorder.write(w, tgt, orders, d1, d2, d3, findings)
    if verdict.blocked and not verdict.override:
        return                                   # PRD §10.9

    result = executor.execute(orders, ctx, sink=ledger.fill_sink())
    recorder.write(result)


def on_mark(ev: Event) -> None:
    ctx = gate.mark_context(ev.ts)
    ledger.mark(ctx.close_prices())
    recorder.write(ledger.snapshot(as_of=ev.ts))


def on_monitor(ev: Event) -> None:
    ctx      = gate.monitor_context(ev.ts)
    snap     = catalog.latest_account_snapshot(as_of=ev.ts)
    findings = compliance.evaluate(snap, ctx)
    recorder.write(findings)                     # ledger를 건드리지 않는다
```

`on_monitor`가 `ledger`가 아니라 `catalog`에서 읽는 것에 주의한다. PRD §13.3이 monitoring을
"pure artifact consumer"로 규정하며, 이래야 저장된 이력을 strategy rerun 없이 `as-was`/`as-if`로
재평가할 수 있다 (§7.11).

### Executor는 sub-flow다

**Exchange와 Executor는 다른 것이다.**

```
Exchange   주문 1건이 얼마나 체결되나        순수 함수. ④ judge. 시간 개념 없음.
Executor   주문 여러 건을 언제 어떻게 넣나   sub-flow. ② flow. 계산하지 않음.
```

```
on_decision (flow)
    │ executor.execute(orders, ctx, sink)
    ▼
┌────────────────────────────────────────────┐
│ Executor (sub-flow)                         │
│   for 시점 in 자기 일정:                     │
│       inner = ctx.derive(그 시점)  ──────────┼→ ③ gate
│       fill, diag = exchange.match(...) ─────┼→ ④ judge
│       sink.apply(fill)                 ─────┼→ ⑤ ledger (좁은 port)
│   return ExecutionResult(fills, diagnostics)│
└────────────────────────────────────────────┘
```

교체는 계약 하나로 이루어진다.

```python
class Executor(Protocol):
    def execute(self, orders: list[Order], ctx: Context,
                sink: FillSink) -> ExecutionResult: ...
```

```
DailyCloseExecutor   일정: t일 종가 1회
MinuteExecutor       일정: 분봉 순회 + slicer(TWAP/VWAP/POV)
```

둘은 `exchange.match`를 공유한다. **산술은 같고 일정만 다르다.** 이것이 교체가 성립하는 이유다.
Alpha, portfolio construction, conversion, validation은 변경되지 않는다.

### FillSink — 좁은 port

Executor에게 `Ledger` 전체를 주면 I4가 깨진다.

```python
class FillSink(Protocol):
    def apply(self, fill: Fill) -> None: ...      # 쓰기 — 이것만
    def cash(self) -> Money: ...                  # 읽기
    def position(self, symbol: str) -> Quantity: ...
```

Executor가 할 수 있는 것은 체결 반영뿐이다. `mark()`도, snapshot 생성도, target 주입도 불가능하다.

**읽기가 필요한 이유:** 하루 안에서 체결이 누적되며 현금이 줄어든다. 다음 주문의 clipping은 그
시점 현금을 봐야 한다. Context에 담긴 정적 snapshot으로는 부족하다.

### qlib과의 차이

qlib은 `exchange.deal_order(order, trade_account=account)`로 **Exchange가 account를 직접 변경**한다
(`backtest/exchange.py` L421). 계산기가 상태를 건드린다.

qlibx는 분리한다.

```python
fill, diag = exchange.match(order, quote, cash)   # 순수. 아무것도 바꾸지 않음
sink.apply(fill)                                   # flow가 반영
```

얻는 것: (1) account 없이 체결 산술을 테스트할 수 있다, (2) 같은 주문을 여러 시나리오로 돌릴 수
있다 (what-if, PRD §9.9), (3) `diag`를 버릴 수 없다.

---

## 7. ③ gate ★

**qlibx의 정체성이 있는 layer다.** Reference 세 곳 어디에도 대응물이 없다.

### 책임

1. cutoff 결정 — 이 event가 언제까지 볼 수 있는가
2. bounded load — 선언한 lookback만 적재 (PRD §9.6)
3. 되먹임 주입 — 실제 position, cash, 직전 execution result
4. 파생 규칙 강제 — 자식은 부모보다 넓어질 수 없다 (PRD §7.6)

### 계약

```python
@dataclass(frozen=True)
class Context:
    as_of:  Timestamp      # 지금 몇 시
    cutoff: Timestamp      # 무엇까지 볼 수 있는가

    def derive(self, as_of: Timestamp) -> "Context":
        """자식 context. cutoff는 부모를 넘을 수 없다 — I3."""
```

Context는 세 종류이고 **담는 데이터가 다르다.**

| | 담는 것 | 담지 않는 것 |
|---|---|---|
| `DecisionContext` | signal, universe, benchmark, tradability, 실제 position/cash, 직전 execution result, bounded strategy memory | **t일 가격** |
| `ExecutionContext` | 체결 시점까지의 quote/volume, lot, cost profile | t+1 |
| `MonitorContext` | account snapshot, compliance dataset | **alpha signal** |

### 핵심: 권한 검사가 아니라 부재다

```python
def alpha(ctx: DecisionContext):
    ctx.price_at(today)      # AttributeError — 그런 것이 없다
```

권한 검사는 실수로 우회할 수 있다. 없는 것은 쓸 수 없다.

이것이 §1 설계 명제의 구체적 구현이다. PIT 위반은 예외를 발생시키지 않으므로, 위반 자체가 불가능한
구조여야 한다.

### cutoff 규칙

```
DECISION    cutoff = 직전 관측 경계 (기본 프로파일에서 t-1 close)
EXECUTION   cutoff = 현재 체결 시점        ← DECISION보다 넓다. 정당하다.
inner 전략   cutoff = 부모 executor 이하    ← I3
MARK        cutoff = t close
MONITOR     cutoff = monitoring time, 그리고 snapshot.as_of <= monitoring time
```

실행 계층이 t일 데이터를 보는 것은 정상이다. t일에 체결하기 때문이다. 금지되는 것은 (a) decision
로직이 t일을 보는 것, (b) 어떤 계층이든 t+1을 보는 것이다.

### compliance 분리

PRD §4.4는 compliance evaluator가 strategy가 소비하지 않는 독립 데이터를 요구할 수 있으나, 그것이
자동으로 strategy input이 되어서는 안 된다고 규정한다.

Gate가 이를 구조로 보장한다 — `MonitorContext`의 compliance dataset은 `DecisionContext`에 담기지
않는다. Monitoring finding을 decision에 쓰려면 명시적으로 선언해야 한다.

```python
ctx = gate.decision_context(
    ts,
    monitoring_findings=catalog.findings(before=cutoff),   # 명시적 입력
)
```

이때 (1) 어떤 finding을 소비했는지 기록되고, (2) cutoff가 적용되며, (3) lineage에 dependency edge가
남는다. `self`에 저장하는 방식은 셋 다 잃는다.

---

## 8. ④ judge

### 계약 — 전부 같은 모양

```python
alpha(ctx)                      -> (AlphaWeights,    Diagnostics)
construct(weights, ctx)         -> (PhysicalTarget,  Diagnostics)
convert(target, ctx)            -> (list[Order],     ConversionLog)
validate(orders, ctx)           -> (Verdict,         list[Finding])
exchange.match(order, quote, cash) -> (Fill,         FillDiagnostic)
```

모두 `(result, diagnostics)` 쌍을 반환한다 (I5). 이 layer 전체가 상태를 갖지 않으므로 교체
가능하며, PRD §13.4의 public extension point 대부분이 여기에 있다.

### exchange.match — 차용의 핵심

qlib `_calc_trade_info_by_order`(`backtest/exchange.py` L859-950)의 clipping 순서를 이식한다.

```
deal_amount = order.amount
  → volume 참여 제한                     (L786 _clip_amount_by_volume)
  → impact cost = impact * (val/total)²  (L892)
  → SELL: min(보유, deal) → lot 반올림
          단, 마지막 매도는 반올림 생략   (L904 np.isclose)
          현금이 수수료를 못 내면 deal = 0
  → BUY : 현금 한도 계산                 (L834) → lot 반올림
  → cost = max(val * ratio, min_cost)
  → val <= 1e-5 이면 cost = 0
```

L904의 "마지막 매도에서 lot 반올림 생략"은 생략하면 잔여 수량이 영구히 청산되지 않는 함정을
막는다. 137주 보유 + lot 100주에서 반올림하면 37주가 남고, 다음에도 37 → 0으로 반올림되어 유령
포지션이 된다.

**필수 개조:** qlib은 각 clip 지점에서 `logger.debug`만 남기고 버린다 (L830, L917, L928, L936). qlibx는
구조화된 `FillDiagnostic`을 반환값에 싣는다 (PRD §11.3, §4.6). 산술은 그대로, 진단만 추가한다.

Cost model과 fill model은 nautilus `backtest/models/{fee,fill}.pyx` 방식으로 교체 가능한 인터페이스
뒤에 둔다. PRD §11.2가 profile별 cost/volume policy 명시를 요구하기 때문이다.

### convert — 전면 재작성

qlib의 weight→order 경로는 PRD 금지 목록을 항목별로 실증한다. 차용하지 않는다.

| qlib 위치 | 동작 | 위반 |
|---|---|---|
| `order_generator.py` L115-121 | 현금 부족 시 tradable 전량 매도 폴백 | §4.6 |
| `order_generator.py` L124 | cost를 `max(open, close)`로 근사 | §4.6 |
| `exchange.py` L534 | tradable subset만 남기고 weight 재정규화 | §9.3, §11.3 |
| 전 경로 | skip 사유가 반환값에 없음 | §11.3 |
| `signal_strategy.py` L345 | trigger 없이 매 step 재제출 | §5.6 |
| vnpy `template.py` L138 | bar 없는 종목 조용히 skip | §4.6 |

`convert`의 반환값은 order list와 **instrument별 conversion/rounding/clipping/skip 사유 전체**다.

### validate — pass or deny-with-reason

nautilus `risk/engine.pyx`의 구조를 채택한다. Validator는 strategy와 executor 사이에 물리적으로
위치하며 두 가지만 한다.

```
통과시키거나  (L1185 _send_to_execution)
사유와 함께 거부하거나  (L1073-1132 _deny_*)
```

**조용히 수정하지 않는다.** 주문이 크면 줄이는 것이 아니라 거부하고 이유를 남긴다. 조용한 수정이
허용되면 backtest 결과가 전략 때문인지 engine 보정 때문인지 구분할 수 없다.

PRD §10.8(best-effort adjustment)과 §10.9(independent validation)는 다른 책임이다. 전자는 조정하고
후자는 판정한다. 조정 결과가 존재한다는 사실이 compliance를 보증하지 않는다.

---

## 9. ⑤ ledger

### 계약

```python
class Ledger:
    def apply(self, fill: Fill) -> None: ...            # 상태 변경 ①
    def mark(self, prices: Mapping[str, Price]) -> None: ...  # 상태 변경 ②
    def snapshot(self, as_of: Timestamp) -> AccountSnapshot: ...  # 불변 복사본
    def fill_sink(self) -> FillSink: ...
```

**상태를 바꾸는 방법이 둘뿐이다.** 체결이 들어오거나, 평가하거나. Target weight를 넣어 상태를 바꾸는
경로는 존재하지 않는다 — PRD §4.3이 API 형태로 박혀 있다.

`snapshot()`은 불변 객체를 반환한다. Monitoring이 이를 들고 무엇을 하든 ledger는 변하지 않는다.

### 차용

qlib `backtest/position.py::Position`(L231-500)의 산술을 이식한다.

- `_buy_stock`/`_sell_stock`/`_del_stock` (L342/L352/L384)
- 미보유·보유초과 매도 거부
- `settle_start`/`settle_commit` 2단계 (L487/L493)
- `fill_stock_value` (L280) — 초기 endowment 채우기
- `InfPosition` (L503) — 제약 없는 position. what-if/child research용

qlib `backtest/account.py`:
- `AccumulatedInfo` (L35) — return/cost/turnover 누적
- `update_bar_end` (L338) — bar 종료 mark. PRD §9.7 "no-trade bar에도 account mark"
- `is_port_metr_enabled` (L132) — metric 명시적 활성화

vnpy `PortfolioDailyResult.calculate_pnl`:
- **trading PnL / holding PnL 분해.** qlib에는 없다. PRD §13.2 attribution과 §10.10
  flexible-budget attribution의 출발점이다.

---

## 10. ⑥ evidence

### 계약

```python
class Recorder:
    def write(self, *artifacts) -> list[ArtifactId]: ...   # append-only
```

덮어쓰기 API가 없다 (I6). 같은 identity + 같은 content는 idempotent, 같은 identity + 다른 content는
conflict 실패다 (PRD §12.6).

### Envelope

PRD §12.2가 요구하는 필드를 pydantic 모델로 정의한다 (§11 참조).

payload는 tabular/matrix는 Parquet, metadata/config는 JSON이다. 물리 layout은 nautilus
`persistence/catalog/parquet.py`를 참고한다 — 특히 parquet metadata로 시간 범위를 인덱싱해 전체를
읽지 않는 기법(L570), 중복 제거(L820), 스키마 검증(L781).

표면 API(`save`/`load`/`list_all_*`)는 vnpy `alpha/lab.py::AlphaLab`을 따른다. 단 vnpy에는
fingerprint, lineage, envelope, 원자적 발행이 없으므로 **형태만 차용하고 내용은 새로 만든다.**

카탈로그 인덱스는 duckdb로 둔다 (이미 의존성에 있고 parquet을 직접 질의할 수 있다).

### Lineage

```
dataset snapshot ─┐
fitted model  ────┼→ signal ─┐
other data    ────┘          ├→ alpha weights ─┐
universe/benchmark ──────────┘                 ├→ ensemble
                                               ├→ physical target
constraint declaration ────────────────────────┤
                                               ├→ orders → fills
                                               └→ validation finding
account snapshot ────────────────────────────────→ monitoring finding
```

Edge는 consumer role, 선택된 field/column, version/fingerprint, 시간 호환성을 기록한다. Graph는
acyclic이어야 하며 mutable alias만으로 dependency를 식별하지 않는다 (PRD §12.4).

---

## 11. 타입과 직렬화 정책

### 규칙

> **pydantic은 경계를 넘는 것에, dataclass는 경계 안에서 도는 것에.**

경계는 넷이다: 파일↔메모리, 사용자↔패키지, 프로세스↔프로세스, 외부 OMS↔qlibx.

판단은 두 질문으로 한다.

```
Q1. 잘못된 상태로 만들어질 수 있는가?  (밖에서 오는가)
Q2. 스키마를 남이 읽어야 하는가?
     하나라도 예 → pydantic
     둘 다 아니오 → dataclass
```

### 배치

| pydantic | dataclass / 일반 클래스 |
|---|---|
| `FrozenConfig` | `Event`, `Handler` |
| `ArtifactEnvelope`, `DependencyEdge` | `Context` 3종 |
| `StageError` (§7.5) | `Order`, `Fill` |
| `ConstraintDeclaration` (§7.11) | `Diagnostic` 행 |
| `CapabilityRequirement` (§7.3) | `Position`, `Account` |
| `DatasetRegistration` (§7.2) | `AccountSnapshot` |
| `ExtensionContract` (§13.5) | 통계 반환값 (JSON primitive) |
| `PreparedDecision`, `OMSResult` (§14) | |

pydantic 대상은 전부 **저빈도 + 경계**, dataclass 대상은 전부 **고빈도 + 내부**다.

### 기본 설정

```python
class QlibxModel(BaseModel):
    model_config = ConfigDict(
        strict=True,        # 타입 강제 변환 금지  ← §4.6
        extra="forbid",     # 모르는 필드는 실패    ← §4.6
        frozen=True,        # 생성 후 불변          ← §7.10
        validate_default=True,
    )
```

**`strict=True`가 중요하다.** pydantic 기본 동작은 `"0.05"` → `0.05` 같은 강제 변환인데, 이는 PRD
§4.6이 금지한 silent coercion이다. 마찬가지로 `@field_validator`에서 값을 보정해서는 안 된다 —
검증기가 값을 고치는 순간 우리가 제거하려던 문제를 다시 만든 것이다.

**`extra="forbid"`**는 config 오타를 즉시 실패시킨다. dict 파싱은 오타를 조용히 무시하고 기본값으로
진행하며, 이것이 PRD §4.6이 금지한 동작이다.

### 에러 번역

pydantic `ValidationError`를 그대로 노출하지 않고 §7.5 공개 계약으로 번역한다.

```python
except ValidationError as e:
    raise StageError(
        stage="PROJECT_INIT",
        message="config validation failed",
        expected=FrozenConfig.model_json_schema(),
        context={"fields": [...][:MAX_REPORTED]},   # bounded — §7.5
        requires_user_confirmation=True,
        retryable=False,
        error_id=new_error_id(),
    ) from e
```

`e.errors()`의 `loc`가 필드 경로를 제공하지만 개수를 제한해야 한다 (PRD §7.5 "bounded offending
values").

### 고빈도 데이터의 검증 위치

Diagnostic은 행마다 검증하지 않는다. Arrow 스키마가 이미 타입 검증이다.

```
행 단위 검증  ✗
테이블 단위 스키마 선언 + 1회 검증  ✓
```

pydantic 모델은 **테이블의 계약서** 역할만 하고 인스턴스는 만들지 않는다. 여기서 Arrow 스키마와
JSON Schema를 함께 파생시킨다.

### 부수 효과: 스키마 자동 생성

`model_json_schema()`가 PRD §7.3, §13.5, §13.7의 machine-readable schema 요구를 충족한다. 손으로
관리하는 스키마 문서는 반드시 코드와 어긋나므로 자동 생성이 요구사항 만족의 전제다.

---

## 12. 패키지 layout과 의존 방향

```
src/qlibx/
  kernel/       clock  event  queue  engine          ① 시간
  flow/         decision  mark  monitor  executor/   ② 순서
  context/      base  decision  execution  monitor  gate    ③ 시야  ★
  data/         registry  materialize  calendar  provider
  research/     signal/  alpha/  ensemble/           ┐
  portfolio/    construct  optimizer/                ├ ④ 계산
  execution/    convert  validate  exchange/         ┘
  ledger/       position  account  pnl  sink         ⑤ 상태
  evidence/     artifact  catalog  lineage  recorder ⑥ 증거
  analysis/     statistic  analyzer  report
  config/       frozen  schema
  errors.py     stage 기반 에러 계약 (§7.5)
  models.py     QlibxModel base
```

### 의존 방향

```
kernel     → 없음
context    → kernel, data
judge (research/portfolio/execution) → context 만
ledger     → domain 객체만
evidence   → domain 객체만
flow       → context, judge, ledger, evidence
engine     → 전부 (조립 지점)
```

**judge가 ledger를 import하지 않는 것이 핵심이다.** Ledger 상태가 필요하면 context에 담겨 들어온다.
그래야 gate를 우회할 수 없다 (I2).

### 조립

nautilus `system/kernel.py::NautilusKernel`(L101) 방식의 명시적 생성자 주입을 따른다.

```python
engine = Engine(
    clock    = BacktestClock(calendar),
    gate     = ContextGate(registry, policy),
    alpha    = MyAlpha(),
    executor = DailyCloseExecutor(exchange),
    ledger   = Ledger(initial_cash=...),
    recorder = Recorder(catalog),
)
```

qlib의 `common_infra.get("trade_account")` 문자열 키 서비스 로케이터는 채택하지 않는다. 타입이
사라지고 경계를 강제할 수 없으며, PRD §7.9(process isolation)와 §12.8(parallel agent)이 요구하는
전역 상태 회피와 상충한다.

---

## 13. Walkthrough

기본 프로파일: 일단위 데이터, decision은 t-1까지만 관측, execution은 t일 종가.

```
데이터   12/29 close: A=10,000  B=20,000
        01/02 close: A=10,200  B=19,800
초기현금 10,000,000   수수료 0.015%   lot 10주   제약: 단일종목 50% 이하
```

### 등록

```python
clock.set_timer("DECISION", 매월 첫 거래일 09:00, flow.on_decision, priority=10)
clock.set_timer("MARK",     매 거래일     15:30, flow.on_mark,     priority=20)
clock.set_timer("MONITOR",  매 거래일     15:30, flow.on_monitor,  priority=30)
```

### 2024-01-02 09:00 — DECISION

```
ctx = DecisionContext(as_of=01/02 09:00, cutoff=12/29 15:30)
      → 01/02 가격은 담기지 않는다

alpha      → {A: 0.5, B: 0.5}
construct  → A 50%, B 50%  (현재 전량 현금)
convert    → t-1 가격으로 수량 산정
             A: 5,000,000 / 10,000 = 500주
             B: 5,000,000 / 20,000 = 250주
validate   → 통과
```

### EXECUTION (DailyCloseExecutor)

```
A: 500 × 10,200 = 5,100,000  + 수수료 765
   현금 10,000,000 → 4,899,235          ✓ 전량 체결

B: 요청 250주 = 4,950,000 + 수수료 > 가용 현금 4,899,235
   최대 = 4,899,235 / (19,800 × 1.00015) ≈ 247.4주
   lot 10주 반올림 → 240주
   240 × 19,800 = 4,752,000 + 수수료 713
   현금 4,899,235 → 146,522             ⚠ 240주만 체결

   FillDiagnostic(symbol="B", requested=250, dealt=240,
                  reason="CASH_LIMIT", unfilled=10,
                  clip_stage="cash_then_lot_rounding")
```

주문 순서가 결과를 바꾼다 — A가 먼저 현금을 소진해 B가 잘렸다. 이것이 §8 `convert`가 전 주문
진단을 보존해야 하는 이유다.

### 15:30 — MARK (priority 20)

```
A 500 × 10,200 = 5,100,000
B 240 × 19,800 = 4,752,000
현금             =   146,522
NAV             = 9,998,522        검산: 10,000,000 - 765 - 713 ✓
```

### 15:30 — MONITOR (priority 30)

```
A 비중 = 5,100,000 / 9,998,522 = 51.01%  >  50%

ConstraintFinding(
    metric="max_single_name_weight",
    measured=0.5101, bound=0.50, excess=0.0101,
    severity="WARNING",
    classification="EXECUTION_INDUCED",     # 가격 drift가 아니라 체결 결과
    lineage=[decision_id, order_id_B, fill_id_B],
)
```

의도한 비중은 50%였다. B가 현금 부족으로 덜 체결되어 A 비중이 상승했다. Finding은 기록만 되고 이전
체결을 rollback하지 않는다 (PRD §4.3).

**이 walkthrough가 첫 통합 테스트의 기대값이다.**

---

## 14. 차용 출처 매핑

범례: 🟢 코드 차용(MIT) / 🔵 설계만(LGPL 또는 부적합) / 🔴 반면교사 / ⚪ 순수 창작

모든 line reference는 `references/` 아래 vendored snapshot 기준이다. 각 snapshot의 upstream commit은
해당 디렉터리의 `UPSTREAM.md`에 기록되어 있다. Snapshot을 갱신하면 이 표의 line number를 함께
검증해야 한다.

| reference | commit | 라이선스 |
|---|---|---|
| `references/qlib` | `79633dd` (main) | MIT |
| `references/vnpy` | `1b78494` (master) | MIT |
| `references/nautilus_trader` | `4d14b8c` (develop) | LGPL-3.0 |

### ① kernel

| 항목 | 출처 | 위치 | |
|---|---|---|---|
| Clock 추상, TestClock, LiveClock | nautilus | `common/component.pyx` L130/L623/L839 | 🔵 |
| `advance_time` → 시각순 정렬 반환 | nautilus | 같은 파일 L790 | 🔵 |
| TimeEvent / TimeEventHandler | nautilus | L1013 / L1144 | 🔵 |
| 동시각 priority | nautilus | `Subscription.priority` L2911 | 🔵 |
| 단일 시간축 정렬 순회 | vnpy | `alpha/strategy/backtesting.py` L156-166 | 🟢 |
| 단일 freq/step 캘린더 | qlib | `backtest/utils.py` L23 | 🔴 |

### ② flow

| 항목 | 출처 | 위치 | |
|---|---|---|---|
| 일단위 executor 골격 | qlib | `backtest/executor.py` L513, L561 | 🟢 |
| 계층 위임 아이디어 | qlib | 같은 파일 L310 `NestedExecutor` | 🔵 |
| 일별 순회 + 체결 루프 | vnpy | `alpha/strategy/backtesting.py` `new_bars` | 🟢 |
| executor 교체 계약, 분할 실행 | nautilus | `execution/client.pyx`, `algorithm.pyx` | 🔵 |
| **callback, FillSink** | — | — | ⚪ |

### ③ gate ★

| 항목 | 출처 | 위치 | |
|---|---|---|---|
| **Context 3종, cutoff, derive, bounded load** | — | — | ⚪ |
| 시간 범위 표현 | qlib | `backtest/decision.py` L206-300 `TradeRange` | 🟢 |
| learn/infer 데이터 분리 | vnpy | `alpha/dataset/template.py` L181-194 | 🟢 |
| 명시적 생성자 주입 | nautilus | `system/kernel.py` L101 | 🔵 |
| 문자열 키 서비스 로케이터 | qlib | `common_infra.get(...)` | 🔴 |

nautilus에는 Context 객체 자체가 없다 — 데이터를 msgbus로 push하는 방식이라 "이 시점에 무엇을 볼 수
있나"가 구조로 강제되지 않는다. 실시간 거래에서는 미래 데이터가 물리적으로 없으므로 필요가 없다.
**이 layer는 backtest에서만 필요하고, backtest에서 가장 어려운 부분이며, qlibx의 존재 이유다.**

### ④ judge

| 항목 | 출처 | 위치 | |
|---|---|---|---|
| **체결 clipping 전체 순서** | qlib | `backtest/exchange.py` **L859-950** | 🟢 |
| ↳ volume 참여 제한 | qlib | L786 | 🟢 |
| ↳ 제곱 impact cost | qlib | L892 | 🟢 |
| ↳ 현금 한도 매수량 | qlib | L834 | 🟢 |
| ↳ **마지막 매도 반올림 생략** | qlib | **L904** | 🟢 |
| ↳ lot 반올림 / 거래단위 | qlib | L761 / L728 | 🟢 |
| 상하한가 / 거래정지 / tradability | qlib | L338 / L378 / L404 | 🟢 |
| volume threshold 파싱 | qlib | L295 | 🟢 |
| cost·fill model 교체 인터페이스 | nautilus | `backtest/models/{fee,fill}.pyx` L33/L34 | 🔵 |
| clipping 사유를 debug 로그로 폐기 | qlib | L830, L917, L928, L936 | 🔴 |
| pass / deny-with-reason 구조 | nautilus | `risk/engine.pyx` L584-666, L1073-1132 | 🔵 |
| TradingState | nautilus | 같은 파일 L228 | 🔵 |
| target/actual 이원 관리 | vnpy | `alpha/strategy/template.py` L31-32, L133 | 🟢 |
| 4방향 분해 (숏 대비) | vnpy | 같은 파일 L144-185 | 🟢 |
| ts 함수 22종 | vnpy | `alpha/dataset/ts_function.py` | 🟢 |
| cs 함수 5종 | vnpy | `alpha/dataset/cs_function.py` | 🟢 |
| processor 9종 | vnpy | `alpha/dataset/processor.py` | 🟢 |
| 검증용 팩터셋 | vnpy | `alpha/dataset/datasets/alpha_{101,158}.py` | 🟢 |
| **target→order 변환 전체** | — | — | ⚪ |
| **Finding 스키마, override 기록** | — | — | ⚪ |
| 섹터 중립화 / beta 제거 / hump | — | — | ⚪ |

PRD §8.4 built-in 목록과 대조 시 vnpy가 마지막 3개를 제외하고 전부 커버한다.

### ⑤ ledger

| 항목 | 출처 | 위치 | |
|---|---|---|---|
| Position 매수/매도/삭제, 초과매도 거부 | qlib | `backtest/position.py` L342/L352/L384 | 🟢 |
| settle 2단계 | qlib | L487 / L493 | 🟢 |
| 초기 endowment | qlib | L280 `fill_stock_value` | 🟢 |
| 제약 없는 position (what-if) | qlib | L503 `InfPosition` | 🟢 |
| return/cost/turnover 누적 | qlib | `backtest/account.py` L35 | 🟢 |
| bar 종료 mark | qlib | L338 `update_bar_end` | 🟢 |
| metric 명시적 활성화 | qlib | L132 | 🟢 |
| **trading/holding PnL 분해** | vnpy | `PortfolioDailyResult.calculate_pnl` | 🟢 |
| 마진 계좌 / 마진 모델 (perp, 후속) | nautilus | `accounting/accounts/margin.pyx` L54, `margin_models.pyx` L26 | 🔵 |
| **FillSink 좁은 port** | — | — | ⚪ |

### ⑥ evidence

| 항목 | 출처 | 위치 | |
|---|---|---|---|
| save/load/list 표면 | vnpy | `alpha/lab.py` L20-480 | 🟢 |
| parquet 물리 layout | nautilus | `persistence/catalog/parquet.py` L105 | 🔵 |
| ↳ metadata 시간범위 인덱싱 | nautilus | L570 | 🔵 |
| ↳ 중복 제거 / 스키마 검증 | nautilus | L820 / L781 | 🔵 |
| 결과 envelope 필드 | nautilus | `backtest/results.py` L20 | 🔵 |
| report 직렬화 패턴 | nautilus | `execution/reports.py` L366, L416 | 🔵 |
| reconciliation report 3분할 | nautilus | 같은 파일 L95/L619/L859, `create_flat` L919 | 🔵 |
| **fingerprint, lineage, atomic publication** | — | — | ⚪ |

### ⑦ analysis / 도메인 객체

| 항목 | 출처 | 위치 | |
|---|---|---|---|
| 통계 plugin 구조 | nautilus | `analysis/statistic.py` L25, `analyzer.py` L38/L59 | 🔵 |
| 성과 지표 계산식 | vnpy | `backtesting.py` L228-380 | 🟢 |
| ↳ 파산 시 통계 계산 거부 | vnpy | L280-282 | 🟢 |
| 주문 단위 진단 집계 | qlib | `backtest/report.py` L249-650 `Indicator` | 🟢 |
| ↳ 체결률 / 가격 유리도 | qlib | L330 / L524 | 🟢 |
| PortfolioMetrics 레코드 스키마 | qlib | `report.py` L22, L153 | 🟢 |
| 350줄 단일 함수 통계 | vnpy | L228-380 | 🔴 |
| dataclass 필드 구성 | vnpy | `trader/object.py` L112-200 | 🟢 |
| **Status enum** (부분체결/거부/취소/만료) | vnpy | `trader/constant.py` L30 | 🟢 |
| amount / deal_amount / factor 분리 | qlib | `backtest/decision.py` L36-152 | 🟢 |
| 고정소수점 Price/Qty/Money | nautilus | `model/objects.pyx` | 🔵 |
| 주문 상태 개념 부재 | qlib | `Order` dataclass | 🔴 |

vnpy 통계는 **계산식은 🟢이나 구조는 🔴**이다. 계산식을 추출해 nautilus의 plugin 껍데기에 개별로
담는다.

### ⚪ 구역 요약

참고 코드가 없는 영역은 전부 **경계와 증거**다.

```
③ gate 전체              Context, cutoff, derive, bounded load   ← 가장 큼
② callback, FillSink
④ target→order 변환      전 주문 진단 보존
④ 제약 선언/조정/검증     PRD §10.8~10.9
⑥ envelope / lineage     fingerprint, dependency graph, 원자적 발행
⑥ production outbox      PRD §14
  instrument capability   숏 가능성, 마진, carry (§16)
```

계산은 전부 🟢/🔵이고 경계는 전부 ⚪이다. 이것이 §1 설계 명제의 실증이며, **구축 순서에서 ⚪를 뒤로
미뤄야 하는 근거**다 — 🟢로 기반을 다진 뒤 창작하는 것이 안전하다.

### 라이선스 실무

```
qlib             MIT        🟢 가능
vnpy             MIT        🟢 가능
nautilus_trader  LGPL-3.0   🔵 코드 복사 금지
```

- 🟢 차용 파일 상단에 원출처(파일·함수), 원저작권, 변경 내용을 주석으로 남긴다.
- 저장소 루트에 `NOTICE`를 두고 qlib·vnpy 라이선스 전문을 포함한다.
- 🔵는 개념과 명명만 차용한다. 저작권은 표현(코드)을 보호하고 아이디어(구조)를 보호하지 않는다.
- 🟢/🔵 표기를 코드 주석에 남겨 이후 감사에서 grep으로 추적 가능하게 한다.

---

## 15. 구축 순서

각 단계는 앞 단계의 결과물만 의존한다.

| # | 단계 | 성격 | 비고 |
|---|---|---|---|
| 1 | 도메인 객체 | 🟢 | vnpy 필드 + qlib amount/deal_amount + Status enum |
| 2 | **exchange.match + 진단** | 🟢 | 가장 검증이 중요. §15.1 fixture parity 먼저 |
| 3 | ledger (position/account/PnL) | 🟢 | qlib 산술 + vnpy PnL 분해 |
| 4 | kernel (clock/event/queue) | 🔵 | 20~30줄. 병렬 clock 검증 |
| 5 | gate (Context 3종) | ⚪ | 첫 창작 구간 |
| 6 | flow + convert + executor | ⚪🟢 | §13 walkthrough가 통합 테스트 |
| 7 | validate | 🔵⚪ | |
| 8 | evidence (envelope/catalog) | ⚪ | |
| 9 | analysis plugin | 🔵🟢 | |
| 10 | signal/dataset | 🟢 | vnpy 이식 |
| 11 | production boundary | ⚪ | PRD §14 |

6단계 완료 시 end-to-end long-only backtest가 동작한다. 7단계 이후는 참고 코드가 희박하므로 기반이
굳은 뒤로 배치한다.

### 15.1 체결 산술 parity 검증

`pyqlib`는 dependency가 아니므로 qlib을 in-process oracle로 실행할 수 없다. 2단계의 검증은 **정적
fixture 대조**로 수행한다.

1. `references/qlib`의 `_calc_trade_info_by_order` 경로를 읽어 clipping 단계별 기대값을 손으로
   계산한 fixture를 만든다. 각 fixture는 하나의 clipping 분기를 겨냥한다 — volume 제한, 현금 부족
   매수, 보유 초과 매도, 마지막 매도 lot 생략(L904), 수수료 미달 취소, `trade_val <= 1e-5`.
2. Fixture는 입력(주문·시세·거래량·현금·lot·cost)과 기대 출력(deal_amount, trade_val, cost)을
   명시하며, 근거가 된 qlib 위치를 주석으로 남긴다.
3. qlibx `exchange.match`가 같은 값을 내는지 검증하고, 추가로 반환된 `FillDiagnostic`이 어느
   단계에서 잘렸는지 정확히 지목하는지 확인한다.

Fixture는 qlib 실행 결과가 아니라 qlib **코드를 읽고 도출한 기대값**이다. 따라서 qlib 설치가
필요하지 않고, 대신 각 fixture가 어느 코드 경로를 근거로 하는지 추적 가능해야 한다.

---

## 16. 열린 결정

| # | 항목 | 상태 |
|---|---|---|
| ~~O1~~ | ~~`pyqlib` 의존성 위치~~ | **해결.** `pyproject.toml`에서 완전히 제거. runtime/dev 어느 group에도 두지 않는다. 결과로 in-process parity oracle을 쓸 수 없으므로 §15.1 정적 fixture 대조로 대체한다. 차용 대상 qlib 소스는 `references/`에 보존되어야 한다 (O8) |
| O2 | **polars 도입** | vnpy alpha 코드 전체가 polars. 저장 Parquet / 질의 duckdb / 계산 polars / 경계 pandas 층 분리를 권고. **결정 필요** |
| O3 | **matched capitalization 폐기** | qlib long-only position 제약이라는 전제가 소멸. 대체로 instrument capability 모델(숏 가능성/마진/carry/계약단위/청산) 도입. PRD §11.5~11.7 개정 필요 |
| O4 | hypothetical vs real short | 종목 속성으로 선언. real short 불가 종목의 숏 결과에 hypothetical 낙인을 artifact에 기록 |
| O5 | crypto perpetual 확장 | funding은 `FUNDING` timer로 §3 원자에 그대로 편입. margin account, 계약단위(linear/inverse), 강제청산이 추가로 필요 |
| O6 | pub/sub 도입 시점 | 현재는 callback만. 횡단 관심사(전 이벤트 로깅, 사용자 관측자)가 생기면 검토. 도입 시 delivery 우선순위를 함께 설계해야 I7이 유지된다 |
| O7 | PRD 본문 정리 | §0.3 해석 규칙으로 처리 중. Qlib 전제 서술 195곳의 정식 개정은 별도 revision |
| ~~O8~~ | ~~qlib 소스 보존~~ | **해결.** `references/qlib`을 upstream `main@79633dd` 전체 트리(619 paths)로 교체. 기존 부분 스냅샷(274 paths)은 소스를 담고 있지 않았다. §14 인용이 저장소만으로 해결된다 |

O3~O5는 서로 묶여 있다. 함께 결정하는 것이 낫다.
