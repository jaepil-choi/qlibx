# qlibx Product Requirements Document

Status: canonical
Runtime: qlibx-owned event-driven engine (no Qlib runtime dependency)
Planned rename: `qlibx` → `vqar` (확정, 실행 보류 — architecture O12)
Companion document: `docs/qlibx-architecture.md`

이 문서는 qlibx의 제품 철학, observable behavior, correctness boundary와 acceptance criteria를 규정하는
정본이다.

## 0. Runtime ownership

이 절은 normative이며 본문의 다른 모든 절보다 우선한다.

### 0.1 qlibx는 자체 execution engine을 소유한다

qlibx는 Qlib을 backtest runtime backend로 사용하지 않는다. Strategy callback, decision, order,
fill, position, account와 clock progression을 포함한 execution lifecycle 전체를 qlibx가 소유하고
구현한다. `pyqlib`는 qlibx의 dependency가 아니며 runtime, test 또는 build 어느 경로에서도 요구하지
않는다.

Engine은 **event-driven** 구조다. 시간 진행은 registered timer가 만드는 event를 하나의 정렬된
queue로 병합해 처리하며, observation, decision, execution과 monitoring은 각각 독립적으로
등록된 event이고 하나의 strategy loop에 합쳐지지 않는다. Event handler는 자신에게 허용된
information cutoff만 담은 bounded context를 인자로 받는다.

### 0.2 Reference implementation 차용 정책

Engine은 백지에서 설계하지 않고 다음 reference에서 검증된 부분을 선별 차용한다.

- **Qlib** (MIT) — order fill 산술, transaction cost, lot/trade-unit rounding, tradability와
  suspension 판정, position/account accounting. 코드 차용 가능.
- **vnpy** (MIT) — daily cross-sectional portfolio backtest 골격, target/actual position 분리,
  trading/holding PnL 분해, signal transform built-in, artifact lab 표면. 코드 차용 가능.
- **nautilus_trader** (LGPL-3.0) — clock/event queue, pre-execution risk validation, execution
  reconciliation, portable catalog, portfolio-statistic plugin 구조. **설계만 차용하며 코드를
  복사하지 않는다.**

차용한 산술과 구조는 qlibx의 failure contract, diagnostic 보존과 artifact 요구사항을 만족하도록
재작성한다. Reference의 silent fallback, 자동 renormalization과 진단 소실 동작은 차용 대상이
아니다.

### 0.3 본문 해석 규칙

본문에는 Qlib을 runtime backend로 전제하던 시기의 서술이 남아 있다. 다음과 같이 읽는다.

- Qlib runtime component(`Executor`, `Exchange`, `Position`, `Account`, `TradeDecision`,
  `BaseStrategy`, `NestedExecutor`, `SimulatorExecutor`)에 대한 서술은 **qlibx가 소유하는
  동일 역할의 component**에 대한 요구사항으로 읽는다. 요구되는 semantics, authority와 evidence는
  그대로 유효하다.
- Qlib version pinning, upstream compatibility, upgrade gate와 native-vs-adapted 분류를
  요구하는 서술은 더 이상 적용되지 않는다. 해당 자리에는 qlibx engine 자체의 characterization
  test와 artifact compatibility gate가 들어간다.
- Qlib의 long-only stock position 제약에서 파생되었던 matched capitalization 요구사항은 §7.12
  instrument capability declaration으로 대체되었다.
- `qrun`, Qlib Recorder와 Qlib config factory에 대한 서술은 optional interoperability이며
  required capability가 아니다.

이 해석 규칙과 충돌하는 본문 서술은 §0이 우선한다. 본문 정리는 별도 revision에서 수행한다.

### Document interpretation

본문의 제품 요구사항은 qlibx가 제공해야 하는 observable behavior, semantic responsibility, stored result와
correctness boundary를 규정한다. 특정 class hierarchy, object count, process boundary, registry, file layout와
Python public name은 명시적으로 확정하지 않는 한 요구사항이 아니다.

> **Architecture/implementation candidate — non-normative**
>
> 이 표기가 붙은 이름, diagram, method shape와 component decomposition은 요구사항을 설명하는 하나의 구현
> 후보다. 동일한 product semantics, evidence와 acceptance criteria를 만족하는 다른 구조를 허용한다.
> `Strategy`, `TradeDecision`, `Executor`, `Exchange`, `Position`, `Account`처럼 역할이 확립된 명칭은
> 설명 목적으로 계속 사용하지만, 이는 qlibx-owned component를 가리키며 외부 package의 class를
> 지시하지 않는다.

## 1. Product thesis

### 1.1 제품 정의

`qlibx`는 Qlib을 학습과 backtest 실행 기반으로 사용하는 **재사용 가능한 alpha research framework**다.
Quantitative researcher와 그 연구를 지원하는 coding agent가 다음 작업을 하나의 누적 가능한 연구 환경에서
수행하도록 돕는다.

- Project data를 의미와 point-in-time availability가 명시된 logical dataset으로 등록한다.
- Model이 재사용 가능한 signal 또는 feature를 만들고 local storage에 축적한다.
- Alpha policy가 저장된 signal과 다른 데이터를 읽어 signed portfolio weight를 만든다.
- 저장된 여러 alpha weight를 원래 producer를 다시 실행하지 않고 ensemble한다.
- Signed active intent를 실제 운용 가능한 physical portfolio로 변환한다.
- Proposed physical target 또는 order를 declared constraint에 맞게 best-effort로 조정하고, 별도 validation으로
  실행 가능 여부를 판정한다.
- Qlib의 Strategy, order, fill, Position과 Account lifecycle에서 backtest한다.
- Strategy decision과 독립적인 monitoring clock에서 actual account의 constraint 상태를 관찰한다.
- Production에서는 broker-neutral decision artifact를 외부 OMS에 전달하고 실제 결과만 authoritative state로
  받아들인다.
- 성공과 실패, input dependency와 intermediate result를 다음 연구의 출발점으로 보존한다.

이 capability는 독립적으로 사용할 수 있다. 모든 연구가 하나의 end-to-end pipeline을 끝까지 따라야 한다고
강제하지 않는다.

### 1.2 주요 사용자와 product promise

주요 사용자는 quantitative researcher와 research engineer이며, coding agent는 이들의 작업을 지원하는
first-class user다.

사용자는 Qlib internal class hierarchy나 qlibx private source를 모두 알 필요가 없어야 한다. 대신 데이터의
경제적 의미, availability, universe, benchmark, alpha hypothesis, risk constraint, execution policy와 production
authority처럼 결과의 의미를 바꾸는 결정은 명시적으로 내려야 한다.

설치와 project initialization 뒤 사용자는 다음과 같은 목표를 직접 표현할 수 있어야 한다.

```text
data/의 데이터를 등록해줘.
등록된 signal로 새로운 reversal alpha를 연구해줘.
저장된 alpha들을 ensemble해서 long-only enhanced index로 backtest해줘.
이번 결과가 어떤 data와 signal에 의존하는지 보여줘.
```

정상적인 사용을 위해 agent가 package source나 `site-packages` private module을 열어야 한다면 public product
surface의 결함으로 취급한다.

## 2. Product philosophy

### 2.1 Signed alpha가 중심 연구 자산이다

qlibx의 첫 번째 목적은 **signed cross-sectional alpha research**다. Signal이 양수와 음수를 갖고 alpha
weight가 long과 short intent를 표현하는 것은 정상적인 research behavior다. 실제 borrow 가능성이나 Qlib
stock Position의 long-only 제약 때문에 research intent를 미리 long-only로 축소하지 않는다.

기본 연구 시나리오는 다음과 같다.

```text
reusable signal research
-> signed alpha weights
-> stored-alpha ensemble and ticker-level netting
-> benchmark-relative active intent
-> investable long-only physical portfolio
-> Qlib closed-loop backtest
```

1. **Signal research.** Model 또는 deterministic transform이 price, fundamental, text, event와 다른 data에서
   재사용 가능한 signal을 만든다.
2. **Alpha research.** Alpha policy가 signal과 필요한 context를 조합해 ticker-level signed weights를 만든다.
3. **Ensemble.** 여러 alpha weights를 저장된 상태로 결합하고 같은 ticker의 반대 intent를 netting하며 member
   contribution과 crossing을 관측한다.
4. **Physical construction.** Signed active intent를 benchmark-relative underweight/overweight와 constraint로
   해석해 실제 보유 가능한 stock, ETF와 cash target으로 변환한다.
5. **Execution.** Physical target을 Qlib order/fill/account lifecycle에 넣고 intended result와 realized result를
   함께 관측한다.

실제 운용 portfolio가 long-only여도 original signed alpha를 덮어쓰지 않는다. 실현되지 않은 short intent,
constraint clipping, residual과 physical mapping은 별도 evidence로 남긴다.

단순 long-only strategy와 market-timing policy도 구성할 수 있다. 다만 기본 research form은 decision time마다
universe 안의 instrument를 비교하는 cross-sectional stock-picking rebalance다.

### 2.2 Signal 생산과 alpha 의사결정을 분리한다

Signal을 생성하는 책임과 signal을 portfolio weights로 해석하는 책임은 분리되어야 한다. Signal 생성 결과는
특정 alpha나 portfolio에 종속되지 않은 reusable research result로 저장할 수 있어야 한다.

하나 이상의 stored signal과 다른 point-in-time data를 조합해 signed alpha weights를 만들 수 있어야 한다.
여러 alpha weights는 원래 producer를 다시 실행하지 않고 결합할 수 있어야 하며, signed weights를 executable
physical target으로 변환하는 과정은 별도로 관측할 수 있어야 한다.

이들은 semantic responsibility와 stored-result boundary다. 반드시 별도 class, process 또는 service여야 한다는
요구사항은 아니다. 필요한 것은 같은 signal을 여러 alpha가 재사용하고, 같은 alpha weights를 여러 ensemble과
portfolio construction profile이 재사용하며, 각 단계의 성능과 dependency를 독립적으로 평가할 수 있다는
것이다.

> **Architecture/implementation candidate — non-normative**
>
> 한 가지 구현 후보는 signal 생성, alpha-weight 결정, ensemble과 physical construction을 별도 component로
> 구성하는 것이다. 설명용 이름으로 `SignalProducer`, `AlphaPolicy`, `EnsemblePolicy`,
> `PortfolioConstructor`를 사용할 수 있지만 이 이름이나 class boundary는 public API 요구사항이 아니다.

### 2.3 연구와 실행을 분리하되 lineage로 연결한다

Research intent와 executable portfolio는 다른 객체다. Research가 반드시 order로 변환될 필요는 없지만,
execution을 선택하면 original intent부터 actual fill까지 하나의 lineage로 연결되어야 한다.

```text
stored signed alpha weights
    ├─ analysis / comparison / ensemble / export
    └─ physical portfolio construction
          -> executable physical target
          -> target-to-order conversion
          -> Qlib execution
          -> actual Position and feedback
```

Weight까지만 materialize하는 run은 완전한 research run일 수 있다. 반대로 execution profile에서는 weight가
중간 artifact이고 Qlib runtime Strategy의 최종 출력은 `TradeDecision`이다.

### 2.4 Qlib은 closed-loop runtime kernel이다

Qlib은 strategy가 decision time의 관측 가능한 상태를 보고 order를 제출하며, fill 이후 실제 Position과
Account를 다음 decision에서 다시 보는 closed-loop lifecycle을 제공한다. qlibx는 이를 대체하는 두 번째 bar
engine을 만들지 않는다.

Closed loop은 단순한 signal evaluation과 다르다.

- Partial fill 뒤 requested target이 아니라 actual holding을 본다.
- Stop-loss policy는 realized price와 position history를 사용할 수 있다.
- Rebalance state, cooldown, risk regime와 fitted belief를 bounded memory로 이어갈 수 있다.
- Blocked order와 transaction cost가 다음 decision에 영향을 줄 수 있다.

Qlib native execution에 연결되는 qlibx runtime integration은 Qlib `BaseStrategy` contract를 만족해야 한다.
이전 `execute_result`와 actual Qlib Position을 다음 decision에 허용된 bounded input으로 전달하고, 생성된
weight와 physical target을 intermediate result로 기록한 뒤 `TradeDecision`을 반환해야 한다.

따라서 **order conversion은 alpha의 downstream responsibility**지만, **execution feedback은 다음 decision
context로 돌아오는 return edge**다.

Constraint adjustment와 pre-execution validation은 이 downstream execution path에 속한다. Constraint
monitoring은 actual account를 읽는 independent observer이며, finding이 명시적으로 다음 trigger/decision input으로
채택되기 전에는 strategy feedback authority가 아니다.

> **Architecture/implementation candidate — non-normative**
>
> 한 가지 구현 후보는 Qlib `BaseStrategy`를 만족하는 adapter가 bounded decision context를 구성하고 alpha,
> portfolio와 order-generation logic을 조합하는 것이다. `QlibStrategyAdapter`와 `DecisionContext`는 이 후보를
> 설명하기 위한 이름이며 qlibx public class name을 확정하지 않는다.

### 2.5 Durable intermediate artifact가 public integration point다

Signal, alpha weight, ensemble weight, optimization problem/result, physical target, constraint
declaration/adjustment/validation, order, fill, position, monitoring finding과 analysis table은 최종 report의
부산물이 아니라 first-class result다.

Runtime 내부에서는 Qlib object와 Python object를 사용할 수 있다. 그러나 다음 경우의 public contract는
versioned portable artifact다.

- 다른 run, process 또는 agent가 결과를 재사용할 때
- Producer를 다시 실행하지 않고 downstream 작업을 할 때
- Project-local code와 built-in을 연결할 때
- 실패한 run을 감사하거나 재개할 때
- 외부 OMS나 reporter와 통신할 때

Downstream consumer는 producer가 qlibx built-in, Qlib native component, local Python module 또는 외부 process인지
몰라도 schema, semantics, compatibility와 lineage를 검사할 수 있어야 한다.

### 2.6 Package behavior는 deterministic하고 bundled agent skill이 대화를 담당한다

Package의 계산·검증 behavior는 선언된 input을 받아 선언된 output을 만드는 deterministic library behavior다.
User에게 질문하지 않고, 빠진 data를 비슷한 field로 대체하지 않으며, 경제적 의미를 추측하지 않는다.

Capability가 충족되지 않으면 package는 다음을 machine-readable하게 보고한다.

- 무엇이 부족한가
- 어떤 requirement가 실패했는가
- 가능한 resolution candidate는 무엇인가
- 어떤 user decision이 필요한가
- 안전하게 retry할 수 있는가

