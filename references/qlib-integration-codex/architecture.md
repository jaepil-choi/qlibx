# Qlib Migration Architecture

## 1. 문서 책임

이 문서는 `qlib-integration-codex/`의 current/target architecture만 설명한다. Root production
architecture는 `docs/vibe/architecture.md`가 계속 소유한다. Migration code는 production `src/`를
import해 내부 구현을 공유하거나 그 module responsibility를 변경하지 않는다.

## 2. Current Architecture

현재 구현은 다음 경계로 나뉜다.

- `qlib_extended/`: public application facade, deterministic run identity, catalog, reporting,
  stored-alpha ensemble과 configured enhanced-index optimizer
- `peer_momentum_runtime/`: 독립 peer-return 계산과 Qlib `BaseStrategy` twin
- `kwam_qlib_backend/`: Qlib execution/accounting capability, optimizer와 artifact regression harness
- `weight-strategy-twin/`: 이전 `WeightStrategyBase` long-only 비교 실험
- `report_twin/`: frozen report ensemble과 physical execution migration acceptance
- `report_assets/`: internal stored report-data 검증과 병렬 asset rendering

Systematic alpha discovery, family crossing, research catalog와 physical portfolio selection의
상세 target architecture는 `research/architecture.md`가 소유한다. 이 문서의 migration
runtime catalog와 research alpha pool은 목적이 다르며, research pool은 data/alpha definition을
복제하지 않는 rebuildable result index로 제한한다.

현재 executable flow는 long-only와 matched-capitalization signed-weight를 모두 지원한다.

```text
lookahead-safe strategy decision
-> current physical long-only target
-> Qlib Order / ScenarioExchange
-> Qlib Account / Position
-> fill, cash, quantity, NAV feedback
-> next decision
```

이 long-only flow와 Goal 0~15는 Goal 16 signed flow가 계속 지켜야 할 regression baseline이다.

## 3. Target Long-Short Flow

```text
strategy / optimizer
    -> SignedActiveIntent(A)
    -> ticker-level ensemble crossing/netting
    -> CausalInventoryMask
    -> MatchedCapitalizationAdapter(B)
    -> CompositeExecutionIntent(C = B + A, C >= 0)
    -> Qlib Order / Exchange / Account / Position
    -> CompositeExecutionObservation
    -> SignedExecutionObserver(A_realized = C_realized - B)
    -> immutable artifacts / active reporting
```

### 3.1 Source-of-truth boundary

```text
Qlib Account / Position
    owns: composite order, fill, quantity, cash, cost, NAV, mark-to-market

Baseline sidecar
    owns: capitalization quantity/cash, activation price/time/reason, inventory readiness

Signed observer
    owns: no execution state
    derives: active signed quantity, exposure, PnL and reconciliation diagnostics
```

Signed observer가 Qlib fill과 독립적으로 quantity를 진행시키면 dual-ledger 구조가 되므로 금지한다.
Production signed holdings ledger는 differential-test oracle일 뿐 migration runtime state가 아니다.

## 4. Layer Responsibilities

### 4.1 Signed intent layer

- 원 종목 ticker만 사용한다.
- Strategy/member/ensemble lineage와 intended signed quantity/weight를 보존한다.
- Qlib composite inventory, reserve cash나 capitalization mechanics를 알지 않는다.

### 4.2 Causal universe layer

- Full ticker axis와 point-in-time availability를 분리한다.
- `observed`, `tradable`, `strategy_universe`, `shortable`, `inventory_ready` mask를 명시한다.
- Rank와 normalization 전에 mask를 적용한다.
- Ticker lifecycle을 `unseen -> observed -> tradable -> inventory_ready`로 진행한다.

### 4.3 Matched capitalization layer

- Current active NAV/config/price만 사용해 required baseline capacity를 계산한다.
- Composite initial cash와 active booksize를 분리한다. 차이는 causal baseline funding reserve이며
  active return denominator나 alpha exposure에 포함하지 않는다.
- 부족한 baseline `delta_B`를 execution-time price `P`에서 quantity와 matching cash debit으로
  baseline/composite 양쪽에 atomic하게 반영한다.
- Activation/top-up이 NAV-neutral인지 즉시 검증한다.
- Active order 전에 capacity가 준비되지 않으면 주문을 만들지 않고 explicit failure를 남긴다.

### 4.4 Qlib execution layer

- Composite position만 본다.
- Baseline activation은 market order로 처리하지 않는다.
- Active order는 underlying의 실제 BUY/SELL 방향으로 처리한다.
- Qlib tradability, direction limit, volume, lot, cost와 Account lifecycle을 유지한다.

### 4.5 Signed observation layer

- Qlib dealt amount를 active signed fill로 해석한다.
- `A_realized = C_realized - B`를 계산한다.
- Target/filled/held 차이, capacity shortfall과 blocked reason을 기록한다.
- Composite/baseline/active cash와 NAV reconciliation을 검증한다.

### 4.6 Persistence and reporting layer

