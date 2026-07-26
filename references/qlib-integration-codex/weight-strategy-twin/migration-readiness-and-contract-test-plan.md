# Qlib WeightStrategyBase Twin Migration Readiness And Capability-Test Plan

> 2026-07-22 이후의 경계 수정과 Goal 9~10/graph 완료 계약은
> [`../qlib-integration-codex/critical-review.md`](../qlib-integration-codex/critical-review.md)를
> 함께 따른다. 특히 corporate-action data 생성은 upstream ETL 책임이다.

## 1. 목적과 테스트 경계

이 문서는 KWAM strategy의 자유도를 유지하면서 Qlib을 실제 execution/accounting
backtester로 쓰기 위한 migration acceptance criteria를 정의한다. Acceptance test를 먼저
고정한 뒤 `qlib-integration-codex/kwam_qlib_backend/`가 Goal 0~10 backend와 research
graph/dataset lineage를 구현했다.
Test-only adapter는 계속 observable capability만 고정하며 production object topology는
고정하지 않는다.

검토 기준은 다음 문서와 현재 코드다.

- `docs/vibe/prd-3-loop.md`: closed-loop feedback
- `docs/vibe/prd-5.md`: flexible alpha budget과 cash/ETF buffer
- `docs/thoughts/subscription-based-data-feed-for-strategies.md`: dataset별 lookback
- `docs/thoughts/scale-to-meta-strategy.md`: strategy composition
- `docs/thoughts/autonomous-counterfactual-alpha-meta-strategy.md`: adaptive research
- `docs/thoughts/etf-funded-long-biased.md`: ETF와 direct holding의 path state
- `docs/report/enhanced-index-2/ensemble-enhanced-index-slides-2.qmd`: long/short alpha →
  ensemble → enhanced index workflow

Acceptance test는 최종 capability를 검증한다. 다음은 구현을 시작하기 전에 고정하지 않는다.

- `desired/optimized/applied/held`라는 특정 단계 분해
- child별 shadow book 또는 `components` 구조
- hypothetical evaluator가 vectorized engine인지 복제 ledger인지
- Qlib Account의 내부 개수와 topology
- Strategy state의 class, dict, model object 형태

이런 항목은 실제 설계를 선택한 뒤 internal unit/integration test에서 검증한다. Acceptance
boundary가 요구하는 것은 observable behavior와 accounting evidence다.

## 2. 현재 구조 진단

### 2.1 KWAM이 계속 소유할 capability

- Strategy가 이전 실제 execution feedback을 받아 다음 decision을 바꾸는 closed loop
- 각 dataset이 독립적인 native-row lookback과 availability date를 갖는 subscription
- 날짜별 K200 membership/investability/tradability를 구분하는 changing universe
- run 사이에는 reset되고 run 안에서는 유지되는 arbitrary stateful memory
- 과거 구간에서 여러 rule을 what-if 평가하거나 model을 학습하는 adaptive research
- signed long/short alpha research, ensemble, ticker-level netting, enhanced-index construction
- benchmark, direct stock, ETF, cash, look-through exposure의 domain 의미
- explicit strategic cash와 flexible budget
- post-run reporting

Public strategy 이름은 필요할 때 `Strategy`를 사용한다. Closed loop는 실행 방식이지 별도
strategy subtype이 아니므로 `ClosedLoopStrategy`를 요구하지 않는다.

### 2.2 Qlib이 증명해야 할 capability

Qlib은 최종 선택된 physical action에 대해 다음을 실제로 수행해야 한다.

- integer target quantity와 current quantity 차이의 order 처리
- buy/sell, suspension, tradability, volume/cash limit
- requested quantity와 filled quantity
- trade price, cost, tax와 cash update
- stock/ETF quantity, mark-to-market NAV, return, turnover
- ETL이 제공한 corporate-action factor의 quantity adjustment

Qlib `Account`를 사용하는 가장 큰 이유는 실제 cash, quantity, fill, cost, NAV의 ledger이기
때문이다. Public 결과를 별도 계산한 뒤 Qlib 결과처럼 표시해서는 안 된다. Acceptance test는
actual execution result가 Qlib accounting evidence와 reconciliation되는지 검사하지만 Account
개수나 내부 wiring은 검사하지 않는다.