qlibx package distribution은 현재 package version과 일치하는 agent skill resource를 포함해야 한다. Project
onboarding은 사용자가 선택한 coding-agent environment에서 이 skill을 사용할 수 있게 해야 한다. Bundled
skill은 structured gap을 user에게 설명하고, 필요한 질문을 하고, user-confirmed registration/config 또는
project-local extension을 작성한 뒤 같은 public capability를 다시 실행하는 reference conversational
workflow다.

Bundled skill은 다음을 담당한다.

- Public status, capability inventory, schema, example와 error를 조회한다.
- Requirement gap과 가능한 복수의 resolution 경로를 설명한다.
- 경제적 의미가 필요한 선택은 user에게 확인한다.
- User-confirmed project config 또는 local extension을 작성하고 validation한다.
- 같은 public operation을 retry하고 result, limitation과 changed files를 요약한다.

Package의 deterministic behavior가 agent skill을 호출하거나 대화 상태를 소유하지 않는다. Skill도 package
validation을 우회하거나 missing semantics를 추측하지 않는다.

```text
deterministic package behavior
  requirement declaration -> validation -> structured gap/result

package-provided agent skill
  explanation -> user interview -> project change -> validation and retry
```

> **Architecture/implementation candidate — non-normative**
>
> Package가 versioned skill resource를 포함하고 onboarding이 Codex, Claude Code 등 selected target에 thin
> routing instruction을 생성할 수 있다. Copy, link, generated managed block 중 어떤 방식으로 skill을
> 노출할지는 같은 onboarding behavior를 만족하는 범위에서 implementation에서 결정한다.

### 2.7 Built-in은 일관성을, local extension은 자율성을 제공한다

자주 쓰는 signal transform, exposure analysis, portfolio diagnostics, artifact validation과 reporting은
deterministic built-in으로 제공한다. Agent마다 같은 helper를 다르게 다시 만드는 일을 줄이고 공통 vocabulary를
제공하기 위해서다.

사용자 고유의 signal model과 alpha logic은 project가 소유한다. 사용자는 installed qlibx, Qlib 또는
`site-packages`를 수정하지 않고 compatible한 local Python implementation을 작성·등록할 수 있어야 한다.

qlibx는 각 extension point에 대해 다음을 제공한다.

- Public input/output contract
- Machine-readable requirement와 schema
- Minimal working template와 sample
- Validation command
- Stage-specific error와 bounded offending example

qlibx가 reference/sample component를 제공할 수는 있지만 project-owned proprietary alpha를 package built-in에
가두지 않는다.

### 2.8 연구는 누적되어야 한다

성공한 trial만 남기면 같은 실패와 중복 hypothesis를 반복한다. qlibx는 성공, 실패, unsupported result,
diagnostic과 user decision을 catalog에 남겨 다음 연구의 출발점으로 사용한다.

새 연구는 가능한 경우 다음을 먼저 확인한다.

- 유사한 signal, transform과 alpha hypothesis가 이미 있는가
- 어떤 dataset과 operation이 사용되었는가
- 기존 alpha와 correlation, overlap 또는 incremental contribution은 어떠한가
- 실패 이유와 미충족 capability는 무엇이었는가
- 결과를 재실행하지 않고 재사용할 수 있는가

## 3. Canonical research semantics

### 3.1 전체 흐름

```text
project-owned source data
-> logical dataset and PIT materialization
-> reusable signal or derived research data
-> signed alpha weights
-> combined alpha weights
-> executable physical target
-> best-effort constraint adjustment
-> target-to-order conversion
-> pre-execution constraint validation
-> Qlib TradeDecision / Executor / Exchange / Account
-> actual fill, Position and feedback
-> independent actual-account constraint monitoring
-> portable analysis, report and next-decision context
```

각 화살표는 강제된 monolithic pipeline이 아니라 documented compatibility edge다. Artifact가 이미 존재하고
identity와 compatibility가 맞으면 upstream producer를 다시 실행하지 않는다.

### 3.2 Semantic roles and result categories

#### Materialized research data

반복 사용을 위해 저장한 derived research data다. Signal, label, factor return, factor exposure, covariance와
rolling risk estimate는 서로 다른 semantic category이며 각자 axis, unit, time semantics와 compatibility를
선언한다.

#### Stored signal

Feature, prediction, score 또는 factor value와 같은 reusable instrument/time information surface다. 최소한
signal semantics, axis, unit, direction, availability, coverage, producer와 input lineage를 포함한다. Factor
return처럼 axis와 경제적 의미가 다른 derived data를 signal로 가장하지 않는다. Signal은 portfolio weight를
의미하지 않는다.

#### Signed alpha-weight result

하나 이상의 stored signal 또는 compatible materialized research data와 bounded input을 소비해 만든 portfolio
intent다. Decision time별 instrument signed weight와 budget semantics를 포함하며 weight가 raw, active,
benchmark-relative 또는 physical인지 명시해야 한다.

Actual holding이나 prior execution feedback에 의존해 생성된 weight는 path-dependent다. 이러한 result는 run
identity, prior Position, feedback cursor와 execution profile을 기록하고 다른 경로에서 보편적인 weight처럼
재사용하지 않는다.

#### Ensemble result

여러 stored alpha-weight results를 member lineage와 함께 소비해 만든 combined signed weights다. Member
weighting, netting, crossing, residual과 normalization을 명시한다.

#### Executable physical target

Signed alpha weights, benchmark, current physical holdings, cost, turnover, exposure와 investability constraint를
반영한 실제 instrument/cash target이다.

#### Constraint declaration

Project가 소유하는 versioned limit contract다. Named metric과 bound, 적용 scope, warning/error policy,
evaluation clock, required compliance data, availability rule과 opaque project metadata를 포함한다.

#### Constraint-adjustment result

Proposed target 또는 order를 actual pre-trade state와 declared constraint에 맞게 best-effort로 조정한
결과다. Original/adjusted intent, hypothetical post-trade state, constraint별 before/after value, adjustment
method/status와 unresolved residual을 보존한다. Result가 존재한다는 사실은 compliance를 보증하지 않는다.

#### Requested orders and conversion evidence

Physical target, actual holding, cash, price, lot와 tradability를 사용해 만든 requested orders와 instrument별
conversion, rounding, clipping, skip/failure reason이다.

#### Pre-execution validation finding

최종 제출 후보 target/order를 독립적으로 평가한 결과다. Constraint별 measured value, bound, excess,
warning/error severity, execution eligibility, required override와 exact input lineage를 포함한다.

#### Actual-account monitoring finding

Confirmed fill 이후 actual Position, cash와 account snapshot을 monitoring time에 평가한 결과다. Constraint별
breach, severity, passive/execution-induced classification, missing/unknown state와 data/account lineage를
포함한다. Monitoring finding은 account를 소급해 변경하지 않는다.

#### Bounded decision input

다음 decision에 허용된 input이다.

- Decision time과 permitted information cutoff
- Bounded observations와 stored signal references
- Universe, benchmark와 tradability view
- Actual realized Position, cash와 prior execution feedback
- Bounded strategy memory와 prior artifact references
- Trigger, finalization과 run state

#### Prepared production decision

Production에서 external OMS에 전달하는 immutable broker-neutral decision artifact다. 생성만으로 authoritative
strategy state를 advance하지 않는다.

> **Architecture/implementation candidate — non-normative**
>
> Python 구현과 portable schema에서 위 역할을 구분하기 위한 후보 이름으로 `ResearchDataArtifact`,
> `SignalArtifact`, `AlphaWeightArtifact`, `PhysicalTargetArtifact`, `DecisionContext`와 `PreparedDecision`을
> 사용할 수 있다. 이 이름은 class, inheritance 또는 public import path를 확정하지 않는다.

### 3.3 Alpha output과 Qlib Strategy output의 구분

Alpha research의 observable output은 signed weights다. Qlib native execution에 참여하는 runtime integration의
observable output은 Qlib-compatible `TradeDecision`이다. 두 요구사항은 동시에 성립하며, alpha 연구 결과를
weight로 재사용하는 것과 Qlib feedback loop에서 orders를 출력하는 것은 충돌하지 않는다.

> **Architecture/implementation candidate — non-normative**
>
> 한 가지 구현 후보는 weight-producing callable과 Qlib `BaseStrategy` adapter를 분리하는 것이다. 설명용
> method shape는 `alpha_decision(context) -> signed weights`와
> `generate_trade_decision(execute_result) -> TradeDecision`일 수 있다.

### 3.4 System mental model

Qlib이 이미 제공하고 qlibx semantics와 일치하는 계산·학습·execution lifecycle은 다시 만들지 않는다.
그러나 native component라는 이유만으로 Qlib default를 qlibx public contract로 노출하지 않는다.

qlibx는 Qlib runtime 앞에서 data meaning, availability, requirements, config와 policy를 확정하고, runtime
뒤에서 portable evidence, dependency lineage, reconciliation, analysis와 reporting을 제공해야 한다. 이
responsibility ordering은 필요하지만 내부 plane, service 또는 package layout을 규정하지 않는다.

> **Architecture/implementation candidate — non-normative**
>
> ```text
> qlibx control plane
>   data meaning / availability / requirements / config / provenance / constraint policy
>              |
>              v
> compatibility and runtime adapters
>              |
>              v
> Qlib runtime kernel
>   Handler / Dataset / Model / Strategy / TradeDecision / Executor / Exchange / Account
>              |
>              v
> qlibx evidence plane
>   portable results / validation findings / monitoring / dependency graph / catalog / reports
> ```

## 4. Product invariants

### 4.1 Native-first, contract-first

- Qlib native component가 qlibx requirement와 semantics를 충족하면 validated integration boundary 안에서
  재사용한다.
- 의미, failure behavior, state authority 또는 artifact portability가 다르면 qlibx가 경계를 소유한다.
- Native reuse는 version-pinned characterization test로 증명한다.
- Qlib upgrade가 qlibx public semantics를 암묵적으로 바꾸어서는 안 된다.
- Qlib lifecycle을 호출하는 두 번째 수동 execution engine을 canonical path로 유지하지 않는다.

### 4.2 Long-short research와 executable short를 구분한다

다음은 서로 다른 capability다.

1. Signal/prediction/label의 IC, RankIC, quantile spread와 long-short diagnostic
2. Signed basket return과 factor-return analysis
3. Orders, Position, Account와 actual fill을 통과하는 executable short portfolio

앞의 두 층은 signed alpha research에 사용할 수 있으며 account를 경유하지 않으므로 instrument의 short
capability와 무관하게 성립한다.

세 번째 층은 instrument가 선언한 position direction constraint(§7.12)에 따른다. `hypothetical_short`
instrument의 음수 position은 research 관측을 위한 것이며 borrow, 담보, 차입 비용과 locate 가능성을
모델링하지 않는다. 이를 executable short로 표시하지 않는다.

### 4.3 Actual state가 authority다

- Requested target은 intention이며 realized holding이 아니다.
- Constraint adjustment와 pre-execution validation은 proposed 또는 hypothetical post-trade state를 평가한다.
- Backtest의 다음 decision은 Qlib actual Position과 dealt quantity를 본다.
- Production의 다음 decision은 external OMS의 confirmed fill과 account snapshot을 본다.
- Constraint monitoring은 actual account snapshot만 authoritative compliance state로 평가한다.
- Partial, rejected, blocked, zero-fill과 expired execution은 canonical result다.
- Intended ledger나 prior target을 actual state처럼 사용하지 않는다.
- Monitoring finding은 prior fill을 rollback하거나 account를 소급 변경하지 않는다.

### 4.4 Point-in-time과 data meaning을 강제한다

모든 data consumer는 선언된 `available_at <= evaluation_time`인 observation만 사용한다. Strategy와 alpha의
evaluation time은 decision time이고, constraint adjustment/validation은 해당 pre-execution cutoff,
monitoring은 monitoring time이다. Actual account snapshot의 `as_of`도 evaluation time보다 늦을 수 없다.
qlibx가 보장하는 것은 선언된 availability의 준수이며, source의 경제적 공시 시점이 사실이라는 보장은
user 책임이다.

Strategy, child research, model inference와 inner execution component가 permitted cutoff를 우회해 source를
직접 읽어서는 안 된다.

Compliance evaluator는 strategy가 소비하지 않는 independent registered data를 요구할 수 있다. 그러나 그
data나 monitoring finding을 alpha/strategy input으로 자동 전달하지 않는다. 이후 trigger 또는 decision이 이를
사용하면 explicit dependency, availability cutoff와 lineage를 가져야 한다.

### 4.5 Evidence는 portable하고 producer-independent하다

Qlib pickle, MLflow run과 process memory는 유용한 runtime representation일 수 있지만 유일한 public result가
아니다. Standard artifact는 Qlib process와 producer implementation 없이 schema와 lineage를 읽을 수 있어야
한다.

### 4.6 명시적 실패가 silent fallback보다 우선한다

다음은 같은 success type으로 숨기지 않는다.

- Tradable instrument만 남기고 target weight를 자동 재정규화
- Untradable target을 reason 없이 skip
- Solver constraint를 제거하거나 current portfolio를 target처럼 반환
- Missing analysis dependency를 warning만 남기고 required output을 생략
- Unknown field, instrument 또는 exposure axis를 임의로 제외
- Failed artifact publication을 complete로 표시

Constraint adjustment의 unresolved residual, validator warning/error, actual-account breach와 evaluator runtime
failure는 다른 result/status다. Adjustment result가 존재한다는 이유로 compliant success를 선언하지 않고,
actual breach를 계산 failure로 숨기지도 않는다.

### 4.7 Config는 의미를 선언하지만 의미를 대신하지 않는다

Config-driven workflow는 reproducibility를 위한 수단이다. 비슷한 field name, class path 또는 default 값이
경제적 의미를 확정하지 않는다. User-confirmed binding과 validated contract만 frozen config에 들어간다.

## 5. Product boundaries

### 5.1 qlibx가 소유하는 것

- Project initialization, config resolution과 frozen invocation
- Logical dataset registration, schema와 capability binding
- Field semantics, unit, currency, timezone, universe와 tradability distinction
- Point-in-time materialization과 bounded access
- Signal, alpha weight, ensemble, physical target와 artifact contracts
- Alpha/portfolio components와 Qlib runtime 사이의 compatibility adapters
- Order conversion semantics와 clipping/failure diagnostics
- Constraint declaration, best-effort adjustment, pre-execution validation과 finding contracts
- Signed alpha diagnostics와 long-only physical construction
- ETF/index look-through와 cash residual
- Instrument capability declaration과 그 강제
- Portable artifact envelope, dependency lineage, file-backed catalog와 reporting
- Trigger, finalization, checkpoint와 resume policy
- Production decision artifact, reconciliation, commit protocol과 monitoring analysis
- Dense actual-account constraint monitoring과 historical re-evaluation
- Agent-readable documentation, capability gap과 stage-based errors

