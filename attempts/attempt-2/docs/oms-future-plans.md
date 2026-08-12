# OMS 미래 계획

상태: 탐색 단계의 계획이며 정본 제품 요구사항이 아님

작업명: `qliby`(임시 명칭이며 변경될 가능성이 높음)

qlibx의 정본 경계: [`qlibx-prd.md`](qlibx-prd.md), 특히 §2.4와 §13

## 1. 목적

이 문서는 qlibx의 production decision을 받아 실제 증권사를 통해 집행하는 미래 실거래 시스템을 검토한다.
`qliby`는 작업명일 뿐이다. 이 시스템은 Qlib에 의존하지 않을 수 있으며, Qlib 의존성이 실질적으로
존재하지 않는다면 최종 이름도 Qlib 의존성을 암시해서는 안 된다.

의도하는 제품 경계는 다음과 같다.

```text
qlibx
  일별 batch 연구와 position decision
  -> durable broker-neutral target과 proposed strategy memory

미래 OMS(작업명: qliby)
  broker/account 검증
  + qlibx target의 장중 집행
  + overnight position을 의도하지 않는 선택적 intraday alpha
  -> confirmed fill, 귀속된 결과와 account snapshot

qlibx
  검증 및 reconciliation
  -> authoritative next-batch strategy memory와 completed checkpoint
```

미래 OMS는 실제 매매와의 연결을 소유한다. 단순한 file mover나 broker SDK wrapper가 아니다. 실시간 시장과
계좌 상태를 지속적으로 관찰하고, 장중 주문을 운영하며, 위험을 통제하고, 장애에서 복구하고, 감사 가능한
결과를 발행해야 한다.

## 2. 핵심 설계 검토

### 2.1 Qlib 재사용은 요구사항이 아니다

OMS에서도 Qlib을 사용하는 것은 구현 가설이지 제품 결정이 아니다. qlibx에는 연구, backtesting과 일별
decision lifecycle이 필요하므로 Qlib이 유용하다. 그러나 이것이 Qlib이 실시간 market data 처리, broker
order state, 저지연 event 처리, retry, cancel, crash recovery 또는 운영 위험 통제에 적합한 kernel이라는
증거는 아니다.

선택 원칙은 다음과 같아야 한다.

> 구체적인 OMS 책임을 선택한 live-trading stack보다 Qlib이 더 안전하고 완전하게 구현할 수 있다는
> 증거가 있을 때만 Qlib을 재사용한다.

Code reuse, 이름의 연속성 또는 익숙함은 충분한 채택 근거가 아니다. 반대로 요구 의미를 충족하는 유지보수
중인 library가 있다면 자체 order state machine, broker abstraction 또는 event engine을 만들어서도 안 된다.

### 2.2 Target 집행과 alpha의 결합은 state 귀속 문제를 만든다

하나의 OMS가 경제적으로 다른 두 활동을 수행할 예정이다.

1. qlibx의 일별 target을 최대한 근접하게 집행한다.
2. overnight position을 남기지 않는 자체 intraday alpha 전략을 수행한다.

두 활동이 같은 broker account에서 같은 종목을 거래하면 최종 account balance만으로는 어떤 전략이 각
holding, 현금 이동, 비용 또는 PnL을 만들었는지 알 수 없다. 명시적 귀속이 없으면 qlibx가 intraday
strategy에 오염된 position이나 cash state를 소비할 수 있다.

따라서 OMS에는 최소한 다음이 필요하다.

- 안정적인 `strategy_id`, `sleeve_id`, `decision_id`, `order_id`와 broker order identity
- replace, cancel, reject와 partial fill 이후에도 유지되는 order/fill 귀속
- sleeve별 독립적인 가상 position, cash, cost와 PnL ledger
- 모든 가상 ledger와 하나의 broker-authoritative account 사이의 reconciliation
- 반대 방향 order, internal netting과 crossing에 대한 명시적 policy
- flatten에 실패한 intraday-alpha residual position에 대한 장 종료 규칙

이는 reporting 개선 사항이 아니라 필수 전제조건이다.

### 2.3 Cash budget은 통제 수단이지 별도 broker cash가 아니다

다음 budget은 개념적으로 분리된다.

- **qlibx target sleeve:** 일별 batch target이 내포하거나 이를 위해 확보한 cash
- **OMS operations reserve:** fee, tax, settlement timing, order replacement와 운영 buffer
- **intraday alpha sleeve:** OMS-local alpha에 별도로 한정한 risk capital

