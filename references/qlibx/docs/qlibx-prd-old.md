# qlibx Product Requirements Document

## 1. 개요

- Product: `qlibx`
- 정의: Qlib-powered adaptive alpha research and enhanced-index framework
- 상태: 초기 요구사항
- 전신: `qlib-integration-codex`
- 기본 운영 모델: 한 repository, 한 shared branch, 여러 agent의 병렬 연구

이 문서는 `qlibx`가 제공해야 하는 결과와 public interface를 정의한다. 구체적인 내부 구현은
별도의 architecture 문서가 소유한다.

### 1.1 Package와 project의 경계

`uv add qlibx`로 설치되는 package는 project data, organization-specific dataset definition,
strategy config 또는 prebuilt alpha config를 포함하지 않는다. Package는 다음 reusable product
surface만 제공한다.

- File-backed data source와 logical dataset contract
- Config schema와 validation
- Qlib-compatible research, strategy, ensemble, optimizer와 execution interface
- CLI와 Python API
- 사람이 읽는 documentation과 agent가 읽을 수 있는 machine-readable schema
- Project bootstrap과 data registration workflow

Project-specific config는 사용자의 repository가 소유한다. `qlibx` upgrade는 사용자가 등록한
dataset이나 strategy config를 덮어쓰지 않아야 한다.

다음은 하나의 **비구속적 예시**다. `qlibx` product가 이 directory 이름이나 배치를 강제하는
것은 아니다.

```text
config/qlibx/          # user-owned YAML; review와 version control 대상
  project.yaml
  data/
  strategies/
  models/
  policies/

.qlibx/                # generated local state; 사용자가 직접 편집하지 않음

data/                  # user-owned source data; qlibx가 기본적으로 복사하거나 수정하지 않음
```

Project는 config root, generated state root와 extension root를 명시적으로 선택할 수 있어야
한다. Public command는 선택된 project layout을 일관되게 사용해야 하며 위 예시를 유일한
supported layout으로 가정해서는 안 된다.

## 2. Product thesis

`qlibx`는 Qlib 위에 놓이는 strategy-research automation과 extension framework다. Qlib이 이미
제공하는 backtest loop, order/fill, Account, Position과 portfolio feedback lifecycle은 최대한
Qlib에 위임한다. `qlibx`는 그 위에서 data/strategy config, reusable research graph, signed-alpha
compatibility, ensemble, enhanced-index construction, reproducible results와 agent-facing tools를
제공한다.

Strategy는 단순한 fixed function이어도 된다. 다음 flow는 `qlibx`가 지원하는 대표적인 advanced
workflow이지, 모든 사용자가 따라야 하는 고정 pipeline은 아니다.

```text
point-in-time data + prior strategy state + realized feedback
-> fixed StrategyAgent with an optional decision-time research loop
-> raw or optionally neutralized signed long-short alpha
-> reusable alpha run
-> ticker-level long-short ensemble and netting
-> benchmark-relative enhanced-index intent
-> long-only stock / ETF / cash portfolio
-> Qlib order / fill / Account / Position
-> stored attribution, report and next-decision feedback
```

Signed alpha 자체를 Qlib에서 실행·감사해야 할 때는 Qlib의 non-negative position contract를
깨지 않고 initial endowment를 제공하는 matched-capitalization mode를 사용한다. 이 mode는
underlying short SELL과 partial fill을 그대로 보존하면서 Qlib account 안의 composite position은
항상 non-negative로 유지한다.

사용자는 atomic alpha research, stored-alpha ensemble, enhanced-index construction, Qlib backtest,
adaptive strategy research를 각각 독립적으로 사용할 수도 있다. Research catalog,
orthogonality analysis와 multi-agent coordination은 이 capability들을 연결하는 control plane이다.

## 3. User journey

### 3.1 Primary journey

1. 사용자는 `uv add qlibx`로 framework를 설치한다.
2. `qlibx init` 또는 동등한 Python API로 원하는 project config/state layout을 선택한다.
3. User-owned file data를 inspect하고 logical dataset config로 등록한다.
4. Built-in deterministic signal operators를 조합하거나 project-local extension을 연결한다.
5. Fixed strategy 또는 decision-time research loop을 가진 StrategyAgent와 필요한 transform/budget
   setting을 정의한다.
6. Atomic signed alpha research를 실행하고, 필요하면 built-in neutralization helper를 조합한다.
7. Alpha result, validation, failure와 lineage를 catalog에서 확인하고 재사용한다.
8. 저장된 여러 alpha를 ticker-level로 ensemble/netting한다.
9. 필요하면 signed ensemble을 benchmark-relative long-only enhanced-index target으로 변환한다.
10. Physical target과 backtest lifecycle은 Qlib에 위임하고 realized order/fill/account result를
    받는다.
11. Stored result만으로 report, attribution과 후속 research를 생성한다.
12. 여러 agent가 기존 성공·실패 연구를 조회하며 병렬로 orthogonal trial을 수행한다.

사용자는 6~11단계를 모두 사용할 필요가 없다. Atomic signal research만 사용하거나, 이미 저장된
alpha로 ensemble만 만들거나, external signal을 enhanced-index construction에 전달할 수 있다.

### 3.2 Advanced strategy-research journey

Advanced 사용자는 Qlib이 제공하는 portfolio feedback loop를 활용하여 다음을 추가할 수 있다.

- Historical candidate-rule evaluation
- Lookback 안에서 여러 child StrategyAgent를 causal what-if로 실행하고 비교
- Scheduled 또는 event-driven ML retraining
- Decision-time Bayesian prior/posterior calculation
- Online-learning member allocation
- Stop, cooldown, regime와 execution-feedback-aware decision

`qlibx`는 이 연구가 causal하고 재현 가능하도록 data subscription, state/model/belief lineage,
what-if isolation과 result contract를 제공한다. Basic backtest loop 자체를 별도로 재구현하는 것이
목표가 아니다.

## 4. Scope boundaries and prohibited behavior

### 4.1 Product scope exclusions

다음은 `qlibx`가 직접 소유하지 않는 product scope다.

- Qlib이 이미 제공하는 basic backtest, order/fill, Account와 Position lifecycle의 재구현
- Qlib 자체에 native short-position support를 추가하는 fork 또는 execution engine 개발
- Project-specific data file, dataset definition 또는 strategy config의 package bundle
- Raw corporate-action 해석과 point-in-time market data normalization을 수행하는 upstream data
  pipeline