### 5.2 Qlib에 맡기는 것

호환성 검증을 통과한 profile에서는 다음 runtime responsibility를 Qlib에 맡긴다.

- Expression, Handler, Dataset와 Processor lifecycle
- Model fit, predict와 Qlib-supported workflow records
- Strategy callback과 execution feedback
- `TradeDecision`과 empty-order hold
- Trading calendar progression과 trade range
- `SimulatorExecutor`와 필요한 multi-level execution
- Exchange order handling, requested/dealt quantity와 transaction cost
- Position, cash와 Account mutation
- Bar-end mark-to-market과 enabled portfolio metrics
- Semantics parity가 확인된 native analysis

### 5.3 User project가 소유하는 것

- Source data와 경제적 의미
- Availability, delivery lag와 restatement assumptions
- Universe, benchmark, sector와 factor definitions
- Signal model과 alpha policy code
- Risk, cost, constraint와 execution policy
- Constraint metric의 경제적 의미, bound, severity, override와 remediation policy
- Compliance reference data의 availability와 applicability assumptions
- Project-local extensions와 report composition
- Research objective, evaluation policy와 promotion decision
- External OMS configuration과 operational approval

### 5.4 External production runtime과 OMS가 소유하는 것

- Broker connectivity, authentication과 secret
- Broker-specific identifier와 order type
- Order slicing, pacing, venue, retry, replace와 cancel
- Always-on scheduling, account polling과 real-time alert
- Market-session operational control, human approval와 kill switch
- Validation override approval, alert delivery와 operational remediation
- Confirmed order, fill, reject reason과 account snapshot publication

qlibx는 broker SDK wrapper나 always-on OMS가 아니다.

### 5.5 사용하지 않는 Qlib subsystem

Qlib `TaskManager`는 MongoDB와 pickle-oriented task state를 요구하므로 기본 project catalog나 parallel research
coordinator로 사용하지 않는다. Qlib Recorder는 runtime sink로 사용할 수 있지만 portable qlibx catalog를
대체하지 않는다.

### 5.6 금지 behavior

- Qlib fork를 기본 해결책으로 사용
- Negative Qlib stock Position을 native short라고 주장
- Requested target을 realized holding으로 취급
- Qlib global provider를 concurrent run 사이에서 무보호 mutation
- Current target을 반복 제출해 hold를 흉내 내고 price-drift rebalance 생성
- 한 decision의 order diagnostics를 마지막 한 건만 보존
- Composite account return을 signed active strategy return으로 사용
- Constraint adjustment result를 independent validation 없이 compliant로 표시
- Requested/hypothetical state를 actual compliance monitoring state로 사용
- Compliance-only data를 undeclared strategy input으로 전달
- Pickle-only result를 portable public artifact라고 주장
- Production `prepare`가 confirmed result 없이 authoritative memory를 advance

### 5.7 현재 지원 범위

현재 product scope는 주식과 ETF다.

- Cross-sectional signed signal과 alpha research
- ML training and inference (model implementation은 project 소유, §5.3)
- Stored signal/alpha reuse와 ensemble
- Long-only enhanced-index physical portfolio
- `hypothetical_short` instrument를 사용하는 signed research (§7.12)
- ETF opaque execution과 PIT constituent data가 있을 때의 look-through
- Historical backtest와 portable research catalog
- Selective decision trigger, explicit hold와 dense actual-account evidence
- Best-effort constraint adjustment, pre-execution validation과 independent monitoring artifacts
- Local-storage-based production decision/OMS boundary

Instrument capability declaration(§7.12)은 이 범위 안에서 확장 가능한 형태로 설계한다. 다만 다음은
현재 범위 밖이며 별도 product decision으로 다룬다.

- `real_short`에 필요한 borrow 가능성, 담보와 차입 비용 모델
- Margin account, leverage와 강제청산
- Perpetual/futures의 funding, 계약 단위와 expiry
- Direct broker execution ownership

## 6. User, agent and config-driven workflow

### 6.1 Initial setup

사용자는 package를 설치한 뒤 project root에서 qlibx project를 초기화한다. Initial setup은 다음을 만든다.

- Project-owned config와 schema version
- Data, artifact, catalog와 extension locations
- Version-matched bundled agent skill을 selected coding-agent target에서 사용할 수 있게 하는 onboarding result
- Installed documentation과 capability inventory
- Qlib compatibility/version information

설치 후 정상 사용에 qlibx source checkout이나 Qlib internal 탐색을 요구하지 않는다. Sample data와 sample
components는 명시적으로 요청할 때만 project에 materialize한다.

#### Safe and idempotent onboarding

Onboarding은 project file을 소유한다고 가정하지 않는다. 실행 전에 target agent, 생성·수정할 exact path,
instruction file의 managed block, skill resource version과 validation command를 preview하는 dry-run을 제공해야
한다. 실제 적용은 다음을 만족한다.

- 기존 `AGENTS.md`, `CLAUDE.md`와 같은 instruction file을 발견하고 qlibx가 소유하는 marked block만
  추가·갱신·제거한다.
- Supported instruction file이 없으면 creation target을 preview하고 user가 creation을 요청한 경우에만 새로
  만든다.
- 같은 target과 version으로 반복 실행해도 duplicate block, duplicate skill 또는 의미 없는 diff를 만들지
  않는다.
- 여러 agent target을 선택한 경우 각 target의 변경을 독립적으로 보여주고 검증한다.
- qlibx가 생성한 skill file이 user에 의해 수정되었으면 content fingerprint 차이를 감지하고 명시적 확인 없이
  덮어쓰지 않는다.
- Update는 qlibx-owned file/block만 갱신하고 같은 skill directory의 user-owned extension file을 보존한다.
- Remove는 qlibx-owned block과 확인된 generated file만 제거하며 instruction file의 나머지 내용이나 project
  artifact를 삭제하지 않는다.
- 생성 결과에 qlibx package version, skill schema/version과 target type을 기록하고 target별 skill structure를
  validation한다.

#### Mandatory agent-skill output protocol

다음 entrypoint path는 selected target이 skill을 발견하기 위해 사용하는 **normative product contract**다.
일반적인 project directory convention이나 architecture candidate가 아니다.

- Codex target: skill directory `.agents/skills/qlibx/`, required entrypoint
  `.agents/skills/qlibx/SKILL.md`
- Claude Code target: skill directory `.claude/skills/qlibx-skill/`, required entrypoint
  `.claude/skills/qlibx-skill/SKILL.md`
- Explicit custom target root: skill directory `<user-selected-output>/qlibx/`, required entrypoint
  `<user-selected-output>/qlibx/SKILL.md`

> **예정된 변경 — 아직 적용되지 않았다.** Package 이름을 `qlibx`에서 `vqar`(vibe quant alpha research)로
> 변경하기로 확정했으나 실행은 최종 단계로 미룬다. 적용 시 위 세 path의 `qlibx` 부분이 함께 바뀌며,
> 이 절과 §13.8, §15 P0가 동시에 갱신되어야 한다. 그 전까지 위 path가 유효한 normative contract다.

Custom target root는 user가 명시적으로 선택해야 하며 package가 임의의 output location을 추측하지 않는다.
각 skill directory 안의 `references/`, `scripts/`, `examples/` 같은 보조 resource는 해당 target protocol과
generated manifest가 허용하는 범위에서 둘 수 있다. Onboarding은 target instruction file에 product facts를
복사하지 않고 이 exact version-matched skill entrypoint로 routing한다.

#### Optional sample end-to-end journey

Fresh user가 전체 mental model을 확인할 수 있도록 package는 명시적으로 materialize할 수 있는 작은 sample
data, sample project-local signal logic, alpha-weight logic, config와 expected result를 제공해야 한다. Sample은
다음을 한 번에 보여준다.

```text
sample data registration
-> PIT-safe materialization
-> stored signal
-> signed alpha weights
-> optional ensemble and physical target
-> Qlib closed-loop backtest
-> portable artifacts, report and catalog lookup
```

Sample은 reference journey이지 hidden built-in alpha나 mandatory starter layout이 아니다. User가 요청하지 않은
project에 자동 생성하지 않으며, 생성된 sample file은 product-owned example과 user-owned research code를
구분해야 한다. 각 단계는 public command/schema만으로 실행·검사할 수 있어야 한다.

### 6.2 Data registration journey

User 또는 agent는 source를 먼저 opaque하게 inventory한 뒤 capability requirement에 맞는 의미를 binding한다.

```text
source inventory
-> bounded sample
-> candidate semantic mapping
-> user confirmation
-> validation
-> canonical materialization
-> immutable registration result
```

Agent는 field 이름만 보고 의미를 확정하지 않는다. Candidate mapping, derivation, warning과 unresolved
limitation을 보여준 뒤 user confirmation으로 project config를 변경한다.

### 6.3 Research journey

일반적인 research request는 다음 순서로 진행한다.

1. Project status와 registered capability를 조회한다.
2. Similar prior research와 reusable artifacts를 검색한다.
3. Hypothesis, required inputs, operations와 evaluation을 bounded proposal로 기록한다.
4. Frozen invocation으로 isolated trial을 실행한다.
5. Intermediate artifacts, dependency lineage, diagnostics와 terminal status를 저장한다.
6. Result를 compare, reject, retain 또는 promote한다.
7. Complete publication 뒤 다른 session과 agent가 result를 조회·재사용한다.

User가 end-to-end execution을 요청하지 않았다면 signal 또는 alpha-weight materialization에서 정상 종료할 수
있다.

### 6.4 Stored result reuse

Identity와 compatibility가 일치하면 stored signal, model prediction, alpha weight, ensemble result와 physical
target을 producer rerun 없이 사용할 수 있다.

Reuse는 단순 path 복사가 아니다. Consumer는 다음을 검사한다.

- Artifact schema와 semantic type
- Time, axis, universe와 currency compatibility
- Input/producer-implementation fingerprint
- Path-dependency와 actual-state dependency
- Terminal status, warnings와 coverage
- Parent/member lineage

### 6.5 Bundled agent skill workflow

Package의 deterministic behavior는 capability contract를 판정하고, package-provided agent skill은 다음을
담당한다.

- Requirement gap 설명
- Candidate source, field와 derivation 비교
- User decision 수집과 project config 작성
- Project-local extension scaffold와 repair
- Validation 실행과 evidence 요약

Skill은 public error의 stage를 기준으로 version-matched guidance를 찾고, 해당 단계의 계약, 자주 발생하는
실패, 가능한 복수의 해결 경로, user confirmation이 필요한 선택과 retry할 public operation을 제시해야 한다.

Agent-specific instruction은 bundled skill과 installed documentation을 찾게 하는 thin routing layer다. Product
facts와 schemas를 agent-specific file에 복제해 stale하게 만들지 않는다. Skill이 project file을 변경할 때는
변경 대상과 validation result를 user에게 보여줘야 한다.

### 6.6 Config의 역할

Frozen run config는 최소한 다음을 완전히 resolve한다.

- Logical datasets와 exact snapshot/reference
- Field binding, derivation과 availability convention
- Universe와 benchmark
- Signal generation, transforms와 fitted state
- Alpha-weight, ensemble과 physical-construction behavior
- Constraint declarations, compliance-data bindings, adjustment와 validation policy
- Qlib-compatible Strategy integration, target-to-order behavior, Executor, Exchange와 cost profile
- Observation/decision/execution/monitoring clocks, trigger, finalization, checkpoint와 reporting
- Artifact location, schema와 provenance

환경변수, mutable global default와 실행 시점의 암묵적 file discovery는 frozen result identity 밖에 남지 않는다.

### 6.7 Qlib config factory reuse

Qlib의 `init_instance_by_config`와 class/module/kwargs 표현은 component instantiation에 재사용할 수 있다. qlibx는
그 위에 다음을 추가한다.

- Allowed extension boundary
- Capability and type validation
- Semantic input/output binding
- Version and source fingerprint
- Safe error classification
- Portable resolved config

Qlib class path가 instantiate된다는 사실은 qlibx compatibility가 증명되었다는 뜻이 아니다.

### 6.8 `qrun`의 지위

`qrun`은 다음 Qlib task workflow를 실행하는 유용한 frontend다.

```text
qlib.init
-> instantiate Model and Dataset
-> model.fit
-> save model/dataset
-> configured Record generation
```

Conventional ML experiment와 Qlib record 생성에는 사용할 수 있다. 그러나 arbitrary artifact DAG, registration
interview, catalog publication, signed accounting, physical construction 또는 production commit을 수행하는
qlibx 전체 workflow engine은 아니다.

qlibx는 resolved config를 qrun-compatible task로 materialize할 수 있지만 qrun pickle이나 MLflow run을 유일한
canonical result로 간주하지 않는다.

### 6.9 Workflow completion

각 stage는 다음 중 하나로 끝난다.

- `complete`: required outputs와 validation이 모두 존재
- `incomplete`: 일부 output은 있으나 requirement 미충족
- `failed`: deterministic contract 또는 runtime failure
- `unsupported`: 선택한 backend/profile이 capability를 제공하지 않음

Required output에 대한 warning-and-skip은 `complete`가 될 수 없다.

## 7. Project, data and capability contracts

### 7.1 Package와 project 분리

Package는 reusable engine, schemas, built-ins와 documentation을 제공한다. Project는 조직·연구별 data, config,
extensions와 artifacts를 소유한다. Package upgrade가 project data, config나 result를 자동 rewrite하지 않는다.

### 7.2 Logical dataset

Logical dataset은 physical file과 구분되는 versioned contract다. 최소 metadata는 다음과 같다.

- Stable dataset ID와 schema version
- Physical source/reference와 immutable fingerprint
- Index/axis와 key uniqueness
- Fields, dtype, unit, currency와 timezone
- Event time, observation time와 `available_at`
- Universe coverage와 missingness
- Registration query/derivation
- Validation result와 warnings

CSV, Parquet, database query 또는 API response는 source일 뿐 그 자체로 logical dataset이 아니다.

### 7.3 Capability requirement와 binding

Signal generation, alpha-weight decision, processing, physical construction, constraint adjustment/validation,
monitoring과 reporting capability는 필요한 input을 capability requirement로 선언한다.

