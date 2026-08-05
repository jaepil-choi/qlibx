# qlibx Architecture

Status: draft
Canonical requirements: `docs/qlibx-prd.md`
Borrow research: [[engine-borrow-benchmark-map]]
Backend 채택 판단: [[why-not-qlib-as-a-backend]], [[why-not-nautilus-as-a-dependency]]

이 문서는 PRD가 규정한 product requirement를 만족하는 **구현 설계**를 기술한다. PRD가 정본이고 이
문서는 그것을 만족하는 하나의 구조다. 둘이 충돌하면 PRD가 우선한다.

이 문서가 정하는 것: layer 경계, 책임 배분, 불변식, 핵심 계약의 shape, 의존 방향, 차용 출처.
이 문서가 정하지 않는 것: 최종 public name, 함수 시그니처의 세부, 파일 분할 단위.

> **§17 설계 감사 기록을 함께 읽을 것.** 이 문서는 초기 고정 pipeline 초안에서 출발했다. 2026-08-05
> PRD가 독립 workflow와 progressive requirement discovery를 정본 계약으로 확정하면서 orchestration,
> error, evidence와 production boundary를 다시 감사했다. 현행 본문은 그 revision을 반영하고, §17은
> 아직 남은 구현 결정과 폐기된 가정을 구분해 기록한다.

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

### 1.1 PRD use-case traceability

PRD는 observable outcome과 evidence를 stable use-case ID로 규정한다. Architecture는 각 ID를 반복하는
데 그치지 않고 다음 여섯 항목을 추적 가능하게 설명해야 한다.

```text
trigger → permitted read → calculation → commit → evidence → validation
```

| PRD use case | trigger | permitted read | calculation | commit | evidence | validation |
|---|---|---|---|---|---|---|
| `UC-DATA-001` | dataset registration | source sample + user binding | minimal key/time/availability validation | registration | binding + schema fingerprint | arbitrary-field fixture |
| `UC-DATA-002` | Strategy invocation | requirements + registered bindings | requirement resolution | 없음 on gap | `OperationError` + requirement ID | add-binding retry |
| `UC-ERROR-001` | short analysis invocation | actual operation path only | requirement check | failure evidence only | hierarchical stage path | no phantom-stage fixture |
| `UC-PIT-001` | model materialization | labels available at evaluation time | horizon requirement resolution | 없음 on gap | missing `horizon_end` | future-label rejection |
| `UC-AGENT-001` | ambiguous registration failure | package error + skill + project semantics | agent proposes; package validates | confirmed binding only | user decision + rule ID | no guessed availability |
| `UC-SIGNAL-001` | direct Strategy run | scoped PIT data + bounded state | signal/weight inside Strategy | results + proposed memory | signed weights + accesses | no mandatory signal stage |
| `UC-SIGNAL-002` | stored-result Strategy run | compatible typed model result | signed-weight assembly | Strategy result | producer-independent edges | producer not rerun |
| `UC-ALPHA-BUDGET-001` | flexible-budget Strategy | signed inputs + budget declaration | allocation without forced rescale | alpha-weight result | invested/residual budget | fixed incompatibility |
| `UC-ALPHA-PATH-001` | cross-state reuse | result state + target state | compatibility assessment | reuse decision artifact | warning + user choice | replay/rerun branches |
| `UC-ALPHA-CHILD-001` | child execution branch | frozen parent weights + child profile | alternate execution only | child Ledger/artifacts | parent edge + profile | parent unchanged |
| `UC-ALPHA-ADAPTIVE-001` | feedback-triggered Strategy | committed feedback + prior memory | proposed belief/member update | Memory at flow boundary | before/after + cursor | no future feedback |
| `UC-ENSEMBLE-001` | Ensemble Strategy run | compatible member results | combine/net/cross by ticker | ensemble result | contribution + residual | producers not rerun |
| `UC-PORTFOLIO-001` | construction profile selection | same weights + selected profile | profile-specific construction | separate portfolio results | budget/direction/cost lineage | alpha unchanged |
| `UC-CONSTRAINT-001` | constraint-free analysis | signal/weight artifact only | requested analysis | analysis result | actual dependencies | no compliance binding |
| `UC-CONSTRAINT-002` | constrained conversion | declaration + metric inputs | requirement resolution | 없음 on gap | missing sector requirement | no order/account mutation |
| `UC-CONSTRAINT-ADJUST-001` | adjust then validate | intent + actual state + constraint data | adjust; independent validate | eligible candidate only | before/after + residual + finding | residual is not compliance |
| `UC-COST-001` | execution event | exact product/side policy + quote | §13.2 cost rule | Fill | total cost + rule ID | product/side fixture |
| `UC-COST-002` | execution event | policy valid at event time | §13.2 schedule resolution | Fill | version + effective time | date-boundary fixture |
| `UC-COST-003` | cash-limited BUY | actual cash + exact policy | §13.3 shared cost calculator | Fill | requested/dealt + clip reason | cash-limit fixture |
| `UC-COST-004` | no exact rule | exact selector; no parent fallback | unsupported failure | 없음 | failure artifact | no Fill/Ledger mutation |
| `UC-CLOSED-LOOP-001` | next decision after commit | committed Ledger/OMS state | Strategy evaluation | next result | feedback cursor + snapshot | requested state excluded |
| `UC-SCALE-001` | 3,000-name execution | compiled arrays + scoped market data | vectorized match | Fill batch | stable per-name diagnostics | batch/scalar parity |
| `UC-EXEC-001` | child profile selection | same decision + profile execution view | daily or intraday execution | separate child Ledgers | shared decision ID + fills | only actual result diverges |
| `UC-EXEC-002` | daily-close execution | observations available by fill time | timing/PIT validation then match | Fill or failure | convention + limitation | no future close |
| `UC-EXEC-003` | independent monitor timer | actual snapshot + compliance view | constraint evaluation | finding artifact only | breach/missing classification | no decision/order |
| `UC-ARTIFACT-001` | external artifact load | documented payload + envelope | typed construction + compatibility | imported artifact | external producer lineage | no producer import |
| `UC-ARTIFACT-002` | load/publication | complete candidate payload | schema + semantic validation | 없음 on invalid | bounded failure evidence | invalid not reusable |
| `UC-RESEARCH-001` | failed operation then retry | frozen failure inputs + new binding | new resolution | failure then success artifacts | resolution lineage | failure retained |
| `UC-REPORT-001` | renderer selection | stored analysis values | presentation only | report artifact | source analysis IDs | renderer value parity |
| `UC-MONITOR-001` | monitoring report | actual-account findings | analysis/rendering | report artifact | actual/intended distinction | breach vs missing |
| `UC-EXTENSION-001` | extension registration | contract + validation fixture | package compatibility validation | registration on success | validation + producer ID | failure not registered |
| `UC-PROD-001` | OMS partial result | decision + confirmed fills/account | reconciliation | confirmed delta only | pending/cancel + correlation | next sees 40, not 100 |
| `UC-PROD-002` | OMS rejection | decision + rejection | reconcile without intended apply | rejection evidence only | retry policy identity | actual unchanged |
| `UC-ACADEMIC-001` | future academic listing | explicit hypothetical profile | §13.6 match | hypothetical Fill | profile identity | disallowed profile rejects |
| `UC-FUTURE-001` | future settlement/expiry | observable settlement input | variation/final settlement | cash/position delta | lifecycle evidence | post-expiry reject |
| `UC-PERP-001` | future funding timer | observable funding rate | funding cash flow | cash delta | funding evidence | no expiry event |
| `UC-CASHFLOW-001` | future fill/lifecycle event | event-specific inputs | separate fee/lifecycle calculation | Ledger | category + source | attribution separation |

마지막 네 future 행은 current acceptance가 아니다. 현재 구조가 해당 flow를 막지 않는지 설명하는 설계
characterization이며 구현 완료를 주장하지 않는다. Test와 fixture를 만들 때도 같은 use-case ID를 사용해
PRD → architecture → validation의 연결을 유지한다. CI는 두 문서의 stable ID 집합을 비교해 누락을
실패시켜야 한다.

---

## 2. 멘탈 모델

### 2.1 월말 전략 하나를 끝까지 따라간다

예를 들어 매 거래일 장 마감 뒤 signal을 계산하지만, 월말에만 주문을 결정하고 다음 거래일 종가에
체결하는 Strategy를 생각한다.

```text
등록된 PIT data
(daily/monthly OHLCV, return, stored artifact)
          │
          ▼
Clock-bound View ──→ Strategy ──→ immutable DecisionIntent
          ▲                              │
          │                              ▼
          │                       ExecutionProfile
          │                              │
          │                              ▼
          │                    result + diagnostics
          │                              │
          │                         Flow commit
          │                              │
          └── 다음 decision feedback ─ Ledger / Memory

각 단계의 input, assumption, result와 failure ──→ Evidence
```

실행 순서는 다음과 같다.

```text
매 거래일 장 마감      MATERIALIZE callback → 그날까지 available한 data로 signal 저장
월말 마지막 거래일     DECISION callback    → signal과 actual state로 DecisionIntent 확정
다음 거래일 종가       EXECUTION callback   → 미리 확정된 intent를 선택한 가정으로 결과화
다음 decision          StrategyView          → commit된 실제 결과와 prior Memory를 읽음
```

여기서 월말은 달력의 마지막 날이 아니라 **마지막 거래 session**이다. 다음 거래일 종가는 Strategy input이
아니다. 월말에 freeze된 DecisionIntent를 결과화하는 execution input이다. Executor가 다음날 가격·현금으로
수량이나 Fill을 계산할 수 있지만 그 가격으로 Strategy intent를 다시 계산하지 않으면 Strategy look-ahead가 아니다.

### 2.2 여섯 질문을 섞지 않는다

| 질문 | 책임 | 예 |
|---|---|---|
| 어떤 data가 존재하는가 | Registry | daily/monthly OHLCV, close-close return, stored signal |
| 지금 무엇을 볼 수 있는가 | Clock + View | `available_at <= evaluation_time`, resolved requirement |
| 무엇을 보유하고 싶은가 | Strategy | signed weight, target, `DecisionIntent` |
| 언제·어떻게 결과화하는가 | ExecutionProfile | next close/open, cost, liquidity, hypothetical convention |
| 실제로 무엇이 됐는가 | Ledger + Memory | Fill, Position, cash, NAV, committed feedback |
| 무엇을 근거로 계산했는가 | Evidence | data identity, lineage, assumption, limitation, failure |

**Strategy look-ahead는 View 경계가 결정하고 execution realism은 ExecutionProfile이 결정한다.** Daily 또는
monthly bar를 쓰거나 단순 종가 체결을 선택했다는 사실만으로 Strategy look-ahead가 발생하지 않는다. 반대로
정교한 intraday executor를 써도 View가 미래 observation을 보여주면 look-ahead다.

같은 immutable DecisionIntent를 daily close, next open, intraday partial-fill 또는 academic profile이 각각
처리할 수 있다. Strategy result는 같고 execution result와 이후 actual state만 달라진다. Signal이나 weight만
분석하는 research는 ExecutionProfile과 Ledger mutation 없이 Evidence publication에서 정상 종료할 수 있다.

### 2.3 Clock, callback과 View

Callback의 business logic은 Flow가 소유하고 Clock은 event 시각, priority와 callback reference를 queue에서
관리한다. Runtime loop가 Clock이 반환한 handler를 순서대로 호출한다.

```text
Engine / Flow가 callback 등록
          ↓
Clock이 다음 event 시점으로 이동
          ↓
Handler(Event, callback)를 priority 순서로 반환
          ↓
Runtime loop가 Flow callback 호출
          ↓
Flow가 scoped View를 만들고 Operation 실행
```

월말 session에는 `MATERIALIZE`를 `DECISION`보다 앞선 priority로 실행할 수 있다. `DECISION`은
DecisionIntent를 확정한 뒤 Executor가 만든 다음 거래일 종가 `EventSpec`을 Clock에 등록한다. `EXECUTION` callback은 그
시각의 `ExecutionView`로 가격과 policy를 읽고 결과를 commit한다.

View에는 두 문이 있다.

```text
시간 경계   available_at <= clock.now()인가      → 모든 View에 공통
역할 경계   이번 Operation이 선언한 binding인가  → View 종류와 resolved requirement가 결정
```

Close-close return $r_t$는 ending close가 공개되기 전에는 available하지 않다. $r_t$를 보고 만든 weight
$w_t$는 같은 $r_t$가 아니라 다음 기간 $r_{t+1}$에 적용한다.

Operation은 시간을 스스로 읽거나 store에 직접 접근하지 않고 Ledger, Memory 또는 Evidence를 직접 쓰지
않는다. Flow가 typed result와 diagnostics를 받은 뒤 허용된 commit/publication port를 호출한다.

### 2.4 세 authority, 두 mutable state store와 여섯 layer

Runtime truth에는 세 authority가 있지만 mutable state store는 둘뿐이다.

```text
Clock     지금 몇 시인가                 — event 순서와 조회 cutoff의 시간 authority
Ledger    실제로 무엇을 갖고 있는가      — Position, cash, NAV의 account authority
Memory    Strategy가 무엇을 기억하는가   — commit된 strategy state의 authority

mutable state store = Ledger + Memory
```

Catalog와 Artifact는 authority를 대신하지 않는 append-only Evidence다. 영수증이 계좌 잔액 자체가 아닌 것과
같다. Strategy는 Ledger나 Memory를 직접 변경하지 않고 StrategyView로 commit된 state를 읽으며 proposed
Memory를 result로 반환한다. Flow가 workflow finalization에 맞춰 이를 commit한다.

| layer | 답하는 질문 | 주요 책임 |
|---|---|---|
| ① kernel | 언제 실행하는가 | Clock, Event, Queue, deterministic priority |
| ② flow | 어떤 순서로 실행하고 무엇을 확정하는가 | callback, direct invocation, Executor sub-flow, commit/publication |
| ③ view | 무엇을 볼 수 있는가 | clock-bound facade, PIT와 role boundary, access lineage |
| ④ operation | 무엇을 계산하는가 | Strategy, Model, construct, analyze, validate, exchange.match |
| ⑤ state | 실제 state는 무엇인가 | Ledger와 Memory |
| ⑥ evidence | 무엇을 근거로 재현하는가 | Artifact, Catalog, Lineage, diagnostics |

