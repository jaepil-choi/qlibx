# qlibx Architecture

Status: current implementation baseline + explicit target/future gaps (audited 2026-08-07)
Canonical requirements: `docs/qlibx-prd.md`
Current package/import/CLI name: `qlibx`
Final rename target: `vqapr` (확정, 마지막 migration 단계까지 실행 보류)
Borrow research: [[engine-borrow-benchmark-map]]
Backend 채택 판단: [[why-not-qlib-as-a-backend]], [[why-not-nautilus-as-a-dependency]]

이 문서는 PRD가 규정한 product requirement를 만족하는 **구현 설계**를 기술한다. PRD가 정본이고 이
문서는 그것을 만족하는 하나의 구조다. 둘이 충돌하면 PRD가 우선한다.

이 문서가 정하는 것: layer 경계, 책임 배분, 불변식, 핵심 계약의 shape, 의존 방향, 차용 출처.
이 문서가 정하지 않는 것: 최종 public name, 함수 시그니처의 세부, 파일 분할 단위.

> **§16 설계 감사 기록을 함께 읽을 것.** 이 문서는 초기 고정 pipeline 초안에서 출발했다. 2026-08-05
> PRD가 독립 workflow와 progressive requirement discovery를 정본 계약으로 확정하면서 orchestration,
> error, evidence와 production boundary를 다시 감사했다. 현행 본문은 그 revision을 반영하고, §16은
> 아직 남은 구현 결정과 폐기된 가정을 구분해 기록한다.

---

### Current implementation alignment (2026-08-07)

이 표에서 **current**는 실제 public symbol 또는 실행 가능한 회귀 테스트가 있는 상태만 뜻한다. Target과
future pseudocode는 구현된 API가 아니다.

| 경계 | actual implementation | architecture 대안 | 판단과 trade-off | 전환 조건 |
|---|---|---|---|---|
| Strategy 결과 권한 | **current:** `StrategyOperation.run()`은 `StrategyDraft`를 반환하고 Flow가 실제 data/artifact/state access를 붙여 `StrategyResult`를 생성·발행한다. DTO 승격 단계가 추가되는 단점이 있다 | Strategy가 `StrategyResult`를 직접 반환하면 API는 짧지만 Strategy가 관측할 수 없는 lineage를 스스로 작성하게 된다 | **actual 채택.** evidence authority와 계산 책임을 분리하는 편이 clean architecture에 가깝다 | 없음. Flow-owned 승격을 normative contract로 유지한다 |
| composition root | **current:** `QlibxProject`가 공개 facade이며 operation별로 필요한 concrete flow와 backend를 조립한다. 조립 코드가 일부 반복된다 | 장수명 `Engine`은 DI와 backend 교체가 쉽지만 현재 수요에는 global graph와 lifecycle 관리가 과도하다 | **actual 채택.** YAGNI와 operation 경계를 우선한다 | 둘 이상의 runtime backend가 공통 lifecycle을 실제로 공유할 때 container/Engine을 재검토한다 |
| role View | **current:** dataset-only base, Strategy 전용 artifact/account/feedback/performance/memory, Monitor 전용 account capability로 최소 권한을 강제한다 | 기능이 큰 단일 View를 상속하면 재사용은 쉽지만 Interface Segregation과 least-authority를 위반한다 | **architecture 채택 후 코드 동기화 완료.** 작은 내부 base의 중복보다 권한 누출 비용이 크다 | 새 operation은 실제 read set을 증명한 capability만 받는다 |
| observation source | **current:** registered CSV/Parquet source를 pandas로 읽고 projection한 뒤 메모리에서 PIT/filter를 적용하며 source fingerprint를 검증한다. 단순하고 user source를 그대로 쓰지만 반복 full scan과 scale 한계가 있다 | partitioned Parquet + DuckDB predicate pushdown은 대규모 PIT query에 유리하지만 ingestion, invalidation과 migration cost가 생긴다 | **현재 actual 명시.** columnar store는 target이지 current가 아니다 | 대표 workload benchmark에서 scan cost가 budget을 넘고 ingestion/fingerprint contract가 정의될 때 전환한다 |
| artifact payload | **current:** typed `QlibxModel` payload는 JSON이고 DuckDB는 catalog/index다. 단순하고 inspectable하지만 큰 matrix에는 비효율적이다 | Parquet payload backend는 tabular artifact에 효율적이지만 schema split과 backend complexity가 증가한다 | **현재 actual 채택.** Parquet payload는 future backend다 | 대형 matrix benchmark와 JSON/Parquet 간 atomic publication·compatibility 계약이 준비될 때 추가한다 |
| generic ports | **current:** concrete flow/API 중심이며 공용 failure helper만 실제 중복에 맞춰 추출했다. abstraction 수는 적지만 backend 대체성은 낮다 | 범용 `Operation`/`ArtifactPublisher`/`ArtifactLoader` protocol은 DIP에 유리하나 단일 구현에서는 speculative하다 | **actual 채택.** 아래 protocol 코드는 conceptual target으로만 읽는다 | 독립적인 두 번째 구현 또는 test double이 같은 계약을 소비할 때 protocol을 추출한다 |
| execution convention | **current:** `NextSessionCloseExecutor`가 schedule을 만들고 `DailyExecutionFlow`가 profile의 execution-price role로 size/match한다. 검증된 경로는 좁다 | 별도 `FillConvention`과 next-open 구현은 schedule/price 역할을 더 깨끗이 분리하지만 real next-open data와 calendar 계약이 없다 | **현재 next-close만 지원.** next-open은 readiness gap이다 | 같은 frozen parent decision을 Strategy rerun 없이 real PIT next-close/next-open으로 비교하는 acceptance가 필요하다 |
| materialization | **current:** generic requirement resolver만 있고 public `MaterializeOperation`과 forward-label Model materialization 증거는 없다 | optional materialization boundary는 PIT 학습/거래 분리에 타당하지만 현재 구현된 것처럼 쓰면 과장이다 | **target 유지, current support에서 제외.** resolver test는 기반 회귀일 뿐 closure evidence가 아니다 | 실제 optional operation과 label-horizon preflight failure/no-mutation acceptance가 필요하다 |
| daily orchestration | **current:** 큰 `DailyExecutionFlow`가 recovery와 event ordering을 한곳에서 보존한다. 이해·변경 비용이 크다 | cohesive state machine/phase extraction은 유지보수에 유리하지만 기계적 파일 분리는 control flow를 숨긴다 | **이번에는 actual 유지.** 기술 부채를 인정한다 | 둘 이상의 phase가 독립 테스트·재사용 경계를 갖거나 변경 충돌이 반복될 때 state machine을 추출한다 |

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
| `UC-DATA-001` | dataset registration | source sample + user binding | minimal key/instrument/availability validation | registration | binding + schema fingerprint | arbitrary-field fixture |
| `UC-DATA-002` | Strategy invocation | requirements + registered bindings | requirement resolution | 없음 on gap | `OperationError` + requirement ID | add-binding retry |
| `UC-ERROR-001` | short analysis invocation | actual operation path only | requirement check | failure evidence only | hierarchical stage path | no phantom-stage fixture |
| `UC-PIT-001` | **readiness gap:** future model materialization | target label availability at evaluation time | target horizon preflight | 없음 on gap | missing `horizon_end` | real MaterializeOperation + forward-label no-mutation acceptance required |
| `UC-AGENT-001` | ambiguous registration failure | package error + skill + project semantics | agent proposes; package validates | confirmed binding only | user decision + rule ID | no guessed availability |
| `UC-SIGNAL-001` | direct Strategy run | scoped PIT data + bounded state | signal/weight inside Strategy | results + proposed memory | signed weights + accesses | no mandatory signal stage |
| `UC-SIGNAL-002` | stored-result Strategy run | compatible typed model result | signed-weight assembly | Strategy result | producer-independent edges | producer not rerun |
| `UC-ALPHA-BUDGET-001` | flexible-budget Strategy | signed inputs + budget declaration | allocation without forced rescale | alpha-weight result | invested/residual budget | fixed incompatibility |
| `UC-ALPHA-PATH-001` | later Strategy/Ensemble composition | frozen typed result + source state/cursor lineage | consumer compatibility + composition | new Strategy result | consumed artifact + all source state/cursor edges | producer not rerun; no current-state recomputation claim |
| `UC-ALPHA-CHILD-001` | **readiness gap:** next-close/next-open child branch | frozen parent weights + two real PIT conventions | alternate execution only, no Strategy rerun | isolated child Account/artifacts | parent edge + convention | same parent, parent unchanged, both conventions proven |
| `UC-ALPHA-ADAPTIVE-001` | feedback-triggered Strategy | committed feedback + prior memory | proposed belief/member update | Memory at flow boundary | before/after + cursor | no future feedback |
| `UC-ENSEMBLE-001` | Ensemble Strategy run | compatible member results | combine/net/cross by ticker | ensemble result | contribution + residual | producers not rerun |
| `UC-PORTFOLIO-001` | construction profile selection | same weights + selected profile | profile-specific construction | separate portfolio results | budget/direction/cost lineage | alpha unchanged |
| `UC-CONSTRAINT-001` | constraint-free analysis | signal/weight artifact only | requested analysis | analysis result | actual dependencies | no compliance binding |
| `UC-CONSTRAINT-002` | constrained conversion | no-short + PIT benchmark weight | requirement resolution | 없음 on gap | missing benchmark weight | no order/account mutation |
| `UC-CONSTRAINT-ADJUST-001` | adjust then validate | intent + actual state + constraint data | adjust; independent validate | eligible candidate only | before/after + residual + finding | residual is not compliance |
| `UC-COST-001` | execution event | exact product/side policy + quote | §13.2 cost rule | Fill | total cost + rule ID | product/side fixture |
| `UC-COST-002` | execution event | policy valid at event time | §13.2 schedule resolution | Fill | version + effective time | date-boundary fixture |
| `UC-COST-003` | cash-limited BUY | actual cash + exact policy | §13.3 shared cost calculator | Fill | requested/dealt + clip reason | cash-limit fixture |
| `UC-COST-004` | no exact rule | exact selector; no parent fallback | unsupported failure | 없음 | failure artifact | no Fill/Account mutation |
| `UC-CLOSED-LOOP-001` | next decision after commit | committed simulation Account | Strategy evaluation | next result | feedback cursor + snapshot | requested state excluded |
| `UC-SCALE-001` | 3,000-name execution | compiled arrays + scoped market data | vectorized match | Fill batch | stable per-name diagnostics | batch/scalar parity |
| `UC-LOOKTHROUGH-001` | user Strategy callback | user-declared constituent binding + actual AccountSnapshot | user code가 선택한 `L @ p` 또는 다른 exposure 계산 | user Strategy result only | actually consumed binding/account edges | same ETF: unsubscribed Strategy는 opaque |
| `UC-LOOKTHROUGH-002` | StrategyView data read | declared observations with `available_at <= evaluation time` | ViewGate visibility; semantic selection은 user code | 없음 unless user emits result | observation/cutoff access lineage | future row hidden; no auto latest/mapping |
| `UC-LOOKTHROUGH-003` | next user Strategy callback | marked committed AccountSnapshot + declared constituent binding | user code가 actual quantity로 재계산 | user artifact/intent if returned | target/fill/held input distinction | requested target excluded; no auto feedback |
| `UC-EXEC-001` | MVP execution | decision + PIT execution view | full-fill convention | committed Account | decision ID + FillBatch | Strategy does not fill directly |
| `UC-EXEC-002` | daily-close execution | observations available by fill time | timing/PIT validation then match | Fill or failure | convention + limitation | no future close |
| `UC-EXEC-003` | explicit `monitor_constraints(spec)` call at caller-selected cadence | committed checkpoint + frozen evaluation time + compliance view | constraint evaluation | finding artifact only | breach/missing classification | no decision/order; not auto-injected into daily flow |
| `UC-ARTIFACT-001` | external artifact load | documented payload + envelope | typed construction + compatibility | imported artifact | external producer lineage | no producer import |
| `UC-ARTIFACT-002` | load/publication | complete candidate payload | schema + semantic validation | 없음 on invalid | bounded failure evidence | invalid not reusable |
| `UC-RESEARCH-001` | failed operation then retry | frozen failure inputs + new binding | new resolution | failure then success artifacts | resolution lineage | failure retained |
| `UC-REPORT-001` | renderer selection | stored analysis values | presentation only | report artifact | source analysis IDs | renderer value parity |
| `UC-MONITOR-001` | monitoring report | actual-account findings | analysis/rendering | report artifact | actual/intended distinction | breach vs missing |
| `UC-EXTENSION-001` | transform extension registration | contract + validation fixture | package compatibility validation | registration on success | validation + producer ID | failure not registered |
| `UC-EXTENSION-002` | exact local Strategy registration | path-confined source + fixed symbols + frozen fixture | two fresh instances; hash/schema/access comparison | registration, then exact-ID Strategy result | source/schema hash + actual artifact/registration edges | drift or implicit selection fails before compute |
| `UC-PROD-001` | future OMS partial result | decision + confirmed fills/account | future reconciliation | confirmed delta only | pending/cancel + correlation | not MVP acceptance |
| `UC-PROD-002` | future OMS rejection | decision + rejection | future reconcile without intended apply | rejection evidence only | retry policy identity | not MVP acceptance |
| `UC-ACADEMIC-001` | future academic listing | explicit hypothetical profile | §13.6 match | hypothetical Fill | profile identity | disallowed profile rejects |
| `UC-FUTURE-001` | future settlement/expiry | observable settlement input | variation/final settlement | cash/position delta | lifecycle evidence | post-expiry reject |
| `UC-PERP-001` | future funding timer | observable funding rate | funding cash flow | cash delta | funding evidence | no expiry event |
| `UC-CASHFLOW-001` | future lifecycle event | event-specific inputs | separate fee/lifecycle calculation | Account | category + source | attribution separation |
| `UC-SETTLEMENT-001` | future stock/ETF settlement | Fill + settlement calendar | receivable/payable transition | Account | settlement assumption/source | MVP remains instant |

`UC-PIT-001`과 `UC-ALPHA-CHILD-001`은 product requirement이지만 2026-08-07 current-support registry에서는
각각 real Model materialization과 real next-close/next-open 비교 증거가 없어 readiness gap으로 분류한다.
Generic requirement rejection과 frozen child isolation 테스트는 기반 회귀로 유지하되 두 use case의 closure로
사용하지 않는다. `UC-PROD-*`, `UC-ACADEMIC-001`, `UC-FUTURE-001`, `UC-PERP-001`, `UC-CASHFLOW-001`과
`UC-SETTLEMENT-001`도 current acceptance가 아니다. 현재 구조가 해당 flow를 막지 않는지 설명하는 설계
characterization이며 구현 완료를 주장하지 않는다. Test와 fixture를 만들 때도 같은 use-case ID를 사용해
PRD → architecture → validation의 연결을 유지한다. CI는 두 문서의 stable ID 집합을 비교해 누락을
실패시켜야 한다.

---

## 2. 멘탈 모델

### 2.1 주식 Strategy와 선물 position을 함께 따라간다

예를 들어 매 거래일 장 마감 뒤 signal을 계산하지만, 월말에만 주문을 결정하고 다음 거래일 종가에
체결하는 Strategy를 생각한다. 이 Strategy는 주식만 거래하지만 Account에는 이전에 만들어진
KOSPI200 선물 Long 1계약도 남아 있다.

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
          └── 다음 decision feedback ─ Account / Memory

각 단계의 input, assumption, result와 failure ──→ Evidence
```

Model/materialization을 선택한 한 workflow의 실행 순서는 다음과 같다. Direct Strategy workflow에는
첫 `MATERIALIZE` callback이 없다.

```text
매 거래일 장 마감      MATERIALIZE callback → 그날까지 available한 data로 signal 저장 (optional)
월말 마지막 거래일     DECISION callback    → signal과 AccountSnapshot으로 주식 intent 확정
다음 거래일 종가       EXECUTION callback   → 미리 확정된 intent를 선택한 가정으로 결과화
선물 정산 시각          SETTLEMENT callback  → variation margin을 Account에 commit
다음 decision          StrategyView          → 둘 다 반영된 AccountSnapshot과 prior Memory를 읽음
```

선물 정산가격이 2포인트 오르고 계약승수가 250,000원이면 Long 1계약의 variation margin은
$2 \times 250{,}000 = 500{,}000$원이다. Strategy가 선물 주문을 만들 수 없더라도 이 현금 변화와 NAV는
Account에 반영된다. 다음 주식 decision은 변경된 현금과 전체 exposure를 본다.

이 선물 부분은 Account 경계를 설명하는 **future-extension characterization**이다. Current stock/ETF
profile은 Future position을 지원한다고 주장하지 않으며 exact lifecycle policy가 없는 Future 초기화는 실패한다.

여기서 월말은 달력의 마지막 날이 아니라 **마지막 거래 session**이다. 다음 거래일 종가는 Strategy input이
아니다. 월말에 freeze된 DecisionIntent를 결과화하는 execution input이다. Executor가 다음날 가격·현금으로
수량이나 Fill을 계산할 수 있지만 그 가격으로 Strategy intent를 다시 계산하지 않으면 Strategy look-ahead가 아니다.

### 2.2 일곱 질문을 섞지 않는다

| 질문 | 책임 | 예 |
|---|---|---|
| 어떤 data가 존재하는가 | Registry | daily/monthly OHLCV, close-close return, stored signal |
| 지금 무엇을 볼 수 있는가 | Clock + View | `available_at <= evaluation_time`, resolved requirement |
| 무엇을 보유하고 싶은가 | Strategy | signed weight, target, `DecisionIntent` |
| 언제·어떻게 결과화하는가 | ExecutionProfile | next close/open, cost, liquidity, hypothetical convention |
| 실제로 무엇을 갖고 있는가 | Account | Fill, Position, cash, mark, NAV, committed feedback |
| Strategy가 무엇을 기억하는가 | Memory | prior belief, cooldown, feedback cursor |
| 무엇을 근거로 계산했는가 | Evidence | data identity, lineage, assumption, limitation, failure |

**Strategy look-ahead는 View 경계가 결정하고 execution realism은 ExecutionProfile이 결정한다.** Daily 또는
monthly bar를 쓰거나 단순 종가 체결을 선택했다는 사실만으로 Strategy look-ahead가 발생하지 않는다. 반대로
정교한 intraday executor를 써도 View가 미래 observation을 보여주면 look-ahead다.

Current MVP는 immutable DecisionIntent를 **next-session close**에서 처리하는 경로만 검증했다. Next-open은 같은
Strategy result를 재실행하지 않고 alternate execution result와 actual state만 만드는 target이지만, real open
observation과 schedule 계약이 없어 `GAP-EXECUTION-CONVENTION-001`로 남는다. Intraday partial-fill은 future
characterization이다. Signal이나 weight만 분석하는 research는 ExecutionProfile과 Account mutation 없이
Evidence publication에서 정상 종료할 수 있다.

### 2.3 Clock, callback과 View — IoC

Callback의 business logic은 Flow가 소유하고 Clock은 event 시각, priority와 callback reference를 queue에서
관리한다. Runtime loop가 Clock이 반환한 handler를 순서대로 호출한다.

```text
QlibxProject가 조립한 Flow가 callback 등록
          ↓