Requirement는 최소한 다음을 포함한다.

- Stable capability ID/version
- Semantic role과 expected artifact type
- Required fields와 dtype
- Axis, frequency, lookback와 availability rule
- Unit, currency와 timezone
- Missingness와 universe completeness
- Optional derivation policy
- Bounded-load expectation

Resolver는 registered dataset과 complete artifact만 후보로 사용한다. Exact field name이 같아도 의미가 다르면
자동 binding하지 않는다. User-confirmed mapping만 project config에 기록한다.

### 7.4 Dependency binding

모든 derived artifact는 자신이 의존하는 input을 stable identity로 기록한다.

- Dataset snapshot/reference
- Upstream artifact ID와 content fingerprint
- Producer component와 code/config version
- Operation graph와 parameter
- Fitted-state identity
- Universe, benchmark와 time cutoff
- Actual-state/feedback dependency when applicable

Signed alpha-weight result가 특정 stored signal을 소비했다면 단순 signal name이 아니라 exact result identity와
column/axis binding을 기록한다. Ensemble도 각 member alpha와 selected version을 기록한다.

Dependency graph는 다음을 지원해야 한다.

- Upstream 변경 시 affected downstream result 조회
- 같은 dependency graph를 가진 duplicate research 식별
- Result 재현과 audit
- Stale artifact 감지
- Producer를 실행하지 않는 safe reuse

### 7.5 Stage-based error contract

Public operation의 failure는 안정된 machine-readable schema로 반환해야 한다. 최소 public field는 다음과 같다.

- `stage`: 실패한 product stage의 stable code
- `message`: user가 이해할 수 있는 bounded summary
- `expected`: 충족되어야 했던 requirement, schema 또는 artifact contract
- `context`: failing requirement/artifact identity, bounded offending values와 필요한 public provenance
- `requires_user_confirmation`: 경제적 의미나 project 변경을 위해 user decision이 필요한지
- `retryable`: 같은 operation을 안전하게 retry할 수 있는지와 retry prerequisite
- `error_id`: log와 catalog evidence를 연결하는 stable occurrence ID

Project-local user code에서 exception이 발생하면 safe한 범위의 original exception type/message를 `context`에
포함한다. Public error에 secret, credential, 전체 source row, unrestricted traceback, private package path 또는
unbounded data sample을 노출하지 않는다.

Public error와 internal diagnostic은 별도 contract다. Public error schema는 agent와 user가 versioned하게
소비하며, internal diagnostic은 debugging을 위한 상세 stack, backend payload와 environment data를 보관할 수
있지만 public recovery logic의 유일한 입력이어서는 안 된다. Internal diagnostic의 저장 위치, retention과
redaction policy를 기록하고 `error_id`로 public error와 연결한다.

`expected`는 실패한 deterministic contract를 설명한다. Package가 source correction, derivation adoption,
universe 축소 또는 parameter 변경 중 하나를 정답으로 결정하지 않는다. Safe recovery guidance는 installed
documentation과 version-matched skill이 `stage`, `expected`와 capability inventory를 사용해 bounded하게
조회한다.

표준 stage는 다음을 포함한다.

- `ONBOARDING`
- `PROJECT_INIT`
- `DATA_REGISTRATION`
- `CAPABILITY_BINDING`
- `UNIVERSE`
- `MATERIALIZATION`
- `MODEL_TRAIN`
- `SIGNAL_MATERIALIZATION`
- `ALPHA_RUN`
- `ENSEMBLE`
- `OPTIMIZATION`
- `CONSTRAINT_ADJUSTMENT`
- `CONSTRAINT_VALIDATION`
- `ORDER_GENERATION`
- `EXECUTION`
- `ACCOUNT_RECONCILIATION`
- `ARTIFACT_PUBLICATION`
- `RESEARCH_RECORD`
- `REPORTING`
- `COMPLIANCE_MONITORING`
- `PRODUCTION_RECONCILIATION`

Package error는 source correction, derivation adoption 또는 scope 축소 같은 경제적 결정을 대신하지 않는다.
Bundled agent skill은 stage별 복수의 resolution 경로를 설명할 수 있지만 user confirmation 없이 하나를
선택해서는 안 된다.

### 7.6 No-look-ahead

모든 observation과 reference data는 해당 consumer의 evaluation time을 기준으로 다음을 만족해야 한다.

\[
available\_at \le evaluation\_time
\]

Runtime은 parent가 허용한 cutoff보다 늦은 데이터를 child research, model inference, alpha-weight decision 또는
inner execution strategy에 전달하지 않는다. Qlib `NestedExecutor`나 financial PIT provider를 사용한다는
사실만으로 이 조건이 자동 충족된다고 가정하지 않는다.

Constraint adjustment와 pre-execution validation도 decision/submission cutoff를 넘는 data를 볼 수 없다.
Constraint monitoring은 독립적인 compliance dataset을 사용할 수 있지만 `available_at <= monitoring_time`과
`account_snapshot.as_of <= monitoring_time`을 만족해야 한다. Compliance-only input은 explicit dependency 없이
strategy state나 alpha decision으로 역류하지 않는다.

### 7.7 Universe와 tradability

Universe는 alpha가 target을 만들 수 있는 instrument set이고 tradability는 특정 execution interval에 BUY/SELL이
가능한지 나타낸다. 두 개를 합치지 않는다.

Universe dataset은:

- Boolean semantics를 명시하고 missing을 false로 조용히 cast하지 않는다.
- `(available_at, instrument)`가 유일해야 한다.
- 선언된 axis를 완전히 채워야 한다.
- Point-in-time rule을 따라야 한다.

Universe에서 제외된 realized holding은 사라지지 않는다. Liquidation이 blocked되면 actual Position에 남고
다음 decision과 reconciliation에 포함된다.

Tradability는 suspension, price limit, volume availability, session과 instrument metadata에서 결정한다.
Unknown 상태를 tradable로 추측하지 않는다.

### 7.8 Daily market materialization

기본 daily OHLCV profile은 source semantics 확인 뒤 Qlib-compatible fields를 materialize한다.

- Price convention과 corporate-action adjustment 명시
- Volume participation을 사용할 때만 volume을 execution capacity로 해석
- Lot/factor가 확인되지 않으면 임의 보정하지 않음
- Decision, execution과 valuation price convention 기록
- Source-to-Qlib mapping과 unsupported assumptions 보존

### 7.9 Provider와 process isolation

Qlib provider wrapper와 cache는 process-global state를 사용한다. 서로 다른 calendar, region, provider 또는 data
materialization을 사용하는 concurrent run은 process isolation, immutable initialization 또는 검증된 lifecycle로
상호 mutation을 막아야 한다.

Custom provider를 등록할 수 있다는 source-level 가능성과 qlibx market data로 native backtest가 끝까지
실행된다는 것은 다른 주장이다. End-to-end execution, cache invalidation과 concurrency를 검증하기 전에는
canonical profile로 채택하지 않는다.

### 7.10 Frozen invocation

실행 전에 effective config와 input identity를 immutable bundle로 동결한다. Run 도중 project config가 바뀌어도
이미 시작한 run의 의미는 바뀌지 않는다. 모든 result는 frozen invocation fingerprint를 참조한다.

### 7.11 Constraint declaration and evaluation binding

Constraint declaration은 최소한 다음을 포함한다.

- Stable constraint ID/version과 named metrics
- Metric별 min/max 또는 allowed range
- Instrument, group, portfolio 등 evaluation scope
- Warning/error policy와 override requirement
- Required compliance datasets, axis, frequency와 availability rule
- Applicability/effective-time semantics
- qlibx가 해석하지 않고 finding에 원문 보존할 수 있는 project metadata

Strategy와 compliance evaluator는 data requirement를 독립적으로 선언한다. 같은 source를 공유할 수 있지만
binding, permitted cutoff와 lineage는 별도다. Compliance-only binding은 strategy가 명시적으로 dependency를
선언하기 전까지 decision input이 아니다.

검증은 세 단계로 나눈다. Load 시 required key, type와 bound 관계를 검사하고, activation 시 metric
implementation과 data binding을 검사하며, evaluation 시 actual value, missing input와 breach를 계산한다.
사용하지 않는 metric-specific binding 때문에 unrelated workflow를 막지는 않지만 malformed declaration을
끝까지 유효한 것으로 보존하지 않는다.

Stored account history를 새 constraint로 재평가할 수 있다. 당시 적용된 constraint/version을 복원하는
`as-was` evaluation과 새 constraint를 과거 state에 적용하는 `as-if` evaluation을 별도 semantics와 lineage로
구분한다.

### 7.12 Instrument capability declaration

qlibx는 하나의 asset class에 고정되지 않는다. Instrument는 1급 개념이며, 각 instrument는 자신을 보유하고
거래하고 평가하는 데 필요한 semantics를 **capability로 선언**한다. Engine은 그 선언만 소비하며 instrument
종류를 하드코딩하지 않는다.

Instrument capability는 최소한 다음을 선언한다.

- Stable instrument ID와 declaration version
- Quantity unit과 contract/lot size
- Price convention, valuation source와 currency
- **Position direction constraint** — 허용되는 보유 방향과 그 근거
- Cost schedule과 tax/fee semantics
- Tradability rule과 settlement convention
- Corporate-action applicability
- 선언되지 않은 항목은 unknown이며 추측하지 않는다

#### Short capability

Position direction constraint는 세 값을 갖는다. 이것이 §4.2의 layer 구분을 instrument 속성으로 표현한 것이다.

- `long_only` — 음수 보유를 허용하지 않는다. Short intent는 physical construction에서 해소되어야 한다.
- `hypothetical_short` — 음수 weight와 음수 position을 research 목적으로 허용하되, 실제 borrow, 담보,
  차입 비용과 locate 가능성을 모델링하지 않는다. 이 instrument의 음수 position에 의존한 모든 result는
  **hypothetical로 표시**되며 execution profile에서는 거부된다.
- `real_short` — borrow 가능성, 담보와 비용이 선언된 데이터로 뒷받침되는 executable short.

Short capability가 선언되지 않은 instrument는 `long_only`로 취급한다. Unknown을 shortable로 추측하지
않는다(§7.7과 같은 원칙).

`hypothetical_short` result를 `real_short` result와 같은 성과로 비교하거나 promotion 근거로 사용할 수
없다. Artifact는 각 instrument의 declaration identity를 lineage에 기록한다.

#### 확장 규칙

새 asset class는 instrument ID를 추가해서 지원하지 않는다. Valuation, quantity/contract unit, settlement,
expiry, margin, corporate action, cost와 risk semantics를 capability로 정의하고, engine이 그 선언을 소비할 수
있음을 증명해야 한다.

Engine이 해석할 수 없는 capability를 선언한 instrument는 `unsupported`로 실패한다. 부분적으로 해석해
실행하지 않는다.

## 8. Signal and model research

### 8.1 Signal generation and model research requirements

Signal-generating behavior는 PIT-safe bounded data를 받아 reusable information을 만든다. 다음 구현을 허용한다.

- Qlib Model fit/predict
- Qlib expression 또는 Processor-compatible transform
- Deterministic factor formula
- Text, event, graph 또는 alternative-data model
- Project-local Python implementation

Model fit과 inference를 구분한다. Fit은 train segment만 사용하고 validation/test leakage를 막는다. Label horizon
overlap이 있는 경우 purge/embargo requirement를 선언한다. Fitted processor와 model state의 identity를 prediction
artifact에 기록한다.

### 8.2 Stored signal result

Stored signal result는 최소한 다음을 포함한다.

- Observation/decision time와 instrument axis
- Signal columns와 semantic description
- Direction convention and unit
- Raw/transformed status와 operation lineage
- Availability cutoff와 source coverage
- Universe and missingness
- Producer/model/fitted-state identity
- Input artifact dependencies
- Terminal status and warnings

Signal은 portfolio weight가 아니다. 음수 signal은 short order를 의미하지 않으며, factor return도 특정 account의
realized return을 의미하지 않는다.

### 8.3 Precomputed derived research data

반복 계산 비용이 크고 semantics가 안정적인 derived data는 versioned artifact로 미리 materialize할 수 있다.

- Model prediction과 embeddings
- Standardized/neutralized signal
- Forward return label
- Factor return과 factor exposure
- Rolling risk, beta와 covariance estimate
- Universe, benchmark와 constituent snapshot

이를 **materialized research data** 또는 **research feature store**라고 부른다. 각 결과는 자신의 semantic
category를 명시해 저장한다. 단순 cache와 달리 schema, availability, dependency, producer version과 validity를
가진다. Upstream identity가 바뀌면 같은 result로 덮어쓰지 않고 새 version을 만든다.

### 8.4 Built-in signal operations

기본 operation은 다음 범주를 지원한다.

- Cross-sectional rank, percentile와 z-score
- Winsorization/clipping와 robust scaling
- Missing/inf handling with explicit policy
- Lag, rolling statistics와 decay
- Industry/sector demeaning
- Market/benchmark beta residualization
- User-supplied factor neutralization
- Hump/barrier와 turnover control

Qlib Processor가 같은 semantics를 제공하면 재사용한다. qlibx는 operation ID/version, axis, availability cutoff,
fitted-state scope와 lineage를 붙인다. Semantics가 다르거나 기능이 없으면 qlibx built-in 또는 project extension을
사용한다.

### 8.5 Signal diagnostics

Qlib `SignalRecord`, `SigAnaRecord`와 alpha evaluation의 IC, RankIC, quantile spread는 semantics parity 후
재사용할 수 있다. Metric parity는 label convention, quantile weighting, missing-value handling, annualization과
cost 포함 여부를 검증한다.

Diagnostic long-short result를 executable short simulation으로 표시하지 않는다.

### 8.6 Adaptive model research

Rolling, expanding 또는 event-triggered retraining은 하나의 mutable model을 조용히 덮어쓰는 behavior가 아니라
명시적인 research lifecycle이어야 한다. 각 fit은 train/validation window, information cutoff, purge/embargo,
feature and label dependencies, fitted-state identity와 selection evidence를 가진 별도 result다.

Adaptive model research는 다음을 만족한다.

- 각 historical decision에서 당시 이용 가능했던 data만으로 fit/select/infer한다.
- Retraining schedule과 candidate comparison rule을 frozen invocation에 포함한다.
- 선택되지 않은 candidate와 failed fit도 catalog에서 구분해 조회할 수 있다.
- 새 fitted state는 proposed result로 먼저 저장하고 validation과 commit boundary 뒤에만 이후 decision의
  authoritative input이 된다.