부수효과를 시작할 수 있는 곳은 **② flow뿐**이다. ③④는 순수하고, ⑤⑥은 Flow가 좁은 port로만
변경한다. Flow는 Clock callback뿐 아니라 dataset registration, analysis, report 같은 direct API/CLI
invocation도 orchestration한다. 모든 run이 `Strategy → construct → convert → validate → execute`를 통과하지
않으며, `on_decision`이 길어지면 계산이 Flow로 흘러들어온 신호다.

Ledger에서 View를 거쳐 다음 decision으로 돌아오는 edge가 PRD §2.4 closed loop다. 다음 decision은 requested
target이 아니라 **commit된 실제 상태**를 읽는다.

### 2.5 Data granularity는 research capability다

Dataset registration은 data를 특정 executor에 맞춰 왜곡하지 않고 실제 의미를 기록한다.

| 보유 data | 가능한 research | 조용히 주장하면 안 되는 것 |
|---|---|---|
| daily OHLCV | daily 또는 더 낮은 빈도의 signal, next-bar convention, daily mark | intraday path, order-book liquidity |
| monthly OHLCV | monthly signal·rebalance·return | daily drawdown, daily tradability, 월중 체결 path |
| close-close return | IC, factor/portfolio return, attribution, hypothetical NAV | observed quote, share quantity, market volume |

최소 계약은 instrument axis, interval/event time, `available_at`, semantic category와 source provenance다. Return은
period start/end, gross/net/excess, currency와 compounding convention을 추가로 선언한다. OHLCV, lot, volume와
tradability는 이를 실제로 사용하는 Operation이 requirement로 요구하며 단순 return research를 막는 전역 필드가
아니다.

Return-only research는 가격 없이 완결될 수 있다. 전기 weight로 다음 기간 return을 적용한다.

$$
R_{p,t+1}=\sum_i w_{i,t}r_{i,t+1}
$$

가격, 수량, lot과 cash clipping이 필요한 physical execution은 그 binding이 없으면 실패해야 한다. 반면
academic profile은 아래의 명시적 synthetic-price 경로를 선택할 수 있다.

### 2.6 Instrument, Exchange와 Factor synthetic price

| 역할 | 답하는 질문 | 예 |
|---|---|---|
| Instrument | 이것은 어떤 경제적 계약 또는 exposure인가 | Equity, ETF, Future, PerpetualSwap, Index, Factor |
| Exchange / profile | 이 profile에서 어떻게 결과화하는가 | listing, tradability, lot, fee/tax, hypothetical convention |
| Clock / flow | 언제 계산하고 commit하는가 | DECISION, EXECUTION, SETTLEMENT, FUNDING, EXPIRY |
| Ledger | 실제 또는 명시적 hypothetical state가 어떻게 바뀌었는가 | Fill, cash flow, position delta, NAV |

Instrument는 immutable contract와 static semantics를 제공한다. Exchange는 listing과
venue/profile/effective-time policy를 적용한다. 시변 가격, return, funding rate와 valuation input은
clock-bound View에서 읽는다. 같은 Index도 일반 profile에서는 tracking-only이고 명시적 academic profile에
등록되면 hypothetical execution 대상이 될 수 있다.

Architecture의 concrete type 후보는 다음과 같다. PRD가 이 hierarchy를 강제하지 않으며 stock/ETF 밖의
항목은 future extension이다.

```text
Instrument
├── Equity
│   └── ETF
├── Index · Factor · Cash · Bond · Option
└── MarginedContract
    ├── Future
    │   ├── FxFuture · CommodityFuture · EquityIndexFuture
    └── PerpetualSwap
        └── CryptoPerpetual
```

`Factor`는 가상의 tracking portfolio를 나타내는 return-native Instrument다. 원천 observation은 기간별
factor return이며 observable market quote를 요구하지 않는다. Return-based analysis는 이 observation을 직접
소비한다.

Price-oriented execution 경로를 재사용해야 하면 deterministic transform이 normalized
`SyntheticUnitPrice`를 만들 수 있다.

$$
P_0=b>0, \qquad P_t=P_{t-1}(1+r_t)
$$

이 값은 observed market price가 아니라 **derived unit NAV**다. Derived binding은 source return identity,
base $b$, period/compounding convention, missing-period policy, transform version과 `available_at`을 보존한다.
`available_at`은 source return보다 이를 수 없고 전체 경로에서 $P_t>0$이어야 한다. 조건을 만족하지 않으면
price-compatible profile은 unsupported로 실패하고 return-native research만 허용한다.

Future extension의 Academic profile은 validated `SyntheticUnitPrice` binding과 명시적인 unit, fractional/lot,
cost와 liquidity assumption이 있을 때 Factor를 hypothetical listing으로 받아 기존 quantity/Fill/Ledger 경로를
재사용할 수 있다. Result는 synthetic source와 profile limitation을 표시한다. Base를 100에서 1,000으로
바꾸면 quantity만 1/10로 바뀌고 gross exposure와 pre-cost return은 같아야 한다. Cost policy는 notional-based
이거나 별도의 base-invariance를 증명해야 하며 exact Factor/profile rule이 없으면 실패한다. 일반 Exchange는
synthetic value를 market quote로 취급하거나 Factor를 silently tradable로 만들지 않는다.

`ETF <: Equity`는 상품 taxonomy와 코드 재사용 관계일 뿐 Exchange transaction cost policy의 상속 규칙이
아니다. Cost policy는 exact concrete product selector로 해석한다. ETF cost rule이 없으면 unsupported로
실패하며 Equity cost rule로 fallback하지 않는다. ETF 비용이 0이어도 명시적인 ETF cost rule이 있어야 한다.

`Future`만 expiry와 final settlement를 가지며 `PerpetualSwap`에는 expiry field 자체가 없다. 둘의 공통
부모는 contract multiplier, settlement currency와 notional/PnL convention을 제공한다. 금리, 배당수익률,
storage/convenience yield와 funding rate는 시변 observation이므로 Instrument instance에 저장하지 않는다.

`Equities`, `Futures` 같은 복수형은 새로운 금융계약 subtype이 아니라 `InstrumentSet[T]` 또는 registry
view다. 개별 객체를 보존하면서 registration과 instrument-axis compilation을 묶는 편의 경계일 뿐이다.

---

## 3. 반복 원자

모든 operation은 같은 transaction shape를 갖는다. Trigger는 Clock event일 수도 있고 CLI/API가 시작한
dataset registration, artifact load, analysis 또는 report invocation일 수도 있다.

```
trigger가 온다
  ① invocation/config/component identity를 freeze한다
  ② 선택한 operation의 requirement를 registered binding에 resolve한다
  ③ clock과 역할에 묶인 scoped view를 만든다
  ④ typed result와 diagnostics를 계산한다
  ⑤ flow가 허용된 state commit 또는 artifact publication을 수행한다
  ⑥ actual dependency, outcome 또는 failure evidence를 기록한다
```

Requirement resolution이 실패하면 ④를 호출하지 않고, Ledger/Memory mutation이나 success artifact publication
없이 hierarchical `OperationError`와 failure evidence를 남긴다. 사용하지 않는 optional operation은 stage
path에 나타나지 않는다.

Event-driven runtime에서 위 원자는 다음처럼 구체화된다.

| event | clock 위치 | scoped view | 선택 가능한 계산 | 결과 | authoritative commit |
|---|---|---|---|---|---|
| `DECISION` | decision time | `StrategyView` | selected Strategy; optional construct/adjust/convert/validate | weights and/or decision intent + diagnostics | proposed Memory만 flow가 commit; execution은 예약 |
| `EXECUTION` | 체결 시점 | `ExecutionView` | exchange.match_batch | fills + diagnostics | apply_batch |
| `MARK` | 15:30 | `ExecutionView` | valuation | NAV | mark |
| `MONITOR` | 15:30 | `MonitorView` | constraint evaluation | findings | **건드리지 않음** |
| `MATERIALIZE`† | model/transform cadence | requirement-scoped data view | model/transform | typed research data | artifact publication |
| `SETTLEMENT`* | 정산 시점 | `ExecutionView` | variation/coupon/corporate cash flow | cash/position delta | apply |
| `FUNDING`* | funding 시점 | `ExecutionView` | perpetual funding | cash delta | apply |
| `EXPIRY`* | 만기 시점 | `ExecutionView` | final settlement | cash/position delta | apply |

cutoff 열이 사라진 것에 주의한다. 무엇을 볼 수 있는지는 clock 위치와 각 관측치의 `available_at`이
결정하므로 event마다 명시할 값이 아니다. 일봉의 `available_at`이 15:30이면 09:00 `DECISION`은 당일
종가를 조회할 수 없다 — 별도 설정 없이 시간표에서 유도된다(§7).

`DECISION`은 fill을 commit하지 않고 `MONITOR`는 Ledger를 변경하지 않는다. Decision intent는 execution
event의 immutable input이고, monitoring finding은 account를 소급 변경하지 않는 evidence다.

† `MATERIALIZE`는 Model 또는 deterministic transform을 선택한 workflow에만 존재한다. Rolling,
expanding 또는 event-triggered fit이 필요하면 이 event의 concrete schedule로 등록하고 `DECISION`보다
앞선 priority를 줄 수 있다. Direct Strategy나 stored-result analysis에는 이 event가 없다. Forward label의
`available_at`은 horizon을 반영해야 하며, 누락된 `horizon_end` requirement는 계산 전에 실패한다.

\* `SETTLEMENT`·`FUNDING`·`EXPIRY`는 future extension characterization이다. Exchange가 Clock을 직접
조작하지 않는다. Instrument registration 시 필요한 event specification을 반환하고 engine/flow가 Clock에
callback을 등록한다. §13.6과 §16 참조.

새 event나 direct operation을 추가할 때 freeze, requirements, permitted read, calculation, commit, evidence와
validation을 모두 채워야 한다. Event 이름이나 global stage enum을 추가하는 것만으로 설계가 끝나지 않는다.

---

## 4. 불변식

아키텍처의 실체는 부품 목록이 아니라 어겨서는 안 되는 규칙이다. 각 항목은 테스트 가능해야 한다.

| # | 불변식 | 검증 방법 |
|---|---|---|
| **I1** | Clock만 시간을 움직인다. 어떤 부품도 `datetime.now()`를 부르지 않는다 | 소스 스캔 테스트 |
| **I2** | 모든 데이터 접근은 clock-bound view를 경유한다. View는 `available_at <= clock.now()`를 우회할 수 없고, store 직접 접근·전역 provider·모듈 상태는 금지한다 | import 방향 테스트 + view 질의 술어 검사 |
| **I3** | 모든 component clock은 kernel이 같은 시각으로 함께 전진시킨다. 어떤 component도 홀로 앞설 수 없다 | clock 단조성 테스트 |
| **I4** | 커밋되는 authoritative state store는 Ledger와 Memory 둘이다. 둘 다 flow의 commit boundary에서만 변경된다. Operation은 어느 쪽도 직접 쓰지 않는다 | 공개 API 표면 테스트 |
| **I5** | 모든 operation은 typed result + diagnostics를 반환하거나 commit 전에 `OperationError`로 실패한다 | contract test |
| **I6** | Catalog는 append-only. 같은 identity + 다른 content는 conflict 실패 | 발행 테스트 |
| **I7** | 같은 frozen config + 같은 데이터 → 같은 event 순서 → 같은 결과 | 2회 실행 비교 |
| **I8** | Requirement는 선택한 operation을 호출할 때 resolve한다. 누락은 unrelated registration이나 workflow를 무효화하지 않고 state mutation 전에 실패한다 | progressive-requirement fixture |
| **I9** | Success, failure, retry, actual state와 intended state는 서로 다른 typed evidence다. Failure나 intended state를 authoritative success로 승격하지 않는다 | artifact/reconciliation fixture |

**I1**이 가장 자주 깨진다. Backtest에서 wall clock을 읽는 것은 조용한 재현성 파괴다.

**I2와 I3도 2026-08-03 개정되었다.** 초안의 I2는 event마다 조립한 context를 전제했고, I3는 그
context의 파생 규칙이었다. View 모델에서는 시간 경계가 clock 한 곳에서 강제되므로 두 불변식이
그에 맞게 다시 쓰였다. §18 참조.

**I4는 2026-08-03 개정되었다.** 초안은 "Ledger가 유일한 mutable state"였으나 Strategy memory와
feedback cursor도 checkpoint/resume 뒤 다음 decision의 의미를 바꾼다. Memory는 Strategy가 직접
변경하지 않고 proposed state를 flow가 commit한다. §17 G1 참조.

**I5**는 명시적 실패와 diagnostics 보존을 타입으로 강제한다. 진단을 버리려면 `_`로 명시적으로
받아야 하고, 그러면 코드 리뷰에서 잡힌다. Requirement gap은 계산 결과의 한 종류가 아니라 계산 전
실패이므로 partial result를 success로 publish하지 않는다.

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
    def schedule(self, event: Event, callback: Callable[[Event], None]) -> None: ...
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

### Clock implementation 교체

```
BacktestClock   데이터 끝까지 즉시 감는다
LiveClock       실제 시각을 기다린다
```

Clock 교체는 event progression 차이만 설명한다. Backtest와 production은 같은 Strategy decision과
actual-feedback contract를 공유하지만 stream source, Executor/OMS adapter, persistence와 authority source도
명시적으로 교체된다. Clock만 바꿔 simulated Fill을 production Fill로 해석하지 않는다. ③ view와 ④
operation contract는 유지되고 ② flow가 선택한 runtime profile의 port를 조립한다.

### 채택하지 않는 것

qlib `TradeCalendarManager`(`backtest/utils.py` L23)는 `freq` 하나와 `trade_step` 하나를 갖는다.
독립 cadence를 가진 병렬 clock을 표현할 수 없다. `NestedExecutor`(`backtest/executor.py` L310)는
계층만 제공하며 형제 관계를 표현하지 못한다.

---

## 6. ② flow

### 책임

선택된 operation graph를 실행한다. 무엇을 어떤 순서로 부르고 어느 result를 commit/publish할지만 안다.
Requirement를 해결하거나 경제적 결과를 계산하지 않는다.