- Alpha run과 backtest run identity를 분리한다.
- Baseline definition, activation policy와 backend code fingerprint를 backtest identity에 포함한다.
- Qlib raw artifact와 signed audit artifact를 immutable Parquet에 함께 저장한다.
- Report는 stored artifacts만 읽고 strategy/backend를 재실행하지 않는다.
- Signed attribution은 stored execution/valuation price, realized position, cost와 member
  alpha parent weight만 읽고 overnight/intraday/cost PnL을 active account와 reconcile한다.
- Enhanced-index attribution은 stored member signed intent, benchmark, optimizer look-through와
  Qlib realized physical position을 연결한다. Optimizer target과 execution target, look-through
  적용 횟수와 parent weight 합을 reader에서 독립 검증한다.

### 4.7 Report twin layer

`report_twin/`은 frozen report artifact를 읽는 migration acceptance layer다. Production
`src/kwam_enhanced_index`와 `research/report/build_report_assets.py`의 계산 함수를 import하지 않는다.

```text
18 frozen member weights
-> 7 market variants
-> market / financial / consensus family weights
-> 5 causal rationale allocations
-> negative screen + embedded volatility multiplier
-> 70% direct BM + alpha adjustment + residual K200 ETF
-> analytical daily PnL parity
-> Qlib target_weight physical execution
```

`contract.py`가 manifest/schema/date/member contract를, `market.py`와 `rationale.py`가 독립
ensemble 계산을, `portfolio.py`가 execution-universe transfer와 drift-adjusted sleeve cost를,
`lineage.py`가 member/family/candidate/backtest parent graph를 담당한다. `runner.py`는 이 layer들을
조립하지만 각 계산 책임을 다시 구현하지 않는다.

Analytical parity는 fractional target 기준 frozen report와 exact 비교한다. Qlib execution은 동일한
physical target을 integer quantity, cash와 cost lifecycle로 실행하는 별도 증거이며, 두 결과의 차이는
명시적으로 기록한다.

## 5. Atomic Bar Sequence

한 execution bar는 다음 순서를 따른다.

```text
1. read prior completed Qlib feedback
2. build lookahead-safe signed intent
3. validate point-in-time masks
4. calculate required baseline capacity
5. activate/top up baseline and composite with matching cash debit
6. validate NAV-neutral capitalization and C >= 0
7. submit active underlying orders to Qlib
8. observe Qlib partial/full fills
9. optional valuation price로 composite position을 mark-to-market
10. reconstruct signed held position and validate invariants
11. publish bar artifacts
```

Strategy decision은 1번에서 완료된 이전 feedback만 볼 수 있다. Execution-time capitalization
price는 alpha를 만드는 정보가 아니라 같은 bar financing event의 valuation input으로만 사용한다.

## 6. Dynamic Universe Semantics

Future ticker가 static matrix column으로 존재하는 것은 허용한다. `observed=False`인 동안 해당
column은 모든 경제적 state에서 0이어야 한다. 양수 dormant inventory를 Qlib `Position`에 미리
넣지 않는다.

Ticker가 처음 tradable해질 때 activation할 수 있다. 이 same-bar policy는 해당 bar에 synthetic
inventory를 사용할 수 있다는 modeling assumption이다. 실제 borrow availability dataset이 생기면
`shortable`과 capacity를 그 데이터로 제한한다. 보수적 비교를 위해 next-bar readiness policy를
configurable variant로 둘 수 있지만 silent lag를 넣어서는 안 된다.

Universe exit 뒤 baseline을 유지할지 retire할지는 명시적 policy다. 기본 target은 retained baseline
policy이며 re-entry 시 기존 capacity를 재사용한다. Delisting과 corporate action이 반영된
execution/mark price, universe와 physical quantity contract는 upstream ETL이 제공한다. Integration은
raw event나 adjustment factor를 해석하지 않으며 non-unit factor 입력을 거부한다.

`inventory_retention=active_short_only`는 high-turnover alpha를 위한 명시적 대안이다. 현재 bar의
underlying fill이 끝난 뒤 realized active quantity를 바꾸지 않는 범위에서 불필요한 baseline과
composite quantity를 같은 수량만큼 줄이고 같은 가격의 cash를 돌려준다. 이는 market fill이나
미래 universe 예측이 아니며 `A = C - B`와 composite NAV를 보존한다. 기본값은 계속 `retained`다.

## 7. Failure and Reconciliation

다음은 모두 fail-fast 대상이다.

- activation price 누락, 비양수 또는 비유한 값
- observed 이전 target/inventory
- baseline funding reserve 부족
- composite quantity 음수
- `A != C - B`
- capitalization 직후 NAV 변화
- Qlib fill과 signed realized delta 불일치
- upstream-normalized physical unit이 아닌 adjustment factor 입력
- artifact hash 또는 lineage 불일치

Failure를 target clipping, future seed, report-time correction으로 숨기지 않는다.

## 8. Dependency Direction

```text
public facade / CLI
        -> application use cases
        -> migration domain contracts
        -> Qlib / storage / reporting adapters
```

Migration domain은 Qlib concrete class topology나 DuckDB table layout을 public API로 노출하지
않는다. Qlib source와 production `src/`는 수정하지 않는다. Canonical requirements는 `prd.md`,
구현 현황은 `implementation.md`, matched-capitalization 상세 결정은
`weight-strategy-twin/qlib-shorting.md`가 소유한다.