- Historical what-if fit, hyperparameter search와 model comparison은 actual Qlib Account, production account,
  sibling trial 또는 previously committed fitted state를 mutate하지 않는다.
- Resume은 selected fitted-state identity와 training cursor를 복원해 uninterrupted run과 같은 decision history를
  만든다.

Model update가 alpha/ensemble allocation을 바꾸는 경우 fitted-state lineage에서 그 downstream decision까지
연결한다. 단순히 최신 model file path를 가리키는 것으로 adaptive research provenance를 대체하지 않는다.

## 9. Alpha decision lifecycle

### 9.1 Alpha decision requirements

Alpha-weight decision은 bounded input과 declared result dependencies를 받아 side-effect 없는 decision result를
만든다. State change가 필요하면 result에 proposed next state를 포함하고 runtime commit boundary에서만
authoritative state로 반영한다.

Alpha-weight decision behavior는 다음을 하지 않는다.

- Qlib order type이나 broker execution tactic 결정
- Source file을 임의로 다시 읽어 PIT boundary 우회
- Requested target을 actual holding으로 간주
- Artifact publication 전에 external state mutation

### 9.2 Signed alpha-weight result

Canonical alpha result는 최소한 다음을 포함한다.

- Decision time와 instrument
- Signed weight 또는 exposure intent
- Weight semantics: raw, active, benchmark-relative 또는 physical 여부
- Gross/net, normalization basis와 budget convention
- Cash/residual and per-name cap
- Universe/coverage and missingness
- Signal and other-data dependencies
- Alpha-decision implementation/config identity
- Actual-state/feedback dependency and run scope
- Diagnostics, warnings와 terminal status

Negative weight는 research intent일 수 있으며 Qlib executable negative Position을 의미하지 않는다.

### 9.3 Fixed와 flexible budget

- **Fixed budget:** target gross/net 또는 total allocation을 명시적으로 채운다.
- **Flexible budget:** weak signal, missing input 또는 unavailable instrument 때문에 unused budget을 cash/residual로
  보존한다.

Untradable instrument를 제외한 뒤 나머지 weight를 자동 확대하는 behavior는 flexible budget을 위반한다.

### 9.4 Path-independent와 path-dependent alpha

Signal과 contemporaneous market data만 소비하는 alpha는 execution path와 독립적일 수 있다. 이 경우 materialized
weight를 여러 execution profile에서 재사용할 수 있다.

다음에 의존하는 alpha는 path-dependent다.

- Actual current holdings or cash
- Prior fills, rejects or blocked orders
- Realized transaction cost or PnL
- Cooldown, stop-loss 또는 stateful memory
- Execution-profile-specific turnover constraint

Path-dependent weight는 해당 run의 intermediate result다. 다른 execution history에서 universal alpha처럼
재사용하지 않는다.

### 9.5 Actual feedback와 Qlib runtime integration

Native execution은 다음 loop를 따른다.

```text
Qlib Executor result
-> Qlib-compatible Strategy call with execute_result
-> bounded input with actual Position
-> alpha-weight decision and physical construction
-> signed weights and physical target publication
-> best-effort constraint adjustment
-> target-to-order conversion
-> final pre-execution constraint validation
-> Qlib TradeDecision
-> Executor
```

Partial fill과 blocked trade 뒤 다음 decision은 requested target이 아니라 actual Qlib Position을 본다.

### 9.6 Observation, decision, execution과 monitoring clocks

- **Observation clock:** 새로운 data/state를 관측하는 시점
- **Decision clock:** alpha/portfolio policy가 새 intent를 만드는 시점
- **Execution clock:** order/fill을 처리하는 bar 또는 interval
- **Monitoring clock:** 저장된 account snapshot을 분석하는 시점

각 supported profile은 clock의 source, cadence, timezone, calendar와 상호 관계를 frozen config에 선언한다.
Trigger가 observation point마다 평가되는지 별도 cadence에서 평가되는지도 명시한다. Monitoring clock은
decision clock과 독립적일 수 있으며, required monitoring profile은 decision이 없는 시점에도 marked actual
account snapshot을 제공해야 한다.

Qlib `NestedExecutor`는 multi-level execution clock을 제공할 수 있지만 arbitrary observation scheduler, PIT cutoff,
research-child isolation 또는 production monitoring service를 자동 제공하지 않는다.

Lookback은 rows와 duration semantics를 구분하고 mixed-frequency input별 cutoff와 coverage를 기록한다. Dense
evaluation profile은 매 point마다 unrelated full history를 다시 load하지 않고 declared lookback과 bounded-load
expectation 안에서 실행되어야 한다.

### 9.7 Hold와 dense state

새 decision이 없는 evaluation point는 zero executable order의 native empty decision으로 표현한다. 이전 target을
다시 제출해 price drift에 따른 암묵적 rebalance를 만들지 않는다.

Dense executor calendar에서 empty decision이어도 bar-end position mark가 진행되어야 한다. Required profile은
portfolio metrics를 명시적으로 활성화하고 no-trade bar의 evidence row를 보존한다.

Hold에는 조정하거나 validate할 새 target/order가 없으므로 constraint adjustment와 pre-execution validation을
실행할 필요가 없다. 그러나 actual account mark와 independent constraint monitoring은 계속할 수 있다.
가격 drift, partial fill, blocked liquidation 또는 corporate action으로 생긴 breach도 이 경로에서 관찰한다.

### 9.8 Trigger와 mandatory finalization

Trigger는 새 decision 생성 여부를 결정한다. Finalization은 run 종료 시 open state, blocked liquidation,
baseline, cash와 pending artifact를 정리하는 별도 단계다.

- Trigger evaluation은 evaluation time, information cutoff, bounded inputs, prior state, fire/hold outcome, reason,
  cooldown 또는 next eligible time과 implementation/config identity를 기록한다.
- Trigger false는 hold이며 failure가 아니다.
- Finalization은 마지막 trigger와 무관하게 실행한다.
- Finalization trade가 blocked되면 realized residual을 기록한다.
- Run end에서 requested target으로 Position을 강제 덮어쓰지 않는다.

Supported trigger profile은 scheduled trigger, bar-boundary conditional trigger와 true intrabar trigger 중 제공하는
범위를 명시한다. Bar-boundary profile을 true intrabar event execution으로 표시하지 않는다.

### 9.9 Parent/child research

Child research는 parent가 허용한 lookback, datasets, cutoff와 state authority를 넘지 않는다. Historical what-if
child는 parent actual Qlib Account나 sibling state를 mutate하지 않는다. Qlib nested execution과 qlibx nested
research를 같은 개념으로 취급하지 않는다.

### 9.10 Checkpoint와 resume

Checkpoint는 다음 authority를 함께 보존한다.

- Actual Position, cash와 accumulated execution state
- Alpha/strategy memory와 prior feedback cursor
- Calendar/execution cursor
- Baseline/endowment state when applicable
- Frozen invocation and input identity
- Artifact publication state
- Qlib/qlibx compatibility version

Resume 직후 state와 uninterrupted run state가 reconcile되어야 한다. Unconfirmed production state는 checkpoint에
authoritative state로 남지 않는다.

### 9.11 Adaptive alpha research and belief update

Alpha 또는 ensemble이 new evidence에 따라 parameter, regime state, member allocation이나 belief를 바꿀 수 있다.
이때 update는 hidden mutable variable이 아니라 재현 가능한 state transition으로 기록해야 한다.

- Prior state, new evidence cutoff, update rule, proposed posterior/next state와 selected action을 식별한다.
- Bayesian update를 주장하면 prior, likelihood assumption, observed evidence와 posterior identity를 기록한다.
- Rolling performance, drawdown, regime, capacity, cost 또는 realized execution feedback을 사용할 때 어떤 clock과
  bounded artifact가 update를 유발했는지 기록한다.
- Candidate alpha/ensemble reallocation은 before/after weights, constraints, unused budget과 decision rationale를
  비교할 수 있어야 한다.
- Historical simulation, counterfactual evaluation과 parameter search는 별도 research state namespace와 isolated
  account를 사용하며 actual Qlib Account, production account 또는 sibling trial state를 mutate하지 않는다.
- Proposed state는 validation과 explicit runtime commit boundary 전에 authoritative state가 아니다. Failed,
  rejected 또는 abandoned update도 reason과 evidence를 남긴다.

Adaptive behavior가 execution feedback을 소비할 수는 있지만 requested target을 actual feedback으로 대체하지
않는다. Production에서는 confirmed fill/account snapshot을 reconcile한 state만 다음 belief update의 authoritative
execution evidence가 된다.

## 10. Ensemble and portfolio construction

### 10.1 Stored-alpha ensemble

Stored-alpha ensemble은 complete signed alpha-weight results를 소비해 새로운 combined weight를 만든다. Input
member의 producer를 다시 실행하지 않는다.

Ensemble result는 다음을 포함한다.

- Member IDs, versions와 content fingerprints
- Member allocation and normalization
- Ticker-level pre/post-net weights
- Crossing/netting amount
- Gross/net and residual budget
- Member contribution and overlap
- Correlation and incremental evidence
- Dependency lineage and terminal status

Ensemble output도 canonical signed alpha-weight result이므로 다른 ensemble의 member가 될 수 있다. Cycle은
허용하지 않는다.

### 10.2 Prior research와 orthogonality

새 alpha나 ensemble proposal 전에 stored catalog에서 유사한 hypothesis, data, transform과 empirical result를
검색할 수 있어야 한다.

Orthogonality는 다음을 구분한다.

- Semantic novelty
- Signal/return correlation and overlap
- Existing ensemble에 대한 incremental contribution
- Exposure duplication
- Regime-specific dependence

상관계수 하나로 novelty를 단정하지 않는다.

### 10.3 Portfolio construction problem

Physical portfolio construction은 signed active intent를 investable physical portfolio로 변환한다. 최소
problem은 다음을 표현한다.

- Expected active alpha
- Benchmark and current physical holdings
- Stock/ETF/cash instrument set
- Long-only physical bounds
- Gross/net/active budget
- Per-name, sector, factor와 beta constraints
- Turnover and transaction-cost penalty/limit
- Tradability, lot와 minimum trade
- ETF look-through when supported
- Hard versus soft constraints
- Flexible residual/cash behavior

### 10.4 Required construction result

Result는 target만 반환하지 않고 다음을 포함한다.

- Physical target weights and quantities when available
- Cash/residual
- Intended versus realized active weights
- Constraint slack, binding status와 relaxation
- Turnover and estimated cost
- Objective components
- Solver/backend/status and diagnostics
- Clipped or unimplemented signed intent
- Pre/post-lot validation

Hard infeasibility, soft relaxation, solver error, unsupported backend와 valid optimum을 다른 status로 구분한다.

### 10.5 Optimizer backend boundary

Backend는 교체 가능하지만 같은 qlibx problem/result contract를 만족해야 한다. Silent constraint removal,
automatic current-weight fallback 또는 missing solver를 success로 반환해서는 안 된다.

Qlib 0.9.7 `EnhancedIndexingOptimizer`는 일부 enhanced-index problem에 재사용할 수 있지만 qlibx contract와
수학적으로 동일하다고 가정하지 않는다. Objective, cash, ETF, budget, solver와 fallback semantics를
characterization한 profile에서만 사용한다.

### 10.6 ETF와 look-through

ETF physical holding과 constituent exposure를 구분한다.

- Qlib Account는 실제 ETF instrument의 quantity와 value를 소유한다.
- Point-in-time constituent data가 있으면 qlibx analysis가 look-through exposure를 계산한다.
- Constituent data가 없으면 ETF를 opaque instrument로 유지한다.
- Constituent exposure를 synthetic Position이나 executable holding으로 기록하지 않는다.

### 10.7 Tradability, lot와 optimization

Optimizer가 continuous target을 만들었다는 사실과 order가 executable하다는 사실은 다르다. Lot rounding,
untradable names, price availability와 cash feasibility는 post-solve validation과 target-to-order conversion에서
처리하고 모든 difference를 diagnostic으로 보존한다.

### 10.8 Pre-execution constraint adjustment

Physical portfolio construction optimizer와 pre-execution constraint adjustment는 다른 responsibility다. 전자는
alpha, risk와 cost objective에서 physical target을 만들고, 후자는 이미 제안된 target/order를 declared limit에
맞게 best-effort로 다듬는다.

Adjustment는 actual holdings/cash, proposed intent, permitted PIT data와 applicable constraint를 소비한다. Result는
original/adjusted intent, hypothetical post-trade state, constraint별 before/after measurement, method/iteration,
termination status와 unresolved residual을 포함한다. Constraint를 완전히 만족시키지 못해도 residual을 숨기지
않고, result를 compliant success로 표시하지 않는다.

Built-in과 project-local adjustment를 허용한다. Black-box metric은 근사적일 수 있고 linear/convex constraint는
정확한 method를 사용할 수 있으므로 method, tolerance와 guarantee를 result에 명시한다. Adjustment는 새
target/order가 있는 triggered decision에서만 필요하다.

### 10.9 Pre-execution constraint validation

Validator는 optimizer와 독립적으로 최종 제출 후보를 평가한다. Target-to-order conversion, lot rounding,
tradability 또는 cash clipping이 quantity를 바꾸면 그 이후 결과를 validate하거나 validation을 반복한다.

- Warning은 finding을 보존하고 declared execution policy에 따라 진행할 수 있다.
- Error는 `TradeDecision` 제출을 중단하거나 explicit override를 요구한다.
- Override는 actor, time, reason과 exact finding identity를 기록한다.
- Invalid executable target, evaluator failure와 ordinary constraint excess를 다른 status로 구분한다.

Constraint optimizer가 residual을 남겼다는 사실만으로 실행 여부를 결정하지 않는다. Validator finding과
declared policy가 continue, stop 또는 approved override를 결정한다.

### 10.10 Flexible-budget attribution

Flexible-budget strategy의 realized return을 단순 stock-selection return으로 표시하면 cash/residual과 budget
timing 효과가 selection skill로 섞인다. Analysis는 가능한 범위에서 같은 signed intent와 information set을
사용하는 fixed-budget counterfactual과 actual flexible-budget result를 비교하고 다음 효과를 구분한다.

- Signal 또는 name selection effect
- Invested-budget level과 timing effect
- Cash, benchmark, passive residual과 financing return
- Constraint, tradability, lot와 transaction-cost implementation effect
- Counterfactual로 설명되지 않는 reconciliation residual

