# qlibx Product Requirements Document

Status: canonical product requirements
Qlib compatibility baseline: `pyqlib==0.9.7`

이 문서는 qlibx의 정본 제품 요구사항이다. 이전 정본은
[`qlibx-prd-old.md`](qlibx-prd-old.md)에 보존한다. Architecture class, migration phase와 현재 prototype의
우연한 구조는 이 문서의 요구사항이 아니다.

## 1. Product definition

### 1.1 목적

qlibx는 Qlib을 기반으로 다음 흐름을 하나의 재현 가능한 연구 시스템으로 연결하는 Python package다.

```text
project data registration
-> point-in-time materialization
-> signal / ML research
-> stored alpha evidence
-> ensemble
-> long-only physical construction
-> Qlib-native backtest execution
-> portable artifacts and reporting
-> broker-neutral production decision artifact
```

주요 사용자는 quantitative researcher와 그 연구를 지원하는 coding agent다. 사용자는 Qlib internal을
모두 알지 않아도 되지만, 데이터 의미와 전략 가정, benchmark, execution policy와 production authority는
명시적으로 결정해야 한다.

### 1.2 핵심 mental model

```text
qlibx control plane
  data meaning / availability / requirements / config / provenance / policy
             |
             v
compatibility adapters
             |
             v
Qlib runtime kernel
  Handler / Dataset / Model / Strategy / TradeDecision / Executor / Exchange / Account
             |
             v
qlibx evidence plane
  portable artifacts / catalog / reconciliation / analysis / reports
```

Qlib이 이미 제공하고 qlibx 요구와 의미가 일치하는 계산·학습·execution lifecycle은 다시 만들지 않는다.
그러나 native component라는 이유만으로 Qlib default를 qlibx public contract로 노출하지 않는다.

### 1.3 제품 원칙

#### Native-first, contract-first

- Qlib native component가 qlibx 요구를 충족하면 adapter 뒤에서 재사용한다.
- 의미, failure behavior, state authority 또는 artifact portability가 다르면 qlibx가 경계를 소유한다.
- Native reuse는 source line에 대한 추측이 아니라 version-pinned characterization test로 증명한다.
- Qlib upgrade 시 이 문서의 contract를 다시 검증한다. Upstream behavior 변화가 qlibx 의미를 암묵적으로
  바꾸어서는 안 된다.

#### Long-short research와 executable short를 구분한다

Qlib의 long-short 관련 기능은 서로 다른 세 층이다.

1. Prediction/label에서 계산하는 IC, quantile spread와 long-short return diagnostic
2. Basket return을 계산하는 lightweight long-short evaluation
3. Order, Position, Account와 actual fill을 통과하는 portfolio execution

앞의 두 층은 signed factor research에 재사용할 수 있다. Qlib 0.9.7의 표준 stock Position은 negative
quantity를 지원하지 않으므로 세 번째 층의 native short, borrow, margin 또는 securities lending을
의미하지 않는다.

#### Actual state가 authority다

- Requested target은 intention이며 realized holding이 아니다.
- Backtest의 다음 decision은 Qlib actual Position과 dealt quantity를 본다.
- Production의 다음 decision은 외부 OMS가 기록한 confirmed fill과 account snapshot을 본다.
- Partial, rejected, blocked와 expired execution은 숨길 실패가 아니라 canonical result다.

#### Point-in-time과 의미는 data plane에서 강제한다

Strategy가 임의로 source를 읽고 미래 데이터를 걸러내는 방식은 허용하지 않는다. Runtime은 선언된
`available_at <= decision_time`인 observation만 bounded object로 전달한다. qlibx가 보장하는 것은 선언된
availability의 준수이며, 원천 데이터의 경제적 공시 시점이 사실이라는 보장은 user 책임이다.

#### Evidence는 portable하고 producer-independent하다

Qlib pickle object나 process memory는 유용한 runtime representation일 수 있지만 public integration
contract가 아니다. 표준 result는 Qlib process와 producer implementation을 몰라도 읽을 수 있어야 한다.

#### 명시적 실패가 silent fallback보다 우선한다

다음은 성공으로 취급하지 않는다.

- Tradable 종목만 남기고 target weight를 자동 재정규화
- Untradable target을 reason 없이 skip
- Solver constraint를 제거하고 같은 success type 반환
- Solver 실패 후 current portfolio를 target처럼 반환
- Missing analysis dependency를 warning만 남기고 결과를 생략
- Unknown field, instrument 또는 exposure axis를 임의로 제외

### 1.4 지원 범위

현재 product scope는 주식과 ETF를 대상으로 한다.

- Cross-sectional signed alpha research
- Qlib-compatible ML training and inference
- Long-only enhanced-index physical portfolio
- ETF opaque execution과 point-in-time constituent data가 있을 때의 look-through
- Qlib long-only account 안에서의 bounded matched-capitalization compatibility
- Historical backtest와 portable research catalog
- Local-storage-based production decision/OMS boundary

Native borrow, margin, recall, forced buy-in, borrow fee와 broker execution ownership은 범위 밖이다.

## 2. Responsibility boundaries

### 2.1 qlibx가 소유하는 것

- Project initialization, config resolution과 frozen invocation
- Logical dataset registration, schema와 capability binding
- Field semantics, unit, currency, timezone, universe와 tradability distinction
- `available_at`과 no-look-ahead materialization
- StrategyAgent의 bounded context/result contract
- Signed alpha representation, ensemble과 budget semantics
- Physical construction problem/result schema
- ETF/index look-through와 cash residual
- Matched-capitalization의 `A/B/C` accounting과 active performance
- Trigger, mandatory finalization과 resume policy
- 모든 order의 clipping/failure diagnostic 보존
- Portable artifact envelope, lineage, centralized file-backed catalog와 reporting
- Production decision artifact, commit/reconciliation protocol과 monitoring analysis
- Agent-readable documentation, requirement interview와 stage-based errors

### 2.2 Qlib에 맡기는 것

호환성 검증을 통과한 profile에서는 다음 runtime responsibility를 Qlib에 맡긴다.

- Expression, Handler, Dataset와 Processor lifecycle
- Model fit, predict와 Qlib-supported workflow records
- Strategy callback과 execution feedback
- `TradeDecision`과 empty-order hold
- Trading calendar progression과 trade range
- `SimulatorExecutor` 및 필요 시 multi-level execution
- Exchange order handling, requested/dealt quantity와 transaction cost
- Position, cash와 Account mutation
- Bar-end mark-to-market, holding count와 enabled portfolio metrics
- Qlib-native portfolio/trade indicators 중 qlibx 정의와 일치하는 계산

qlibx는 Qlib lifecycle을 호출하는 두 번째 수동 bar engine을 canonical path로 유지하지 않는다. 다만 native
path가 qlibx contract를 충족하지 못하는 동안 기존 path는 characterization oracle과 rollback path로 유지할
수 있다.

