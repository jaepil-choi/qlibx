# qlibx Product Requirements Document

> Status: review-integrated draft
> Source baseline: `qlibx-prd.md`
> Revision purpose: `critical-review-on-prd-codex.md`와
> `critical-review-on-prd-claude.md`의 합의된 지적을 product contract에 반영한다.

## 0. 이번 개정의 판단

### 0.1 유지하는 제품 정체성

이번 개정은 qlibx의 방향을 바꾸지 않는다. 다음 원칙은 그대로 유지한다.

- Qlib을 order, fill, position, account와 closed-loop backtest의 기반으로 사용한다.
- Signed alpha research, stored-alpha ensemble, long-only enhanced index implementation을 하나의 lineage로
  연결한다.
- 성공뿐 아니라 실패, invalid trial과 이미 탐색한 범위도 reusable evidence로 남긴다.
- Stored artifact를 module 사이의 public integration point로 사용한다.
- Built-in으로 공통 vocabulary를 제공하고 project-local extension으로 자율성을 제공한다.
- Human과 AI coding agent가 private implementation을 읽지 않고 public surface만으로 연구할 수 있게 한다.

### 0.2 핵심 contract로 즉시 반영하는 항목

두 리뷰가 공통으로 지적했거나 제품 의미를 결정하는 항목은 선택 기능이 아니라 전역 invariant로
반영한다.

1. Market execution authority와 account administration authority를 구분한다.
2. Point-in-time data에 `knowledge_time`과 revision/vintage를 포함한다.
3. Signal부터 physical target까지 unit, reference NAV, currency와 financing을 명시한다.
4. Run을 deterministic, seeded stochastic, externally stochastic으로 분류한다.
5. Cost와 risk method를 versioned input contract로 관리한다.
6. Attempt, artifact verification, research decision lifecycle을 분리한다.
7. Evaluation segment의 역할, exposure와 holdout consumption을 기록한다.
8. Frozen run에 config뿐 아니라 data content, source와 executable environment identity를 포함한다.
9. StrategyAgent output kind별 decision authority와 allowed downstream operation을 제한한다.
10. Ensemble member의 calendar, decision clock, staleness와 budget compatibility를 검증한다.
11. Same-branch safety guarantee를 qlibx-owned state로 한정한다.
12. Local extension과 agent의 trust, permission, secret, resource boundary를 명시한다.
13. Artifact portability grade와 grade별 downstream use를 구분한다.
14. Capability checklist를 release gate와 검증 가능한 acceptance scenario로 교체한다.

### 0.3 표현을 바로잡아 반영하는 항목

- Pearson correlation은 양의 상수 rescale에 불변이다. Scale 문제는 correlation 자체가 아니라
  holding distance, turnover notional, marginal PnL, concentration과 capacity 같은 scale-sensitive
  metric에 적용한다.
- Enhanced index에 covariance 또는 factor risk model을 강제하지 않는다. 대신 `risk_model`,
  `scenario`, `constraint_only` 중 어떤 risk method를 사용했는지 선언한다.
- Fixed dollar-neutral default는 silent inference와 논리적으로 모순되지 않는다. Default 적용 사실과
  raw/pre-budget/post-budget snapshot을 명시적으로 보존하는 문제로 다룬다.
- Baseline reserve opportunity cost는 canonical active PnL에서 자동 차감하지 않는다. Actual reserve
  usage, carry, total committed-capital return과 user-defined counterfactual을 분리한다.
- Matched-capitalization은 독립된 두 번째 execution engine이 아니다. Qlib fill 경로 밖에서 같은
  composite account를 바꾸는 non-market account administration mechanism이다.

### 0.4 후속 capability로 배치하는 항목

다음 제안은 가치가 있지만 foundational contract의 선행 조건은 아니다. Core contract가 안정된 뒤
release slice로 추가한다.

- Alpha fragility card와 synthetic perturbation battery
- Historical regime/stress replay
- Capacity curve와 AUM/participation-rate sensitivity
- Hypothesis와 사전 prediction을 대조하는 falsifiability diagnostic
- Information gain을 기준으로 trial을 배치하는 research portfolio scheduler

## 1. Product overview

### 1.1 제품 정의

`qlibx`는 Qlib을 execution 기반으로 사용하는 alpha research framework다. Quant researcher와 AI coding
agent가 다음을 하나의 재사용 가능한 환경에서 수행하게 한다.

- Project data를 point-in-time logical dataset으로 등록한다.
- Signed long-short alpha를 만들고 평가한다.
- Fixed rule 또는 adaptive `StrategyAgent`를 실행한다.
- Stored alpha를 strategy rerun 없이 ensemble한다.
- Signed active intent를 benchmark-relative long-only enhanced index portfolio로 변환한다.
- Physical target을 Qlib order/fill/account lifecycle에서 실행한다.
- Signed alpha 자체는 별도의 matched-capitalization compatibility route로 실행 진단할 수 있다.
- 성공, 실패, invalid result와 research decision을 다음 연구의 evidence로 남긴다.
- Built-in module을 documented project-local extension으로 교체하거나 확장한다.

각 capability는 독립적으로 사용할 수 있다. 모든 연구가 하나의 end-to-end pipeline을 따라야 하는 것은
아니다. 다만 서로 다른 route와 artifact를 연결할 때는 이 문서의 time, unit, identity와 authority
contract를 만족해야 한다.

### 1.2 제품 철학

#### Qlib dealt fill이 market execution의 유일한 authority다

Tradability, submitted order, dealt quantity, cost, physical position과 cash는 Qlib lifecycle을 따른다.
qlibx는 별도 fill engine이나 independent signed execution ledger를 유지하지 않는다.

Matched-capitalization의 baseline activation, top-up과 release는 market fill이 아니다. 이는 Qlib
composite account와 qlibx baseline sub-account를 함께 바꾸는 명시적 account administration event다.
이 event는 별도 authority, event log와 atomic reconciliation contract를 따른다.

#### Stored result는 의미가 닫힌 public integration point다

Artifact는 schema만 맞아서는 안 된다. Time boundary, economic unit, reference NAV, currency,
implementation identity, producer trust와 compatibility grade가 호환될 때만 downstream input으로 사용할
수 있다.

#### 새 연구는 기존 evidence와 evidence consumption에서 시작한다

Agent는 성공한 alpha뿐 아니라 실패, invalid run, searched range, decision과 evaluation exposure를
조회한다. 이미 반복 관측된 segment를 sealed holdout 또는 true forward evidence로 표시하지 않는다.