```python
def invoke(operation, trigger) -> OperationOutcome:
    invocation = freezer.freeze(operation, trigger)
    resolved = resolver.resolve(operation.requirements(invocation), registry)
    if resolved.failed:
        failure = OperationError.from_resolution(invocation, resolved)
        artifacts.publish_failure(failure)       # success artifact나 state mutation 없음
        return OperationOutcome.failed(failure)

    view = gate.scoped_view(invocation, resolved)
    result, diagnostics = operation.run(view)
    return OperationOutcome.succeeded(result, diagnostics, lineage=view.accessed())


def on_decision(ev: Event) -> None:
    outcome = invoke(profile.strategy_operation, ev)
    artifacts.publish(*outcome.artifacts)
    if outcome.failed:
        return
    if outcome.decision_intent is None:           # research-only result or explicit hold
        finalizer.commit_non_execution(outcome)   # explicit policy + CAS; evidence 기록
        return
    pending = finalizer.prepare(outcome)           # proposed memory는 아직 authority가 아님
    for spec in profile.executor.plan(pending.decision_intent, decision_ts=ev.ts):
        clock.schedule(spec.to_event(), on_execution)  # fill은 여기서 만들지 않는다


def on_execution(ev: ExecutionEvent) -> None:
    view = gate.execution_view(ev.ts, ev.requirements)
    result = profile.executor.execute(ev, view, sink=ledger.fill_sink())
    artifacts.publish(result)                     # sink commit 뒤 actual result
    if result.completes_decision:
        finalizer.commit_simulation_checkpoint(result.decision_id, ledger, memory)


def on_mark(ev: Event) -> None:
    view = gate.execution_view(ev.ts, profile.mark_requirements)
    mark, diagnostics = profile.valuation.run(view)
    ledger.mark(mark.prices)
    artifacts.publish(ledger.snapshot(as_of=ev.ts), diagnostics)


def on_monitor(ev: Event) -> None:
    view = gate.monitor_view(ev.ts, profile.monitor_requirements)
    snap = account_authority.snapshot(as_of=ev.ts)
    findings, diagnostics = profile.monitor.evaluate(snap, view)
    artifacts.publish(findings, diagnostics)      # account를 건드리지 않는다
```

`account_authority`는 simulation에서는 Ledger, production에서는 reconciled OMS account port다. Runtime
monitoring은 이 현재 authority를 읽는다. Stored snapshot의 `as-was`/`as-if` 재평가는 별도 analysis
invocation이 Catalog artifact를 명시적으로 입력받아 같은 pure evaluator를 호출한다. `latest` 파일을
암묵적으로 선택해 runtime authority와 historical evidence를 섞지 않는다.

Proposed Memory의 commit timing도 profile contract다. Research-only/hold는 explicit non-execution
finalization에서, simulation decision은 마지막 execution result와 checkpoint를 묶을 때, production은 OMS
reconciliation이 completed checkpoint를 만들 때 CAS commit한다. PreparedDecision publish나 OMS
acknowledgement만으로 Strategy memory를 advance하지 않는다.

### Executor는 횡단면 batch sub-flow다

**Exchange와 Executor는 다른 것이다.**

```
Exchange   이 시각·venue/profile에서 얼마나 체결되나   상태를 쓰지 않는 계산. ④ operation.
Executor   그 집합을 언제 어떤 event로 넘기나          sub-flow. ② flow. 계산하지 않음.
```

qlibx의 기본 단위는 **decision time의 횡단면**이다. 3000종목 일봉은 같은 순간에 함께 확정되므로
3000개의 개별 event로 쪼개지 않는다. Executor는 한 시점의 주문 집합을 통째로 받아 처리한다.

```
on_decision (flow)
    │ specs = executor.plan(orders, decision_ts)
    │ flow가 specs를 Clock에 등록       ← orders는 event payload, 숨은 pending store 없음
    ▼
on_execution(event) (flow)
    │ view = gate.execution(event.ts)
    ▼
┌────────────────────────────────────────────────────────┐
│ Executor (sub-flow)                                     │
│   q, v = view.quotes(), view.volumes()  ────────────────┼→ ③ view
│   fills, diags = exchange.match_batch(  ────────────────┼→ ④ operation
│       at=event.ts, orders=event.orders,                 │
│       instruments=compiled_terms, quotes=q, volumes=v, │
│       cash=sink.cash(),                                 │
│   )                                                     │
│   sink.apply_batch(fills)                     ──────────┼→ ⑤ ledger (좁은 port)
│   return ExecutionResult(fills, diags)                  │
└────────────────────────────────────────────────────────┘
```

### 계약

```python
class Executor(Protocol):
    def plan(self, decision: DecisionIntent, decision_ts: Timestamp) -> list[ExecutionSpec]: ...
    def execute(self, event: ExecutionEvent, view: ExecutionView,
                sink: FillSink) -> ExecutionResult: ...
    def limitations(self) -> tuple[ExecutionLimitation, ...]: ...
```

`Orders`는 단건 목록이 아니라 instrument축 배열 묶음이다. `match_batch`는 §8의 clipping 순서를
elementwise 연산으로 수행한다.

여러 venue가 지원되면 Executor가 stable venue order로 partition하고 shared cash, currency와 collateral
semantics를 명시해야 한다. 현재 stock/ETF scope는 하나의 execution profile로 시작한다. Venue 순서에 따라
공유 현금 결과가 달라질 수 있으므로 이 규칙 없이 병렬 실행하지 않는다.

첫 vertical slice는 daily executor 하나로 시작할 수 있지만 architecture validation은 같은 immutable
decision을 daily profile과 intraday/partial-fill characterization profile이 각각 처리하는 `UC-EXEC-001`을
포함한다. Intraday profile은 별도 public class name을 요구하지 않으며, schedule granularity, required market
binding, liquidity model과 limitation을 위 계약 뒤에서 선언한다. 지원하지 않는 granularity를 daily fill로
조용히 축약하지 않는다.

### FillConvention — 체결가 규약을 분리한다

Executor가 정하는 것은 **일정**(언제 몇 번 넘기나)이고, 체결가 규약은 별도 축이다. 둘을 묶으면
"종가 체결"을 "시가 체결"로 바꾸는 데 executor를 새로 써야 한다.

```python
class FillConvention(Protocol):
    def reference_price(self, view: ExecutionView) -> Prices: ...   # instrument축 배열
```

```
CloseFill      execution event까지 available한 eligible close에 체결
NextOpenFill   다음 거래일 시가에 체결
VWAPFill       구간 VWAP
```

**`CloseFill`은 명시적 simulation convention이며 낙관적일 수 있다.** 가격은 StrategyView에서 복사하지
않고 execution event의 `available_at <= event.ts`를 만족하는 ExecutionView에서 읽는다. Decision cutoff와
같은 시점의 아직 공개되지 않은 종가를 사용하려 하면 `UC-EXEC-002` validation이 Fill 전에 실패한다.
Result artifact는 convention identity, decision time, fill time, modelled/unmodelled liquidity와 limitation을
기록한다.

Convention 교체는 Strategy decision artifact를 바꾸지 않는다. 다만 required market binding, execution
schedule과 actual Fill이 달라질 수 있으므로 Executor profile이 compatibility를 검증하고 그 dependency를
기록한다. `exchange.match_batch`는 선택된 convention이 ExecutionView에서 만든 가격 배열만 받는다.

### batch가 closed loop를 해치지 않는다

한 event가 횡단면 전체를 나른다는 것과, 시간 축이 순차라는 것은 서로 독립이다.

```
피드백 유무   →  시간 축이 순차인가로 결정   →  qlibx: 순차. 유지.
event 입도    →  종목별인가 횡단면인가       →  qlibx: 횡단면. batch.
```

시간 축이 순차이므로 다음이 모두 성립한다.

- 부분체결 후 다음 decision은 requested target이 아니라 **실제 보유**에서 계산한다 (PRD §4.3)
- Blocked liquidation은 포지션에 남아 다음 decision에 포함된다 (PRD §4.3)
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
fills, diags = exchange.match_batch(
    at=event.ts, orders=orders, instruments=compiled_terms,
    quotes=quotes, volumes=volumes, cash=cash,
)                                                                    # explicit input의 순수 계산
sink.apply_batch(fills)                                               # flow가 반영
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

### Minimal registration과 progressive requirement resolution

최초 dataset registration은 모든 미래 workflow의 schema를 요구하지 않는다. 다음 최소 계약만
validation하고 logical dataset identity를 발행한다.

```text
logical key / instrument axis
event time binding
available_at binding 또는 user-confirmed derivation rule
payload location, shape, null/uniqueness facts
semantic category와 source provenance
```

Currency, universe, sector, benchmark, tradability, OHLCV, lot, label horizon과 compliance binding은 이를
실제로 사용하는 operation이 requirement로 선언한다. Requirement는 field name이 아니라 semantic role,
axis, time, unit/shape와 compatibility condition을 표현한다.

```python
@dataclass(frozen=True)
class ComponentRequirement:
    requirement_id: str
    semantic_role: str
    axis: AxisRequirement
    time: TimeRequirement
    compatibility: tuple[CompatibilityRule, ...]

class RequirementResolver(Protocol):
    def resolve(self, requirements: tuple[ComponentRequirement, ...],
                registry: RegistrySnapshot) -> Resolution: ...
```

Resolver는 user 의미를 추측하지 않는다. 등록된 binding으로 충족되면 immutable `ResolvedBinding`을 만들고,
부족하면 operation과 hierarchical stage path, requirement ID, bounded observed fact, commit status와 retry
precondition을 담은 `OperationError`를 반환한다. Agent가 이 evidence와 bundled skill을 해석해 binding
보강, derived dataset, 다른 profile 또는 local extension 후보를 제시한다. User가 선택한 결과만 package가
다시 validation한다.

같은 physical source를 Strategy, compliance와 report가 서로 다른 semantic binding으로 사용할 수 있다.
실제로 resolve되고 읽힌 binding만 lineage에 남으며, 등록됐지만 쓰지 않은 metadata는 dependency가 아니다.

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
발생하지 않는다. User project가 source 의미와 실제 공개 가정을 소유하고 qlibx가 confirmed binding의
형식, coverage와 PIT 적용을 validation하므로, 이 배치는 PRD의 책임 분담과 일치한다. 대신 data
registration과 operation별 time requirement 검증이 §1 설계 명제를 지탱하는 핵심 경계가 된다.

### 역할 경계 — view 구성

| view | resolve할 수 있는 facade | 구조적으로 제외 |
|---|---|---|
| `StrategyView` | Strategy가 선언한 PIT data/artifact, 필요한 actual state·feedback·memory | undeclared binding, future feedback |
| `ExecutionView` | profile이 선언한 quote/volume/lot/tradability와 actual positions/cash | signal/label, unconfirmed account state |
| `MonitorView` | committed account snapshot + declared compliance binding | undeclared Strategy data, mutable account port |
| `MaterializeView` | Model/transform이 선언한 feature/label/source data | positions/cash unless explicitly required |

View 이름이 global field 목록을 뜻하지 않는다. Resolver가 이번 operation에 허용한 binding만 facade에
넣는다. Compliance data나 monitoring finding을 Strategy에 쓰려면 Strategy requirement가 이를 명시해야
하며 자동 feedback하지 않는다.

```python
view = views.strategy(
    resolved=resolver.require("strategy.monitoring_findings"),
    findings=catalog.findings(before=clock.now()),
)
```

이때 (1) 어떤 finding을 소비했는지 기록되고, (2) `available_at` 조건이 적용되며, (3) lineage에
dependency edge가 남는다.

### 조회 창구 계약

```python
class PanelView(Protocol):
    """횡단면 패널 조회. clock 에 묶인다."""
    def panel(self, binding: ResolvedBinding, lookback: Lookback) -> DataFrame: ...
    def universe(self, binding: ResolvedBinding) -> Index: ...
    def accessed(self) -> list[AccessRecord]: ...

class PositionView(Protocol):
    def positions(self) -> Mapping[str, Quantity]: ...
    def cash(self) -> Money: ...
    def nav(self) -> Money: ...
```

`Protocol`은 읽기 전용이다. 쓰기 메서드를 노출하지 않는다 — nautilus의 `CacheFacade` /
`PortfolioFacade`와 같은 배치다. 임의 문자열 field를 조회하지 않고 Resolver가 이번 invocation에 발급한
`ResolvedBinding`만 받는다. 다른 operation의 binding이나 undeclared field를 넘기면 access 전에 실패한다.

`lookback`은 rows와 duration semantics를 구분하며 질의에 그대로 반영되어 조회량을
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

이 부분은 §14에서 여전히 순수 창작으로 분류한다. 세 reference 어디에도 대응물이 없다.

### 접근 기록이 lineage가 된다

View는 조회를 기록한다. 따라서 "이 Strategy/operation이 실제로 무엇을 읽었는가"가 관측에서 나온다.

```python
result, diag = operation.run(view)
artifacts.publish(result, lineage=view.accessed())
```

PRD §7.4는 derived artifact가 의존 input을 stable identity로 기록하도록 요구한다. 선언 기반은
실제 사용과 어긋날 수 있으나 접근 기록은 어긋나지 않는다. 초안의 사전 선언 방식보다 강한 보장이다.

### Runtime profile 간 view 동형성

View와 operation은 clock implementation, execution adapter와 storage backend가 무엇인지 모른다. 모든 profile은
같은 `available_at <= evaluation_time`, resolved binding과 access-record contract를 만족한다.

```
backtest    BacktestClock + historical stream + simulated Ledger
production  LiveClock     + arrival stream + reconciled OMS account
```

Gate와 operation 구현은 한 벌이다. 다만 Clock만 바꾸면 production이 되는 것은 아니며 profile이 stream,
Executor/OMS port와 authority source를 함께 조립한다. 이 차이는 view를 복제하지 않고 port identity와
lineage로 드러난다.

---

## 8. ④ operation

### 공통 계약과 선택 가능한 graph

각 operation은 requirement를 먼저 선언하고 resolved view에서 typed result와 diagnostics를 계산한다.
공통 모양은 같지만 result type과 graph 위치는 operation마다 다르다.

```python
class Operation(Protocol[ResultT]):
    def requirements(self, invocation: FrozenInvocation) \
            -> tuple[ComponentRequirement, ...]: ...
    def run(self, view: ScopedView) -> tuple[ResultT, Diagnostics]: ...

class StrategyOperation(Operation[StrategyResult], Protocol): ...
class MaterializeOperation(Operation[ResearchDataArtifact], Protocol): ...
class AnalysisOperation(Operation[AnalysisArtifact], Protocol): ...
class RendererOperation(Operation[ReportArtifact], Protocol): ...
```