### 2.3 User project가 소유하는 것

- Source data와 그 경제적 의미
- Availability, delivery lag와 restatement 가정
- Universe, benchmark, sector/factor definition
- Strategy와 model code
- Risk, cost, constraint와 execution policy
- Project-local extensions와 report composition
- External OMS configuration과 operational approval

### 2.4 외부 production runtime과 OMS가 소유하는 것

- Broker connectivity, authentication과 secret
- Order slicing, pacing, venue, broker order type, retry와 cancel
- Always-on scheduling, account polling과 real-time alert
- Market-session operational control
- Confirmed fill/account snapshot publication

qlibx는 broker SDK wrapper나 always-on OMS가 아니다.

### 2.5 사용하지 않는 Qlib subsystem

Qlib `TaskManager`는 MongoDB와 pickle-oriented task state를 요구하므로 기본 qlibx catalog 또는 parallel
research coordinator로 사용하지 않는다. Qlib Recorder는 runtime sink로 사용할 수 있지만 qlibx portable
catalog를 대체하지 않는다.

### 2.6 금지 behavior

- Qlib fork를 기본 해결책으로 사용
- Negative Qlib stock Position을 native short라고 주장
- Requested target이나 별도 intended ledger를 realized holding으로 취급
- Qlib global provider를 동시 run 사이에서 무보호 mutation
- Current target을 반복 제출해 hold를 흉내 내고 price-drift rebalance를 발생
- Native executor 이전 중 order-level diagnostic을 마지막 한 건만 보존
- Composite account return을 signed active strategy return으로 사용
- Pickle-only result를 public portable artifact라고 주장
- Production `prepare`가 confirmed fill 없이 authoritative strategy state를 advance

## 3. User and agent journey

### 3.1 초기 설정

사용자는 package를 설치한 뒤 project root에서 qlibx project를 초기화한다. Initial setup은 다음을 만든다.

- Project-owned config와 schema version
- Data, artifact, catalog와 extension location
- Agent instruction integration
- Installed documentation과 capability inventory
- Qlib compatibility/version information

설치 후 정상 사용에 qlibx source checkout이나 Qlib internal 탐색을 요구하지 않는다.

### 3.2 Data registration

User 또는 agent는 source를 먼저 opaque하게 등록한 뒤 capability requirement에 맞는 의미를 binding한다.

```text
source inventory
-> bounded sample
-> user-confirmed semantic mapping
-> validation
-> canonical materialization
-> immutable registration result
```

Agent는 field 이름만 보고 의미를 추측하지 않는다. Candidate mapping, derivation, warning과 unresolved
limitation을 보여주고 user confirmation 뒤에만 project config를 변경한다.

### 3.3 Research execution

User는 built-in 또는 project-local Strategy/Model을 frozen config로 실행한다. Runtime은 다음을 기록한다.

- Exact dataset snapshots/references와 availability cutoff
- Universe, benchmark와 execution profile
- Model, strategy와 processor identity/version
- Seed와 deterministic config
- Prediction, signal, target, order, fill, position과 metrics
- Warning, unsupported capability와 terminal status

### 3.4 Stored result reuse

Stored alpha, model prediction과 physical target은 producer를 재실행하지 않고 ensemble, comparison,
optimization, reporting과 다음 StrategyAgent context로 사용할 수 있다.

### 3.5 Agent interaction

Core package는 deterministic contract를 판정한다. Agent는 다음을 담당한다.

- Requirement gap 설명
- Candidate source/field/derivation 비교
- User decision 수집
- Project-local extension 작성
- Validation command 실행과 evidence 요약

Core가 ambiguity를 임의로 해결하거나 agent가 core validation을 우회해서는 안 된다.

## 4. Config-driven workflow

### 4.1 Config의 역할

qlibx workflow는 config-driven이지만 config가 의미를 대신하지 않는다. Frozen run config는 다음을
완전히 resolve해야 한다.

- Logical dataset와 exact snapshot/reference
- Field binding과 derivation
- Availability and decision convention
- Universe and benchmark
- Handler, Processor, Dataset segment와 Model
- Strategy/ensemble/optimizer
- Executor, Exchange와 cost profile
- Trigger, finalization, checkpoint와 reporting
- Artifact location, schema와 provenance

환경변수, mutable global default와 실행 시점의 암묵적 file discovery는 frozen config에 남지 않는다.

### 4.2 Qlib config factory 재사용

Qlib의 `init_instance_by_config`와 class/module/kwargs 표현은 component instantiation에 재사용할 수 있다.
qlibx는 그 위에 다음을 추가한다.

- Allowed extension boundary
- Capability/type validation
- Semantic binding
- Version and source fingerprint
- Safe error classification
- Portable resolved config

### 4.3 `qrun`의 지위

`qrun`은 다음의 고정된 Qlib task workflow를 실행하는 유용한 frontend다.

```text
qlib.init
-> instantiate Model and Dataset
-> model.fit
-> save model/dataset
-> configured Record generation
```

따라서 conventional ML experiment와 Qlib record 생성에는 사용할 수 있다. 하지만 arbitrary DAG,
registration interview, catalog publication, signed accounting, production decision commit을 수행하는 qlibx
전체 workflow engine은 아니다.

qlibx는 필요하면 resolved config를 qrun-compatible task로 materialize할 수 있지만, qrun pickle artifact나
MLflow run을 canonical qlibx result로 간주하지 않는다.

### 4.4 Workflow completion

각 stage는 다음 중 하나로 끝난다.

- `complete`: required outputs와 validation이 모두 존재
- `incomplete`: 일부 output이 있으나 requirement가 충족되지 않음
- `failed`: deterministic contract 또는 runtime failure
- `unsupported`: 선택한 backend/profile이 capability를 제공하지 않음

Warning-and-skip은 required output에 대해 `complete`가 될 수 없다.

## 5. Project, data and capability contracts

### 5.1 Package와 project 분리

Package는 reusable engine, schemas, built-ins와 documentation을 제공한다. Project는 조직·연구별 data,
config, extensions와 artifacts를 소유한다. Package upgrade가 project data나 result를 자동 rewrite하지
않는다.

### 5.2 Logical dataset

Logical dataset은 physical file과 구분되는 versioned contract다. 최소 metadata는 다음과 같다.

- Stable dataset ID and schema version
- Physical source/reference와 immutable fingerprint
- Index/axis와 key uniqueness
- Field names, dtype, unit, currency와 timezone
- Event time, observation time와 `available_at`
- Universe coverage와 missingness
- Registration query/derivation
- Validation result와 warnings

CSV, Parquet, database query 또는 API response는 source일 뿐 그 자체로 logical dataset이 아니다.

### 5.3 Capability requirement와 binding

Strategy, Processor, Model, optimizer와 report는 필요한 input을 capability requirement로 선언한다.