Clock이 다음 event 시점으로 이동
          ↓
Handler(Event, callback)를 priority 순서로 반환
          ↓
Runtime loop가 Flow callback 호출
          ↓
Flow가 scoped View를 만들고 Operation 실행
```

이것은 **Inversion of Control(IoC)** 이다. Strategy가 시간을 진행하거나 callback을 직접 부르지 않고
Runtime이 event 순서에 따라 Strategy를 호출한다. 따라서 Strategy 밖에서 동일시각 priority와 PIT cutoff를
한 번만 통제할 수 있다.

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

Operation은 시간을 스스로 읽거나 store에 직접 접근하지 않고 Account, Memory 또는 Evidence를 직접 쓰지
않는다. Flow가 typed result와 diagnostics를 받은 뒤 허용된 commit/publication port를 호출한다.

### 2.4 세 authority, 두 mutable state store와 여섯 layer

Runtime truth에는 세 authority가 있지만 mutable state store는 둘뿐이다.

```text
Clock     지금 몇 시인가                 — event 순서와 조회 cutoff의 시간 authority
Account   실제로 무엇을 갖고 있는가      — Position, cash, mark, NAV의 actual-state authority
Memory    Strategy가 무엇을 기억하는가   — commit된 strategy state의 authority

mutable state store = Account + Memory
```

PRD의 `ledger`는 "실제 결과를 authoritative state에 commit한다"는 **역할명**이다. Architecture의 concrete
state object는 `Account`이며 별도 `Ledger` 객체를 만들지 않는다. Catalog와 Artifact는 authority를 대신하지
않는 append-only Evidence다. 영수증이 계좌 잔액 자체가 아닌 것과 같다.

Strategy는 Account나 Memory를 직접 변경하지 않고 StrategyView로 commit된 state를 읽으며 proposed Memory를
result로 반환한다. Flow가 workflow finalization에 맞춰 이를 commit한다.

| layer | 답하는 질문 | 주요 책임 |
|---|---|---|
| ① kernel | 언제 실행하는가 | Clock, Event, Queue, deterministic priority |
| ② flow | 어떤 순서로 실행하고 무엇을 확정하는가 | callback, direct invocation, Executor sub-flow, commit/publication |
| ③ view | 무엇을 볼 수 있는가 | clock-bound facade, PIT와 role boundary, access lineage |
| ④ operation | 무엇을 계산하는가 | Strategy, Model, construct, analyze, validate, exchange.match |
| ⑤ state | 실제 state는 무엇인가 | Account와 Memory |
| ⑥ evidence | 무엇을 근거로 재현하는가 | Artifact, Catalog, Lineage, diagnostics |

부수효과를 시작할 수 있는 곳은 **② flow뿐**이다. ③④는 순수하고, ⑤⑥은 Flow가 좁은 port로만
변경한다. Flow는 Clock callback뿐 아니라 dataset registration, analysis, report 같은 direct API/CLI
invocation도 orchestration한다. 모든 run이 `Strategy → construct → convert → validate → execute`를 통과하지
않으며, `on_decision`이 길어지면 계산이 Flow로 흘러들어온 신호다.

Account에서 View를 거쳐 다음 decision으로 돌아오는 edge가 PRD §2.4 closed loop다. 다음 decision은 requested
target이 아니라 **commit된 실제 상태**를 읽는다.

### 2.5 Data granularity는 research capability다

Dataset registration은 data를 특정 executor에 맞춰 왜곡하지 않고 실제 의미를 기록한다.

| 보유 data | 가능한 research | 조용히 주장하면 안 되는 것 |
|---|---|---|
| daily OHLCV | daily 또는 더 낮은 빈도의 signal, next-bar convention, daily mark | intraday path, order-book liquidity |
| monthly OHLCV | monthly signal·rebalance·return | daily drawdown, daily tradability, 월중 체결 path |
| close-close return | IC, factor/portfolio return, attribution, hypothetical NAV | observed quote, share quantity, market volume |

최초 logical dataset registration의 최소 계약은 instrument axis, `available_at`과 logical row key다. Event time,
effective date, semantic category와 source provenance는 알려져 있으면 보존할 수 있지만 전역 필수 field가 아니다.
Return의 period start/end, gross/net/excess, currency와 compounding convention도 이를 사용하는 Operation이 점진적으로
요구한다. OHLCV, lot, volume와 tradability 역시 단순 return research를 막는 전역 필드가 아니다.

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
| Clock / flow | 언제 계산하고 commit하는가 | DECISION, EXECUTION, MARK, MONITOR; future SETTLEMENT/FUNDING/EXPIRY |
| Account | 실제 또는 명시적 hypothetical state가 어떻게 바뀌었는가 | Fill, cash flow, position delta, mark, NAV |

Instrument는 immutable contract와 static semantics를 제공한다. Exchange는 listing과
venue/profile/effective-time policy를 적용한다. 시변 가격, return, funding rate와 valuation input은
clock-bound View에서 읽는다. 같은 Index도 일반 profile에서는 tracking-only이고 명시적 academic profile에
등록되면 hypothetical execution 대상이 될 수 있다.

서로 다른 네 집합을 같은 universe로 부르지 않는다.

| 집합 | 의미 | 예 |
|---|---|---|
| registered instruments | project config와 Instrument registry가 stable ID와 계약조건을 아는 전체 상품 | 삼성전자, SK하이닉스, KOSPI200 Future |
| held instruments | Account가 0이 아닌 Position을 가진 상품 | 삼성전자 100주, Future Long 1계약 |
| Strategy tradable universe | 이 Strategy가 주문할 수 있는 상품 | 삼성전자와 SK하이닉스만 |
| valuation set | Account가 현재 평가해야 하는 상품 | 모든 held instrument |

`held instruments ⊆ registered instruments`는 불변식이다. Position map은 실제 보유 상품만 담는 sparse map이며
등록 Instrument마다 0 position을 만들지 않는다. Strategy tradable universe에서 빠진 상품도 이미 보유 중이면
Account에서 사라지지 않는다. **거래 가능 범위는 주문을 제한하고 valuation set은 실제 보유를 따른다.**

향후 derivative capability를 추가할 때 Strategy tradable universe 밖의 held Future도 valuation set에 남고 exact
settlement policy가 선택된 경우에만 variation margin을 cash에 반영해야 한다. 이는 current behavior가 아니다.
필요한 가격이나 lifecycle input이 없으면 이전 값을 정상값처럼 사용하지 않고 `INCOMPLETE` 또는 `STALE` diagnostic을
남기는 확장 경계만 보존한다.

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
cost와 liquidity assumption이 있을 때 Factor를 hypothetical listing으로 받아 기존 quantity/Fill/Account 경로를
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

Future position을 담을 수 있는 Account 계약과 Future가 **current support**라는 주장은 다르다. Current
vertical slice는 stock/ETF Fill과 mark를 구현한다. Future multiplier, variation margin, expiry를 다루는
`LifecycleBatch`는 PRD `UC-FUTURE-001`을 위한 future-extension characterization이며 exact settlement policy가
등록되기 전에는 Future position 초기화나 commit을 unsupported로 실패시킨다.

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

Requirement resolution이 실패하면 ④를 호출하지 않고, Account/Memory mutation이나 success artifact publication
없이 hierarchical `OperationError`와 failure evidence를 남긴다. 사용하지 않는 optional operation은 stage
path에 나타나지 않는다.

Event-driven runtime에서 위 원자는 다음처럼 구체화된다.

| event | clock 위치 | scoped view | 선택 가능한 계산 | 결과 | authoritative commit |
|---|---|---|---|---|---|
| `DECISION` | decision time | `StrategyView` | selected Strategy; optional construct/adjust/convert/validate | weights and/or decision intent + diagnostics | proposed Memory만 flow가 commit; execution은 예약 |
| `EXECUTION` | 체결 시점 | `ExecutionView` | exchange.match_batch | fills + diagnostics | `Account.commit(FillBatch)` |
| `MARK` | 15:30 | `ExecutionView` | valuation | marks + NAV | `Account.commit(MarkBatch)` |
| `MONITOR` | session close | committed mark/execution + Account snapshot | session performance와 account observation | monitor evidence | **건드리지 않음** |
| `MATERIALIZE`† | model/transform cadence | requirement-scoped data view | model/transform | typed research data | artifact publication |
| `SETTLEMENT`* | 정산 시점 | `ExecutionView` | future variation/coupon/dividend cash flow | cash/position delta | future `Account.commit(LifecycleBatch)` |
| `FUNDING`* | funding 시점 | `ExecutionView` | future perpetual funding | cash delta | future `Account.commit(LifecycleBatch)` |
| `EXPIRY`* | 만기 시점 | `ExecutionView` | future final settlement | cash/position delta | future `Account.commit(LifecycleBatch)` |

cutoff 열이 사라진 것에 주의한다. 무엇을 볼 수 있는지는 clock 위치와 각 관측치의 `available_at`이
결정하므로 event마다 명시할 값이 아니다. 일봉의 `available_at`이 15:30이면 09:00 `DECISION`은 당일
종가를 조회할 수 없다 — 별도 설정 없이 시간표에서 유도된다(§7).

별표(`*`) event는 MVP scheduler와 acceptance 대상이 아닌 future extension point다. `DECISION`은 fill을
commit하지 않고 daily runtime의 `MONITOR`도 Account를 변경하지 않는다. Decision intent는 execution event의
immutable input이다.

여기서 current `DailyExecutionFlow`의 `MONITOR` callback은 session performance와 account observation evidence를
만들 뿐 constraint를 평가하지 않는다. Constraint monitoring은 committed checkpoint와 frozen `evaluation_time`을
받는 별도 `QlibxProject.monitor_constraints()` operation이다. Caller가 원하는 cadence로 명시적으로 호출할 수 있고,
future optional scheduler가 같은 operation을 callback으로 등록할 수는 있지만 `run_daily()`는 현재 자동 호출하지 않는다.

† `MATERIALIZE`는 **target boundary**다. Current code에는 public materialization operation/scheduler가 없고
Strategy invocation의 generic requirement resolver만 있다. Rolling/expanding/event-triggered fit, forward-label
`available_at`과 `horizon_end` preflight는 `GAP-MATERIALIZATION-PIT-001` closure acceptance를 갖춘 뒤 current로
승격한다. Direct Strategy나 stored-result analysis에는 이 event가 없다.

\* `SETTLEMENT`·`FUNDING`·`EXPIRY`는 future extension characterization이다. Exchange가 Clock을 직접
조작하지 않는다. Instrument registration 시 필요한 event specification을 반환하고 engine/flow가 Clock에
callback을 등록한다. §13.6과 §15 참조.

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
| **I4** | 커밋되는 authoritative state store는 Account와 Memory 둘이다. 둘 다 flow의 commit boundary에서만 변경된다. Operation은 어느 쪽도 직접 쓰지 않는다 | 공개 API 표면 테스트 |
| **I5** | 모든 operation은 typed result + diagnostics를 반환하거나 commit 전에 `OperationError`로 실패한다 | contract test |
| **I6** | Catalog는 append-only. 같은 identity + 다른 content는 conflict 실패 | 발행 테스트 |
| **I7** | 같은 frozen config + 같은 데이터 → 같은 event 순서 → 같은 결과 | 2회 실행 비교 |
| **I8** | Requirement는 선택한 operation을 호출할 때 resolve한다. 누락은 unrelated registration이나 workflow를 무효화하지 않고 state mutation 전에 실패한다 | progressive-requirement fixture |
| **I9** | Success, failure, retry, actual state와 intended state는 서로 다른 typed evidence다. Failure나 intended state를 authoritative success로 승격하지 않는다 | artifact/reconciliation fixture |
| **I10** | Account의 모든 held Instrument는 frozen registry에 등록되어 있고, Strategy tradable universe와 무관하게 valuation set에 포함된다 | registration + mixed-instrument fixture |
| **I11** | Account change는 event ID 기준 idempotent하고 `expected_version` CAS와 batch atomicity를 지킨다. 실패한 batch는 cash, Position, journal 어느 것도 바꾸지 않는다 | duplicate/stale/partial-failure fixture |

**I1**이 가장 자주 깨진다. Backtest에서 wall clock을 읽는 것은 조용한 재현성 파괴다.

**I2와 I3도 2026-08-03 개정되었다.** 초안의 I2는 event마다 조립한 context를 전제했고, I3는 그
context의 파생 규칙이었다. View 모델에서는 시간 경계가 clock 한 곳에서 강제되므로 두 불변식이
그에 맞게 다시 쓰였다. §17 참조.

**I4는 2026-08-06 다시 개정되었다.** 2026-08-03 개정은 Ledger와 Memory를 두 store로 두었지만 concrete
account state를 Ledger와 Account로 중복 표현하고 있었다. 현행은 Account가 actual state의 유일한 aggregate이고
Memory가 Strategy state의 별도 authority다. 둘 다 Flow만 commit한다. §9와 §16 G1 참조.

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

같은 timestamp의 event는 `priority` 오름차순으로 처리한다. `MARK`가 daily `MONITOR`보다 먼저여야
session performance와 account observation이 갱신된 committed mark를 읽는다. 시각을 인위적으로 벌리는 대신
priority로 표현한다 — 순서의 이유가 코드에 남기 때문이다. 이 순서는 별도 constraint-monitoring operation을
daily flow에 자동 연결한다는 뜻이 아니다.

### Clock implementation 교체

```
BacktestClock   데이터 끝까지 즉시 감는다
LiveClock       실제 시각을 기다린다
```

Clock 교체는 event progression 차이만 설명한다. MVP는 `BacktestClock`만 acceptance 대상으로 삼는다. 향후 live
production은 stream source, Executor/OMS adapter, persistence와 authority source까지 별도로 설계해야 하며 Clock만
바꿔 simulated Fill을 production Fill로 해석하지 않는다.

### Reference와 선택 근거

| 항목 | 출처 | 위치 | 차용 방식 | qlibx 판단 |
|---|---|---|---|---|
| Clock 추상과 test/live 구현 | NautilusTrader | `common/component.pyx` L130/L623/L839 | 설계만 | 같은 callback 계약으로 simulated/live time source를 교체하기 적합 |
| `advance_time`의 시각순 handler 반환 | NautilusTrader | 같은 파일 L790 | 설계만 | Clock은 순서만 소유하고 business logic을 Flow에 남김 |
| TimeEvent / TimeEventHandler와 priority | NautilusTrader | 같은 파일 L1013/L1144, `Subscription.priority` L2911 | 설계만 | IoC와 동시각 결정론을 명시적으로 표현 |
| 단일 시간축 정렬 순회 | vn.py | `alpha/strategy/backtesting.py` L156-166 | 코드 차용 | timestamp merge 산술만 참고하고 callback/priority는 qlibx가 추가 |

### 채택하지 않는 것

Qlib `TradeCalendarManager`(`backtest/utils.py` L23)는 `freq` 하나와 `trade_step` 하나를 갖는
**반면교사**다.
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
    before = account.snapshot(as_of=ev.ts)
    result = profile.executor.execute(ev, view, account=before)
    commit = account.commit(
        FillBatch.from_result(result),
        expected_version=before.version,
    )
    artifacts.publish(result, commit)             # Account commit 뒤 actual result
    if result.completes_decision:
        finalizer.commit_simulation_checkpoint(result.decision_id, account, memory)


def on_mark(ev: Event) -> None:
    view = gate.execution_view(ev.ts, profile.mark_requirements)
    before = account.snapshot(as_of=ev.ts)
    mark, diagnostics = profile.valuation.run(view, account=before)
    commit = account.commit(mark, expected_version=before.version)  # MarkBatch
    artifacts.publish(account.snapshot(as_of=ev.ts), commit, diagnostics)


def on_settlement(ev: SettlementEvent) -> None:        # future characterization
    view = gate.execution_view(ev.ts, ev.requirements)
    before = account.snapshot(as_of=ev.ts)
    lifecycle, diagnostics = profile.settlement.run(view, account=before)
    commit = account.commit(lifecycle, expected_version=before.version)  # LifecycleBatch
    artifacts.publish(account.snapshot(as_of=ev.ts), commit, diagnostics)


def on_monitor(ev: Event) -> None:
    view = gate.monitor_view(ev.ts, profile.monitor_requirements)
    snap = account.snapshot(as_of=ev.ts)
    findings, diagnostics = profile.monitor.evaluate(snap, view)
    artifacts.publish(findings, diagnostics)      # account를 건드리지 않는다
```

Simulation에서는 local Account가 actual-state authority다. Runtime monitoring은 이 committed Account snapshot을
읽는다. External OMS reconciliation과 production Account projection은 future work이며 MVP flow에 포함하지 않는다.
Stored snapshot의 `as-was`/`as-if` 재평가는 별도 analysis invocation이 Catalog artifact를 명시적으로
입력받아 같은 pure evaluator를 호출한다. `latest` 파일을 암묵적으로 선택해 runtime authority와 historical
evidence를 섞지 않는다.

Proposed Memory의 commit timing도 profile contract다. Research-only/hold는 explicit non-execution
finalization에서, MVP simulation decision은 하나의 full-fill execution result와 checkpoint를 묶을 때 CAS commit한다.
Production-specific memory timing은 future work다.

### Default local daily recovery protocol

Local Account와 Strategy Memory가 process memory에만 있으면 final checkpoint 하나로는 commit 직후 crash를 복구할 수
없다. 따라서 Flow는 state-changing callback마다 현재 Account와 Memory를 clone하고 동일한 expected version, event ID,
Memory commit ID로 typed change를 먼저 검증한다. 검증된 post-state, event position, pending DecisionIntent와 아직 발행되지
않았을 수 있는 typed evidence를 `simulation_recovery_point`로 durable publication한 뒤 live Account와 Memory에 같은
candidate를 적용한다. Candidate와 live commit 결과가 다르면 성공으로 진행하지 않는다.

```text
freeze and validate candidate on cloned Account/Memory
  → publish immutable recovery point
  → apply identical Account CAS change
  → apply identical Strategy Memory CAS change
  → publish execution/mark/memory evidence
  → continue events strictly after the stored (timestamp, priority)
```

Process 재시작은 같은 run의 가장 높은 recovery sequence를 load하고 request/config/profile, logical dataset registration과
Strategy identity를 mutation 전에 비교한다. 일치하면 checkpoint의 Account journal과 Memory head를 runtime authority로
복원하고 recovery point에 포함된 누락 evidence를 strict artifact contract로 다시 발행한다. 동일 logical identity와 content는
catalog idempotency로 같은 artifact가 되고, 다른 content는 conflict다. Identity가 달라지면 자동 merge하지 않고
`RESUME_BRANCH_REQUIRED`로 실패한다.

Recovery point는 별도 mutable ledger나 세 번째 runtime authority가 아니라 Account/Memory authority의 portable durable
serialization이다. 이 local simulation protocol은 distributed transaction, external OMS state 또는 broker acknowledgement를
복구한다고 주장하지 않는다.