Counterfactual은 실제로 실행된 account가 아니므로 realized holding처럼 표시하지 않는다. Reweighting rule,
financing, benchmark, cash return, cost, rebalance clock과 unavailable-name 처리 가정을 기록한다. Additive
attribution이 수학적으로 성립하지 않으면 억지로 합을 맞추지 않고 interaction/residual을 별도로 보여준다.
Attribution table은 actual result, counterfactual result와 exact upstream alpha/portfolio artifact를 lineage로
연결한다.

## 11. Qlib execution and signed compatibility

### 11.1 Native execution lifecycle

Canonical historical execution path는 Qlib native lifecycle을 사용한다.

```text
qlibx bounded input and decision behavior
-> Qlib-compatible Strategy integration
-> physical target and best-effort constraint adjustment
-> target-to-order conversion and final constraint validation
-> Qlib TradeDecision
-> SimulatorExecutor or NestedExecutor
-> Exchange order handling and dealt quantity
-> Qlib Account and Position
-> qlibx portable result and diagnostic integration
-> next bounded decision input
```

Strategy, decision, executor, exchange와 account 역할을 하나의 qlibx for-loop에 합치지 않는다.

### 11.2 Qlib Exchange integration

Project market data, stock/ETF cost, lot, tradability와 volume policy를 Qlib Exchange extension point로 제공할 수
있다. 이 integration은 Qlib order/fill/account lifecycle을 우회하지 않는다.

선택한 profile은 최소한 다음을 명시한다.

- Execution and valuation price
- Open/close convention
- Cost and tax schedule
- Lot/quantity unit
- Suspension and price-limit behavior
- Volume participation and clipping
- Missing price behavior

> **Architecture/implementation candidate — non-normative**
>
> Project scenario를 Qlib `Exchange` extension point에 연결하는 구현에 `ScenarioExchange` 같은 설명용 이름을
> 사용할 수 있다. 이 이름이나 subclass layout은 product requirement가 아니다.

### 11.3 Order generation

Qlib weight-to-order building block은 qlibx semantics와 parity가 맞을 때 재사용한다. 다음 behavior를 public
contract로 암묵적으로 받아들이지 않는다.

- Tradable subset만 남긴 뒤 automatic renormalization
- Missing price/untradable target의 silent skip
- Sell-first/buy-second ordering에서 lost diagnostic
- Flexible budget을 fixed budget처럼 확대
- Current holding, target와 cash unit의 implicit mismatch

Target-to-order conversion result는 requested order뿐 아니라 instrument별 conversion, rounding, clipping,
skip/failure reason을 모두 포함한다.

Conversion이 proposed quantity나 cash를 변경하면 final pre-execution validator가 converted result를 평가한다.
Unresolved error finding과 approved override가 모두 없는 상태에서 Qlib `TradeDecision`을 제출하지 않는다.

### 11.4 Position direction과 instrument declaration

Position이 음수 수량을 가질 수 있는지는 engine의 고정 속성이 아니라 instrument가 선언하는 capability다
(§7.12). Engine은 선언을 읽어 강제하며 asset class를 하드코딩하지 않는다.

- `long_only` — 미보유 SELL과 보유 초과 SELL을 거부한다. Signed alpha의 short intent는 physical
  construction 단계에서 해소되어야 하며, 권장 경로는 long-only enhanced-index construction이다.
- `hypothetical_short` — 음수 position을 허용하되 borrow, 담보, 차입 비용과 locate를 모델링하지 않는다.
  해당 position에 의존한 result는 hypothetical로 표시되고 execution profile에서 거부된다.
- `real_short` — 현재 범위 밖이다(§5.7). 선언 항목이 갖춰지기 전에는 `unsupported`로 실패한다.

Declaration을 확인하지 않고 음수 position을 허용하거나, `hypothetical_short` 결과를 executable short로
표시하지 않는다.

### 11.5 Initial-position accounting

Initial cash와 stock endowment가 있으면 first return denominator, marked starting NAV와 initial Position state가
일치해야 한다. Default field를 그대로 사용해 첫 bar return을 왜곡하지 않는다.

Resume 시 previous NAV denominator와 accumulated metrics도 uninterrupted run과 일치해야 한다.

### 11.6 Active performance와 limitations

Composite account return과 signed active strategy return은 다르다. Analysis는 baseline, composite와 active
economics를 분리한다.

- Composite Qlib Position and account value
- Baseline stock and financing
- Active quantity and active PnL
- Transaction cost and dealt quantity
- Capitalization event neutrality
- Intended versus realized active exposure

`hypothetical_short` profile은 다음을 모델링하지 않으며 result와 report에 명시한다.

- Locate/borrow availability
- Margin/collateral
- Recall and forced buy-in
- Borrow fee
- Securities-lending capacity

Result와 report에 limitation을 명시한다.

### 11.7 Settlement와 corporate action

Settlement, adjusted price, quantity factor, dividend, split, delisting과 corporate-action semantics가 확인되지
않으면 exchange 또는 broker behavior를 추측하지 않는다. Qlib settlement option을 사용하기 전에 selected
market convention과 characterization parity를 검증한다.

## 12. Research workspace, artifact graph and catalog

### 12.1 Workspace

Project는 exploratory scripts, notebooks와 notes를 둘 수 있다. Canonical result는 scratch path나 live notebook
state가 아니라 validated artifact publication으로 식별한다.

각 research session은 다른 session과 충돌하지 않는 scratch namespace를 가져야 한다. Scratch에는 incomplete
download, bounded sample, temporary transform, notebook output와 candidate config를 둘 수 있지만 다음 규칙을
따른다.

- Scratch result는 validation과 atomic publication 전까지 catalog의 complete artifact로 검색되지 않는다.
- Session 종료 시 retain, publish 또는 discard할 item을 명시하고 published item은 exact scratch source와
  transformation lineage를 가진다.
- Failed/abandoned session은 failure evidence와 retention decision을 남기며 partial file을 canonical alias로
  승격하지 않는다.
- 다른 agent와 후속 run은 scratch path를 추측해 읽지 않고 catalog와 published artifact identity를 사용한다.
- Cleanup은 session-owned scratch만 대상으로 하며 published payload, other session state와 user-owned file을
  제거하지 않는다.

다음은 fresh user가 config, research code, local extension, scratch와 published result의 위치를 상상하기 위한
**illustrative layout**이다. 이 directory name이나 nesting은 강제가 아니며 같은 ownership, isolation,
discoverability와 publication semantics를 만족하면 다른 layout을 사용할 수 있다.

```text
config/qlibx/                    # project-owned resolved-input sources
data/qlibx/                      # optional project-owned materialized data
qlibx-research/                  # scripts, notebooks and local research code
.qlibx/
  extensions/                   # example local extension location; not mandatory
  sessions/<session-id>/scratch/
  artifacts/
  catalog/
reports/
```

특히 `.qlibx/extensions/`는 user journey를 설명하는 예시일 뿐 public import path나 required discovery path가
아니다. 반면 §6.1의 agent-skill output directories는 target protocol이므로 exact normative path다. 두 종류의
경로를 혼동하지 않는다.

### 12.2 Portable artifact envelope

모든 complete stage result는 최소한 다음 envelope를 갖는다.

- Artifact type and schema version
- Stable artifact ID and content fingerprint
- Producer implementation and version
- Frozen config/input fingerprint
- Time range and decision cutoff
- Axis, unit, currency and timezone
- Portable payload or immutable payload reference
- Coverage, warning, diagnostic and terminal status
- Parent/member/input dependency lineage
- Path-dependency and compatibility flags

초기 portable format은 metadata/config에 JSON, tabular/matrix payload에 Parquet 또는 Arrow-compatible data를
사용한다. Model binary나 Qlib pickle은 별도 non-portable payload로 reference할 수 있다.

### 12.3 Standard artifacts

- Dataset registration and materialization
- Model fit and fitted state
- Signal, label, factor return/exposure and risk estimate
- Alpha weight
- Ensemble weight and member contribution
- Optimization problem and result
- Physical target
- Constraint declaration snapshot and adjustment result
- Trade decision and requested order
- Pre-execution validation finding and approved override
- Fill and execution diagnostic
- Position/account snapshot
- Actual-account constraint monitoring finding
- Instrument capability declaration snapshot
- Checkpoint/resume state
- Analysis tables and report manifest
- Production prepared decision and OMS result

### 12.4 Artifact dependency graph

Artifact lineage는 단순 parent run ID가 아니라 typed dependency graph다.

```text
dataset snapshot ─┐
fitted model ─────┼─> stored signal ─┐
other data ───────┘                   ├─> signed alpha weights
universe/benchmark ──────────────────┘          |
                                                v
other stored alpha weights ───────────> ensemble weights
                                                |
                                                v
current holdings / constraints ──────> physical target
                                                |
                                                v
actual Position / price / lot ───────> orders and fills
```

Dependency edge는 consumer role, selected field/column, version/fingerprint와 time compatibility를 기록한다.
Graph는 acyclic이어야 하며 mutable alias만으로 dependency를 식별하지 않는다.

Constraint lineage는 exact declaration/data와 proposed target에서 adjustment result와 converted order를 거쳐
validation finding으로 이어지고, confirmed fill/account snapshot에서 monitoring finding으로 이어져야 한다.
Hypothetical validation state와 actual monitoring state를 같은 edge나 identity로 합치지 않는다.

### 12.5 Centralized file-backed catalog

모든 session과 agent에게 하나의 queryable project-local catalog로 보여야 한다. MongoDB나 always-on service를
기본 요구하지 않는다.

Catalog는 다음을 저장하거나 참조한다.

- Run/trial and artifact identity
- Terminal status and stage completion
- Frozen invocation and environment compatibility
- Dataset/model/producer-implementation identity
- Portable artifacts and dependency edges
- Metrics, diagnostics and warnings
- Publication timestamp and content fingerprint
- User decision and promotion status

### 12.6 Publication semantics

- Artifact payload를 먼저 완성하고 검증한 뒤 catalog visibility를 commit한다.
- Crash로 incomplete payload가 생기면 complete record로 보이지 않는다.
- 같은 identity와 content의 duplicate publication은 idempotent할 수 있다.
- 같은 identity와 다른 content는 conflict이며 덮어쓰지 않는다.
- Stale session이 최신 record를 overwrite하지 못한다.
- Reporting은 새 canonical research result를 암묵적으로 만들지 않는다.

### 12.7 Identity와 reuse

Identity는 name만이 아니라 input, config, code/component와 semantics fingerprints를 포함한다. Human-readable
alias는 immutable identity를 가리킬 수 있지만 identity 자체를 대체하지 않는다.

Reuse 시 producer implementation은 필요하지 않지만 schema, semantics, dependency, compatibility와 terminal
status 검사는 필요하다.

### 12.8 Parallel-agent behavior

여러 session과 agent가 같은 repository와 branch에서 연구할 수 있다. 다음을 default로 제공한다.

- Session-scoped temporary state
- Frozen run inputs
- Atomic publication
- Deterministic duplicate/conflict handling
- Stale update rejection
- Qlib process-global state isolation

Git branch 또는 worktree 생성은 qlibx research isolation의 필수조건이 아니다. qlibx가 user의 Git history를
자동 관리하지도 않는다.

### 12.9 Qlib Recorder integration

Qlib Recorder/MLflow experiment는 model fit과 native records의 runtime sink로 사용할 수 있다. Integration은
Qlib run ID를 qlibx artifact identity와 연결하고 필요한 output을 portable artifact로 export한다.

Recorder success만으로 qlibx publication complete가 되지 않는다.

### 12.10 Custom intermediate artifact and external round-trip

Standard artifact 목록에 없는 project-specific intermediate result도 named, versioned artifact로 저장할 수
있어야 한다. Custom type은 namespace, semantic description, schema/version, axis/unit/time semantics, producer,
payload media type, compatibility와 dependency를 선언하고 §12.2의 envelope와 publication rule을 따른다.

Consumer가 custom semantics를 이해하지 못해도 artifact identity, raw payload reference, checksum, provenance와
dependency edge는 보존할 수 있어야 한다. 반대로 type name만 같다는 이유로 payload를 해석하거나 compatible한
standard artifact로 간주하지 않는다.

External tool round-trip은 다음을 지원한다.

```text
published qlibx artifact or immutable raw source
-> explicit export manifest
-> external calculation or review
-> validated re-import as a new artifact
-> dependency edge to exact exported input and external producer
```

Export manifest는 selected fields, schema, content fingerprint, time/axis semantics와 redaction을 기록한다.
Re-import는 expected schema, checksum/content identity, row/key coverage와 time semantics를 검증하고 external tool,
version, parameter와 operator evidence를 producer lineage에 남긴다. Original artifact나 raw source를 in-place로
덮어쓰지 않는다. Binary, text 또는 vendor-native payload도 immutable raw reference로 보존할 수 있지만 portable
consumer contract가 없는 payload를 standard portable artifact라고 표시하지 않는다.

### 12.11 Research proposal and decision audit

Research proposal은 자유 형식 note만이 아니라 실행·비교 범위를 고정하는 structured result여야 한다. 최소한
다음을 기록한다.

- Hypothesis와 예상 economic/statistical mechanism
- Prior related research와 novelty claim
- Required datasets, signals, universe, benchmark와 availability assumptions
- Observation, label, decision, holding과 evaluation horizon
- Transform, model, parameter/search space와 search budget
- Baseline, out-of-sample protocol, metrics와 comparison rule
- Cost, turnover, capacity와 implementation assumptions
- Stopping, failure와 acceptance criteria

Proposal은 실행 전에 frozen invocation과 연결되고, 변경되면 같은 proposal을 조용히 수정하지 않고 revision을
만든다. Trial 종료 뒤 decision record는 `promote`, `reject`, `retain-for-evidence`, `supersede` 중 명시적 outcome과
proposal/run/artifact IDs, 적용한 criteria, supporting/contradicting evidence, decision maker, timestamp, rationale와
unresolved risk를 기록한다.

Promotion은 immutable result를 mutate하지 않고 promoted alias/status가 exact artifact identity를 가리키게 한다.
Reject와 failed result도 검색 가능하게 남아 같은 hypothesis와 failure를 반복하지 않게 한다. Agent가 promotion을
제안할 수는 있지만 project가 요구한 human approval을 우회하거나 metric 하나만으로 자동 promote하지 않는다.
Decision update는 expected prior decision fingerprint를 검사하며 stale promote/reject/supersede attempt는
명시적으로 conflict로 실패한다.

## 13. Analysis, reporting and extensibility

### 13.1 Analysis와 rendering 분리