Requirement는 최소한 다음을 포함한다.

- Stable capability ID/version
- Semantic role
- Required fields와 dtype
- Axis, frequency, lookback와 availability rule
- Unit/currency/timezone
- Missingness와 universe completeness
- Optional derivation policy
- Bounded-load expectation

Resolver는 registered dataset만 후보로 사용한다. Exact field name이 같아도 의미가 다르면 자동 binding하지
않는다. User-confirmed mapping만 project-owned config에 기록한다.

### 5.4 Stage-based error contract

Public error는 최소한 다음을 제공한다.

- Stage code
- Failing requirement or artifact
- Original exception type/message when user code failed
- Bounded offending values/examples
- Retryability와 safe recovery guidance

표준 stage는 다음을 포함한다.

- `PROJECT_INIT`
- `DATA_REGISTRATION`
- `CAPABILITY_BINDING`
- `UNIVERSE`
- `MATERIALIZATION`
- `MODEL_TRAIN`
- `STRATEGY_RUN`
- `SIGNAL_ANALYSIS`
- `OPTIMIZATION`
- `EXECUTION`
- `ACCOUNT_RECONCILIATION`
- `ARTIFACT_PUBLICATION`
- `PRODUCTION_RECONCILIATION`

Core는 error를 분류하되 source 정정, derivation 채택 또는 scope 축소 같은 경제적 결정을 대신하지 않는다.

### 5.5 No-look-ahead

모든 observation은 다음을 만족해야 한다.

\[
available\_at \le decision\_time
\]

Runtime은 parent Strategy가 허용한 cutoff보다 늦은 데이터를 child Strategy, inner execution Strategy 또는
model inference에 전달하지 않는다. `NestedExecutor`를 사용해도 이 규칙은 자동으로 성립한다고 가정하지
않으며 adapter와 test로 검증한다.

Qlib의 financial PIT provider와 `P()` operator는 특정 quarterly/annual financial data access에는 사용할
수 있지만 qlibx의 일반 `available_at` contract를 대체하지 않는다.

### 5.6 Universe와 tradability

Universe는 Strategy가 target을 만들 수 있는 instrument set이고 tradability는 특정 execution interval에
BUY/SELL이 가능한지 나타낸다. 두 개를 합치지 않는다.

Universe dataset은:

- Boolean value이며 missing을 false로 해석하지 않는다.
- `(available_at, instrument)`가 유일해야 한다.
- 선언된 axis를 완전히 채워야 한다.
- Point-in-time rule을 따라야 한다.

Universe에서 제외된 realized holding은 사라지지 않는다. Liquidation order가 blocked되면 actual Position에
남고 다음 decision과 reconciliation에 포함된다.

Tradability는 suspension, price limit, volume availability, market session과 instrument metadata에서
결정한다. Unknown 상태를 tradable로 추측하지 않는다.

### 5.7 Daily market materialization

기본 daily OHLCV profile은 source 의미를 확인한 뒤 Qlib-compatible fields를 materialize한다.

- Price convention과 corporate-action adjustment를 명시
- Volume participation을 사용할 때만 volume을 execution capacity로 해석
- Lot/factor가 확인되지 않으면 임의 보정하지 않음
- Default decision convention과 execution/valuation price를 frozen config에 기록
- Source-to-Qlib mapping과 unsupported assumption을 result에 포함

### 5.8 Provider와 process isolation

Qlib provider wrapper와 cache는 process-global state를 사용한다. 서로 다른 calendar, region, provider 또는
dataset materialization을 사용하는 run은 다음 중 하나를 만족해야 한다.

- Process isolation
- Run당 immutable initialization
- 동시 mutation을 막는 검증된 lifecycle

한 run의 provider 등록이나 cache가 다른 run의 결과를 바꾸어서는 안 된다. Same-branch parallel research는
artifact/catalog concurrency뿐 아니라 Qlib global state isolation까지 검증한다.

Qlib 0.9.7에서 custom `CalendarProvider.load_calendar`는 native TradeCalendarManager를 여는 유력한
integration seam이다. 그러나 custom provider를 등록할 수 있다는 source-level 가능성과 qlibx market data로
native backtest가 끝까지 실행된다는 것은 다른 주장이다. End-to-end execution, cache invalidation과 concurrent
run isolation을 검증하기 전에는 canonical provider profile로 채택하지 않는다.

### 5.9 Frozen invocation

실행 전에 effective config와 input identity를 immutable bundle로 동결한다. Run 도중 project config가
바뀌어도 이미 시작한 run의 의미는 바뀌지 않는다. Result는 frozen invocation fingerprint를 참조한다.

## 6. StrategyAgent and decision lifecycle

### 6.1 StrategyAgent definition

StrategyAgent는 bounded market/research context를 받아 side effect 없는 deterministic decision result를
만드는 project-facing contract다. StrategyAgent가 Qlib `BaseStrategy`와 같은 클래스일 필요는 없지만,
execution profile에서는 adapter를 통해 native Qlib Strategy/TradeDecision lifecycle에 참여한다.

Input context는 필요한 범위에서 다음을 포함한다.

- Decision time and permitted information cutoff
- Bounded observations and model predictions
- Universe, benchmark and tradability view
- Actual realized position, cash and prior execution feedback
- Stored research evidence and bounded memory
- Current trigger/finalization state

Result는 다음을 구분한다.

- Observation and reasoning artifact
- Signed intent or physical target
- Executable trade decision
- No-op/hold
- Warning, unsupported requirement or failure

### 6.2 Actual feedback

Native execution에서는 이전 executor result와 current Qlib Position을 다음 Strategy call에 전달한다. Partial
fill과 blocked trade 뒤에도 requested target이 아니라 realized state를 본다.

Production에서는 external OMS의 confirmed result가 도착하기 전까지 prepared decision을 authoritative
strategy memory에 commit하지 않는다.

### 6.3 Observation, decision, execution and monitoring clocks

네 clock은 서로 다른 개념이다.

- **Observation clock:** 새로운 data/state를 관측하는 시점
- **Decision clock:** Strategy가 새 intent를 만드는 시점
- **Execution clock:** order/fill을 처리하는 bar 또는 interval
- **Monitoring clock:** 저장된 account snapshot을 분석하는 시점

Qlib `NestedExecutor`는 outer decision을 higher-frequency inner Strategy/Executor가 실행하는 multi-level
execution clock을 제공할 수 있다. 그러나 arbitrary observation scheduler, qlibx PIT cutoff, child state
isolation 또는 production monitoring service까지 자동 제공하지 않는다.

### 6.4 Hold와 dense state

Strategy가 활성화되지 않은 evaluation point는 zero executable order인 native empty decision으로
표현한다. 이전 target weight를 다시 제출해 암묵적 rebalance를 만들어서는 안 된다.