Broker가 실제로 분리된 subaccount를 제공하지 않는다면 이들은 대체 가능한 account cash 위의 가상
allocation이다. 합계는 broker cash와 reconcile되어야 하며, 동시 order가 buying power를 두고 경쟁할 때의
우선순위를 OMS가 정의해야 한다. Broker reject 또는 의도하지 않은 borrowing을 막지 못하는 budget ledger는
risk control이 아니다.

### 2.4 OMS가 qlibx authoritative memory를 직접 advance해서는 안 된다

현재 qlibx PRD에 따르면 prepared decision은 authoritative strategy memory를 advance하지 않는다. 외부
OMS가 confirmed execution result와 account snapshot을 발행하고, qlibx가 이를 검증하고 reconcile한 뒤
completed checkpoint를 commit한다.

따라서 “OMS가 다음 batch를 위한 state를 쓴다”는 표현은 다음을 의미해야 한다.

- OMS는 immutable하고 qlibx가 소비할 수 있는 **execution result와 state input**을 쓴다.
- Reconciliation 후 **next-batch strategy memory**를 commit하는 authority는 qlibx에 남는다.

OMS가 qlibx memory를 직접 덮어쓰게 하면 기존 commit boundary를 우회하며 replay, duplicate delivery와
state mismatch recovery가 모호해진다. 이 ownership을 바꾸려면 향후 PRD에서 명시적으로 결정해야 한다.

## 3. 확정된 책임

### 3.1 qlibx

- 전략 연구, backtesting과 production daily batch decision을 수행한다.
- 마지막 completed checkpoint에서 실제 confirmed state를 읽는다.
- Durable local storage를 통해 immutable하고 broker-neutral한 target을 발행한다.
- Prepare 시점에는 proposed strategy memory를 commit하지 않고 보존한다.
- OMS result를 소비하고 identity를 검증한 뒤 account snapshot과 reconcile한다.
- Reconciliation에 성공한 뒤에만 authoritative next-batch memory를 commit한다.

### 3.2 미래 OMS

- Broker와 실시간 market-data source에 연결한다.
- 인증하고 session을 관리하며 broker/account 상태를 관찰한다.
- Broker-authoritative pre-trade account와 qlibx decision이 예상한 state를 비교한다.
- 차이가 명시적 tolerance를 초과하면 execution을 reject하거나 quarantine한다.
- 실제 current holding을 사용해 qlibx target을 executable child order로 변환한다.
- 한정된 policy 안에서 order를 slice, pace, submit, amend, cancel, retry한다.
- Broker acknowledgement, reject, partial fill, fee, tax와 remaining quantity를 추적한다.
- 별도 승인된 budget과 risk envelope 안에서만 OMS-local intraday alpha를 수행한다.
- Alpha sleeve의 no-overnight intention을 강제하고 residual이 있으면 예외로 보고한다.
- Pre-trade 및 continuous risk control, kill switch와 session 종료 통제를 적용한다.
- Append-only 운영 audit trail을 보존하고 restart 후 안전하게 복구한다.
- Broker-confirmed execution outcome과 account snapshot만 qlibx에 발행한다.

### 3.3 Broker와 market-data provider

- Account balance, position, order status와 fill의 authority로 남는다.
- Duplicate, late, out-of-order event를 해결하는 데 필요한 timestamp와 identifier를 제공한다.
- Rate limit, session rule, order type과 correction behavior 같은 운영 제약을 정의한다.

## 4. 제안 runtime 흐름

```text
1. 실행 가능한 qlibx PreparedDecision 하나를 읽는다
2. broker account, position, open order와 session status를 조회한다
3. expected-state fingerprint와 broker-authoritative state를 비교한다
4. reconciliation policy에 따라 block, quarantine 또는 계속한다
5. sleeve budget을 할당하고 운영 cash를 reserve한다
6. 이전 target이 아니라 actual holding에서 target-execution delta를 계산한다
7. target executor와, 별도로 활성화된 경우 intraday-alpha executor를 실행한다
8. 모든 intent를 공통 pre-trade risk 및 order management로 전달한다
9. command, acknowledgement, fill, reject, cancel과 risk event를 저장한다
10. 설정된 deadline에 신규 alpha risk를 중단하고 alpha flatten을 시도한다
11. expiry/close policy에 따라 남은 qlibx target quantity를 finalize한다
12. 최종 broker-confirmed account와 open-order snapshot을 확보한다
13. broker truth와 sleeve별 ledger를 reconcile한다
14. immutable OMSResult와 qlibx next-batch state input을 발행한다
15. qlibx가 검증, reconciliation, CompletedCheckpoint commit을 수행한다
```

“장중 최대한 집행”은 실행 가능한 policy가 아니다. 최소한 decision 또는 OMS policy에 validity window,
participation/price limit, target tolerance, retry bound, close behavior, incomplete-order disposition과 kill
switch 발동 조건을 정의해야 한다.

