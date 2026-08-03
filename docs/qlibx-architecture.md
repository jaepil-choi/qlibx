# qlibx Architecture

Status: draft
Canonical requirements: `docs/qlibx-prd.md`
Borrow research: [[engine-borrow-benchmark-map]]
Backend 채택 판단: [[why-not-nautilus-as-a-dependency]]

이 문서는 PRD가 규정한 product requirement를 만족하는 **구현 설계**를 기술한다. PRD가 정본이고 이
문서는 그것을 만족하는 하나의 구조다. 둘이 충돌하면 PRD가 우선한다.

이 문서가 정하는 것: layer 경계, 책임 배분, 불변식, 핵심 계약의 shape, 의존 방향, 차용 출처.
이 문서가 정하지 않는 것: 최종 public name, 함수 시그니처의 세부, 파일 분할 단위.

> **§17 설계 감사 기록을 먼저 읽을 것.** 초안을 네 개의 research scenario에 대조한 결과 다섯 개의
> gap이 확인되었다. I4는 PRD와 모순되어 개정되었고, judge 계약과 §3 event 표는 아직 불완전하며,
> long-short 실행 회계는 설계 미착수다. 해당 절에 상호참조를 달았다.

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
① Clock              지금 몇 시인가        — 시간을 움직이는 유일한 주체
⑤ Ledger / Memory    무엇을 갖고 있는가    — 커밋되는 상태 저장소
```

그리고 이 둘 사이에 **view**가 있다. View는 상태를 갖지 않지만 clock에 묶여 있어서, 조회 결과가
clock의 위치에 따라 달라진다.

```
③ View      무엇을 볼 수 있는가   — 읽기 전용. clock 이 경계를 정한다.
```

나머지 전부는 **계산만 한다**.

- 시간을 스스로 알아내지 않는다 (`datetime.now()`를 부르지 않는다)
- 커밋되는 상태를 직접 쓰지 않는다
- store에 직접 접근하지 않는다 (반드시 view 경유)

부품이 몇 개로 늘어나든 규율을 지킬 곳은 clock, view, 그리고 두 개의 state store다.

### 2.2 여섯 layer

```
┌──────────────────────────────────────────────────────┐
│ ① kernel    Clock · Event · Queue                    │  시간
├──────────────────────────────────────────────────────┤
│ ② flow      on_decision / on_mark / on_monitor       │  순서
│             Executor (sub-flow)                       │
├──────────────────────────────────────────────────────┤
│ ③ view      clock-bound facade · 횡단면 패널 조회     │  시야  ★
├──────────────────────────────────────────────────────┤
│ ④ judge     alpha · construct · convert              │  계산
│             validate · exchange.match                 │
├──────────────────────────────────────────────────────┤
│ ⑤ ledger    Position · Account · Trade · Memory       │  상태
├──────────────────────────────────────────────────────┤
│ ⑥ evidence  Artifact · Catalog · Lineage             │  증거
└──────────────────────────────────────────────────────┘
```

부수효과는 **② flow에만** 있다. ③④는 순수하고, ⑤⑥은 변경 경로가 좁게 정의된 저장소다.

`on_decision`이 길어지면 계산이 flow로 흘러들어온 신호다.

### 2.3 흐름과 되먹임

```
   Clock ──tick──→ Flow ──view──→ Judge ──(result, diag)──→ Ledger ──→ Evidence
     │                 ↑                                      │
     │                 └──── view 는 ledger 를 읽는다 ─────────┘
     └──── clock 위치가 view 의 조회 경계를 정한다
```

되먹임 edge가 PRD §2.4 closed loop이다. 다음 decision은 requested target이 아니라 **ledger의 실제
상태**를 view를 통해 읽는다. 초안과 달리 flow가 snapshot을 조립해 넘기지 않고, judge가 view로
필요한 시점에 조회한다.

---

## 3. 반복 원자

모든 event 처리가 같은 모양이다.

```
시각이 온다
  ① clock 이 그 시각으로 이동한다     ← 여기서 "볼 수 있는 것"이 정해진다
  ② 역할에 맞는 view 를 넘긴다        ← 어떤 종류를 볼지는 view 구성이 정한다
  ③ (result, diagnostics)가 나온다   ← 진단이 항상 동반
  ④ ledger 에 반영하고 기록한다       ← 유일한 부수효과 지점