Dense executor calendar에서는 empty decision이어도 Qlib bar-end position mark가 진행된다. Portfolio metric과
historical position row가 필요한 profile은 executor에서 `generate_portfolio_metrics=True`를 명시해야 한다.
Required monitoring/evidence row를 default에 의존해서는 안 된다.

### 6.5 Trigger와 mandatory finalization

Trigger는 새 decision을 만들지 결정한다. Finalization은 run 종료 시 open state, blocked liquidation,
baseline, cash와 pending artifact를 정리하고 terminal evidence를 만드는 별도 단계다.

- Trigger false는 hold이며 failure가 아니다.
- Finalization은 마지막 trigger 여부와 무관하게 실행한다.
- Finalization trade가 blocked되면 숨기지 않고 realized residual을 기록한다.
- Run end에서 requested target으로 Position을 강제 덮어쓰지 않는다.

### 6.6 Parent/child와 nested research

Child Strategy는 parent가 허용한 lookback, dataset, information cutoff와 state authority를 넘지 않는다.
Qlib nested execution과 qlibx nested research는 같은 개념이 아니다. Historical what-if child는 parent actual
account를 mutate하지 않는다.

### 6.7 ML과 belief update

Model은 Qlib Dataset segment와 Processor lifecycle을 사용할 수 있다. Fit은 train segment만 사용하고,
validation/test leakage를 막는다. Purge/embargo 또는 label horizon overlap이 필요한 model은 requirement로
선언한다.

StrategyAgent memory나 online belief update는 deterministic input/result와 commit boundary를 가져야 한다.
Backtest rollback 또는 production rejection 뒤에도 unconfirmed state가 남아서는 안 된다.

### 6.8 Checkpoint와 resume

Checkpoint는 단순 Position pickle이 아니라 다음 authority를 함께 보존한다.

- Actual Position, cash and accumulated execution state
- Strategy memory and prior feedback cursor
- Calendar/execution cursor
- Baseline/endowment state when applicable
- Frozen invocation and input identity
- Artifact publication state
- Qlib/qlibx compatibility version

Resume 직후 state와 uninterrupted run state가 reconcile되어야 한다. Initial/previous NAV denominator와
accumulated metrics를 별도로 검증한다.

## 7. Signal, factor and model research

### 7.1 Canonical alpha result

Signed alpha result는 최소한 다음을 포함한다.

- Decision time and instrument
- Raw signal and transformed signal
- Signed weight or exposure intent
- Universe/coverage and missingness
- Input lineage and operation lineage
- Budget convention
- IC/RankIC, spread, turnover and applicable exposure diagnostics
- Terminal status and warnings

Negative signal/weight는 research intent일 수 있으며 Qlib executable negative Position을 의미하지 않는다.

### 7.2 Built-in signal operations

기본 operation은 다음 범주를 지원한다.

- Cross-sectional rank, percentile and z-score
- Winsorization/clipping and robust scaling
- Missing/inf handling with explicit policy
- Lag, rolling statistics and decay
- Industry/sector demeaning
- Market/benchmark beta residualization
- User-supplied factor neutralization
- Hump/barrier and turnover control
- Per-name cap and budget rescaling

Qlib Processor가 같은 semantics를 제공하는 rank, z-score, clipping, missing/inf와 rolling operation은
재사용할 수 있다. qlibx는 operation ID/version, axis, availability cutoff, fitted-state scope와 lineage를
붙인다. Industry neutralization, beta residualization, custom decay, cap와 budget semantics가 Qlib에 없거나
다르면 qlibx built-in 또는 project extension이 제공한다.

### 7.3 Signal diagnostics

Qlib `SignalRecord`, `SigAnaRecord`와 alpha evaluation의 prediction, label, IC, RankIC와 quantile long-short
spread 계산은 semantics parity 후 재사용할 수 있다. 이 결과를 executable short simulation이라고 표시하지
않는다.

Metric parity는 label convention, quantile weighting, missing-value handling, annualization과 transaction
cost 포함 여부를 비교해 검증한다.

### 7.4 Neutralization과 exposure

Neutralization operation과 사후 exposure measurement를 구분한다. Required market, benchmark, industry 또는
factor data가 없으면 exposure를 추측하지 않고 capability gap을 반환한다.

표준 analysis는 data가 있을 때 다음을 제공한다.

- Net/gross and long/short exposure
- Market or benchmark beta
- Industry/sector exposure
- User-supplied factor exposure
- Intended versus realized exposure
- Residual exposure and coverage

### 7.5 Fixed와 flexible budget

- **Fixed budget:** target gross/net 또는 total allocation을 명시적으로 채운다.
- **Flexible budget:** signal strength가 약하거나 instrument가 unavailable하면 unused budget을 cash/residual로
  보존한다.

Untradable instrument를 제외한 뒤 나머지 weight를 자동 확대하는 behavior는 flexible budget을 위반한다.

### 7.6 Weight snapshot

각 weight snapshot은 normalization basis, gross/net, cash/residual, cap, universe와 decision time을 함께
저장한다. Weight만 저장하고 그것이 active, benchmark-relative 또는 physical인지 추측하게 하지 않는다.

## 8. Research workspace and catalog

### 8.1 Workspace

Project는 exploratory files를 둘 수 있지만 canonical research result는 scratch file 경로나 notebook state가
아니라 catalog publication을 통해 식별한다. Example directory structure는 convention일 뿐 package contract가
아니다.

### 8.2 Centralized file-backed catalog

모든 session과 agent에게 하나의 queryable project-local catalog로 보여야 한다. MongoDB나 always-on service를
기본 요구하지 않는다.

Catalog는 다음을 저장하거나 참조한다.

- Run/trial identity and terminal status
- Frozen invocation and environment compatibility
- Dataset/model/strategy/processor identity
- Portable stage artifacts
- Metrics, diagnostics and warnings
- Parent/member lineage
- Publication timestamp and content fingerprint

### 8.3 Publication semantics

- Artifact payload를 먼저 완성하고 검증한 뒤 catalog visibility를 commit한다.
- Crash로 incomplete payload가 생기면 complete record로 보이지 않는다.
- 같은 identity와 같은 content의 중복 publication은 idempotent할 수 있다.
- 같은 identity와 다른 content는 conflict이며 덮어쓰지 않는다.
- Stale agent가 최신 record를 overwrite하지 못한다.
- Reporting은 새 canonical research result를 암묵적으로 만들지 않는다.

### 8.4 Identity와 reuse

Identity는 단순 이름이 아니라 input, config, code/component와 semantics fingerprint를 포함한다. Stored result를
reuse할 때 consumer는 producer implementation을 몰라도 schema, compatibility와 lineage를 검사할 수 있어야
한다.

### 8.5 Prior research와 orthogonality

새 alpha proposal 전에는 stored catalog에서 유사한 hypothesis, input, transformation과 empirical result를
검색할 수 있어야 한다. Orthogonality는 다음을 구분한다.