#### Built-in은 일관성을, local extension은 trusted-code 자율성을 제공한다

Common transform, exposure, portfolio diagnostic과 reporting은 versioned built-in으로 제공한다.
Project-local extension은 public contract로 연결하지만 v1에서는 trusted code로 취급한다. Untrusted code
sandbox는 out of scope다.

#### 같은 repository와 branch에서 qlibx-owned state를 병렬 처리한다

qlibx는 session isolation, frozen input, atomic catalog publication, duplicate/conflict detection과 crash
isolation을 기본 제공한다. User-owned source/config의 동시 편집, Git merge와 overwrite 방지는 보장하지
않는다.

### 1.3 전체 research flow와 route

```text
project-owned source
-> versioned point-in-time dataset / cost / risk input
-> frozen run
-> StrategyAgent decision
-> ticker-level signed alpha
-> stored-alpha ensemble
-> combined active intent
   -> Route A: enhanced-index construction -> long-only physical target -> Qlib market execution
   -> Route B: matched-capitalization composite target -> Qlib market execution + account administration
-> verified artifact / decision / report / next-decision feedback
```

Route A는 long-only enhanced-index implementation route다. Route B는 signed alpha의 execution feasibility와
implementation effect를 진단하기 위한 compatibility route이며, Route A의 deployability 또는 promotion
evidence를 자동으로 대체하지 않는다.

## 2. Product boundaries and authority

### 2.1 qlibx가 담당하는 것

- Project, dataset, cost, risk input과 frozen-run contract
- Agent onboarding, public documentation, schema와 skill resource
- StrategyAgent input/output/state와 bounded nested research
- Signed alpha, transform, budget, metric과 diagnostics
- Evaluation governance와 centralized research catalog
- Stored-alpha ensemble과 enhanced-index construction
- Matched-capitalization account administration와 reconciliation
- Artifact portability, retention, reporting과 local extension validation
- qlibx-owned state의 parallel publication과 recovery

### 2.2 Qlib에 맡기는 것

- Closed-loop decision/execution schedule
- Exchange와 tradability behavior
- Order submission, dealt quantity와 partial fill
- Suspension, price/volume limit과 lot handling
- Physical position, cash, execution cost와 account feedback

### 2.3 Project가 소유하는 것

- Source와 preprocessed data
- Dataset, strategy, model, portfolio와 reporting config
- Benchmark, sector, factor, constraint, cost와 risk definition
- Trusted local extension source
- Research objective, evaluation threshold와 promotion decision
- Secret와 external service credential

Project가 definition을 소유하더라도 qlibx는 identity, time semantics, validation과 lineage를 요구한다.
qlibx upgrade는 project-owned definition을 조용히 수정하지 않는다.

### 2.4 Human과 agent authority

| Action | Agent default authority | Human approval requirement |
|---|---|---|
| Help/schema/catalog inspect | Read-only로 허용 | 불필요 |
| Proposal과 dry-run 생성 | 허용 | 불필요 |
| Derived project file materialize | 변경 파일을 사전 표시 | Project policy에 따름 |
| Bounded research execute | Declared quota 안에서 허용 | Project policy에 따름 |
| Catalog publish | Immutable run/result publish 허용 | 불필요 |
| Promote/reject/supersede | 제안과 evidence 작성 | 최종 authority는 project policy |
| Sealed holdout unlock | 금지 | Named human/reviewer approval 필수 |
| Local code execute | Trusted extension만, capability 기록 | Project policy에 따름 |
| Secret/network/subprocess 사용 | Default deny 또는 explicit capability | 명시적 승인/정책 필수 |

### 2.5 Out of scope

- Qlib native short-position support 추가
- Qlib core order/fill/account/backtest engine 대체
- Upstream market-data normalization system 구축
- Git branch, worktree와 merge 관리
- User-owned file edit의 conflict-free 보장
- Local extension을 위한 security sandbox
- 경제적 가설의 투자 가능성을 user-defined criteria 없이 대신 결정
- Borrow, locate, recall, margin과 forced buy-in의 완전한 시장 모델

### 2.6 금지 behavior

- Source data를 명시적 요청 없이 이동, 수정 또는 overwrite한다.
- Required semantic을 column name이나 regex로 추측한다.
- Installed qlibx, Qlib 또는 site-packages를 project extension 목적으로 수정한다.
- Requested target 또는 별도 ledger를 realized Qlib holding으로 취급한다.
- Flexible budget unused amount를 자동 복원하거나 관계없는 security에 배분한다.
- 이미 노출된 segment를 sealed holdout 또는 live forward로 표시한다.
- Environment-bound checkpoint나 opaque attachment를 canonical integration input으로 사용한다.
- Verification, trust 또는 compatibility가 불명확한 artifact를 promotion evidence로 사용한다.
- 지원 범위 밖 Qlib version에서 warning만 남기고 계속 실행한다.

## 3. Global semantic invariants

### 3.1 Time and point-in-time invariant

Dataset은 의미에 따라 다음 시간 중 필요한 것을 선언한다. Field name은 구현 schema 이름을 강제하는
것이 아니라 semantic distinction이다.

- `event_time`: 경제적 사건 또는 측정 시점
- `valid_time`: 값이 대표하거나 효력을 갖는 기간
- `knowledge_time` 또는 `published_at`: 해당 vintage를 알 수 있게 된 시점
- `ingested_at`: project가 해당 vintage를 수집한 시점
- `superseded_at` 또는 revision sequence: 이전 vintage가 대체된 시점

Decision subscription은 다음 규칙을 따른다.

```text
knowledge_time <= decision_time인 record만 후보로 삼고,
각 observation key에서 decision_time 당시 latest-known vintage를 선택한다.
```

`ingested_at`은 provenance와 operational replay를 위한 정보이며, project policy가 명시하지 않는 한
economic availability를 대신하지 않는다. Correction은 기존 immutable snapshot을 소급 변경하지 않고 새
snapshot/vintage를 발행한다.

Benchmark membership/weight는 최소 `announced_at`, `effective_from`, `effective_to`와 revision identity를
가진다. Announcement 이후 선반영을 허용할지, effective date부터만 target에 반영할지는 별도 policy다.

### 3.2 Quantity, NAV and financing invariant

다음 quantity는 서로 다른 type으로 취급한다.