```

| event | clock 위치 | view | 계산 | 결과 | ledger |
|---|---|---|---|---|---|
| `DECISION` | 09:00 | `DecisionView` | alpha → construct → convert → validate | orders + diagnostics | executor에 위임 |
| `EXECUTION` | 체결 시점 | `ExecutionView` | exchange.match_batch | fills + diagnostics | apply_batch |
| `MARK` | 15:30 | `ExecutionView` | valuation | NAV | mark |
| `MONITOR` | 15:30 | `MonitorView` | constraint evaluation | findings | **건드리지 않음** |
| `FIT`† | 학습 시점 | `FitView` | model.fit | FittedState | Memory (proposed → commit) |
| `FUNDING`* | 정산 시점 | `ExecutionView` | carry 계산 | cash delta | apply |

cutoff 열이 사라진 것에 주의한다. 무엇을 볼 수 있는지는 clock 위치와 각 관측치의 `available_at`이
결정하므로 event마다 명시할 값이 아니다. 일봉의 `available_at`이 15:30이면 09:00 `DECISION`은 당일
종가를 조회할 수 없다 — 별도 설정 없이 시간표에서 유도된다(§7).

`MONITOR`만 ④에서 ledger를 변경하지 않는다. PRD §4.3 "monitoring finding은 account를 소급 변경하지
않는다"가 표에서 직접 보인다.

† `FIT`은 rolling/expanding retraining event다. PRD §8.6이 요구하지만 초안에는 없었다.
`priority`는 `DECISION`보다 앞선다. §17 G3 참조 — view 모델에서는 label의 `available_at`을
`event_time + horizon`으로 선언하면 purge/embargo가 별도 장치 없이 성립한다.

\* `FUNDING`은 perpetual 확장 시 추가되는 event다. §16 참조.

새 event를 추가할 때 이 표의 행을 채우면 설계가 끝난다.

---

## 4. 불변식

아키텍처의 실체는 부품 목록이 아니라 어겨서는 안 되는 규칙이다. 각 항목은 테스트 가능해야 한다.

| # | 불변식 | 검증 방법 |
|---|---|---|
| **I1** | Clock만 시간을 움직인다. 어떤 부품도 `datetime.now()`를 부르지 않는다 | 소스 스캔 테스트 |
| **I2** | 모든 데이터 접근은 clock-bound view를 경유한다. View는 `available_at <= clock.now()`를 우회할 수 없고, store 직접 접근·전역 provider·모듈 상태는 금지한다 | import 방향 테스트 + view 질의 술어 검사 |
| **I3** | 모든 component clock은 kernel이 같은 시각으로 함께 전진시킨다. 어떤 component도 홀로 앞설 수 없다 | clock 단조성 테스트 |
| **I4** | 커밋되는 state store는 Ledger와 Memory 둘이다. 둘 다 flow의 commit boundary에서만 변경된다. Judge는 어느 쪽도 직접 쓰지 않는다 | 공개 API 표면 테스트 |
| **I5** | 모든 judge 함수는 `(result, diagnostics)`를 반환한다 | 시그니처 테스트 |
| **I6** | Catalog는 append-only. 같은 identity + 다른 content는 conflict 실패 | 발행 테스트 |
| **I7** | 같은 frozen config + 같은 데이터 → 같은 event 순서 → 같은 결과 | 2회 실행 비교 |

**I1**이 가장 자주 깨진다. Backtest에서 wall clock을 읽는 것은 조용한 재현성 파괴다.

**I2와 I3도 2026-08-03 개정되었다.** 초안의 I2는 event마다 조립한 context를 전제했고, I3는 그
context의 파생 규칙이었다. View 모델에서는 시간 경계가 clock 한 곳에서 강제되므로 두 불변식이
그에 맞게 다시 쓰였다. §18 참조.

**I4는 2026-08-03 개정되었다.** 초안은 "Ledger가 유일한 mutable state"였으나 이는 PRD와
모순이다. PRD §9.1은 alpha decision이 "result에 proposed next state를 포함하고 runtime commit
boundary에서만 authoritative state로 반영"하도록 요구하고, §9.10은 checkpoint가 "Alpha/strategy
memory와 prior feedback cursor"를 보존하도록 요구한다. 즉 커밋되는 state store는 처음부터 둘이었다.
§17 G1 참조.

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

### Executor는 횡단면 batch sub-flow다

**Exchange와 Executor는 다른 것이다.**

```
Exchange   주문 집합이 얼마나 체결되나       순수 함수. ④ judge. 시간 개념 없음.
Executor   그 집합을 언제 어떻게 넘기나      sub-flow. ② flow. 계산하지 않음.
```

qlibx의 기본 단위는 **decision time의 횡단면**이다. 3000종목 일봉은 같은 순간에 함께 확정되므로
3000개의 개별 event로 쪼개지 않는다. Executor는 한 시점의 주문 집합을 통째로 받아 처리한다.

```
on_decision (flow)
    │ executor.execute(orders, view, sink)
    ▼
┌──────────────────────────────────────────────────┐
│ Executor (sub-flow)                               │
│   q, v = view.quotes(), view.volumes()  ──────────┼→ ③ view
│   fills, diags = exchange.match_batch(  ──────────┼→ ④ judge
│       orders, q, v, sink.cash()                   │
│   )                                               │
│   sink.apply_batch(fills)               ──────────┼→ ⑤ ledger (좁은 port)
│   return ExecutionResult(fills, diags)            │
└──────────────────────────────────────────────────┘
```

### 계약

```python
class Executor(Protocol):
    def execute(self, orders: Orders, view: ExecutionView,
                sink: FillSink) -> ExecutionResult: ...
```

`Orders`는 단건 목록이 아니라 instrument축 배열 묶음이다. `match_batch`는 §8의 clipping 순서를
elementwise 연산으로 수행한다.

```
DailyCloseExecutor   기본. t일 종가 1회, 3000종목 batch.
```

교체 지점은 유지하되 현재 구현은 하나다. 분단위 체결은 요구되지 않는 것으로 확인되었으므로
`MinuteExecutor`는 계획에 넣지 않는다. 필요해지면 같은 계약 뒤에 추가한다 —
[[why-not-nautilus-as-a-dependency]] §4의 재검토 조건 2에 해당한다.

### batch가 closed loop를 해치지 않는다

한 event가 횡단면 전체를 나른다는 것과, 시간 축이 순차라는 것은 서로 독립이다.

```
피드백 유무   →  시간 축이 순차인가로 결정   →  qlibx: 순차. 유지.
event 입도    →  종목별인가 횡단면인가       →  qlibx: 횡단면. batch.
```

시간 축이 순차이므로 다음이 모두 성립한다.

- 부분체결 후 다음 decision은 requested target이 아니라 **실제 보유**에서 계산한다 (PRD §4.3)
- Blocked liquidation은 포지션에 남아 다음 decision에 포함된다 (PRD §7.7)
- 실현손익 누적에 의존하는 stop-loss 같은 path-dependent 정책이 성립한다 (§17 G1, G2)

흔히 "vectorized backtest"로 불리는 것 — `(weights.shift(1) * returns).sum()` 형태의 시간 축
일괄 계산 — 은 이와 다르다. 그쪽은 feedback edge 자체가 없어 PRD §4.3을 만족할 수 없으며
채택하지 않는다. **벡터화 대상은 instrument 축이고 시간 축이 아니다.**

### FillSink — 좁은 port

Executor에게 `Ledger` 전체를 주면 I4가 깨진다.

```python
class FillSink(Protocol):
    def apply_batch(self, fills: Fills) -> None: ...   # 쓰기 — 이것만
    def cash(self) -> Money: ...                       # 읽기
    def positions(self) -> Quantities: ...             # instrument축 배열