## 5. 필요한 state와 artifact model

### 5.1 State의 권한 주체

시스템은 서로 다른 네 종류의 state를 분리해야 한다.

| State | Authority | 목적 |
|---|---|---|
| Broker account/order state | Broker-confirmed snapshot과 event | 실제 holding, cash, order와 fill |
| OMS operational state | Durable OMS event log와 recovery store | In-flight command, retry, risk와 restart |
| Sleeve attribution state | Broker truth와 reconcile한 OMS ledger | qlibx target, operations reserve와 alpha 분리 |
| qlibx strategy memory | qlibx completed checkpoint | 다음 daily batch decision의 input |

In-memory strategy object, requested order와 broker acknowledgement는 confirmed fill/account state를 대체할
수 없다.

### 5.2 qlibx에서 OMS로 전달하는 input

기존 `PreparedDecision` 방향을 교체하지 않고 구체화해야 한다. 다음 항목을 직접 포함하거나 참조해야 한다.

- Schema version, decision identity와 idempotency identity
- Portfolio/account, strategy와 parent-checkpoint identity
- Decision time, observation cutoff와 validity window
- 예상 account-state fingerprint
- 단위가 명시된 broker-neutral target position 또는 order intent
- Target tolerance와 execution/risk boundary
- 제안 strategy memory reference
- 요구되는 OMS result schema

정확한 target semantic은 별도의 qlibx contract decision으로 남는다. Target weight, target physical quantity와
explicit order intent는 서로 바꿔 쓸 수 없다.

### 5.3 OMS 영속 event 기록

OMS에는 restart 가능한 다음 기록이 필요하다.

- 수신한 decision과 claim status
- Decision에 사용한 market-data 및 account snapshot reference
- Parent/child order command와 broker acknowledgement
- Replace, cancel, reject, expiry와 late event
- Timestamp가 있는 fill, fee와 tax
- Strategy/sleeve 귀속
- Pre-trade 및 continuous risk decision
- Operator action과 kill-switch transition
- Recovery generation과 replay position

### 5.4 OMS에서 qlibx로 전달하는 output

Immutable result에는 다음이 포함되어야 한다.

- Decision과 idempotency identity
- `complete`, `partial`, `rejected`, `expired`, `quarantined` 등의 terminal status
- 종목별 requested, submitted, filled, remaining quantity
- 실제 order, fill, price, fee, tax, time과 reason code
- qlibx sleeve의 realized position과 cash attribution
- 별도로 식별한 intraday-alpha 및 operations-reserve effect
- Residual alpha exposure와 exception status
- 최종 broker account, holding, cash와 open-order snapshot reference
- Reconciliation result와 unresolved difference
- 영속 event-log/content fingerprint

최종 broker account는 모든 sleeve ledger와 reconcile되어야 한다. 귀속되지 않은 차이를 단순히 버리는 result는
불완전하다.

## 6. 위험 및 운영 통제

최소 production control은 다음과 같다.

- Order submit 전 account, market session과 data freshness gate
- 최대 order notional, position, turnover, participation, price deviation과 daily loss
- Sleeve별 및 account-level cash/risk limit
- Stale, duplicate, out-of-order event 처리
- Broker rate limit와 disconnect behavior
- Broker가 지원하는 경우 cancel-on-disconnect policy
- Manual 및 automatic kill switch
- Intraday alpha의 no-new-risk 및 flattening deadline
- Suspension, price limit, auction과 market close의 명시적 처리
- Duplicate order 없는 restart/replay
- Clock synchronization과 exchange-calendar 처리
- Immutable operator audit log, metric과 alert delivery
- 동일한 order-state semantic을 사용하는 paper, simulation, shadow와 limited-live mode

“No overnight alpha”는 market-close order를 예약하는 것만으로 보장되지 않는다. Suspension, limit move,
broker outage와 rejected order는 residual exposure를 남길 수 있다. 제품 contract는 **flatten 의도**와
**confirmed flat state**를 구분하고 escalation과 next-session handling을 정의해야 한다.

## 7. Intraday alpha의 미결정 제품 질문

Alpha strategy, research owner 또는 deployment process는 아직 선택되지 않았다. OMS infrastructure가
암묵적으로 research authority가 되어서는 안 된다.

Live alpha를 활성화하기 전에 다음을 결정해야 한다.

1. Alpha research, approval, monitoring과 retirement를 누가 소유하는가?
2. Strategy가 어떤 data를 사용할 수 있으며 latency, license와 timestamp guarantee는 무엇인가?
3. Research를 live execution과 같은 framework에서 수행하는가, 아니면 안정적인 signal/strategy contract로
   내보내는가?