- Signal: dimensionless score
- Active weight: declared reference NAV에 대한 benchmark-relative weight
- Ensemble coefficient: member combination parameter
- Total constituent weight: total portfolio NAV에 대한 weight
- Physical target: currency, valuation time, price와 lot convention을 가진 quantity/weight
- Order/fill/holding: Qlib physical account quantity

Canonical conversion은 다음 순서를 따른다.

```text
dimensionless signal
-> declared alpha-to-active-weight policy
-> active weight on declared reference NAV
-> member normalization and ensemble
-> benchmark weight + active-risk multiplier × combined active weight
-> constraint projection
-> physical target + explicit cash/passive residual
-> desired / submitted / filled / held quantity
```

모든 weight artifact는 denominator, gross/net/side budget, leverage meaning, currency와 valuation timestamp를
가진다. Ensemble coefficient 적용 전 member normalization 여부도 선언한다.

Long-only physical result는 다음을 만족한다.

```text
sum(stock physical weights)
+ sum(ETF physical weights)
+ cash weight
= 1
```

허용 tolerance, borrowing 또는 leverage가 있다면 policy와 residual을 명시한다. Lot rounding, blocked trade,
constraint relaxation 뒤에도 intended, feasible, submitted, filled와 held stage의 denominator를 보존하고
차이를 artifact로 남긴다.

### 3.3 Reproducibility invariant

모든 run은 시작 전에 한 등급을 가진다.

1. `deterministic`: 동일 frozen input/implementation에서 canonical payload가 byte-equivalent하거나
   schema가 선언한 semantics-equivalent result를 만든다.
2. `seeded_stochastic`: RNG algorithm, library version, seed stream과 parallelism condition을 freeze하고
   artifact가 선언한 numerical tolerance 안에서 replay한다.
3. `externally_stochastic`: provider response, model revision 또는 external state 때문에 replay를
   보장하지 않는다. Request/response identity, external dependency와 non-reproducible flag를 남긴다.

Resume equivalence와 cache reuse는 등급별로 정의한다. `externally_stochastic` result의 promotion과 cache
reuse는 project policy가 명시적으로 허용해야 한다.

### 3.4 Identity and frozen-run invariant

Frozen run identity는 최소 다음을 포함한다.

- Resolved effective config content digest
- Dataset definition과 physical snapshot/content digest
- Cost/risk/benchmark input identity
- Local extension source와 relevant transitive dependency digest
- qlibx, Qlib, Python, numerical library, solver와 native dependency version
- Calendar, timezone database와 numerical backend
- Reproducibility grade, seed와 platform-sensitive option

Immutable snapshot, content-addressed manifest 또는 versioned external reference 중 어떤 보증을 제공하는지
명시한다. Mutable path 이름만으로 frozen identity를 만들지 않는다.

### 3.5 Failure and degraded-result invariant

모든 component는 다음 상태를 공통 의미로 사용한다.

- `failed`: required semantic이나 operation을 완료하지 못해 result가 유효하지 않음
- `unsupported`: 해당 feature/input을 product가 지원하지 않음
- `partial`: 유효한 coverage가 일부이며 범위가 명시됨
- `degraded`: core result는 유효하지만 optional diagnostic 또는 market model이 제한됨
- `warning`: result validity를 깨지 않는 관측 사항

Required input 누락, incompatible axis/unit/time boundary는 `failed`다. ETF constituent가 없어 opaque ETF로
실행하는 것은 look-through에 대해 `degraded`일 수 있다. Component는 중요한 limitation을 임의로 warning으로
낮추지 않는다.

## 4. Project, data, cost and compatibility contracts

### 4.1 Package와 project 분리

Package는 reusable code, schema, built-in, documentation과 onboarding resource를 제공한다. Project는
data, config, local extension, research record와 generated state를 소유하고 각 root를 선택한다.

### 4.2 Logical dataset

qlibx는 project-owned Parquet dataset과 DuckDB file/query를 logical dataset으로 등록한다. Definition은
다음을 포함한다.

- Dataset ID, schema version, source type과 project-relative location
- Table/query, required column, primary key와 output shape
- Date/ticker/value semantic, dtype, frequency와 timezone
- §3.1의 applicable time/revision field와 as-of selection policy
- Missing, duplicate, alignment, universe와 tradability meaning
- Physical content/snapshot identity

Required meaning이 없으면 명확히 실패한다. Registration은 source를 read-only inspect하고, source-to-Qlib
mapping과 가정을 user에게 보여준 뒤 qlibx-owned derived data를 materialize한다. 원본은 변경하지 않는다.

Daily OHLCV default profile은 `t-1`까지 알려진 data를 보고 `t`일 종가에 거래·평가한다. Price, factor,
volume, suspension, price limit, membership와 corporate-action mapping을 명시하며, 없는 의미를 추측하지
않는다.

### 4.3 Universe and tradability

Research universe와 Qlib execution tradability는 별개다.

- Research universe는 strategy가 signal 또는 target을 만들 수 있는 instrument를 나타낸다.
- Qlib tradability는 registered price, suspension, price-limit, volume-limit과 execution profile을
  사용해 실제 order가 체결 가능한지를 판단한다.
- Matrix axis에 ticker가 있다는 사실만으로 universe membership이나 tradability를 추론하지 않는다.
- 제공되지 않은 shortability, borrow inventory 또는 exchange restriction을 추측하지 않는다.
- Universe에서 빠진 holding은 desired target에서 제거할 수 있지만 actual liquidation은 Qlib fill로만
  확인한다.

Universe entry/exit, blocked liquidation과 re-entry는 source가 표현하는 범위에서 관측 가능해야 한다.
표현하지 못하는 상태는 `degraded` limitation으로 남기며 완전한 market reality로 보고하지 않는다.

### 4.4 Cost model

Cost는 dataset과 같은 급의 versioned input contract다. Cost model은 다음을 선언한다.

- Component: commission, tax, spread, slippage, impact, borrow-related assumption 등
- 적용 instrument, side, venue와 execution stage
- Rate, unit, currency, minimum fee와 rounding
- Announcement/effective time와 applicable vintage
- Estimated/actual schedule 구분과 calibration dataset
- Research-time capacity proxy와 execution-time cost 구분
- Model ID/version, parameter와 frozen-run identity

Expected cost, Qlib simulated/realized cost와 post-trade attribution은 별도 metric이다. Cost identity가
바뀌면 cost-aware evaluation, portfolio와 backtest identity도 달라진다.