Strategy는 raw Qlib object가 아니라 backend-neutral feedback을 관찰해야 한다. 최소 observable
feedback은 다음이다.

```text
feedback date
actual cash and NAV
actual held quantity
filled quantity and trade cost
portfolio return
unfilled/blocked reason
```

### 2.3 Adaptive research의 핵심 경계

원하는 loop는 다음이다.

```text
Strategy observes history available before t
→ evaluates candidate rules or trains a model on historical data
→ selects the action for t
→ only the selected action reaches actual Qlib execution
→ actual execution feedback becomes visible after the bar
→ Strategy may change its rule at a later decision
```

Hypothetical evaluation은 actual cash, position, NAV, order count, transaction cost를 변경하지
않아야 한다. 이를 어떻게 구현하는지는 정하지 않는다. 별도 shadow book, vectorized evaluator,
scenario simulator, cached artifact, model-based estimator 모두 허용된다.

### 2.4 범위상 한계

- Qlib 0.9.7 기본 기능만으로 실제 stock short/margin/borrow account를 가정하지 않는다.
- 승인된 long-short target은 matched capitalization이며 별도 capability와 contract test가
  완료되기 전에는 지원된다고 주장하지 않는다. Synthetic mirror는 사용하지 않는다.
- stock과 ETF의 비용/세금 차이는 explicit asset-class policy로 공급해야 한다.
- adjusted close와 quantity adjustment factor의 의미가 일치해야 한다.

## 3. Capability-Oriented Acceptance Harness

테스트는 production API를 직접 import하지 않는다. Test-only adapter가 implementation을 다음
normalized harness로 연결한다.

```text
BackendHarness
  run_consecutive_loss_stop(...)
  run_subscription_probe(...)
  run_stateful_probe(...)
  run_universe_probe(...)
  run_weight_targets(...)
  run_cached_ensemble(...)
  run_adaptive_rules(...)
  run_adaptive_model(...)
  resume_equivalence_probe(...)
  artifact_store(...)
```

이 이름과 반환 view는 acceptance test 전용이다. Production `Strategy`, request, result,
portfolio constructor의 class/signature를 규정하지 않는다. Custom event loop, Qlib strategy
subclass, research kernel 중 무엇을 선택해도 adapter만 연결하면 된다.

Harness가 정규화하는 observable output은 다음 범주다.

- decision date별 target weight와 선택 rule
- observation/feedback causality audit
- actual orders, fills, positions, account daily values
- hypothetical candidate evaluation과 side-effect audit
- 실제 execution이 Qlib에서 왔다는 reconciliation evidence
- signal/portfolio/execution artifact

## 4. Physical Execution Contract

### 4.1 Input semantics

```text
execution_price            date x physical instrument
universe                    date x research instrument, point-in-time bool
volume                      optional date x physical instrument
buyable / sellable          optional explicit bool matrices
suspended                   optional explicit KRX suspension bool matrix
upper_price_limit           optional explicit KRX upper-limit bool matrix
lower_price_limit           optional explicit KRX lower-limit bool matrix
asset_class                 instrument -> stock | etf | ...
lot_size                    instrument -> positive integer, default 1 only if explicit policy says so
position_unit_factor       required ETL-provided corporate-action position multiplier
booksize                    initial physical cash/NAV
cost_policy                 asset class별 buy/sell/tax policy
```

필드나 asset class를 ticker 이름에서 추정하지 않는다. `position_unit_factor`는 corporate
action이 없는 구간에도 explicit all-ones matrix로 제공한다. 누락 field, mismatched axes,
비양수 또는 비유한 factor는 Qlib 실행 전에 fail-fast한다. 현재 valuation과 execution에
동일한 canonical series를 사용하므로 별도 `valuation_price`를 만들지 않는다. 실제로 다른
valuation series가 필요해질 때에만 계약을 확장한다.

### 4.2 Integer sizing