`StrategyResult`는 signed alpha weights를 보존하고 closed-loop workflow이면 executor-neutral
`DecisionIntent`를 함께 제공한다. Strategy가 signal과 weights를 내부에서 한 번에 계산해도 되고,
`MaterializeOperation`이 만든 signal/characteristic/risk result를 읽어도 된다. Public boundary를 넘거나
재사용되는 intermediate만 정확한 semantic artifact로 materialize한다.

```python
Strategy.run(view)              -> (StrategyResult, Diagnostics)
EnsembleStrategy.run(view)      -> (StrategyResult, EnsembleDiagnostics)
ModelOrTransform.run(view)      -> (ResearchDataArtifact, Diagnostics)
construct(weights, view)        -> (PhysicalTarget, Diagnostics)       # optional
adjust(candidate, view)         -> (AdjustmentResult, Diagnostics)     # optional
convert(target, view)           -> (Orders, ConversionLog)             # optional
validate(candidate, view)       -> (Verdict, Findings)                 # optional
analyze(artifact, view)         -> (AnalysisArtifact, Diagnostics)     # optional
render(analysis, options)       -> (ReportArtifact, Diagnostics)       # optional
exchange.match_batch(at, orders, instruments, quotes, volumes, cash)
                                -> (Fills, FillDiagnostics)
```

첫 view 인자는 **clock과 resolved requirements에 묶인 조회 창구**다(§7). Operation은 필요한 만큼
조회하며 view가 실제 접근을 lineage로 기록한다. Constraint-free analysis, direct Strategy와 stored-result
reuse는 construct/adjust/convert/validate를 호출하지 않는다.

Ensemble은 별도 mandatory stage가 아니라 `StrategyOperation` 구현이다. Member Strategy result를 typed
artifact로 읽고 ticker-level netting, crossing, member contribution과 fixed/flexible budget residual을
기록한다. Member producer가 direct Strategy인지 Model result를 소비했는지는 Ensemble public contract가
아니다.

Path-dependent result도 재사용 가능하다. Compatibility operation은 source state/feedback cursor와 target
state의 차이를 warning으로 제시하고, user가 historical intent replay 또는 target state에서 Strategy rerun을
선택한 decision artifact를 남긴다. 다른 execution history라는 이유만으로 무조건 거부하거나 조용히
재사용하지 않는다.

`exchange.match_batch`만 view를 받지 않는다. 필요한 관측값은 Executor가 view에서 꺼내고, effective-dated
policy를 고르기 위한 event time은 `at`으로 명시한다. Exchange는 wall clock을 읽지 않으며 같은 frozen
instrument/exchange config, `at`과 배열 입력에서 같은 결과를 낸다. 인자는 instrument축 배열이며 clipping이
elementwise로 수행된다.

모두 typed result와 diagnostics를 반환한다(I5). 이 layer는 state를 직접 변경하지 않으므로 built-in,
project-local과 external implementation을 같은 validation boundary 뒤에서 교체할 수 있다. Package가
compatibility를 판정하고 agent는 failure evidence를 해석할 뿐 등록 성공을 대신 선언하지 않는다.

### Constraint adjustment, validation과 monitoring

세 operation은 authority와 output이 다르다.

```text
adjust proposed intent   → modified candidate + unresolved residual
validate final candidate → execution eligibility + finding
monitor committed actual → actual-account finding; account mutation 없음
```

Adjustment result가 존재해도 compliance를 의미하지 않는다. Constraint를 선택한 workflow만 declaration과
metric data requirement를 resolve한다. Missing sector binding은 order나 hypothetical account를 만들기 전에
실패하고, constraint-free signal research에는 compliance dataset을 요구하지 않는다.

### Instrument와 Exchange registration

Config/registration 경계에서는 concrete Pydantic model을 사용한다. Generic `kind + parameters` bag으로
상품을 만들지 않는다.

```python
engine.add_exchange(KrxExchange(exchange_id="XKRX", cost_schedule=krx_schedule))
engine.add_instrument(samsung)
engine.add_instrument(kodex_etf)
```

`engine.add_instrument`는 stable ID와 concrete type을 registry에 넣고 `venue_id`의 Exchange에 listing을
등록한다. Exchange는 instrument compatibility와 required policy coverage를 검증한다. Tracking-only Index는
명시적인 executable listing이 없으면 order를 거부한다. Future extension의 `AcademicExchange`는 가격과 수량
semantics를 명시한 Index만 hypothetical listing으로 받을 수 있고 result에 profile identity를 남긴다.
Factor는 return-native이며 일반 Exchange는 이를 silently tradable로 만들지 않는다. Future Academic profile은
validated `SyntheticUnitPrice` binding과 unit/lot, cost, liquidity assumption이 있을 때만 Factor를 hypothetical
listing으로 받아 quantity/Fill 경로를 사용할 수 있다. Binding이 없으면 return-based research만 허용한다.

Instrument와 Exchange model은 생성 시 한 번 검증되고 frozen된다. Engine build 단계는 lot, multiplier,
currency, exact cost selector처럼 hot path에 필요한 static term을 stable instrument index의 array로 compile한다.
3,000종목 batch의 fill마다 Pydantic model을 다시 만들지 않는다.

Future extension에서 Exchange는 registration 결과로 lifecycle `EventSpec`을 반환할 수 있다. Flow가 이를
Clock에 등록하며 Exchange가 Clock이나 Ledger를 직접 보유하거나 변경하지 않는다.

### Transaction cost resolution

거래비용 계산의 진입점은 Exchange다. Exchange subclass는 자기 market에 필요한 schedule schema를 갖는다.

```text
KrxExchange       effective date × exact product type × BUY/SELL
AcademicExchange profile-defined hypothetical cost
CryptoExchange    maker/taker × account tier                 (future)
```

연도별 rate 때문에 Exchange subclass를 늘리지 않는다. `KrxExchange2024`, `KrxExchange2025` 대신 하나의
`KrxExchange`가 versioned effective-dated schedule을 가진다. Cost entry는 exact concrete product selector로
해결하며 ETF가 Equity의 subtype이라는 이유로 Equity rule을 상속하지 않는다. ETF 0bp도 명시적인 rule이다.
Required rule이 없으면 structured unsupported failure를 반환하고 Fill과 Ledger mutation을 만들지 않는다.

공개 `CostContext`는 두지 않는다. Order, Instrument/compiled terms, fill quantity/price와 event time이 이미
입력이다. Mandatory `CostBreakdown`도 두지 않는다. Fill은 최소한 `total_cost`, applied rule ID와 schedule
version을 보존하고, tax/commission attribution 요구가 생기면 optional cost line을 추가한다.

Cash clipping과 final Fill은 같은 pure cost calculator를 사용한다. Candidate quantity의 비용을 계산해 현금을
검사하고, clipped quantity로 다시 계산해 final Fill에 기록한다. 별도의 estimated-cost 구현을 두지 않는다.
Broker/account commission은 후속 account overlay가 될 수 있다. Current profile에서는 Exchange instance를
venue + execution profile로 보고 함께 freeze한다.

### exchange.match_batch — 차용의 핵심

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

Nautilus `backtest/models/{fee,fill}.pyx`에서는 `order`, `fill_qty`, `fill_px`, `instrument`를 직접 전달하는
교체 가능한 계산 경계를 참고한다. qlibx의 public entrypoint는 Exchange의
`calculate_transaction_cost(...)`이며 내부 calculator protocol은 재사용이 실제로 필요할 때만 추출한다.
Fill price model은 별도 교체 경계로 유지해 slippage/impact를 fee/tax와 이중 집계하지 않는다.

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

PRD §10.3의 best-effort adjustment와 independent validation은 다른 책임이다. 전자는 조정하고
후자는 판정한다. 조정 결과가 존재한다는 사실이 compliance를 보증하지 않는다.

---

## 9. ⑤ ledger

### 계약

```python
class Ledger:
    def apply_fills(self, fills: Fills) -> None: ...
    def apply_cashflows(self, cashflows: CashFlows) -> None: ...       # future lifecycle
    def apply_position_deltas(self, deltas: PositionDeltas) -> None: ...  # future lifecycle
    def mark(self, prices: Mapping[str, Price]) -> None: ...
    def snapshot(self, as_of: Timestamp) -> AccountSnapshot: ...  # 불변 복사본
    def fill_sink(self) -> FillSink: ...
```

Current stock/ETF path는 Fill과 mark만 사용한다. Future extension은 funding, variation margin, expiry와
corporate action을 Fill로 위장하지 않고 cash/position delta로 commit한다. Target weight를 넣어 상태를
바꾸는 경로는 존재하지 않는다 — PRD §4.3이 API 형태로 박혀 있다.

Transaction cost는 Fill에 귀속된다. Funding과 variation margin은 거래가 없어도 발생하므로 lifecycle cash
flow다. Flow만 위 mutation method를 호출하고 Exchange는 계산 결과만 반환한다. 다음 decision view는 commit된
cash/NAV/position을 읽는다.

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
- `update_bar_end` (L338) — bar 종료 mark. no-trade monitoring에도 actual snapshot을 제공
- `is_port_metr_enabled` (L132) — metric 명시적 활성화

vnpy `PortfolioDailyResult.calculate_pnl`:
- **trading PnL / holding PnL 분해.** qlib에는 없다. Actual-state analysis와 budget residual attribution의
  출발점이다.

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
class ArtifactPublisher(Protocol):
    def publish(self, *candidates: ArtifactCandidate,
                lineage: tuple[AccessRecord, ...] = ()) -> tuple[ArtifactId, ...]: ...
    def publish_failure(self, failure: OperationError) -> ArtifactId: ...

class ArtifactLoader(Protocol):
    def load(self, artifact_id: ArtifactId, expected: ArtifactContract) \
            -> TypedArtifact: ...
```

Publisher는 payload, envelope와 dependency edge를 하나의 publication transaction으로 다룬다. Payload만
쓰였거나 index commit이 실패한 candidate는 reusable artifact로 보이지 않는다. 덮어쓰기 API가 없고(I6),
같은 logical identity + 같은 content는 idempotent, 같은 identity + 다른 content는 conflict 실패다.

Loader는 raw dictionary를 public consumer에 통과시키지 않는다. Type/version registry에서 schema를 찾고
payload를 적합한 typed object로 생성하면서 required field, logical key uniqueness, semantic category,
time/axis/unit와 cross-field invariant를 검증한다. Unknown version은 explicit migration 또는 unsupported
error이며 producer의 private Python class를 import하지 않는다.

### Envelope

Public envelope는 Pydantic 모델로 정의한다(§11). 이는 architecture가 선택한 boundary implementation이며
다른 implementation도 같은 object-construction validation과 portable schema를 제공하면 교체 가능하다.

Default local backend의 payload는 tabular/matrix는 Parquet, metadata/config는 JSON이다. 물리 layout은 nautilus
`persistence/catalog/parquet.py`를 참고한다 — 특히 parquet metadata로 시간 범위를 인덱싱해 전체를
읽지 않는 기법(L570), 중복 제거(L820), 스키마 검증(L781).

표면 API(`save`/`load`/`list_all_*`)는 vnpy `alpha/lab.py::AlphaLab`을 따른다. 단 vnpy에는
fingerprint, lineage, envelope, 원자적 발행이 없으므로 **형태만 차용하고 내용은 새로 만든다.**

Default local catalog index는 duckdb로 둔다. Object store나 external tracker backend도 같은
`ArtifactPublisher`/`ArtifactLoader` contract, logical identity, atomic visibility와 conflict outcome을
만족해야 한다. External tracker run ID나 file path는 producer reference일 수 있지만 canonical artifact
identity를 대신하지 않는다.

### Lineage

```
registered PIT data ─┬→ direct Strategy ────────────────┐
                     └→ materialized research data ─────┤
member Strategy results ─→ Ensemble Strategy ───────────┤
                                                         ├→ signed weights
instrument/profile/constraint ───────────────────────────┤
                                                         ├→ physical target → decision → fills
                                                         └→ analysis → report
actual account snapshot + compliance binding ─────────────→ monitoring finding → report
failure evidence + resolution decision ───────────────────→ retry invocation
```

Edge는 consumer role, 선택된 field/column, version/fingerprint, 시간 호환성을 기록한다. Graph는
acyclic이어야 하며 mutable alias만으로 dependency를 식별하지 않는다. Content hash가 같아도 economic
meaning, state cursor나 contract가 다르면 같은 logical artifact로 합치지 않는다.

### Failure, retry와 publication status

`OperationError`도 frozen invocation, actual stage path, requirement/error identity, commit status와 bounded
diagnostic을 가진 typed evidence로 publish한다. Retry는 failure를 덮어쓰지 않고 `resolves_error_id` edge로
연결한 새 invocation이다. 실패한 fit, rejected research, invalid external payload와 partial publication을
success catalog query에서 숨기되 audit query에서는 찾을 수 있어야 한다.

### Analysis, renderer와 extension boundary

Analysis는 stored result를 읽어 metric/table artifact를 만들고 Renderer는 그 값을 presentation으로만
변환한다. Table, chart와 machine-readable renderer가 달라도 return, cost, exposure와 failure count의
underlying artifact identity는 같다. Renderer 안에서 metric을 재계산하지 않는다.

Built-in과 project-local/external operation은 같은 `ComponentRequirement`, typed result와 validation fixture를
제공한다. Extension registration은 package compatibility validation이 성공한 뒤에만 commit한다. Agent가
code를 작성하거나 error를 설명할 수는 있지만 compatibility success를 선언하지 않는다.

### Production outbox와 reconciliation

Production flow도 같은 evidence boundary를 사용하되 prepared intent와 authoritative outcome을 분리한다.

```text
Strategy result
  → immutable PreparedDecision + idempotency identity
  → atomic outbox publication                    # Ledger/Memory advance 없음
  → external OMS acknowledgement                 # Fill 아님
  → confirmed fill/reject/cancel/account result
  → correlate + deduplicate + order-state reconcile
  → commit confirmed delta/account snapshot only
  → next Strategy view and independent monitoring
```

```python
class Reconciler(Protocol):
    def reconcile(self, prepared: PreparedDecision,
                  received: tuple[OMSResult, ...],
                  account: ConfirmedAccountSnapshot) -> ReconciliationResult: ...