### Executor는 횡단면 batch sub-flow다

**Exchange와 Executor는 다른 것이다.**

```
Exchange   이 시각·venue/profile에서 얼마나 체결되나   상태를 쓰지 않는 계산. ④ operation.
Executor   그 집합을 언제 어떤 event로 넘기나          sub-flow. ② flow. Account를 쓰지 않음.
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
    │ before = account.snapshot(event.ts)
    ▼
┌────────────────────────────────────────────────────────┐
│ Executor (sub-flow)                                     │
│   q, v = view.quotes(), view.volumes()  ────────────────┼→ ③ view
│   working = WorkingState.from_snapshot(before)          │   local calculation only
│   fills, diags = exchange.match_batch(  ────────────────┼→ ④ operation
│       at=event.ts, orders=event.orders,                 │
│       instruments=compiled_terms, quotes=q, volumes=v, │
│       resources=working.resources(),                    │
│   )                                                     │
│   return ExecutionResult(fills, diags)                  │
└────────────────────────────────────────────────────────┘
    │ account.commit(FillBatch, expected_version=before.version)
    ▼
⑤ Account — batch 전체를 원자적으로 반영
```

### 계약

```python
class Executor(Protocol):
    def plan(self, decision: DecisionIntent, decision_ts: Timestamp) -> list[ExecutionSpec]: ...
    def execute(self, event: ExecutionEvent, view: ExecutionView,
                account: AccountSnapshot) -> ExecutionResult: ...
    def limitations(self) -> tuple[ExecutionLimitation, ...]: ...
```

`Orders`는 단건 목록이 아니라 instrument축 배열 묶음이다. `match_batch`는 §8의 clipping 순서를
elementwise 연산으로 수행한다.

여러 venue가 지원되면 Executor가 stable venue order로 partition하고 shared cash, currency와 collateral
semantics를 명시해야 한다. 현재 stock/ETF scope는 하나의 execution profile로 시작한다. Venue 순서에 따라
공유 현금 결과가 달라질 수 있으므로 이 규칙 없이 병렬 실행하지 않는다.

한 execution event 안에서 여러 주문이 같은 현금을 경쟁하면 Executor/Exchange의 local working state가 stable
order로 잔여 현금을 계산한다. 이 임시 계산은 Account authority가 아니며 성공한 전체 `FillBatch`만 한 번에
commit된다. MVP에는 partial fill이나 여러 execution event에 걸친 pending quantity가 없다.

### Future work — 같은 계약으로 intraday Executor를 끼운다

다음 내용은 MVP acceptance가 아닌 future characterization이다. Daily와 intraday Executor의 차이는 Account
mutation 방법이 아니라 **execution event 계획과 필요한 market data**다.

```text
DecisionIntent: 삼성전자 1,000주 BUY                         # 둘이 공유

Next-session close Executor
  E1 다음 session close → Fill 1,000주 → Account.commit(FillBatch) → 완료

Intraday Executor
  E1 09:30 → Fill 300주 → Account commit v11
  E2 11:00 → 최신 Account v11 + 최신 quote/volume → Fill 200주 → commit v12
  E3 15:20 → 최신 Account v12 + 최신 quote/volume → Fill 100주 → commit v13
  종료      → 400주 미체결과 limitation을 ExecutionResult/Evidence에 기록
```

Intraday `plan()`은 calendar와 frozen DecisionIntent만으로 여러 `ExecutionSpec`을 만든다. 미래 quote를 보고
event 시각을 소급 선택하지 않는다. 각 callback의 `execute()`는 그 시각까지 available한 `ExecutionView`와
가장 최근 `AccountSnapshot`만 읽는다. `ExecutionResult.completes_decision`이 false이면 다음 event가 같은
decision ID와 remaining quantity를 이어받고, 마지막 event나 expiry/cancel policy가 decision을 종료한다.

따라서 Executor를 교체해도 다음 계약은 변하지 않는다.

```text
immutable DecisionIntent
  → one or many ExecutionEvent
  → ExecutionResult(FillBatch + diagnostics)
  → Flow-owned Account.commit(expected_version)
  → 다음 event와 다음 Strategy가 committed actual state를 읽음
```

Intraday profile은 quote/volume 또는 order-book binding, latency/liquidity model과 scheduling limitation을 추가로
선언한다. Data가 없으면 next-close 결과로 조용히 축약하지 않고 requirement resolution에서 실패한다. 이 때문에
첫 naive profile을 구현해도 Executor/Account public contract를 다시 설계하지 않고 intraday 가정을 추가할 수 있다.

MVP architecture validation은 daily full-fill executor만 대상으로 한다. 향후 intraday profile을 추가할 때도 별도
public class name을 PRD에 고정하지 않고 schedule granularity, required market binding, liquidity model과 limitation을
위 계약 뒤에서 선언한다. 지원하지 않는 granularity를 daily fill로 조용히 축약하지 않는다.

### Current next-close execution과 future FillConvention

**Current implementation.** `NextSessionCloseExecutor`는 다음 eligible session close의 `EventSpec`만 만들고,
`DailyExecutionFlow`가 `DailyExecutionProfile.execution_price_role`을 `ExecutionView`에서 resolve해 size/match한다.
별도 `FillConvention`, `ClosePriceFill`, `OpenPriceFill` class는 현재 없다. 아래는 두 번째 convention이 실제로
생길 때의 **target/future pseudocode**이며 current public symbol이 아니다.

Executor가 정하는 것은 **일정**(언제 몇 번 넘기나)이고, 체결가 규약은 별도 축이다. 둘을 묶으면
"종가 체결"을 "시가 체결"로 바꾸는 데 executor를 새로 써야 한다.

```python
# target/future pseudocode — not a current public symbol
class FillConvention(Protocol):
    def reference_price(self, view: ExecutionView) -> Prices: ...   # instrument축 배열
```

```
ClosePriceFill     execution event가 속한 session의 close를 기준 가격으로 사용
OpenPriceFill      execution event가 속한 session의 open을 기준 가격으로 사용
IntradayVWAPFill   execution event가 선언한 intraday 구간의 VWAP을 기준 가격으로 사용
```

Target 설계가 의도하는 첫 조합은 `NextSessionCloseExecutor`와 close-price convention의 분리지만, current 구현은 **`NextSessionCloseExecutor` + profile의 execution-price role + `DailyExecutionFlow`** 이다. 예를 들어 월말
session 종가가 available해진 뒤 `DECISION`이 확정되면 Executor는 다음 eligible trading session의 close에
`EXECUTION` event를 등록하고, FillConvention은 그 event가 속한 session의 close를 기준 가격으로 고른다.
당일 종가나 단순히 "현재 close"에 체결한다는 뜻이 아니다. 이 분리로 **언제 체결을 시도하는가**와
**어느 가격을 기준으로 삼는가**를 독립적으로 바꿀 수 있다.

이 조합은 가장 단순하고 낙관적인 simulation profile이다. 다음 session close 한 가격으로
전체 batch가 체결된다고 가정하며, 별도 liquidity model이 없으면 장중 가격 경로, market impact와 partial fill을
설명하지 못한다. 가격은 StrategyView에서 복사하지 않고 execution event의
`available_at <= event.ts`를 만족하는 ExecutionView에서 읽는다. 다음 session close가 아직 available하지
않으면 Fill 전에 실패한다. Result artifact는 convention identity, decision time, scheduled session, fill time,
modelled/unmodelled liquidity와 limitation을 기록한다.

Same-session close는 기본값의 다른 이름이 아니다. Decision이 close 공개 전에 확정되고 별도 profile이 그
시점과 availability를 명시할 때만 가능한 별도 convention이다.

Future convention 교체는 Strategy decision artifact를 바꾸지 않아야 한다. Next-open은 real PIT open observation, schedule 계약과 no-Strategy-rerun acceptance가 없는 readiness gap이다. 다만 required market binding, execution
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
- 실현손익 누적에 의존하는 stop-loss 같은 path-dependent 정책이 성립한다 (§16 G1, G2)

흔히 "vectorized backtest"로 불리는 것 — `(weights.shift(1) * returns).sum()` 형태의 시간 축
일괄 계산 — 은 이와 다르다. 그쪽은 feedback edge 자체가 없어 PRD §4.3을 만족할 수 없으며
채택하지 않는다. **벡터화 대상은 instrument 축이고 시간 축이 아니다.**

### 읽기와 쓰기를 분리한다

Executor는 immutable `AccountSnapshot`만 읽고 `ExecutionResult`를 반환한다. `Account.commit()`은 Flow만
호출한다. 이름은 쓰기 전용처럼 보이지만 cash/positions 조회까지 제공하던 `FillSink`는 제거한다.

```text
query     Account.snapshot()     → immutable state
compute   Executor / Exchange    → typed result + diagnostics
command   Account.commit()       → validated atomic transition
```

이 경계는 **Functional Core, Imperative Shell** 패턴이다. Exchange와 valuation policy는 frozen input으로
결과를 계산하는 functional core이고, Flow는 callback 순서와 commit을 담당하는 imperative shell이다. 계산
실패를 Account mutation과 분리하고 같은 입력의 체결 산술을 독립적으로 검증하기 위해 적절하다.

Executor, Exchange와 valuation policy는 **Strategy Pattern**으로 교체하며 current `QlibxProject`/Flow 조립이 생성자에서 명시적으로
주입한다. 향후 daily executor를 intraday executor로 바꾸더라도 `ExecutionResult → Account.commit()` 계약은
변하지 않도록 경계를 유지한다.

### qlib과의 차이

qlib은 `exchange.deal_order(order, trade_account=account)`로 **Exchange가 account를 직접 변경**한다
(`backtest/exchange.py` L421). 계산기가 상태를 건드린다.

qlibx는 분리한다.

```python
fills, diags = exchange.match_batch(
    at=event.ts, orders=orders, instruments=compiled_terms,
    quotes=quotes, volumes=volumes, resources=working.resources(),
)                                                                    # explicit input의 순수 계산
account.commit(FillBatch(fills), expected_version=before.version)     # Flow만 반영
```

얻는 것: (1) account 없이 체결 산술을 테스트할 수 있다, (2) 같은 주문 집합을 여러 시나리오로 돌릴
수 있다 (what-if, PRD §9.9), (3) `diags`를 버릴 수 없다.

qlib은 주문 단건 순회이므로 이 분리가 성립해도 batch가 되지 않는다. qlibx는 단위 자체를
instrument축 배열로 두어 `deal_order` 순회를 elementwise 연산으로 대체한다.

### Flow/Executor reference와 선택 근거

| 항목 | 출처 | 위치 | 차용 방식 | qlibx 판단 |
|---|---|---|---|---|
| 일단위 executor 골격 | Qlib | `backtest/executor.py` L513/L561 | 코드 차용 | decision 뒤 별도 execution step을 여는 최소 흐름에 사용 |
| 계층 위임 아이디어 | Qlib | 같은 파일 L310 `NestedExecutor` | 설계만 | 상위 decision과 하위 execution 분리는 참고하되 고정 계층은 강제하지 않음 |
| 일별 순회와 체결 loop | vn.py | `alpha/strategy/backtesting.py::new_bars` | 코드 차용 | deterministic loop 산술만 참고 |
| executor 교체와 분할 실행 | NautilusTrader | `execution/client.pyx` L71/L198, `algorithm.pyx` L88/L870-930 | 설계만 | client 교체와 primary order의 child-order 분할 아이디어를 one-or-many execution event seam에 사용 |
| callback과 Flow-owned Account commit | qlibx | §2.3, §6, §9 | 순수 창작 | reference의 mutable account/cache 접근을 PIT-safe snapshot/atomic commit으로 바꿈 |

NautilusTrader처럼 intraday execution을 별도 client/algorithm 뒤에 둘 수 있다는 점은 배우지만, qlibx는
MessageBus와 live order graph를 복사하지 않는다. Decision-time 횡단면과 `available_at` View를 유지한 채
Executor가 event를 나누고 같은 Account commit 계약을 호출하는 것이 현재 product 범위에 더 작고 명확하다.

---

## 7. ③ view ★

**정보 경계를 강제하는 layer다.** 초안에서는 `gate`가 event마다 snapshot을 조립해 넘기는
구조였으나, 2026-08-03 개정으로 **clock에 묶인 조회 창구(view)** 방식으로 교체되었다. 변경 이유와
근거는 §17에 기록한다.

### Minimal registration과 progressive requirement resolution

최초 dataset registration은 모든 미래 workflow의 schema를 요구하지 않는다. 다음 최소 계약만
validation하고 logical dataset identity를 발행한다.

```text
logical key / instrument axis
available_at binding 또는 user-confirmed derivation rule
payload location, shape, null/uniqueness facts
```

Event/effective time, semantic category와 source provenance는 알려져 있으면 기록할 수 있지만 최초 registration을
막는 전역 필드가 아니다. 이를 실제로 필요로 하는 future lifecycle operation 등이 자신의 requirement로 요구한다.

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

모든 관측치는 qlibx PIT gate가 사용하는 `available_at`을 갖는다. `event_time`은 source가 제공하거나 선택한
operation이 경제적 의미상 요구할 때 보존할 수 있지만 MVP의 전역 계약이 아니다.

```
available_at    관측 가능해진 시각          ← PRD §4.4의 available_at
event_time?     그 사건이 발생한 시각       ← optional payload/operation requirement
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

| view | current capability | 구조적으로 제외 |
|---|---|---|
| `StrategyView` | declared PIT dataset/artifact, committed Account snapshot, bounded feedback/performance, Strategy memory | undeclared binding, future feedback, mutable state port |
| `ExecutionView` | declared PIT dataset only | artifact, Account, feedback, performance, memory |
| `MonitorView` | declared PIT dataset + committed Account snapshot | artifact, feedback, performance, memory, mutable Account port |
| `MaterializeView` | declared PIT dataset only; public materialization operation은 아직 gap | artifact, Account, feedback, performance, memory |

View 이름이 global field 목록을 뜻하지 않는다. Resolver가 이번 operation에 허용한 binding만 facade에
넣는다. Compliance data나 monitoring finding을 Strategy에 쓰려면 Strategy requirement가 이를 명시해야
하며 자동 feedback하지 않는다.

Strategy가 actual account state를 요구하면 `AccountSnapshot`에는 모든 held position과 전체 cash/NAV가
들어간다. Strategy tradable universe는 이 snapshot을 잘라내는 filter가 아니라 **새 주문을 검증하는 경계**다.
따라서 주식 Strategy는 보유 Future와 그 평가 결과를 볼 수 있지만 Future order는 만들 수 없다. Future의 raw
quote나 funding observation은 별도 data requirement를 선언하지 않는 한 StrategyView에 자동 노출되지 않는다.

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

class AccountView(Protocol):
    def snapshot(self) -> AccountSnapshot: ...
    def feedback(self, after: FeedbackCursor, limit: int) -> AccountFeedback: ...
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

qlibx의 논리적 접근 단위는 **decision time의 횡단면**이다. Current view는 메모리 누적 컨테이너가
아니라 registered source를 매 query에 읽는 시간 한정 projection으로 구현한다. Query 전에 source fingerprint를 확인해 drift를 거부한다.

```
current source   user-owned CSV 또는 Parquet
current query    pandas read + projected columns + in-memory PIT/filter
current return   DataFrame (instrument × field)
future target    partitioned Parquet + DuckDB predicate pushdown
```

Current 방식은 별도 ingestion 없이 user source를 보존해 단순하지만 반복 full scan과 대규모 workload 비용이 단점이다. Columnar store는 representative PIT benchmark와 ingestion/invalidation/migration 계약이 준비된 뒤 도입한다. 이 횡단면 논리 축은 세 reference 어디에도 대응물이 없으므로 qlibx 순수 창작이다.

### View reference와 선택 근거

| 항목 | 출처 | 위치 | 차용 방식 | qlibx 판단 |
|---|---|---|---|---|
| `ts_event` / `ts_init` 이중 timestamp | NautilusTrader | `core/data.pyx` L30/L42 | 비교 근거 | qlibx는 `ts_init`에 대응하는 `available_at`만 전역 필수로 채택하고 event time은 optional로 둠 |
| `ts_init` 오름차순 stream과 data/timer ordering | NautilusTrader | `backtest/engine.pyx` L903/L1658-1735 | 설계만 | 아직 available하지 않은 observation을 stream 밖에 둠 |
| revision 표시 | NautilusTrader | `model/data.pyx` L1496 `is_revision` | 설계만 | restatement를 원본과 구분 |
| read-only Cache/Portfolio facade | NautilusTrader | `cache/base.pxd`, `portfolio/base.pxd`, `common/actor.pxd` L73/L83 | 설계만 | mutable store 대신 bounded read Protocol을 제공 |
| learn/infer 데이터 분리 | vn.py | `alpha/dataset/template.py` L181-194 | 코드 차용 | optional materialization의 입력 역할 분리에 사용 |
| 시간 범위 표현 | Qlib | `backtest/decision.py` L206-300 `TradeRange` | 코드 차용 | event range 표현만 차용 |
| 문자열 key service locator | Qlib | `common_infra.get(...)` | 반면교사 | 타입·requirement·authority 경계를 우회하므로 거부 |
| 횡단면 PanelView, 접근 기록 lineage, 역할별 View | qlibx | §7 | 순수 창작 | 20년 × 3,000종목 PIT research와 progressive requirement에 필요 |

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
backtest    BacktestClock + historical stream + simulated Account
future production  LiveClock + arrival stream + reconciled OMS account
```

MVP는 backtest profile만 구현한다. Future production에서도 Gate와 operation 구현은 재사용할 수 있지만 Clock만
바꾸면 production이 되는 것은 아니며 stream, Executor/OMS port와 authority source를 함께 설계해야 한다.

---

## 8. ④ operation

### 공통 계약과 선택 가능한 graph

각 operation은 requirement를 먼저 선언하고 resolved view에서 typed result와 diagnostics를 계산한다.
공통 모양은 같지만 result type과 graph 위치는 operation마다 다르다. 다음 `Operation` 계열은 두 번째 구현이 생길 때 추출할 **target pseudocode**이며 current public protocol이 아니다.

```python
# target pseudocode — current code uses concrete operation/flow contracts
class Operation(Protocol[ResultT]):
    def requirements(self, invocation: FrozenInvocation) \
            -> tuple[ComponentRequirement, ...]: ...
    def run(self, view: ScopedView) -> tuple[ResultT, Diagnostics]: ...

class StrategyOperation(Operation[StrategyDraft], Protocol): ...
class MaterializeOperation(Operation[ResearchDataArtifact], Protocol): ...  # readiness gap
class AnalysisOperation(Operation[AnalysisArtifact], Protocol): ...
class RendererOperation(Operation[ReportArtifact], Protocol): ...
```

Current Strategy는 signed alpha weights와 optional proposed memory를 담은 `StrategyDraft`를 반환한다. Flow가 실제 view access와 frozen invocation identity를 결합해 authoritative `StrategyResult`로 승격하고, closed-loop workflow이면 executor-neutral
`DecisionIntent`를 함께 제공한다. Strategy가 signal과 weights를 내부에서 한 번에 계산해도 되고,
stored signal/characteristic/risk result를 읽어도 된다. Future `MaterializeOperation`은 그 reusable result를 생산하는 optional path다. Public boundary를 넘거나
재사용되는 intermediate만 정확한 semantic artifact로 materialize한다.