Fractional stock/ETF quantity는 허용하지 않는다. 각 instrument `i`에 대해 economic intent가
weight로 표현되더라도 actual quantity는 execution price와 lot size로 계산한다.

```text
raw_target_quantity_i = target_weight_i × current_NAV / execution_price_i
target_quantity_i = floor(raw_target_quantity_i / lot_size_i) × lot_size_i
order_quantity_i = target_quantity_i - current_adjusted_quantity_i
```

Rounding residual은 actual cash에 남는다. Engine이 목표 비중을 100%로 silent renormalize하거나
fractional share로 맞추면 안 된다. `booksize`는 Qlib accounting의 money scale이다.

### 4.3 ETF semantics

ETF는 actual execution에서는 하나의 physical instrument다. 내부 K200 constituents는 실제
position/order로 확장하지 않는다. Look-through economic exposure는 날짜별 benchmark weight와
physical ETF weight를 이용해 reporting/research layer에서 계산할 수 있다.

## 5. Parquet Artifact Database

### 5.1 목적

Strategy run의 signal, portfolio target, actual execution result와 research evaluation을 재사용
가능한 Parquet file DB로 저장한다.

- ensemble이 member strategy를 매번 다시 실행하지 않고 허용된 artifact를 읽는다.
- reporting은 completed artifact만 읽고 Strategy/Qlib backtest를 다시 실행하지 않는다.
- 동일 run을 재현하고 결과를 audit할 수 있다.

### 5.2 Identity와 reuse semantics

공통 identity:

```text
strategy_id   stable strategy definition identity
run_id        immutable execution instance identity
```

Artifact row key는 `run_id`에 `trade_date`, `instrument_id`, `order_id` 같은
table별 row key를 추가한다. Strategy와 날짜가 같아도 data, config, code 또는 실행 instance가
다르면 서로 다른 `run_id`로 공존한다.

Run provenance에는 최소한 다음을 둔다.

```text
definition_hash
code_version
input_fingerprint       data snapshot, calendar, config를 포함
run_fingerprint         optional semantic deduplication key
result_hash
schema_version
reuse_scope
```

`reuse_scope`는 내부 book 구조가 아니라 stored output의 의미적 약속이다.

- `portable_signal`: signal을 다른 ensemble/research run의 input으로 사용 가능
- `portable_target`: producer가 execution context와 무관함을 명시한 target만 재사용 가능
- `exact_run`: 동일 input/context 재현과 reporting에만 사용 가능

Store가 portability를 추정하지 않는다. 특히 actual feedback에 따라 바뀐 target을 선언 없이
다른 Account context의 target으로 재생하면 안 된다.
`run_fingerprint`는 필요한 경우에만 중복 실행 탐지에 사용하며 primary identity가 아니다.
Content hash는 파일 integrity 검증용이며 `run_id`를 대신하지 않는다.

### 5.3 Table contract

#### `strategy_registry`

Primary key: `strategy_id`

```text
strategy_name
definition_hash
code_version
created_at
```

동일 `strategy_id`를 다른 definition으로 재등록하지 않는다.

#### `strategy_runs`

Primary key: `run_id`

```text
strategy_id, start_date, end_date
status: writing | complete | failed
definition_hash, code_version, input_fingerprint, run_fingerprint, reuse_scope
result_hash, schema_version, created_at, completed_at
```

#### `signals`

Primary key: `(run_id, trade_date, signal_name, instrument_id)`

```text
signal_value: float64
max_observation_date
```

#### `portfolio_targets`

Primary key: `(run_id, trade_date, instrument_id)`

```text
target_weight: float64
```

이는 Strategy가 내놓은 portfolio target artifact다. 실제 order/fill/position과 동일하다고
가정하지 않는다. 내부 optimization 단계를 여러 view로 강제하지 않는다.

#### `orders`

Primary key: `(run_id, trade_date, order_id)`

```text
instrument_id, direction
requested_quantity: int64
```

#### `fills`

Primary key: `(run_id, trade_date, fill_id)`