```

Executor가 할 수 있는 것은 체결 반영뿐이다. `mark()`도, snapshot 생성도, target 주입도 불가능하다.

**읽기가 필요한 이유:** 하루 안에서 체결이 누적되며 현금이 줄어든다. 다음 주문의 clipping은 그
시점 현금을 봐야 한다. Context에 담긴 정적 snapshot으로는 부족하다.

### qlib과의 차이

qlib은 `exchange.deal_order(order, trade_account=account)`로 **Exchange가 account를 직접 변경**한다
(`backtest/exchange.py` L421). 계산기가 상태를 건드린다.

qlibx는 분리한다.

```python
fills, diags = exchange.match_batch(orders, quotes, volumes, cash)  # 순수
sink.apply_batch(fills)                                             # flow가 반영
```

얻는 것: (1) account 없이 체결 산술을 테스트할 수 있다, (2) 같은 주문 집합을 여러 시나리오로 돌릴
수 있다 (what-if, PRD §9.9), (3) `diags`를 버릴 수 없다.

qlib은 주문 단건 순회이므로 이 분리가 성립해도 batch가 되지 않는다. qlibx는 단위 자체를
instrument축 배열로 두어 `deal_order` 순회를 elementwise 연산으로 대체한다.

---

## 7. ③ view ★

**정보 경계를 강제하는 layer다.** 초안에서는 `gate`가 event마다 snapshot을 조립해 넘기는
구조였으나, 2026-08-03 개정으로 **clock에 묶인 조회 창구(view)** 방식으로 교체되었다. 변경 이유와
근거는 §18에 기록한다.

### 두 개의 경계를 분리한다

초안은 "무엇을 볼 수 있는가"를 하나의 문제로 다뤘다. 실제로는 서로 독립인 두 문제다.

```
시간 경계   언제까지의 데이터를 볼 수 있는가     →  clock 이 결정. 모든 view 공통.
역할 경계   어떤 종류의 데이터를 볼 수 있는가     →  view 구성이 결정. view 마다 다름.
```

이 분리가 개정의 핵심이다. 시간 경계는 한 곳(clock)에서 일괄 강제되고, 역할 경계는 view에 어떤
facade를 묶느냐로 표현된다.

### 시간 경계 — stream 순서가 곧 cutoff다

모든 관측치는 두 개의 시각을 갖는다.

```
event_time      그 사건이 실제로 발생한 시각
available_at    관측 가능해진 시각          ← PRD §4.4의 available_at
```

Runtime data stream은 **`available_at` 오름차순**으로 정렬된다. `event_time`이 아니다.

```python
stream = sorted(observations, key=lambda o: o.available_at)
```

View의 모든 조회에는 `available_at <= clock.now()` 조건이 붙는다. 우회 경로는 없다 — 조건이
질의에 박혀 있고 view 밖의 store 직접 접근은 금지한다(I2).

따라서 **cutoff는 파라미터가 아니라 clock의 위치다.**

```
09:00  DECISION      일봉의 available_at = 15:30 이므로 당일 종가는 조회되지 않는다
15:30  EXECUTION     당일 종가가 조회된다
```

초안이 event마다 명시하던 cutoff 표는 사라진다. 시간표에서 유도되기 때문이다.

**위험은 제거되지 않고 이동한다.** 보장은 전적으로 `available_at`이 등록 시점에 올바로 선언되었는지에
달려 있다. 일봉의 `available_at`을 당일 00:00으로 넣으면 09:00 decision이 당일 종가를 보고, 예외는
발생하지 않는다. PRD §5.1과 §7.2가 availability 선언을 qlibx 소유로 규정하고 §4.4가 qlibx의 보장
범위를 "선언된 availability의 준수"로 한정하므로, 이 배치는 PRD의 책임 분담과 일치한다. 대신
data registration 단계의 검증이 §1 설계 명제를 지탱하는 단일 지점이 된다.

### 역할 경계 — view 구성

| view | 묶는 facade | 제외 |
|---|---|---|
| `DecisionView` | panel(signal/price), universe, benchmark, tradability, positions, cash, 직전 execution result, memory | **compliance dataset** |
| `ExecutionView` | quote/volume, lot, cost profile, positions, cash | signal panel |
| `MonitorView` | account snapshot, compliance dataset | **signal panel, memory** |
| `FitView` | panel(feature/label), universe | positions, cash |

`MonitorView`가 signal을, `DecisionView`가 compliance dataset을 갖지 않는 것이 PRD §4.4의
"compliance-only data를 undeclared strategy input으로 전달하지 않는다"를 구조로 만든다. Monitoring
finding을 decision에 쓰려면 명시적으로 주입해야 한다.

```python
view = views.decision(monitoring_findings=catalog.findings(before=clock.now()))
```

이때 (1) 어떤 finding을 소비했는지 기록되고, (2) `available_at` 조건이 적용되며, (3) lineage에
dependency edge가 남는다.

### 조회 창구 계약

```python
class PanelView(Protocol):
    """횡단면 패널 조회. clock 에 묶인다."""
    def panel(self, field: str, lookback: Lookback) -> DataFrame: ...
    def universe(self) -> Index: ...
    def accessed(self) -> list[AccessRecord]: ...