- Semantic novelty
- Signal/return correlation and overlap
- Existing ensemble에 대한 incremental contribution

단순 low correlation을 독립적인 경제적 alpha라고 자동 판정하지 않는다.

### 8.6 Parallel-agent behavior

최소 세 independent session이 worktree 없이 같은 branch/project에서 연구할 수 있어야 한다. Config edit,
publication, duplicate identity와 stale update에 대해 deterministic conflict behavior를 제공한다. Qlib global
provider state가 필요한 run은 process isolation requirement를 따른다.

### 8.7 Qlib Recorder adapter

Qlib Recorder/MLflow experiment는 model fit과 native record의 runtime sink로 사용할 수 있다. Canonical catalog
publication 전에는 다음 adapter를 통과한다.

- Pickle model/object와 portable payload 분리
- JSON/Parquet/Arrow-compatible export
- Required record completeness check
- Qlib run ID와 qlibx identity 연결
- Provenance and schema validation

Qlib Recorder가 저장했다는 사실만으로 publication complete가 되지 않는다.

## 9. Ensemble and physical construction

### 9.1 Stored-alpha ensemble

Ensemble은 member strategy를 다시 실행하지 않고 compatible stored alpha를 결합한다. 다음을 보존한다.

- Member identity and full lineage
- Member allocation and effective dates
- Ticker-level netting
- Gross/net and flexible budget semantics
- Missing member/coverage behavior
- Member and ensemble attribution

Ensemble output은 benchmark-relative signed active intent이며 아직 executable physical portfolio가 아니다.

### 9.2 Construction problem

Enhanced-index constructor는 다음을 입력으로 받는다.

```text
benchmark constituent exposure
+ desired signed active exposure
+ current physical holdings and cash
+ stock/ETF look-through matrix
+ tradability and instrument bounds
+ transaction cost and risk inputs
+ hard/soft constraints
-> stock / ETF / cash physical target
```

Constructor는 long-only physical target을 만든다. Active underweight는 physical negative holding이 아니라
benchmark보다 작은 non-negative exposure로 구현한다.

### 9.3 Required result

Result는 최소한 다음을 제공한다.

- Physical target weights and cash target
- Constituent-level look-through exposure when data exists
- Desired versus achieved active exposure
- Expected trades and costs
- Turnover and risk diagnostics
- Every constraint value, bound, slack and binding status
- Post-solve validation
- Solver/backend/version metadata
- Explicit `optimal`, `infeasible`, `soft_relaxed`, `solver_error` 또는 `unsupported` status

Hard infeasibility, soft relaxation, solver failure와 backend unsupported를 같은 결과로 합치지 않는다.

### 9.4 Optimizer backend boundary

Optimizer backend는 교체 가능하지만 모두 같은 qlibx problem/result contract를 만족해야 한다. Backend가
제공하지 않는 semantics를 wrapper가 조용히 추측해서는 안 된다.

Qlib 0.9.7 `EnhancedIndexingOptimizer`는 expected active return과 tracking risk, benchmark/factor deviation,
turnover limit을 가진 fully-invested stock optimizer다. 다음 이유로 qlibx constructor와 수학적으로 1:1인
core가 아니다.

- Desired signed exposure tracking과 expected-return maximization의 objective가 다름
- Explicit cash와 flexible residual 없음
- ETF physical/look-through axis 분리 없음
- General named hard/soft constraint와 portable diagnostics 없음
- Turnover-constrained solve 실패 시 해당 constraint를 제거해 재시도
- 최종 실패 시 current weight를 반환할 수 있음

따라서 comparison baseline 또는 conditional backend로만 취급한다. 현재 environment의 solver availability를
포함한 characterization과 post-solve validation 없이는 채택하지 않는다. Unchanged current weight는 명시된
legitimate optimum이 아닌 한 solver success가 아니다.

Compatibility baseline인 Qlib 0.9.7 구현은 ECOS solver를 직접 선택한다. `cvxpy` package가 설치되어 있다는
사실은 ECOS availability를 보장하지 않는다. Backend activation 전에 exact solver를 preflight하고, unavailable
solver나 failed solve를 current-weight target으로 바꾸지 않고 explicit failure로 승격한다.

### 9.5 ETF와 look-through

ETF는 constituent data 없이 opaque physical instrument로 거래할 수 있다. Look-through가 필요한 경우에만
point-in-time ETF/index constituent dataset을 사용한다.

- Qlib Account의 ETF physical holding과 constituent exposure는 별도 result다.
- Constituent data가 없으면 exposure를 생성하거나 추측하지 않는다.
- Constituent membership/weight도 `available_at` rule을 따른다.
- Look-through matrix의 physical axis와 constituent axis를 명시적으로 검증한다.

### 9.6 Tradability, lot과 optimization

Optimization과 execution을 혼동하지 않는다. Constructor는 current untradable holding을 freeze하거나
explicit result로 다루고, execution은 price limit, volume, cash와 lot에 따라 actual fill을 만든다.

Post-optimization quantity conversion과 execution clipping 뒤에는 desired-versus-realized residual을 다시
계산한다. Lot rounding이나 blocked trade를 optimizer success 안에 숨기지 않는다.

## 10. Qlib execution and signed compatibility

### 10.1 Native execution lifecycle

Canonical historical execution path는 다음과 같다.

```text
qlibx context and policy
-> Qlib-compatible Strategy adapter
-> TradeDecision (orders or empty hold)
-> SimulatorExecutor / optional NestedExecutor
-> ScenarioExchange
-> Qlib Account and Position
-> qlibx diagnostic and artifact adapters
```

Strategy, decision, executor, exchange와 account 역할을 하나의 qlibx for-loop에 합치지 않는다.

### 10.2 ScenarioExchange

Project market data, stock/ETF cost, lot, tradability와 volume policy를 Qlib Exchange extension point로 제공한다.
ScenarioExchange는 Qlib order/fill/account lifecycle을 우회하지 않는다.

Exchange result는 모든 order에 대해 다음 stage를 보존한다.

- Requested amount
- After tradability
- After volume/capacity
- After position limit
- After cash limit
- After lot rounding
- Final dealt amount and price/cost
- Blocking/clipping reason

Native executor가 한 decision에서 여러 order를 처리해도 마지막 diagnostic만 남겨서는 안 된다.

### 10.3 Order generation

Qlib weight-to-order building block은 semantics가 맞을 때 재사용할 수 있다. 다음 default는 qlibx public
behavior가 될 수 없다.

- Tradable target만 남긴 후 automatic renormalization
- Untradable instrument silent skip
- Process-global random seed mutation
- Negative target weight의 모호한 처리
- Cash/flexible budget의 암묵적 소진

Order generation 결과는 target-to-order residual과 reason을 제공해야 한다. 같은 bar에서 sell proceeds를
buy에 사용할지는 explicit serial/parallel execution policy다.