### 4.5 Risk method

Enhanced-index constructor는 다음 중 하나를 선언한다.

- `risk_model`: covariance/factor input으로 ex-ante predicted active risk 계산
- `scenario`: historical/user-defined scenario distribution으로 predicted risk 계산
- `constraint_only`: exposure/weight deviation을 통제하며 predicted tracking error는 제공하지 않음

Risk input은 estimation window, availability time, frequency, annualization, missing/shrinkage policy,
model version과 coverage를 가진다. Ex-post realized tracking error는 realized active return artifact에서
별도로 계산한다. Constraint-only proxy를 predicted tracking error라고 부르지 않는다.

### 4.6 Version compatibility and migration

Release metadata는 supported Qlib version range와 tested adapter matrix를 선언한다. 범위 밖에서는
명확히 실패한다.

Catalog/artifact는 현재 qlibx에서 다음 상태 중 하나다.

- `native_readable`
- `read_only_legacy`
- `deterministically_migratable`
- `incompatible_quarantined`

Migration은 original payload와 lineage를 보존한다. Package upgrade가 과거 evidence를 조용히 재해석,
삭제 또는 promotion 가능 상태로 바꾸지 않는다.

## 5. Human and AI-agent journey

### 5.1 Onboarding

User는 package를 설치하고 project-owned data를 준비한 뒤 agent instruction/skill을 추가할 수 있다.
Onboarding action은:

- Supported instruction file을 detect하고 target을 선택하게 한다.
- Dry-run 후 delimiter가 있는 managed block만 create/update/remove한다.
- Repeated execution이 idempotent하며 user-authored content를 보존한다.
- Version-matched `SKILL.md`, reference, schema와 example을 selected directory에 생성한다.

### 5.2 Agent-readable public surface

Installed help와 documentation은 project initialization, data registration, StrategyAgent, alpha,
catalog/evaluation governance, ensemble, enhanced index, Qlib route, extension, artifact, reporting, error와
recovery를 제공한다.

Agent는 private source를 읽지 않고 task-specific help, machine-readable schema와 bounded example을 조회할
수 있어야 한다.

### 5.3 Project inspection and data registration

Agent는 변경 전에 project root, qlibx/schema/Qlib compatibility, registered input, catalog/session,
trust policy와 만들거나 바꿀 file을 확인한다.

Registration 시:

1. Source를 read-only inspect한다.
2. Required semantic과 time/revision meaning을 확인한다.
3. Qlib input mapping, derived field, 가정과 unsupported feature를 제시한다.
4. Ambiguity를 추측하지 않고 질문 또는 실패로 남긴다.
5. Approved mapping으로 derived data/config를 materialize한다.
6. Schema, uniqueness, point-in-time query와 bounded load를 검증한다.
7. Input identity, result, warning과 limitation을 반환한다.

### 5.4 Alpha research and publish

Agent는 새 trial 전에 prior alpha, failed/invalid trial, searched range, active proposal, nearest neighbor,
segment exposure와 remaining search/evidence budget을 확인한다.

Proposal은 hypothesis, mechanism, input, clock, horizon, transform, segment role, comparison set, cost/risk
assumption, stopping condition과 search limit을 가진다. Promotion을 의도하는 proposal은 사전에 관측 가능한
prediction과 falsification condition을 선언할 수 있어야 한다.

Run은 isolated session과 frozen identity에서 수행한다. Completed attempt는 run/artifact/metric/status,
prior comparison, evidence exposure, concise decision과 next action을 atomic하게 publish한다.

## 6. StrategyAgent

### 6.1 Definition and decision context

StrategyAgent는 declared reproducibility grade를 가진 decision program이다. Decision context는 필요에 따라
다음을 포함한다.

- Decision time과 dataset별 bounded lookback
- Point-in-time universe와 Qlib tradability state
- Previous desired/submitted/filled/held position
- Realized return, PnL, cost와 turnover
- Qlib-confirmed feedback history
- Strategy-owned state와 model/belief identity
- Isolated nested-research interface

Current-bar fill은 이후 Qlib decision context에서만 전달한다. Next decision은 requested target이 아니라
actual holding을 본다.

### 6.2 Typed decision authority

Output kind는 다음 capability를 가진다. Public type name은 구현에서 달라질 수 있지만 authority 구분은
유지한다.

| Output kind | 허용 downstream use | 금지 use |
|---|---|---|
| Signal decision | Rank, transform, alpha evaluation | 직접 주문 |
| Active-weight decision | Budget, ensemble, portfolio construction | Physical fill 주장 |
| Physical-target decision | Lot/order conversion, execution adapter | Alpha score처럼 재해석 |
| Order decision | Qlib execution adapter | 추가 optimizer의 암묵 적용 |
| Diagnostic payload | Record와 report | Decision/execution input |

Parent/wrapper는 child output의 kind, axis, unit과 time boundary를 검증한 뒤 composition한다. Arbitrary
declared payload를 generic execution path에 전달하지 않는다.

### 6.3 Nested research and resource bound

Child는 parent decision에서 볼 수 있는 data/feedback보다 넓거나 늦은 정보를 볼 수 없다. Child evaluation은
actual Qlib account, parent state 또는 sibling state를 변경하지 않는다.

Initial supported contract는 한 단계 parent-to-child nesting이다. Child가 다시 child를 spawn하는 recursive
nested research는 unsupported로 명확히 실패한다.

Request와 project policy는 다음 aggregate limit을 강제한다.

- Parent당 총 child evaluation과 concurrent child 수
- CPU, memory, wall time와 artifact byte quota
- Session/project admission control
- Parent cancellation/crash 시 descendant cancellation
- Resource limit으로 중단된 attempt의 `cancelled` 또는 `deferred_resource_limit` publication

### 6.4 State, ML and resume

Model retraining, Bayesian update, trailing evidence 기반 allocation과 regime response는 bounded input 안에서
허용된다. Model version, train/evaluation window, selected action과 state identity를 기록한다.

Fresh run은 explicit checkpoint가 없으면 fresh state에서 시작한다. Environment-bound checkpoint는 resume
전용이다. Resume equivalence는 §3.3 reproducibility grade별 tolerance를 따른다.

## 7. Signed alpha and canonical metrics

### 7.1 Canonical alpha result

Atomic alpha는 ticker-level signal 또는 active weight를 반환하며 kind를 명시한다. Synthetic execution
asset은 underlying alpha ranking/universe에 섞지 않는다.