Project-local Strategy가 alpha logic의 primary extension point다. Package는 module/source identity, public
input/output contract와 deterministic fixture로 compatibility를 판정하고 성공한 component만 등록한다. Strategy가
stored artifact를 요구하면 Flow가 role/schema/semantics를 resolve·load하고 evidence-independent immutable projection만
scoped view에 주입한다. User code는 artifact backend나 raw observation store를 직접 읽지 않는다. Current에는 Model materialization public operation이 없다. Target에서 Model과
`MATERIALIZE`는 selected Strategy가 reusable intermediate를 요구할 때만 존재하는 optional path다.

```python
StrategyOperation.run(view)     -> StrategyDraft
Flow.promote(draft, accesses)   -> StrategyResult
ModelOrTransform.run(view)      -> ResearchDataArtifact  # target; not current materialization API
construct(weights, view)        -> (PhysicalTarget, Diagnostics)       # optional
adjust(candidate, view)         -> (AdjustmentResult, Diagnostics)     # optional
convert(target, view)           -> (Orders, ConversionLog)             # optional
validate(candidate, view)       -> (Verdict, Findings)                 # optional
analyze(artifact, view)         -> (AnalysisArtifact, Diagnostics)     # optional
render(analysis, options)       -> (ReportArtifact, Diagnostics)       # optional
exchange.match_batch(at, orders, instruments, quotes, volumes, resources)
                                -> (Fills, FillDiagnostics)
```

첫 view 인자는 **clock과 resolved requirements에 묶인 조회 창구**다(§7). Operation은 필요한 만큼
조회하며 view가 실제 접근을 lineage로 기록한다. Constraint-free analysis, direct Strategy와 stored-result
reuse는 construct/adjust/convert/validate를 호출하지 않는다.

Ensemble은 별도 mandatory stage가 아니라 `StrategyOperation` 구현이다. Member Strategy result를 typed
artifact로 읽고 ticker-level netting, crossing, member contribution과 fixed/flexible budget residual을
기록한다. Member producer가 direct Strategy인지 Model result를 소비했는지는 Ensemble public contract가
아니다.

Path-dependent result도 frozen typed input으로 재사용 가능하다. Flow는 consumer가 선언한 artifact role, schema와
semantics를 확인하고 실제로 load·consume한 member에만 dependency edge를 만든다. 새 Strategy/Ensemble result는 source
artifact ID뿐 아니라 그 member가 의존한 모든 Account/Memory state identity와 feedback cursor를 보존한다. Member
producer는 재실행하지 않고 parent artifact도 변경하지 않는다.

이 reuse는 target/current Account에서 member를 다시 계산했다는 주장이 아니다. 이후 physical target 또는 order
conversion만 현재 committed Account와 그 시점의 execution input을 읽는다. Consumer-declared budget/schema/semantic
requirement가 맞지 않으면 Strategy 계산 전에 explicit compatibility error로 실패한다.

`exchange.match_batch`만 view를 받지 않는다. 필요한 관측값은 Executor가 view에서 꺼내고, effective-dated
policy를 고르기 위한 event time은 `at`으로 명시한다. Exchange는 wall clock을 읽지 않으며 같은 frozen
instrument/exchange config, `at`과 배열 입력에서 같은 결과를 낸다. 인자는 instrument축 배열이며 clipping이
elementwise로 수행된다.

모두 typed result와 diagnostics를 반환한다(I5). 이 layer는 state를 직접 변경하지 않으므로 built-in,
project-local과 external implementation을 같은 validation boundary 뒤에서 교체할 수 있다. Package가
compatibility를 판정하고 agent는 failure evidence를 해석할 뿐 등록 성공을 대신 선언하지 않는다.

`Account.commit()`은 Operation이 아니다. Operation은 계산 결과를 만들고, commit은 Flow가 호출하는 state
transition이다. 이 구분이 없으면 user-defined Operation이 actual cash나 Position을 우회 변경할 수 있다.

### Constraint adjustment, validation과 monitoring

세 operation은 authority와 output이 다르다.

```text
adjust proposed intent   → modified candidate + unresolved residual
validate final candidate → execution eligibility + finding
monitor committed actual → actual-account finding; account mutation 없음
```

Adjustment result가 존재해도 compliance를 의미하지 않는다. Constraint를 선택한 workflow만 declaration과
metric data requirement를 resolve한다. MVP hard constraint는 no-short와
`single-name weight <= max(10%, index constituent weight)`뿐이다. Missing PIT benchmark weight는 order나
hypothetical account를 만들기 전에 실패하고, constraint-free signal research에는 compliance dataset을 요구하지
않는다. Sector와 기타 constraint는 future work다.

### User Strategy-owned ETF look-through

ETF look-through는 qlibx의 Instrument capability나 자동 exposure operation이 아니다. Exchange와 Account는 ETF를
항상 하나의 physical Instrument로 체결·보유한다. ETF를 등록하거나 Account가 ETF 수량을 보유한다는 사실은
constituent data requirement, mapping resolution 또는 exposure 계산을 발생시키지 않는다.

선택권은 **Strategy별로 user에게만** 있다. 같은 ETF도 Strategy A가 constituent data를 선언하지 않으면 opaque이고,
Strategy B가 index/ETF constituent dataset을 명시적으로 구독해 StrategyView에서 consume하면 B의 user code 안에서만
look-through가 일어난다. Instrument와 config에는 `opaque/transparent` mode를 두지 않는다.
여기서 구독은 O6의 runtime pub/sub를 뜻하지 않는다. `DatasetRequirement`로 logical binding을 선언하고 Flow가 그
callback의 scoped StrategyView에 resolve하는 기존 requirement 계약을 뜻한다.

예를 들어 user Strategy가 아래 계산을 선택할 수 있다.

```text
rows     constituent exposure axis C
columns  physical instrument axis P — direct Equity와 ETF
L_t      Strategy가 declared PIT data로 직접 만든 mapping[C, P]
p_t      Strategy가 actual AccountSnapshot으로 직접 만든 physical weight[P]
x_t      Strategy-owned constituent exposure[C] = L_t @ p_t
```

이 식, direct Equity identity column, ETF constituent column과 cash 처리 방식은 package contract가 아니라 user의
경제적 계산이다. qlibx는 `L_t`를 만들거나 적용하지 않는다. Strategy가 결과를 artifact로 반환할 때만 generic
Evidence가 실제로 읽힌 dataset과 AccountSnapshot의 dependency edge를 기록한다.

qlibx가 소유하는 경계와 user가 소유하는 의미를 분리한다.

| qlibx가 소유 | user Strategy가 소유 |
|---|---|
| Logical dataset registration과 declared binding | 어떤 index/ETF constituent source를 구독할지 |
| `available_at <= clock.now()` ViewGate | available row 중 어떤 observation을 사용할지 |
| Immutable actual AccountSnapshot 접근 | ETF 수량·mark·cash에서 어떤 physical exposure를 만들지 |
| 실제 조회에서 생성한 dependency lineage | mapping schema, axis, coverage, normalization과 계산식 |
| Generic StrategyResult/Artifact envelope | target/actual exposure result를 만들고 소비할지 |

따라서 package-owned `LookthroughSnapshot`, `LookthroughExposureResult`, coverage profile 또는 ETF mapping resolver는
두지 않는다. `opaque`도 별도 profile이 아니라 **Strategy가 constituent binding을 선언·소비하지 않은 상태**다.
Look-through를 쓰는 Strategy가 complete/partial/stale 정책을 원하면 그 Strategy code에서 검증하고
diagnostic을 반환한다. ViewGate는 미래 observation을 숨기지만 그 데이터의 경제적 해석을 대신하지 않는다.

개념적인 callback은 다음과 같다. 이름은 public API 확정이 아니라 책임 경계를 보여준다.

```python
class MyEnhancedIndexStrategy:
    requirements = (
        DatasetRequirement("etf_constituents"),
        AccountStateRequirement(),
    )

    def decide(self, view: StrategyView) -> StrategyResult:
        members = view.panel("etf_constituents")  # declared PIT data만 노출
        account = view.account.snapshot()          # marked actual ETF quantity
        exposure = user_defined_exposure(members, account)
        return user_defined_result(exposure)
```

다른 Strategy가 `DatasetRequirement("etf_constituents")`를 선언하지 않으면 같은 ETF를 보유해도 구성종목 데이터는
View에 없고 exposure result도 생성되지 않는다. ETF Instrument registration에서 이 requirement를 암묵적으로
추가하는 경로는 금지한다.

Look-through를 선택한 user Strategy의 flow는 다음처럼 기존 callback/IoC 안에 머문다.

```text
user declares constituent DatasetRequirement + AccountStateRequirement
  → Flow resolves only those bindings and creates StrategyView
  → user Strategy consumes PIT constituent rows + marked AccountSnapshot
  → user code computes optional exposure/constraint/physical target
  → Strategy returns its chosen result/artifact/diagnostics
  → ordinary optional construct / adjust / validate / execute flow
  → Account.commit(FillBatch) keeps physical ETF quantity authoritative
  → next user Strategy callback may read the new actual snapshot and recompute
```

User code가 desired constituent exposure, actual holding 대비 turnover, risk와 expected cost를 최적화할 수는 있다.
그 결과를 built-in construction/constraint에 넘길 때는 explicit input/artifact여야 하며, downstream operation이 ETF를
보고 constituent exposure를 다시 계산하지 않는다. Expected cost는 target choice의 assumption이고 actual Fill cost는
§8의 exact Exchange rule이 계산한다. Risk input 부재를 identity covariance로 조용히 대체하지 않는 원칙도 user
optimizer의 validation contract로 남는다.

User-authored optimizer는 tradable하지 않은 physical instrument를 requested target이 아니라 actual holding에 freeze하고,
solver 뒤 budget/bounds/user-defined exposure constraint를 독립 검증할 수 있다. 이 behavior는 qlibx ETF subsystem이
아니라 user Strategy 계산의 계약이며, StrategyResult diagnostic과 generic artifact evidence로 결과를 표현한다.

Account는 오직 physical state authority다. qlibx가 target이나 actual look-through를 Account/feedback에 자동 추가하지
않는다. User가 두 결과를 publish하면 별도 artifact/schema로 구분하고, actual artifact는 실제로 consume한 marked
AccountSnapshot에 의존해야 한다. 재계산 가능성, mapping identity와 axis 검증 수준도 그 user-owned artifact schema가
정한다.

`references/qlib-integration-codex`는 non-authoritative comparative implementation이다. 여기서 확인한 동작을
다음처럼 선별한다.

| reference behavior | 판단 | qlibx 적용 |
|---|---|---|
| `lookthrough_matrix @ physical_target`과 exact axis 검사 | 계산 아이디어 채택 | user Strategy 예제와 fixture에서 사용; package가 자동 실행하지 않음 |
| Non-tradable physical position을 actual holding에 freeze | 채택 | AccountSnapshot authority와 adjustment requirement로 표현 |
| Turnover를 current realized physical holding에서 계산 | 채택 | target/requested state가 아니라 marked actual input 사용 |
| Solver 뒤 독립 budget/bound/hard-constraint validator | 채택 | validate operation으로 분리하고 stored input에서 재계산 |
| Infeasible와 solver failure 구분, named soft slack 기록 | 채택·확장 | invalid solution도 별도 status로 추가하고 adjustment/validation evidence를 분리 |
| Stored target과 mapping으로 exactly-once attribution 재검증 | 조건부 채택 | user가 그런 artifact schema를 publish할 때 producer-independent reader validation으로 구현 가능 |
| Config 안의 날짜 없는 static nested mapping | 거부 | user가 constituent source를 PIT dataset으로 등록·구독하고 StrategyView에서 consume |
| Risk covariance가 없을 때 identity matrix 사용 | 거부 | 경제적 의미를 바꾸는 silent default이므로 progressive requirement로 실패하거나 risk-free profile을 명시 |
| Solver 결과를 사후 재정규화 | 제한 | tolerance 안 cleanup만 raw delta를 남기고 전 constraint를 재검증; budget을 맞추기 위한 의미 변경 금지 |
| Optimizer target exposure를 `realized_lookthrough_exposure`로 기록 | 거부 | user artifact를 만들더라도 target과 actual authority를 분리 |
| Qlib feedback/object와 결합된 target policy | 거부 | user Strategy가 declared StrategyView와 AccountSnapshot을 직접 consume |

근거 위치는 `kwam_qlib_backend/constraint_optimization.py`, `qlib_extended/enhanced.py`,
`qlib_extended/enhanced_attribution.py`, `report_twin/portfolio.py`,
`tests/test_goal_09_optimizer_contract.py`다. 계산식과 fixture idea만 참고하며 Qlib lifecycle이나 public object
shape를 차용하지 않는다.

### Instrument와 Exchange registration

Config/registration 경계에서는 concrete Pydantic model을 사용한다. Generic `kind + parameters` bag으로
상품을 만들지 않는다.

```python
engine.add_exchange(KrxExchange(exchange_id="XKRX", cost_schedule=krx_schedule))
engine.add_instrument(samsung)
engine.add_instrument(kodex_etf)
```

이 explicit registration 순서는 NautilusTrader
`backtest/engine.pyx::BacktestEngine.add_venue`(L502)와 `add_instrument`(L733)를 **설계만 차용**한다.
NautilusTrader는 venue를 먼저 만들고, instrument의 venue가 등록됐는지와 account compatibility를 검증한 뒤
instrument를 DataEngine/Cache와 SimulatedExchange 양쪽에 연결한다(L756-779).

qlibx에 적합한 부분은 **"venue/profile을 먼저 등록하고 Instrument를 그 경계에 명시적으로 연결한다"**는
build-time rule이다. 이 순서가 있어야 잘못된 venue ID, cash account에 맞지 않는 margined contract, 누락된
exact cost/settlement policy를 run 전에 실패시킬 수 있고, 등록 완료 뒤 3,000종목을 stable index array로
compile할 수 있다. 사용자가 어떤 Exchange를 쓰는지도 config에 드러난다.

NautilusTrader의 구현 전체는 가져오지 않는다. Instrument를 mutable Cache, MessageBus, execution client와
연결하는 live-runtime object graph는 qlibx의 컬럼 저장소 View와 횡단면 batch에 과하다. qlibx는 frozen
InstrumentRegistry와 Exchange listing/policy만 만들고 runtime data는 `available_at` View로 읽는다.

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

Account 초기 Position도 같은 frozen registry에 대해 검증한다. 등록되지 않은 Instrument, venue/listing과 맞지
않는 Instrument 또는 required accounting policy가 없는 Position은 Engine 시작 전에 실패한다. Strategy
tradable universe는 별도로 등록하며 Account의 기존 held instrument를 삭제하지 않는다.

Future extension에서 Exchange는 registration 결과로 lifecycle `EventSpec`을 반환할 수 있다. Flow가 이를
Clock에 등록하며 Exchange가 Clock이나 Account를 직접 보유하거나 변경하지 않는다.

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
Required rule이 없으면 structured unsupported failure를 반환하고 Fill과 Account mutation을 만들지 않는다.

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

NautilusTrader `risk/engine.pyx`의 구조를 **설계만 차용**한다. Validator는 strategy와 executor 사이에 물리적으로
위치하며 두 가지만 한다.

```
통과시키거나  (L1185 _send_to_execution)
사유와 함께 거부하거나  (L1073-1132 _deny_*)
```

**조용히 수정하지 않는다.** 주문이 크면 줄이는 것이 아니라 거부하고 이유를 남긴다. 조용한 수정이
허용되면 backtest 결과가 전략 때문인지 engine 보정 때문인지 구분할 수 없다.

PRD §10.3의 best-effort adjustment와 independent validation은 다른 책임이다. 전자는 조정하고
후자는 판정한다. 조정 결과가 존재한다는 사실이 compliance를 보증하지 않는다.

### Operation provenance 요약

| 항목 | 출처 | 위치 | 차용 방식 | qlibx 판단 |
|---|---|---|---|---|
| clipping, lot, tradability, volume/impact 산술 | Qlib | `backtest/exchange.py` L295/L338/L728/L761/L786/L834/L859-950 | 코드 차용 | 검증된 산술을 batch화하고 모든 clip diagnostic을 반환 |
| cost/fill model 교체 seam | NautilusTrader | `backtest/models/{fee,fill}.pyx` | 설계만 | fee/tax와 fill-price assumption을 분리 |
| pass / deny-with-reason risk 경계 | NautilusTrader | `risk/engine.pyx` L584-666/L1073-1132 | 설계만 | Validator가 주문을 조용히 수정하지 않도록 함 |
| target/actual 이원 관리와 long/short 4방향 분해 | vn.py | `alpha/strategy/template.py` L31-32/L133/L144-185 | 코드 차용 | intended state와 actual state를 섞지 않는 계산에 사용 |
| ts/cs/processor 연산 정의와 검증용 factor set | vn.py | `alpha/dataset/{ts_function,cs_function,processor}.py`, `datasets/alpha_{101,158}.py` | 설계만/코드 차용 | 연산 의미는 참고하되 pandas 경계로 구현 |
| target→order 변환, Finding, constraint adjustment | qlibx | §8 | 순수 창작 | residual과 실패 이유를 버리지 않는 PRD 계약에 맞춤 |

---

## 9. ⑤ account

### Account는 하나의 consistency boundary다

`Account`는 실제 cash, Position, mark와 accounting journal을 함께 관리하는 **Aggregate Root**다. Position이나
cash를 외부 객체가 직접 수정할 수 없다. PRD에서 ledger라고 부른 역할을 이 concrete object가 수행하며 별도
`Ledger`, `FillSink`, `TradeLedger` 객체를 만들지 않는다.

```python
AccountChange = FillBatch | MarkBatch | LifecycleBatch | ReconciledBatch

class Account:
    def snapshot(self, as_of: Timestamp) -> AccountSnapshot: ...
    def feedback(self, after: FeedbackCursor, limit: int) -> AccountFeedback: ...
    def commit(
        self,
        change: AccountChange,
        expected_version: int,
    ) -> AccountCommit: ...
```

`snapshot()`과 `feedback()`은 immutable read model을 반환하고 `commit()`만 state를 변경한다. 이는
**Command-Query Separation**이다. 별도 read database가 없고 event replay만으로 현재 state를 재구성하도록
강제하지 않으므로 full CQRS나 Event Sourcing이라고 부르지 않는다.

Account의 논리 상태는 다음으로 제한한다.

```text
identity        account ID, base currency, frozen InstrumentRegistry identity
current state   cash, sparse positions, marks, valuation status, NAV
position state  quantity, average cost, realized PnL, instrument-specific settlement basis
commit state    applied event IDs, feedback cursor, version
journal         committed Fill, lifecycle cash flow, position delta의 순서
```