```

Reconciler는 missing, duplicate, stale, out-of-order와 conflicting result를 state mutation 전에 구분한다.
Partial fill은 confirmed quantity만 apply하고 remainder의 pending/cancel state를 추측하지 않는다. Rejection은
evidence를 남기지만 intended position이나 proposed Strategy state를 actual로 commit하지 않는다. 같은
idempotency identity의 duplicate delivery는 두 번 적용하지 않는다. Production `account_authority`는 이
reconciliation이 확인한 account snapshot이며 outbox publish나 OMS acknowledgement가 아니다.

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
| Concrete `Instrument`, Exchange config, cost schedule entry | compiled instrument arrays |
| `ArtifactEnvelope`, `DependencyEdge` | `ScopedView`, `ResolvedBinding` |
| `OperationError` (§7) | `Order`, `Fill` |
| Instrument/Exchange registration | `CashFlow`, `PositionDelta`, diagnostic 행 |
| `ConstraintDeclaration` | `Diagnostic` 행 |
| `ComponentRequirement` | `Position`, `Account` |
| `DatasetRegistration` | `AccountSnapshot` |
| `ExtensionContract` | 통계 반환값 (JSON primitive) |
| `PreparedDecision`, `OMSResult`, `ReconciliationResult` | |

pydantic 대상은 전부 **저빈도 + 경계**, dataclass 대상은 전부 **고빈도 + 내부**다.

`InstrumentSet[T]`도 registration boundary에서는 전체 collection을 한 번 검증하지만, execution 전에는 stable
instrument index와 typed array로 compile한다. `Order`, `Fill`, `CashFlow`를 만들 때 concrete Instrument나
cost schedule을 다시 Pydantic validation하지 않는다. 이것이 `UC-SCALE-001`의 architecture mechanism이다.

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

pydantic `ValidationError`를 그대로 노출하지 않고 §7의 hierarchical operation error로 번역한다.

```python
except ValidationError as e:
    raise OperationError(
        operation="dataset.register",
        stage_path="dataset.register.schema",
        error_code="SCHEMA_VALIDATION_FAILED",
        requirement_id="dataset.minimal_schema",
        expected=FrozenConfig.model_json_schema(),
        context={"fields": [...][:MAX_REPORTED]},
        commit_status="NONE",
        retry_preconditions=("provide a schema-valid candidate",),
        idempotency_identity=invocation.id,
        error_id=new_error_id(),
    ) from e
```

`e.errors()`의 `loc`가 필드 경로를 제공하지만 개수를 제한한다. Package는 observed fact와 retry
precondition을 제공하고, 어떤 경제적 의미를 선택하거나 user에게 어떤 질문을 할지는 bundled agent skill이
판단한다.

### 고빈도 데이터의 검증 위치

Diagnostic은 행마다 검증하지 않는다. Arrow 스키마가 이미 타입 검증이다.

```
행 단위 검증  ✗
테이블 단위 스키마 선언 + 1회 검증  ✓
```

pydantic 모델은 **테이블의 계약서** 역할만 하고 인스턴스는 만들지 않는다. 여기서 Arrow 스키마와
JSON Schema를 함께 파생시킨다.

### 부수 효과: 스키마 자동 생성

`model_json_schema()`는 external artifact, operation requirement와 extension contract의 machine-readable
schema를 같은 type definition에서 생성하는 architecture mechanism이다. Pydantic 자체가 product requirement는
아니지만, 손으로 별도 관리하는 schema가 runtime validation과 어긋나는 구현은 허용하지 않는다.

---

## 12. 패키지 layout과 의존 방향

```
src/qlibx/
  kernel/       clock  event  queue  engine          ① 시간
  flow/         decision  mark  monitor  executor/   ② 순서
  context/      scoped  strategy  execution  monitor  gate  ③ 시야  ★
  data/         registry  requirement  resolver  provider
  operations/   strategy  model  ensemble  extension ┐
  portfolio/    construct  optimizer/                ├ ④ 계산
  execution/    adjust  convert  validate  exchange/ ┘
  ledger/       position  account  pnl  sink         ⑤ 상태
  evidence/     artifact  catalog  lineage  publisher⑥ 증거
  analysis/     statistic  analyzer  report
  production/   outbox  oms_result  reconcile
  config/       frozen  schema
  errors.py     hierarchical operation error (§7)
  models.py     QlibxModel base
```

### 의존 방향

```
kernel     → 없음
data       → domain schema
context    → kernel, data resolver
operation (strategy/model/portfolio/execution/analysis) → context + domain type
ledger     → domain 객체만
evidence   → domain 객체만
production → evidence + domain type
flow       → context, operation, ledger, evidence, production port
engine     → 전부 (조립 지점)
```

**operation이 ledger나 raw provider를 import하지 않는 것이 핵심이다.** State/data가 필요하면 resolved
scoped view로 들어온다. 그래야 gate와 requirement resolver를 우회할 수 없다(I2, I8).

### 조립

nautilus `system/kernel.py::NautilusKernel`(L101) 방식의 명시적 생성자 주입을 따른다.

```python
engine = Engine(
    clock       = BacktestClock(calendar),
    registry    = DatasetRegistry(...),
    resolver    = RequirementResolver(...),
    gate        = ViewGate(...),
    strategy    = MyStrategy(),
    execution   = DailyExecutionProfile(exchange, fill_convention),
    ledger      = Ledger(initial_cash=...),
    memory      = StrategyMemoryStore(...),
    artifacts   = LocalArtifactBackend(catalog),
)
```

qlib의 `common_infra.get("trade_account")` 문자열 키 서비스 로케이터는 채택하지 않는다. 타입이
사라지고 resolved requirement, frozen invocation과 authority source를 우회하므로 채택하지 않는다.

---

## 13. PRD use-case walkthrough

이 절은 PRD의 stable use-case ID를 architecture flow에 연결한다. 숫자는 법령이나 시장 관행을 주장하기
위한 값이 아니라, 구현이 같은 입력에 같은 결과를 내는지 검증하기 위한 **결정론적 fixture**다.

### 13.1 공통 등록과 fixture

```text
InstrumentRegistry
  005930.XKRX -> Equity
  069500.XKRX -> ETF

KrxExchange
  2024 Equity BUY  : commission 1.5bp, tax  0bp
  2024 Equity SELL : commission 1.5bp, tax 18bp
  2024 ETF BUY/SELL: commission 1.5bp, tax  0bp
  2025 Equity BUY  : commission 1.5bp, tax  0bp
  2025 Equity SELL : commission 1.5bp, tax 15bp
  2025 ETF BUY/SELL: commission 1.5bp, tax  0bp
```

각 행에는 `rule_id`와 `schedule_version`이 있다. Exchange가 Instrument의 구체 타입, side, event
timestamp로 정확한 행을 고르고, build 단계가 Instrument와 schedule을 dense array로 compile한다.

### 13.2 상품·side·유효일 비용 — UC-COST-001, UC-COST-002

2025년에 7,000,000원을 거래하면 다음 결과가 나온다.

```text
Equity BUY  :  7,000,000 × 1.5bp          =  1,050
Equity SELL :  7,000,000 × (1.5 + 15)bp   = 11,550
ETF BUY     :  7,000,000 × 1.5bp          =  1,050
ETF SELL    :  7,000,000 × 1.5bp          =  1,050
```

같은 Equity SELL을 2024 timestamp로 평가하면 `(1.5 + 18)bp = 13,650`이다. Instrument는 자신이
Equity인지 ETF인지 알려줄 뿐 세율을 소유하지 않는다. Exchange가 timestamp와 side까지 포함해
schedule을 해석하므로 같은 상품도 연도와 매매 방향에 따라 비용이 달라진다.

### 13.3 cash clipping과 exact rule — UC-COST-003, UC-COST-004

가용 현금이 7,000,500원이고 가격 70,000원인 ETF를 100주 BUY한다고 하자. 명목금액만 보면 주문이
들어가지만 비용까지 포함하면 `7,001,050 > 7,000,500`이다. lot이 10주라면 동일한 순수 비용 계산기를
사용해 90주로 줄인다.

```text
candidate check : 100 × 70,000 + 1,050 = 7,001,050  -> reject
clipped order   :  90 × 70,000 +   945 = 6,300,945  -> accept
final Fill      : quantity=90, transaction_cost=945
```

candidate check와 최종 Fill이 서로 다른 계산기를 쓰면 closed loop의 cash가 어긋난다. 따라서 둘은
같은 `calculate_transaction_cost(...)`를 호출한다. 반대로 ETF exact rule이 없다면 Equity rule로
추측하지 않고 명시적으로 실패하며, Fill과 Ledger mutation도 만들지 않는다.

### 13.4 실제 체결이 다음 판단으로 돌아오는 loop — UC-CLOSED-LOOP-001

```text
DECISION D1
  -> target/order
  -> EXECUTION E1: exact cost로 cash clipping, Fill 생성
  -> LEDGER COMMIT: position, cash, transaction cost 반영
  -> MARK: valuation과 NAV 갱신
  -> DECISION D2: D1의 목표값이 아니라 E1 이후 actual position/cash/NAV를 읽음
```

예를 들어 위 ETF 주문은 목표 100주가 아니라 실제 90주와 남은 현금 699,555원이 다음 StrategyView에
보인다. 이것이 단순 수익률 계산과 closed-loop backtest의 차이다.

### 13.5 3,000종목 cross-section — UC-SCALE-001

Pydantic Instrument는 등록 시 한 번 검증한다. 그 뒤 build 단계가 stable instrument index, lot size,
product selector와 cost schedule lookup key를 배열로 compile한다. EXECUTION 한 번이 3,000개 주문을
batch로 처리하고, hot loop는 Pydantic 모델을 다시 만들지 않는다. 결과는 stable order의 Fill과
FillDiagnostic으로 돌아가므로 같은 config와 data에서 event 순서와 결과가 재현된다.

### 13.6 미래 확장의 design characterization

다음 항목은 **현재 제품 acceptance가 아니라 미래 설계를 구속하는 characterization**이다.

- **UC-ACADEMIC-001:** Index는 기본 exchange에서 tracking-only다. `AcademicExchange`가 가격과 수량
  semantics를 갖춘 해당 Instrument를 명시적으로 listing한 경우에만 가상 체결할 수 있다. tradability는
  Instrument의 본성이 아니라 Instrument와 Exchange의 관계다.
- **Factor synthetic-price extension:** Factor는 return-native tracking Instrument다. Future Academic profile은
  validated `SyntheticUnitPrice`와 명시적인 unit/lot, cost, liquidity assumption이 있을 때만 hypothetical
  Fill을 만들 수 있다. Synthetic source와 limitation을 evidence에 남기며 일반 Exchange는 listing을 거부한다.
- **UC-FUTURE-001:** multiplier 250,000인 Future 1계약의 settlement price가 350에서 352로 움직이면
  variation margin `+500,000`이 lifecycle cash flow로 Ledger에 반영된다. expiry event는 최종 정산과
  포지션 종료를 유발한다.
- **UC-PERP-001:** notional 50,000인 CryptoPerpetual long 1계약에 `+1bp` funding이 적용되면 long은
  `-5` funding cash flow를 낸다. PerpetualSwap에는 expiry field와 expiry event가 없다.
- **UC-CASHFLOW-001:** transaction cost는 Fill의 비용이고, funding과 variation margin은 lifecycle cash
  flow다. 둘 다 cash/NAV에 반영되지만 같은 집계 항목으로 섞지 않으며 다음 decision에서 actual state로
  관측된다.

통합 테스트와 fixture 이름에 이 use-case ID를 그대로 사용하면 PRD 요구, architecture flow, 검증
증거 사이의 추적성을 유지할 수 있다.

### 13.7 Minimal registration과 progressive gap — UC-DATA-001, UC-DATA-002, UC-ERROR-001, UC-PIT-001, UC-AGENT-001

```text
REGISTER price_source
  → user-confirmed instrument/time/available_at binding
  → minimal validation
  → DatasetRegistration publish                         UC-DATA-001

RUN price_reversal_strategy
  → required price binding resolves
  → Strategy runs

RUN sector_neutral_strategy
  → required sector binding missing
  → dataset/registration은 유지
  → OperationError(strategy.run.requirements.sector)
  → failure evidence publish                            UC-DATA-002
  → agent explains add-binding / derived-data / profile alternatives
  → user selects, package validates, new invocation retries
```

Signal analysis처럼 짧은 invocation은 실제 `analysis.run.requirements`에서만 실패하고 model, optimizer,
order stage를 만들지 않는다(`UC-ERROR-001`). Forward-label materialization은 `horizon_end` requirement를
resolve하지 못하면 label을 만들기 전에 실패한다(`UC-PIT-001`). Availability 의미가 불명확하면 package는
추측하지 않고 structured gap을 내며, agent가 release timestamp나 confirmed delay-rule 후보를 설명한 뒤
user-confirmed binding만 등록한다(`UC-AGENT-001`).

### 13.8 Strategy composition과 state — UC-SIGNAL-001, UC-SIGNAL-002, UC-ALPHA-BUDGET-001, UC-ALPHA-PATH-001, UC-ALPHA-CHILD-001, UC-ALPHA-ADAPTIVE-001, UC-ENSEMBLE-001

Direct reversal Strategy는 PIT price binding을 읽어 내부 score와 signed weights를 만들고 optional academic
profile에서 평가한다. Stored signal이나 physical construction을 요구하지 않는다(`UC-SIGNAL-001`). Value
characteristic을 materialize한 Model result는 typed artifact로 load되어 long-short Strategy와 long-only
Strategy가 producer rerun 없이 각각 소비한다(`UC-SIGNAL-002`).

Flexible-budget result는 invested 40%와 residual 60%를 그대로 저장하고 fixed consumer가 요청되면
compatibility error를 낸다(`UC-ALPHA-BUDGET-001`). 다른 account에서 path-dependent result를 재사용하면
source/target state 차이를 보여주고 historical replay와 Strategy rerun 중 user choice를 기록한다
(`UC-ALPHA-PATH-001`).

```text
parent signed weights ─┬→ daily-close child execution
                       └→ intraday child execution        UC-ALPHA-CHILD-001

member Strategy results → EnsembleStrategy
  → ticker netting/crossing/contribution/residual          UC-ENSEMBLE-001
  → committed fill feedback + prior memory
  → proposed member-weight update
  → flow Memory commit with feedback cursor                UC-ALPHA-ADAPTIVE-001