- Git branch, worktree와 merge workflow를 생성·관리하는 source-control orchestration
- 모든 alpha가 완벽한 market/sector neutrality를 달성한다는 보장

### 4.2 Product invariants and prohibited behavior

다음은 범위 제외가 아니라 `qlibx` workflow가 해서는 안 되는 동작이다.

- Parallel research를 위해 agent별 Git worktree 또는 branch를 요구하지 않는다.
- Data registration 과정에서 user source data를 기본적으로 이동, 변환 또는 overwrite하지 않는다.
- Extension을 위해 Qlib source, installed `qlibx` package 또는 site-packages를 직접 수정하지 않는다.
- Synthetic inverse ticker를 매수해 short를 흉내 내지 않는다.
- Long leg와 short leg를 별도 account에서 실행한 뒤 PnL만 사후 결합하지 않는다.
- Requested target이나 별도 signed ledger를 realized state의 source로 사용하지 않는다.
- Generic downstream layer가 alpha budget을 조용히 확대하거나 unrelated stock으로 재분배하지
  않는다.
- 이미 관찰한 historical period를 true forward OOS로 표시하지 않는다.

## 5. Advanced StrategyAgent capabilities

### 5.1 Public decision contract

Strategy는 고정된 deterministic decision program이다. 같은 effective context, strategy definition,
dependency version, checkpoint state와 declared random seed에는 같은 decision result를 반환해야 한다.
필요하면 Qlib feedback lifecycle을 소비하고 자신의 lookback 안에서 research를 수행할 수 있다.
`qlibx`는 다음 context를 strategy research interface에 노출할 수 있어야 한다.

- `decision_time`
- logical dataset별 causal lookback window
- point-in-time universe and tradability state
- 이전 decision의 desired, submitted, filled and held position
- realized return, PnL, cost and turnover
- engine-managed feedback history
- strategy-owned memory
- optional current model or belief-state identity
- isolated child-strategy research interface

Strategy decision은 다음을 반환할 수 있어야 한다.

- signed signal 또는 signed active weight
- optional physical intent
- updated strategy memory
- optional model 또는 belief-state diagnostics
- weight snapshots and diagnostics
- do-nothing, stop, cooldown, retrain 같은 decision event

### 5.2 Decision-time research inside a fixed StrategyAgent

여기서 adaptive 또는 evolving이라는 말은 strategy definition이 run 도중 임의로 바뀐다는 뜻이
아니다. 동일한 StrategyAgent가 decision time마다 달라진 causal observation, realized feedback과
strategy-owned memory를 입력받아 다른 action을 선택할 수 있다는 뜻이다.

Strategy loop 안에서는 필요에 따라 다음을 수행할 수 있어야 한다.

- Rolling 또는 expanding lookback으로 historical candidate rule을 평가한다.
- Parent strategy가 여러 child StrategyAgent를 만들고 lookback 안에서 isolated what-if로 실행한다.
- Child result를 공통 metric으로 비교한 뒤 current decision의 rule, model, allocation 또는 action을
  선택한다.
- Scheduled 또는 event-driven 방식으로 ML model을 retrain한다.
- New evidence를 사용해 Bayesian prior/posterior calculation을 수행한다.
- Trailing alpha performance로 member allocation 또는 budget을 계산한다.
- Regime, drawdown, consecutive loss, execution failure와 capacity feedback에 반응한다.
- Pair set, hedge ratio, cooldown, open-position state와 retrain counter를 memory에 보존한다.

예를 들어 120일 lookback을 가진 parent strategy는 다음 decision loop을 구현할 수 있다.

```text
last 120 causal observations
-> child strategies A, B and C를 같은 120일 warmup에서 replay
-> child result와 diagnostics 비교
-> next desired position을 결정
-> actual Qlib execution은 parent의 최종 decision에만 적용
```

Child run은 parent가 허용한 historical context만 보고 actual account, holding 또는 sibling state를
변경하지 않는다. Parent result는 사용한 child definition, evaluation window, comparison result와
selected action을 optional diagnostics로 남길 수 있어야 한다.

Public nested-research request는 최소 child strategy definitions, 허용된 causal lookback/warmup,
evaluator ID, declared seed와 execution bound를 받는다. 반환값은 child별 serialized result ID,
evaluation segment, metrics, diagnostics와 failure status다. 어떤 child 또는 조합을 next action에
사용할지는 parent StrategyAgent의 deterministic decision logic이 결정한다.

Belief calculation이나 ML retraining을 사용한 strategy는 원하면 prior/posterior, evidence window,
model version, effective train window와 retrain event를 diagnostics로 반환할 수 있다. 이 필드는
모든 strategy에 강제되지 않으며, engine이 strategy 밖에서 decision logic을 몰래 변경하는 근거가
되어서는 안 된다.

### 5.3 Causal adaptation

- Decision은 decision time보다 먼저 알려진 observation만 사용한다.
- Current bar execution feedback은 다음 decision부터 볼 수 있다.
- Model이나 belief를 사용하는 strategy는 그 계산 시점과 입력을 causal decision loop 안에 둔다.
- Historical what-if, candidate evaluation, fit과 predict는 actual account를 변경하지 않는다.
- Strategy memory는 한 run 안에서 유지되며 새 run은 명시적으로 전달된 checkpoint가 없으면 fresh
  state에서 시작한다.
- Checkpoint resume와 uninterrupted run은 동일한 observable result를 만들어야 한다.

## 6. Data, observation and universe contract

### 6.1 File-backed data source contract

`qlibx`는 package에 dataset definition을 포함하는 대신, project YAML이 local file-backed source를
logical dataset으로 등록하는 public contract를 제공한다. MVP는 최소 Parquet dataset과 DuckDB
file을 지원해야 한다.

Data config는 최소 다음을 명시한다.

- dataset key and config schema version
- source type and project-relative path
- DuckDB table 또는 explicit query when applicable
- required source columns
- table 또는 matrix output contract
- date, ticker와 primary-key identity
- value columns and dtype
- native frequency and timezone
- observation time, availability lag and PIT status
- missing, duplicate and alignment policy
- optional universe/tradability semantics