성과 지표, chart와 report는 Account 책임이 아니다. Evidence/analysis가 AccountSnapshot과 journal artifact에서
계산한다. Account journal은 commit 순서, resume와 Strategy feedback의 authority이고, Evidence는 process 밖에서
재사용할 수 있는 portable immutable 기록이다.

### Typed change와 atomic commit

| AccountChange | 의미 | current support |
|---|---|---|
| `FillBatch` | Fill, transaction cost, cash와 Position 변화 | stock/ETF current path |
| `MarkBatch` | 모든 held instrument의 valuation input과 NAV 변화 | stock/ETF current path |
| `LifecycleBatch` | future dividend/distribution, variation margin, funding, expiry | future characterization |
| `ReconciledBatch` | external OMS가 확인한 Fill/account 결과 | future production boundary |

MVP `FillBatch`는 eligible stock/ETF order를 전량 체결하고 원금과 거래비용을 같은 commit에서 cash에 반영한다.
Unsettled cash, receivable/payable과 settlement calendar는 만들지 않는다. 이 instant-settlement assumption은 profile
limitation으로 보존한다. Merger, spin-off와 delisting의 해석·instrument 변환은 security master/ETL 책임이며
`LifecycleBatch`가 원천 corporate-action processor가 되어서는 안 된다.

Flow만 `commit()`을 호출한다. Account는 commit 전에 다음을 모두 검증한다.

1. change의 account ID와 base currency가 일치한다.
2. 모든 Instrument ID가 frozen registry에 등록되어 있다.
3. event/fill ID가 아직 적용되지 않았다.
4. `expected_version`이 현재 version과 같다.
5. instrument-specific accounting와 exact policy가 해당 change를 지원한다.
6. batch 전체 적용 뒤 cash, Position과 settlement state가 유효하다.

하나라도 실패하면 아무 state도 바뀌지 않는다. 성공하면 batch 전체, journal append, feedback cursor와 version
증가가 하나의 commit이다. Target weight, submitted order나 hypothetical post-trade state를 commit하는 change는
존재하지 않는다.

```text
Account version 17
  + FillBatch(F1, F2) 검증 성공
  → cash/positions/journal을 함께 반영
  → Account version 18

Account version 18
  + 같은 F1 재수신
  → duplicate failure, state 변화 없음
```

### 모든 held instrument를 평가한다

`MarkBatch`의 대상은 Strategy tradable universe가 아니라 Account의 held instruments다. 아래 Future 사례는
current stock/ETF path가 아니라 future extension에서 이 원칙을 유지하는 characterization이다.

```text
Future settlement price +2 point
× multiplier 250,000원
× Long 1계약
→ LifecycleBatch(variation_margin=+500,000원)
→ Account cash와 NAV 변경
```

일반 mark는 평가손익과 NAV를 갱신하고, settlement event는 product policy에 따라 variation margin을 cash로
이전하고 settlement basis를 갱신한다. 필요한 valuation input이 없으면 `INCOMPLETE`/`STALE` snapshot과
diagnostic을 만들며 조용히 정상 valuation으로 취급하지 않는다.

Current vertical slice는 stock/ETF `FillBatch`와 `MarkBatch`만 지원한다. 위 Future 예시는 Account contract의
확장 가능성을 검증하는 design characterization이며 exact lifecycle policy가 구현되기 전에는 지원 성공을
주장하지 않는다.

### Reference에서 차용하고 거부한 것

| 항목 | 출처 | 위치 | 차용 방식 | qlibx 판단 |
|---|---|---|---|---|
| cash와 Position을 함께 소유하는 Account, 보유분 bar-end mark | Qlib | `backtest/account.py` L71/L115/L225/L338 | 설계만 | 작은 연구용 aggregate 범위는 유지하되 reporting은 분리 |
| Position 매수·매도·삭제, 초과매도 거부와 현금 산술 | Qlib | `backtest/position.py` L342/L352/L384 | 코드 차용 | MIT provenance를 남기고 typed batch 산술로 이식 |
| settlement 2단계, 초기 endowment, unconstrained what-if Position | Qlib | 같은 파일 L280/L487/L493/L503 | 코드 차용 | current stock slice 밖의 항목은 해당 policy가 선택될 때만 사용 |
| Exchange 직접 mutation, BUY/SELL update 순서, Account의 metrics/history 소유 | Qlib | `backtest/exchange.py` L421, `backtest/account.py` L128/L203/L338 | 반면교사 | 계산·상태·분석 authority가 섞이므로 거부 |
| 일별 trading/holding PnL 분해 | vn.py | `PortfolioDailyResult.calculate_pnl` | 코드 차용 | attribution 시작점으로 사용하되 Position cost basis를 대신하지 않음 |
| typed AccountState ID/type/currency 검증과 instrument별 accounting | NautilusTrader | `accounting/accounts/base.pyx` L354-388, `accounting/manager.pyx` L106 | 설계만 | explicit validation 경계만 축소 적용; LGPL 코드는 복사하지 않음 |
| Account/Position/Portfolio/Cache/AccountsManager/MessageBus 전체 분리 | NautilusTrader | `portfolio/portfolio.pyx`, `accounting/manager.pyx` | 반면교사 | 다중 계좌·live lifecycle용 구조는 현재 연구 범위에 과함 |
| typed AccountChange + snapshot/feedback/commit | qlibx | §9 | 순수 창작 | actual-state authority를 한 aggregate와 한 commit 경계에 둠 |

Qlib `Account`가 cash/Position을 함께 관리하고 모든 보유 주식을 mark하는 기본 모양은 현재 product의 작은
account authority에 맞는다. Position 산술은 MIT 조건과 provenance를 지켜 이식한다.

다음 Qlib 구조는 **반면교사**로 두고 차용하지 않는다.

- `Exchange.deal_order(..., trade_account=account)`가 Account를 직접 변경하는 구조
- SELL은 Account를 먼저, BUY는 Position을 먼저 갱신하는 순서 의존적 `update_order`
- Account 안에서 portfolio metrics와 전체 historical Position 복사를 함께 관리하는 구조
- 평균단가·실현손익·native short가 없는 기존 Position을 완성된 회계 모델로 간주하는 것

vn.py `PortfolioDailyResult.calculate_pnl`의 trading PnL/holding PnL 분해는 **코드 차용**해 일별 attribution의
출발점으로 쓴다. 다만 이것은 일별 합계이므로 종목별 average cost, realized PnL와 round-trip을 대신하지 않는다.
그 path-dependent state는 Position과 Account journal이 소유한다.

NautilusTrader `accounting/accounts/base.pyx::Account.apply(AccountState)` L354-388에서 typed update의 account
ID, account type, base currency를 검증하는 경계와 `accounting/manager.pyx` L106의 instrument-specific
accounting rule을 **설계만** 차용한다. LGPL-3.0 코드는 복사하지 않는다.

NautilusTrader의 `Account + Position + Portfolio + Cache + AccountsManager + MessageBus` 분리는 **반면교사**다. 다중 계좌,
실시간 order lifecycle과 margin venue를 위한 구조다. 현재 qlibx 연구 범위에서는 actual-state authority를
찾기 어렵게 만들므로 전체 구조를 차용하지 않는다. 대신 하나의 Account가 Position까지 소유하고 Flow가 typed
change를 commit한다.

### 남은 범위 (§16)

- **G1 Memory.** Strategy memory는 Account와 별개의 committed store다. 실제 투자 상태와 전략 belief를 섞지 않는다.
- **G2 round-trip.** 별도 TradeLedger 없이 Position의 average cost/realized PnL와 Account journal로 해결한다.
- **G4 long-short.** Account aggregate만으로 real-short collateral, borrow fee와 locate가 자동 해결되지는 않는다.
  Exact accounting policy가 없는 real short는 여전히 unsupported다.

---

## 10. ⑥ evidence

### 계약

```python
# target pseudocode; current public facade is concrete LocalArtifactBackend
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

NautilusTrader `backtest/results.py`의 backtest result envelope 필드 구성은 **설계만 차용**한다. qlibx는
그 형태에 producer-independent fingerprint, dependency lineage, failure identity와 atomic publication status를
추가한다. Reference에는 이 네 계약이 함께 없으므로 확장 부분은 qlibx 순수 창작이다.

Current `LocalArtifactBackend`는 typed `QlibxModel` payload를 canonical JSON으로 저장하고 DuckDB를 catalog/index로만 사용한다. JSON은 단순하고 inspectable하지만 큰 tabular/matrix에는 비효율적이다. Parquet payload는 compatibility·atomic publication·benchmark 계약이 준비된 뒤 추가할 future backend다. Future Parquet 물리 layout은 NautilusTrader
`persistence/catalog/parquet.py`에서 **설계만 차용**한다 — 특히 parquet metadata로 시간 범위를 인덱싱해 전체를
읽지 않는 기법(L570), 중복 제거(L820), 스키마 검증(L781).

표면 API(`save`/`load`/`list_all_*`)는 vn.py `alpha/lab.py::AlphaLab`에서 **코드 차용**한다. 단 vn.py에는
fingerprint, lineage, envelope, 원자적 발행이 없으므로 그 필드는 qlibx **순수 창작**이다.

Current default local catalog index는 DuckDB다. Object store나 external tracker backend도 같은
`ArtifactPublisher`/`ArtifactLoader` contract, logical identity, atomic visibility와 conflict outcome을
만족해야 한다. External tracker run ID나 file path는 producer reference일 수 있지만 canonical artifact
identity를 대신하지 않는다.

#### Default local publication state machine

Default local backend의 durable contract는 다음 순서로 고정한다.

1. Catalog file별 OS-backed writer lock을 bounded timeout으로 획득한다. 같은 process의 thread도 같은
   path lock을 공유한다. Timeout은 raw DuckDB exception이 아니라 typed failure다.
2. DuckDB `catalog_metadata`의 schema version을 확인한다. 기존 exact unversioned schema는 v1으로 한 번
   채택하지만 unknown version이나 partial schema는 추측해 migration하지 않는다.
3. Candidate별 append-only publication event를 먼저 기록하고 payload를 `.staging`에 write + fsync한다.
4. Content-addressed final path에 payload를 atomic promote한 뒤에만 envelope, lineage와
   `CATALOG_COMMITTED` event를 한 DuckDB transaction으로 commit한다.
5. Reusable query는 `artifacts`의 committed envelope만 읽는다. Staged 또는 promoted-only payload는 audit
   event로는 관측되지만 reusable success가 아니다.
6. Recovery는 index commit 전 candidate를 성공으로 승격하지 않는다. Lock 아래에서 uncommitted staging과
   unreferenced final payload를 제거하고 `RECOVERED_ABANDONED` event를 append한다. 같은 frozen candidate는
   새 attempt로 retry한다. Commit 뒤 response 전에 process가 종료됐다면 기존 artifact를 그대로 재사용한다.

이 state machine은 한 host의 local filesystem용이다. Multi-host/NFS writer coordination, object store
consistency와 remote catalog availability는 default lock file로 지원한다고 간주하지 않고 별도 backend
contract와 fixture를 요구한다.

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

| 분석 항목 | 출처 | 위치 | 차용 방식 | qlibx 판단 |
|---|---|---|---|---|
| statistic plugin 구조 | NautilusTrader | `analysis/statistic.py`, `analyzer.py` | 설계만 | metric을 독립 plugin으로 분리 |
| 성과 지표 계산식과 파산 시 계산 거부 | vn.py | `backtesting.py` L228-380 | 코드 차용 | 검증된 식은 쓰되 350줄 단일 함수 구조는 반면교사 |
| 주문 진단, 체결률, 가격 유리도 | Qlib | `backtest/report.py::Indicator` L249-650 | 코드 차용 | Account mutation과 분리된 analysis artifact로 계산 |
| PortfolioMetrics record shape | Qlib | `backtest/report.py` L22/L153 | 코드 차용 | portable schema로 옮기고 Account 내부 책임으로 두지 않음 |

### Future work — Production outbox와 reconciliation

이 절은 MVP architecture와 acceptance 대상이 아닌 future characterization이다. 향후 production flow도 같은 evidence
boundary를 사용하되 prepared intent와 authoritative outcome을 분리하는 방향을 검토한다.

NautilusTrader `execution/reports.py`의 order/fill/position reconciliation report 분리와 `create_flat` 패턴은
**설계만 차용**한다. qlibx는 이를 external OMS result의 duplicate/stale/conflict 판정과
`ReconciledBatch` 생성에 맞게 축소한다. NautilusTrader의 MessageBus/Cache mutation은 가져오지 않는다.

```text
Strategy result
  → immutable PreparedDecision + idempotency identity
  → atomic outbox publication                    # Account/Memory advance 없음
  → external OMS acknowledgement                 # Fill 아님
  → confirmed fill/reject/cancel/account result
  → correlate + deduplicate + order-state reconcile
  → Account.commit(ReconciledBatch)               # confirmed result만
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
idempotency identity의 duplicate delivery는 두 번 적용하지 않는다. Production Account projection은 이
reconciliation이 확인한 결과만 반영하며 outbox publish나 OMS acknowledgement가 아니다. External OMS가 원천
authority이고 local Account는 Strategy/View가 읽는 reconciled projection이다.

---

## 11. 타입과 직렬화 정책

### 규칙

> **pydantic은 경계를 넘는 것에, dataclass는 경계 안에서 도는 것에.**

MVP 경계는 파일↔메모리, 사용자↔패키지와 프로세스↔프로세스다. 외부 OMS↔qlibx는 future production 경계다.

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
| `OperationError` (§7) | `Order`, `Fill`, `FillBatch`, `MarkBatch` |
| Instrument/Exchange registration | `CashFlow`, `PositionDelta`, `LifecycleBatch`, diagnostic 행 |
| `ConstraintDeclaration` | `Diagnostic` 행 |
| `ComponentRequirement` | `Position`, `Account` |
| `DatasetRegistration` | `Account`, `AccountSnapshot`, `AccountFeedback`, `AccountCommit` |
| `ExtensionContract`, `StrategyExtensionRegistration` | 통계 반환값 (JSON primitive) |
| future `PreparedDecision`, `OMSResult`, `ReconciliationResult` | |

pydantic 대상은 전부 **저빈도 + 경계**, dataclass 대상은 전부 **고빈도 + 내부**다.

`InstrumentSet[T]`도 registration boundary에서는 전체 collection을 한 번 검증하지만, execution 전에는 stable
instrument index와 typed array로 compile한다. `Order`, `Fill`, `CashFlow`를 만들 때 concrete Instrument나
cost schedule을 다시 Pydantic validation하지 않는다. 이것이 `UC-SCALE-001`의 architecture mechanism이다.

Domain DTO의 provenance도 이 절에서 함께 관리한다.

| 항목 | 출처 | 위치 | 차용 방식 | qlibx 판단 |
|---|---|---|---|---|
| Order/Trade/Position dataclass field shape | vn.py | `trader/object.py` L112-200 | 코드 차용 | 경계 안의 작은 typed DTO에 적합 |
| partial fill/reject/cancel/expire Status enum | vn.py | `trader/constant.py` L30 | future 코드 차용 후보 | intraday와 OMS reconciliation을 추가할 때만 필요 |
| requested amount / dealt amount / factor 분리 | Qlib | `backtest/decision.py` L36-152 | 코드 차용 | intent와 actual execution을 구분 |
| fixed-point Price/Quantity/Money | NautilusTrader | `model/objects.pyx` | 설계만 | 통화·수량 정밀도 계약에 사용하되 LGPL 코드는 복사하지 않음 |
| Order status가 없는 mutable Order | Qlib | `Order` dataclass | 반면교사 | Fill을 Order 내부 필드에 덮어쓰지 않고 별도 typed result로 보존 |

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
  project.py    public facade + operation별 composition root
  simulation.py public daily-simulation request/profile/result facade
  onboarding.py installed-project preview/apply/remove operation
  kernel/       clock, event, queue
  flow/         research, daily, analysis, portfolio, constraints, monitoring,
                extensions, strategy_extensions, recovery, shared failures
  context/      least-authority role views + ViewGate
  data/         registration, requirement resolution, pandas ObservationStore
  operations/   Strategy operation contracts and built-in implementations
  portfolio/    construction contracts/implementations
  execution/    instruments, executor, exchange, cost, quantity, validation
  account/      Account aggregate, committed feedback/performance/memory
  evidence/     QlibxModel artifacts, JSON payload, DuckDB catalog/index
  analysis/     typed analysis and rendering
  extensions/   exact project-local module loading
  production/   future boundary only; no current OMS/reconcile support
  config/       project/runtime schemas
  errors.py     hierarchical operation error
  models.py     QlibxModel base
```

### 의존 방향

```
kernel     → 없음
data       → domain schema
context    → kernel, data resolver
operation (strategy/portfolio/execution/analysis) → context + domain type
account    → domain 객체만
evidence   → domain 객체만
future production → evidence + domain type
flow       → context, operation, account, evidence; future production port
project    → operation별로 필요한 concrete flow/backend (public composition root)
```

**operation이 mutable Account나 raw provider를 import하지 않는 것이 핵심이다.** State/data가 필요하면
immutable AccountSnapshot 또는 resolved scoped view로 들어온다. 그래야 account commit boundary, gate와
requirement resolver를 우회할 수 없다(I2, I4, I8).

### Project onboarding lifecycle — direct operation

Project onboarding은 market-time event나 Flow가 아니다. 설치된 package resource와 user-selected project
root 사이를 조정하는 **preview-first direct operation**이다. `QlibxProject.onboard`는 target별 request를
독립된 plan으로 만들며, 한 target의 conflict가 다른 target의 plan이나 mutation을 막지 않는다.

각 target의 순서는 다음과 같다.

```text
OnboardingRequest(target, desired_state=PRESENT|ABSENT)
  -> resolve normative skill root and optional instruction file
  -> read bundled resource + prior generated manifest + current target bytes
  -> build complete-state diff and fingerprint preflight
  -> preview, or mutate only when apply=True
  -> write/remove generated files and managed block; manifest last
  -> validate entrypoint, manifest, block, and generated fingerprints
  -> return typed validation evidence + equivalent preview argv