4. Simulation, replay, paper trading과 production parity를 어떻게 입증하는가?
5. Alpha budget, capacity, turnover, cost, loss와 residual-position limit은 무엇인가?
6. Alpha가 qlibx target sleeve와 같은 종목을 거래할 수 있는가?
7. 반대 방향 sleeve order를 broker에 보내기 전에 netting하는가? 그렇다면 price, fee와 PnL을 어떻게
   귀속하는가?
8. Strategy를 배포하거나 변경할 때 어떤 operator approval이 필요한가?
9. 어떤 evidence가 성능이 저하된 strategy를 자동으로 disable하는가?
10. Model/strategy version, config, data와 모든 live decision을 어떻게 재현하는가?

안전한 초기 경계는 target execution을 먼저 구현하고 alpha를 비활성화하는 것이다. Alpha research는 별도
interface와 budget 뒤에서 replay/paper mode로 진행할 수 있다. Attribution, flattening, recovery와 risk
control이 검증된 뒤에만 production OMS에 들어가야 한다.

## 8. 조사할 architecture 대안

### 대안 A — 기존 live-trading engine 채택

Market data, strategy scheduling, order management, portfolio/risk state와 broker adapter를 제공하는 검증된
event-driven trading framework를 사용한다. qlibx artifact adapter, 조직 고유 control과 누락된 broker
integration만 추가한다.

Framework가 올바른 restart, reconciliation과 order-state semantic을 제공한다면 이 대안을 우선한다.
Production evidence 없는 feature breadth는 충분하지 않다.

### 대안 B — 목적별 library 조합

qlibx가 소유하는 OMS contract 뒤에서 event bus/runtime, broker SDK 또는 gateway, durable store, scheduler와
observability stack을 조합한다.

필요한 broker를 지원하는 단일 framework가 없을 때 더 적합할 수 있지만 integration risk는 더 높다.
Cross-component ordering, idempotency, replay와 state reconciliation을 프로젝트가 소유해야 한다.

### 대안 C — 얇은 자체 OMS core 구현

공식 broker API와 검증된 infrastructure component 주위에 누락된 domain layer만 구현한다.

이는 최후의 대안이다. 기존 engine이 필요한 broker, license, deployment 또는 state-authority constraint를
충족하지 못한다는 조사 결과가 있을 때만 정당화된다. “기존 framework가 무겁다”는 충분한 증거가 아니다.

### Qlib의 가능한 역할

Qlib은 offline alpha research, model artifact 또는 일부 strategy logic에 계속 유용할 수 있다. 실시간 market
data, order management 또는 operational state를 Qlib이 소유한다고 전제해서는 안 된다. 경계가 명시적이고
OMS가 qlibx internal을 import하지 않고 작동할 수 있다면 hybrid architecture도 허용한다.

## 9. Research framework 선택 가설

이 절은 2026-07-31 현재 Qlib과 NautilusTrader의 공식 문서를 비교한 탐색 결과다. Framework 채택 결정이나
production 적합성의 증명이 아니며, 실제 broker/API와 market-data 조건 아래 characterization prototype을
통과해야 한다.

### 9.1 비교 문제를 먼저 분리한다

“Intraday research”를 하나의 범주로 취급하면 잘못된 framework를 선택할 수 있다.

- **Daily 또는 bar-based cross-sectional research:** 같은 decision time의 universe를 함께 보고 factor,
  label, rank, neutralization, model과 portfolio target을 계산한다.
- **Fill-independent intraday research:** 5분 또는 30분과 같이 완성된 bar마다 cross-sectional target을
  갱신하지만, order acknowledgement나 partial fill이 alpha state를 직접 바꾸지 않는다.
- **Fill-dependent event-driven research:** Tick, quote, order book, latency, partial fill, cancel/replace와
  position transition이 다음 action을 결정한다.
- **Hierarchical execution research:** Daily parent portfolio decision을 intraday child execution strategy가
  나누어 집행하고 두 수준의 성과를 함께 평가한다.

첫 두 범주는 panel data, label, model과 cross-sectional portfolio 문제다. 뒤의 두 범주는 event ordering,
market microstructure와 execution state 문제다. 같은 “research framework”라는 이유로 하나의 runtime을 모든
범주에 강제해서는 안 된다.

### 9.2 현재 비교 판정