Analysis module은 stored artifacts에서 performance, risk, exposure, attribution, turnover, cost와 reconciliation을
계산한다. Renderer는 analysis output을 표, graph와 document로 표현한다. Renderer가 canonical calculation을
숨겨서 다시 수행하지 않는다.

두 층 사이에는 versioned **report composition manifest**가 있어야 한다. Composition은 새 research calculation을
수행하는 것이 아니라 다음을 선언한다.

- 사용할 analysis artifact와 table/series selection
- Section order, grouping, label, comparison과 narrative reference
- Built-in analysis와 project-local analysis의 조합
- Renderer, theme, output format와 destination
- Required/optional section과 missing-dependency behavior
- Input artifact fingerprints와 composition/renderer version

User는 stored analysis result를 research rerun 없이 선택·제거·재배열·결합해 다른 report를 만들 수 있어야
한다. 같은 metric을 renderer별로 다시 계산하지 않으며, report-only filter나 formatting이 canonical analysis
artifact를 mutate하지 않는다. Required section의 input이 없으면 composition은 incomplete/capability gap으로
끝나고 빈 chart를 success로 만들지 않는다.

Renderer output은 report manifest와 exact analysis dependencies를 가진다. Report publication이 별도 research
artifact를 만들 필요가 있을 때만 명시적으로 publish하며, 기본적으로 rendering 자체가 새로운 alpha evidence나
promotion decision을 암묵적으로 만들지 않는다.

### 13.2 Built-in analysis

Data가 있을 때 다음을 제공한다.

- Signal IC/RankIC, quantile spread, coverage와 turnover
- Alpha gross/net, exposure와 path-dependency diagnostics
- Ensemble member contribution, overlap, netting와 crossing
- Portfolio performance and risk
- Market/benchmark/industry/factor exposure
- Cost, fill and desired-versus-realized reconciliation
- Optimizer objective, constraint와 relaxation
- Constraint adjustment effectiveness, unresolved residual과 validation override
- Constraint utilization, warning/error/breach history와 passive versus trade-induced breach
- Physical/look-through reconciliation
- Composite/baseline/active signed reconciliation
- Regime and stability diagnostics

Required dependency가 없으면 해당 analysis를 silently 생략하지 않고 capability gap을 반환한다.

### 13.3 Monitoring analysis

Historical backtest에서는 dense account artifacts를, production에서는 external OMS account snapshots를 읽는다.
Monitoring analysis는 pure artifact consumer로 구현할 수 있다. Snapshot polling, always-on scheduling과 real-time
alert delivery는 external runtime responsibility다.

Observation, decision, execution과 monitoring clock을 하나의 Strategy loop로 강제하지 않는다.

Constraint monitoring은 strategy가 trigger되지 않은 시점에도 marked actual account와 PIT-safe compliance data를
평가한다. 가격 drift, partial fill, blocked liquidation과 corporate action에 의한 breach를 포함하고, requested
target을 actual state처럼 사용하지 않는다. Stored history는 strategy rerun 없이 `as-was` 또는 `as-if` constraint
evaluation에 재사용할 수 있다. Monitoring은 account를 mutate하거나 order를 직접 생성하지 않는다.

### 13.4 Public extension points

- Dataset loader and materializer
- Processor and signal transform
- Signal generation and fitted model behavior
- Alpha-weight decision behavior
- Stored-alpha ensemble behavior
- Physical portfolio construction and optimizer backend
- Constraint metric and best-effort adjustment behavior
- Pre-execution validation policy
- Target-to-order conversion and Qlib runtime integration
- Exchange cost/tradability policy
- Actual-account constraint monitoring behavior
- Analyzer and reporter
- Production artifact integration

Extension은 installed package를 수정하지 않고 project 안에서 작성·등록할 수 있어야 한다.

### 13.5 Extension contract

각 extension은 다음을 선언한다.

- Stable type, ID and version
- Input capability requirements
- Output artifact schema
- Determinism and fitted/state behavior
- Availability and lookback behavior
- Failure contract
- Compatibility range

Undocumented private import를 public extension surface로 사용하지 않는다.

### 13.6 Qlib native component exposure

Qlib class를 config에서 직접 지정할 수 있어도 qlibx compatibility validation을 우회하지 않는다. Native
component는 다음 중 하나로 분류한다.

- `native-compatible`: qlibx semantics와 parity 검증 완료
- `adapted`: wrapper/translator 뒤에서 사용
- `analysis-only`: execution authority 없음
- `unsupported`: selected profile과 충돌

### 13.7 Agent-readable documentation

Installed documentation만으로 agent가 다음을 찾을 수 있어야 한다.

- Project discovery and status
- Available capabilities and extensions
- Config schemas and examples
- Artifact schemas and public loaders
- Error stages and recovery guidance
- Validation commands
- Qlib compatibility limitations

Documentation은 source checkout이나 hidden test를 전제로 하지 않는다.

Documentation access는 task-bounded retrieval을 지원해야 한다. Agent는 전체 manual이나 모든 example을 context에
적재하지 않고 project status, capability ID, error `stage`, artifact type 또는 public operation을 key로 관련
schema, help, minimal example와 recovery section만 조회할 수 있어야 한다. Search result는 document/version,
section identity와 bounded excerpt/reference를 반환한다.

Public status, schema, help와 error output은 non-interactive mode에서 UTF-8 machine-readable form을 제공해야
한다. Documentation lookup이 package private source scan이나 unrestricted project data read로 확장되어서는 안
된다. 필요한 정보가 여러 section에 걸치면 skill은 먼저 index/capability inventory로 범위를 좁힌 뒤 필요한
resource만 읽는다.

### 13.8 Package-provided agent skill

Package distribution은 installed qlibx version과 일치하는 agent skill resource를 제공한다. Skill은 private
source를 읽지 않고 installed documentation, public schema, status, capability inventory, error와 validation
surface만 사용해야 한다.

Skill은 최소한 다음 workflow를 제공한다.

- Project discovery, initialization과 current-state inspection
- Data registration과 semantic-binding interview
- Research proposal, prior-result lookup, execution과 publication
- Requirement gap의 stage별 resolution interview
- Project-local extension scaffold, validation과 repair
- Stored result reuse, ensemble, backtest와 reporting

현재 version이 제공하는 각 extension point에 대해 skill은 workflow 위치, required input/output, data/time
boundary, validation과 minimal example을 직접 포함하거나 그 정보를 가진 exact version-matched installed
documentation section으로 연결해야 한다. Extension 이름만 나열하거나 private source 탐색을 지시하는 것은
valid skill content가 아니다.

각 stage guidance는 계약 요약, 자주 발생하는 실패, 가능한 복수의 해결 경로, user confirmation이 필요한
선택과 해결 뒤 다시 실행할 public operation을 포함해야 한다. Skill은 특정 해결책을 user confirmation 없이
선택하거나 package validation을 우회하지 않는다.

Agent-specific instruction은 bundled skill 또는 정확한 version-matched resource로 routing해야 한다. Product
facts와 schema를 agent-specific file에 복제하지 않는다.

Skill materialization은 §6.1의 exact normative output protocol을 따라야 한다. 즉 Codex는
`.agents/skills/qlibx/SKILL.md`, Claude Code는 `.claude/skills/qlibx-skill/SKILL.md`, explicit custom target은
`<user-selected-output>/qlibx/SKILL.md`를 entrypoint로 사용한다. 이 경로는 `.qlibx/extensions/` 같은 optional
project layout example과 달리 교체 가능한 implementation hint가 아니다.

Generated skill은 exact output directory, qlibx/skill schema version, included resource manifest와 validation
result를 machine-readable하게 보고해야 한다. Preview 없이 user-modified skill을 overwrite하지 않고,
version update와 removal도 §6.1의 managed ownership/idempotency rule을 따른다.

### 13.9 Local extension repair loop

User/agent가 local component를 scaffold한 뒤 실패하면 error는 stage, observed input, original exception과 safe
recovery guidance를 반환한다. Package-provided skill은 이 error를 해석해 복수의 repair path를 제시한다.
Agent는 package source를 수정하지 않고 project-local code/config를 고쳐 다시 validate한다.

## 14. Production decision and OMS boundary

### 14.1 범위

Production scope는 durable local artifacts를 통해 external OMS와 통신하는 broker-neutral incremental decision
runtime이다. qlibx는 direct broker API owner가 아니다.

### 14.2 Prepared decision

Strategy evaluation은 immutable prepared decision을 만든다.

- Decision ID and portfolio/account ID
- Signal/alpha/portfolio/config/input identity
- Decision time and information cutoff
- Broker-neutral target position, quantity or order intent
- Validity window and target tolerance
- Price/quantity/risk boundaries
- Expected actual-state fingerprint
- Constraint-adjustment result and final validation-finding identity
- Remaining warnings and approved override identity when applicable
- Required OMS result schema

Prepared decision 생성만으로 authoritative strategy state를 advance하지 않는다.
Unresolved error finding과 approved override가 모두 없는 prepared decision은 executable outbox에 publish하지 않는다.

### 14.3 Outbox와 OMS inbox

qlibx는 atomic local outbox publication을 제공한다. External OMS는 decision을 claim하고 execution한 뒤 confirmed
result와 account snapshot을 inbox에 기록한다.

OMS result는 최소한 다음을 포함한다.

- Decision and idempotency IDs
- Accepted/rejected/partial/expired status
- Requested and filled quantity
- Fill price, cost and time
- Remaining quantity and reason
- Account/holding snapshot reference

### 14.4 Commit boundary

qlibx는 OMS result와 actual account snapshot을 검증하고 reconciliation이 통과한 뒤 completed checkpoint를
commit한다. Delta는 prior requested target이 아니라 actual holding에서 계산한다.

```text
actual holdings
-> prepare target and delta
-> external execution
-> confirmed fills and snapshot
-> reconcile
-> commit authoritative strategy state
```

Rejected, partial 또는 zero fill 뒤에는 실제 상태만 advance한다.

### 14.5 Concurrency와 idempotency

초기 contract는 portfolio/account마다 동시에 하나의 in-flight decision만 허용한다. 같은 decision/result의
duplicate delivery는 idempotent해야 한다. Supersede/merge semantics는 별도 roadmap이며 암묵적으로 지원하지
않는다.

### 14.6 Execution policy

Validity window, target tolerance, partial completion, market close와 expiry behavior를 decision 또는 project-owned
OMS policy에 명시한다. “장중 최대한 실행” 같은 모호한 문장을 executable policy로 사용하지 않는다.

### 14.7 Storage와 recovery

Local storage는 임시 file drop이 아니라 durable protocol이다.

- Atomic visibility boundary
- Schema/version validation
- Checksum/content identity
- Duplicate and stale-result handling
- Claim/recovery and replay
- Completed checkpoint immutability
- Audit trail and retention policy

### 14.8 Production monitoring

OMS는 actual account snapshot을 선택된 주기로 저장할 수 있다. qlibx는 그 artifact를 읽어 desired-versus-actual,
risk, stale decision과 reconciliation 상태를 분석한다. Polling, process supervision과 alert delivery는 external
runtime이 소유한다.

Production constraint monitoring은 confirmed OMS/account snapshot과 monitoring time에 available한 compliance
data만 사용한다. Monitoring warning/error/breach는 prior fill을 rollback하지 않고 durable finding으로 남는다.
Finding이 remediation 또는 다음 strategy trigger에 사용되면 explicit dependency와 authority transition을
기록한다.

## 15. Acceptance criteria

### P0 — Product comprehension and onboarding

- PRD 첫 부분만 읽고 signal, alpha, ensemble, physical portfolio와 Qlib runtime의 차이를 설명할 수 있다.
- Physical construction optimizer, constraint adjustment, pre-execution validator와 actual-account monitoring의
  책임과 authority 차이를 설명할 수 있다.
- Fresh project에서 installed documentation만으로 init, status와 capability discovery를 수행한다.
- Installed package가 version-matched bundled agent skill resource를 제공한다.
- Onboarding dry-run이 생성·수정할 exact path, managed instruction block, versions와 validation을 실제 변경 전에
  보여준다.
- Codex target은 `.agents/skills/qlibx/SKILL.md`, Claude Code target은
  `.claude/skills/qlibx-skill/SKILL.md`, explicit custom target은
  `<user-selected-output>/qlibx/SKILL.md`에 valid skill entrypoint를 만든다.
- 같은 onboarding/update/remove를 반복해도 duplicate나 unrelated diff가 없고, user-modified skill과 instruction
  content를 명시적 확인 없이 덮어쓰거나 삭제하지 않는다.
- Missing instruction file은 preview와 explicit creation request가 있을 때만 생성한다.
- 여러 selected coding-agent target을 독립적으로 materialize하고 각 변경과 validation result를 확인한다.
- Source checkout이나 private import 없이 public extension surface를 찾는다.
- Qlib version과 compatibility profile을 확인할 수 있다.
- Status, capability, error stage 또는 artifact type으로 installed documentation의 관련 schema/help/example만
  bounded retrieval하고 UTF-8 machine-readable output을 얻는다.
- Public failure가 `stage`, `message`, `expected`, bounded `context`, `requires_user_confirmation`, `retryable`과
  `error_id`를 반환하며 internal traceback/secret과 분리된다.
- Bundled skill이 structured requirement gap을 읽어 복수의 resolution path와 user-confirmation point를 제시하고,
  user-confirmed change 뒤 같은 public operation을 retry한다.
- Explicitly requested sample을 public surface만으로 data registration부터 stored signal, signed weights, optional
  Qlib backtest, artifact/report lookup까지 실행하며 fresh project에 sample을 자동 주입하지 않는다.

### P1 — Data registration and PIT

- Opaque source를 bounded inventory한 뒤 user-confirmed semantic binding으로 등록한다.
- Canonical materialization과 Qlib-compatible mapping을 생성한다.
- Invalid datetime, duplicate `(available_at, instrument)`와 incomplete universe를 거부한다.
- Signal generation, alpha-weight decision, child research와 inner execution call이
  `available_at <= decision_time`을 위반하지 않는다.
- Frozen run은 시작 뒤 project config 변경의 영향을 받지 않는다.
- 서로 다른 provider/calendar run이 global state를 통해 오염되지 않는다.
- Strategy와 compliance evaluator가 독립적인 data requirement를 PIT-safe하게 binding하고 compliance-only data가
  explicit dependency 없이 strategy input으로 전달되지 않는다.

### P2 — Signal model and materialized research data