예시:

```yaml
schema_version: 1
dataset:
  key: market.adjusted_return
  source:
    type: parquet
    path: data/adjusted_prices.parquet
  output:
    kind: matrix
    index: date
    columns: ticker
    values: adjusted_return
    dtype: float64
  contract:
    primary_key: [date, ticker]
    frequency: business_daily
    availability:
      observation_time: close
      lag_days: 1
```

Daily, quarterly, event-driven dataset을 하나의 공통 lookback으로 암묵적으로 자르지 않는다.
필수 dataset, field 또는 declared schema가 없으면 strategy가 호출되기 전에 실패해야 한다.

### 6.2 Data discovery and registration result

Public interface는 user-owned source를 변경하지 않고 다음 workflow를 제공해야 한다.

```text
source discovery
-> schema and sample inspection
-> dataset-config draft
-> contract validation
-> project registration
-> logical dataset load smoke
```

Discovery result는 발견한 file, relation/table, columns, dtype, row/key sample과 ambiguity를
machine-readable하게 반환해야 한다. Column의 경제적 의미, date/ticker identity 또는 availability
rule이 모호하면 agent가 regex나 이름 추측으로 registration을 완료해서는 안 된다. 이 경우
validated draft와 필요한 사용자 질문을 반환한다.

Successful registration은 최소 다음을 반환한다.

- `dataset_key`
- installed config path under the selected project data-config root
- source type and resolved project-relative source
- validated output schema
- snapshot identity
- PIT/availability classification
- load-smoke result and warnings

### 6.3 Project initialization

Fresh project에서 `qlibx init`은 사용자가 선택한 project layout과 최소 project config를 만들 수
있어야 한다. CLI는 비구속적 layout example과 명시적 path option을 제공한다. Existing file을
덮어쓰지 않고 created, unchanged와 conflict path를 결과로 구분해야 한다. Generated local state는
version-control 대상 config와 구분되어야 한다.

### 6.4 Point-in-time universe

각 decision은 최소 다음 상태를 구분할 수 있어야 한다.

- observed
- strategy-eligible
- tradable
- shortable
- inventory-ready

미래 ticker가 전체 matrix axis에 존재한다는 사실은 현재 eligibility나 inventory를 의미하지
않는다. Universe entry, exit, blocked liquidation, delayed exit와 re-entry가 result에서 관측
가능해야 한다. Re-entry 때 memory와 signed execution endowment를 어떻게 처리할지 명시해야
한다.

## 7. Signed long-short alpha research

### 7.1 Alpha result

Atomic alpha의 canonical result는 원 종목 ticker-level signed signal 또는 signed active weight다.
Synthetic execution asset은 alpha ranking, normalization과 research universe에 들어가지 않는다.

Alpha result는 최소 다음을 제공한다.

- long, short, gross and net exposure
- signal and weight coverage
- turnover and cost diagnostics
- information availability audit
- evaluation segment metrics
- optional intermediate weight snapshots

### 7.2 Neutralization helpers and exposure analytics

`qlibx`는 alpha에 neutrality mode를 강제하지 않는다. 사용자는 raw signal을 그대로 사용하거나
built-in helper와 custom transform을 조합하여 market 또는 industry effect를 줄일 수 있다.

Built-in surface는 최소 다음을 제공해야 한다.

- Cross-sectional/market demean
- Industry 또는 sector group demean
- Registered market-factor data가 있을 때 beta estimation과 residualization
- Transform 전후 signal coverage와 group residual diagnostics

이 helper를 적용했다는 사실만으로 result를 완벽한 market-neutral 또는 sector-neutral alpha라고
인증해서는 안 된다. Missing data, estimation error, selection, cap, rebalance와 execution 때문에
실제 exposure는 남을 수 있다.

사용자가 필요한 market, benchmark, industry 또는 factor data를 등록했다면 built-in exposure
analyzer는 최소 다음을 계산할 수 있어야 한다.

- signed long, short, gross and net exposure
- market 또는 benchmark beta/exposure
- industry/sector exposure
- supplied custom factor exposure
- intended weight와 realized holding의 exposure 차이

Exposure result는 analyzer name/version, input artifact와 dataset identity, estimation window, coverage,
missingness와 method를 함께 제공해야 한다. Built-in analyzer는 기본 선택지일 뿐이며, 사용자는 같은
serialized input/output contract를 따르는 local Python evaluator로 이를 보완하거나 교체할 수 있어야
한다.

### 7.3 Budget policies

기본 mode는 비교 편의를 위한 fixed dollar-neutral rescale다.

```yaml
budget_policy:
  mode: fixed_dollar_neutral
  long_budget: 1.0
  short_budget: 1.0
```

Feasible한 양쪽 candidate가 있을 때 기본 result는 다음 target을 갖는다.

```text
long weight sum  =  1
short weight sum = -1
```

Flexible mode는 long과 short budget을 반드시 소진해야 하는 target이 아니라 maximum으로
해석한다.

```yaml
budget_policy:
  mode: flexible
  long_budget: 1.0
  short_budget: 1.0
```

```text
0 <= long weight sum  <=  1
-1 <= short weight sum <= 0
```

Flexible mode에서는 truncation, candidate scarcity, signal strength, regime, trailing performance,
ML 또는 belief update에 따라 budget을 남길 수 있다. Candidate가 없는 side는 0이 될 수 있다.

### 7.4 Intention preservation

Flexible result를 받은 generic downstream interface는 다음을 해서는 안 된다.

- Long/short side를 full budget으로 silent rescale
- Cap/floor로 잘린 weight를 unrelated active stock에 재분배
- Ensemble 직전에 member gross exposure 복원
- 남은 alpha budget을 임의의 stock bet으로 소진

Ensemble이나 strategy가 명시적인 rule로 rescale 또는 redistribute하는 것은 허용한다. 이 경우
변환 전후 result와 rationale이 관측 가능해야 한다.

### 7.5 Weight snapshots

Strategy는 selection, truncation, model/belief update, budget adjustment, ensemble과 execution 전후
원하는 지점에서 signed weight snapshot을 기록할 수 있어야 한다.

각 snapshot은 다음을 제공한다.

- date, strategy and snapshot name
- sequence
- signed weights
- long/short/gross/net exposure
- leftover long/short budget
- strategy-owned metadata