Result는 signal/weight, unit/reference NAV, exposure, coverage, missingness, turnover, cost, information
availability, segment role/metric과 snapshot을 포함한다.

### 7.2 Built-in transform and exposure

Initial built-in은 rank, demean, z-score, winsorization, clipping, group demean, beta residualization, lag,
rolling statistic, linear decay, hump/barrier, top/bottom selection, per-name cap, fixed/flexible budget,
matrix alignment과 no-look-ahead check를 포함한다.

Operation은 axis, tie/NaN/group-missing behavior, minimum observation, dtype, parameter, ID와 version을
문서화한다.

Neutrality mode는 mandatory가 아니다. Transform을 적용했다는 사실을 exact neutrality의 증명으로
표시하지 않는다. Exposure analyzer는 method, input identity, window, coverage와 missingness를 남긴다.

### 7.3 Budget provenance

Fixed dollar-neutral default는 양쪽 candidate가 feasible할 때 다음을 목표로 한다.

```text
sum(long active weights)  =  1
sum(short active weights) = -1
```

Flexible budget은 side amount를 maximum으로 취급한다. Unused budget을 자동 복원하지 않는다.

Default 또는 explicit policy와 관계없이 effective config에 budget policy를 materialize하고 다음 snapshot을
각각 보존한다.

- Raw signal
- Pre-budget candidate weight
- Post-budget active weight

Result summary는 default 적용 여부와 before/after exposure를 표시한다.

### 7.4 Canonical metric semantics

Comparable metric artifact는 formula/version, input frequency, segment, annualization factor, benchmark,
currency, cash return, cost scope/timing, missing date, delisting 처리와 coverage를 가진다.

Orthogonality metric은 `scale_invariant` 여부를 선언한다. Pearson/Spearman correlation은 raw view를
제공할 수 있다. Holding distance, turnover notional, trade overlap, marginal PnL, concentration과 capacity
같은 scale-sensitive metric은 raw view와 common-budget-normalized counterfactual을 구분한다. Sign reversal을
같은 family로 처리하는지도 명시한다.

## 8. Research catalog and evaluation governance

### 8.1 Catalog and identity

Project-local file-backed catalog는 dataset/frozen config, proposal, run, model, alpha, ensemble, portfolio,
backtest, metric, decision, lineage, session과 agent identity를 저장하거나 reference한다.

각 session은 isolated scratch workspace를 사용할 수 있다. Scratch script, note와 intermediate output은
canonical evidence가 아니며, completed attempt로 atomic publish되기 전에는 catalog의 verified result로
보이지 않는다. 다른 agent는 전체 scratch를 읽지 않고 catalog record만으로 다음 연구를 시작할 수 있어야
한다.

Alpha definition, alpha run, ensemble run, portfolio run, route run과 backtest run은 서로 다른 identity다.
Transitive input이 바뀌면 dependent identity가 달라진다. Compatible upstream artifact는 rerun 없이
재사용한다.

### 8.2 Independent state machines

세 lifecycle은 독립적이다.

- Attempt: `proposed -> running -> completed | failed | cancelled | invalid`
- Artifact verification: `pending -> verified | corrupt | incompatible | quarantined`
- Research decision: `exploratory -> retained | promoted | rejected | superseded`

각 transition은 actor, reason, expected prior version과 append-only audit event를 가진다. Completed attempt가
rejected될 수 있고 invalid attempt가 diagnostic evidence로 남을 수 있다. Verification되지 않은 artifact는
promotion input이 아니다.

### 8.3 Evaluation governance

Evaluation segment는 `train`, `validation`, `test`, `sealed_holdout`, `live_forward` 중 역할을 가진다.
Catalog는 누가 언제 어떤 segment의 aggregate metric, series 또는 pass/fail 정보를 보았는지 exposure
ledger에 기록한다.

Proposal은 search budget과 실제 trial count를 가진다. Project-selected multiple-testing/false-discovery
policy와 promotion threshold를 기록한다.

Sealed holdout unlock은 named reviewer 승인이 필요하다. Unlock 후 공개된 정보량을 기록하고 해당 segment는
project policy에 따라 test/validation으로 강등한다. Supersede는 과거 decision이나 나쁜 result를 삭제하지
않는다.

### 8.4 Orthogonality and decision record

Candidate는 semantic, empirical, incremental level에서 비교한다. Low PnL correlation만으로 independence를
인정하지 않는다. Result는 reference pool, segment, scale semantics, missing comparison, metric과 threshold를
기록한다.

Promotion/rejection/supersede는 evidence run, evaluation policy, reviewer와 rationale를 reference한다.
Promotion evidence와 exploratory evidence를 구분한다.

### 8.5 Parallel publication

qlibx-owned runtime/catalog state는:

- Session/workspace를 isolate한다.
- Frozen input을 run 중 변경하지 않는다.
- Concurrent run과 atomic publication을 지원한다.
- Duplicate content를 deduplicate하고 identity conflict를 실패시킨다.
- Retry를 idempotent하게 처리한다.
- Incomplete publish를 complete result로 노출하지 않는다.
- Crash가 다른 session/completed result를 손상시키지 않게 한다.
- Stale state transition을 실패시킨다.

이 보장은 user-owned source/config의 동시 edit이나 Git merge에는 적용되지 않는다.

### 8.6 Retention, archive and rebuild

Canonical proposal, lifecycle state, decision, metric summary, lineage와 tombstone은 계속 queryable하게
유지한다. Large payload, checkpoint, scratch, diagnostic attachment와 report deliverable은 class별
retention/archival/GC policy를 가진다.

Pinning, export/import, catalog rebuild와 삭제 audit를 제공한다. Payload가 삭제되어도 누가, 언제, 왜
삭제했는지와 원래 identity를 tombstone으로 보존한다. Secret 또는 법적 삭제 요구는 metadata retention
정책보다 우선할 수 있으며 그 결과를 명시한다.

## 9. Ensemble and enhanced-index construction

### 9.1 Stored-alpha ensemble

Verified portable canonical alpha artifact만 canonical ensemble input으로 사용한다. Member strategy는
필요하지 않으면 다시 실행하지 않는다.

Compatibility validation은 다음을 포함한다.