| Strategy/research 유형 | 우선 후보 | 이유 | 남는 핵심 gap |
|---|---|---|---|
| Daily/weekly cross-sectional | Qlib + qlibx | `datetime × instrument` dataset, processor, model, IC/RankIC와 portfolio workflow가 자연스럽다 | qlibx PIT, signed semantics, portable artifact와 production boundary가 계속 필요하다 |
| 5~60분 cross-sectional, fill feedback가 약함 | Qlib + qlibx 우선 | 문제 구조가 여전히 cross-sectional batch에 가깝다 | Data volume, timestamp barrier와 실제 execution을 별도 검증해야 한다 |
| Daily parent + intraday execution 최적화 | Qlib outer research + 별도 event-driven execution 후보 | Qlib nested execution으로 multi-level 가설을 연구할 수 있다 | Live broker reconciliation과 operational recovery는 Qlib 책임이 아니다 |
| Tick/order-book 또는 fill-dependent intraday | NautilusTrader 우선 후보 | Event-driven order/position/account state와 backtest/sandbox/live 공통 kernel을 제공한다 | Cross-sectional research layer, sleeve accounting과 production recovery evidence를 검증해야 한다 |
| Market making 또는 multi-venue arbitrage | NautilusTrader 우선 후보 | Order book, latency, cancel/replace와 venue event가 strategy state의 일부다 | 실제 venue adapter, queue/impact model과 broker-specific failure semantics가 남는다 |

이 판정은 “intraday이면 NautilusTrader”를 의미하지 않는다. 완성된 bar를 사용해 universe를 매번 rank하는
전략은 intraday여도 Qlib 쪽 문제에 가깝다. 반대로 partial fill이나 cancel 결과가 다음 quote, hedge 또는
position limit을 바꾼다면 inner runtime은 event-driven이어야 한다.

### 9.3 Daily cross-sectional에서는 Qlib을 유지한다

Qlib은 `DataHandlerLP`, Dataset segment, model fit/predict, workflow record와 signal/portfolio analysis를
연결한다. qlibx의 signed alpha, ensemble, physical construction과 portable evidence contract는 이 research
kernel 위에 유지한다.

NautilusTrader의 data catalog, bars와 custom data는 유용하지만 cross-sectional factor platform 자체는
아니다. NautilusTrader만으로 daily research를 수행하려면 다음을 별도로 구현해야 한다.

- Timestamp별 universe snapshot과 missing/stale instrument policy
- Cross-sectional rank, winsorization, neutralization과 exposure diagnostic
- Label horizon, train/validation/test와 leakage control
- IC/RankIC, quantile spread, turnover와 alpha comparison
- Ensemble, portfolio construction, optimizer와 experiment publication

이는 qlibx가 소유하기로 한 핵심 research responsibility를 중복 구현한다. 따라서 daily cross-sectional을
이유로 qlibx backend 전체를 NautilusTrader로 교체하지 않는다.

다만 Qlib의 signal diagnostic과 execution simulation을 혼동해서는 안 된다. Qlib 0.9.7의 표준 stock
Position은 native short, borrow, margin과 securities-lending lifecycle을 제공하지 않는다. Signed factor
성과는 research evidence일 수 있지만 realistic short execution의 증거는 아니다.

### 9.4 Intraday에서는 bar-based와 event-driven을 분리한다

Fill-independent bar strategy는 Qlib/qlibx에서 signal과 target을 연구할 수 있다. 그러나 여러 instrument의
동일 timestamp bar가 모두 도착했다는 판단, 늦거나 누락된 bar의 처리와 decision cutoff는 명시적인
cross-sectional barrier로 정의해야 한다.

Qlib `NestedExecutor`는 daily outer decision을 higher-frequency inner decision으로 집행하는 joint backtest에
유용하지만 다음을 자동 제공하지 않는다.

- Live market-data session과 arbitrary scheduler
- Broker acknowledgement, external/manual order와 account reconciliation
- Disconnect/restart, duplicate prevention과 durable operational replay
- Production kill switch, alert와 operator intervention

Fill-dependent strategy의 우선 후보는 NautilusTrader다. 공식 architecture는 data, execution, portfolio와
risk engine을 event-driven kernel로 구성하고, backtest, sandbox와 live context에서 같은 strategy 및
order-state model을 사용하는 방향을 제공한다. Order book, quote, trade와 bar를 서로 다른 granularity로
처리하며 submitted, accepted, rejected, canceled, expired와 partial/complete fill을 event로 표현한다.

그러나 adoption 전에 다음을 검증해야 한다.

- Historical order book이 immutable이므로 queue position과 own-market-impact realism은 fill model에
  의존한다.
- `strategy_id`와 position/report가 존재해도 qlibx target, intraday alpha와 operations reserve의 경제적
  sleeve 귀속이 자동 충족된다는 증거는 아니다.