```

`PRESENT` plan은 current bundle과 prior manifest file set의 union을 계산한다. 새 bundle에 남은 file은
create/update/unchanged로, prior manifest에만 남은 obsolete file은 remove로 분류한다. Manifest fingerprint와
현재 bytes가 다르면 user modification으로 간주해 해당 target 전체를 mutation 전에 conflict로 종료한다.
Manifest에 없는 extension file은 읽기·갱신·삭제 대상이 아니다.

`ABSENT` plan은 manifest가 fingerprint로 소유권을 입증한 generated file과 qlibx marker block만 제거한다.
`AGENTS.md`와 `CLAUDE.md`는 qlibx가 처음 만들었더라도 file 자체를 삭제하지 않는다. Instruction editing은
UTF-8 bytes에서 `<!-- qlibx-managed:start -->`와 `<!-- qlibx-managed:end -->` 사이만 교체하므로 marker 밖의
user bytes와 newline style을 보존한다. Marker가 중복되거나 한쪽만 있으면 추측하지 않고 conflict로 끝낸다.

Generated manifest schema v2는 package version, skill schema, target, generated-file fingerprints와 managed
instruction metadata를 기록한다. Reader는 기존 schema v1을 받아 update/remove할 수 있지만, 모든 manifest
path는 skill root 아래 POSIX relative path여야 한다. Absolute path, parent traversal, drive selector와 backslash는
mutation 전에 거부한다. File mutation은 같은 directory의 temporary file과 replace를 사용하고 manifest를 final
commit marker로 쓴다. Process interruption 시에는 다음 preview/apply가 actual bytes를 다시 읽어 복구 방향을
결정한다.

Apply 뒤 validation은 requested state를 새로 관찰한다. `entrypoint_ok`, `manifest_ok`,
`managed_block_ok`, `fingerprints_ok`를 분리해 반환하며, `validation_argv`는 `--apply`를 제외한 동일 preview
command다. 따라서 caller는 mutation result를 boolean 하나로 신뢰하지 않고 같은 public operation으로 다시
검증할 수 있다. 이 flow가 `GAP-ONBOARD-001`의 architecture closure다.

### 조립 — current QlibxProject와 conditional future Engine

NautilusTrader `system/kernel.py::NautilusKernel`(L101)의 명시적 composition root를 **설계만 차용**한다.
Kernel 생성 시 Clock, Cache, Portfolio, execution component를 한 곳에서 조립해 component가 전역 locator를
찾지 않게 하는 방식이다. qlibx current code도 Clock, Executor, Exchange, Account와 Evidence 구현을 operation 요청에 따라
교체해야 하므로 이 패턴이 적합하다.

```python
project = QlibxProject.open(project_root)
research = project.invoke(strategy, invocation)
daily = project.run_daily(strategy, request, account=account, memory=memory)
monitoring = project.monitor_constraints(spec)
```

Current `QlibxProject`는 public facade이자 operation별 composition root다. 각 public method가 필요한 concrete Flow, `ViewGate`, backend와 policy만 조립한다. 이는 명시적 Dependency Injection이며 Executor, Exchange와 valuation policy에는 **Strategy Pattern**을 적용한다.
`QlibxProject`/Flow가 concrete implementation을 명시적으로 조립하므로 사용자가 execution 가정을 교체해도 Account와
Strategy의 snapshot/feedback 계약은 바뀌지 않는다.

NautilusTrader의 concrete Kernel, Cache, MessageBus나 lifecycle을 복사하지 않는다. Current qlibx composition root는
PIT View, 횡단면 batch와 producer-independent artifact라는 자체 계약을 조립한다. 장수명 `Engine`은 backend 둘 이상이 공통 lifecycle과 graph를 공유할 때만 도입할 conditional future다. 지금 도입하면 조립 반복은 줄지만 global lifetime과 speculative abstraction이 늘어난다.

qlib의 `common_infra.get("trade_account")` 문자열 키 서비스 로케이터는 채택하지 않는다. 타입이
사라지고 resolved requirement, frozen invocation과 authority source를 우회하므로 채택하지 않는다.

### Reference provenance와 license 규칙

본문의 모든 차용 지점은 바로 옆에서 `코드 차용`, `설계만`, `반면교사`, `순수 창작`을 표시한다. Line
reference는 아래 vendored snapshot 기준이며 snapshot을 갱신할 때 해당 본문 설명과 characterization fixture를
같이 검증한다.

| reference | snapshot | license | 허용 범위 |
|---|---|---|---|
| Qlib | `main@79633dd` | MIT | provenance와 notice를 남긴 코드/산술 차용 가능 |
| vn.py | `master@1b78494` | MIT | provenance와 notice를 남긴 코드/DTO 차용 가능 |
| NautilusTrader | `develop@4d14b8c` | LGPL-3.0 | 설계 비교만; 코드 복사 금지 |

코드 차용 파일에는 원출처, 함수, 원저작권과 변경 내용을 남기고 repository `NOTICE`에 MIT license를 보존한다.
설계만 차용한 NautilusTrader는 동일한 source 위치와 qlibx에 맞춘 차이를 문서에 기록한다. 세 reference 모두
runtime dependency나 qlibx authority가 아니다. Backend 자체를 채택하지 않은 상세 근거는
[[why-not-qlib-as-a-backend]]와 [[why-not-nautilus-as-a-dependency]]에 있다.

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
추측하지 않고 명시적으로 실패하며, Fill과 Account mutation도 만들지 않는다.

### 13.4 실제 체결이 다음 판단으로 돌아오는 loop — UC-CLOSED-LOOP-001

```text
DECISION D1
  -> target/order
  -> EXECUTION E1: exact cost로 cash clipping, Fill 생성
  -> ACCOUNT COMMIT(FillBatch): position, cash, transaction cost 반영
  -> ACCOUNT COMMIT(MarkBatch): valuation과 NAV 갱신
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
  variation margin `+500,000`이 `LifecycleBatch`로 Account에 반영된다. 이 Account를 읽는 주식 Strategy는
  Future order를 만들 수 없지만 증가한 cash/NAV와 Future exposure를 다음 decision에서 본다. Expiry event는
  최종 정산과 포지션 종료를 유발한다.
- **UC-PERP-001:** notional 50,000인 CryptoPerpetual long 1계약에 `+1bp` funding이 적용되면 long은
  `-5` funding cash flow를 낸다. PerpetualSwap에는 expiry field와 expiry event가 없다.
- **UC-CASHFLOW-001:** transaction cost는 Fill의 비용이고, funding과 variation margin은 lifecycle cash
  flow다. 둘 다 cash/NAV에 반영되지만 같은 집계 항목으로 섞지 않으며 다음 decision에서 actual state로
  관측된다.

#### NautilusTrader perpetual funding 비교 기록