- Common decision grid, calendar, timezone과 as-of alignment
- Rebalance frequency, holding horizon과 effective/expiry time
- Slow member의 maximum staleness
- Holiday, missing rebalance와 partial coverage 처리
- Point-in-time universe에서 absent ticker의 의미
- Reference NAV, gross/net budget과 coefficient normalization
- Partial coverage 때 coefficient renormalization 여부

Result는 member/run ID, coefficient/effective weight, ticker contribution/netting, combined active intent,
budget/exposure, similarity/marginal contribution과 full lineage를 제공한다.

### 9.2 Enhanced-index constructor

Route A는 다음을 수행한다.

```text
point-in-time benchmark weight
+ active-risk multiplier × combined active weight
-> desired total constituent exposure
-> hard/soft constraint projection
-> long-only stock / ETF / cash physical target
```

Input은 benchmark, active intent, current Qlib holding/cash, price/lot/tradability, optional look-through,
versioned cost, declared risk method와 constraint다.

Result는 desired active/total exposure, stock/ETF/cash target, look-through, constraint residual, binding
constraint, solver status, infeasibility/relaxation, expected trade/cost와 predicted risk 또는 model-free
diagnostic을 제공한다.

Hard infeasibility, soft relaxation, solver failure, partial coverage와 degraded look-through를 구분한다.
Unknown instrument나 incompatible axis/unit을 silent exclusion하지 않는다.

### 9.3 Physical instrument and look-through

지원 physical instrument는 stock과 ETF다. Qlib Account/Position이 physical quantity의 source다.
ETF constituent data가 없으면 ETF를 opaque instrument로 거래할 수 있으나 look-through는 제공하지 않는다.
Point-in-time constituent dataset이 있을 때만 constituent exposure를 계산한다.

Physical holding과 look-through exposure는 별도 artifact다. Instrument type별 price, lot, cost와 execution
metadata를 명시한다.

### 9.4 Capital efficiency and robustness diagnostics

Volume/cost data가 있으면 result는 participation-rate와 booksize에 따른 capacity diagnostic을 제공할 수
있다. Capacity 수치는 assumption과 scale을 명시한다.

후속 built-in은 historical stress replay와 synthetic perturbation을 별도 artifact로 제공한다. 평균
performance, historical regime behavior와 assumption fragility를 한 metric으로 합치지 않는다.

## 10. Qlib execution routes

### 10.1 Route taxonomy

| Route | 목적 | Output semantics | Promotion limitation |
|---|---|---|---|
| A: enhanced index | Deployable long-only benchmark-relative portfolio | Total-NAV physical stock/ETF/cash target | Route A evidence로 사용 가능 |
| B: matched capitalization | Signed alpha execution/implementation diagnostic | Active-book signed position reconstructed from composite holding | Route A deployability를 대체하지 않음 |

같은 alpha의 두 route는 별도 route run/backtest identity를 가진다. 비교 report는 denominator, cost,
capital usage와 implementation gap을 명시한다.

### 10.2 Qlib market execution

Physical target은 price, booksize와 lot rule로 quantity가 되고 Qlib lifecycle을 통과한다. Order/fill은
requested/dealt quantity, clipping stage와 reason을 제공한다. Partial fill 이후 optimizer와 StrategyAgent는
actual holding을 본다. Cash와 marked physical holding은 Qlib account에 reconcile한다.

### 10.3 Matched-capitalization accounting

각 ticker에서:

```text
A = realized signed active quantity
B = matched baseline quantity, B >= 0
C = Qlib composite quantity, C >= 0

C = B + A
A = C - B
```

Active booksize와 baseline funding reserve는 분리한다. Qlib account는 `C`를 소유하고 baseline sub-account는
`B`와 matching reserve cash를 추적한다. Independent signed fill ledger는 없다.

Market `SELL`/`BUY`만 active position을 실제로 바꾼다. Baseline activation/top-up/release는 Qlib dealt
fill이 아닌 account administration event다.

### 10.4 Account administration atomicity

Administration event는:

- Decision/execution boundary 중 documented safe point에서만 발생한다.
- Composite position/cash와 baseline quantity/reserve를 하나의 joint commit ID로 저장한다.
- Event 전후 balance-sheet identity, composite NAV와 reconstructed active NAV를 검증한다.
- 한쪽 state만 저장된 crash를 rollback하거나 quarantined checkpoint로 표시한다.
- 다음 decision에서 `A = C - B`를 복원할 수 있어야 한다.
- Qlib public lifecycle과 supported adapter에서 feasible함이 증명되기 전에는 supported로 표시하지 않는다.

Dividend, split, delisting, stale price, FX와 cash interest가 `A`, `B`, `C`, reserve와 NAV에 미치는 정책을
instrument contract로 선언한다.

### 10.5 Activation, fill and release

Negative active intent에 baseline이 필요하면 execution-time price, lot, short cap과 safety policy로
required `B`를 계산한다. Matching quantity/cash를 atomic하게 추가한 뒤 `C_target = B + A_target`을
Qlib에 제출한다.

Active short는 actual underlying Qlib `SELL`이다. Cover는 actual `BUY`다. Blocked cover 뒤에는 baseline을
유지하고 actual cover fill 뒤에만 release한다. Funding reserve 부족 또는 `C_target < 0`은 실패다.

### 10.6 Performance and capital usage

Result는 intended signed intent, baseline/reserve before-after, administration event, Qlib order/fill,
composite/reconstructed holding, cost, turnover, PnL과 reconciliation을 제공한다.

Canonical active return은 active booksize를 denominator로 하고 baseline price movement를 제거한다. 별도로
다음을 제공한다.

- Reserve balance와 peak/average utilization
- Reserve 부족으로 blocked된 short intent
- Reserve cash에 실제 발생한 interest/carry
- Total committed-capital return
- User가 alternative/hurdle을 정의한 경우에만 opportunity-cost scenario

Opportunity-cost scenario를 canonical active PnL과 섞지 않는다.

### 10.7 Compatibility limitations

Matched-capitalization은 native short가 아니다.

- Borrow, locate, recall, margin, forced buy-in, borrow fee와 securities-lending capacity를 자동으로
  재현하지 않는다.
- Baseline reserve가 부족하면 새 short를 실행할 수 없다.
- Composite account return은 signed active return과 같지 않다.
- Universe 교체가 잦으면 activation, retention, release와 reserve usage가 증가한다.
- Corporate action, delisting, normalized price/quantity 또는 FX input이 잘못되면 reconstructed result도
  잘못된다.