### 10.4 Qlib long-only limitation

Qlib 0.9.7의 표준 stock Position은 미보유 SELL과 보유 수량 초과 SELL을 허용하지 않는다. qlibx는 Qlib이
native short를 지원한다고 주장하지 않는다.

Signed research를 account execution으로 옮길 때 현재 compatibility mode는 matched capitalization이다.

```text
A = realized signed active quantity
B = non-negative baseline/endowment quantity
C = Qlib composite quantity

C = B + A
A = C - B
B >= 0
C >= 0
```

Qlib Account는 `C`만 소유한다. qlibx는 `B`와 active/composite reconciliation을 소유한다.

### 10.5 Canonical dynamic matched capitalization

Full signed compatibility mode는 dynamic lifecycle을 지원한다.

1. Actual active NAV, configured short capacity, execution price와 lot으로 required baseline을 계산한다.
2. 실제로 short capacity가 필요한 시점에 missing baseline을 activation/top-up한다.
3. Matching quantity와 cash change를 같은 event로 처리해 NAV-neutrality를 검증한다.
4. Qlib에는 `C_target = B + A_target`만 제출한다.
5. Economic short 진입은 Qlib Exchange를 통과하는 actual underlying SELL이다.
6. Realized active quantity는 dealt composite quantity로부터 `A_realized = C_realized - B`로 복원한다.
7. Blocked cover 동안 필요한 baseline을 유지한다.
8. Actual cover fill 이후 policy에 따라 baseline을 release하거나 retain한다.

Baseline reserve가 부족하거나 `C_target < 0`이면 명시적으로 실패한다. Signed intended ledger를 actual fill
source로 사용하지 않는다.

Qlib 0.9.7에는 exchange fill 없이 중간에 stock/cash를 함께 주입하는 표준 administration hook이 없다.
Dynamic implementation은 qlibx-owned capitalization event와 account metric reconciliation을 제공해야 하며,
Strategy가 journal 없이 `current_position`을 직접 mutation하는 방식을 허용하지 않는다.

### 10.6 Optional static initial-endowment profile

Static profile은 run 시작 전에 fixed baseline quantity를 Qlib initial Position에 넣는 bounded compatibility
mode다. Native lifecycle migration과 제한된 hypothetical research에는 유용하지만 dynamic mode를 대체하지
않으며 full signed-execution acceptance를 자동 충족하지 않는다.

Static profile은 반드시 다음을 선언한다.

- Fixed endowment universe
- Ticker별 fixed maximum short quantity 또는 검증된 NAV/price stress capacity
- Corporate action/factor adjustment policy
- Capacity breach의 explicit failure
- Universe 밖 short 금지
- Starting cash, initial stock value와 starting composite NAV
- Active/composite performance decomposition

Baseline은 weight capacity가 아니라 quantity capacity다. Price 하락, active NAV 상승 또는 cap 변경으로
필요 quantity가 증가할 수 있다. `C_target < 0`을 clipping하지 않는다.

### 10.7 Initial-position accounting

Qlib Account는 `init_cash`를 Position cash이자 첫 portfolio-return denominator로 사용한다. Initial stock
position이 있으면 starting account value는 cash만이 아니라 marked holdings를 포함한다.

따라서 initial-position 또는 resume profile은 다음을 검증해야 한다.

- Starting composite NAV = starting cash + marked physical holdings
- 첫 metric denominator가 starting composite NAV와 일치
- Baseline, active and composite NAV reconciliation
- 첫 bar의 zero-return/no-price-change parity
- Resume 직후 metric이 uninterrupted run과 일치

Qlib default field 값을 그대로 사용해 첫 return 왜곡을 허용하지 않는다.

### 10.8 Performance와 limitation

Composite account에는 baseline inventory와 reserve가 포함되므로 composite return은 canonical signed active
return이 아니다. Active performance는 active denominator를 사용하고 baseline price movement와 cash를
분리해 PnL을 reconcile한다.

Matched capitalization은 다음을 모델링하지 않는다.

- Locate/borrow availability
- Margin/collateral
- Recall and forced buy-in
- Borrow fee
- Securities-lending capacity

Result와 report에 이 limitation을 명시한다.

### 10.9 Settlement와 corporate action

Settlement, adjusted price, quantity factor, delisting과 corporate action semantics가 확인되지 않으면 KRX
또는 broker behavior를 추측하지 않는다. Qlib settlement option을 사용하기 전에 selected market convention과
characterization parity를 검증한다.

## 11. Artifacts, analysis and reporting

### 11.1 Portable artifact envelope

모든 complete stage result는 최소한 다음 envelope를 갖는다.

- Artifact type and schema version
- Producer and component version
- Frozen config/input fingerprint
- Time range and decision cutoff
- Axis, unit, currency and timezone
- Portable payload or immutable payload reference
- Coverage, warning, diagnostic and terminal status
- Parent/member lineage

초기 portable format은 metadata/config에 JSON, table/matrix에 Parquet 또는 Arrow-compatible data를 사용한다.
Model binary나 Qlib pickle은 별도 non-portable payload로 reference할 수 있다.

### 11.2 Standard artifacts

표준 artifact는 다음을 포함한다.

- Dataset registration/materialization
- Model fit and prediction
- Signal and signed weight
- Ensemble intent
- Optimization problem/result
- Physical target
- Trade decision and order
- Fill and execution diagnostic
- Position/account snapshot
- Matched-capitalization event and reconciliation
- Checkpoint/resume state
- Analysis tables and report manifest
- Production prepared decision and OMS result

### 11.3 Analysis와 report 분리

Analysis module은 stored artifacts에서 performance, risk, exposure, attribution, turnover, cost와 reconciliation을
계산한다. Renderer는 analysis output을 표·그래프·문서로 표현한다. Renderer가 canonical research calculation을
숨겨서 다시 수행하지 않는다.

### 11.4 Built-in analysis

Data가 있을 때 다음을 제공한다.

- Signal IC/RankIC, spread, coverage and turnover
- Portfolio performance and risk
- Market/benchmark/industry/factor exposure
- Cost, fill and desired-versus-realized reconciliation
- Member/ensemble/optimizer attribution
- Physical/look-through reconciliation
- Composite/baseline/active signed reconciliation
- Path-dependency and regime diagnostics

### 11.5 Monitoring analysis

Historical backtest에서는 dense account artifacts를, production에서는 external OMS가 저장한 account snapshot을
읽는다. Monitoring analysis는 pure artifact consumer로 구현할 수 있다. Snapshot polling, always-on scheduler와
real-time alert는 외부 runtime 책임이다.

Observation, decision, execution과 monitoring clock을 하나의 Strategy loop로 강제하지 않는다.

## 12. Extensibility and agent-readable product surface

### 12.1 Public extension points

Built-in은 일관성과 onboarding을 제공하고 project-local extension은 조직별 자율성을 제공한다. 다음은
documented extension point다.