class PositionView(Protocol):
    def positions(self) -> Mapping[str, Quantity]: ...
    def cash(self) -> Money: ...
    def nav(self) -> Money: ...
```

`Protocol`은 읽기 전용이다. 쓰기 메서드를 노출하지 않는다 — nautilus의 `CacheFacade` /
`PortfolioFacade`와 같은 배치다.

`lookback`은 rows와 duration semantics를 구분하며(PRD §9.6), 질의에 그대로 반영되어 조회량을
한정한다. 초안의 "bounded load 사전 선언"은 불필요해진다 — 조회 자체가 한정적이다.

### 횡단면이 기본 축이다

Reference 세 곳은 모두 instrument별 시계열이 기본 접근 단위다. nautilus `cache.bars(bar_type)`은
한 종목의 deque를 반환하고, 3000종목 패널을 만들려면 3000회 조회해 조립해야 한다. 메모리 상주
방식이라 20년 × 3000종목을 담을 수도 없다.

qlibx의 기본 접근 단위는 **decision time의 횡단면**이다. 따라서 view는 메모리 누적 컨테이너가
아니라 **컬럼 저장소에 대한 시간 한정 질의**로 구현한다.

```
저장   Parquet (available_at 파티션)
질의   DuckDB   WHERE available_at <= :now AND available_at > :now - :lookback
반환   DataFrame (instrument × field)
```

이 부분은 §14에서 여전히 ⚪다. 세 reference 어디에도 대응물이 없다.

### 접근 기록이 lineage가 된다

View는 조회를 기록한다. 따라서 "이 alpha가 실제로 무엇을 읽었는가"가 관측에서 나온다.

```python
weights, memory, diag = alpha(view)
recorder.write(weights, lineage=view.accessed())
```

PRD §7.4는 derived artifact가 의존 input을 stable identity로 기록하도록 요구한다. 선언 기반은
실제 사용과 어긋날 수 있으나 접근 기록은 어긋나지 않는다. 초안의 사전 선언 방식보다 강한 보장이다.

### backtest / live 동형성

View와 judge는 clock이 무엇인지 모른다. Backtest와 live의 차이는 clock 교체와 stream 공급원뿐이다.

```
backtest   BacktestClock + 정렬된 과거 stream
live       LiveClock     + 실시간 도착 stream
```

초안은 gate 구현이 두 벌 필요했다. 개정 후에는 한 벌이다. 두 벌이 어긋나 "backtest는 통과하고
live는 실패하는" 부류의 결함이 구조적으로 제거된다.

---

## 8. ④ judge

### 계약 — 전부 같은 모양

```python
alpha(view)                     -> (AlphaWeights,    ProposedMemory, Diagnostics)
ensemble(members, view)         -> (AlphaWeights,    EnsembleDiagnostics)
construct(weights, view)        -> (PhysicalTarget,  Diagnostics)
convert(target, view)           -> (list[Order],     ConversionLog)
validate(orders, view)          -> (Verdict,         list[Finding])
model.fit(view)                 -> (FittedState,     SelectionEvidence)
exchange.match_batch(orders, quotes, volumes, cash)
                                -> (Fills,          FillDiagnostics)