- Opposing sleeve order의 netting, fill/fee/cash/PnL 배분은 별도 contract가 필요하다.
- Durable event sourcing과 recovery API가 발전 중이므로 production audit/replay 요구를 이미 충족한다고
  전제하지 않는다.
- 선택한 broker, KRX market data와 production OS의 adapter 및 운영 증거를 확인해야 한다.

### 9.5 권장 hybrid 경계

```text
Qlib + qlibx
  daily/bar-based cross-sectional research와 outer portfolio decision
  -> immutable PreparedDecision

NautilusTrader 기반 후보 runtime
  target-execution sleeve
  + 별도로 승인된 fill-dependent intraday-alpha sleeve
  -> broker-confirmed execution result와 account snapshot

qlibx
  identity 검증과 reconciliation
  -> CompletedCheckpoint와 authoritative next-batch memory
```

Daily target의 intraday execution을 공동 연구할 때는 `Qlib outer decision -> event-driven execution simulation
-> realized fill/cost -> qlibx portfolio evaluation` 경계를 prototype한다. 두 framework의 account를 동시에
authoritative state로 취급하지 않고 portable result artifact만 경계를 넘긴다.

True intraday alpha의 각 market event를 qlibx outbox의 새 `PreparedDecision`으로 전달하지 않는다. 현재
qlibx contract는 portfolio/account당 하나의 in-flight decision을 전제하므로 overlapping high-frequency
decision lifecycle과 맞지 않는다. Intraday loop와 operational state는 OMS runtime이 소유하고, qlibx에는
승인된 strategy/model/config identity, sleeve별 outcome과 broker-confirmed terminal state만 전달한다.

### 9.6 채택 전 gate

Framework 선택은 feature 수가 아니라 다음 evidence로 판정한다.

1. **Daily parity:** 동일 frozen input에서 Qlib/qlibx signal, target과 performance가 재현된다.
2. **Timestamp correctness:** Event time, ingestion time과 decision cutoff가 look-ahead 없이 처리된다.
3. **Execution realism:** Partial fill, reject, cancel/replace, latency, stale data와 close behavior를 주입한다.
4. **Research-to-live parity:** 같은 strategy contract가 replay, paper와 live에서 동작하고 차이를 기록한다.
5. **State authority:** Broker truth, OMS operational state, sleeve ledger와 qlibx memory가 섞이지 않는다.
6. **Recovery:** Disconnect와 restart 뒤 duplicate order 없이 같은 terminal result로 수렴한다.
7. **Attribution:** 동일 account/instrument에서도 모든 fill, fee, cash movement와 residual을 sleeve에 귀속한다.

현재 권고는 daily cross-sectional의 canonical research framework로 Qlib + qlibx를 유지하고,
NautilusTrader는 fill-dependent intraday research와 future OMS의 우선 characterization 후보로 다루는 것이다.
이는 채택 결정이 아니며 §10의 단계별 gate를 통과해야 한다.

비교 근거:

- [Qlib Data Layer](https://qlib.readthedocs.io/en/stable/component/data.html)
- [Qlib Recorder and signal analysis](https://qlib.readthedocs.io/en/stable/component/recorder.html)
- [Qlib nested decision execution](https://qlib.readthedocs.io/en/stable/component/highfreq.html)
- [NautilusTrader architecture](https://nautilustrader.io/docs/latest/concepts/architecture/)
- [NautilusTrader backtesting and fill model](https://nautilustrader.io/docs/latest/concepts/backtesting/)
- [NautilusTrader events](https://nautilustrader.io/docs/latest/concepts/events/)
- [NautilusTrader strategies](https://nautilustrader.io/docs/latest/concepts/strategies/)
- [NautilusTrader event sourcing](https://nautilustrader.io/docs/nightly/concepts/event_sourcing/)

## 10. 단계별 계획과 gate

### 단계 0 — Contract 및 library 조사

- 최소 input, output, identity, budget과 state-authority contract를 확정한다.
- §11의 prompt로 기존 framework와 component를 조사한다.
- 작은 characterization prototype을 수행할 후보를 선택한다.
- Production operating system, broker/API 유형과 persistence constraint를 결정한다.

종료 gate: 근거가 있는 shortlist가 있고 authoritative account, operational state와 strategy state의
ownership에 모호함이 없다.

### 단계 1 — Broker/account shadow runtime

- Sandbox 또는 paper broker API에 연결한다.
- Account, position, open-order와 session snapshot을 저장한다.
- Broker state와 합성 qlibx expected-state fingerprint를 비교한다.
- Live order 없이 disconnect, duplicate event, restart와 stale snapshot 처리를 시험한다.

종료 gate: 주입한 장애 아래에서 deterministic recovery와 reconciliation이 가능하다.

### 단계 2 — Simulation, paper 및 shadow mode의 qlibx target execution

- Version이 있는 `PreparedDecision`을 소비한다.
- Actual holding에서 delta를 계산한다.
- Slicing, partial fill, reject, cancel, expiry와 close policy를 시험한다.
- `OMSResult`를 발행하고 qlibx가 OMS internal 없이 reconcile할 수 있음을 입증한다.

종료 gate: Replay가 같은 terminal attributed result를 만들고 broker order를 중복 생성하지 않는다.

### 단계 3 — 제한된 live target execution

- 하나의 account/portfolio와 하나의 in-flight qlibx decision만 활성화한다.
- 엄격한 notional, instrument와 operator-approval limit으로 시작한다.
- Alerting, kill switch, manual intervention audit와 end-of-day reconciliation을 검증한다.

종료 gate: 설명되지 않은 cash, position 또는 order 차이 없이 broker-confirmed reconciliation이 지속된다.

### 단계 4 — Intraday alpha research 및 paper operation

- Research ownership과 promotion policy를 정의한다.
- Market-data correctness, cost realism과 strategy replay를 입증한다.
- Virtual budget과 강제 failure scenario로 alpha sleeve를 실행한다.
- Production order submission은 비활성화한다.

종료 gate: 승인된 strategy가 있고 confirmed flattening이 불가능한 경우의 문서화된 behavior를 포함해
no-new-risk/flattening control이 검증된다.

### 단계 5 — 통제된 alpha integration

- 별도 sleeve와 hard budget으로 alpha를 활성화한다.
- Target-execution과 alpha attribution을 broker account에 reconcile한다.
- Conflict, netting, shared buying power와 simultaneous failure를 시험한다.
- 명시적인 operational review 뒤에만 범위를 확대한다.

종료 gate: 모든 fill, fee, cash movement와 residual position을 귀속하고 재현할 수 있다.

## 11. 다른 에이전트용 복사·붙여넣기 조사 지시문

다음 prompt는 그대로 재사용할 수 있도록 의도적으로 영어로 작성했다. 조사 답변은 한국어로 작성하도록
지시한다.

```text
You are one of several independent research agents evaluating existing libraries and frameworks for
a future production OMS/live-trading runtime. Perform current web research. Respond in Korean.

Context
-------
qlibx is a Qlib-based research, backtesting, and production daily-batch position-decision system.
It publishes a durable, broker-neutral target to local storage. A separate future system, currently
called "qliby" only as a temporary working name, will connect to a real broker, execute that target
intraday, and return only broker-confirmed fills and account snapshots. The future system may not
depend on Qlib and will likely be renamed.

The future OMS may eventually also run its own live intraday alpha strategies. Those alpha
strategies should carry no intended overnight position and must use a separately bounded cash/risk
budget. The OMS must keep the qlibx target-execution sleeve, OMS operational reserve, and intraday
alpha sleeve attributable while reconciling all of them to the same broker-authoritative account.
Alpha strategy selection, research ownership, and live deployment workflow are not decided yet.

Research objective
------------------
Find maintained open-source libraries, frameworks, gateways, or composable components that can
avoid reinventing order management and live-trading infrastructure. Do not assume that one product
must provide everything. Distinguish:

1. complete event-driven live-trading engines;
2. OMS/EMS or order-state-management components;
3. broker and market-data gateways/adapters;
4. portfolio/risk/accounting components;
5. durable event, replay, scheduling, and operational components that would need to be composed.

Do not recommend a candidate merely because it supports backtesting or has a broker API wrapper.
The main problem is reliable real trading and state authority, not another research notebook.

Non-negotiable capabilities or evaluation criteria
---------------------------------------------------
- Real live market-data ingestion and broker order submission.
- Explicit order lifecycle: pending/submitted/acknowledged/partially filled/filled/cancelled/
  rejected/expired, including replace and late or out-of-order events.
- Account, position, cash, open-order, fill, fee, and tax reconciliation against broker truth.
- Durable state, idempotency, crash recovery, replay, and prevention of duplicate orders.
- Multiple strategy/sleeve attribution with per-sleeve position, cash, cost, PnL, and risk budgets,
  reconciled to one broker account.
- Common pre-trade and continuous risk controls, kill switches, rate-limit handling, disconnect
  behavior, and auditable operator intervention.
- Intraday scheduling, exchange calendars, market-session controls, and end-of-day no-new-risk /
  flatten workflows. Explicitly assess behavior when flattening fails because of suspension, price
  limits, broker outage, or rejection.
- Support for target-position execution, order slicing/pacing, partial completion, expiry, and
  configurable execution algorithms. The delta must be derived from actual holdings, not from the
  previous requested target.
- Paper/sandbox, historical replay, shadow, and live modes with comparable order-state semantics.
- Extensible broker and market-data adapter interfaces. Identify existing support relevant to
  Korean securities brokers or KRX if any, but do not fabricate support. If no direct support
  exists, assess the effort and stability of a custom adapter.
- Clear separation between offline research/model code and the always-on live OMS runtime.
- Python interoperability is strongly preferred but not mandatory. State supported operating
  systems, deployment model, language/runtime, persistence backend, and latency design point.
- Active maintenance, release cadence, issue health, documentation quality, production references,
  license, commercial restrictions, governance, and bus-factor risk.
- Ability to integrate through versioned files/messages or a small public API without importing
  qlibx private implementation.
- No required Qlib dependency unless it provides a specifically evidenced benefit.

Critical questions
------------------
- Is the candidate genuinely suitable for production live trading, or primarily a backtester?
- Which required responsibilities are implemented by the candidate, and which would remain ours?
- What is the authoritative source of order, account, portfolio, and strategy state?
- Can its state model represent partial fills, external/manual broker orders, corrections, and
  restart reconciliation without silent divergence?
- Can it separate multiple virtual sleeves in one physical broker account? If not, what must be
  built and how risky is that gap?
- Does it support target-position execution natively, or only raw order submission?
- How does it handle opposing orders or internal netting between strategies, and how are fills and
  fees attributed?
- Can an intraday alpha sleeve be forced into no-new-risk and flattening phases while target
  execution continues?
- Can the live runtime run without the research/backtest stack?
- Are there hidden cloud, database, broker, licensing, or infrastructure lock-ins?
- What failure modes or open issues make the candidate unsuitable?

Evidence standard
-----------------
Use current primary sources wherever possible: official documentation, source repositories,
release notes, issue trackers, license files, and broker integration documentation. Cite a direct
link for every material claim. Record the date checked, latest stable release and latest repository
activity. Treat marketing claims and unsourced feature lists as weak evidence. Clearly label
inference, unverified claims, abandoned projects, paper-trading-only support, and features that
require commercial editions.

Required Korean deliverable
---------------------------
1. 조사일과 조사 범위.
2. 요구사항을 다시 요약한 뒤, 잘못되었거나 과도한 가정이 있으면 비판적으로 지적.
3. 후보를 범주별로 longlist하고, 각 후보를 포함하거나 제외한 근거.
4. 가장 유력한 3~5개 후보의 비교표. 최소 열:
   - candidate / category / language
   - live-broker and live-data maturity
   - order-state and reconciliation semantics
   - multi-strategy sleeve/accounting support
   - target execution and execution algorithms
   - recovery/idempotency/persistence
   - risk and operational controls
   - paper/replay/live parity
   - broker/KRX extensibility
   - deployment and OS support
   - maintenance/license/governance
   - missing pieces we must build
   - evidence links
5. 각 유력 후보가 전체 framework로 적합한지, 일부 component로만 적합한지 판정.
6. "adopt", "prototype", "component-only", "reject" 중 하나로 판정하고 신뢰도 표시.
7. 1~2주짜리 characterization prototype 계획. 반드시 partial fill, reject, cancel/replace,
   disconnect/restart, duplicate event, stale account snapshot, external/manual order, EOD flatten
   failure, and multi-sleeve reconciliation을 시험.
8. 최종 권고 architecture 1개와 차선책 1개. 우리가 직접 구현해야 하는 최소 영역을 명시.
9. 아직 답할 수 없는 질문과 실제 broker/API를 정한 뒤 재검증할 항목.

Be skeptical. A conclusion that no single library is adequate is acceptable, but only after showing
evidence and identifying the safest composable alternative. Do not propose building a full OMS from
scratch unless the researched evidence rules out maintained alternatives.
```

## 12. 추가로 필요한 결정

조사와 prototype이 근거를 제공할 때까지 다음 선택지는 열어 두어야 한다.

- 최종 제품명
- Live runtime의 Qlib 의존성 여부
- qlibx/OMS 경계의 target semantic
- Broker, account/subaccount와 market-data provider
- Deployment operating system과 availability target
- Framework 채택 또는 component 조합
- Persistence/event-log 기술
- Internal netting과 sleeve attribution policy
- 정확한 cash-budget priority와 settlement 처리
- Intraday alpha research owner와 promotion process
- Intraday alpha용 strategy runtime/API
- Live latency, capacity와 instrument scope
- Operator approval, compliance와 incident-response 요구사항

이 문서는 조사와 구현의 순서를 제안한다. 특정 OMS library, alpha strategy 또는 live deployment
architecture를 채택하지 않는다.