- Dataset loader/materializer
- Processor and signal transform
- Model
- StrategyAgent
- Ensemble allocator
- Optimizer backend
- Exchange cost/tradability policy
- Analyzer and reporter
- Production artifact adapter

Extension은 qlibx installed package를 수정하지 않고 project 안에서 작성·등록할 수 있어야 한다.

### 12.2 Extension contract

각 extension은 다음을 선언한다.

- Stable type/ID/version
- Input capability requirements
- Output artifact schema
- Determinism and fitted state
- Availability/lookback behavior
- Failure contract
- Compatibility range

Undocumented private import를 public extension surface로 사용하지 않는다.

### 12.3 Qlib native component exposure

Qlib class를 project config에서 직접 지정할 수 있더라도 qlibx compatibility adapter와 validation을
우회하지 않는다. Native class는 다음 중 하나로 분류한다.

- `native-compatible`: qlibx semantics와 parity 검증 완료
- `adapted`: wrapper/translator 뒤에서 사용
- `analysis-only`: execution authority 없음
- `unsupported`: selected product profile과 충돌

### 12.4 Agent-readable documentation

Installed documentation만으로 agent가 다음을 찾을 수 있어야 한다.

- Project discovery and status
- Available capabilities and extensions
- Config schema and examples
- Artifact schemas and loaders
- Error stages and recovery guidance
- Validation commands
- Qlib compatibility limitations

Documentation은 source checkout이나 hidden test를 전제로 하지 않는다.

### 12.5 Instruction/skill integration

qlibx는 selected coding-agent target에 project instruction 또는 skill을 생성할 수 있다. Generated instruction은
thin routing layer이며 정본 product facts를 복제해 stale하게 만들지 않는다. User는 하나 이상의 target을
선택할 수 있고, 생성 결과와 변경 내용을 확인할 수 있어야 한다.

### 12.6 Local module example

User/agent는 installed public contract만 사용해 exponential decay transform, exposure analyzer 또는 custom
reporter를 project-local file로 추가할 수 있어야 한다. Core package source나 canonical artifact schema를
fork하지 않는다.

## 13. Production decision and OMS boundary

### 13.1 범위

Production scope는 durable local artifacts를 통해 외부 OMS와 통신하는 broker-neutral decision runtime이다.
qlibx는 direct broker API owner가 아니다.

### 13.2 Prepared decision

Strategy evaluation은 immutable prepared decision을 만든다.

- Decision ID and portfolio/account ID
- Strategy/model/config/input identity
- Decision time and information cutoff
- Broker-neutral target position, quantity 또는 order intent
- Validity window and target tolerance
- Price/quantity/risk boundaries
- Expected current-state fingerprint
- Required OMS result schema

Prepared decision 생성만으로 authoritative strategy state를 advance하지 않는다.

### 13.3 Outbox와 OMS inbox

qlibx는 atomic local outbox publication을 제공한다. External OMS는 decision을 읽고 execution을 수행한 뒤
confirmed result/account snapshot을 inbox에 기록한다.

OMS result는 최소한 다음을 포함한다.

- Decision ID and idempotency identity
- Accepted/rejected/partial/expired status
- Requested and filled quantity
- Fill price/cost/time
- Remaining quantity and reason
- Account/holding snapshot reference

### 13.4 Commit boundary

qlibx는 OMS result와 actual account snapshot을 검증하고 reconciliation이 통과한 뒤 completed checkpoint를
commit한다. Delta는 이전 requested target이 아니라 actual holding에서 계산한다.

```text
actual holdings
-> prepare target/delta
-> external execution
-> confirmed fills and snapshot
-> reconcile
-> commit strategy state
```

Rejected/partial/zero fill 뒤에는 실제 상태만 advance한다.

### 13.5 Concurrency와 idempotency

초기 contract는 portfolio/account마다 동시에 하나의 in-flight decision만 허용한다. 같은 decision/result의
중복 delivery는 idempotent해야 한다. Supersede/merge semantics는 별도 roadmap이며 암묵적으로 지원하지
않는다.

### 13.6 Execution policy

Validity window, target tolerance, partial completion, market close와 expiry behavior를 decision 또는 project-owned
OMS policy에 명시한다. “장중 최대한 실행” 같은 모호한 문장을 executable policy로 사용하지 않는다.

### 13.7 Storage와 recovery

Local storage는 임시 file-drop이 아니라 durable protocol이다.

- Atomic write/rename or equivalent visibility boundary
- Schema/version validation
- Checksum/content identity
- Duplicate and stale-result handling
- Crash recovery and replay
- Completed checkpoint immutability
- Audit trail and retention policy

### 13.8 Production monitoring

OMS는 actual account snapshot을 선택된 주기로 저장할 수 있다. qlibx는 그 artifact를 읽어 desired-versus-actual,
risk, stale decision과 reconciliation 상태를 분석한다. Polling과 alert delivery는 외부 runtime이 소유한다.

## 14. Acceptance criteria

### P0 — Installation and agent onboarding

- Fresh project에서 installed documentation만으로 init, status와 capability discovery를 수행한다.
- Selected agent instruction/skill을 생성하고 변경 내용을 확인한다.
- Source checkout이나 private import 없이 public extension surface를 찾는다.
- Qlib version과 compatibility profile을 확인할 수 있다.

### P1 — Data registration and PIT

- Opaque source를 bounded inventory한 뒤 user-confirmed semantic binding으로 등록한다.
- Canonical materialization과 Qlib-compatible mapping을 생성한다.
- Invalid datetime, duplicate `(available_at, instrument)`와 incomplete universe를 registration에서 거부한다.
- Strategy/Model/inner execution call은 `available_at <= decision_time`을 위반하지 않는다.
- Frozen run은 시작 후 project config 변경의 영향을 받지 않는다.
- 서로 다른 provider/calendar run이 global state를 통해 서로 오염되지 않는다.

### P2 — Config-driven model and StrategyAgent

- Resolved config로 Handler/Dataset/Processor/Model/Strategy를 instantiate한다.
- Conventional Qlib ML task는 qrun-compatible workflow로 실행할 수 있다.
- qrun output을 portable qlibx artifact로 adapt한다.
- Actual realized position과 prior execution feedback가 다음 decision에 전달된다.
- Parent/child lookback과 PIT boundary를 보존한다.

### P3 — Signed signal research

- Signed alpha, weight, budget와 lineage를 portable artifact로 저장한다.
- Qlib-native IC/RankIC/quantile spread를 semantics parity 후 재사용한다.
- Analysis long-short와 executable short를 명확히 구분한다.
- Built-in 또는 extension으로 neutralization, exposure, decay, cap와 budget operation을 구성한다.
- Missing capability를 silent skip하지 않는다.

### P4 — Research catalog and parallel sessions