Snapshot logging on/off는 final strategy result를 바꾸지 않아야 한다.

### 7.6 Battery-included deterministic signal toolkit

Agent가 매 research마다 common transform을 새로 구현하지 않도록 `qlibx`는 deterministic signal
processing operator와 helper를 기본 제공해야 한다.

Minimum built-in surface:

- Cross-sectional rank, demean, z-score, winsorize and clipping
- Cross-sectional/market demean and optional beta residualization
- Industry/sector group demean
- Lag and rolling statistics
- Linear signal decay
- Hump/barrier function
- Top/bottom selection and per-name cap
- Fixed dollar-neutral and flexible-budget rescale/validation
- Matrix alignment, missingness, coverage and causality checks

각 operator는 axis, tie-breaking, NaN policy, minimum observations, group-missing policy, dtype와
parameter semantics가 문서화되어야 한다. 같은 input과 parameter는 같은 result를 반환해야 하며,
run result는 사용한 operator name과 version을 조회할 수 있어야 한다.

Built-in operator는 common vocabulary와 consistent implementation을 제공하는 출발점일 뿐 허용된
research space의 전체 목록이 아니다.

### 7.7 Project-local extension bridge

사용자와 agent는 `qlibx` package source를 수정하거나 upstream contrib PR을 만들지 않고 새
capability를 연결할 수 있어야 한다.

Supported extension categories:

- Signal transform and weight helper
- Dataset/source adapter
- StrategyAgent and model adapter
- Metric, exposure/risk evaluator and orthogonality comparator
- Optimizer constraint or construction policy
- Report component

Extension code location은 product가 강제하지 않는다. 예를 들어 `.qlibx/extensions/`,
`qlibx-custom/`, 다른 user-owned directory 또는 별도 installed Python package를 사용할 수 있다.
Project config가 extension ID, import target, version과 selected path/package를 명시한다.

Built-in component가 존재하는 extension point에서도 사용자는 compatible local module ID를 config나
public API에서 선택하여 해당 component를 교체할 수 있어야 한다. 교체는 site-packages monkey patch가
아니며, built-in과 local module이 같은 public artifact contract를 소비하고 반환하는 방식이어야 한다.

예를 들어 built-in에 linear decay만 있고 agent가 exponential decay를 필요로 하면 다음 journey를
지원해야 한다.

```text
built-in operator search
-> local exponential-decay extension scaffold
-> deterministic contract test and validation
-> project registration
-> config에서 operator ID로 사용
```

Local extension은 built-in과 동일한 input/output, causality, determinism, versioning과 result-lineage
contract를 만족해야 한다. Invalid extension은 등록되거나 complete run에서 사용되어서는 안 된다.

### 7.8 Universal serialized artifact contract

`qlibx`의 모든 composable workflow boundary—data loader, universe/mask, signal transform,
StrategyAgent, child strategy evaluator, model, metric, ensemble, optimizer, backtest, exposure analyzer와
reporter를 포함한다—는 서로의 private Python object나 live process memory를 요구하지 않아야 한다.
각 public stage는 자신의 raw input과 output을 documented portable format으로 serialize하고 다시
load할 수 있어야 한다.

Minimum artifact envelope:

- artifact type and schema version
- stable artifact/run identity and producer component ID/version
- parent/input identities and causal time range
- axes, index, unit, currency, timezone and data semantics when applicable
- portable data payload 또는 payload reference
- warnings, coverage, diagnostics and completion status

MVP portable surface는 metadata/config용 JSON과 tabular/matrix result용 Parquet 또는 Arrow-compatible
representation을 제공해야 한다. 사용자는 raw artifact를 public CLI/Python API로 export하여 qlibx
밖의 Python code에서 읽고, compatible artifact를 반환하는 local module을 workflow 중간에 연결할
수 있어야 한다.

Built-in component와 local replacement는 같은 artifact schema를 사용한다. Downstream module은
producer가 built-in인지 local Python file인지 알 필요가 없어야 하며, private class import나
in-process object identity에 의존해서는 안 된다.

## 8. Research graph and ML

Alpha, mask, transform, model prediction, ensemble, active intent와 physical target을 typed research
graph로 표현할 수 있어야 한다.

Public behavior:

- Parent/child lineage와 input/output type을 조회할 수 있다.
- 같은 verified node result를 재사용할 수 있다.
- Dataset 또는 transitive parent가 바뀌면 dependent result identity가 바뀐다.
- Cycle과 incompatible type connection은 실행 전에 실패한다.
- Backtest-only 변경은 compatible alpha/model result를 다시 계산하지 않는다.

Qlib ML research는 Qlib Dataset, DataHandler와 Model surface를 사용할 수 있어야 한다.

- Processor는 effective train segment에만 fit한다.
- Label horizon purge와 validation/test embargo를 적용한다.
- Prediction은 `(datetime, instrument)` identity를 유지한다.
- Prediction은 deterministic portable alpha artifact가 될 수 있다.
- Fit/predict는 actual Qlib account에 side effect를 만들지 않는다.

## 9. Long-short ensemble and super alpha

### 9.1 Stored-alpha composition

Ensemble은 member strategy를 다시 실행하지 않고 alpha run ID를 입력으로 받는다.

```text
stored member signed weights
-> ensemble capital weights
-> ticker-level crossing and netting
-> combined signed alpha
```

Member의 실제 flexible weight를 사용하며 full-budget exposure로 복원하지 않는다. 같은 ticker의
반대 intent는 execution과 cost 계산 전에 netting된다. 다른 ticker의 반대 exposure는 자동으로
risk가 상쇄된 것으로 간주하지 않는다.

### 9.2 Adaptive ensemble

Super alpha 자체도 StrategyAgent가 될 수 있다. 이전 member performance, regime, Bayesian
belief 또는 ML forecast로 member allocation을 갱신할 수 있다. Allocation update는 causal해야
하며 member result를 다시 학습·실행하지 않고 stored result에 적용할 수 있어야 한다.

### 9.3 Ensemble result

Ensemble은 다음을 제공해야 한다.

- member alpha run IDs and capital weights
- member compatibility and calendar checks
- pre/post-netting signed intent
- crossing and cost reduction
- combined exposure and budget diagnostics
- reusable ensemble alpha run ID
- member and family attribution