```text
order_id, instrument_id
filled_quantity: int64
trade_price, trade_value, trade_cost
reason                      legacy filled/partial/unfilled compatibility
reason_code, blocked_by
quantity_after_tradability, quantity_after_volume
quantity_after_position, quantity_after_cash, quantity_after_lot
asset_class, execution_policy, effective_cost_rate, short_enabled
```

#### `positions`

Primary key: `(run_id, trade_date, instrument_id)`

```text
held_quantity: int64
market_value: float64
asset_class
```

#### `account_daily`

Primary key: `(run_id, trade_date)`

```text
cash, nav, portfolio_return, trade_cost, turnover
```

#### `research_evaluations`

Primary key: `(run_id, trade_date, candidate_id)`

```text
score, selected
max_observation_date
diagnostics
```

이 table은 what-if 방식이나 ledger를 규정하지 않는다. 어떤 후보가 어떤 과거 evidence로
평가되어 현재 action이 선택됐는지를 저장한다.

#### `artifact_manifest`

Primary key: `(run_id, table_name)`

```text
schema_version, relative_path, row_count, content_hash
min_trade_date, max_trade_date
```

### 5.4 File layout와 transaction rule

```text
artifact_db/
  strategy_registry/<strategy-id-hash>.parquet
  runs/<run-id-hash>/
    strategy_runs.parquet
    signals.parquet
    portfolio_targets.parquet
    orders.parquet
    fills.parquet
    positions.parquet
    account_daily.parquet
    research_evaluations.parquet
    artifact_manifest.parquet
```

Write는 temporary location에 수행한 뒤 schema, primary-key uniqueness, row count, content hash를
검증하고 atomic publish한다. `status=complete`와 valid manifest를 모두 만족한 run만 읽는다.
동일 `run_id`, provenance, content의 재기록은 idempotent no-op이다. 동일 `run_id`에
다른 provenance나 content를 덮어쓰려 하면 실패한다.

### 5.5 Reporting read model

Reporting은 `signals`, `portfolio_targets`, `orders`, `fills`, `positions`, `account_daily`와 필요한
external benchmark data를 읽는다. Reporting path는 Strategy decision, Qlib Account, Exchange를
생성하거나 실행하지 않는다. 현재 codebase의 `BacktestRun` 형태가 필요하면 reporting adapter가
completed artifact에서 view를 구성한다.

## 6. Goal별 Tests와 완료 Metric

### Goal 0 — Acceptance adapter seam

Tests:

- tests가 production package root의 class/signature를 직접 import하지 않는다.
- configured test-only adapter가 `BackendHarness` capability를 제공한다.

Metric:

- `test_goal_00_public_contract.py` 통과
- production object 이름에 따른 acceptance test 수정 0건

### Goal 1 — Actual feedback closed loop

Fixture: A 가격 `100 → 90 → 81 → 72.9 → 72.9`, 3회 연속 확정 손실이면 stop.

Tests:

- 세 번째 손실을 만든 bar에서는 아직 stop하지 않는다.
- 다음 decision에서 signal과 무관하게 target 0이 되고 actual position이 청산된다.
- volume-limited order는 requested 10, filled 2, legacy reason `partial_fill`,
  structured `reason_code=volume_limited`가 된다.
- actual cash/position/NAV가 Qlib accounting evidence와 reconcile된다.

Metric:

- 모든 feedback row에서 `feedback_date < decision_date`
- `nav = cash + Σ(quantity × execution_price)` 오차 `<= 1e-8`
- Qlib account reconciliation error `<= 1e-8`

### Goal 2 — Data subscription과 state

Tests:

- daily lookback 3과 quarterly available-date lookback 2를 동시에 받는다.
- 모든 observation의 최대 날짜가 decision date보다 작다.
- memory counter가 한 run에서 `1,2,3`, 새 run에서 다시 `1,2,3`이다.

Metric:

- `max_observation_date < decision_date` 위반 0건
- requested native row count mismatch 0건

### Goal 3 — Changing universe

Fixture: A-only → A/B → A exit와 sell block → sell 가능 → A reentry.

Tests:

- entrant는 편입 전 target/position이 없다.
- exit action이 나와도 sell blocked이면 actual position은 남고 reason이 보존된다.
- 가능해진 다음 날 청산되고 reentry가 처리된다.
- state reentry policy가 필요한 시나리오에서 누락하면 fail-fast한다.

Metric:

- universe 밖 신규 target notional 0
- requested order마다 terminal fill/reject reason 정확히 1개

### Goal 4 — Booksize, integer execution, cash, ETF cost

Tests:

- booksize 1,000, execution price 300, target 55%이면 1주와 cash 700이다.
- requested/filled/held quantity column은 int64 계열이다.
- stock sell tax와 ETF sell tax 차이가 actual fills/account에 반영된다.
- ETL fixture가 제공한 2-for-1 factor를 adapter에 적용하면 quantity 2배, price 절반,
  NAV/return 불변이다. Factor/adjusted price의 생성 공식은 ETL contract test가 검증한다.
- `position_unit_factor`가 누락되거나 execution price와 축이 다르면 fail-fast한다.
- factor가 0, 음수, NaN 또는 infinity이면 Qlib 실행 전에 fail-fast한다.
- Cash capacity가 fractional이면 Qlib position에 반영하기 전에 instrument별 KRX lot으로
  내림하고 cash/lot 각 stage quantity를 별도로 기록한다.
- Suspension, upper price limit buy, lower price limit sell은 구체적인 `reason_code`를
  보존한다.
- Stock/ETF fill은 적용한 execution policy와 effective cost rate를 기록한다.

Metric:

- fractional physical quantity 0건
- quantity/lot-size remainder 0
- cost와 NAV reconciliation 오차 `<= 1e-8`

### Goal 5 — Artifact DB와 reporting isolation

Tests:

- 모든 table이 §5 schema와 `run_id` 기반 primary key를 만족한다.
- quantity column은 integer dtype이다.
- manifest row count/hash와 Parquet file이 일치한다.
- 같은 `run_id`/provenance/content write는 idempotent다.
- 같은 `run_id`를 다른 provenance 또는 content에 재사용하면 실패한다.
- 같은 strategy/date라도 다른 `run_id`의 실행 결과는 공존한다.
- reporting bundle과 portable ensemble input load 중 strategy invocation count가 늘지 않는다.
- `exact_run` target을 portable target으로 요청하면 실패한다.

Metric:

- primary-key duplicate 0건
- completed manifest mismatch 0건
- reporting path strategy/backend invocation 0건
- artifact round-trip value mismatch 0건

### Goal 6 — Cached alpha → ensemble → enhanced index

Tests:

- cached signed member alpha를 읽어 ticker level에서 결합한다.
- cancellation fixture의 combined alpha가 0이다.
- final actual orders에는 direct stock과 physical ETF만 있다.
- member strategy는 다시 실행되지 않는다.
- ETF constituents는 physical position/order로 생성되지 않는다.

Metric:

- combined alpha error `<= 1e-12`
- member strategy invocation 0
- actual execution backend evidence = Qlib

### Goal 7 — Historical what-if와 adaptive learning

Rule fixture: 초반 momentum 우세, 후반 reversal 우세.

Tests:

- 초반에는 momentum, 충분한 반대 evidence 이후 reversal을 선택한다.
- 모든 candidate score와 model training row는 decision 이전 data만 사용한다.
- 후보 평가 중 actual order/cash/position delta는 0이다.
- 선택된 action만 actual execution으로 이어진다.
- deterministic ML fixture에서 retrain 이전 model을 유지하고 retrain 이후 relation 변화에
  맞게 action이 바뀐다.

Metric:

- `max_observation_date < decision_date` 위반 0
- hypothetical phase actual order count 0
- hypothetical phase actual cash/position delta 0
- model version change가 scheduled retrain 외에 발생한 횟수 0

### Goal 8 — Resume, determinism, scale

Tests:

- uninterrupted run과 checkpoint-resumed run의 signal/order/fill/position/account/research artifact가
  동일하다.
- 동일 input/seed의 result hash와 order ordering이 동일하다.
- malformed checkpoint와 incomplete artifact run은 fail-fast한다.