- Composite position의 non-negative invariant나 reconciliation이 깨지면 run을 실패 또는 quarantine한다.

## 11. Extension, artifact and reporting

### 11.1 Extension contract and trust

모든 extension point는 purpose, workflow 위치, input/output kind/schema/axis/unit/time boundary, lifecycle,
side effect, error, compatibility, composition과 minimal example을 version-matched public documentation으로
제공한다.

Local extension은 v1에서 trusted code다. Run은 producer trust level과 filesystem/network/subprocess/secret
capability 사용을 기록한다. Secret은 config, artifact, report와 log에서 redaction하고 content digest나
raw value로 저장하지 않는다. External process/network 사용은 reproducibility grade에 반영한다.

### 11.2 Artifact grade

Artifact는 다음 grade 중 하나다.

- `portable_canonical`: versioned independent loader가 있으며 canonical integration/promotion에 사용 가능
- `environment_bound_checkpoint`: exact environment를 요구하는 resume 전용 payload
- `diagnostic_attachment`: opaque 또는 non-canonical payload, record/report만 가능
- `report_deliverable`: HTML/image/document 등 최종 표현물, promotion graph input은 아니지만 provenance 유지

Artifact envelope은 type/schema, stable ID, producer/source/environment identity, parent/input, bounded time,
axis/unit/currency/timezone, payload grade/reference, trust, coverage, warning과 completion/verification status를
포함한다.

Initial canonical format은 metadata/config에 JSON, table/matrix에 Parquet 또는 Arrow-compatible format을
사용한다. Arbitrary serializer는 checkpoint나 attachment로 사용할 수 있지만 portable을 자칭할 수 없다.
User는 portable canonical artifact를 export하고 qlibx 밖에서 처리한 뒤 schema, lineage, trust와
verification을 만족하는 compatible artifact로 다시 import할 수 있다.

### 11.3 Reporting

Reporting은 stored artifact만 읽으며 live Strategy/Qlib object를 요구하거나 research를 rerun하지 않는다.

- Analysis는 performance, exposure, attribution, turnover와 reconciliation 수치를 계산한다.
- Composition은 section을 선택, 결합, 제거, 재배열한다.
- Renderer는 table, chart, HTML, notebook 또는 document로 표현한다.

Built-in analysis는 최소 performance/risk summary, signal/weight coverage, turnover, available exposure,
cost/order/fill reconciliation, member/ensemble/optimizer attribution과 Route B composite/baseline/active
reconciliation을 제공한다.

Report deliverable은 source artifact, analysis module/version과 renderer/version을 기록한다. Report를
canonical alpha/portfolio evidence로 승격하지 않지만 provenance는 버리지 않는다.

## 12. Release gates and acceptance contract

`P0`~`P7` capability 번호는 사용하지 않는다. 아래 gate는 dependency 순서를 나타낸다. 뒤 gate는 앞
gate를 통과해야 supported release로 표시할 수 있다.

### G0 — Semantic foundation

- Time/vintage, unit/NAV, reproducibility, frozen identity와 failure taxonomy schema가 확정된다.
- Qlib support matrix와 artifact migration state가 동작한다.
- Canonical fixture에서 incompatible time/unit/axis/version이 execution 전에 실패한다.

### G1 — Data and reproducible research

- Agent onboarding, data registration, StrategyAgent, signed alpha와 canonical metric이 동작한다.
- Bitemporal fixture에서 revised final value가 과거 decision에 노출되지 않는다.
- Deterministic replay는 canonical payload equality를, seeded replay는 declared tolerance를 만족한다.
- Child가 parent boundary를 넘거나 recursive spawn을 시도하면 명확히 실패한다.

### G2 — Catalog and governed parallel research

- 세 concurrent session이 qlibx-owned state에서 atomic publish한다.
- Duplicate, identity conflict, crash point와 stale transition fixture가 예상 lifecycle 상태를 만든다.
- Attempt/verification/decision lifecycle이 독립적으로 query된다.
- Holdout exposure와 unlock/role-change가 audit된다.
- Retention/GC 후 canonical metadata와 tombstone으로 catalog를 rebuild할 수 있다.

### G3 — Ensemble and enhanced-index Route A

- 서로 다른 calendar/staleness/reference NAV member의 compatible/incompatible fixture를 판정한다.
- Combined active intent부터 physical target까지 unit과 total-weight identity가 reconcile된다.
- `risk_model`, `scenario`, `constraint_only` output 의미가 구분된다.
- Hard infeasible, soft relaxed, solver failed와 degraded look-through가 별도 상태로 반환된다.
- Partial fill 뒤 desired/submitted/filled/held 차이와 next-decision feedback이 일치한다.

### G4 — Matched-capitalization Route B

- Supported Qlib version에서 administration feasibility test를 통과한다.
- Activation/top-up/release의 모든 crash point에서 joint state가 commit, rollback 또는 quarantine된다.
- Corporate action과 cash-interest fixture에서 balance sheet와 `A = C - B`가 유지된다.
- Blocked sell/cover, partial fill, reserve exhaustion과 universe change를 reconcile한다.
- Active return, composite return, committed-capital return과 opportunity-cost scenario를 분리한다.

G4를 통과하기 전 Route B는 experimental/unsupported이며 deployable capability로 광고하지 않는다.

### G5 — Trusted extension and reporting

- Agent가 public documentation만으로 local transform/analyzer/reporter를 작성하고 validate한다.
- Permission/secret policy 위반은 publish 전에 실패하고 secret이 artifact/log에 남지 않는다.
- Portable canonical, checkpoint, attachment와 report deliverable의 allowed use가 강제된다.
- Stored artifact에서 research rerun 없이 multiple renderer report를 만든다.

### 12.1 Canonical acceptance scenarios