## 10. Enhanced-index long-only construction

### 10.1 Purpose

Signed alpha 또는 ensemble을 benchmark-relative active intent로 해석하고 실제 투자 가능한
long-only enhanced-index portfolio로 변환한다.

```text
benchmark constituent exposure
+ scaled signed active intent
-> desired total constituent exposure
-> stock / ETF / cash physical target
```

### 10.2 Public optimizer contract

Input:

- desired signed active exposure
- benchmark weight
- current realized physical holding and cash
- stock/ETF look-through
- tradability
- bounds and named constraints
- transaction cost and turnover preference
- risk and capacity inputs

Result:

- physical stock/ETF target and cash target
- realized look-through constituent exposure
- desired-versus-realized active exposure
- optimizer status
- hard/soft constraint diagnostics
- turnover and cost estimate
- financing/passive residual attribution

Look-through는 정확히 한 번 적용되어야 한다. Non-tradable current holding은 실제 보유 상태에
맞게 유지되어야 한다. Infeasible와 solver failure를 구분하고 silent relaxation하지 않는다.

### 10.3 Flexible-budget financing

Flexible alpha가 사용하지 않은 stock budget은 unrelated active stock으로 재분배하지 않는다.
Enhanced-index result에서는 ETF, benchmark sleeve 또는 명시된 passive buffer가 residual capital을
흡수한다.

Result는 다음을 분리해야 한다.

- alpha-requested active intent
- strategy budget utilization
- feasibility 때문에 실현하지 못한 exposure
- passive/ETF residual
- final realized active exposure

Fixed-budget counterfactual과 flexible-budget actual portfolio를 함께 비교할 수 있어야 하며,
selection effect, budget timing, passive residual과 implementation effect를 구분해야 한다.

## 11. Signed execution through Qlib long-only accounts

### 11.1 Why matched capitalization exists

현재 Qlib의 공식 stock `Position`/`Account` execution contract는 long-only이며 negative stock
quantity를 native short position으로 지원하지 않는다. `qlibx`는 Qlib source를 fork하지 않고
signed long-short alpha를 검증하기 위해 `matched_capitalization`이라는 명시적인 compatibility
hack을 제공한다. 이 mode는 Qlib에 native short support가 있다고 주장하지 않는다.

### 11.2 Exact accounting contract

Backtest initial cash는 active strategy booksize와 short capacity를 위한 baseline funding reserve로
구분된다. Qlib Account에는 non-negative composite position만 존재하고, 별도의 baseline sidecar는
endowed inventory와 matching cash를 추적한다. Signed observer는 독립적인 execution ledger를
가지지 않는다.

각 ticker와 decision에서 다음 public relation을 만족한다.

```text
A = realized signed active quantity
B = matched baseline/endowment quantity, B >= 0
C = Qlib composite quantity, C >= 0

C = B + A
A = C - B
```

음수 intent가 필요한 ticker가 `observed`, strategy universe, `shortable`과 sellable 조건을 처음
만족하면 다음 public behavior를 보장한다.

1. Active pre-trade NAV, configured per-name short cap, safety multiplier, execution price와 lot size로
   필요한 baseline quantity를 계산한다.
2. 부족한 baseline quantity를 Qlib composite position과 baseline sidecar에 같은 execution-time
   price로 동시에 endow하고, 동일 notional을 baseline reserve cash에서 차감한다.
3. 이 endowment/top-up은 market exchange fill이 아닌 zero-cost capitalization event이며 volume,
   commission과 tax를 소비하지 않는다.
4. Quantity 증가와 matching cash debit 때문에 composite NAV와 active NAV는 바뀌지 않는다.
5. Signed target `A_target`을 baseline `B`에 더한 `C_target = B + A_target`만 Qlib의 non-negative
   physical target으로 전달한다.
6. Active short의 economic order는 underlying instrument의 실제 `SELL` 방향으로 Qlib Exchange를
   통과한다.
7. Partial fill, suspension, price limit과 volume limit 이후 `A_realized = C_realized - B`로 signed
   holding을 역산한다. Qlib dealt amount와 독립적으로 움직이는 signed ledger는 없다.

Baseline은 configured retention policy에 따라 유지되거나 더 이상 필요하지 않은 capacity를
NAV-neutral release할 수 있다. Funding reserve가 부족하거나 `C_target < 0`이면 우회하지 않고
실패한다. Universe exit, blocked liquidation, re-entry와 checkpoint resume 뒤에도 위 identity를
검증할 수 있어야 한다.

### 11.3 Observable results

- Intended signed weight and target quantity
- Baseline quantity/cash before and after
- Activation, top-up and release event
- Qlib requested/dealt amount and blocked reason
- Composite and reconstructed signed closing quantity
- Composite, baseline and active account reconciliation

Capitalization policy만 바뀌면 compatible alpha run을 재사용하고 새 backtest result만 만든다.

### 11.4 Active performance

Qlib composite account는 baseline endowment를 포함하므로 standard composite return을 signed alpha의
canonical 성과로 사용하지 않는다.

Result는 다음을 제공해야 한다.

- composite account
- baseline/endowment account
- active account
- active money PnL
- explicit active return denominator
- composite = baseline + active reconciliation

## 12. Realized execution and closed-loop feedback

Physical execution은 Qlib order, fill, Account와 Position 결과를 authoritative realized state로
사용한다.

Public requirements:

- Weight target을 booksize, price와 lot size에 맞는 physical quantity로 변환한다.
- Rounding residual은 cash로 남긴다.
- Stock과 ETF에 서로 다른 cost policy를 적용할 수 있다.
- Suspension, price limit, volume participation, cash와 lot constraint를 반영한다.
- Order와 fill은 requested/dealt quantity, clipping stage와 reason code를 제공한다.
- Partial fill 이후 다음 optimizer와 StrategyAgent는 requested target이 아닌 actual holding을 본다.
- NAV는 cash와 marked position value에 reconcile된다.
- Unknown instrument, malformed checkpoint와 state mismatch는 fail-fast한다.
- Resume와 uninterrupted execution은 position, cash, orders, fills와 result identity가 일치한다.

## 13. Runs, catalog, raw results, reports and attribution

### 13.1 Stored runs and raw artifacts

Alpha, model, ensemble, portfolio와 backtest run은 별도 identity와 parent lineage를 가진다.