Performance는 환경 의존적 pass/fail 숫자를 미리 가정하지 않는다. 다음 reference workload의
baseline report를 먼저 만든다.

```text
2,000 daily bars
300 physical instruments
6 cached/member alpha sources
26 hypothetical candidate actions
```

기록 metric:

- total wall time, bars/second, peak memory
- research evaluation time와 Qlib execution time/bar
- Parquet write/read throughput와 storage size
- checkpoint size와 save/load time

### Goal 9 — Constraint-aware portfolio optimizer

Tests:

- `OptimizationProblem -> OptimizationResult` port가 ETF/direct-stock look-through intent를
  physical target과 cash로 투영한다.
- Hard/soft named constraint, frozen holding, turnover/cost와 risk input을 처리한다.
- Infeasible와 solver failure를 구분하고 독립 post-solve validator가 hard constraint를
  재검증한다.
- Qlib의 actual partial fill holding과 cash가 다음 optimizer call의 current state가 된다.

Metric:

- hard-constraint residual tolerance 위반 0건
- silent fallback 0건
- ETF/direct-stock constituent exposure double counting 0건

### Goal 10 — Actual Qlib ML research path

Tests:

- pandas feature/label/universe가 실제 `StaticDataLoader -> DataHandlerLP -> DatasetH ->
  Qlib Model.fit/predict`를 통과한다.
- Processor fit은 purged train segment에만 제한되고 label horizon purge와 embargo를 적용한다.
- Test prediction은 원 `(datetime, instrument)` axis와
  `max_observation_date < decision_date` audit를 보존한다.
- Prediction은 재학습 없이 읽을 수 있는 portable Parquet signal과 deterministic manifest로
  저장된다.
- Feature/label/universe의 실제 content hash가 immutable dataset snapshot과 일치해야 하며
  `run_dataset_inputs`에 bind된다.

Metric:

- valid/test 변경으로 train processor statistic이 변한 횟수 0
- causality/index mismatch 0건
- model research 중 actual Qlib account mutation 0건

### Cross-cutting graph contract

`ResearchGraph`는 `signal`, `mask`, `active_intent`, `physical_target` type, cycle 금지,
recursive definition hash와 strategy별 단일 physical execution root를 검증한다.
`ResearchGraphExecutor`는 typed node를 topological order로 실행하고 동일 definition/snapshot의
output을 hash-verified Parquet artifact에서 재사용한다.
`ParquetResearchCatalog`는 logical dataset dependency와 run별 immutable snapshot binding을
query 가능한 table로 제공한다.

## 7. Test 실행 정책

Qlib dependency와 integration 실행 비용을 일반 unit suite에서 분리하기 위해 contract
tests는 opt-in이다.

```powershell
uv run --group qlib python -m pytest qlib-integration-codex\tests -q

$env:KWAM_RUN_QLIB_CONTRACTS='1'
uv run --group qlib python -m pytest qlib-integration-codex\tests -q
```

Adapter module은 환경변수로 바꿀 수 있다.

```powershell
$env:KWAM_QLIB_ACCEPTANCE_ADAPTER='kwam_qlib_backend.acceptance_adapter'
```

현재 기대 상태:

- 기본 실행: opt-in 정책에 따라 모든 test skip
- opt-in: 실제 Qlib backend를 사용해 전체 suite green
- 2026-07-22 reference: 53 passed
- adapter import 또는 Qlib dependency가 깨지면 fail-fast

## 8. 구현 순서 제약

1. Capability test를 구현 편의에 맞춰 약화하지 않는다.
2. Test-only normalized harness를 production public API로 복사할 필요는 없다.
3. Precomputed production target replay로 feedback-loop test를 우회하지 않는다.
4. Hypothetical 평가가 actual Qlib accounting state를 바꾸지 않음을 계측한다.
5. Cached artifact의 portability를 추정하거나 과장하지 않는다.
6. Qlib raw object를 Strategy가 직접 의존하도록 만들어 test를 통과시키지 않는다.
7. Matched-capitalization contract가 구현되지 않았거나 실제 borrow/margin data가 없으면 research
   long/short를 실제 stock-loan execution으로 표기하지 않는다.