- Qlib Model 또는 project-local signal-generation/model implementation을 resolved config에서 실행한다.
- Fit, fitted processor와 inference scope를 분리하고 leakage를 검사한다.
- Stored signal을 producer, input, availability, operation과 coverage lineage와 함께 저장한다.
- Stored signal을 producer rerun 없이 두 개 이상의 alpha policy가 소비한다.
- Upstream identity가 바뀌면 derived signal/factor-return artifact를 stale로 감지한다.
- Conventional Qlib ML task를 qrun-compatible workflow로 실행하고 portable qlibx artifact로 adapt한다.
- Rolling/expanding/event-triggered retraining이 당시 available data만 사용하고 각 fitted state, comparison,
  selection과 training cursor를 별도 evidence로 남긴다.
- Historical model search와 failed candidate가 actual/sibling account 또는 committed fitted state를 mutate하지
  않으며 resume이 uninterrupted selected-state history와 일치한다.

### P3 — Alpha-weight research

- Stored signals와 declared other data를 소비해 signed alpha weights를 만든다.
- Alpha output은 weights이며 order-generation concern을 포함하지 않는다.
- Signed weight, budget, normalization, universe와 dependency lineage를 portable artifact로 저장한다.
- Path-independent와 actual-state-dependent weight를 구분한다.
- Qlib-native IC/RankIC/quantile spread를 semantics parity 후 재사용한다.
- Diagnostic long-short와 executable short를 명확히 구분한다.
- Missing capability를 silent skip하지 않는다.
- Adaptive alpha/belief update가 prior, bounded new evidence, update rule, proposed next state와 before/after allocation을
  기록한다.
- Bayesian claim은 prior/likelihood/posterior identity를, performance/regime/capacity update는 triggering artifact와
  clock을 기록한다.

### P4 — Qlib closed-loop runtime integration

- Qlib runtime integration은 `BaseStrategy` contract를 만족하고 `TradeDecision`을 반환한다.
- Integration은 intermediate alpha weight와 physical target을 portable result로 기록한다.
- Actual Qlib Position과 prior execution result가 다음 bounded decision input에 전달된다.
- Partial/blocked fill 뒤 requested target이 아니라 actual state를 본다.
- Trigger false는 empty-order hold이며 target 재제출 rebalance를 만들지 않는다.
- Dense profile은 no-trade bar의 account/position evidence를 보존한다.
- Trigger evaluation이 time, cutoff, inputs, fire/hold reason과 next eligible time을 저장한다.
- 월간 decision trigger와 일별 monitoring profile에서 non-trigger day는 zero order이지만 marked actual-account와
  monitoring row를 남긴다.
- Dense evaluation은 declared lookback만 bounded load하고 매 point마다 unrelated full history를 다시 읽지 않는다.
- Parent/child PIT와 state-isolation boundary를 보존한다.
- Historical what-if, adaptive search와 counterfactual child가 actual Qlib/production account, committed strategy
  state와 sibling trial을 mutate하지 않고 proposed state는 commit 전 authority를 갖지 않는다.

### P5 — Research catalog and dependency graph

- Stored signal/alpha/target을 producer rerun 없이 query하고 reuse한다.
- 어떤 alpha가 어떤 exact signal/data/version에 의존하는지 조회한다.
- 어떤 upstream 변경이 어떤 downstream artifact를 stale하게 하는지 조회한다.
- Content/provenance conflict와 incomplete publication을 구분한다.
- Prior alpha와 semantic/empirical orthogonality evidence를 조회한다.
- 최소 세 session이 같은 project/branch에서 deterministic publication behavior를 보인다.
- Qlib Recorder pickle 없이도 standard artifact를 읽을 수 있다.
- Session scratch는 complete catalog result와 격리되고 retain/publish/discard가 기록되며 다른 agent는 scratch
  path가 아니라 published identity를 소비한다.
- Structured proposal이 hypothesis, inputs, horizons, bounded search/evaluation/cost/stopping rule을 고정하고
  revision lineage를 가진다.
- Promote/reject/retain-for-evidence/supersede decision이 exact proposal/run/artifact, criteria, evidence, actor,
  timestamp와 rationale를 보존하며 rejected/failed research도 검색된다.
- Stale proposal/promotion update가 expected prior fingerprint conflict로 명시적으로 실패한다.

### P6 — Ensemble and physical construction

- Stored alpha weights를 member lineage와 함께 ensemble한다.
- Ticker-level netting, crossing, member contribution과 residual을 저장한다.
- Ensemble output이 새로운 canonical signed alpha-weight result로 재사용된다.
- Signed active intent를 long-only stock/ETF/cash target으로 변환한다.
- ETF를 opaque instrument로 실행하고 constituent data가 있을 때만 look-through를 계산한다.
- Physical holding과 constituent exposure를 별도 result로 유지한다.
- Hard infeasibility, soft relaxation, solver error와 unsupported backend를 구분한다.
- Silent constraint removal/current-weight fallback을 success로 허용하지 않는다.
- Constraint adjustment가 original/adjusted intent, hypothetical state, before/after measurement와 unresolved
  residual을 저장하며 미해결 결과를 compliant success로 표시하지 않는다.
- Built-in과 project-local adjustment가 같은 result/failure contract를 만족한다.
- Flexible-budget result를 fixed-budget counterfactual과 비교해 selection, invested-budget timing, cash/passive
  residual/financing, implementation과 unexplained residual을 가정·lineage와 함께 구분한다.

### P7 — Native Qlib execution

- Canonical path가 Qlib Strategy/TradeDecision/Executor/Exchange/Account lifecycle을 사용한다.
- Target-to-order conversion이 all-order conversion, rounding, clipping과 failure diagnostics를 보존한다.
- Quantity-changing conversion 뒤 final validator가 warning/error를 기록하고, unresolved error는 제출 중단 또는
  recorded explicit override를 요구한다.
- Adjustment residual, validation finding, evaluator failure와 actual monitoring breach를 서로 다른 status로
  유지한다.
- Native path와 characterization oracle의 supported long-only result/account parity를 검증한다.
- Nested execution에서도 PIT boundary와 account metric frequency를 검증한다.
- Checkpoint/resume result가 uninterrupted run과 reconcile된다.

### P8 — Instrument capability and signed execution

- Instrument가 quantity unit, price convention, position direction constraint, cost, tradability와
  settlement를 declaration으로 제공하고 engine이 asset class를 하드코딩하지 않는다.
- 선언되지 않은 short capability는 `long_only`로 취급하며 unknown을 shortable로 추측하지 않는다.
- `long_only` instrument는 미보유 SELL과 보유 초과 SELL을 거부한다.
- `hypothetical_short` instrument의 음수 position이 허용되고, 그 position에 의존한 result가
  hypothetical로 표시되며 execution profile에서 거부된다.
- `hypothetical_short` result를 `real_short` result와 같은 성과로 비교하거나 promotion 근거로 사용할 수
  없다.
- Engine이 해석할 수 없는 capability를 선언한 instrument는 `unsupported`로 실패하며 부분 해석해
  실행하지 않는다.
- Artifact가 소비한 instrument declaration identity를 lineage에 기록한다.
- Dollar-neutral signed portfolio의 수익률 분모는 gross로 계산하고 그 규약을 result에 기록한다.
- Initial/first-resume metric denominator가 marked starting NAV와 일치한다.

### P9 — Artifacts, extensions and reporting

- Complete stage result를 documented JSON/Parquet/Arrow-compatible format으로 export한다.
- Project-local signal generation, alpha-weight decision, processing, analysis와 reporting implementation이
  package 수정 없이 동작한다.
- Stored artifact에서 research rerun 없이 report를 만든다.
- Analysis calculation과 rendering을 분리한다.
- Report composition manifest로 stored analysis의 section을 선택·제거·재배열하고 built-in/local analysis와
  renderer를 조합하며 metric을 renderer 안에서 재계산하지 않는다.
- Performance, exposure, cost, optimizer와 signed reconciliation을 제공한다.
- Monitoring analysis는 stored account snapshot의 pure consumer로 동작한다.
- 가격 drift만으로 발생한 breach와 partial fill 뒤 actual-holding breach를 새 strategy decision 없이 감지한다.
- Stored account history를 새 constraint로 strategy rerun 없이 재평가하고 `as-was`와 `as-if`를 구분한다.
- Project-specific intermediate result를 versioned custom artifact로 publish하고 unknown consumer도 raw payload,
  checksum, provenance와 dependency를 보존한다.
- Artifact를 explicit manifest로 external tool에 export한 뒤 schema/content/time semantics와 external producer
  lineage를 검증해 새 artifact로 re-import하며 original을 덮어쓰지 않는다.

### P10 — Production artifact boundary

- Prepared decision을 durable outbox에 atomic publish한다.
- Prepare는 authoritative strategy state를 commit하지 않는다.
- External OMS result와 actual account snapshot을 reconcile한 뒤 completed checkpoint를 commit한다.
- Prepared decision은 final validation finding과 override identity를 포함하며 unresolved error를 executable
  outbox에 publish하지 않는다.
- Production monitoring은 confirmed actual account와 PIT-safe compliance data를 사용하고 finding이 prior fill을
  rollback하지 않는다.
- Partial/rejected/expired/duplicate/stale result를 명시적으로 처리한다.
- Delta는 actual holding에서 계산한다.
- Portfolio당 single in-flight decision과 crash recovery를 검증한다.
- Broker connectivity, scheduling과 real-time alert가 qlibx 밖의 책임임을 유지한다.

## 16. Compatibility gates and validation

### 16.1 Qlib upgrade gate

Qlib version을 바꾸기 전에 최소한 다음을 검증한다.

- Strategy feedback and empty decision behavior
- Independent decision/monitoring clocks and no-trade account marks
- WeightStrategy-style weight-to-order boundary
- Calendar/provider registration and cache isolation
- Custom provider end-to-end native backtest
- Executor order sequencing and account update timing
- Portfolio metric frequency and initial denominator
- Position negative-quantity rejection
- Exchange cost, lot and tradability behavior
- Post-conversion constraint validation and override ordering
- Actual-account monitoring PIT and authority behavior
- NestedExecutor account sharing and PIT enforcement behavior
- Recorder/Processor metric parity
- Optimizer solver, fallback and status behavior

### 16.2 Native migration gate

Manual characterization lifecycle을 제거하기 전에 다음 evidence가 있어야 한다.

- Existing supported long-only fixtures parity
- Hold/no-trade bar parity
- All-order diagnostics preservation
- Trigger/finalization parity
- Constraint adjustment/validation finding parity
- Dense non-trigger monitoring parity
- Checkpoint/resume parity
- Instrument capability declaration 강제 동작
- Bounded performance regression
- Rollback path

### 16.3 Artifact compatibility gate

Artifact schema나 identity rule을 변경할 때 다음을 검증한다.

- Old artifact read or explicit migration behavior
- Dependency graph integrity
- Producer-independent loading
- Duplicate/conflict identity behavior
- Partial/incomplete publication recovery
- Path-dependent artifact misuse prevention
- Constraint declaration/adjustment/validation/monitoring lineage integrity
- Hypothetical validation state and actual monitoring state separation

### 16.4 Test philosophy

Prototype implementation과 tests는 이 PRD의 evidence다. Prototype의 accidental class name, file layout 또는
private API를 requirement로 승격하지 않는다. Tests는 public behavior, accounting identity, information boundary,
feedback ordering, trigger/monitoring clock separation, constraint authority와 artifact contract를 검증한다.

## 17. Out of scope and roadmap

### 17.1 현재 범위 밖

- Native short Position/Account in Qlib
- Broker borrow, locate, margin, recall와 borrow-fee modeling
- Futures, options, bonds와 derivatives lifecycle
- Direct broker API and secret management
- Always-on OMS, scheduler와 real-time alert delivery
- Distributed MongoDB task orchestration as a prerequisite
- Unbounded autonomous strategy state mutation
- Source availability declaration의 경제적 진실성 자동 판정
- User가 제공하지 않은 universe, shortability, corporate action 또는 exposure data 추측

### 17.2 Asset-class expansion

새 asset class는 instrument ID만 추가해서 지원하지 않는다. §7.12의 instrument capability declaration으로
valuation, quantity/contract unit, settlement, expiry, margin, corporate action, cost와 risk semantics를
정의하고, engine이 그 선언을 소비할 수 있음을 증명해야 한다.

우선순위가 확인된 확장 후보는 `real_short`(borrow/담보/차입 비용)와 perpetual/futures(funding, 계약 단위,
강제청산)다. 둘 다 §7.12의 선언 항목을 늘리는 형태이며 engine 구조 변경을 요구하지 않아야 한다.

### 17.3 AI-defined runtime policy

AI가 runtime에서 직접 alpha logic을 바꾸거나 decision을 생성하는 기능은 future scope다. 도입 시 bounded input,
deterministic replay, approval, safety limit, provenance와 commit boundary를 먼저 정의한다.

AI를 사용하는 project-local signal-generation 또는 alpha-decision implementation도 같은 public contract를
만족하면 연결할 수 있다.
qlibx가 별도의 opaque AI state authority를 만들지는 않는다.

### 17.4 Optimizer backend expansion

Commercial risk model, alternative solver와 differentiable optimizer는 같은 problem/result contract 뒤에 추가할 수
있다. Adoption은 feature count가 아니라 semantic parity, explicit failure와 reproducibility로 판정한다.

### 17.5 Production expansion

Multiple in-flight decisions, supersede/merge, high-frequency feedback와 service deployment는 initial local artifact
protocol이 안정된 뒤 별도 product decision으로 다룬다.

## 18. Product-level conclusion

qlibx의 차별점은 Qlib을 대체하는 데 있지 않다. Qlib의 data/model/strategy/execution runtime을 최대한
활용하면서 그 주위에 다음 계약을 제공하는 데 있다.

- Signal과 alpha의 분리
- Reusable signed alpha weights
- Stored-artifact composition and dependency lineage
- Signed research와 investable physical portfolio의 연결
- Selective decision, best-effort constraint adjustment와 independent validation
- Actual execution feedback authority
- Decision과 독립적인 actual-account constraint monitoring
- Producer-independent evidence와 agent-readable product surface

```text
Research freely in signed alpha space.
Materialize reusable signals and weights.
Construct investable portfolios explicitly.
Adjust intent, validate execution, and monitor actual state separately.
Use Qlib for closed-loop execution mechanics.
Use qlibx for meaning, composition, authority and evidence.
```

Native reuse가 짧은 코드라는 이유만으로 qlibx contract를 약화해서는 안 된다. 반대로 qlibx contract를
지킨다는 이유로 Qlib lifecycle을 다시 구현해서도 안 된다.