- Stored result를 strategy rerun 없이 query/reuse한다.
- Content/provenance conflict와 incomplete publication을 구분한다.
- Prior alpha와 orthogonality evidence를 조회한다.
- 최소 세 session이 같은 project/branch에서 deterministic publication behavior를 보인다.
- Qlib Recorder pickle 없이도 standard artifact를 읽을 수 있다.

### P5 — Ensemble and physical construction

- Stored alpha를 member lineage와 함께 ensemble한다.
- Signed active intent를 long-only stock/ETF/cash target으로 변환한다.
- ETF를 opaque physical instrument로 실행하고 constituent data가 있을 때만 look-through를 계산한다.
- Physical holding과 constituent exposure를 별도 result로 유지한다.
- Hard infeasibility, soft relaxation, solver error와 unsupported backend를 구분한다.
- Constraint, cost, turnover, cash와 post-solve validation을 관측한다.
- Backend의 silent constraint removal/current-weight fallback을 success로 허용하지 않는다.

### P6 — Native Qlib execution

- Canonical path가 Qlib Strategy/TradeDecision/Executor/Exchange/Account lifecycle을 사용한다.
- Trigger false는 empty-order hold이며 target 재제출 rebalance를 만들지 않는다.
- Dense profile에서 portfolio metrics를 명시적으로 활성화하고 no-trade bar의 account/position row를 만든다.
- Partial/blocked fill 뒤 다음 decision이 actual Qlib Position을 본다.
- 한 decision의 모든 order-level clipping/failure diagnostic을 보존한다.
- Native path와 characterization oracle의 long-only result/account parity를 검증한다.
- Nested execution에서도 PIT boundary와 account metric frequency를 검증한다.

### P7 — Signed execution compatibility

- Dynamic matched capitalization이 `C=B+A`, `B>=0`, `C>=0`을 유지한다.
- Activation/top-up/release event가 NAV-neutral이고 auditable하다.
- Active short 진입/cover는 Qlib actual SELL/BUY dealt quantity로만 변한다.
- Blocked cover 뒤 baseline을 유지하고 actual cover 뒤에만 release한다.
- Insufficient reserve와 negative composite target은 명시적으로 실패한다.
- Active performance를 composite denominator로 희석하지 않는다.
- Static profile은 fixed universe/quantity capacity, starting NAV와 breach를 명시하며 full P7로 가장하지 않는다.
- Initial position과 resume 첫 metric denominator가 marked starting NAV와 일치한다.

### P8 — Artifacts, extensions and reporting

- Complete stage result를 documented JSON/Parquet/Arrow-compatible format으로 export한다.
- Project-local Processor/Analyzer/Reporter가 package 수정 없이 동작한다.
- Stored artifact에서 research rerun 없이 report를 만든다.
- Analysis calculation과 rendering을 분리한다.
- Performance, exposure, cost, optimizer와 signed reconciliation을 제공한다.
- Monitoring analysis는 stored account snapshot의 pure consumer로 동작한다.

### P9 — Production artifact boundary

- Prepared decision을 durable outbox에 atomic publish한다.
- Prepare는 authoritative strategy state를 commit하지 않는다.
- External OMS result와 actual account snapshot을 reconcile한 뒤에만 completed checkpoint를 commit한다.
- Partial/rejected/expired/duplicate/stale result를 명시적으로 처리한다.
- Delta는 actual holding에서 계산한다.
- Portfolio당 single in-flight decision contract와 crash recovery를 검증한다.
- Broker connectivity, scheduling과 real-time alert가 qlibx 밖의 책임임을 유지한다.

## 15. Compatibility gates and validation

### 15.1 Qlib upgrade gate

Qlib version을 바꾸기 전에 최소한 다음을 검증한다.

- Strategy feedback and empty decision behavior
- Calendar/provider registration and cache isolation
- Custom calendar provider의 end-to-end native backtest
- Executor order sequencing and account update timing
- Portfolio metric frequency and initial denominator
- Position negative-quantity rejection
- Exchange cost/lot/tradability behavior
- NestedExecutor account sharing and PIT adapter
- Recorder/Processor metric parity
- Optimizer solver, fallback and status behavior
- ECOS availability가 없을 때의 explicit optimizer failure

### 15.2 Native migration gate

Manual lifecycle을 제거하기 전에 다음 evidence가 있어야 한다.

- Existing long-only characterization fixtures의 parity
- Hold/no-trade bar parity
- All-order diagnostics preservation
- Trigger/finalization parity
- Checkpoint/resume parity
- Dynamic matched-capitalization reconciliation
- Bounded performance regression
- Rollback path

### 15.3 Test philosophy

Prototype implementation과 test는 이 PRD의 evidence다. Prototype의 accidental class/layout을 requirement로
승격하지 않는다. 테스트는 public behavior, accounting identity, information boundary와 artifact contract를
검증한다.

## 16. Out of scope and roadmap

### 16.1 현재 범위 밖

- Native short Position/Account in Qlib
- Broker borrow/locate/margin/recall/fee modeling
- Futures, options, bonds and derivatives lifecycle
- Direct broker API and secret management
- Always-on OMS, scheduler and real-time alert delivery
- Distributed MongoDB task orchestration as a package prerequisite
- Unbounded autonomous strategy state mutation

### 16.2 Asset-class expansion

새 asset class는 instrument ID만 추가해서 지원하지 않는다. Valuation, quantity/contract unit, settlement,
expiry, margin, corporate action, cost와 risk semantics를 별도 capability로 정의해야 한다.

### 16.3 AI-defined Strategy

AI가 runtime에서 직접 strategy logic을 변경하거나 decision을 생성하는 기능은 future scope다. 도입 시 bounded
input, deterministic replay, approval, safety limit, provenance와 commit boundary를 먼저 정의한다.

### 16.4 Optimizer backend expansion

Commercial risk model, alternative solver와 differentiable optimizer는 같은 qlibx problem/result contract 뒤에
추가할 수 있다. Backend adoption은 feature count가 아니라 semantic parity, explicit failure와 reproducibility로
판정한다.

### 16.5 Production expansion

Multiple in-flight decisions, supersede/merge, high-frequency broker feedback와 service deployment는 initial local
artifact protocol이 안정된 뒤 별도 product decision으로 다룬다.

## 17. Product-level conclusion

qlibx의 차별점은 Qlib을 대체하는 데 있지 않다. Qlib의 학습·전략·execution runtime을 최대한 사용하면서
그 위와 아래에 Qlib이 제공하지 않는 의미·정책·증거 계약을 제공하는 데 있다.

```text
Reuse Qlib for runtime mechanics.
Use qlibx for meaning, authority, compatibility and evidence.
```

Native reuse가 더 짧은 코드라는 이유만으로 qlibx contract를 약화해서는 안 된다. 반대로 qlibx contract를
지킨다는 이유로 Qlib lifecycle을 다시 구현해서도 안 된다.