사용자는 다음을 할 수 있어야 한다.

- 같은 effective input의 verified result 재사용
- Backtest config만 바꾸고 alpha 재사용
- Stored alpha로 ensemble 생성
- Stored backtest로 report 생성
- Stored member/ensemble/optimizer result로 attribution 생성
- Corrupt 또는 incomplete result 식별
- Process 종료 후 run과 lineage 재조회

Complete result는 최소 다음을 연결한다.

- logical dataset snapshots
- strategy/model/graph definition
- signal and signed intent
- weight snapshots
- optimizer targets
- orders, fills, positions and account
- baseline and active account when applicable
- metrics, comparison and report inputs
- artifact manifest and public schema versions

Report와 attribution은 strategy, model 또는 original data loading을 다시 실행하지 않아야 한다.

모든 complete run은 built-in report를 거치지 않은 raw serialized artifact를 export할 수 있어야 한다.
사용자는 signal, weight, exposure, optimizer target, order, fill, holding, cash, account와 metric result를
public schema 그대로 읽을 수 있어야 한다.

### 13.2 Built-in and replaceable reporting

`qlibx`는 최소 다음 built-in reporter를 제공해야 한다.

- Performance and risk summary
- Signal/weight coverage and turnover
- Market, benchmark and industry exposure when required data is available
- Cost, order/fill and desired-versus-realized execution reconciliation
- Member, ensemble and optimizer attribution
- Matched-capitalization composite/baseline/active reconciliation

Built-in report format은 유일한 presentation layer가 아니다. 사용자는 local Python file 또는 installed
package의 reporter를 extension으로 등록하고 `reporter_id`로 선택할 수 있어야 한다. Built-in과 custom
reporter는 같은 stored serialized result를 입력받으며 strategy, model, optimizer 또는 backtest를 다시
실행해서는 안 된다.

Custom reporter는 완전히 다른 table, chart, document 또는 downstream payload를 만들 수 있다. 다만
report artifact는 reporter ID/version, consumed artifact IDs, output locations와 warnings를 반환해야
한다. 사용자는 reporter를 사용하지 않고 raw result만 export할 수도 있어야 한다.

## 14. Systematic agent research control plane

### 14.1 Research context

Agent는 새 proposal 전에 다음 bounded context를 조회할 수 있어야 한다.

- registered and superseded alpha definitions
- successful, failed and invalid trials
- searched parameter ranges
- active proposals
- nearest semantic and empirical neighbors
- available dataset snapshots and known PIT limitations
- required comparison set and evaluation policy
- research gaps

### 14.2 Orthogonality

새 candidate는 다음 세 층으로 평가한다.

- Semantic: mechanism, input, clock, horizon, operator, neutralization, search-space overlap
- Empirical: signal, holding, return, exposure, turnover, trade overlap and regime stability
- Incremental: residual signal quality, cost-aware marginal return/IR, risk, concentration and capacity

Low PnL correlation 하나만으로 independent alpha로 승격하지 않는다. Parameter, sign, scale 또는
neutralization variation은 independent alpha와 구분한다.

### 14.3 Research decision

Promotion, rejection, diagnostic retention과 supersede decision은 evidence run, policy, reviewer와
rationale를 제공해야 한다. 실패한 trial도 catalog와 context에 남아야 한다.

## 15. Parallel multi-agent product requirements

`qlibx`는 worktree 없이 한 repository와 한 branch에서 병렬 연구를 지원해야 한다.

사용자에게 보이는 보장:

1. Agent마다 독립적인 research session과 workspace ID를 받는다.
2. 서로 다른 agent의 scratch, config context와 intermediate result가 섞이지 않는다.
3. Run 시작 후 다른 agent의 config 변경이 해당 run의 resolved config를 바꾸지 않는다.
4. 여러 agent가 동시에 독립 strategy와 research proposal을 실행할 수 있다.
5. 동일 proposal/run의 동시 요청은 duplicate 또는 conflict를 명시적으로 반환한다.
6. 동일 idempotency key의 재요청은 중복 result를 만들지 않는다.
7. Incomplete result는 complete로 조회되지 않는다.
8. 서로 다른 completed result는 유실되지 않는다.
9. 같은 identity의 다른 content는 조용히 overwrite되지 않는다.
10. Stale version을 사용한 promotion은 명시적으로 실패한다.
11. 한 agent의 중단이 다른 session과 완료 result에 영향을 주지 않는다.

일반적인 새 dataset, alpha, model과 evaluator는 shared core file을 수정하지 않고 public extension
interface로 추가할 수 있어야 한다.

## 16. Public configuration interface

Project가 선택한 config root는 project-owned source of truth다. `config/qlibx/`는 supported
layout example이지 mandatory path가 아니다. Package upgrade와 generated result가 selected config
root를 조용히 수정해서는 안 된다.

최소 config 영역:

```text
# illustrative only
config/qlibx/project.yaml
config/qlibx/data/*.yaml
config/qlibx/strategies/*.yaml
config/qlibx/models/*.yaml
config/qlibx/policies/*.yaml
```

Config loader는 unknown key, missing dataset, incompatible axis와 invalid combination을 실행 전에
거부해야 한다. 여러 YAML을 resolve한 effective config는 run result에서 stable `config_id`로
조회할 수 있어야 한다.

Installed package는 config author가 source code를 읽지 않아도 되도록 다음 documentation surface를
제공해야 한다.

- Project layout guide
- Data config reference and examples
- 모든 public config의 machine-readable schema
- CLI/Python API reference
- Validation error reference
- Agent workflow guide

Documentation과 schema는 offline installed environment에서 public command로 조회할 수 있어야 한다.

## 17. Public CLI and Python API

최소 CLI surface:

```text
qlibx doctor
qlibx init
qlibx docs index|show
qlibx schema list|show|export
qlibx data discover|scaffold|validate|register
qlibx data list|show|load
qlibx operators list|show
qlibx exposure analyze --analyzer <component-id>
qlibx extensions scaffold|validate|register|list|show
qlibx run
qlibx research context|propose|run|compare|decide
qlibx alpha list|show|history
qlibx model run|history
qlibx ensemble build|run
qlibx enhanced-index build|run
qlibx backtest run|resume
qlibx results show|export|validate
qlibx report create --reporter <component-id>
qlibx catalog runs|lineage|artifacts
```