이 절은 **future design reference**이며 MVP 구현 지시가 아니다. 비교 기준은 repository의 non-authoritative
NautilusTrader snapshot `v1.231.0`, upstream commit
`4d14b8c669f8fc31f343da9ae39526729a78381f`이다(`references/nautilus_trader/UPSTREAM.md`). 공식 설명은
[Backtest Accounts and Margin](https://nautilustrader.io/docs/latest/concepts/backtesting/accounts-and-margin/)과
[FundingRateUpdate](https://raw.githubusercontent.com/nautechsystems/nautilus_trader/develop/docs/concepts/data/funding_rate_update.md),
구현 근거는 `crates/backtest/src/exchange.rs` L1020-1063, L1190-1283, L1317-1349, L1407-1429다.

NautilusTrader의 핵심은 **funding-rate observation**과 **funding payment**를 분리하는 것이다.

1. `FundingRateUpdate`는 `instrument_id`, `rate`, optional `interval`/`next_funding_ns`, `ts_event`, `ts_init`을 가진
   reference data다. Rate observation 자체는 payment가 아니다.
2. `next_funding_ns`가 있으면 그 boundary를 예약한다. 없으면 `ts_event`가 명시된 `interval` boundary와 정확히
   일치할 때만 settlement한다. Boundary를 식별할 수 없는 update는 Strategy data로 남고 cash flow를 만들지 않는다.
3. Boundary에서 해당 instrument의 open positions를 모으고 funding settlement price를 구한다. 구현은 mark price를
   우선하고, 없으면 best bid/ask midpoint를 사용한다.
4. Position별 amount는 다음 부호 계약을 사용한다.

   $$
   \text{funding amount}=\text{notional(settlement price)}\times\text{rate}\times
   \begin{cases}-1,&\text{long}\\+1,&\text{short}\end{cases}
   $$

   따라서 positive funding rate는 long의 cash/PnL을 차감하고 short에 가산한다.
5. 성공한 settlement는 `FundingSettlement` identity를 만들고 position에
   `PositionAdjusted(Funding)`을 적용하며 matching account balance를 함께 변경한다. 같은 boundary/instrument
   settlement를 중복 적용하지 않는다.

qlibx가 향후 채택할 것은 구체 class나 MessageBus가 아니라 이 책임 경계다. User가 perpetual funding capability와
funding data를 명시적으로 선택한 경우에만 operation-specific requirement가 rate와 settlement boundary를 요구하고,
Clock이 boundary event를 예약하며, pure calculation 결과를 하나의 idempotent `LifecycleBatch`로 Account에 commit한다.
Instrument를 보유했다는 사실만으로 funding data를 자동 발견하거나 cash flow를 생성하지 않는다. Funding evidence는
rate observation identity, boundary, settlement price source, notional, side, currency와 resulting cash/PnL delta를
보존한다. Transaction fee와 같은 집계로 섞지 않는다.

Dividend/distribution도 향후 같은 lifecycle cash-flow commit 경계를 재사용할 수 있지만 entitlement, ex/pay date와
withholding 계산은 별도 policy다. Merger, spin-off와 delisting의 security identity/reference transformation은 이
경계에 넣지 않고 security master/ETL에 남긴다.

같은 snapshot에서 일반 futures daily variation-margin settlement의 대응 구현은 확인되지 않았다. Matching engine의
`process_instrument_close`는 `ContractExpired` close에서만 expiration을 실행하고 end-of-session close로 일일 cash
settlement를 수행하지 않는다(`crates/execution/src/matching_engine/engine.rs` L2260-2277). 따라서 qlibx의 future
daily settlement는 NautilusTrader behavior를 그대로 차용한다고 주장하지 않고 별도의 settlement calendar, price,
cash transfer와 basis-reset policy로 설계해야 한다. 이는 source inspection에 근거한 architecture inference다.

통합 테스트와 fixture 이름에 이 use-case ID를 그대로 사용하면 PRD 요구, architecture flow, 검증
증거 사이의 추적성을 유지할 수 있다.

### 13.7 Minimal registration과 progressive gap — UC-DATA-001, UC-DATA-002, UC-ERROR-001, UC-PIT-001, UC-AGENT-001

```text
REGISTER price_source
  → user-confirmed instrument/available_at binding + logical key
  → minimal validation
  → DatasetRegistration publish                         UC-DATA-001

RUN price_reversal_strategy
  → required price binding resolves
  → Strategy runs

RUN single_name_constrained_strategy
  → required PIT benchmark-weight binding missing
  → dataset/registration은 유지
  → OperationError(strategy.run.requirements.benchmark_weight)
  → failure evidence publish                            UC-DATA-002
  → agent explains add-binding / derived-data / profile alternatives
  → user selects, package validates, new invocation retries
```

Signal analysis처럼 짧은 invocation은 실제 `analysis.run.requirements`에서만 실패하고 model, optimizer,
order stage를 만들지 않는다(`UC-ERROR-001`). Current generic resolver test는 Strategy requirement의
`horizon_end` 누락을 계산 전에 거부하지만, 이것은 forward-label Model materialization을 실행한 증거가 아니다.
`UC-PIT-001`은 real optional materialization operation과 label-horizon no-mutation acceptance가 생길 때까지
`GAP-MATERIALIZATION-PIT-001`이다. Availability 의미가 불명확하면 package는 추측하지 않고 structured gap을
내며, agent가 release timestamp나 confirmed delay-rule 후보를 설명한 뒤 user-confirmed binding만 등록한다
(`UC-AGENT-001`).

### 13.8 Strategy composition과 state — UC-SIGNAL-001, UC-SIGNAL-002, UC-ALPHA-BUDGET-001, UC-ALPHA-PATH-001, UC-ALPHA-CHILD-001, UC-ALPHA-ADAPTIVE-001, UC-ENSEMBLE-001

Direct reversal Strategy는 PIT price binding을 읽어 내부 score와 signed weights를 만들고 optional academic
profile에서 평가한다. Stored signal이나 physical construction을 요구하지 않는다(`UC-SIGNAL-001`). Value
characteristic을 materialize한 Model result는 typed artifact로 load되어 long-short Strategy와 long-only
Strategy가 producer rerun 없이 각각 소비한다(`UC-SIGNAL-002`).

Flexible-budget result는 invested 40%와 residual 60%를 그대로 저장하고 fixed consumer가 요청되면
compatibility error를 낸다(`UC-ALPHA-BUDGET-001`). Path-dependent result는 frozen Ensemble member로 소비하고
producer를 다시 실행하지 않는다. Ensemble dependency는 consumed artifact와 source Account/Memory state identity 및
cursor를 모두 보존한다. 이후 account B에서 executable target을 만들면 conversion만 account B의 current committed
state를 읽으며 member를 account B에서 재계산했다고 표시하지 않는다(`UC-ALPHA-PATH-001`).

```text
parent signed weights ─┬→ current: next-close frozen-child isolation
                       └→ gap: real PIT next-open comparison   UC-ALPHA-CHILD-001

member Strategy results → EnsembleStrategy
  → ticker netting/crossing/contribution/residual          UC-ENSEMBLE-001
  → committed fill feedback + prior memory
  → proposed member-weight update
  → flow Memory commit with feedback cursor                UC-ALPHA-ADAPTIVE-001
```

Current child regression은 parent Strategy/Model을 다시 실행하거나 parent state를 바꾸지 않지만 participation-rate만 비교한다. Next-open을 실행하지 않으므로 `UC-ALPHA-CHILD-001` closure가 아니며 `GAP-EXECUTION-CONVENTION-001`로 남는다. Adaptive update는 commit된
feedback까지만 읽으며 proposed state는 flow commit 전 authority가 아니다.

### 13.9 Portfolio와 optional constraint — UC-PORTFOLIO-001, UC-CONSTRAINT-001, UC-CONSTRAINT-002, UC-CONSTRAINT-ADJUST-001

같은 signed weight artifact를 hypothetical long-short analysis와 equity enhanced-index profile이 각각 읽는다.
각 construction operation이 direction, instrument, budget과 cost requirement를 별도로 resolve하고 새 result를
만들며 original alpha artifact를 다시 쓰지 않는다(`UC-PORTFOLIO-001`). Derivative construction은 future work다.

Constraint가 없는 signal IC/hypothetical return analysis는 compliance binding 없이 끝난다
(`UC-CONSTRAINT-001`). MVP constrained conversion은 no-short와 time-varying single-name cap을 적용한다. PIT
benchmark weight가 없으면 order/account mutation 전에 실패한다(`UC-CONSTRAINT-002`). Binding이 있으면 adjust가
original/adjusted intent와 lot-rounding residual을 만들고 validate가 eligibility를 별도로 판정한다. 남은 breach를
adjusted success로 숨기지 않는다(`UC-CONSTRAINT-ADJUST-001`).

### 13.10 User-authored ETF look-through — UC-LOOKTHROUGH-001, UC-LOOKTHROUGH-002, UC-LOOKTHROUGH-003

두 Strategy가 같은 `K200_ETF` Instrument와 Account를 사용한다고 하자. `OpaqueStrategy`는 constituent dataset을
선언하지 않는다. 이 Strategy의 View에는 ETF 구성종목이 없으며 qlibx도 exposure를 만들지 않는다. ETF는 주문과
Account에서 하나의 physical Instrument일 뿐이다.

반면 `LookthroughStrategy`는 user가 등록한 `etf_constituents` binding과 actual account state를 requirements에 넣고
둘을 consume한다. Constituent axis가 `A, B`, physical axis가 `A, K200_ETF`일 때 user code가 만든 mapping이 다음과
같다고 하자.

```text
              physical A   K200_ETF
constituent A      1.0         0.5
constituent B      0.0         0.5
```

이 Strategy가 actual AccountSnapshot에서 `A=0.2, K200_ETF=0.6, cash=0.2`를 읽으면 user code는
mapping을 정확히 한 번 적용해
`A=0.5, B=0.3`이다. Direct A 0.2와 ETF 안의 A 0.3을 합치되 ETF benchmark 0.6을 다시 더하지 않는다.
Cash 0.2를 constituent exposure에서 제외하는 것도 이 user-defined calculation의 규칙이다
(`UC-LOOKTHROUGH-001`). qlibx는 계산하지 않고 실제 dataset/account read lineage만 기록한다.

ETF 구성이 바뀐 observation S2의 `available_at`이 1월 3일이면 1월 2일 StrategyView는 S2를 노출하지 않는다.
그 시점에 available한 S1을 사용할지, stale로 실패할지, partial coverage를 허용할지는 user Strategy가 결정한다.
qlibx가 latest snapshot을 찾거나 ETF에 S1/S2를 자동 연결하지 않는다
(`UC-LOOKTHROUGH-002`).

다음 rebalance target이 `A=0.3, ETF=0.7`이어도 현재 marked actual이 `A=0.2, ETF=0.4, cash=0.4`라면
execution 전
callback에서 `LookthroughStrategy`가 actual AccountSnapshot을 다시 consume해 계산한 exposure는
`A=0.4, B=0.2`다. Target exposure `A=0.65, B=0.35`는 actual input으로 쓰지 않는다(`UC-LOOKTHROUGH-003`).
이 재계산도 자동 feedback이 아니라 user Strategy가 다음 callback에서 다시 실행한 결과다.

### 13.11 Pluggable execution과 monitoring — UC-EXEC-001, UC-EXEC-002, UC-EXEC-003

하나의 immutable DecisionIntent를 MVP daily profile이 참조한다. Current `NextSessionCloseExecutor`는 다음 eligible
trading session close의 batch event를 만들고, `DailyExecutionFlow`가 profile의 execution-price role로 가격을
resolve해 match한 뒤 원금·cost를 cash에 반영한다(`UC-EXEC-001`). 별도 `ClosePriceFill` 구현은 없다.
Next-open은 같은 경계를 사용할 target이지만 current acceptance가 아니며 `GAP-EXECUTION-CONVENTION-001`이다.
Intraday/partial-fill profile도 §6의 future characterization이다.

Daily profile은 decision 다음 eligible session과 그 close observation의 `available_at`을 검증한다. 아직
공개되지 않은 close나 기본 convention과 다른 same-session close를 요청하면 Fill 전에 실패한다. Volume
impact나 partial fill을 모델링하지 않으면 limitation artifact에 남긴다(`UC-EXEC-002`).

`QlibxProject.monitor_constraints(spec)`는 decision 유무와 무관하게 spec이 지정한 committed checkpoint와 frozen
evaluation instant의 resolved compliance view를 읽는다. Price drift로 time-varying single-name cap breach가 생기면
finding만 publish하고 order나 account mutation을 만들지 않는다(`UC-EXEC-003`). 이 standalone operation은 caller가
독립 cadence로 호출하며 current `run_daily()`의 session-close `MONITOR` callback에 자동 연결되지 않는다. Shared
scheduler가 필요하면 같은 frozen spec operation을 별도 callback으로 등록하는 optional integration으로 다룬다.

### 13.12 Artifact, failure, report와 extension — UC-ARTIFACT-001, UC-ARTIFACT-002, UC-RESEARCH-001, UC-REPORT-001, UC-MONITOR-001, UC-EXTENSION-001, UC-EXTENSION-002

External producer가 documented envelope와 payload로 signal을 publish하면 Loader가 producer class import 없이
typed Signal object를 생성하고 semantics/lineage를 검사한다(`UC-ARTIFACT-001`). Duplicate logical key나
payload/semantics mismatch는 object construction 또는 publication을 실패시키고 reusable success로 노출하지
않는다(`UC-ARTIFACT-002`).

Benchmark-weight gap으로 실패한 Strategy invocation은 failure artifact를 보존한다. Binding 보강 후 retry는 새
invocation/result를 만들고 `resolves_error_id`로 연결하며 실패를 삭제하지 않는다(`UC-RESEARCH-001`).
Analysis artifact 하나를 table/chart/machine renderer가 공유하고 metric을 renderer에서 재계산하지 않는다
(`UC-REPORT-001`). Monitoring report는 actual finding과 intended target을 섞지 않고 breach와 missing input을
구분한다(`UC-MONITOR-001`). Local neutralization transform은 package contract validation이 성공한 뒤에만
registry에 commit한다(`UC-EXTENSION-001`).

Project-local Strategy는 configured extension root 아래의 한 `.py` file과 fixed `STRATEGY_SPEC` /
zero-argument `create_strategy()` contract를 사용한다. `StrategyExtensionFlow`가 source hash, 두 fresh instance의
requirements, local `QlibxModel` JSON schema, typed `StrategyDraft`와 모든 view access evidence를 비교한다. Local
payload model은 registration-scoped `StrategyArtifactContractRegistry`에만 추가하며 built-in registry를 mutation하지
않는다. Validation success만 append-only `strategy_extension_registration:v1`을 publish한다.

Runtime facade는 caller가 지정한 exact registration artifact를 먼저 typed load하고 source hash를 import 전에 확인한
뒤 module contract를 다시 구성한다. Registration-scoped registry와 registration dependency를 기존 `ResearchFlow` /
`DailyExecutionFlow`에 주입하므로 Strategy는 backend/path/loader를 보지 않는다. Registered daily config identity에는
registration ID와 source hash가 들어간다. Source/schema drift, missing ID와 implicit latest selection은 compute와
Account/Memory mutation 전에 실패한다(`UC-EXTENSION-002`). Python module은 trusted project code이며 path confinement와
hashing은 hostile-code sandbox가 아니다.

### 13.13 Future work — Production reconcile — UC-PROD-001, UC-PROD-002

다음은 MVP acceptance 대상이 아닌 future characterization이다.

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

## 14. Implementation/readiness map

이 표는 과거 구축 순서가 아니라 2026-08-07의 current/gap을 함께 표시하는 readiness map이다. 구축 단위는 layer가 아니라 observable vertical use case다. Error와 evidence를 뒤로 미루면 초기
workflow가 failure/lineage contract 없이 굳으므로 foundation에 먼저 둔다.

| # | vertical slice | 주요 architecture | use-case evidence |
|---|---|---|---|
| 1 | Minimal registration + typed evidence | DatasetRegistration, RequirementResolver, OperationError, atomic local catalog | UC-DATA-001/002, UC-ERROR-001, UC-ARTIFACT-002, UC-RESEARCH-001 |
| 2 | PIT direct research (**current**) / Model materialization (**gap**) | Clock/View, ResolvedBinding, Direct Strategy; future materialization preflight | UC-SIGNAL-001, UC-CONSTRAINT-001; UC-PIT-001 is GAP-MATERIALIZATION-PIT-001 |
| 3 | Instrument/exact-cost batch | Instrument/Exchange registration, compiler, match_batch, diagnostics | UC-COST-001~004, UC-SCALE-001; §14.1 |
| 4 | Daily closed loop | kernel, decision/execution flow, Account/Memory, daily profile, checkpoint | UC-CLOSED-LOOP-001, UC-EXEC-002 |
| 5 | next-close frozen execution (**current**) / next-open branch (**gap**) | immutable DecisionIntent, current next-close executor, isolated Account; future real next-open | UC-EXEC-001; UC-ALPHA-CHILD-001 is GAP-EXECUTION-CONVENTION-001 |
| 6 | Stored research + bounded Strategy composition (**current with separate composition gap**) | typed load, Ensemble flow, reuse compatibility, Memory update; no current materialize operation | UC-SIGNAL-002, supported UC-ALPHA cases, UC-ENSEMBLE-001, UC-ARTIFACT-001; GAP-STRATEGY-COMPOSITION-001 remains |
| 7 | Portfolio/constraint/monitoring + user look-through fixture | construction, adjust/validate, user-declared PIT/account consumption, independent monitor | UC-PORTFOLIO-001, UC-LOOKTHROUGH-001~003, UC-CONSTRAINT-002, UC-CONSTRAINT-ADJUST-001, UC-EXEC-003; §14.2 |
| 8 | Analysis/report/extension | analysis artifact, pure renderer, transform validation, exact local Strategy registration/execution | UC-REPORT-001, UC-MONITOR-001, UC-EXTENSION-001/002 |
| 9 | Future design characterization — current build 밖 | academic listing, lifecycle cash flow, actual settlement, partial fill와 production boundary | UC-ACADEMIC-001, UC-FUTURE-001, UC-PERP-001, UC-CASHFLOW-001, UC-SETTLEMENT-001, UC-PROD-001/002 |

각 current slice는 success만 아니라 requirement gap, commit status, artifact/failure evidence와 deterministic
retry를 함께 검증한다. Daily long-only closed loop와 frozen next-close child isolation은 동작하지만, 그
isolation만으로 next-open convention 독립성을 입증하지 않는다. Materialization과 next-open gap은 위 closure
oracle이 통과할 때만 current로 이동한다. 9단계는 current support publication이 아니라 architecture를
구속하는 characterization fixture다.

3단계부터 instrument축 배열을 기본 단위로 잡는다. 단건 `match`를 먼저 만든 뒤 batch로 확장하는
경로는 택하지 않는다 — clipping 순서 중 현금 제약만이 순차이고 나머지는 elementwise이므로, 처음부터
batch로 두는 편이 단순하다.

### 14.1 체결 산술 parity 검증

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

### 14.2 User-authored ETF look-through boundary validation

7단계는 reference 구현을 runtime oracle로 사용하지 않고 자동 ETF subsystem이 없다는 경계와 user-authored fixture를
검증한다.

1. 같은 ETF와 Account를 쓰는 두 Strategy 중 constituent requirement를 선언하지 않은 Strategy에는 구성종목 data가
   노출되지 않고 exposure result도 자동 생성되지 않는다(`UC-LOOKTHROUGH-001`).
2. Constituent requirement를 선언한 user Strategy만 해당 binding을 consume하며, 2×2 matrix fixture의 `L @ p` 계산은
   user code에서 실행된다. Instrument registration이나 Account 보유가 이 계산을 trigger하지 않는다.
3. `UC-LOOKTHROUGH-002`는 `available_at`이 다른 두 observation에서 미래 row를 ViewGate가 숨기는지 확인한다.
   Available row의 stale/coverage/normalization 판단은 fixture Strategy가 수행한다.
4. Undeclared constituent binding을 Strategy가 읽으려 하면 role/requirement gate가 실패하며, package가 ETF ticker로
   binding을 추측하거나 latest dataset으로 fallback하지 않는다.
5. `UC-LOOKTHROUGH-003`은 다음 target과 현재 marked AccountSnapshot이 다를 때 user Strategy가 current actual
   quantity로 exposure를 다시 계산하는지 확인한다. qlibx는 target exposure를 Account나 feedback에 주입하지 않는다.
6. User가 result artifact를 반환한 경우 generic lineage가 실제 constituent observation과 AccountSnapshot read를
   기록한다. 별도 result를 반환하지 않은 opaque Strategy에는 ETF-specific artifact를 만들지 않는다.

---

## 15. 열린 결정

이 절에는 **아직 선택이나 구현 범위가 확정되지 않은 항목만** 둔다. 해결·기각된 판단은 §17 개정 이력에서
보존하며 열린 결정 표에 남기지 않는다.

| # | 항목 | 현재 상태와 결정에 필요한 것 |
|---|---|---|
| O5 | margined contract 확장 | **범위 미확정.** Account의 held-instrument valuation과 `LifecycleBatch` 경계는 정했지만 complete Future/Perpetual lifecycle, collateral, borrow fee와 locate의 current-support 포함 여부는 별도 결정이 필요하다 |
| O6 | pub/sub 도입 시점 | **도입 시점 미확정.** 현재는 수신자가 적고 Flow가 순서를 직접 아는 편이 단순하다. Runtime subscriber extension, 한 event의 다수 소비자 또는 전 event logging/replay가 실제 요구될 때 MessageBus 도입을 재검토한다 |

---
## 16. 설계 감사 기록

이 절은 architecture를 구체적 research scenario와 canonical PRD에 대조해 발견한 gap과 불일치를
기록한다. 1차 감사는 2026-08-03의 실행 중심 PRD와 vendored reference를, 2차 감사는 2026-08-05
`84cd113`의 progressive workflow PRD를 대상으로 했다.

기록 목적은 두 가지다. 첫째, 초안이 이미 만족한다고 **잘못 읽힐 수 있는** 부분을 명시적으로
표시한다. 둘째, 해결 순서와 선행 결정을 남긴다. 해결된 항목의 상세는 당시 문제를 설명하는 역사로
보존하되 현행 normative contract는 앞 절이 우선한다.

| # | 항목 | 성격 | 상태 |
|---|---|---|---|
| G1 | Strategy memory 부재 | 불변식 오류 + 계약 누락 | **current local implementation.** in-memory `StrategyMemoryStore`, CAS identity, flow commit와 checkpoint/recovery evidence가 있다. Durable/distributed backend는 future |
| G2 | Round-trip 회계 부재 | 차용 판단 오류 | **계약 해결.** Account Position의 cost basis/realized PnL + committed journal/feedback로 통합 |
| G3 | 학습/거래 분리 (`FIT` event) | fixed-stage 가정 | **target contract만 해결, implementation gap.** generic resolver는 있으나 optional `MATERIALIZE` operation/event와 forward-label acceptance는 없다 |
| G4 | Long-short 실행 회계 | 설계 방향 확정 | O3·O4 해결. `hypothetical_short`까지 착수 가능. `real_short` 담보·차입·locate는 별도 후속 범위 |
| G5 | `ensemble` 계약 부재 | 명세 누락 | **해결.** Ensemble은 StrategyOperation; typed member result, net/cross/residual 계약 확정 |

### G1 — Strategy memory

초안은 bounded memory를 decision input으로만 언급하고 output·store·commit 경로를 정의하지 않았다.
현행 계약은 StrategyView가 resolved prior memory와 feedback cursor를 읽고 `StrategyDraft`가 proposed
memory를 반환하는 형태다.

```python
StrategyOperation.run(view) -> StrategyDraft(weights, decision, proposed_memory)
StrategyMemoryStore.commit(proposed_memory, expected_memory_id=prior_memory_id) -> StrategyMemorySnapshot
```

`ProposedMemory`는 제안 artifact일 뿐이며 flow가 compare-and-swap identity로 commit한 뒤에만 다음
Strategy의 authority가 된다. Concurrent/stale prior identity는 commit conflict로 실패하고 proposed result는
actual state로 승격되지 않는다. Checkpoint는 committed memory ID와 feedback cursor를 함께 보존한다.

Memory나 actual feedback을 소비한 result는 state identity, account identity와 cursor를 lineage에 기록한다.
Later Strategy가 frozen result를 소비하면 이 lineage를 새 result dependency로 전파한다. Producer를 rerun하거나
consumer Account에서 recompute한 것으로 표시하지 않으며, 실제 current Account는 downstream target/order conversion에서
별도로 읽는다.

Current physical backend는 process-local in-memory `StrategyMemoryStore`다. Flow가 expected memory identity로
compare-and-swap commit하고 recovery point/checkpoint가 committed snapshot과 feedback cursor를 직렬화한다.
단순하고 deterministic하지만 process 외 durability와 distributed concurrency를 제공하지 않는다. Durable
index나 artifact-stream head는 같은 CAS/checkpoint replay contract를 증명해야 하는 future backend다.

### G2 — Round-trip 회계

초안 §9는 상태 산술을 qlib `backtest/position.py::Position`에서 이식한다고 기술했다. 이 판단은 수량과
현금 회계에는 유효하지만 **PnL 경로 의존 로직에는 불충분하다.**

Vendored source 확인 결과 `Position`이 종목별로 보유하는 필드는 `amount`, `price`, `weight` 셋이며,
`price`는 취득원가가 아니라 평가가격이다. `update_stock_price`(L401-402)가 매 bar 덮어쓰고,
`_buy_stock`(L342-350)은 추가 매수 시 평균단가를 갱신하지 않는다. 실현손익 필드와 라운드트립 개념은
존재하지 않는다.

따라서 "직전 N회 거래가 손실이었는가" 같은 조건은 Qlib Position을 그대로 복사해서는 **답할 수 없다.**
초안은 별도 TradeLedger를 제안했지만 state authority를 다시 나누므로 폐기한다. 현행 §9는 다음을 하나의
Account aggregate에 둔다.

```
Position        평균 취득단가 · 수량 · 실현손익 · settlement basis
Account journal Fill · lifecycle cash flow · position delta의 commit 순서
AccountFeedback Strategy가 cursor 이후 읽는 bounded execution 결과
```

Position이 닫히더라도 journal의 Fill과 realized PnL feedback은 사라지지 않는다. Full portable history는
Evidence에도 publish하지만 runtime commit 순서와 feedback cursor의 authority는 Account다.

nautilus `model/position.pxd`가 동일 역할을 하며(`avg_px_open`, `avg_px_close`, `realized_pnl`,
`realized_return`, `is_closed_c`, `calculate_pnl`) 설계 참고 대상이다. LGPL이므로 `설계만`으로 분류한다.

vnpy `PortfolioDailyResult`의 trading/holding PnL 분해는 일별 집계이므로 종목별 라운드트립을
대체하지 못한다.

### G3 — 학습/거래 분리

초안은 Model/FIT을 canonical pipeline의 mandatory stage로 읽었다. 현 PRD는 Direct Strategy와 stored
Model output을 동등한 선택지로 둔다. 아래는 구현 완료 설명이 아니라 **target contract**다. `FIT` global stage를 추가하는 것이 아니라 Model/transform
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
`available_at > T`인 라벨은 조회되지 않는다. Target Model component가 `horizon_end`를 요구하는데 binding이 없으면
`UC-PIT-001` OperationError로 materialization 전에 실패해야 한다. Current Strategy requirement rejection test는 이 target의 일부만 검증하므로 closure가 아니다.

따라서 derived label registration은 horizon이 availability와 일치하는지 validation해야 한다. 이를
누락하면 §17이 지적한 "보장이 write 시점으로 이동한 대가"가 정확히 여기서 실현된다.

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

가중치가 부호 있는 수치일 뿐이고 Account를 경유하지 않으므로 **현재 구조에서 이미 가능하다.**
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
EnsembleStrategyOperation.run(view) -> StrategyDraft  # Flow가 StrategyResult로 승격
```

**G4와 독립이다.** Ensemble은 weight space에서 일어나며 Account를 경유하지 않으므로 long-short
member를 결합하는 것 자체는 실행 회계와 무관하다.

확정된 계약은 다음과 같다.

- **Crossing 기록.** 두 member가 같은 종목에 반대 intent를 내면 ticker-level pre/post-net weight,
  crossing/netting amount와 member contribution을 기록한다. 이 단계의 crossing은 Exchange Fill이 아니므로
  transaction cost를 발생시키지 않는다.
- **Netting 후 normalization.** 네팅으로 줄어든 gross를 목표치로 되돌릴지는 fixed/flexible budget
  선언에 따른다. 말없이 재정규화하지 않고 gross/net residual을 evidence로 남긴다.
- **Path-dependency lineage.** Member가 state-dependent면 artifact dependency와 함께 모든
  state/account/cursor identity를 보존한다. Compatible frozen member의 producer는 rerun하지 않고, 여러 source
  identity를 fabricated single identity로 축약하지 않는다. Current Account는 downstream target/order conversion에서만
  authority로 읽는다.

### Current Strategy-composition readiness

`UC-EXTENSION-002`로 project-local Strategy validation, registration-scoped payload model, typed artifact input,
exact-ID research/daily 실행과 installed sample은 current support가 되었다. 다만
`GAP-STRATEGY-COMPOSITION-001` 전체가 닫힌 것은 아니다. `StrategyResult:v1`은 한 producer의
`state_identity`/`feedback_cursor`만 표현하고, current Ensemble special flow는 서로 다른 path-dependent state
identity를 함께 쓰는 경우 거부한다. 따라서 여러 frozen Strategy result의 모든 Account/Memory source와 cursor를
보존하는 composition은 M4 closure fixture가 통과하기 전까지 current support가 아니다. 기존 decision-intent
replay/rerun fixture도 이 acceptance oracle을 대신하지 않는다.

### 현재 남은 감사 action

```
G1 · G2 · G5      → current local contract/implementation evidence 있음; 각 제한은 본문 참조
G3                 → target contract만 있음. GAP-MATERIALIZATION-PIT-001 closure 필요
G4                 → hypothetical은 O3·O4 의미로 진행 가능. real short는 담보·차입·locate 결정 필요
execution convention → GAP-EXECUTION-CONVENTION-001 closure 필요
```

G2의 구현은 Account/Position slice에 남아 있지만 별도 state store 결정은 필요하지 않다. G4의 hypothetical
범위도 진행 가능하며, real-short accounting과 complete derivative lifecycle만 후속 product decision을 기다린다.

---

## 17. 개정 이력

### 2026-08-07 — Actual implementation sync and readiness correction

**Current authority.** Strategy returns `StrategyDraft`; Flow owns observed-lineage promotion to `StrategyResult`.
`QlibxProject` is the operation-specific composition root. Role views now expose only their structural capability,
ObservationStore currently scans registered sources with pandas, artifacts use JSON payloads with a DuckDB catalog,
and Strategy memory is an in-memory CAS store included in local recovery checkpoints.

**Design alternatives retained honestly.** A long-lived Engine, partitioned columnar source store, Parquet artifact
payload, generic operation/publisher/loader protocols and a decomposed daily state machine remain conditional future
options with the trade-offs and activation criteria in the alignment table. Same-layer flow imports remain audit debt;
a shared domain/evidence contract is extracted only when a second real consumer exists, with compatibility re-export.

**Evidence correction.** `UC-PIT-001` is excluded from current support by
`GAP-MATERIALIZATION-PIT-001`; `UC-ALPHA-CHILD-001` is excluded by
`GAP-EXECUTION-CONVENTION-001`. Existing generic horizon rejection and frozen participation-rate child tests remain
regressions but are not closure evidence. `GAP-STRATEGY-COMPOSITION-001` remains open.

### 2026-08-07 — Installed project-local Strategy lifecycle

**검증과 등록.** Configured extension root의 trusted Python file은 fixed `STRATEGY_SPEC`와 fresh-instance
`create_strategy()` contract로 검증한다. Package가 dataset/artifact/state fixture를 materialize하고 declaration,
typed draft와 실제 access evidence가 deterministic할 때만 source/schema hash를 포함한 registration artifact를
publish한다. Project-local payload model은 registration-scoped registry만 확장한다.

**Exact 실행.** Research/daily facade는 caller가 지정한 registration artifact ID만 load한다. Current source를 import
전에 hash하고 module contract를 다시 비교하며 registration-scoped payload contract와 registration lineage를 기존
Flow에 주입한다. Source drift, schema drift, missing ID와 latest-compatible 추측은 compute/authority mutation 전에
실패한다. Bundled `strategy-extension-v1` sample은 installed public imports로 validation, registration과 exact 실행을
재현한다(`UC-EXTENSION-002`).

**남은 composition gap.** 이 lifecycle은 M3 범위만 닫는다. 여러 path-dependent `StrategyResult` source의 모든
Account/Memory identity와 cursor를 Ensemble result에 보존하는 schema/compatibility 변경은
`GAP-STRATEGY-COMPOSITION-001`의 남은 M4 범위다.

### 2026-08-07 — Strategy-first composition contract 정정

**Path-dependent reuse.** Account 또는 Memory를 소비한 Strategy result는 다른 Strategy/Ensemble의 frozen typed
input으로 재사용한다. Producer rerun이나 cross-account replay/rerun interview를 요구하지 않고, 실제로 소비한
artifact와 모든 source state/cursor lineage를 새 result에 전파한다. Current Account는 downstream physical
target/order conversion에서만 authority다.

**Extension lifecycle.** Project-local Strategy를 alpha logic의 primary extension point로 두고 Model/materialization은
선택된 component가 reusable intermediate를 요구할 때만 사용한다. Flow가 typed artifact를 resolve·load하고 bounded
projection을 Strategy view에 주입한다. 이 revision 당시 build에는 full lifecycle이 없어
`GAP-STRATEGY-COMPOSITION-001`로 명시했으며, 위 M3 revision이 local validation/execution 부분을 닫았다.

**Monitoring clock.** Daily runtime의 session-close `MONITOR`는 performance/observation callback이며 constraint
evaluation이 아니다. Constraint monitoring은 committed checkpoint와 frozen evaluation instant를 받는 standalone
public operation이다. Optional scheduler integration은 가능하지만 `run_daily()`에 자동 삽입하지 않는다.

### 2026-08-07 — public sample 선택과 constraint monitoring 노출

**독립 monitoring 경로.** 설치 project의 공인 mutable Account 복원 경로는
`SimulationCheckpoint → AccountCheckpoint → Account.from_checkpoint`다. Public facade는 frozen
`ConstraintMonitoringSpec`이 가리키는 checkpoint artifact를 typed contract로 읽고 Account 무결성을
검증한 뒤 기존 `MonitoringFlow`를 호출한다. Checkpoint의 version, journal, event identity 또는 `as_of`
관계가 손상되면 raw `ValueError` 대신 `MONITORING_ACCOUNT_CHECKPOINT_INVALID`를 반환한다.

**단일 evaluation instant.** `evaluation_time`은 wall clock에서 읽지 않고 frozen spec에 저장한다. 같은
instant가 Account mark freshness와 benchmark의 PIT cutoff를 동시에 결정하므로 동일 spec과 immutable
checkpoint의 반복 실행은 동일 monitoring artifact identity를 반환한다. Held position의 mark가 이 instant보다
이르면 `ACCOUNT_VALUATION_STALE`이며, facade는 mark를 보정하거나 최신 가격을 추측하지 않는다.

**Bundled sample 선택.** 이 revision에서 `project sample --sample-id`는 세 bundled sample identity를 argparse
choice로 공개하고 기존 basic sample을 default로 유지했다. 위 M3 revision은 별도 closure evidence와 함께 네 번째
`strategy-extension-v1` sample을 추가했으며 daily flow의 자동 constraint monitoring 단계는 여전히 추가하지 않는다.

### 2026-08-07 — 선언된 source timezone과 원자적 dataset 등록

**Timestamp 의미.** Naive availability 또는 observation timestamp는 더 이상 UTC로 추정하지 않는다.
Dataset registration이 user-confirmed IANA `source_timezone`을 보존하고, data layer가 localize한 뒤 UTC
instant로 변환한다. 이미 offset이 있는 source에 사용되지 않는 timezone을 선언하거나 혼합·DST 경계로
정확한 instant를 만들 수 없으면 mutation 전에 typed failure를 반환한다. 이는
`ConfirmedDelayRule.user_confirmed`와 같은 명시적 의미 선언이며 schema fingerprint는 원본 dtype을 계속
나타낸다.

**Session calendar.** Session query는 UTC calendar date를 암묵적으로 사용하지 않고 caller가 선언한
`session_timezone`으로 observation instant를 변환한 뒤 local date를 비교한다. `StrategyView.session`은
필수 keyword로 이 달력을 받고, signal analysis는 `return_session_timezone`을 frozen request에 보존한다.
Daily execution은 `DailyExecutionProfile.session_timezone`을 date 계산과 조회에 동일하게 사용한다.

**Identity와 migration.** `source_timezone`은 registration identity에 포함된다. Upgrade 전 registration은
읽을 수 있지만 naive source를 다시 query하려면 명시적 timezone으로 재등록해야 하고, 기존 identity와의
충돌 또는 이전 run resume은 각각 `REGISTRATION_IDENTITY_CONFLICT`와 `RESUME_BRANCH_REQUIRED`로 드러난다.
Silent identity migration은 하지 않는다.

**Append-only publication.** Registry publication은 destination을 교체할 수 있는 `os.rename` 대신 같은
filesystem의 atomic hard-link create-if-absent를 사용한다. Hard link를 지원하지 않는 filesystem에서는
부분 JSON을 노출하는 직접쓰기 fallback 없이 `REGISTRY_PUBLICATION_FAILED`로 종료한다.

### 2026-08-06 — 최종 package name 확정과 user-owned ETF look-through 설계

**Package name.** 현재 package/import/CLI는 구축이 끝날 때까지 `qlibx`를 유지하고, 마지막 migration
단계에서만 확정된 target `vqapr`로 전환한다. O12는 열린 결정에서 제거했다.

**ETF look-through.** PRD `UC-LOOKTHROUGH-001`~`003`에 맞춰 qlibx core는 ETF를 physical Instrument로만 취급하고,
look-through는 user Strategy가 constituent dataset과 actual AccountSnapshot을 명시적으로 선언·consume해 계산하는
behavior로 정정했다. Package-owned mapping resolver, special snapshot/result type, coverage profile과 자동 feedback은
두지 않는다. qlibx는 PIT ViewGate, actual-state 접근과 generic lineage만 제공한다.

**Reference 판단.** `references/qlib-integration-codex`의 matrix multiplication, exact axis, actual-holding
turnover, non-tradable freeze, independent validation과 stored attribution 검사는 차용한다. Static config mapping,
identity-covariance fallback, 의미를 바꾸는 사후 normalization, optimizer target을 realized exposure로 부르는
동작과 Qlib lifecycle 결합은 거부한다.

### 2026-08-06 — execution 시점 명확화와 출처 설명의 본문 통합

**체결 시점.** 첫 vertical slice의 모호한 `CloseFill` 표현을
`NextSessionCloseExecutor + ClosePriceFill` 조합으로 명확히 했다. Decision이 끝난 **다음 eligible trading
session의 close**에 체결하며,
당일 종가 체결과 calendar day 기준 이튿날 체결을 뜻하지 않는다. 이는 intraday path, market impact와
부분체결을 생략한 가장 단순하고 낙관적인 가정이다. Intraday Executor는 같은 immutable DecisionIntent를
여러 ExecutionEvent로 나누고, 각 event마다 최신 AccountSnapshot을 읽어 같은 `Account.commit()` 경계를
통과한다.

**출처 설명.** 별도 차용 출처 표를 제거하고 Clock, Flow/Executor, View, Operation, Account, Evidence,
DTO와 Engine 조립의 해당 본문에 출처·위치·차용 수준·비차용 이유를 함께 기록한다. 특히 명시적인
`add_exchange` 뒤 `add_instrument` 조립 순서는 NautilusTrader `BacktestEngine.add_venue`와
`add_instrument`의 build-time validation에서 설계만 차용했음을 §8에 기록했다. 계약과 근거가 서로 다른
절에서 독립적으로 변해 sync가 깨지는 것을 막기 위한 변경이다.

**Package name.** 현재 구축, import, CLI, artifact schema와 generated skill path는 `qlibx`를 사용한다.
최종 rename target은 `vqapr`로 확정했지만 실행은 마지막 migration 단계까지 보류한다. 그 단계에서 PyPI,
import/CLI/document path, artifact/schema identity, installed skill과 migration guide를 하나의 versioned change로
전환한다. 따라서 package name은 더 이상 열린 결정이 아니며 O12를 제거했다.

### 2026-08-06 — Account authority 통합과 read/write 분리

**계기.** Ledger가 actual-state authority이면서 AccountSnapshot을 만들고, 쓰기 port인 FillSink가 cash와
positions까지 읽으며, round-trip을 위해 다시 TradeLedger를 추가하려 했다. 같은 계좌 상태를 여러 객체가
나누어 소유해 "누가 commit하는가"가 불명확해지는 구조였다.

**결정.** PRD의 ledger는 actual result commit 역할명으로 해석하고 concrete state object는 하나의 Account로
통합한다. Account는 cash, sparse Position, marks, Position cost basis/realized PnL, committed journal,
feedback cursor와 version을 소유한다. 읽기는 immutable `AccountSnapshot`/`AccountFeedback`, 쓰기는 Flow가
호출하는 `Account.commit(AccountChange, expected_version)`으로 분리한다. FillSink와 별도 TradeLedger는
폐기한다.

**Instrument 범위.** Registered, held, Strategy tradable, valuation instrument 집합을 분리한다. Strategy가
주식만 거래해도 Account가 보유한 Future는 valuation set에 남고 exact settlement policy에 따라 cash/NAV에
반영된다. 다만 complete Future lifecycle은 current support가 아니라 PRD future characterization이다.

**차용 판단.** Qlib에서 cash/Position을 함께 소유하는 연구용 Account shape와 bar-end mark를 배우되 Exchange
직접 mutation, 순서 의존적 update와 metrics/history 혼합은 거부한다. NautilusTrader에서 typed AccountState의
identity/currency 검증과 instrument-specific accounting 경계를 설계만 차용하되 Account/Position/Portfolio/
Cache/Manager 전체 분리는 현재 범위에 과해 채택하지 않는다.

**패턴.** Callback/Clock은 IoC, Engine 조립은 Dependency Injection, Executor/Exchange/valuation 교체는
Strategy Pattern, 계산과 commit 분리는 Functional Core/Imperative Shell, Account는 Aggregate Root,
snapshot/feedback 대 commit은 Command-Query Separation으로 명시한다. 별도 read database나 event-only state
rebuild를 도입하지 않으므로 full CQRS/Event Sourcing이라고 부르지 않는다.

### 2026-08-03 — 정보 전달 모델 교체 (초안 §7 폐기)

**변경.** Event마다 `gate`가 snapshot(`Context`)을 조립해 judge에 넘기던 구조를, **clock에 묶인
읽기 전용 조회 창구(view)** 를 judge가 들고 필요한 시점에 조회하는 구조로 교체했다.

**계기.** nautilus 소스를 다시 읽는 과정에서 초안의 사실관계 오류가 확인되었다. 당시 별도 차용
매핑 절은 "nautilus에는 Context 객체가 없어 PIT가 구조로 강제되지 않는다"고 기술했으나, nautilus는
다른 메커니즘으로 같은 보장을 제공한다. 현행 출처와 판단은 §7 본문에 통합했다.

```
core/data.pyx  L30  ts_event   그 사건이 발생한 시각
core/data.pyx  L42  ts_init    그 데이터가 시스템에 들어온 시각
backtest/engine.pyx L903       sorted(data, key=lambda x: x.ts_init)
model/data.pyx L1496           is_revision
```

Stream이 `ts_event`가 아니라 **`ts_init` 오름차순**으로 정렬된다는 점이 핵심이다. qlibx가 채택하는 부분은
PRD §4.4의 `available_at <= evaluation_time` 보장이다. NautilusTrader의 `ts_event`는 비교 근거로 기록하지만
qlibx 최초 registration의 필수 field로 채택하지 않는다. 미래를 차단하는 것이 아니라 **아직 stream에서 나오지
않았으므로 존재하지 않는다.**

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
§8 judge 계약 첫 인자를 정정했다. 당시 별도 매핑표의 내용은 현행 §7 View reference 설명에 흡수했다.

**남는 순수 창작 영역.** 시간 경계 메커니즘은 nautilus에서 차용하지만 **접근 축**은 여전히 창작이다. Reference
세 곳은 instrument별 시계열이 기본 단위이고 메모리 상주 방식이라, decision time 횡단면을 컬럼
저장소 질의로 제공하는 부분에는 대응물이 없다.

### 2026-08-03 — 설계 감사

네 개의 research scenario 대조로 다섯 개 gap 확인. I4가 PRD §9.1·§9.10과 모순되어 개정. 상세는
현행 §16.

### 2026-08-03 — execution backend 결정 및 batch 단위 확정

**결정.** nautilus_trader를 execution backend dependency로 채택하지 않는다. 설계는 선별 차용하되
engine은 qlibx가 구현한다. 근거와 재검토 조건은 [[why-not-nautilus-as-a-dependency]]에 있다.

**핵심 사유.** 기본 작업 단위가 다르다. nautilus는 instrument별 event, qlibx는 decision-time
횡단면이다. 3000종목 × 5000일이면 1500만 event 대 5000 batch step이고, 이는 최적화로 좁힐 수 있는
차이가 아니다. 여기에 PRD §8~§10·§12에 대응물이 없다는 점, v1→v2 전환 진행 중이라는 점,
3000종목 규모가 미검증이라는 점이 더해진다.

**구조 변경.** Executor가 "일정표"에서 **횡단면 batch 실행기**로 바뀐다. `exchange.match(order)`는
`exchange.match_batch(orders)`가 되고, 당시에는 `FillSink.apply_batch`가 commit을 담당했다. 현행 §14 구축 순서는
2단계부터 instrument축 배열을 기본 단위로 잡았다. FillSink 결정은 2026-08-06 Account commit으로 폐기되었다.

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
미선언은 `long_only`로 취급하고 unknown을 shortable로 추측하지 않는다. §16 G4가 `hypothetical_short`
범위까지 착수 가능해졌다.

matched capitalization은 qlib의 long-only Position 제약을 우회하기 위한 장치였다. Engine 소유권이
넘어오면서 전제가 사라졌고, 우회로 대신 선언을 요구하는 형태로 교체했다. PRD §4.2, §5.1, §5.7,
§11.4, §11.6, §12.3, §15 P8, §16.2, §17.2가 함께 갱신되었다.

**perp·담보 보류 (O5).** 현재 범위 밖이다. 도입 시 §7.12의 선언 항목을 늘리는 형태여야 하며 engine
구조 변경을 요구해서는 안 된다는 제약만 남긴다.

**polars 기각 (O2).** 횡단면 batch 접근에서 이득이 크지 않다고 판단했다. 저장 Parquet / 질의 duckdb /
계산·경계 pandas로 간다. 대가는 vnpy signal 연산 30여 개가 복사가 아니라 pandas 재작성이 된다는 것이다.
현행은 §8 Operation provenance에서 코드 차용과 재작성 경계를 함께 설명한다.

**FillConvention 분리.** Executor가 정하는 것은 일정이고 체결가 규약은 별도 축이다. 둘을 묶으면 종가
체결을 시가 체결로 바꾸는 데 executor를 새로 써야 한다. 당시 `CloseFill`이라고 적은 기본값은
2026-08-06 `NextSessionCloseExecutor + ClosePriceFill` 조합으로 명확히 했고, **낙관적 가정임을 명시**하며 사용된 convention identity를
result에 기록한다. Convention 교체는 alpha부터 Account까지 어느 계약에도 영향을 주지 않는다.

**pub/sub 보류 근거 확정 (O6).** 한 event의 수신자가 둘뿐이고 이름을 안다. 전환 비용이 발행 지점 1곳
교체에 그치고 operation·Account 계약이 불변이므로 미룰 수 있다. 반대로 `available_at`, clock 분리,
`(결과, 진단)` 반환, 시간 축 순차는 나중에 추가하면 정보를 잃으므로 미루지 않았다. 판단 기준은
**"나중에 추가하면 정보를 잃는가"** 이다.

### 2026-08-04 — PRD use-case traceability와 Instrument/Exchange 책임 정정

**PRD 경계 정정.** PRD는 instrument capability dictionary, cost schedule 선언 형식이나 class hierarchy를
강제하지 않는다. 대신 상품·side·유효일 비용, 비용을 포함한 cash clipping, exact-rule failure,
closed-loop feedback과 3,000종목 batch를 stable use-case ID로 정의한다. Academic instrument와 margined
contract 사례는 현재 acceptance가 아니라 미래 design characterization으로 구분한다.

**책임 배치.** Instrument는 구체 Pydantic 타입으로 정적 경제 계약을 표현한다. Exchange는 listing,
tradability, transaction-cost policy와 lifecycle event specification을 소유한다. Clock이 event를 순서대로
발행하고 Flow가 Fill 또는 lifecycle cash flow를 Account에 commit한다. 다음 decision은 이 commit 이후의
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
G5의 architecture gap을 해결했고 당시에는 G2 round-trip 회계와 G4 real-short accounting을 남겨 두었다.
G2의 state 경계는 2026-08-06 Account/Position 회계로 해결되었다.

### 2026-08-06 — MVP execution·time·lifecycle 범위 축소

**Superseding scope decision.** 이 결정은 위 2026-08-05 기록 중 intraday/partial-fill validation과 production
reconciliation을 current scope로 둔 부분을 대체한다. MVP는 eligible order 전량 체결, 주식·ETF cash 즉시 결제와
local simulation Account만 지원한다. Pending/cancel/reject, multiple in-flight decision, external OMS authority와
reconciliation은 future work다.

**Data time.** 최초 registration과 PIT gate의 유일한 필수 시점은 `available_at`이다. Event/effective time은
전역 schema가 아니며 미래 lifecycle operation처럼 실제로 필요한 operation만 점진적으로 요구한다. ETF constituent
ViewGate도 `available_at`만 강제하고 available observation의 선택과 해석은 user Strategy에 남긴다.

**Constraint.** MVP hard constraint는 no-short와
`single-name weight <= max(10%, index constituent weight)`뿐이다. Benchmark weight는 decision time에 available한
time-varying data다. Missing weight를 0으로 추정하지 않는다. Sector와 그 밖의 constraint는 future work다.

**Lifecycle boundary.** Dividend/distribution, futures settlement와 perpetual funding은 current implementation이
아닌 future `LifecycleBatch` 확장이다. Merger, spin-off와 delisting의 원천 해석·instrument/reference 변환은
security master/ETL 책임이다. Stock/ETF의 실제 settlement cycle도 future work다.

**NautilusTrader funding reference.** Future perpetual funding 설계는 §13.6의 비교 기록을 따른다. 핵심은
`FundingRateUpdate`가 payment가 아니며 settlement boundary가 식별될 때만 open position notional과 side로 cash/PnL을
계산해 idempotent event로 반영한다는 점이다. qlibx도 향후 instrument 보유만으로 data를 자동 발견하거나 funding을
발생시키지 않는다.