```

Child는 parent Strategy/Model을 다시 실행하거나 parent state를 바꾸지 않는다. Adaptive update는 commit된
feedback까지만 읽으며 proposed state는 flow commit 전 authority가 아니다.

### 13.9 Portfolio와 optional constraint — UC-PORTFOLIO-001, UC-CONSTRAINT-001, UC-CONSTRAINT-002, UC-CONSTRAINT-ADJUST-001

같은 signed weight artifact를 crypto perpetual long-short profile과 equity enhanced-index profile이 각각
읽는다. 각 construction operation이 direction, instrument, budget, cost와 settlement requirement를 별도로
resolve하고 새 result를 만들며 original alpha artifact를 다시 쓰지 않는다(`UC-PORTFOLIO-001`). 이 예시의
perpetual complete lifecycle은 future characterization이며 current support claim이 아니다.

Constraint가 없는 signal IC/hypothetical return analysis는 compliance binding 없이 끝난다
(`UC-CONSTRAINT-001`). Sector limit을 선택한 conversion은 sector binding을 먼저 resolve하고, 없으면
order/account mutation 전에 실패한다(`UC-CONSTRAINT-002`). Binding이 있으면 adjust가 original/adjusted
intent와 lot-rounding residual을 만들고 validate가 eligibility를 별도로 판정한다. 남은 breach를 adjusted
success로 숨기지 않는다(`UC-CONSTRAINT-ADJUST-001`).

### 13.10 Pluggable execution과 monitoring — UC-EXEC-001, UC-EXEC-002, UC-EXEC-003

하나의 immutable DecisionIntent를 두 child profile이 참조한다. Daily profile은 다음 eligible close처럼
선언된 convention으로 하나의 batch event를 만들고, intraday profile은 필요한 market binding과 여러
execution event를 선언해 partial fill을 만들 수 있다. Decision lineage는 같고 각 child Ledger의 Fill,
cash, position과 이후 feedback만 다르다(`UC-EXEC-001`).

Daily close profile은 decision time과 close observation의 `available_at`을 비교한다. 아직 공개되지 않은
동일 시점 close를 fill price로 요청하면 Fill 전에 실패한다. Volume impact나 partial fill을 모델링하지
않으면 limitation artifact에 남긴다(`UC-EXEC-002`).

MONITOR timer는 decision 유무와 무관하게 `account_authority`의 committed snapshot과 resolved compliance
view를 읽는다. Price drift로 sector breach가 생기면 finding만 publish하고 order나 account mutation을
만들지 않는다(`UC-EXEC-003`).

### 13.11 Artifact, failure, report와 extension — UC-ARTIFACT-001, UC-ARTIFACT-002, UC-RESEARCH-001, UC-REPORT-001, UC-MONITOR-001, UC-EXTENSION-001

External producer가 documented envelope와 payload로 signal을 publish하면 Loader가 producer class import 없이
typed Signal object를 생성하고 semantics/lineage를 검사한다(`UC-ARTIFACT-001`). Duplicate logical key나
payload/semantics mismatch는 object construction 또는 publication을 실패시키고 reusable success로 노출하지
않는다(`UC-ARTIFACT-002`).

Sector gap으로 실패한 Strategy invocation은 failure artifact를 보존한다. Binding 보강 후 retry는 새
invocation/result를 만들고 `resolves_error_id`로 연결하며 실패를 삭제하지 않는다(`UC-RESEARCH-001`).
Analysis artifact 하나를 table/chart/machine renderer가 공유하고 metric을 renderer에서 재계산하지 않는다
(`UC-REPORT-001`). Monitoring report는 actual finding과 intended target을 섞지 않고 breach와 missing input을
구분한다(`UC-MONITOR-001`). Local neutralization transform은 package contract validation이 성공한 뒤에만
registry에 commit한다(`UC-EXTENSION-001`).

### 13.12 Production reconcile — UC-PROD-001, UC-PROD-002

```text
PreparedDecision(100 BUY)
  → outbox publish / OMS ack                    authority 변화 없음
  → confirmed Fill(40) + account snapshot
  → reconcile pending/cancel state
  → confirmed 40과 actual cash만 commit         UC-PROD-001

PreparedDecision
  → OMS rejection
  → rejection evidence publish
  → intended position/Memory commit 없음        UC-PROD-002
```

Duplicate, missing, stale, out-of-order와 conflicting result는 commit 전에 구분한다. Next Strategy와 production
monitoring은 outbox target이 아니라 reconciled account authority만 읽는다.

---

## 14. 차용 출처 매핑

각 표의 마지막 열은 차용 방식을 `코드 차용`, `설계만`, `반면교사`, `순수 창작` 중 하나로 직접 표기한다.

세 reference 모두 **dependency가 아니다.** qlibx는 engine을 직접 구현하며 reference별 license와 아래
분류에 따라 코드, 산술 또는 설계만 선택적으로 차용한다. 채택하지 않은 판단의 근거는 [[why-not-qlib-as-a-backend]]와
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

| 항목 | 출처 | 위치 | 차용 방식 |
|---|---|---|---|
| Clock 추상, TestClock, LiveClock | nautilus | `common/component.pyx` L130/L623/L839 | 설계만 |
| `advance_time` → 시각순 정렬 반환 | nautilus | 같은 파일 L790 | 설계만 |
| TimeEvent / TimeEventHandler | nautilus | L1013 / L1144 | 설계만 |
| 동시각 priority | nautilus | `Subscription.priority` L2911 | 설계만 |
| 단일 시간축 정렬 순회 | vnpy | `alpha/strategy/backtesting.py` L156-166 | 코드 차용 |
| 단일 freq/step 캘린더 | qlib | `backtest/utils.py` L23 | 반면교사 |

### ② flow

| 항목 | 출처 | 위치 | 차용 방식 |
|---|---|---|---|
| 일단위 executor 골격 | qlib | `backtest/executor.py` L513, L561 | 코드 차용 |
| 계층 위임 아이디어 | qlib | 같은 파일 L310 `NestedExecutor` | 설계만 |
| 일별 순회 + 체결 루프 | vnpy | `alpha/strategy/backtesting.py` `new_bars` | 코드 차용 |
| executor 교체 계약, 분할 실행 | nautilus | `execution/client.pyx`, `algorithm.pyx` | 설계만 |
| **callback, FillSink** | — | — | 순수 창작 |

### ③ view ★

> **초안 정정.** 이 표는 원래 "Context 3종, cutoff, bounded load — 어디에도 대응물 없음(순수 창작)"과
> "nautilus에는 Context 객체 자체가 없어 PIT가 구조로 강제되지 않는다"고 기술했다. **후자는
> 사실이 아니다.** nautilus는 Context 객체 대신 이중 timestamp와 `ts_init` 정렬 stream으로 같은
> 보장을 제공하며, 이는 PRD §4.4가 요구하는 메커니즘 그 자체다. §18 참조.

| 항목 | 출처 | 위치 | 차용 방식 |
|---|---|---|---|
| **이중 timestamp** (`ts_event` / `ts_init`) | nautilus | `core/data.pyx` L30, L42 | 설계만 |
| ↳ PRD 대응 | — | `ts_event`=event time, **`ts_init`=`available_at`** (§4.4, §7.2) | — |
| **`ts_init` 오름차순 stream** = PIT 강제 | nautilus | `backtest/engine.pyx` L903, L1658-1735 | 설계만 |
| restatement 표시 | nautilus | `model/data.pyx` L1496 `is_revision` | 설계만 |
| 읽기 전용 facade | nautilus | `cache/base.pxd` `CacheFacade`, `portfolio/base.pxd` | 설계만 |
| ↳ Actor가 보유하는 형태 | nautilus | `common/actor.pxd` L73, L83 (`readonly`) | 설계만 |
| data ↔ timer 실행 순서 | nautilus | `backtest/engine.pyx` L1692, L1731-1735 | 설계만 |
| 명시적 생성자 주입 | nautilus | `system/kernel.py` L101 | 설계만 |
| learn/infer 데이터 분리 | vnpy | `alpha/dataset/template.py` L181-194 | 코드 차용 |
| 시간 범위 표현 | qlib | `backtest/decision.py` L206-300 `TradeRange` | 코드 차용 |
| 문자열 키 서비스 로케이터 | qlib | `common_infra.get(...)` | 반면교사 |
| **횡단면 패널 view** (instrument × field) | — | — | 순수 창작 |
| **접근 기록 기반 lineage** | — | — | 순수 창작 |
| **역할별 view 구성** (compliance 분리) | — | — | 순수 창작 |

시간 경계 메커니즘은 nautilus에서 설계만 차용한다. 남는 순수 창작 영역은 **접근 축**이다. Reference 세 곳은
모두 instrument별 시계열이 기본 단위이고(`cache.bars(bar_type)`은 한 종목의 deque), 메모리 상주
방식이라 20년 × 3000종목을 담지 못한다. qlibx의 기본 단위인 decision time 횡단면과 그것을 컬럼
저장소 질의로 구현하는 부분은 여전히 창작이다.

### ④ operation

| 항목 | 출처 | 위치 | 차용 방식 |
|---|---|---|---|
| **체결 clipping 전체 순서** | qlib | `backtest/exchange.py` **L859-950** | 코드 차용 |
| ↳ volume 참여 제한 | qlib | L786 | 코드 차용 |
| ↳ 제곱 impact cost | qlib | L892 | 코드 차용 |
| ↳ 현금 한도 매수량 | qlib | L834 | 코드 차용 |
| ↳ **마지막 매도 반올림 생략** | qlib | **L904** | 코드 차용 |
| ↳ lot 반올림 / 거래단위 | qlib | L761 / L728 | 코드 차용 |
| 상하한가 / 거래정지 / tradability | qlib | L338 / L378 / L404 | 코드 차용 |
| volume threshold 파싱 | qlib | L295 | 코드 차용 |
| cost·fill model 교체 인터페이스 | nautilus | `backtest/models/{fee,fill}.pyx` L33/L34 | 설계만 |
| clipping 사유를 debug 로그로 폐기 | qlib | L830, L917, L928, L936 | 반면교사 |
| pass / deny-with-reason 구조 | nautilus | `risk/engine.pyx` L584-666, L1073-1132 | 설계만 |
| TradingState | nautilus | 같은 파일 L228 | 설계만 |
| target/actual 이원 관리 | vnpy | `alpha/strategy/template.py` L31-32, L133 | 코드 차용 |
| 4방향 분해 (숏 대비) | vnpy | 같은 파일 L144-185 | 코드 차용 |
| ts 함수 22종 | vnpy | `alpha/dataset/ts_function.py` | 설계만† |
| cs 함수 5종 | vnpy | `alpha/dataset/cs_function.py` | 설계만† |
| processor 9종 | vnpy | `alpha/dataset/processor.py` | 설계만† |
| 검증용 팩터셋 | vnpy | `alpha/dataset/datasets/alpha_{101,158}.py` | 코드 차용 |
| **target→order 변환 전체** | — | — | 순수 창작 |
| **Finding 스키마, override 기록** | — | — | 순수 창작 |
| 섹터 중립화 / beta 제거 / hump | — | — | 순수 창작 |

PRD §8.4 built-in 목록과 대조 시 vnpy가 마지막 3개를 제외하고 전부 커버한다.

† polars를 채택하지 않기로 했으므로(O2) 이 세 항목은 **복사가 아니라 pandas 재작성**이다. 연산 정의와
경계 처리만 참고하고 구현은 pandas로 독립 재작성한다.

### ⑤ ledger

| 항목 | 출처 | 위치 | 차용 방식 |
|---|---|---|---|
| Position 매수/매도/삭제, 초과매도 거부 | qlib | `backtest/position.py` L342/L352/L384 | 코드 차용 |
| settle 2단계 | qlib | L487 / L493 | 코드 차용 |
| 초기 endowment | qlib | L280 `fill_stock_value` | 코드 차용 |
| 제약 없는 position (what-if) | qlib | L503 `InfPosition` | 코드 차용 |
| return/cost/turnover 누적 | qlib | `backtest/account.py` L35 | 코드 차용 |
| bar 종료 mark | qlib | L338 `update_bar_end` | 코드 차용 |
| metric 명시적 활성화 | qlib | L132 | 코드 차용 |
| **trading/holding PnL 분해** | vnpy | `PortfolioDailyResult.calculate_pnl` | 코드 차용 |
| 마진 계좌 / 마진 모델 (perp, 후속) | nautilus | `accounting/accounts/margin.pyx` L54, `margin_models.pyx` L26 | 설계만 |
| **FillSink 좁은 port** | — | — | 순수 창작 |

### ⑥ evidence

| 항목 | 출처 | 위치 | 차용 방식 |
|---|---|---|---|
| save/load/list 표면 | vnpy | `alpha/lab.py` L20-480 | 코드 차용 |
| parquet 물리 layout | nautilus | `persistence/catalog/parquet.py` L105 | 설계만 |
| ↳ metadata 시간범위 인덱싱 | nautilus | L570 | 설계만 |
| ↳ 중복 제거 / 스키마 검증 | nautilus | L820 / L781 | 설계만 |
| 결과 envelope 필드 | nautilus | `backtest/results.py` L20 | 설계만 |
| report 직렬화 패턴 | nautilus | `execution/reports.py` L366, L416 | 설계만 |
| reconciliation report 3분할 | nautilus | 같은 파일 L95/L619/L859, `create_flat` L919 | 설계만 |
| **fingerprint, lineage, atomic publication** | — | — | 순수 창작 |

### ⑦ analysis / 도메인 객체

| 항목 | 출처 | 위치 | 차용 방식 |
|---|---|---|---|
| 통계 plugin 구조 | nautilus | `analysis/statistic.py` L25, `analyzer.py` L38/L59 | 설계만 |
| 성과 지표 계산식 | vnpy | `backtesting.py` L228-380 | 코드 차용 |
| ↳ 파산 시 통계 계산 거부 | vnpy | L280-282 | 코드 차용 |
| 주문 단위 진단 집계 | qlib | `backtest/report.py` L249-650 `Indicator` | 코드 차용 |
| ↳ 체결률 / 가격 유리도 | qlib | L330 / L524 | 코드 차용 |
| PortfolioMetrics 레코드 스키마 | qlib | `report.py` L22, L153 | 코드 차용 |
| 350줄 단일 함수 통계 | vnpy | L228-380 | 반면교사 |
| dataclass 필드 구성 | vnpy | `trader/object.py` L112-200 | 코드 차용 |
| **Status enum** (부분체결/거부/취소/만료) | vnpy | `trader/constant.py` L30 | 코드 차용 |
| amount / deal_amount / factor 분리 | qlib | `backtest/decision.py` L36-152 | 코드 차용 |
| 고정소수점 Price/Qty/Money | nautilus | `model/objects.pyx` | 설계만 |
| 주문 상태 개념 부재 | qlib | `Order` dataclass | 반면교사 |

vnpy 통계는 **계산식은 코드 차용이지만 구조는 반면교사**다. 계산식을 추출해 nautilus의 plugin 껍데기에 개별로
담는다.

### 순수 창작 구역 요약

참고 코드가 없는 영역은 전부 **경계와 증거**다.

```
③ 횡단면 패널 view        instrument × field, 컬럼 저장소 질의   ← 가장 큼
③ 접근 기록 lineage       view 가 조회를 기록
③ requirement resolver   minimal registration → operation-scoped binding
③ 역할별 view 구성        resolved capability만 노출
② callback, FillSink
② finalization            decision/execution/reconcile별 Memory commit timing
④ Strategy/Ensemble      direct/stored/member result composition
④ target→order 변환      전 주문 진단 보존
④ 제약 선언/조정/검증     PRD §10.3
⑤ TradeLedger            평균단가 · 라운드트립 · 실현손익 (§17 G2)
⑤ Memory                 전략 상태 commit boundary (§17 G1)
⑤ long-short 실행 회계    담보 · 수익률 분모 · 차입비용 (§17 G4)
⑥ artifact / failure     typed load, fingerprint, lineage, 원자적 발행
⑥ production reconcile  outbox, OMS result, idempotent confirmed-state commit
  instrument/exchange semantics   계약조건, listing, 비용, lifecycle (§2.6·§16)