Agent-facing command는 JSON output, dry-run, timeout, idempotency key, stable error code와 suggested
next action을 제공해야 한다.

Python API는 최소 다음 use case를 제공해야 한다.

```python
client.initialize_project(...)
client.docs.show(...)
client.schemas.get(...)
client.data.discover(...)
client.data.scaffold(...)
client.data.validate(...)
client.data.register(...)
client.data.load(...)
client.operators.list(...)
client.exposure.analyze(..., analyzer_id=...)
client.extensions.scaffold(...)
client.extensions.validate(...)
client.extensions.register(...)
client.run_strategy_batch(...)
client.research.context(...)
client.research.propose(...)
client.research.run(...)
client.research.compare(...)
client.build_ensemble(...)
client.build_enhanced_index(...)
client.run_backtest(...)
client.results.show(...)
client.results.export(...)
client.results.validate(...)
client.reports.create(..., reporter_id=...)
client.open_catalog(...)
```

CLI와 Python API는 동일한 ID, status와 result semantics를 사용해야 한다.

## 18. Agentic skills

### 18.1 Project data registration skill

사용자가 “`data/`의 데이터를 qlibx에 등록해줘”라고 요청하면 skill은 package source를 읽거나
private interface를 사용하지 않고 다음 workflow를 수행한다.

1. `qlibx doctor`와 documentation index를 확인한다.
2. Project가 초기화되지 않았다면 `qlibx init`을 실행한다.
3. `qlibx data discover data/ --format json`으로 source를 read-only inspection한다.
4. Data-config documentation과 schema를 조회한다.
5. 명확한 source에는 selected project data-config root에 YAML draft를 scaffold한다.
6. 의미가 모호한 field에는 guess하지 않고 필요한 질문을 제시한다.
7. Config validation과 logical load smoke를 실행한다.
8. Valid dataset을 project에 register한다.
9. 생성·변경된 config path, dataset key, schema, PIT status와 validation result를 반환한다.

Skill은 source data를 기본적으로 복사·수정하지 않고, unrelated project config를 변경하지 않으며,
validation을 통과하지 않은 draft를 registered dataset으로 보고하지 않는다.

### 18.2 Orthogonal alpha research skill

`research-orthogonal-alpha` skill은 등록된 project dataset과 `qlibx` public interface로 다음
workflow를 수행한다.

1. Environment와 registered dataset을 확인한다.
2. Existing alpha, failure와 active proposal context를 읽는다.
3. Research objective, dataset, evaluation window와 필요한 transform/budget setting을 포함한 bounded
   proposal을 등록한다.
4. Duplicate와 nearest neighbor를 검토한다.
5. Atomic StrategyAgent 또는 model research를 실행한다.
6. Fixed/flexible alpha result와 snapshots을 검증한다.
7. Reference pool과 orthogonality를 평가한다.
8. 필요하면 stored alpha로 ensemble과 enhanced-index what-if를 실행한다.
9. 성공·실패 result와 decision을 등록한다.
10. Canonical IDs, 핵심 결과와 next action을 반환한다.

Skill은 unbounded search, holdout tuning, 실패 누락, 기존 result overwrite, 다른 agent session 변경과
public interface 우회를 해서는 안 된다.

### 18.3 Extension authoring behavior

Agent는 새 helper가 필요할 때 먼저 built-in operator registry를 검색한다. 필요한 capability가
없으면 public documentation과 scaffold command로 project-local extension을 만들고, deterministic
contract test와 validation을 통과시킨 뒤 register한다. Agent는 이를 위해 installed `qlibx`
source를 직접 수정해서는 안 된다.

같은 workflow는 exposure analyzer와 reporter에도 적용한다. Agent는 raw serialized artifact schema를
조회하고 local Python component를 만든 뒤, built-in과 동일한 validation을 통과시켜 workflow의 해당
extension point에서 선택할 수 있어야 한다.

## 19. Acceptance criteria

### P0 — Fresh install and project data registration

- `uv add qlibx` 후 project-specific data/config가 package에서 자동 설치되지 않는다.
- `qlibx init`이 사용자가 선택한 config/state root를 만들고 example layout을 강제하지 않으며,
  existing file을 덮어쓰지 않는다.
- Installed documentation과 machine-readable data schema를 offline CLI로 조회할 수 있다.
- Agent가 public CLI만 사용해 `data/`의 Parquet 또는 DuckDB source를 discover한다.
- Successful registration이 selected project data-config root의 valid YAML, dataset key와 load smoke를 제공한다.
- Registration 전후 user source data content가 바뀌지 않는다.
- Ambiguous date/ticker/value/availability semantics는 추측하지 않고 actionable question을 반환한다.
- `qlibx data list|show|load`가 새 dataset을 즉시 조회·로드한다.

### P1 — Adaptive StrategyAgent and causality

- Dataset별 lookback과 availability가 독립적이며 모든 observation은 decision보다 과거다.
- 같은 effective decision input, definition, dependency, checkpoint와 seed는 같은 strategy result를
  만든다.
- Confirmed feedback은 다음 decision에만 영향을 준다.
- Strategy memory는 run 안에서 유지되고 새 run에서 격리된다.
- Parent strategy가 lookback 안에서 여러 child StrategyAgent를 causal what-if로 실행하고 비교하여
  next action을 선택할 수 있다.
- Child strategy, historical what-if와 ML/Bayesian calculation은 actual account를 변경하지 않는다.
- Model/belief diagnostics는 해당 technique을 사용하는 strategy에만 optional하게 존재한다.
- Qlib ML run이 train-only fit, purge/embargo와 portable prediction을 제공한다.
- Resume와 uninterrupted run의 observable result가 동일하다.

### P2 — Signed alpha, transforms, exposure and flexible budget

- Raw signed signal은 별도 neutralization을 적용하지 않아도 canonical alpha result가 될 수 있다.
- 사용자가 built-in/custom transform을 조합해 market 또는 industry effect를 줄인 signed alpha를
  만들 수 있으며, helper 적용 자체는 exact neutrality 보장으로 표시되지 않는다.
- Common rank, market/industry demean, hump/barrier와 linear decay가 documented deterministic
  operator로 제공된다.