| ID | Scenario | Expected observable/pass condition |
|---|---|---|
| AC-TIME-01 | 같은 event의 original/revised vintage | 각 decision은 당시 latest-known vintage만 받는다 |
| AC-UNIT-01 | signal을 weight input에 직접 연결 | Explicit conversion policy 없이는 실패한다 |
| AC-REP-01 | deterministic full run과 resume | Declared canonical equality를 만족한다 |
| AC-REP-02 | external AI response 사용 | `externally_stochastic`과 request/response identity가 남는다 |
| AC-CAT-01 | publish 중 process crash | Partial artifact가 verified complete로 보이지 않는다 |
| AC-CAT-02 | sealed holdout 조회 | Approval/exposure event와 role transition이 남는다 |
| AC-ENS-01 | stale slow member | Declared staleness 초과 시 fail 또는 explicit exclusion policy를 적용한다 |
| AC-PORT-01 | active intent를 long-only projection | Physical weights와 cash가 declared tolerance에서 1로 합산된다 |
| AC-RISK-01 | constraint-only constructor | Predicted tracking error field를 생성하지 않는다 |
| AC-EXEC-01 | partial fill | Realized holding은 Qlib dealt quantity로만 변한다 |
| AC-ADMIN-01 | baseline top-up 중 crash | Composite/baseline 한쪽만 verified state로 남지 않는다 |
| AC-ADMIN-02 | blocked cover | Actual cover fill 전 baseline을 release하지 않는다 |
| AC-ART-01 | pickle checkpoint를 ensemble에 연결 | Canonical input으로 거부한다 |
| AC-TRUST-01 | extension이 secret을 output에 기록 | Redaction 또는 hard failure가 project policy대로 발생한다 |

각 numerical component는 schema/version별 absolute/relative tolerance를 release manifest에 선언한다.
Tolerance가 없는 floating-point acceptance는 pass로 처리하지 않는다.

### 12.2 Performance envelope

Release는 reference hardware, dataset size, wall time, peak memory, parallel session 수와 artifact growth를
포함하는 benchmark manifest를 제공한다. Initial release gate는 최소 다음 fixture를 고정한다.

- Daily 500 instruments × 10 calendar years
- 세 concurrent bounded research session
- 16 GiB RAM reference machine에서 out-of-memory 없이 완료
- Catalog query와 publication latency threshold를 release manifest에 사전 고정

측정 후 threshold를 바꾸어 실패를 통과시키지 않는다. Threshold 변경은 새 release contract와 rationale을
요구한다.

## 13. Working prototype reference

`qlib-integration-codex`는 Qlib feedback timing, partial fill, checkpoint/resume, stored alpha reuse, ensemble,
enhanced index, look-through, reporting과 matched-capitalization을 검증한 reference다. Product definition,
public naming 또는 package layout은 이 PRD가 결정한다.

Prototype의 direct `Position` mutation은 Route B feasibility의 증거이지 최종 public contract가 아니다.
G4 atomic administration과 supported Qlib adapter requirement를 만족하지 않으면 그대로 제품화하지 않는다.

## 14. Future roadmap

### 14.1 AI를 사용하는 user-defined Strategy

qlibx는 AI runtime이 아니다. Provider, prompt, token/cost, tool call, retry와 rate limit은 user-owned
Strategy 또는 external runtime의 책임이다.

AI Strategy도 bounded data, typed decision, trust/permission, externally stochastic provenance, artifact
grade와 Qlib account isolation을 따른다. External AI가 child로 실행되어도 parent boundary를 확장하거나
historical evaluation으로 actual account를 바꿀 수 없다.

### 14.2 Evidence and robustness

- Evidence budget은 holdout에서 공개된 정보량과 trial count를 함께 관리한다.
- Fragility card는 availability delay, cost multiplier, parameter jitter, missingness와 universe perturbation을
  표준화한다.
- Historical stress replay는 실제 crisis/reconstitution/corporate-action window를 별도 panel로 제공한다.
- Capacity curve는 AUM, participation rate, slippage와 reserve exhaustion을 연결한다.
- Falsifiability diagnostic은 proposal의 사전 prediction과 observed outcome을 대조한다.
- Research scheduler는 expected information gain, evidence overlap, compute/storage와 human review cost를
  기준으로 proposal을 배치한다.

이 기능들은 canonical metric과 evaluation governance를 재정의하지 않고 그 위에 추가된다.

## Appendix A. Review finding traceability

| Review finding | 반영 위치 | 결정 |
|---|---|---|
| Market execution/account administration authority | §1.2, §10.3~§10.5, G4 | Core invariant로 채택 |
| Signal→physical unit/NAV/financing | §3.2, §9.2 | Core invariant로 채택 |
| Revision/vintage/benchmark announcement | §3.1, §4.2, AC-TIME-01 | Core invariant로 채택 |
| Determinism과 stochastic 예외 모순 | §3.3, §6.4, G1 | 3등급으로 교체 |
| Same-branch guarantee 과장 | §1.2, §2.5, §8.5 | qlibx-owned state로 한정 |
| Evaluation governance 부재 | §5.4, §8.3 | Core catalog contract로 채택 |
| Cost model contract 부재 | §4.4 | Versioned input으로 채택 |
| Risk model 강제 여부 | §4.5, §9.2 | Risk method 선언으로 완화 채택 |
| Frozen environment/content 부족 | §3.4 | Transitive identity로 채택 |
| Qlib/qlibx compatibility | §4.6 | Support matrix/migration state로 채택 |
| Strategy output union 과도 | §6.2 | Typed authority로 채택 |
| Nested child recursion/resource | §6.3 | Initial one-level + aggregate quota |
| Ensemble temporal compatibility | §9.1 | Compatibility gate로 채택 |
| Portable artifact/serializer 긴장 | §11.2 | 4개 artifact grade로 채택 |
| Local extension trust/secret | §2.4, §11.1 | Trusted-code boundary로 채택 |
| Acceptance가 checklist에 머묾 | §12 | Dependency gate와 fixture로 교체 |
| Canonical metric semantics | §7.4 | Metric artifact contract로 채택 |
| Orthogonality scale semantics | §7.4, §8.4 | Metric별 raw/normalized view |
| Fixed-budget default provenance | §7.3 | Default 유지, 3 snapshot 필수 |
| Reserve opportunity cost | §10.6 | Canonical PnL과 분리 |
| Catalog lifecycle 혼합 | §8.2 | 3개 state machine으로 분리 |
| Failure/partial/degraded 혼용 | §3.5 | 공통 taxonomy로 채택 |
| Retention/GC/export/import | §8.6 | Metadata/payload 분리 채택 |
| Enhanced-index/compatibility route 관계 | §1.3, §10.1 | Route A/B로 명시 |
| Capacity/scalability | §9.4, §14.2 | Optional diagnostic/후속 release |
| Falsifiability | §5.4, §14.2 | Promotion proposal에서 지원, 자동화는 후속 |
| Regime/stress replay | §9.4, §14.2 | 후속 built-in |
| Evidence budget/fragility/scheduler | §14.2 | Evaluation core 위 후속 capability |