```

첫 인자는 초안의 snapshot이 아니라 **clock에 묶인 조회 창구**다(§7). Judge는 필요한 시점에
필요한 만큼 조회하며, view가 접근을 기록해 lineage가 된다.

`exchange.match_batch`만 view를 받지 않는다. 주문 집합과 시세·거래량·현금만으로 결정되는 순수
산술이고, 시간 개념이 없기 때문이다(§6). 인자는 instrument축 배열이며 clipping이 elementwise로
수행된다.

> **미완 (§17)** — `alpha`의 `ProposedMemory` 반환(G1), `ensemble`(G5), `model.fit`(G3) 계약은
> shape만 확정되었고 세부는 미설계다.

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

### 이 절의 한계 (§17)

위 차용 계획은 **수량과 현금 회계에만 유효하다.** 세 가지가 빠져 있다.

- **G2 round-trip 회계.** qlib `Position`은 `amount`/`price`/`weight`만 보유하며 `price`는
  취득원가가 아니라 매 bar 덮어써지는 평가가격이다. 평균단가·실현손익·라운드트립이 없으므로
  "직전 거래가 손실이었는가"에 답할 수 없다. 별도 `TradeLedger`가 필요하다.
- **G1 Memory.** 전략 상태는 Ledger와 별개의 committed store다. I4 개정 참조.
- **G4 long-short.** `_sell_stock`이 음수 잔량에서 `ValueError`를 던지므로 이 차용은 구조적으로
  long-only다. Executable short는 담보 모델과 수익률 분모 선언이 선행되어야 한다.

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
clock = 01/02 09:00
view  = DecisionView(clock)
      → 01/02 일봉의 available_at = 15:30 이므로 조회되지 않는다

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

세 reference 모두 **dependency가 아니다.** qlibx는 engine을 직접 구현하며 reference에서는 설계와
산술만 차용한다. nautilus를 execution backend dependency로 채택하지 않은 판단의 근거는
[[why-not-nautilus-as-a-dependency]]에 있다.

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

### ③ view ★

> **초안 정정.** 이 표는 원래 "Context 3종, cutoff, bounded load — 어디에도 대응물 없음 ⚪"과
> "nautilus에는 Context 객체 자체가 없어 PIT가 구조로 강제되지 않는다"고 기술했다. **후자는
> 사실이 아니다.** nautilus는 Context 객체 대신 이중 timestamp와 `ts_init` 정렬 stream으로 같은
> 보장을 제공하며, 이는 PRD §4.4가 요구하는 메커니즘 그 자체다. §18 참조.

| 항목 | 출처 | 위치 | |
|---|---|---|---|
| **이중 timestamp** (`ts_event` / `ts_init`) | nautilus | `core/data.pyx` L30, L42 | 🔵 |
| ↳ PRD 대응 | — | `ts_event`=event time, **`ts_init`=`available_at`** (§4.4, §7.2) | |
| **`ts_init` 오름차순 stream** = PIT 강제 | nautilus | `backtest/engine.pyx` L903, L1658-1735 | 🔵 |
| restatement 표시 | nautilus | `model/data.pyx` L1496 `is_revision` | 🔵 |
| 읽기 전용 facade | nautilus | `cache/base.pxd` `CacheFacade`, `portfolio/base.pxd` | 🔵 |
| ↳ Actor가 보유하는 형태 | nautilus | `common/actor.pxd` L73, L83 (`readonly`) | 🔵 |
| data ↔ timer 실행 순서 | nautilus | `backtest/engine.pyx` L1692, L1731-1735 | 🔵 |
| 명시적 생성자 주입 | nautilus | `system/kernel.py` L101 | 🔵 |
| learn/infer 데이터 분리 | vnpy | `alpha/dataset/template.py` L181-194 | 🟢 |
| 시간 범위 표현 | qlib | `backtest/decision.py` L206-300 `TradeRange` | 🟢 |
| 문자열 키 서비스 로케이터 | qlib | `common_infra.get(...)` | 🔴 |
| **횡단면 패널 view** (instrument × field) | — | — | ⚪ |
| **접근 기록 기반 lineage** | — | — | ⚪ |
| **역할별 view 구성** (compliance 분리) | — | — | ⚪ |

시간 경계 메커니즘은 nautilus에 있고 🔵로 차용한다. 남는 ⚪는 **접근 축**이다. Reference 세 곳은
모두 instrument별 시계열이 기본 단위이고(`cache.bars(bar_type)`은 한 종목의 deque), 메모리 상주
방식이라 20년 × 3000종목을 담지 못한다. qlibx의 기본 단위인 decision time 횡단면과 그것을 컬럼
저장소 질의로 구현하는 부분은 여전히 창작이다.

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
③ 횡단면 패널 view        instrument × field, 컬럼 저장소 질의   ← 가장 큼
③ 접근 기록 lineage       view 가 조회를 기록
③ 역할별 view 구성        compliance / signal 분리
② callback, FillSink
④ target→order 변환      전 주문 진단 보존
④ 제약 선언/조정/검증     PRD §10.8~10.9
⑤ TradeLedger            평균단가 · 라운드트립 · 실현손익 (§17 G2)
⑤ Memory                 전략 상태 commit boundary (§17 G1)
⑤ long-short 실행 회계    담보 · 수익률 분모 · 차입비용 (§17 G4)
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
| 1 | 도메인 객체 (instrument축 배열) | 🟢 | vnpy 필드 + qlib amount/deal_amount + Status enum |
| 2 | **exchange.match_batch + 진단** | 🟢 | 가장 검증이 중요. §15.1 fixture parity 먼저 |
| 3 | ledger (position/account/PnL) | 🟢 | qlib 산술 + vnpy PnL 분해 + TradeLedger(§17 G2) |
| 4 | kernel (clock/event/queue) | 🔵 | 20~30줄. 병렬 clock 검증 |
| 5 | view (available_at 질의 + 횡단면 패널) | 🔵⚪ | 시간 경계는 🔵, 접근 축은 ⚪ |
| 6 | flow + convert + executor | ⚪🟢 | §13 walkthrough가 통합 테스트 |
| 7 | validate | 🔵⚪ | |
| 8 | evidence (envelope/catalog) | ⚪ | |
| 9 | analysis plugin | 🔵🟢 | |
| 10 | signal/dataset | 🟢 | vnpy 이식 |
| 11 | production boundary | ⚪ | PRD §14 |

6단계 완료 시 end-to-end long-only backtest가 동작한다. 7단계 이후는 참고 코드가 희박하므로 기반이
굳은 뒤로 배치한다.

2단계부터 instrument축 배열을 기본 단위로 잡는다. 단건 `match`를 먼저 만든 뒤 batch로 확장하는
경로는 택하지 않는다 — clipping 순서 중 현금 제약만이 순차이고 나머지는 elementwise이므로, 처음부터
batch로 두는 편이 단순하다.

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
| O3 | **matched capitalization 폐기** | qlib long-only position 제약이라는 전제가 소멸. 대체로 instrument capability 모델(숏 가능성/마진/carry/계약단위/청산) 도입. PRD §11.5~11.7 개정 필요. **§17 G4가 이 결정에 막혀 있다** |
| ~~O9~~ | ~~long-short 수익률 분모~~ | **해결.** dollar-neutral book은 **gross 기준**으로 수익률을 계산한다. Long 100 / short 100이면 분모는 200이다. NAV 기준은 leverage에 따라 수익률이 달라져 alpha 비교가 불가능해지므로 채택하지 않는다. §17 G4의 나머지 항목(담보 모델, 차입 비용, locate)은 여전히 미해결 |
| O4 | hypothetical vs real short | 종목 속성으로 선언. real short 불가 종목의 숏 결과에 hypothetical 낙인을 artifact에 기록 |
| O5 | crypto perpetual 확장 | funding은 `FUNDING` timer로 §3 원자에 그대로 편입. margin account, 계약단위(linear/inverse), 강제청산이 추가로 필요 |
| ~~O10~~ | ~~nautilus를 execution backend로 채택~~ | **기각.** 기본 작업 단위가 다르다 — instrument별 event 대 decision-time 횡단면. PRD §8~§10·§12에 대응물 없음. v1→v2 전환 중. 3000종목 미검증. 상세와 재검토 조건은 [[why-not-nautilus-as-a-dependency]] |
| O6 | pub/sub 도입 시점 | 현재는 callback만. 횡단 관심사(전 이벤트 로깅, 사용자 관측자)가 생기면 검토. 도입 시 delivery 우선순위를 함께 설계해야 I7이 유지된다 |
| O7 | PRD 본문 정리 | §0.3 해석 규칙으로 처리 중. Qlib 전제 서술 195곳의 정식 개정은 별도 revision |
| ~~O8~~ | ~~qlib 소스 보존~~ | **해결.** `references/qlib`을 upstream `main@79633dd` 전체 트리(619 paths)로 교체. 기존 부분 스냅샷(274 paths)은 소스를 담고 있지 않았다. §14 인용이 저장소만으로 해결된다 |

O3~O5는 서로 묶여 있다. 함께 결정하는 것이 낫다.

---

## 17. 설계 감사 기록

이 절은 초안을 네 개의 구체적 research scenario에 대조해 발견한 gap과 불일치를 기록한다. 감사
시점 2026-08-03, 대조 대상은 `docs/qlibx-prd.md`와 `references/` 아래 vendored source다.

기록 목적은 두 가지다. 첫째, 초안이 이미 만족한다고 **잘못 읽힐 수 있는** 부분을 명시적으로
표시한다. 둘째, 해결 순서와 선행 결정을 남긴다. 여기 적힌 gap은 구조의 결함이 아니라 명세의
미완이다 — G4만 예외다.

| # | 항목 | 성격 | 상태 |
|---|---|---|---|
| G1 | Strategy memory 부재 | 불변식 오류 + 계약 누락 | I4 개정 완료, 계약·저장소 미설계 |
| G2 | Round-trip 회계 부재 | 차용 판단 오류 | 미해결 |
| G3 | 학습/거래 분리 (`FIT` event) | 명세 누락 | 미해결 |
| G4 | Long-short 실행 회계 | **설계 미착수** | O3~O5 선행 필요 |
| G5 | `ensemble` 계약 부재 | 명세 누락 | 미해결 |

### G1 — Strategy memory

초안은 "bounded strategy memory"를 §7의 `DecisionContext` **입력** 항목으로만 언급하고, 출력·
저장소·commit 경로를 정의하지 않았다. §8의 judge 계약도 `alpha(ctx) -> (AlphaWeights,
Diagnostics)`로 state 출력이 없다.

(`DecisionContext`는 §18에서 폐기된 초안 용어다. 현행 대응물은 `DecisionView`이며, memory를
어떻게 담고 되돌려받을지는 아래 미결정 항목으로 남아 있다.)

PRD §9.1과 §9.10이 요구하는 형태는 다음이다.

```python
alpha(ctx) -> (AlphaWeights, ProposedMemory, Diagnostics)
```

`ProposedMemory`는 제안일 뿐이며 flow가 commit boundary에서 반영한다. Alpha는 여전히 순수 함수다 —
이전 memory를 입력으로 받고 다음 memory를 반환할 뿐 어디에도 쓰지 않는다.

Memory를 소비한 alpha result는 자동으로 path-dependent다 (PRD §9.4). §10 envelope의
`path_dependent` 플래그가 이를 표시하며, G5의 ensemble member 검사와 연결된다.

**미결정:** Memory를 별도 store로 둘지, evidence의 artifact stream에서 최신 커밋본을 읽는 형태로
둘지. 후자는 PRD §9.11("재현 가능한 state transition으로 기록")과 더 잘 맞지만 매 decision마다
조회 비용이 든다.

### G2 — Round-trip 회계

§9는 ledger 산술을 qlib `backtest/position.py::Position`에서 이식한다고 기술했다. 이 판단은 수량과
현금 회계에는 유효하지만 **PnL 경로 의존 로직에는 불충분하다.**

Vendored source 확인 결과 `Position`이 종목별로 보유하는 필드는 `amount`, `price`, `weight` 셋이며,
`price`는 취득원가가 아니라 평가가격이다. `update_stock_price`(L401-402)가 매 bar 덮어쓰고,
`_buy_stock`(L342-350)은 추가 매수 시 평균단가를 갱신하지 않는다. 실현손익 필드와 라운드트립 개념은
존재하지 않는다.

따라서 "직전 N회 거래가 손실이었는가" 같은 조건은 현재 차용 계획으로 **답할 수 없다.**
`PositionLedger`와 별개로 다음을 보유하는 `TradeLedger`가 필요하다.

```
평균 취득단가 · 라운드트립 개시/종료 · 실현손익 · 실현수익률
```

nautilus `model/position.pxd`가 동일 역할을 하며(`avg_px_open`, `avg_px_close`, `realized_pnl`,
`realized_return`, `is_closed_c`, `calculate_pnl`) 설계 참고 대상이다. LGPL이므로 🔵다.

vnpy `PortfolioDailyResult`의 trading/holding PnL 분해는 일별 집계이므로 종목별 라운드트립을
대체하지 못한다.

### G3 — 학습/거래 분리

§3 원자 표에 `FIT` event가 없다. "fitted model"은 §10 lineage 다이어그램에만 등장한다. PRD §8.6과
P2 수용 기준은 rolling/expanding/event-triggered retraining을 명시적 research lifecycle로 요구한다.

원자 패턴에는 그대로 편입된다.

| event | context cutoff | 순수 함수 | 결과 | store |
|---|---|---|---|---|
| `FIT` | train_end − label_horizon − embargo | model.fit | FittedState + selection evidence | Memory (proposed → commit) |

`priority`는 `DECISION`보다 앞선다.

**라벨의 `available_at` 선언이 이 gap의 핵심이다.** 20일 forward return 라벨로 12/31까지 학습하면
마지막 샘플의 라벨이 1/20까지의 가격을 소비하고, 그 모델이 1/2 decision에 쓰인다. 예외는 발생하지
않는다.

§18 개정 이후 이 문제는 별도 cutoff 장치가 아니라 **선언으로 해결된다.** 라벨의 `available_at`을
`event_time + horizon`으로 등록하면, `FIT`이 시각 T에 실행될 때 `available_at > T`인 라벨은 애초에
조회되지 않는다. purge/embargo가 view의 일반 규칙에서 그대로 따라 나온다.

따라서 남는 요구는 **derived label을 등록할 때 horizon을 `available_at`에 반영하도록 강제**하는
것이다. PRD §8.1이 요구하는 purge/embargo 선언이 이 지점에 해당한다. 이를 누락하면 §18이 지적한
"보장이 write 시점으로 이동한 대가"가 정확히 여기서 실현된다.

부수 요구: `FittedState`는 binary payload 참조로 저장하고(PRD §12.2), 어느 fitted state가 활성인지는
lineage edge로 기록한다. 최신 파일 경로 참조로 대체하지 않는다(PRD §8.6). 선택되지 않은 후보와
실패한 fit도 조회 가능해야 한다.

### G4 — Long-short 실행 회계

**초안 구조로는 executable long-short가 불가능하다.** 이 절의 다른 항목과 달리 명세 미완이 아니라
설계 미착수다.

§9가 차용하는 qlib `Position._sell_stock`(L352-374)은 잔량이 음수가 되면 `ValueError`를 던진다.
구조적으로 long-only다. 그리고 이 제약을 우회하던 PRD §11.4~11.7 matched capitalization은 §0.3이
전제 소멸로 무효화했다. 옛 우회로는 폐기되었고 대체 메커니즘은 아직 없다.

**연구 층위와 실행 층위를 분리해야 한다.** PRD §4.2의 세 층 중

- 1층(signal IC/RankIC/quantile spread, long-short diagnostic)과
- 2층(signed basket return, factor return)은

가중치가 부호 있는 수치일 뿐이고 ledger를 경유하지 않으므로 **현재 구조에서 이미 가능하다.**
막힌 것은 3층, 즉 order/position/account를 통과하는 executable short다.

3층에 필요한 미설계 항목:

1. **부호 있는 position** — 예외 제거 자체는 사소하다.
2. **공매도 대금의 성격** — qlib `Position`의 `cash`는 단일 수치이며 free/encumbered 구분이 없다.
   그대로 두면 공매도 대금으로 재매수하는 무한 레버리지가 성립한다. 담보 모델이 필요하다.
3. **수익률 분모** — 달러 뉴트럴 북에서 NAV·gross·capital-at-risk 중 무엇을 분모로 쓸지는
   계산으로 도출되지 않는 **선언 사항**이다. PRD §11.9가 composite와 active return을 구분하지만
   matched capitalization 맥락에 한정되어 있어 일반 long-short용으로 재작성이 필요하다.
4. **차입 비용** — 종목별·시점별로 변한다. 데이터가 없으면 모델링하지 않는다(PRD §5.7).
5. **대차 가능성(locate)** — unknown을 가능으로 추측하지 않는다(PRD §7.7 원칙).

해결 경로는 O3~O5의 instrument capability 선언이다. 종목이 `shortable: none | hypothetical | real`을
선언하고, `hypothetical`은 1~2층 연구를 허용하되 실행 프로파일에서 거부되며 결과 artifact에
표시된다. **O3~O5 결정 없이는 진행할 수 없다.**

### G5 — `ensemble` 계약

§8 judge 계약 목록에 `ensemble`이 없다. §10 lineage 다이어그램과 §12 package layout에만 등장한다.
PRD §10.1은 결과 요구사항(member fingerprint, ticker-level pre/post-net weight, crossing/netting
amount, gross/net residual, member contribution/overlap)을 상세히 규정하므로 출력은 정의되어 있고
계약만 없다.

```python
ensemble(members, ctx) -> (AlphaWeights, EnsembleDiagnostics)
```

**G4와 독립이다.** Ensemble은 weight space에서 일어나며 ledger를 경유하지 않으므로 long-short
member를 결합하는 것 자체는 실행 회계와 무관하다.

설계 시 확정할 항목 셋:

- **Crossing 기록.** 두 member가 같은 종목에 반대 intent를 내면 netting 후 gross가 줄고 각 member의
  의도가 부분적으로만 실현된다. 거래 비용은 발생하지 않지만 gross budget이 상쇄에 소비된 것이므로
  member allocation과 capacity 진단의 입력이다. PRD §10.1이 명시적으로 요구한다.
- **Netting 후 normalization.** 네팅으로 줄어든 gross를 목표치로 되돌릴지는 fixed/flexible budget
  선언에 따른다(PRD §9.3). 말없이 재정규화하면 §9.3 위반이다.
- **Path-dependency 검사.** Member가 path-dependent면 다른 execution history에서 재사용할 수 없다
  (PRD §9.4). §10 envelope의 `path_dependent` 플래그로 검사 가능하며, **감사 항목 중 유일하게 이미
  처리된 부분이다.** G1의 memory 소비 alpha가 이 플래그를 통해 여기 연결된다.

### 해결 순서 제안

```
G1 · G3 · G5   → 각각 store 하나 / event 하나 / judge 함수 하나. §15 구축 순서에 편입 가능
G2             → §15 3단계(ledger)에 TradeLedger 추가. 선행 결정 없음
G4             → O3~O5 결정이 선행되어야 함
```

G1·G2·G3·G5는 선행 결정 없이 명세를 채울 수 있다. G4만 product decision을 기다린다.

---

## 18. 개정 이력

### 2026-08-03 — 정보 전달 모델 교체 (초안 §7 폐기)

**변경.** Event마다 `gate`가 snapshot(`Context`)을 조립해 judge에 넘기던 구조를, **clock에 묶인
읽기 전용 조회 창구(view)** 를 judge가 들고 필요한 시점에 조회하는 구조로 교체했다.

**계기.** nautilus 소스를 다시 읽는 과정에서 초안의 사실관계 오류가 확인되었다. §14는
"nautilus에는 Context 객체가 없어 PIT가 구조로 강제되지 않는다"고 기술했으나, nautilus는 다른
메커니즘으로 같은 보장을 제공한다.

```
core/data.pyx  L30  ts_event   그 사건이 발생한 시각
core/data.pyx  L42  ts_init    그 데이터가 시스템에 들어온 시각
backtest/engine.pyx L903       sorted(data, key=lambda x: x.ts_init)
model/data.pyx L1496           is_revision
```

Stream이 `ts_event`가 아니라 **`ts_init` 오름차순**으로 정렬된다는 점이 핵심이다. 이는 PRD §4.4의
`available_at <= evaluation_time`과 §7.2의 "Event time, observation time와 `available_at`"를 그대로
구현한 것이다. 미래를 차단하는 것이 아니라 **아직 stream에서 나오지 않았으므로 존재하지 않는다.**

**채택 근거.**

1. **Backtest와 live의 judge 코드가 동일해진다.** 초안은 gate 구현이 두 벌 필요했고, 두 벌이
   어긋나면 backtest만 통과하는 결함이 생긴다. 개정 후 차이는 clock 교체와 stream 공급원뿐이다.
2. **Cutoff가 파라미터에서 사라진다.** 일봉의 `available_at`이 15:30이면 09:00 `DECISION`이 당일
   종가를 볼 수 없다. §3의 cutoff 열이 시간표에서 유도된다.
3. **Event마다 snapshot을 조립하는 비용이 없다.**
4. **Lineage가 선언이 아니라 관측에서 나온다.** View가 접근을 기록하므로 실제 사용과 어긋나지
   않는다(PRD §7.4).
5. **사전 bounded-load 선언이 불필요하다.** 조회 자체가 lookback으로 한정된다.

**대가.**

1. **Judge가 순수 함수가 아니게 된다.** View를 보유하고 조회하므로 초안의 I2("context 밖 데이터에
   접근하지 않는다")가 성립하지 않는다. I2는 "모든 접근은 clock-bound view를 경유한다"로
   개정되었다. 테스트는 가짜 clock과 가짜 view 주입으로 유지된다.
2. **보장 지점이 read 시점에서 write 시점으로 이동한다.** `available_at`을 잘못 선언하면 조용한
   look-ahead가 발생하고 예외는 나지 않는다. PRD §5.1·§7.2가 availability 선언을 qlibx 소유로,
   §4.4가 qlibx의 보장 범위를 "선언된 availability의 준수"로 규정하므로 책임 배분 자체는 일치한다.
   다만 **data registration 검증이 §1 설계 명제를 지탱하는 단일 지점**이 되므로 그에 상응하는
   검증이 필요하다.

**유지되는 것.** Event / callback / handler 기반 inversion of control, 여섯 layer 구분, 반복 원자,
flow가 유일한 부수효과 지점이라는 배치는 변경되지 않는다.

**영향 범위.** §2 멘탈 모델, §3 원자 표(cutoff 열 제거), §4 불변식 I2·I3, §7 전면 재작성,
§8 judge 계약 첫 인자, §14 매핑표 ③ 정정.

**남는 ⚪.** 시간 경계 메커니즘은 nautilus에서 차용하지만 **접근 축**은 여전히 창작이다. Reference
세 곳은 instrument별 시계열이 기본 단위이고 메모리 상주 방식이라, decision time 횡단면을 컬럼
저장소 질의로 제공하는 부분에는 대응물이 없다.

### 2026-08-03 — 설계 감사 (§17)

네 개의 research scenario 대조로 다섯 개 gap 확인. I4가 PRD §9.1·§9.10과 모순되어 개정. 상세는
§17.

### 2026-08-03 — execution backend 결정 및 batch 단위 확정

**결정.** nautilus_trader를 execution backend dependency로 채택하지 않는다. 설계는 선별 차용하되
engine은 qlibx가 구현한다. 근거와 재검토 조건은 [[why-not-nautilus-as-a-dependency]]에 있다.

**핵심 사유.** 기본 작업 단위가 다르다. nautilus는 instrument별 event, qlibx는 decision-time
횡단면이다. 3000종목 × 5000일이면 1500만 event 대 5000 batch step이고, 이는 최적화로 좁힐 수 있는
차이가 아니다. 여기에 PRD §8~§10·§12에 대응물이 없다는 점, v1→v2 전환 진행 중이라는 점,
3000종목 규모가 미검증이라는 점이 더해진다.

**구조 변경.** Executor가 "일정표"에서 **횡단면 batch 실행기**로 바뀐다. `exchange.match(order)`는
`exchange.match_batch(orders)`가 되고, `FillSink.apply`는 `apply_batch`가 된다. §15 구축 순서는
2단계부터 instrument축 배열을 기본 단위로 잡는다.

**유지되는 것.** event / callback / handler 기반 inversion of control, clock, closed-loop feedback은
변경되지 않는다. 한 event가 나르는 데이터의 크기만 바뀐다. 시간 축은 여전히 순차이므로 partial
fill, blocked liquidation, path-dependent stop-loss가 모두 성립한다.

**명시적으로 배제하는 것.** 시간 축을 일괄 계산하는 형태의 backtest — `(weights.shift(1) *
returns).sum()` — 는 feedback edge가 없어 PRD §4.3을 만족할 수 없으므로 채택하지 않는다.
벡터화 대상은 instrument 축이지 시간 축이 아니다.

**분단위 체결.** 요구되지 않는 것으로 확인되어 `MinuteExecutor`를 계획에서 제외한다. Executor 교체
지점은 유지한다.