- 같은 operator input/parameter가 같은 result를 만들고 operator version이 lineage에 남는다.
- Registered market/factor data가 있으면 built-in analyzer가 method와 coverage를 포함한 market,
  industry와 custom factor exposure를 계산한다.
- Compatible local Python analyzer가 built-in exposure analyzer를 package 수정 없이 교체할 수 있다.
- Agent가 exponential decay 같은 새 helper를 package source 수정 없이 project-local extension으로
  추가, 검증, 등록하고 strategy config에서 사용할 수 있다.
- Default fixed mode는 feasible case에서 long `1`, short `-1`로 rescale한다.
- Flexible mode는 long `[0,1]`, short `[-1,0]`을 허용한다.
- Candidate가 없는 flexible side는 0일 수 있다.
- Cap/truncation 후 leftover budget이 silent redistribution되지 않는다.
- Snapshot logging on/off가 final weight를 바꾸지 않는다.

### P3 — Ensemble and enhanced index

- Stored long-short member를 재실행하지 않고 ensemble한다.
- Member actual weight를 ticker-level로 netting한다.
- Ensemble active intent가 benchmark-relative total exposure로 변환된다.
- Long-only stock/ETF/cash target과 look-through exposure가 reconcile된다.
- Flexible residual은 passive sleeve로 구분되고 unrelated stock bet이 되지 않는다.
- Hard/soft constraint, infeasible와 solver error가 명시적으로 구분된다.

### P4 — Matched endowment and Qlib realized execution

- Result가 Qlib의 official long-only limitation을 우회한 compatibility mode임을 명시한다.
- Future ticker는 first-observed 이전에 endowment와 position이 0이다.
- Endowment activation은 composite와 active NAV를 바꾸지 않는다.
- Active short는 underlying Qlib SELL로 실행된다.
- Composite position은 non-negative이고 `A = C - B`를 만족한다.
- Partial fill은 dealt amount만큼만 realized signed quantity를 바꾼다.
- Baseline reserve 부족 또는 composite target 음수는 명시적으로 실패한다.
- Active PnL이 endowment를 포함한 composite denominator로 희석되지 않는다.
- Stock/ETF cost, lot rounding, blocked trade와 actual holding feedback이 일치한다.

### P5 — Reuse, reporting and attribution

- Alpha와 backtest run identity가 분리된다.
- Backtest-only 변경은 alpha를 재실행하지 않는다.
- Stored member로 reusable ensemble result를 만든다.
- Stored run만으로 report와 member/optimizer attribution을 만든다.
- 모든 complete stage result를 documented JSON/Parquet 또는 Arrow-compatible artifact로 export한다.
- Raw backtest result는 built-in reporter 없이도 public schema로 읽을 수 있다.
- Local Python reporter가 같은 stored artifact를 소비하여 built-in reporter를 교체할 수 있다.
- Same effective input은 verified result를 재사용한다.
- Corrupt, incomplete 또는 provenance-conflicting result는 complete로 읽히지 않는다.

### P6 — Agent research and parallelism

- 기존 성공·실패 alpha와 nearest neighbor를 context로 조회한다.
- Orthogonality result가 semantic, empirical, incremental section을 모두 제공한다.
- 최소 세 agent가 한 branch에서 독립 session과 run을 동시에 수행한다.
- 한 agent의 config 변경이 이미 시작한 다른 run을 바꾸지 않는다.
- Duplicate, stale update와 result conflict가 stable public error로 반환된다.
- Agent가 public interface만으로 전체 research workflow를 완료한다.

## 20. Legacy capability parity

`qlibx` MVP는 `qlib-integration-codex` Goal tests가 증명한 다음 product behavior를 regression
baseline으로 유지해야 한다.

| Goal | Required product behavior |
|---|---|
| 0 | Public capability surface와 test observation contract |
| 1 | Feedback timing, partial fill and Qlib account reconciliation |
| 2 | Dataset별 lookback과 strategy memory lifecycle |
| 3 | Universe entry/exit, blocked liquidation and re-entry |
| 4 | Integer/lot quantity, rounding cash and stock/ETF costs |
| 5 | Reusable runs, provenance, integrity and corruption detection |
| 6 | Cached long-short members to one enhanced-index Qlib run |
| 7 | Causal adaptive rule/model evaluation without account side effects |
| 8 | Checkpoint/resume parity |
| 9 | Look-through optimizer and explicit constraint/solver results |
| 10 | Qlib ML train-only fit, purge/embargo and portable prediction |
| 11 | Config-driven logical data, alpha run and backtest run |
| 12 | Parallel independent strategy execution and deterministic reuse |
| 13 | Stored-run reporting without strategy rerun |
| 14 | Stored-member reusable ensemble and lineage |
| 15 | Thin public run/report/ensemble interface |
| 16 | Matched endowment signed execution and active reporting |
| 17 | Frozen member-to-family-to-enhanced-index migration parity |
| 18 | Stored report-data to complete cached report surface |

## 21. Migration from `qlib-integration-codex`

기존 run과 artifact는 source reference, known PIT limitation, selection contamination, reconstructed
lineage와 validation result를 포함해 `qlibx`에서 조회할 수 있어야 한다.

Legacy result는 자동으로 trusted 또는 forward-eligible alpha가 되지 않는다. 기존 report와 새
`qlibx` result의 차이를 설명하는 reconciliation report를 제공해야 한다.

## 22. Quality requirements

- Reproducibility: run은 definition, config, data, code, model/belief와 seed identity를 제공한다.
- Causality: future observation, future universe와 current-bar feedback을 decision에 사용하지 않는다.
- Consistency: complete, failed, invalid와 cached status를 명확히 구분한다.
- Auditability: signal에서 ensemble, optimizer, fill, account와 report까지 lineage를 추적한다.
- Compatibility: Public config, CLI JSON과 Python result는 schema version을 가진다.
- Distribution: Package는 project-specific dataset/config를 포함하지 않고 documentation, schema와
  public bootstrap/registration interface만 배포한다.
- Performance: Context query와 cached result 조회는 agent interactive workflow에 적합해야 한다.

## 23. Future product decisions

- Remote multi-host agent execution
- General Bayesian model library와 posterior visualization
- Automated ensemble capital allocation
- Online experiment budget allocation
- Web research and portfolio dashboard
- External experiment tracker integration
- Live/paper execution adapter