```

계산은 대부분 코드 차용/설계만이고 경계는 대부분 순수 창작이다. 이것이 §1 설계 명제의 실증이다. 그러나 progressive
workflow에서는 error/evidence 경계를 뒤로 미루면 앞선 계산 slice가 잘못된 success/failure contract로
굳는다. §15는 최소 resolver, typed evidence와 publication boundary를 foundation으로 먼저 만들고,
borrowed calculation은 그 뒤의 vertical slice에서 추가하도록 정한다.

### 라이선스 실무

```
qlib             MIT        코드 차용 가능
vnpy             MIT        코드 차용 가능
nautilus_trader  LGPL-3.0   설계만 — 코드 복사 금지
```

- 코드 차용 파일 상단에 원출처(파일·함수), 원저작권, 변경 내용을 주석으로 남긴다.
- 저장소 루트에 `NOTICE`를 두고 qlib·vnpy 라이선스 전문을 포함한다.
- 설계만 항목은 개념과 명명만 차용한다. 저작권은 표현(코드)을 보호하고 아이디어(구조)를 보호하지 않는다.
- 코드 주석에 `코드 차용` 또는 `설계만` 분류를 남겨 이후 감사에서 grep으로 추적 가능하게 한다.

---

## 15. 구축 순서

구축 단위는 layer가 아니라 observable vertical use case다. Error와 evidence를 뒤로 미루면 초기
workflow가 failure/lineage contract 없이 굳으므로 foundation에 먼저 둔다.

| # | vertical slice | 주요 architecture | use-case evidence |
|---|---|---|---|
| 1 | Minimal registration + typed evidence | DatasetRegistration, RequirementResolver, OperationError, atomic local catalog | UC-DATA-001/002, UC-ERROR-001, UC-ARTIFACT-002, UC-RESEARCH-001 |
| 2 | PIT direct research | Clock/View, ResolvedBinding, Direct Strategy, signed-weight artifact | UC-PIT-001, UC-SIGNAL-001, UC-CONSTRAINT-001 |
| 3 | Instrument/exact-cost batch | Instrument/Exchange registration, compiler, match_batch, diagnostics | UC-COST-001~004, UC-SCALE-001; §15.1 |
| 4 | Daily closed loop | kernel, decision/execution flow, Ledger/Memory, daily profile, checkpoint | UC-CLOSED-LOOP-001, UC-EXEC-002 |
| 5 | Pluggable execution branch | immutable DecisionIntent, daily/intraday child profiles, isolated Ledger | UC-EXEC-001, UC-ALPHA-CHILD-001 |
| 6 | Stored research + Strategy composition | materialize operation, typed load, Ensemble Strategy, reuse compatibility, Memory update | UC-SIGNAL-002, UC-ALPHA-*, UC-ENSEMBLE-001, UC-ARTIFACT-001 |
| 7 | Portfolio/constraint/monitoring | construction, adjust/validate, account authority, independent monitor | UC-PORTFOLIO-001, UC-CONSTRAINT-002, UC-CONSTRAINT-ADJUST-001, UC-EXEC-003 |
| 8 | Analysis/report/extension | analysis artifact, pure renderer, extension validation | UC-REPORT-001, UC-MONITOR-001, UC-EXTENSION-001 |
| 9 | Production boundary | prepared decision, atomic outbox, OMS result, reconciler | UC-PROD-001/002 |
| 10 | Future design characterization | academic listing, lifecycle event spec, cash-flow attribution | UC-ACADEMIC-001, UC-FUTURE-001, UC-PERP-001, UC-CASHFLOW-001 |

각 slice는 success만 아니라 requirement gap, commit status, artifact/failure evidence와 deterministic retry를
함께 검증한다. 4단계 완료 시 daily long-only closed loop가 동작하고, 5단계가 decision contract와
execution assumption의 독립성을 검증한다. 10단계는 current support publication이 아니라 architecture를
구속하는 characterization fixture다.

3단계부터 instrument축 배열을 기본 단위로 잡는다. 단건 `match`를 먼저 만든 뒤 batch로 확장하는
경로는 택하지 않는다 — clipping 순서 중 현금 제약만이 순차이고 나머지는 elementwise이므로, 처음부터
batch로 두는 편이 단순하다.

### 15.1 체결 산술 parity 검증

`pyqlib`는 dependency가 아니므로 qlib을 in-process oracle로 실행할 수 없다. 3단계의 검증은 **정적
fixture 대조**로 수행한다.

1. `references/qlib`의 `_calc_trade_info_by_order` 경로를 읽어 clipping 단계별 기대값을 손으로
   계산한 fixture를 만든다. 각 fixture는 하나의 clipping 분기를 겨냥한다 — volume 제한, 현금 부족
   매수, 보유 초과 매도, 마지막 매도 lot 생략(L904), 수수료 미달 취소, `trade_val <= 1e-5`.
2. Fixture는 입력(주문·시세·거래량·현금·lot·cost)과 기대 출력(deal_amount, trade_val, cost)을
   명시하며, 근거가 된 qlib 위치를 주석으로 남긴다.
3. qlibx `exchange.match_batch`가 같은 값을 내는지 검증하고, 추가로 반환된 `FillDiagnostic`이 어느
   단계에서 잘렸는지 정확히 지목하는지 확인한다.
4. `UC-COST-001`~`004` fixture로 exact product type, BUY/SELL 비대칭, effective date 경계, 비용을
   포함한 cash clipping, 명시적 0 rule, 금지된 상위 타입 fallback을 검증한다. candidate와 final Fill의
   transaction cost가 동일한 순수 계산기에서 나온다는 것도 확인한다.
5. `UC-SCALE-001` fixture는 scalar reference와 3,000종목 batch 결과가 일치하고, 실행 중 Instrument
   Pydantic 모델을 새로 만들지 않으며, 입력 순서를 고정했을 때 Fill과 진단 순서도 같음을 검증한다.

Fixture는 qlib 실행 결과가 아니라 qlib **코드를 읽고 도출한 기대값**이다. 따라서 qlib 설치가
필요하지 않고, 대신 각 fixture가 어느 코드 경로를 근거로 하는지 추적 가능해야 한다.

---

## 16. 열린 결정

| # | 항목 | 상태 |
|---|---|---|
| ~~O1~~ | ~~`pyqlib` 의존성 위치~~ | **해결.** `pyproject.toml`에서 완전히 제거. runtime/dev 어느 group에도 두지 않는다. 결과로 in-process parity oracle을 쓸 수 없으므로 §15.1 정적 fixture 대조로 대체한다. 차용 대상 qlib 소스는 `references/`에 보존되어야 한다 (O8) |
| ~~O2~~ | ~~polars 도입~~ | **기각.** 우리 접근 축(횡단면 batch)에서 이득이 크지 않다고 판단. 저장 Parquet / 질의 duckdb / 계산·경계 pandas로 간다. 대가로 vnpy signal 연산 이식이 복사가 아니라 재작성이 된다 (§14) |
| ~~O3~~ | ~~matched capitalization 폐기~~ | **해결.** Position direction은 matched-capitalization 우회가 아니라 concrete Instrument semantics와 execution policy가 함께 결정한다. Architecture가 모델과 policy resolution을 소유하며 PRD는 특정 capability 필드를 강제하지 않는다 |
| ~~O9~~ | ~~long-short 수익률 분모~~ | **해결.** dollar-neutral book은 **gross 기준**으로 수익률을 계산한다. Long 100 / short 100이면 분모는 200이다. NAV 기준은 leverage에 따라 수익률이 달라져 alpha 비교가 불가능해지므로 채택하지 않는다. §17 G4의 나머지 항목(담보 모델, 차입 비용, locate)은 여전히 미해결 |
| ~~O4~~ | ~~hypothetical vs real short~~ | **해결.** workflow가 `long_only` / `hypothetical_short` / `real_short` semantics를 명시적으로 resolve한다. 미해결은 `long_only`이며, hypothetical result는 실제 execution profile에서 거부되고 artifact에 표시된다. 이를 Instrument의 단일 고정 필드로 제한하지 않는다 |
| O12 | **패키지명 `qlibx` → `vqar`** | **확정, 실행 보류.** vqar = vibe quant alpha research. PRD 본문 정리(O7)는 완료됐지만 rename은 별도 product/release change로 격리한다. 범위: 배포/import/CLI 이름, `src/qlibx/`, 문서 파일명과 obsidian 링크, `.agent/project.yaml`의 canonical document 경로, `.gitignore`의 `.qlibx/`·`qlibx-research/`, bundled skill entrypoint. 착수 전 PyPI 가용성 확인 필요. `.agent/plans/completed/`는 당시 명칭 기록이므로 소급 변경하지 않는다 |
| O5 | margined contract 확장 | **보류. 설계 characterization 확정.** Complete derivative lifecycle은 현재 범위 밖이다. 공통 `MarginedContract` 아래 만기·최종정산이 있는 `Future`와 만기 필드가 없는 `PerpetualSwap`을 형제 타입으로 둔다. Exchange가 settlement/funding/expiry callback을 등록하고 Ledger가 lifecycle cash flow를 반영한다. `real_short`의 담보·차입 비용은 별도 후속 결정이다 |
| ~~O11~~ | ~~qlib을 runtime backend로 채택~~ | **기각.** decision clock이 데이터 인덱스에 묶여 있어 4개 clock 분리가 불가능하고, 저장 최소 단위에 `available_at`이 없으며, 실험 단위 pickle/MLflow가 portable artifact를 대체하지 못한다. 모델 35개를 싣는 배포 형태도 PRD §5.3·§2.7의 소유 경계와 어긋난다. 상세는 [[why-not-qlib-as-a-backend]] |
| ~~O10~~ | ~~nautilus를 execution backend로 채택~~ | **기각.** 기본 작업 단위가 다르다 — instrument별 event 대 decision-time 횡단면. PRD §8~§10·§12에 대응물 없음. v1→v2 전환 중. 3000종목 미검증. 상세와 재검토 조건은 [[why-not-nautilus-as-a-dependency]] |
| O6 | pub/sub 도입 시점 | **보류. 근거 확정.** 한 event의 수신자가 2개뿐이고 이름을 안다. 중간층은 호출 그래프를 감추고 배달 순서를 따로 설계해야 I7이 유지된다. 도입 조건은 (a) runtime event subscriber extension 개방 (b) 한 event 수신자 증가 (c) 전 event 로깅/replay. 전환 비용이 flow registration에 국한되고 operation/ledger 계약은 불변이므로 미룰 수 있다 |
| ~~O7~~ | ~~PRD 본문 정리~~ | **해결.** `84cd113`이 Qlib-runtime 전제와 fixed global stage/pipeline 서술을 제거하고 progressive workflow contract로 본문을 정리했다. 현 architecture revision이 그 결과를 반영한다 |
| ~~O8~~ | ~~qlib 소스 보존~~ | **해결.** `references/qlib`을 upstream `main@79633dd` 전체 트리(619 paths)로 교체. 기존 부분 스냅샷(274 paths)은 소스를 담고 있지 않았다. §14 인용이 저장소만으로 해결된다 |

O3·O4는 현재 주식 workflow에 필요한 의미를 해결했다. O5는 그 결정을 막지 않는 독립적인 미래 확장이다.

---

## 17. 설계 감사 기록

이 절은 architecture를 구체적 research scenario와 canonical PRD에 대조해 발견한 gap과 불일치를
기록한다. 1차 감사는 2026-08-03의 실행 중심 PRD와 vendored reference를, 2차 감사는 2026-08-05
`84cd113`의 progressive workflow PRD를 대상으로 했다.

기록 목적은 두 가지다. 첫째, 초안이 이미 만족한다고 **잘못 읽힐 수 있는** 부분을 명시적으로
표시한다. 둘째, 해결 순서와 선행 결정을 남긴다. 해결된 항목의 상세는 당시 문제를 설명하는 역사로
보존하되 현행 normative contract는 앞 절이 우선한다.

| # | 항목 | 성격 | 상태 |
|---|---|---|---|
| G1 | Strategy memory 부재 | 불변식 오류 + 계약 누락 | **계약 해결.** proposed state → flow commit, CAS identity와 feedback cursor 확정. 물리 backend는 구현 선택 |
| G2 | Round-trip 회계 부재 | 차용 판단 오류 | 미해결 |
| G3 | 학습/거래 분리 (`FIT` event) | fixed-stage 가정 | **해결.** optional `MATERIALIZE` operation/event + horizon requirement |
| G4 | Long-short 실행 회계 | 설계 방향 확정 | O3·O4 해결. `hypothetical_short`까지 착수 가능. `real_short` 담보·차입·locate는 별도 후속 범위 |
| G5 | `ensemble` 계약 부재 | 명세 누락 | **해결.** Ensemble은 StrategyOperation; typed member result, net/cross/residual 계약 확정 |

### G1 — Strategy memory

초안은 bounded memory를 decision input으로만 언급하고 output·store·commit 경로를 정의하지 않았다.
현행 계약은 StrategyView가 resolved prior memory와 feedback cursor를 읽고 StrategyResult가 proposed
memory를 반환하는 형태다.

```python
Strategy.run(view) -> (StrategyResult(weights, decision, proposed_memory), Diagnostics)
MemoryStore.commit(proposed_memory, expected=prior_memory_id) -> MemoryCommitId
```

`ProposedMemory`는 제안 artifact일 뿐이며 flow가 compare-and-swap identity로 commit한 뒤에만 다음
Strategy의 authority가 된다. Concurrent/stale prior identity는 commit conflict로 실패하고 proposed result는
actual state로 승격되지 않는다. Checkpoint는 committed memory ID와 feedback cursor를 함께 보존한다.

Memory나 actual feedback을 소비한 result는 state identity, account identity와 cursor를 lineage에 기록한다.
다른 state에서 재사용하면 §8 compatibility operation이 warning과 replay/rerun choice를 만든다.

MemoryStore를 독립 low-latency index로 구현할지 artifact stream의 committed head로 구현할지는 물리
backend 결정이다. 어느 구현이든 immutable proposed/committed state artifact, CAS identity와 checkpoint
replay 결과는 같아야 한다.

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
`realized_return`, `is_closed_c`, `calculate_pnl`) 설계 참고 대상이다. LGPL이므로 `설계만`으로 분류한다.

vnpy `PortfolioDailyResult`의 trading/holding PnL 분해는 일별 집계이므로 종목별 라운드트립을
대체하지 못한다.

### G3 — 학습/거래 분리

초안은 Model/FIT을 canonical pipeline의 mandatory stage로 읽었다. 현 PRD는 Direct Strategy와 stored
Model output을 동등한 선택지로 둔다. 따라서 `FIT` global stage를 추가하는 것이 아니라 Model/transform
workflow가 선택될 때만 `MATERIALIZE` operation을 direct invocation 또는 scheduled event로 등록한다.

| trigger | scoped view | operation | result | publication |
|---|---|---|---|---|
| direct/scheduled `MATERIALIZE` | resolved feature/label bindings | Model/transform | typed research data + diagnostics | artifact catalog |

Rolling/expanding/event-triggered fit을 사용하는 concrete component는 자신의 schedule과 requirement를
선언하고, same-time decision이 소비해야 하면 priority를 `DECISION`보다 앞에 둔다. Direct Strategy나
stored-result analysis에는 이 event가 존재하지 않는다.

**라벨의 `available_at` 선언이 이 gap의 핵심이다.** 20일 forward return 라벨로 12/31까지 학습하면
마지막 샘플의 라벨이 1/20까지의 가격을 소비하고, 그 모델이 1/2 decision에 쓰인다. 예외는 발생하지
않는다.

§7 view에서는 이 문제를 별도 hidden cutoff가 아니라 **binding과 requirement로 해결한다.** 라벨의
`available_at`을 `event_time + horizon`으로 등록하면, `MATERIALIZE`가 시각 T에 실행될 때
`available_at > T`인 라벨은 조회되지 않는다. Component가 `horizon_end`를 요구하는데 binding이 없으면
`UC-PIT-001` OperationError로 materialization 전에 실패한다.

따라서 derived label registration은 horizon이 availability와 일치하는지 validation해야 한다. 이를
누락하면 §18이 지적한 "보장이 write 시점으로 이동한 대가"가 정확히 여기서 실현된다.

Fitted state가 있는 component는 이를 typed artifact 또는 versioned binary payload reference로 저장하고,
어느 state를 Strategy가 소비했는지 lineage edge로 기록한다. 최신 파일 경로 alias로 대체하지 않으며
선택되지 않은 candidate와 failed materialization도 audit query에서 조회 가능해야 한다.

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
   계산으로 도출되지 않는 **선언 사항**이며 O9에서 gross로 확정되었다. PRD §11.6이 composite와 active
   return을 구분한다.
4. **차입 비용** — 종목별·시점별로 변한다. 데이터가 없으면 모델링하지 않는다(PRD §5.7).
5. **대차 가능성(locate)** — unknown을 가능으로 추측하지 않는다(PRD §7.7 원칙).

해결 경로는 concrete Instrument semantics와 Exchange/execution policy의 명시적 결합이다. 연구
workflow는 `long_only | hypothetical_short | real_short` 중 하나를 resolve하며, unknown은
`long_only`로 처리한다. `hypothetical_short`는 가상 venue에서만 executable하고 실제 execution
profile에서는 거부하며 결과 artifact에 표시한다. 실제 short는 borrow/locate, collateral, proceeds
encumbrance, borrow fee가 모두 명시되어야 한다. 이 경계는 특정 `capability` 필드 하나를 PRD에서
강제하지 않고 architecture가 모델과 policy resolution으로 구현한다.

### G5 — `ensemble` 계약

초안은 ensemble을 lineage와 package 폴더에만 두고 callable contract를 정의하지 않았다. 현행 §8은
Ensemble을 `StrategyOperation`으로 정의한다. RequirementResolver가 compatible member Strategy result를
typed artifact로 resolve하고 producer를 재실행하지 않는다.

```python
EnsembleStrategy.run(view) -> (StrategyResult, EnsembleDiagnostics)
```

**G4와 독립이다.** Ensemble은 weight space에서 일어나며 ledger를 경유하지 않으므로 long-short
member를 결합하는 것 자체는 실행 회계와 무관하다.

확정된 계약은 다음과 같다.

- **Crossing 기록.** 두 member가 같은 종목에 반대 intent를 내면 ticker-level pre/post-net weight,
  crossing/netting amount와 member contribution을 기록한다. 이 단계의 crossing은 Exchange Fill이 아니므로
  transaction cost를 발생시키지 않는다.
- **Netting 후 normalization.** 네팅으로 줄어든 gross를 목표치로 되돌릴지는 fixed/flexible budget
  선언에 따른다. 말없이 재정규화하지 않고 gross/net residual을 evidence로 남긴다.
- **Path-dependency compatibility.** Member가 state-dependent면 state/account/cursor identity를 보존한다.
  다른 history에서 사용할 때 무조건 금지하지 않고 compatibility warning 뒤 historical replay 또는
  rerun choice를 기록한다.

### 현재 남은 감사 action

```
G1 · G3 · G5   → architecture contract 해결. §15 해당 vertical slice에서 fixture로 검증
G2             → round-trip/PnL-dependent Strategy를 지원하는 Ledger slice에 TradeLedger 추가
G4             → hypothetical은 O3·O4 의미로 진행 가능. real short는 담보·차입·locate 결정 필요
```

G2는 구현 미완이지만 product 의미를 바꿀 선행 결정은 없다. G4의 hypothetical 범위도 진행 가능하며,
real-short accounting과 complete derivative lifecycle만 후속 product decision을 기다린다.

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

**남는 순수 창작 영역.** 시간 경계 메커니즘은 nautilus에서 차용하지만 **접근 축**은 여전히 창작이다. Reference
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

### 2026-08-04 — instrument capability 도입, 부수 결정 넷

**instrument (O3·O4 해결).** PRD에 §7.12 instrument capability declaration을 신설하고 §11.4~11.7의
matched capitalization을 대체했다. Position이 음수를 가질 수 있는지는 engine의 고정 속성이 아니라
instrument가 선언하는 값이며, `long_only` / `hypothetical_short` / `real_short` 세 값을 갖는다.
미선언은 `long_only`로 취급하고 unknown을 shortable로 추측하지 않는다. §17 G4가 `hypothetical_short`
범위까지 착수 가능해졌다.

matched capitalization은 qlib의 long-only Position 제약을 우회하기 위한 장치였다. Engine 소유권이
넘어오면서 전제가 사라졌고, 우회로 대신 선언을 요구하는 형태로 교체했다. PRD §4.2, §5.1, §5.7,
§11.4, §11.6, §12.3, §15 P8, §16.2, §17.2가 함께 갱신되었다.

**perp·담보 보류 (O5).** 현재 범위 밖이다. 도입 시 §7.12의 선언 항목을 늘리는 형태여야 하며 engine
구조 변경을 요구해서는 안 된다는 제약만 남긴다.

**polars 기각 (O2).** 횡단면 batch 접근에서 이득이 크지 않다고 판단했다. 저장 Parquet / 질의 duckdb /
계산·경계 pandas로 간다. 대가는 vnpy signal 연산 30여 개가 복사가 아니라 pandas 재작성이 된다는 것이며
§14에 †로 표시했다.

**FillConvention 분리.** Executor가 정하는 것은 일정이고 체결가 규약은 별도 축이다. 둘을 묶으면 종가
체결을 시가 체결로 바꾸는 데 executor를 새로 써야 한다. `CloseFill`을 기본으로 두되 **낙관적 가정임을
명시**하고, 사용된 convention identity를 result에 기록한다. Convention 교체는 alpha부터 ledger까지 어느
계약에도 영향을 주지 않는다.

**pub/sub 보류 근거 확정 (O6).** 한 event의 수신자가 둘뿐이고 이름을 안다. 전환 비용이 발행 지점 1곳
교체에 그치고 judge·ledger 계약이 불변이므로 미룰 수 있다. 반대로 `available_at`, clock 분리,
`(결과, 진단)` 반환, 시간 축 순차는 나중에 추가하면 정보를 잃으므로 미루지 않았다. 판단 기준은
**"나중에 추가하면 정보를 잃는가"** 이다.

### 2026-08-04 — PRD use-case traceability와 Instrument/Exchange 책임 정정

**PRD 경계 정정.** PRD는 instrument capability dictionary, cost schedule 선언 형식이나 class hierarchy를
강제하지 않는다. 대신 상품·side·유효일 비용, 비용을 포함한 cash clipping, exact-rule failure,
closed-loop feedback과 3,000종목 batch를 stable use-case ID로 정의한다. Academic instrument와 margined
contract 사례는 현재 acceptance가 아니라 미래 design characterization으로 구분한다.

**책임 배치.** Instrument는 구체 Pydantic 타입으로 정적 경제 계약을 표현한다. Exchange는 listing,
tradability, transaction-cost policy와 lifecycle event specification을 소유한다. Clock이 event를 순서대로
발행하고 Flow가 Fill 또는 lifecycle cash flow를 Ledger에 commit한다. 다음 decision은 이 commit 이후의
actual position, cash와 NAV를 읽는다.

**비용 계약.** 거래비용 계산 entrypoint는 Exchange에 붙인다. Product type, side, explicit event time과
effective-dated schedule로 exact rule을 선택하고, ETF rule 부재를 Equity rule로 fallback하지 않는다.
Candidate cash clipping과 최종 Fill이 같은 순수 계산기를 사용한다. 공개 `CostContext`와 필수
`CostBreakdown`은 도입하지 않고 total cost, rule ID와 schedule version만 최소 evidence로 보존한다.

**상품 계층.** `Future`와 `PerpetualSwap`은 `MarginedContract` 아래의 형제 타입이다. Future만 expiry와
final settlement를 가지며, PerpetualSwap에는 expiry field 자체가 없다. Funding과 variation margin은
transaction cost가 아니라 lifecycle cash flow다.

**성능과 결정론.** Pydantic은 등록 경계에서만 검증하고 build 단계가 stable instrument index와 배열을
compile한다. Hot fill loop에서 Instrument 모델을 다시 만들지 않는다. 모든 Exchange 계산은 wall clock이
아닌 event time을 명시적으로 받아 같은 config와 data에서 같은 event 순서와 결과를 낸다.

이 항목은 바로 앞의 `instrument capability` 개정 기록을 역사로 보존하되, 현재 설계에서는 그 기록의
"단일 선언 필드가 책임을 소유한다"는 방향을 대체한다.

### 2026-08-05 — Progressive workflow와 pluggable execution revision

**계기.** PRD `84cd113`이 fixed global stage와 mandatory end-to-end pipeline을 제거하고 minimal
registration, operation-time requirement discovery, Direct Strategy, stored Model output, Ensemble Strategy,
pluggable executor, typed failure evidence와 production reconciliation을 observable use case로 확정했다.

**Orchestration.** 여섯 responsibility layer와 callback/IoC는 유지한다. 반복 원자는
`freeze → resolve requirements → scoped view → typed calculation → commit/publication → evidence`로
확장하고, `alpha → construct → convert → validate`를 모든 run의 고정 chain으로 사용하지 않는다.

**Data와 error.** 최초 registration은 logical key, instrument/time/availability와 payload facts만 요구한다.
각 operation이 `ComponentRequirement`를 선언하고 `RequirementResolver`가 binding을 해결한다. Gap은
hierarchical `OperationError`와 failure artifact로 남으며 unrelated registration이나 workflow를 무효화하지
않는다. Agent가 resolution candidate를 설명하고 package가 user-confirmed 결과를 validation한다.

**Strategy와 execution.** Strategy는 internal signal과 signed weights를 함께 만들거나 typed Model result를
소비할 수 있다. Ensemble은 StrategyOperation이다. Decision callback은 immutable intent와 execution event를
예약할 뿐 fill을 만들지 않으며, daily/intraday profile은 같은 decision contract 뒤에서 다른 actual result를
commit한다. 2026-08-03의 "MinuteExecutor 제외" 판단은 현 PRD의 `UC-EXEC-001`에 의해 supersede되었다.
특정 `MinuteExecutor` 이름은 요구하지 않지만 intraday/partial-fill characterization profile은 validation
범위에 포함한다.

**Evidence와 production.** Artifact load는 typed object construction을 수행하고 publication은 payload,
envelope와 lineage를 atomic하게 노출한다. Failure/retry, analysis/report와 extension validation을 같은
boundary에 둔다. Production은 PreparedDecision outbox publication과 OMS acknowledgement를 authority로
보지 않고 confirmed result reconciliation 뒤의 state만 commit한다.

**Traceability와 build.** §1.1과 §13이 PRD의 stable use case 37개를 모두 추적한다. 구축 순서는 layer
완성 순서에서 use-case vertical slice로 바뀌며 error/evidence가 foundation으로 이동한다. O7, G1, G3와
G5의 architecture gap을 해결했고 G2 round-trip 회계와 G4 real-short accounting은 남겨 둔다.
