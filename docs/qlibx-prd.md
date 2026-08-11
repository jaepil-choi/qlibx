# vqapr Product Requirements Document

Status: canonical
Runtime: vqapr-owned research and execution capability (no Qlib runtime dependency)
Target package/import/CLI name: `vqapr`
Implementation status: target product contract; package migration and rewrite follow architecture completion
Companion document: the architecture document maintained beside this PRD

이 문서는 vqapr의 제품 철학, observable behavior, correctness boundary와 acceptance criteria를 규정하는
정본이다.

## 0. Runtime ownership

이 절은 normative이며 본문의 다른 모든 절보다 우선한다.

### 0.1 vqapr는 자체 execution engine을 소유한다

vqapr는 Qlib을 backtest runtime backend로 사용하지 않는다. Historical simulation과 선택된 execution
profile의 상태 전이를 vqapr가 책임지며, `pyqlib`는 runtime, test 또는 build dependency가 아니다.

vqapr-owned execution capability는 다음 product behavior를 제공해야 한다.

- **Path-dependent strategy.** Stop-loss, cooldown, turnover-aware rebalance와 adaptive belief처럼 이전의
  committed fill, realized price, actual holding, cash 또는 bounded strategy state에 따라 다음 판단이 달라지는
  전략을 지원한다. Weight 벡터를 날짜별로 독립 계산하는 방식만을 backtest로 간주하지 않는다.
- **Multi-instrument portfolio.** 하나의 run과 account에서 여러 instrument의 position, shared cash, cost,
  exposure와 cross-instrument decision을 함께 처리할 수 있어야 한다. 종목별 계산을 지원한다는 사실만으로
  portfolio-level 동시성을 충족했다고 간주하지 않는다.
- **Multi-frequency workflow.** Observation, Model calculation, Strategy decision, execution, valuation과
  monitoring은 서로 다른 frequency와 cadence를 가질 수 있어야 한다. 예를 들어 daily observation과
  valuation을 사용하면서 monthly rebalance와 daily monitoring을 수행할 수 있어야 한다.
- **Point-in-time correctness.** 각 판단과 계산은 자신의 evaluation time에 허용된 정보만 사용하며 미래
  observation이나 아직 확정되지 않은 execution result를 읽지 않는다.
- **Closed-loop feedback.** Committed execution outcome과 그에 따른 actual state가 이후 Strategy decision의
  입력이 된다. Requested target이나 가상 post-trade state를 actual feedback으로 사용하지 않는다.
- **Deterministic replay.** 같은 frozen input, data와 product policy에서는 판단 순서, state transition,
  diagnostics와 결과가 재현된다.
- **Lifecycle extensibility.** 새로운 cadence, instrument lifecycle 또는 monitoring requirement를 추가할 때
  관련 없는 Model, Strategy 또는 execution behavior의 의미를 다시 정의하지 않아야 한다.

이 요구는 intraday order book, partial fill, real settlement 또는 모든 asset class를 현재 지원한다는 뜻이
아니다. Current와 future support boundary는 §5.7과 §17이 정한다.

> **Architecture suggestion — non-normative**
>
> 독립 cadence, path-dependent feedback와 결정론적 순서를 함께 만족시키는 방법으로 event-driven scheduler와
> role-specific callback mechanism을 권장한다. Queue, callback registry, context/view, scheduler와 class
> decomposition은 architecture가 선택하며, 같은 product behavior를 만족하는 다른 설계도 허용한다.

### 0.2 Reference implementation은 product authority가 아니다

Qlib, vn.py, NautilusTrader와 다른 reference implementation은 behavior comparison, calculation
characterization과 설계 검토에 사용할 수 있다. 그러나 어느 reference도 vqapr의 runtime dependency, state
authority, public result format 또는 workflow coordinator가 아니다.

Reference에서 관찰하거나 차용한 behavior도 이 PRD의 correctness, explicit failure, diagnostic preservation와
portable result 요구사항을 만족해야 한다. Reference version을 바꾸거나 대체해도 vqapr의 observable product
semantics가 암묵적으로 달라져서는 안 된다.

구체적인 source, version, license, 차용 범위와 검증 방법은 companion architecture와 provenance record에서
관리한다. 이는 product requirement가 아니다.

### 0.3 본문 해석 규칙

본문에서 Qlib, vn.py 또는 NautilusTrader를 이름으로 언급하는 경우 §0.2의 comparison 또는 provenance
대상만을 뜻한다. `Model`, `Strategy`, decision, execution, position과 account 같은 명칭은 별도 external package가
명시되지 않는 한 제품의 semantic role을 설명한다. 특정 Python class, inheritance 또는 module path를 뜻하지 않는다.

본문과 이 절이 충돌하면 §0의 runtime ownership이 우선한다.

### Document interpretation

본문의 normative 제품 요구사항은 vqapr가 제공해야 하는 user-visible capability, economic semantics,
observable behavior, external compatibility, stored result와 correctness boundary를 규정한다. 특정 class hierarchy,
object count, process boundary, registry, file layout, storage engine와 Python method name은 명시적으로
**external product contract**라고 선언하지 않는 한 요구사항이 아니다.

> **Architecture/implementation candidate — non-normative**
>
> 이 표기가 붙은 이름, diagram, method shape와 component decomposition은 요구사항을 만족할 수 있는 하나의
> 구현 후보다. 동일한 product semantics, evidence와 acceptance criteria를 만족하는 다른 구조를 허용한다.

## 1. Product thesis

### 1.1 제품 정의

`vqapr`는 자체 research와 execution capability를 소유하는 **재사용 가능한 alpha research framework**다.
Qlib을 포함한 reference implementation은 behavior와 계산의 비교 대상으로만 사용한다.
Quantitative researcher와 그 연구를 지원하는 coding agent가 다음 작업을 하나의 누적 가능한 연구 환경에서
수행하도록 돕는다.

- Project data를 의미와 point-in-time availability가 명시된 logical dataset으로 등록한다.
- Model 또는 deterministic transform이 재사용 가능한 signal, feature와 다른 derived research data를 만들고
  local storage에 축적할 수 있다.
- Strategy가 point-in-time data에서 signal과 signed portfolio weight를 한 번에 계산하거나, 미리 저장된 signal과
  다른 data를 읽어 signed portfolio weight를 만든다.
- 기존 Strategy를 member로 참조하는 ensemble Strategy가 compatible stored alpha-weight result를 조합하고
  ticker-level intent를 netting한다.
- Signed active intent를 실제 운용 가능한 physical portfolio로 변환한다.
- Proposed physical target 또는 order를 declared constraint에 맞게 best-effort로 조정하고, 별도 validation으로
  advisory compliance finding을 만든다.
- Strategy가 만든 executable intent와 실제 execution outcome을 분리하고, 선택한 execution profile로
  closed-loop simulation한다. MVP profile은 지원되는 order가 전량 체결되고 주식·ETF의 cash가 즉시
  결제된다고 가정한다. Partial fill, 미체결 order lifecycle과 실제 결제주기는 future work다.
- Strategy decision과 독립적으로 schedule된 monitoring event에서 marked actual account snapshot과 PIT-safe
  compliance data를 평가한다. Decision이 없는 시점에도 monitoring할 수 있으며, finding은 account를 변경하거나
  주문을 직접 생성하지 않는다.
- 성공과 실패, input dependency와 intermediate result를 다음 연구의 출발점으로 보존한다.

이 capability는 독립적으로 사용할 수 있다. 모든 연구가 하나의 end-to-end pipeline을 끝까지 따라야 한다고
강제하지 않는다.

### 1.2 주요 사용자와 product promise

주요 사용자는 quantitative researcher와 research engineer이며, coding agent는 이들의 작업을 지원하는
first-class user다.

사용자는 reference implementation의 internal class hierarchy나 vqapr private source를 모두 알 필요가 없어야
한다. 대신 데이터의
경제적 의미, availability, universe, benchmark, alpha hypothesis, risk constraint와 execution policy처럼 결과의
의미를 바꾸는 결정은 명시적으로 내려야 한다.

예를 들어 data registration을 돕는 agent는 `DATE`라는 이름만 보고 event time이나 `available_at`을 추측해서는
안 된다. 다음처럼 정보가 실제로 알려진 시점과 look-ahead 위험을 설명하고 user의 명시적 결정을 받아야 한다.

```text
Agent: DATE 컬럼의 값은 데이터가 나타내는 사건의 발생 시점인가요, 아니면 그 행 전체를 시장 참여자가
       실제로 알 수 있게 된 시점인가요? 예를 들어 DATE=2025-01-02인 종가 행 전체를 같은 날 장 시작 전에
       사용할 수 없다면, DATE를 그 시점의 투자 결정 input으로 사용하면 look-ahead가 발생합니다.

Agent: vqapr는 모든 관측치에 available_at을 정해야 합니다. available_at은 "이 값으로 투자 결정을 내려도
       되는 최초 시점"입니다. source에 실제 공개 시각 컬럼이 있다면 어느 컬럼인지 지정해 주세요. 없다면
       DATE + 확정된 공개 지연 규칙(예: 다음 영업일 08:00)을 사용할지, 명시적 timestamp를 source에
       추가할지 결정해 주세요. 근거가 확인되기 전에는 DATE를 available_at으로 간주해 등록하지 않겠습니다.
```

`DATE`가 실제 공개 시각임을 user가 확인한 경우에만 같은 컬럼을 event time과 `available_at`에 함께 binding할
수 있다. 별도 availability 컬럼이 없으면 bundled agent skill은 data category, source 설명과 공개 관행을 근거로
하나 이상의 지연 규칙 candidate를 제시하고, 각 candidate의 가정과 look-ahead 영향을 설명해야 한다. 예를 들어
일봉 종가는 `DATE` 당일 장 종료 시각, 재무제표는 별도 공시 timestamp 또는 확인된 publication lag를 제안할 수
있다. 이 candidate는 package default가 아니며 user가 근거를 확인해 선택해야 한다. 선택된 규칙은 project config에
명시하고 package가 형식, coverage와 PIT consistency를 deterministic하게 validation한다.

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

vqapr의 첫 번째 목적은 **signed cross-sectional alpha research**다. Signal이 양수와 음수를 갖고 alpha
weight가 long과 short intent를 표현하는 것은 정상적인 research behavior다. 실제 borrow 가능성이나 선택한
execution profile의 long-only 제약 때문에 research intent를 미리 long-only로 축소하지 않는다.

Model research는 portfolio나 execution 없이 끝날 수 있다. 반면 **portfolio return, NAV, PnL 또는 turnover를
주장하는 모든 executable Strategy run은 동일한 closed-loop lifecycle을 끝까지 따른다.** 대표적인 composition은
다음과 같다.

```text
registered PIT data ──> Model/transform ──> reusable research result ──> analysis / reuse
          |
          └────────────> Strategy decision
                              |
                   mandatory portfolio construction
                              |
                    frozen intended portfolio
                              |
        execution-time order conversion from committed state
                              |
         selected academic or physical execution profile
                              |
              fills -> committed account -> valuation
                              |
                 feedback / analysis / evidence
```

1. **Model/research loop.** Model 또는 transform은 feature, firm characteristic, signal, label, factor return과
   같은 derived research data를 만들고 저장할 수 있다. IC·RankIC·prediction diagnostic처럼 portfolio 성과를
   주장하지 않는 연구는 여기서 완결될 수 있다.
2. **Strategy decision.** Strategy는 registered PIT data, 선택적인 reusable research result, committed account
   state와 bounded strategy state를 소비해 경제적 판단을 만든다. 그 public output shape는 별도 설계 논의로
   남기며 downstream lifecycle에 결합하지 않는다.
3. **Strategy composition.** Ensemble은 별도의 후처리 단계로 강제되는 것이 아니라 기존 member Strategy와
   그 compatible stored alpha-weight result를 입력으로 삼는 하나의 Strategy다. Member contribution, 같은 ticker의
   반대 intent netting, crossing과 dependency를 관측 가능하게 남긴다.
4. **Portfolio construction 공통 경계.** Executable Strategy run은 signed, long-only, benchmark-relative 여부와
   무관하게 현재 연구 결과를 실행 가능한 하나의 frozen intended portfolio로 확정한다. Construction 규칙은
   profile마다 다를 수 있지만 이 경계를 우회할 수는 없다.
5. **하나의 execution lifecycle.** Academic long-short와 physical long-only는 같은 intended-portfolio → order
   conversion → fill → account commit → valuation → feedback 순서를 따른다. 달라지는 것은 선택 profile이 허용하는
   direction, instrument별 quantity granularity, price, cost와 realism뿐이다. Intended result와 committed result를
   같은 state로 취급하지 않는다.

실제 운용 portfolio가 long-only여도 original signed alpha를 덮어쓰지 않는다. 실현되지 않은 short intent,
constraint clipping, residual과 physical mapping은 별도 evidence로 남긴다.

단순 long-only strategy와 market-timing policy도 구성할 수 있다. Cross-sectional stock-picking rebalance는
중요한 research profile이지만 package가 모든 user에게 강제하는 유일한 기본 흐름은 아니다.

### 2.2 Model과 Strategy는 분리된 product role이다

**Model**은 point-in-time data를 소비해 다른 연구와 Strategy가 재사용할 수 있는 research result를 만든다.
Prediction, signal, feature, firm characteristic, risk estimate와 statistical factor-return estimate가 대표적인
결과다. Model의 정상적인 종착점은 reusable result와 그 평가 evidence이며, portfolio나 order를 반드시 만들 필요가
없다.

**Strategy**는 registered data와 선택적인 Model result, 그리고 필요한 경우 actual portfolio state와 bounded
strategy state를 소비해 경제적 decision result를 만든다. 이 PRD는 Strategy가 signal, score, weight 또는 target
중 하나를 반드시 public output으로 내도록 고정하지 않는다. Deterministic rule만으로 판단하는 Strategy는 Model을
선행 조건으로 요구하지 않는다.

Model result와 Strategy result는 경제적 의미가 다르다. Signal을 weight로, statistical estimate를 executed
portfolio return으로, intended target을 actual holding으로 가장해서는 안 된다. 같은 implementation이 내부에서
signal과 weight를 연속 계산할 수는 있지만 public result와 acceptance에서는 두 semantic role을 구분해야 한다.
이는 별도 Python class, process 또는 service를 반드시 두라는 요구사항이 아니다.

Factor return도 의미를 구분한다.

- Cross-sectional regression coefficient나 statistical factor estimate는 Model/research result로 만들 수 있다.
- 실제 factor portfolio의 return, NAV, PnL 또는 turnover는 선택한 execution과 accounting을 거친 결과여야 한다.

> **Architecture suggestion — non-normative**
>
> Reusable Model result와 portfolio-state-aware Strategy decision을 별도 component boundary로 두면 reuse와 독립
> 평가가 단순해진다. 한 component가 두 계산을 함께 수행하더라도 외부 result contract는 두 역할을 구분해야 한다.

### 2.3 Model research와 Strategy research는 독립적으로 실행하고 조합할 수 있다

Model-only run, Strategy-only run과 Model result를 소비하는 Strategy run은 모두 완전한 workflow일 수 있다.
Research가 반드시 order로 변환되거나 end-to-end execution까지 진행될 필요는 없다.

```text
registered PIT data -> Model -> reusable signal / estimate / research result
registered PIT data ------------------------------------┐
reusable Model result ----------------------------------┼-> Strategy result -> analysis / reuse
actual portfolio state, when required ------------------┘                         |
                                          executable run selected ----------------┘
                                                       |
                                  frozen intended portfolio -> common execution loop
```

제품은 다음 composition을 지원해야 한다.

- 같은 Model result를 서로 다른 Strategy가 재사용하고 독립적으로 평가한다.
- 같은 Strategy logic을 compatible한 여러 Model result와 비교한다.
- 여러 Strategy result를 producer 재실행 없이 조합한다.
- Strategy result를 analysis, comparison 또는 export에 사용할 수 있다. Execution을 선택한 run은 frozen intended
  portfolio를 반드시 확정한 뒤 공통 execution lifecycle을 따른다.

Result dependency는 구체적으로 확인 가능해야 한다. Strategy result는 실제로 소비한 data와 Model/Strategy result를
식별하고, execution result는 자신이 처리한 Strategy intent를 식별한다. 이 traceability는 producer를 특정 class나
process로 고정하지 않는다.

### 2.4 Decision과 execution outcome은 closed loop에서 분리된다

Strategy는 decision time에 허용된 관측과 committed actual state만 사용해 intent를 만든다. Execution은 선택한
profile의 timing, price, tradability, cost와 fill assumption으로 그 intent를 처리한다. Execution time에 새로 보이는
정보로 과거 Strategy intent를 암묵적으로 다시 계산하지 않는다.

제품은 다음 observable behavior를 보장해야 한다.

- Strategy intent는 fill이나 realized holding이 아니다.
- Simulation에서 committed fill은 현실 세계의 체결은 아니지만 해당 run의 authoritative execution result다.
- 다음 decision은 requested target이 아니라 committed actual holding, cash와 execution result를 본다.
- Stop-loss는 actual entry/fill price와 이후 marked price 또는 realized state를 이용할 수 있다.
- Rebalance state, cooldown, risk regime와 fitted belief를 bounded strategy state로 이어갈 수 있다.
- Blocked 또는 zero-dealt order는 fill로 가장하지 않으며 다음 decision이 구분해 읽을 수 있다.
- Constraint adjustment와 pre-execution validation은 proposed state에 대한 evidence이고 actual fill과 구분된다.
- Actual-account monitoring은 decision cadence와 독립적이며, finding을 명시적으로 Strategy input으로 채택하기
  전에는 자동 feedback이 아니다.

MVP simulation은 지원되는 order의 전량 체결과 주식·ETF cash의 즉시 결제를 가정한다. Intraday liquidity,
partial fill, pending/cancel state와 external OMS 연결은 future capability다.

> **Architecture suggestion — non-normative**
>
> Decision, execution, state commit과 feedback을 서로 다른 event callback으로 처리하는 구조는 위 경계와
> path-dependent loop를 구현하는 권장 방법이다. 구체 event type, component name, scheduling과 commit protocol은
> architecture가 정한다.

### 2.5 Durable intermediate artifact가 public integration point다

Signal, alpha weight, ensemble weight, optimization problem/result, physical target, constraint
declaration/adjustment/validation, order, fill, position, monitoring finding과 analysis table은 최종 report의
부산물이 아니라 first-class result다.

Runtime 내부에서는 목적에 맞는 Python object와 compiled representation을 사용할 수 있다. 그러나 다음 경우의
public contract는 versioned portable artifact다.

- 다른 run, process 또는 agent가 결과를 재사용할 때
- Producer를 다시 실행하지 않고 downstream 작업을 할 때
- Project-local code와 built-in을 연결할 때
- 실패한 run을 감사하거나 재개할 때
- 외부 OMS나 reporter와 통신할 때

Downstream consumer는 producer가 vqapr built-in, local Python module 또는 외부 process인지 몰라도 schema,
semantics, compatibility와 lineage를 검사할 수 있어야 한다. 따라서 local serialized data를 읽을 때 단순
`dict`로 넘기는 데서 끝내지 않고 semantic role에 맞는 typed Python object를 생성해야 하며, object 생성 또는
deserialization 경계에서 schema, required field, type, version과 cross-field invariant를 validation해야 한다.
Invalid serialized state는 partially constructed object로 runtime에 들어가서는 안 된다.

### 2.6 Package behavior는 deterministic하고 bundled agent skill이 대화를 담당한다

Package의 계산·검증 behavior는 선언된 input을 받아 선언된 output을 만드는 deterministic library behavior다.
User에게 질문하지 않고, 빠진 data를 비슷한 field로 대체하지 않으며, 경제적 의미를 추측하지 않는다.

Capability가 충족되지 않으면 package는 agent layer가 해석할 수 있도록 다음의 observed fact를
machine-readable하게 보고한다.

- Failure stage, stable error code와 실패한 requirement identity
- Missing/invalid field, observed value shape와 bounded offending example
- 어떤 validation rule 또는 compatibility condition이 충족되지 않았는가
- Operation이 state를 commit했는지와 deterministic retry에 필요한 precondition 또는 idempotency identity

Package error는 가능한 resolution candidate나 user에게 물을 질문을 결정하지 않는다. Bundled agent skill이
package error, skill 지침, project context와 user가 제공한 의미를 함께 해석해 복수의 해결 경로를 만들고,
각 경로의 가정·trade-off·변경 범위를 설명한다. 경제적 의미나 authority를 바꾸는 선택은 agent가 최종 결정을
대신하지 않고 user가 판단할 수 있도록 질문해야 한다.

vqapr package distribution은 현재 package version과 일치하는 agent skill resource를 포함해야 한다. Project
onboarding은 사용자가 선택한 coding-agent environment에서 이 skill을 사용할 수 있게 해야 한다. Bundled
skill은 structured gap을 user에게 설명하고, 필요한 질문을 하고, user-confirmed registration/config 또는
project-local extension을 작성한 뒤 package의 public validation과 capability를 다시 호출하는 reference
conversational workflow다.

Bundled skill은 다음을 담당한다.

- Public status, capability inventory, schema, example와 error를 조회한다.
- Package error와 skill 지침에서 가능한 복수의 resolution 경로를 구성하고 설명한다.
- 경제적 의미가 필요한 선택은 user에게 확인한다.
- User-confirmed project config 또는 local extension을 작성하고 package validation을 호출한다.
- 같은 public operation을 retry하고 result, limitation과 changed files를 요약한다.

Package의 deterministic behavior가 agent skill을 호출하거나 대화 상태를 소유하지 않는다. Skill도 package
validation을 우회하거나 missing semantics를 추측하지 않는다. Validation을 호출하는 주체가 agent여도
config와 local extension을 deterministic하게 판정하고 machine-readable result를 반환하는 책임은 package에
있다.

```text
deterministic package behavior
  requirement declaration -> object/extension validation -> structured failure/result

package-provided agent skill
  candidate construction -> explanation -> user interview -> project change -> package validation and retry
```

### 2.7 Built-in은 일관성을, local extension은 자율성을 제공한다

자주 쓰는 signal transform, exposure analysis, portfolio diagnostics, artifact validation과 reporting은
deterministic built-in으로 제공한다. Agent마다 같은 helper를 다르게 다시 만드는 일을 줄이고 공통 vocabulary를
제공하기 위해서다. Built-in은 계산 기능뿐 아니라 valid config, typed input/output, expected diagnostic과
failure behavior를 보여주는 executable example 역할도 한다. Agent는 이 예시와 extension contract를 함께 사용해
더 정확하게 compatible한 local extension을 작성할 수 있어야 한다.

사용자 고유의 signal model과 alpha logic은 project가 소유한다. **Project-local Strategy가 alpha logic의
primary extension point**다. 사용자는 installed vqapr 또는 `site-packages`를 수정하지 않고 compatible한 local
Python implementation을 작성·검증·등록할 수 있어야 한다. Model이나 deterministic materialization은 그
Strategy가 reusable intermediate data를 요구할 때 선택하는 optional component이며 direct Strategy의 선행 조건이
아니다.

vqapr는 각 extension point에 대해 다음을 제공한다.

- Public input/output contract
- Machine-readable requirement와 schema
- Built-in과 같은 contract를 따르는 minimal working template와 executable sample
- Validation command
- Stage-specific error와 bounded offending example

vqapr가 reference/sample component를 제공할 수는 있지만 project-owned proprietary alpha를 package built-in에
가두지 않는다.

### 2.8 연구는 누적되어야 한다

성공한 trial만 남기면 같은 실패와 중복 hypothesis를 반복한다. vqapr는 성공, 실패, unsupported result,
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
-> minimal logical dataset registration
   |-> Strategy: decision result
   |-> Model: feature / characteristic / factor / stored signal
                 -> Strategy: decision result
   |-> existing Strategy results -> Ensemble Strategy -> combined result

research-only result -> analysis / report / later Strategy reuse

executable Strategy result
   -> mandatory portfolio construction
   -> frozen intended portfolio
   -> execution-time order conversion
   -> selected academic or physical execution profile
   -> fills -> committed account state -> valuation -> feedback

stored results -> analysis / report / later Strategy reuse
actual account -> independent constraint monitoring
```

Model-only와 non-portfolio analysis는 execution 없이 완결될 수 있다. 그러나 새로운 portfolio return, NAV, PnL
또는 turnover를 만드는 run은 portfolio construction 이후의 공통 lifecycle을 우회할 수 없다. Academic
long-short와 physical long-only는 서로 다른 lifecycle이 아니라 같은 lifecycle에 서로 다른 profile을 적용한
결과다. Artifact가 이미 존재하고 identity와 compatibility가 맞으면 upstream producer를 다시 실행하지 않는다.

### 3.2 Semantic roles and result categories

#### Materialized research data

반복 사용을 위해 저장한 derived research data다. Signal, label, factor return, factor exposure, covariance와
rolling risk estimate는 서로 다른 semantic category이며 각자 axis, unit, time semantics와 compatibility를
선언한다.

Statistical factor-return estimate는 regression specification과 input data를 dependency로 가져야 한다. 반면
실제 factor portfolio의 수익률을 담은 materialized data는 그것을 산출한 execution과 actual state를 dependency로
가져야 한다. 두 result를 같은 category로 표시하거나 산출 경로 없이 portfolio return 시계열을 등록하지 않는다(§4.6).

#### Stored signal

Feature, prediction, score 또는 factor value와 같은 reusable instrument/time information surface다. 최소한
signal semantics, axis, unit, direction, availability, coverage, producer와 input lineage를 포함한다. Factor
return처럼 axis와 경제적 의미가 다른 derived data를 signal로 가장하지 않는다. Signal은 portfolio weight를
의미하지 않는다.

#### Signed alpha-weight result

하나 이상의 stored signal 또는 compatible materialized research data와 bounded input을 소비해 만든 portfolio
intent다. Decision time별 instrument signed weight와 budget semantics를 포함하며 weight가 raw, active,
benchmark-relative 또는 physical인지 명시해야 한다.

Actual holding이나 prior execution feedback에 의존해 생성된 weight는 path-dependent다. 이러한 result도 frozen
typed input으로 재사용할 수 있으며 run identity, 실제로 의존한 actual state와 strategy state의 identity, 어떤
committed outcome까지 반영했는지와 execution profile을 기록해야 한다. 다른 Strategy나 Ensemble이 이를 소비하는 것은 저장된 alpha intent를 입력으로
사용한다는 뜻이지, 그 producer가 consumer의 현재 state에서 재실행되었음을 뜻하지 않는다. 이후 executable target이나
order를 만들 때는 별도 downstream operation이 현재 committed Account와 현재 execution input을 사용한다.

#### Ensemble result

여러 stored alpha-weight results를 member lineage와 함께 소비해 만든 combined signed weights다. Member
weighting, netting, crossing, residual과 normalization을 명시한다.

#### Frozen intended portfolio

Strategy result, portfolio construction rule, budget, benchmark와 필요한 제약을 반영해 실행 전에 동결한
instrument/cash target이다. Academic signed target과 physical long-only target 모두 이 category를 사용한다.
이 결과는 아직 order, Fill 또는 actual holding이 아니다.

#### Constraint declaration

선택한 workflow에 적용할 versioned limit intent다. MVP declaration은 no-short와 time-varying single-name cap의
metric, bound와 scope만 다룬다. Evaluator가 필요한 benchmark data와 clock은 그 workflow를 호출할 때 요구한다.

#### Constraint-adjustment result

Proposed target 또는 order를 actual pre-trade state와 declared constraint에 맞게 best-effort로 조정한
결과다. Original/adjusted intent, hypothetical post-trade state, constraint별 before/after value, adjustment
method/status와 unresolved residual을 보존한다. Result가 존재한다는 사실은 compliance를 보증하지 않는다.

#### Requested orders and conversion evidence

Physical target, actual holding, cash, price, lot와 tradability를 사용해 만든 requested orders와 instrument별
conversion, rounding, clipping, skip/failure reason이다.

#### Pre-execution validation finding

최종 제출 후보 target/order를 독립적으로 평가한 advisory result다. Constraint별 measured value, bound, excess,
`passed`/`compliant` status와 exact input lineage를 포함한다. Current MVP는 breach를 기록한 뒤 같은 candidate의
execution을 계속하며 profile별 blocking switch를 두지 않는다. Required input 부재나 evaluator 계산 실패는 finding이
아니라 execution 시작 전 structured operation error다. Blocking, severity와 override policy는 future work다.

#### Actual-account monitoring finding

Confirmed fill 이후 actual Position, cash와 account snapshot을 monitoring time에 평가한 결과다. MVP constraint별
breach, missing/unknown state와 data/account lineage를 포함한다. Monitoring finding은 account를 소급해 변경하지
않는다.

#### Bounded decision input

다음 decision에 허용된 input이다.

- Decision time과 permitted information cutoff
- Bounded observations와 stored signal references
- Universe, benchmark와 tradability view
- Actual realized Position, cash와 prior execution feedback
- Bounded strategy memory와 prior artifact references
- Trigger, finalization과 run state

#### Hypothetical academic execution result

Frozen intended portfolio를 explicit academic listing과 PIT reference price로 공통 execution lifecycle에서
평가한 결과다. Hypothetical Fill, committed hypothetical account state, financing balance, NAV, gross/net exposure,
PnL과 turnover를 포함한다. Fractional 허용 여부는 선택한 venue에서 instrument별로 결정한다. Profile의
zero-friction과 full-fill 가정 및 미모델링된 borrow·margin·lifecycle 항목을 결과에 직렬화하며, broker-confirmed
production state로 주장하지 않는다.

#### Prepared production decision — future work

향후 production integration에서 external OMS에 전달할 수 있는 immutable broker-neutral decision artifact 후보다.
MVP 계약과 acceptance 대상이 아니며, 생성만으로 authoritative strategy state를 advance하지 않는다는 경계만
future characterization으로 보존한다.

### 3.3 Alpha output과 executable Strategy output의 구분

Alpha research의 observable output은 signed weights일 수 있다. 그러나 그 표현을 execution contract로 직접
사용하지 않는다. Closed-loop execution을 선택하면 portfolio construction이 Strategy result를 frozen intended
portfolio로 확정하고, order conversion은 execution 시점의 committed state와 PIT input을 사용한다. 따라서
Strategy가 signal, score, signed weight 또는 다른 intermediate shape 중 무엇을 내는지는 향후 public API 설계에서
결정해도 downstream execution lifecycle은 변하지 않는다. 어느 경우에도 Strategy output 자체는 Fill이나
authoritative actual state가 아니다.

### 3.4 System mental model

vqapr의 product flow는 다음 다섯 질문을 구분한다.

1. 어떤 data를 언제 알 수 있었는가.
2. Model이 어떤 reusable research result를 만들었는가.
3. Strategy result가 어떤 frozen intended portfolio로 construction되었는가.
4. Execution을 선택했다면 실제로 어떤 결과가 발생했는가.
5. 어떤 input, limitation과 failure evidence가 결과를 뒷받침하는가.

Reference implementation의 lifecycle이나 default가 이 질문의 답을 대신하지 않는다. 구체적인 internal plane,
service, object와 package layout은 architecture가 정한다.

### 3.5 Canonical execution and instrument use cases

이 절의 use case는 observable product outcome과 evidence를 규정한다. 구체적인 class hierarchy, policy
ownership, event type, registry, batch representation과 validation library는 규정하지 않는다. Architecture는
각 stable use-case ID에 대해 trigger, permitted read, calculation, commit, evidence와 validation flow를
추적 가능하게 설명해야 한다.

아래 수치와 상품명은 법률 또는 시장 관행을 고정하는 선언이 아니라 deterministic characterization
fixture다. 실제 run은 선택한 venue/profile과 effective-dated policy를 기록한다.

#### Current product scope

##### UC-COST-001 — 상품과 방향에 따른 거래비용

같은 execution date의 fixture에서 삼성전자와 ETF를 같은 venue/profile로 거래한다. Equity SELL tax는
15bp, ETF SELL tax는 명시적인 0bp이며 BUY와 SELL policy가 다르다. 각 주문에는 상품과 방향에 맞는
policy가 적용되고, Fill은 total cost와 적용 policy identity를 보존해야 한다.

##### UC-COST-002 — Effective-dated 거래비용

2024년과 2025년에 서로 다른 cost policy가 등록된 상태에서 경제적으로 같은 주문을 실행하면 각
execution time에 유효한 policy가 선택되어 비용이 달라져야 한다. Fill과 run evidence는 적용한 policy
version, rule identity와 effective time을 보존해야 한다.

##### UC-COST-003 — Cost-aware cash clipping

주문 원금만으로는 전량 BUY가 가능하지만 거래비용을 포함하면 현금이 부족한 경우, actual fill quantity는
비용을 포함한 가용 현금에 맞게 줄어야 한다. Clipping에 사용한 policy와 최종 Fill 비용에 사용한 policy는
같아야 하며, requested/dealt quantity와 clipping reason을 보존해야 한다.

##### UC-COST-004 — 잘못된 비용 fallback 금지

ETF에 필요한 exact cost policy가 없고 Equity policy만 존재하는 경우, ETF가 Equity와 관련된 상품이라는
이유로 Equity policy를 암묵적으로 적용하지 않는다. Execution은 missing/unsupported policy로 실패하고 Fill
또는 account mutation을 만들지 않으며 failure evidence를 남겨야 한다.

##### UC-CLOSED-LOOP-001 — Actual execution feedback

첫 decision의 전량 Fill과 transaction cost가 commit된 뒤 다음 decision은 requested target이나 비용 차감 전
현금이 아니라 actual cash, NAV, position과 prior execution result를 소비해야 한다. MVP의 주식·ETF cash는
Fill과 동시에 결제된 것으로 처리한다.

##### UC-SCALE-001 — 대규모 횡단면 실행

약 3,000개 주식으로 구성된 일별 횡단면 universe에서 한 decision time의 주문 집합을 처리할 때 종목별
Fill과 diagnostic을 누락하지 않고 시간 축 closed loop를 유지해야 한다. Supported resource profile에서
batch와 equivalent single-name characterization의 경제적 결과가 일치해야 한다.

##### Path-dependent scenario — Actual fill에 의존하는 stop-loss

Strategy가 첫 decision에서 주식을 매수했지만 cost와 clipping 때문에 requested quantity보다 적게 체결된다.
이후 marked price가 actual entry price 대비 user-declared stop-loss threshold를 넘게 하락하면 다음 Strategy
decision은 requested target이 아니라 committed quantity와 actual fill price를 사용해 exit intent를 만든다.
첫 decision과 두 번째 decision을 날짜별 독립 weight 계산으로 대체하거나 미래 fill을 앞당겨 사용해서는 안 된다.

##### Multi-instrument scenario — 하나의 portfolio에서 여러 instrument를 함께 처리

한 Strategy가 여러 주식과 ETF를 같은 decision에서 선택하면 shared cash, instrument별 cost와 actual holding을
하나의 portfolio constraint 안에서 처리해야 한다. 종목별 requested/dealt quantity와 failure reason을 모두
보존하며, 한 instrument의 cash consumption이나 blocked execution이 다른 instrument의 결과와 다음 decision에
미치는 영향을 재현할 수 있어야 한다.

##### Multi-frequency scenario — 서로 다른 data와 decision cadence

Daily observation과 valuation을 사용하면서 monthly Strategy rebalance와 daily actual-account monitoring을
수행한다. 각 operation은 자신의 evaluation time과 permitted data cutoff를 보존하고, rebalance가 없는 날에도
valuation과 monitoring 결과를 만들 수 있어야 한다. 이 use case는 intraday order book이나 partial fill 지원을
의미하지 않는다.

##### UC-LOOKTHROUGH-001 — User Strategy의 명시적 ETF exposure 계산

Constituent A/B를 각각 50% 보유한 ETF와 A direct stock을 함께 보유해도 vqapr는 Instrument 또는 Account position만
보고 look-through를 자동 수행하지 않는다. User가 Strategy에 index/ETF constituent dataset binding과 actual account
state requirement를 명시하고 둘을 직접 consume한 경우에만 Strategy code가 constituent exposure를 계산한다.
그 Strategy는 direct stock과 ETF constituent exposure를 정확히 한 번 합산하고 physical cash/residual을 별도로
취급한다. 같은 ETF를 아무 constituent binding 없이 사용하는 다른 Strategy에서는 ETF가 opaque physical
Instrument로 남아야 한다.

##### UC-LOOKTHROUGH-002 — User Strategy의 PIT constituent consumption

ETF constituent 구성이 바뀌었지만 새 observation의 `available_at`이 decision time보다 늦으면 vqapr는
그 observation을 노출하지 않는다. Look-through를 선택한 user Strategy는 자신이 구독한 binding에서 그 시각에
읽을 수 있는 구성종목만 consume하고, snapshot 선택·coverage·stale/revision 처리와 재정규화 여부를 Strategy의
경제적 규칙으로 명시한다. vqapr가 ETF Instrument를 근거로 constituent dataset을 자동 발견하거나 latest 구성을
대입하지 않는다.

##### UC-LOOKTHROUGH-003 — Actual holding을 읽는 user recomputation

ETF와 direct stock이 체결된 뒤 가격 drift 또는 다음 rebalance가 발생하면 look-through를 구현한 user Strategy는
다음 decision에서 requested target이 아니라 그 시점에 허용된 marked actual portfolio state를 읽어
exposure를 다시 계산한다. vqapr는 계산값을 Account에 자동 주입하거나 다음 Strategy에 자동 feedback하지 않는다.
User가 결과를 publish한다면 consumed constituent binding, actual-state identity와 target/actual 구분을
lineage로 보존하며 intended exposure를 actual compliance state로 가장하지 않는다.

##### UC-ACADEMIC-001 — Signed portfolio의 명시적 가상 거래

사용자가 signed Strategy result를 academic profile로 실행하면 먼저 frozen intended portfolio를 확정하고,
execution 시점의 committed hypothetical account state와 PIT reference price를 사용해 physical profile과 같은
order → Fill → account commit → valuation lifecycle을 따른다. 선택한 academic venue는 Stock, ETF,
tracking-only Index 또는 synthetic-unit-price Factor의 listing과 instrument별 fractional/lot 규칙을 판정한다.
Fractional execution을 허용한 instrument는 signed fractional quantity를 전량 가상 체결할 수 있다.

거래비용·tax·slippage·market impact·borrow cost는 이 fixture에서 명시적인 0이고 turnover는 별도 기록한다.
Listing, exact-time price, positive NAV, compatible signed state transition 또는 supported quantity rule이 없으면
해당 rebalance 전체를 mutation 전에 거부한다. 결과는 `hypothetical`로 표시하며 broker-confirmed production
state, borrow/locate, collateral, margin 또는 executable real short capability로 주장하지 않는다.

#### Future extension characterization — current support가 아님

##### UC-FUTURE-001 — 만기 있는 증거금 계약

만기, contract multiplier와 settlement currency가 있는 Future position은 settlement time마다 variation
margin을 cash에 반영하고 만기에는 final settlement와 position 종료를 수행해야 한다. 만기 이후 주문은
거부되어야 한다.

##### UC-PERP-001 — 만기 없는 perpetual contract

Expiry가 없는 perpetual position은 정해진 funding time에 당시 관측 가능한 funding rate로 cash flow를
발생시키고 position을 유지해야 한다. 이 상품에는 expiry event나 final expiry settlement를 만들지 않는다.

##### UC-CASHFLOW-001 — 거래비용과 lifecycle cash flow 구분

Fill fee와 tax만 transaction cost로 집계한다. 향후 dividend/distribution, Future variation margin과 perpetual
funding을 지원한다면 transaction cost가 아닌 lifecycle cash flow로 별도 집계하고 Account cash/PnL에 명시적으로
commit해야 한다. 해당 data와 policy가 없으면 cash flow를 자동 추정하지 않는다.

##### UC-SETTLEMENT-001 — 주식·ETF 실제 결제주기

MVP는 주식과 ETF의 Fill 원금·비용이 즉시 cash에 반영된다고 가정한다. Unsettled cash, receivable/payable,
settlement calendar와 buying-power 차이는 future work이며 현재 결과 limitation에 즉시 결제 가정을 남긴다.

Merger, spin-off와 delisting처럼 instrument identity, tradability 또는 reference state를 바꾸는 사건의 해석과
변환은 vqapr가 아니라 security master와 ETL pipeline 책임이다. vqapr는 향후에도 그 원천 corporate action을
자체 해석하지 않고 이미 정규화된 instrument/reference data만 소비한다.

같은 frozen config와 data에서 event 순서와 결과가 재현되어야 한다는 요구는 모든 use case에 적용되는
cross-cutting invariant다. 3,000종목 실행에서 어떤 validation object를 언제 생성하는지는 architecture와
성능 검증이 결정하며 PRD use case가 특정 library나 hot-path representation을 강제하지 않는다.

## 4. Product invariants

### 4.1 Contract-owned, reference-informed

- vqapr가 product semantics, failure behavior, state authority와 artifact portability를 소유한다.
- Reference implementation의 계산 또는 구조는 source provenance와 version을 기록하고 characterization test로
  동등성이 확인된 범위에서 차용할 수 있다.
- Reference snapshot이나 차용한 산술을 갱신해도 vqapr public semantics가 암묵적으로 바뀌어서는 안 된다.
- External runtime lifecycle을 canonical execution authority로 두거나 vqapr의 PIT, actual-state와 evidence
  boundary를 우회하지 않는다.
- 같은 product contract를 만족하는 built-in과 local extension은 producer identity와 무관하게 같은 validation과
  artifact boundary를 통과한다.

### 4.2 Long-short research와 executable short를 구분한다

다음은 서로 다른 capability다.

1. Signal/prediction/label의 IC, RankIC와 rank-based diagnostic — portfolio를 구성하지 않는다
2. Execution을 거쳐 산출·저장된 return/NAV 시계열에 대한 분석 — attribution, correlation, factor
   regression처럼 기존 result를 읽으며 새 return을 만들지 않는다
3. Explicit academic listing, hypothetical Fill과 signed state-transition rule을 사용하는 가상 execution
4. Orders, production Position/Account와 actual fill을 통과하는 executable real short portfolio

첫 번째 층만 execution state를 경유하지 않는다. **새로운 portfolio return을 만드는 것은 세 번째 층부터이며,
두 번째 층은 그 이상의 층이 만든 result를 읽는 분석이다.** Quantile spread와 signed basket return처럼 basket
수익률을 뜻하는 지표는 첫 번째 층이 아니라 세 번째 층 경로로 산출한다. 세 번째와 네 번째 층은 같은
fill → commit → valuation lifecycle을 사용하되, 서로 다른 run과 명시적으로 다른 state-transition validity,
venue rule과 realism label을 가진다.

네 번째 층은 resolved instrument semantics와 execution policy가 결정한 position direction(§7.12)에 따른다.
`hypothetical_short`의 음수 position은 research 관측을 위한 committed hypothetical state이며 borrow, 담보,
차입 비용과 locate 가능성을 모델링하지 않는다. 이를 executable real short 또는 broker-confirmed production
state로 표시하지 않는다.

### 4.3 Actual state가 authority다

- Requested target은 intention이며 realized holding이 아니다.
- Constraint adjustment와 pre-execution validation은 proposed 또는 hypothetical post-trade state를 평가한다.
- Current MVP constraint validation의 breach는 advisory evidence이며 actual state도 execution failure도 아니다.
- Simulation의 다음 decision은 selected execution profile이 확정한 actual Position, cash와 dealt quantity를 본다.
- Constraint monitoring은 actual account snapshot만 authoritative compliance state로 평가한다.
- MVP에서 지원되는 order는 선택된 execution rule에 따라 전량 체결되고 주식·ETF cash는 즉시 결제된다. Partial,
  pending, cancel과 reject lifecycle은 future work다.
- Intended ledger나 prior target을 actual state처럼 사용하지 않는다.
- Monitoring finding은 prior fill을 rollback하거나 account를 소급 변경하지 않는다.

### 4.3.1 Actual state는 이력으로 관측할 수 있다

Strategy와 monitoring은 actual state를 현재 시점의 한 장면으로만이 아니라 관측 이력으로 읽을 수 있어야 한다.

- 관측 단위는 최소한 둘을 선택할 수 있어야 한다. 계좌 전체의 session 시계열(cash, NAV, 실현손익 등)과
  instrument 단위 panel(보유 수량, 진입 평단, 실현손익 등)이다.
- 소비자는 필요한 관측 항목과 범위를 선언하고, 선언하지 않은 항목은 보이지 않는다. 등록된 data 관측과 같은
  원칙이다.
- User는 actual state가 무엇을 기록할지 선택할 수 있어야 하며, 선택하지 않은 항목을 조용히 추정하거나 다른
  값으로 대체하지 않는다.
- **Stop-loss, cooldown, 연속 손실 판정 같은 규칙은 strategy state 없이 actual state 이력만으로 표현될 수 있어야
  한다.**
- **Actual state 이력 접근은 strategy state 보유 여부에 종속되지 않는다.**

#### UC-ACCOUNT-HISTORY-001 — Strategy state 없는 stop-loss

Strategy가 진입 평단과 최근 세션의 실현손익 이력을 선언해 읽고, 손실 한도를 넘은 종목을 청산 대상으로 판정한다.
이 판정에 strategy state를 사용하지 않으며, 실제로 소비한 actual-state 항목과 범위가 result의 dependency로 남는다.
선언하지 않은 항목은 읽을 수 없고, 기록되지 않은 항목을 요구하면 계산 전에 실패한다.

### 4.4 Point-in-time과 data meaning을 강제한다

모든 data consumer는 선언된 `available_at <= evaluation_time`인 observation만 사용한다. Strategy와 alpha의
evaluation time은 decision time이고, proposed target/order의 constraint adjustment와 validation은 해당
execution evaluation time, monitoring은 monitoring time이다. Actual account snapshot의 `as_of`도 evaluation
time보다 늦을 수 없다. 이 보장은 actual state가 과거 committed outcome만 담기 때문에 성립하며, 별도의 cutoff
장치를 요구하지 않는다.
vqapr가 보장하는 것은 선언된 availability의 준수다. Bundled agent skill은 source와 data category에 맞는
availability candidate와 근거를 제시해야 하고, source의 실제 경제적 공시 시점에 대한 최종 확인은 user가
내린다. 선택된 rule의 형식과 PIT 적용은 package가 deterministic하게 validation한다.

Strategy, child research, model inference와 inner execution component가 permitted cutoff를 우회해 source를
직접 읽어서는 안 된다.

Compliance evaluator는 strategy가 소비하지 않는 independent registered data를 요구할 수 있다. 그러나 그
data나 monitoring finding을 alpha/strategy input으로 자동 전달하지 않는다. 이후 trigger 또는 decision이 이를
사용하면 explicit dependency, availability cutoff와 lineage를 가져야 한다.

### 4.5 Evidence는 portable하고 producer-independent하다

Pickle, experiment-tracking run과 process memory는 유용한 internal/optional representation일 수 있지만 유일한
public result가 아니다. Standard artifact는 producer process와 implementation 없이 typed object로 load하고,
schema, semantics, compatibility와 lineage를 validation할 수 있어야 한다.

### 4.6 명시적 실패가 silent fallback보다 우선한다

다음은 같은 success type으로 숨기지 않는다.

- Tradable instrument만 남기고 target weight를 자동 재정규화
- Untradable target을 reason 없이 skip
- Solver constraint를 제거하거나 current portfolio를 target처럼 반환
- Missing analysis dependency를 warning만 남기고 required output을 생략
- Unknown field, instrument 또는 exposure axis를 임의로 제외
- Failed artifact publication을 complete로 표시
- Explicit execution과 accounting을 거치지 않고 계산한 값을 portfolio return, NAV, PnL 또는 turnover로 보고

Constraint adjustment의 unresolved residual, advisory validation breach, actual-account breach와 evaluator runtime
failure는 다른 result/status다. Adjustment result가 존재한다는 이유로 compliant success를 선언하지 않고,
advisory breach를 execution failure로 바꾸거나 actual breach를 계산 failure로 숨기지도 않는다.

### 4.7 Config는 의미를 선언하지만 의미를 대신하지 않는다

Config-driven workflow는 reproducibility를 위한 수단이다. 비슷한 field name, class path 또는 default 값이
경제적 의미를 확정하지 않는다. User-confirmed binding과 validated contract만 frozen config에 들어간다.

## 5. Product boundaries

### 5.1 vqapr가 소유하는 것

- Project initialization, config resolution과 frozen invocation
- Logical dataset registration, schema와 capability binding
- Field semantics, unit, currency, timezone, universe와 tradability distinction
- Point-in-time materialization과 bounded access
- Signal, alpha weight, ensemble, physical target와 artifact contracts
- Model result, Strategy intent, execution profile와 actual-state result 사이의 compatibility contract
- Order conversion semantics와 clipping/failure diagnostics
- Constraint declaration, best-effort adjustment, pre-execution validation과 finding contracts
- Signed alpha diagnostics와 long-only physical construction
- User Strategy가 명시적으로 구성하는 ETF/index look-through와 cash residual
- Instrument semantics, execution-policy resolution과 unsupported behavior의 명시적 실패
- Portable artifact envelope, dependency lineage, file-backed catalog와 reporting
- Trigger, finalization과 run 종료 시 결과·실패 evidence의 확정
- Dense actual-account constraint monitoring과 historical re-evaluation
- Agent-readable documentation, capability gap과 stage-based errors

### 5.2 vqapr execution runtime이 소유하는 것

vqapr-owned execution capability는 다음 product outcome을 책임진다.

- 서로 다른 observation, decision, execution, valuation과 monitoring time의 일관된 진행
- 각 evaluation time에서 `available_at` 경계를 지킨 data access
- Strategy intent, explicit hold와 execution outcome의 구분
- Requested/dealt quantity, tradability, clipping, fill과 transaction cost의 관측 가능한 결과
- Position, cash, portfolio value와 supported lifecycle cash flow의 일관된 actual state
- Committed actual-state feedback와 decision 없는 시점의 독립 monitoring
- 같은 frozen input에서 재현 가능한 diagnostics, results와 resumable progress

이를 구현하는 clock, event priority, callback, scheduler, view, execution component와 state store는 architecture가
정한다.

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
- 향후 production을 도입할 경우의 external OMS configuration과 operational approval

### 5.4 External production runtime과 OMS가 소유하는 것 — future boundary

- Broker connectivity, authentication과 secret
- Broker-specific identifier와 order type
- Order slicing, pacing, venue, retry, replace와 cancel
- Always-on scheduling, account polling과 real-time alert
- Market-session operational control, human approval와 kill switch
- Validation override approval, alert delivery와 operational remediation
- Confirmed order, fill, reject reason과 account snapshot publication

vqapr는 broker SDK wrapper나 always-on OMS가 아니다.

### 5.5 Reference implementation 사용 경계

Qlib, vn.py와 NautilusTrader는 §0.2에 선언된 산술·구조의 비교 및 차용 source다. 이들은 vqapr runtime
dependency, state authority, default project catalog 또는 workflow coordinator가 아니다. Reference-specific
object, pickle, recorder나 process-global provider는 portable vqapr artifact와 clock-bound access를 대체하지
않는다.

### 5.6 금지 behavior

- Reference implementation fork를 기본 product runtime으로 사용
- Position-direction contract 없이 negative Position을 executable short라고 주장
- Requested target을 realized holding으로 취급
- Process-global provider를 concurrent run 사이에서 무보호 mutation
- Current target을 반복 제출해 hold를 흉내 내고 price-drift rebalance 생성
- 한 decision의 order diagnostics를 마지막 한 건만 보존
- Composite account return을 signed active strategy return으로 사용
- Constraint adjustment result를 independent validation 없이 compliant로 표시
- Requested/hypothetical state를 actual compliance monitoring state로 사용
- Compliance-only data를 undeclared strategy input으로 전달
- Pickle-only result를 portable public artifact라고 주장
- 향후 Production `prepare`가 confirmed result 없이 authoritative memory를 advance

### 5.7 현재 지원 범위

Physical simulation의 현재 product scope는 주식과 ETF다. 별도 academic profile은 Stock, ETF, Index와 Factor의
hypothetical signed evaluation을 지원한다.

- Cross-sectional signed signal과 alpha research
- ML training and inference (model implementation은 project 소유, §5.3)
- Stored signal/alpha reuse와 ensemble
- Long-only enhanced-index physical portfolio
- Exact signed portfolio artifact를 사용하는 zero-friction fractional academic execution profile (§7.12)
- ETF의 physical/opaque 처리와 user Strategy가 명시적으로 PIT constituent data를 구독·소비해 계산하는 look-through
- Historical backtest와 portable research catalog
- Actual fill, marked state와 bounded strategy state에 의존하는 path-dependent Strategy
- 하나의 portfolio에서 여러 주식·ETF와 shared cash를 함께 처리하는 multi-instrument simulation
- Daily observation/valuation, 선택적인 lower-frequency decision과 독립 monitoring을 결합하는 multi-frequency workflow
- Selective decision trigger, explicit hold와 dense actual-account evidence
- Standalone best-effort constraint adjustment, advisory pre-execution validation과 independent monitoring artifacts
- MVP hard constraint인 no-short와 time-varying single-name cap
- 지원되는 order의 전량 체결과 주식·ETF cash의 즉시 결제를 가정한 simulation
- 가격 축을 갖춘 source 또는 §7.2.1로 등록한 derived unit price를 사용하는 closed-loop research

Instrument와 execution policy의 extension boundary(§7.12)는 이 범위 안에서 확장 가능해야 한다. 다만 다음은
현재 범위 밖이며 별도 product decision으로 다룬다.

- `real_short`에 필요한 borrow 가능성, 담보와 차입 비용 모델
- Margin account, leverage와 강제청산
- Perpetual/futures의 funding, 계약 단위와 expiry
- Dividend/distribution과 기타 instrument lifecycle cash flow
- Partial fill, pending/cancel order state와 실제 주식·ETF settlement cycle
- Prepared decision, external OMS reconciliation과 live production authority

§3.5의 `UC-COST-001`~`UC-SCALE-001`, path-dependent·multi-instrument·multi-frequency scenario,
`UC-LOOKTHROUGH-001`~`003`과 `UC-ACADEMIC-001`은 current product scope의 characterization과 acceptance
대상이다. `UC-FUTURE-001`, `UC-PERP-001`, `UC-CASHFLOW-001`과
`UC-SETTLEMENT-001`은 future characterization이며 현재 지원을 의미하지 않는다.

## 6. User, agent and config-driven workflow

### 6.1 Initial setup

사용자는 package를 설치한 뒤 project root에서 vqapr project를 초기화한다. Initial setup은 다음을 만든다.

- Project-owned config와 schema version
- Data, artifact, catalog와 extension locations
- Version-matched bundled agent skill을 selected coding-agent target에서 사용할 수 있게 하는 onboarding result
- Installed documentation과 capability inventory
- vqapr runtime, artifact schema와 extension-contract version information

설치 후 정상 사용에 vqapr source checkout이나 reference implementation internal 탐색을 요구하지 않는다. Sample data와 sample
components는 명시적으로 요청할 때만 project에 materialize한다.

#### Safe and idempotent onboarding

Onboarding은 project file을 소유한다고 가정하지 않는다. 실행 전에 target agent, 생성·수정할 exact path,
instruction file의 managed block, skill resource version과 validation command를 preview하는 dry-run을 제공해야
한다. 실제 적용은 다음을 만족한다.

- 기존 `AGENTS.md`, `CLAUDE.md`와 같은 instruction file을 발견하고 vqapr가 소유하는 marked block만
  추가·갱신·제거한다.
- Supported instruction file이 없으면 creation target을 preview하고 user가 creation을 요청한 경우에만 새로
  만든다.
- 같은 target과 version으로 반복 실행해도 duplicate block, duplicate skill 또는 의미 없는 diff를 만들지
  않는다.
- 여러 agent target을 선택한 경우 각 target의 변경을 독립적으로 보여주고 검증한다.
- vqapr가 생성한 skill file이 user에 의해 수정되었으면 content fingerprint 차이를 감지하고 명시적 확인 없이
  덮어쓰지 않는다.
- Update는 vqapr-owned file/block만 갱신하고 같은 skill directory의 user-owned extension file을 보존한다.
- Remove는 vqapr-owned block과 확인된 generated file만 제거하며 instruction file의 나머지 내용이나 project
  artifact를 삭제하지 않는다.
- 생성 결과에 vqapr package version, skill schema/version과 target type을 기록하고 target별 skill structure를
  validation한다.

#### Mandatory agent-skill output protocol

다음 entrypoint path는 selected target이 skill을 발견하기 위해 사용하는 **normative product contract**다.
일반적인 project directory convention이나 architecture candidate가 아니다.

- Codex target: skill directory `.agents/skills/vqapr/`, required entrypoint
  `.agents/skills/vqapr/SKILL.md`
- Claude Code target: skill directory `.claude/skills/vqapr-skill/`, required entrypoint
  `.claude/skills/vqapr-skill/SKILL.md`
- Explicit custom target root: skill directory `<user-selected-output>/vqapr/`, required entrypoint
  `<user-selected-output>/vqapr/SKILL.md`

> **확정된 최종 rename — 아직 적용하지 않는다.** 현재 package, import, CLI와 generated skill path의
> normative name은 `vqapr`다. 최종 migration 단계에서만 `vqapr`(vibe quant alpha portfolio / asset pricing
> research)로 한 번에 변경한다. 그때 위 세 path, import/CLI, artifact schema identity, installed docs와
> migration guide를 같은 change set에서 갱신한다. 그 전까지 위 `vqapr` path가 유효한 normative contract다.

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
|-> direct Strategy: signal + signed weights + research backtest
|-> model output -> Strategy: signed weights + research backtest
|-> optional Ensemble Strategy
|-> optional physical/enhanced-index construction -> selected executor
-> portable artifacts, report and catalog lookup
```

Sample은 reference journey이지 hidden built-in alpha나 mandatory starter layout이 아니다. User가 요청하지 않은
project에 자동 생성하지 않으며, 생성된 sample file은 product-owned example과 user-owned research code를
구분해야 한다. 각 단계는 public command/schema만으로 실행·검사할 수 있어야 한다.

### 6.2 Data registration journey

User 또는 agent는 source를 먼저 opaque하게 inventory한 뒤 최초 등록에 필요한 최소 의미를 binding한다.

```text
source inventory
-> bounded sample
-> instrument and available_at candidates
-> user confirmation
-> logical-key validation
-> minimal registration result
```

Agent는 field 이름만 보고 의미를 확정하지 않는다. Availability와 key 후보, warning과 unresolved limitation을
보여준 뒤 user confirmation으로 project config를 변경한다. 추가 capability는 선택한 workflow가 요구할 때 발견한다.

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

Frozen invocation은 **선택한 operation이 실제로 소비하는 것만** 완전히 resolve한다. 예를 들어 signal analysis는
dataset snapshot, availability, Strategy와 analysis config만 필요할 수 있다. Physical execution을 선택한 경우에만
instrument/exchange, target-to-order, executor, cost와 account binding이 추가된다. Constraint, ensemble, benchmark,
monitoring과 reporting도 호출한 workflow의 dependency일 때만 포함한다.

환경변수, mutable global default와 실행 시점의 암묵적 file discovery는 frozen result identity 밖에 남지 않는다.

### 6.7 Local extension configuration

Project-local extension은 user가 선택한 source, version과 validated parameter로 명시적으로 식별할 수 있어야 한다. Source를 찾거나 load할 수 있다는 사실만으로 compatibility가 증명되지는 않는다. vqapr는 다음을
deterministic하게 validation한다.

- Allowed extension boundary
- Capability and type validation
- Semantic input/output binding
- Version and source fingerprint
- Safe error classification
- Portable resolved config
- Bounded loading/initialization error와 partial registration 방지

### 6.8 Public workflow orchestration

사용자는 필요한 capability만 선택해 workflow를 구성할 수 있어야 한다.

```text
data registration
  |-> Model research and materialization
  |-> Strategy research
  |-> stored result analysis or composition
  |-> optional execution and monitoring
```

각 branch는 독립적으로 완료될 수 있으며 선택하지 않은 Model, construction, constraint, execution 또는 reporting
capability를 요구하지 않는다. 실행하는 workflow는 시작 전에 필요한 binding과 policy를 확정하고, 완료 시 typed
portable result와 terminal status를 제공해야 한다.

External experiment frontend나 model trainer를 사용할 수 있지만 data meaning, portable result, actual-state
authority 또는 closed-loop correctness를 대신하지 않는다. External run ID, pickle이나 tracking record는 vqapr
result에 dependency로 연결할 수 있지만 유일한 canonical result가 아니다.

### 6.9 Workflow completion

각 stage는 다음 중 하나로 끝난다.

- `complete`: required outputs와 validation이 모두 존재
- `incomplete`: 일부 output은 있으나 requirement 미충족
- `failed`: deterministic contract 또는 runtime failure
- `unsupported`: 선택한 component/profile이 capability를 제공하지 않음

Required output에 대한 warning-and-skip은 `complete`가 될 수 없다.

## 7. Project, data and capability contracts

이 절의 목적은 처음부터 완전한 dataset·project schema를 요구하는 것이 아니다. vqapr는 현재 작업에 꼭 필요한
semantic binding만 먼저 확인하고, 실제 Strategy나 workflow component를 호출할 때 추가 requirement를 발견한다.
등록 성공은 모든 downstream workflow와의 호환성 보증이 아니다.

Package는 deterministic validation과 structured failure evidence를 제공한다. Bundled agent skill은 그 evidence와
skill 지침을 해석해 resolution candidate를 설명하고, 경제적 의미나 data choice를 바꾸는 결정은 user에게 묻는다.

### 7.1 Package와 project 분리

Package는 validation, artifact compatibility, runtime과 built-in behavior를 제공한다. Project는 dataset binding,
Strategy 선택, execution profile과 local extension처럼 user가 선택한 의미를 보존한다. Package upgrade가 project의
경제적 결정을 암묵적으로 다시 쓰어서는 안 된다.

### 7.2 Minimal logical dataset registration

Logical dataset은 physical file과 구분되는 versioned reference다. 최초 등록은 다음 semantic role만 요구한다.

- instrument를 식별하는 field
- observation을 사용할 수 있게 된 시점을 뜻하는 `available_at` field 또는 user-confirmed availability rule
- 해당 dataset의 logical row key
- 등록할 data field의 선택

Field 이름은 강제하지 않는다. 예를 들어 `ticker`, `symbol`, `종목코드` 중 무엇이 instrument인지 user가 binding할
수 있다. 기본 instrument-time panel에서는 `(available_at, instrument)`가 null 없이 해석 가능하고 유일한지
검사한다. 같은 instrument와 time에 여러 행이 필요한 event/long-form dataset은 event ID나 sequence 같은 추가 key
axis를 선언하거나 별도 logical dataset으로 등록한다.

Registration result는 선택된 binding, 선택 field, physical source identity와 validation evidence를 보존한다.
`available_at`만 모든 dataset에 공통으로 특별 취급하는 시간 경계다. `fiscal_period`, `session_date`, `event_time`,
`revision`, `horizon_end`, unit, currency, universe coverage와 missingness는 source가 제공하는 일반 column 또는
metadata다. 이를 필요로 하는 consumer가 명시적으로 요구하고 해석하며, 아직 선택하지 않은 workflow 때문에
최초 등록을 막지 않는다. 같은 field를 research, execution, valuation 목적마다 별도 등록 role로 중복 선언하지
않는다.

`DATE`를 `available_at`으로 바로 binding할 수 있는 것은 user가 그 값이 실제 공개 시각이라고 확인한 경우뿐이다.
별도 availability field가 없다면 bundled agent skill은 data category와 source 관행에 근거한 지연 규칙 후보와
각 후보의 look-ahead 위험을 설명한다. Package가 임의의 지연을 선택하지 않으며, user가 선택한 rule만
결정적으로 validation하고 적용한다.

#### UC-DATA-001 — 최소 등록과 field-name 자율성

`DATE`, `CODE`, `VALUE`, `FISCAL_PERIOD` 컬럼이 있는 file에서 user는 `CODE`를 instrument, source rule로 확정한
`DATE`를 `available_at`, `(DATE, CODE)`를 logical key로 binding하고 필요한 data field를 선택한다. Daily close
row의 `DATE=2024-03-05`가 해당 session 종가를 뜻한다면 확정된 availability rule은
`2024-03-05 15:30 Asia/Seoul`을 만든다. `FISCAL_PERIOD`는 Strategy가 필요할 때 요구하는 일반 column이다.
Package는 field 이름을 바꾸거나 universal observation timestamp를 추가하라고 요구하지 않는다. Currency나
universe metadata가 없다는 이유만으로 이 단계가 실패해서는 안 된다.

### 7.2.1 Price axis and derived unit price

Execution을 선택한 workflow는 예외 없이 가격 축을 요구한다. vqapr에는 return-native 체결 경로가 없으며,
모든 체결과 valuation은 수량과 가격으로 표현한다.

Source가 기간 return만 제공하면, 그것을 unit price 시계열로 변환한 dataset을 등록한다.

$$
P_0 = b > 0, \qquad P_t = P_{t-1}(1 + r_t)
$$

이 값은 observed market price가 아니라 derived unit NAV다. 변환은 package operation이 아니다. Bundled agent
skill이 base $b$와 변환 가정을 설명하고 user가 확정하며, 결과 dataset은 다른 dataset과 동일한 최소 등록
계약(§7.2)을 따른다. Package는 이 변환을 위한 별도 schema, transform registry 또는 derived-binding metadata를
두지 않는다. 가격의 양수성과 체결 가능성은 execution 시점에 판정한다.

Return-native fallback은 제공하지 않는다. 가격 축 없이 portfolio 수익률을 주장하는 경로는 §4.6이 금지한다.

### 7.3 Progressive requirement discovery

Strategy, model, optimizer, report 또는 executor는 실제로 호출될 때 자신에게 필요한 capability를 선언한다. 등록된
dataset이 requirement를 충족하지 못하면 package는 해당 operation을 state mutation 전에 멈추고 structured error를
agent layer에 전달한다. 이 실패는 기존 registration 전체를 무효화하지 않는다.

Agent는 error와 skill 지침을 바탕으로 다음 후보 중 의미가 맞는 방법을 user에게 제시한다.

- 기존 logical dataset에 binding을 추가해 다시 등록한다.
- 같은 physical source를 다른 semantic contract의 새 dataset으로 등록한다.
- 필요한 field를 계산한 derived dataset을 만든다.
- requirement가 적은 다른 workflow profile을 선택한다.
- compatible local extension을 작성하고 package validation을 호출한다.

어떤 후보가 적절한지는 data의 경제적 의미와 user intent에 달려 있다. Agent가 선택을 설명하고 질문하며,
package는 선택된 결과가 requirement를 만족하는지만 deterministic하게 판정한다.

#### UC-DATA-002 — Downstream constraint workflow에서 발견된 benchmark-weight requirement

가격 Strategy는 최소 등록된 dataset만으로 실행되지만 single-name cap을 선택한 execution workflow는
execution evaluation 시점의 time-varying benchmark-weight binding을 추가로 요구한다. 해당 workflow를 처음
호출할 때 package는 requirement가 충족되지 않았음을 보고하고 execution request나 actual-state mutation을 만들지 않는다.
Agent는 benchmark dataset 신규 등록, 기존 dataset의 binding 보강 또는 constraint 없는 research 선택을 제시한다.
User 선택 후 validation에 성공하면 그 operation만 안전하게 retry할 수 있어야 한다.

### 7.4 Dependency binding

각 operation은 실제로 소비한 logical dataset, artifact와 config identity를 결과 lineage에 기록한다. 같은 source를
사용하더라도 Strategy input, compliance input과 reporting input은 서로 다른 binding일 수 있다. 등록되어 있지만
해당 operation이 읽지 않은 field나 dataset은 dependency로 기록하지 않는다.

### 7.5 Hierarchical operation error contract

모든 workflow를 하나의 거대한 표준 stage 목록에 맞추지 않는다. 실행한 operation이 자신의 stage path를 세분화해
보고하고, 사용하지 않은 optional stage는 나타나지 않는다. 예시는 다음과 같다.

- `dataset.register.key_uniqueness`
- `strategy.run.requirements.universe`
- `execution.submit.constraint_validation`
- `account.reconcile.fills`

Package error는 최소한 다음 사실을 machine-readable하게 제공한다.

- 실패한 operation과 hierarchical stage path
- 충족되지 않은 requirement ID와 bounded diagnostic
- state 또는 artifact가 commit되었는지 여부
- retry 전에 충족해야 할 precondition과 idempotency 정보
- 상관관계 추적을 위한 error identity

Resolution candidate, user에게 필요한 경제적 결정과 권장 질문은 package의 고정 error schema가 아니라 agent
layer가 skill 지침과 이 evidence를 이용해 판단한다.

#### UC-ERROR-001 — Optional stage가 없는 짧은 workflow

등록된 signal을 단순 분석하는 workflow는 model training, optimization, order와 execution stage를 생성하지 않는다.
분석 입력이 부족하면 실제 경로인 `analysis.run.requirements`에서 실패한다. 존재하지 않는 optional stage를 통과한
것처럼 보고하거나 unrelated capability를 미리 요구해서는 안 된다.

### 7.6 Point-in-time requirement

모든 consumer는 자신의 evaluation time보다 늦게 available한 observation을 읽지 않는다. 등록 단계에서는
`available_at` binding의 형식과 기본 key integrity를 검사하고, 각 workflow는 label horizon, publication delay,
revision policy처럼 자신에게 추가로 필요한 PIT requirement를 실행 시점에 선언한다.

#### UC-PIT-001 — Label horizon의 늦은 발견

Forward-return label을 만드는 model이 `horizon_end`를 요구하지만 input dataset에는 binding이 없다. Package는
model materialization 전에 실패하고 어떤 requirement가 부족한지 보고한다. Agent는 계산 가능한 derived field인지,
별도 dataset이 필요한지, model을 바꿀지를 설명해 user의 결정을 받는다. 임의의 horizon이나 delay를 채우지 않는다.

### 7.6.1 Bounded lookback

Historical data access는 선택한 operation이 선언한 exact lookback을 강제한다. Current product contract는 다음
두 종류뿐이다.

- `rows`: PIT gate를 통과한 행을 registered logical key로 결정적으로 정렬한 뒤 instrument별 최근 N행까지 반환한다.
- `calendar`: user가 명시한 timezone의 evaluation date에서 years/months/days를 달력 산술로 이동한 date의 00:00부터
  evaluation time까지 `available_at`이 포함되는 행을 반환한다. 거래일 수를 세는 `sessions` semantics가 아니다.

두 종류 모두 `available_at <= evaluation_time` 상한을 바꾸지 않고 Store query에 직접 반영한다. 전체 history를
먼저 읽은 뒤 Strategy code에서 자르는 경로를 bounded access로 간주하지 않는다. `rows`보다 적은 행만 존재하면
있는 만큼 반환하고 requested/actual count를 access evidence에 기록한다. Dataset-wide `available_at_min`만으로
instrument별 coverage를 추정하거나, row가 전혀 없는 instrument를 declared universe 없이 존재한다고 추측하지 않는다.
계산에 필요한 최소 관측치와 ragged-panel 처리 방식은 해당 Strategy의 경제적 규칙이다.

Calendar lookback은 years/months/days 중 적어도 하나가 양수여야 하고 timezone과 month-end clamp policy를 frozen
input에 보존한다. 동일 `available_at`의 순서는 registered logical key로 결정해 같은 input에서 같은 row set을 만든다.

### 7.7 Universe와 tradability

Universe와 tradability는 모든 dataset의 최초 등록 조건이 아니다. 횡단면 비교, benchmark-relative construction,
실제 주문 생성처럼 필요한 operation이 각자 coverage, membership time과 tradability requirement를 선언한다.
Unknown은 자동으로 tradable 또는 non-member로 바꾸지 않고 해당 operation의 policy에 따라 fail, exclude 또는 warn한다.

### 7.8 Market metadata on demand

OHLCV, limit, suspension, lot size와 price source는 이를 사용하는 execution 또는 analysis profile에서 요구한다.
단순 signal 연구가 사용하지 않는 market field 때문에 막혀서는 안 된다. 반대로 실제 주문 생성은 필요한 price,
lot와 tradability binding이 없는데도 추정 default로 진행해서는 안 된다. Signal 연구는 가격 없이 진행할 수
있지만, execution을 선택하는 순간 §7.2.1의 가격 축 요구가 적용된다.

### 7.9 Provider와 process isolation

Downstream consumer는 producer가 vqapr built-in, Qlib component, local Python module 또는 external process인지 몰라도
serialized result를 적합한 Python object로 읽고 schema, semantics, compatibility와 lineage를 검사할 수 있어야 한다.
Object construction 시 validation해야 하지만 구체 validation library와 object model은 architecture가 정한다.

### 7.10 Frozen invocation

한 operation이 시작되면 그 invocation이 소비하는 config, binding, data cutoff와 component identity를 동결한다.
동시 수정은 다음 invocation에만 반영한다. Failure evidence도 같은 frozen input identity를 가리켜야 안전한 retry와
비교가 가능하다.

#### 7.10.1 Incremental configuration은 frozen invocation과 충돌하지 않는다

Freeze 시점은 **operation이 시작될 때**다. 그 전에 어떤 순서로 config를 조립했는지는 규정하지 않는다.
따라서 user나 agent는 instrument와 execution assumption 같은 environment decision을 한 번에 모두 입력하지 않고
점진적으로 확정할 수 있어야 한다. Operation을 시작할 때는 그 시점까지 확정된 설정이 complete frozen input으로
고정되어야 한다.

이 요구는 PRD §1.2와 §6.2의 인터뷰 기반 onboarding에서 나온다. Agent는 "어떤 종목을 거래하나요",
"체결 가정은 무엇인가요"를 **한 번에 하나씩** 확인한다. 거대한 spec 생성자를 한 번에 채우는 표면만
제공하면 그 대화 형태를 표현할 수 없다.

다음 두 product behavior를 유지해야 한다.

- **Frozen input은 완전하다.** 이전의 mutable configuration을 암묵적으로 다시 읽지 않고, 보존된 input만으로
  실행과 재현이 가능해야 한다.
- **Run은 시작 시점의 설정을 본다.** Invocation이 시작된 뒤의 project 변경은 그 run의 instrument,
  execution assumption 또는 identity를 바꾸지 않는다(§7.10).

설정 입력을 받는 구체적인 method, builder, file format와 persistence 방식은 architecture와 public API design이
정한다. 누적 상태의 세션 간 persistence는 current requirement가 아니다.

### 7.11 Constraints are workflow capabilities

Constraint는 모든 research workflow의 선행 조건이 아니다. Constraint adjustment, pre-execution validation 또는
actual-account monitoring을 선택한 경우에만 해당 operation이 metric, bound, evaluation scope와 필요한 data를
요구한다. MVP가 지원하는 hard constraint는 다음 두 개뿐이다.

$$
w_i(t) \ge 0
$$

$$
w_i(t) \le \max\left(10\%, w_i^{index}(t)\right)
$$

첫 식은 no-short다. 둘째 식의 benchmark constituent weight는 time-varying PIT data이며 해당 constraint를 선택한
workflow가 명시적으로 구독한다. 종목이 benchmark 비구성종목임이 확인되면 $w_i^{index}(t)=0$이지만, 구성 여부나
weight data가 누락되면 0으로 추정하지 않고 constraint evaluation을 실패시킨다. 그 밖의 sector, turnover,
liquidity, leverage, gross/net exposure와 override policy는 future work다.

#### UC-CONSTRAINT-001 — Constraint 없는 signal research

사용자는 stored signal의 IC와 hypothetical long-short return만 분석한다. Portfolio constraint나 compliance dataset을
등록하지 않아도 이 workflow는 실행되어야 한다.

#### UC-CONSTRAINT-002 — Time-varying single-name cap

User가 single-name cap을 켠 뒤 physical target을 주문으로 바꾸려 한다. Execution preparation time에 사용할 수 있는 benchmark
constituent weight binding이 없으면 package는 constraint evaluation 전에 missing requirement를 보고하고 주문이나
account mutation을 만들지 않는다. Weight가 3%인 종목의 cap은 10%, 15%인 종목의 cap은 15%다.

### 7.12 Instrument semantics are selected capabilities

Instrument type, venue와 execution profile은 가능한 position direction, lifecycle cash flow, settlement와 cost policy를
결정한다. `long_only`, `hypothetical_short`, borrow-aware short와 derivative exposure를 같은 capability로 취급하지 않는다.
다만 이 의미는 해당 instrument를 실제로 연구하거나 실행할 때 요구하며, unrelated dataset registration을 막는
전역 schema가 되어서는 안 된다. 현재 지원과 future characterization은 §3.5의 stable use case로 구분한다.
현재 `hypothetical_short`는 explicit academic listing, next-session-close PIT price, zero-friction full-fill profile과
분리된 signed state ledger에서만 지원한다. Production KRX profile은 계속 long-only이며 real short capability를
추론하지 않는다.

## 8. Model and Strategy research

Model과 Strategy는 서로 다른 질문에 답한다. Model은 data에서 reusable research estimate를 만들고, Strategy는
data와 선택적인 Model result를 portfolio intent로 해석한다. 두 역할은 독립적으로 실행·평가할 수 있으며 하나의
의무적인 pipeline이나 internal class hierarchy를 공유할 필요가 없다.

### 8.1 Reusable Model research

Model은 prediction, signal, feature, firm characteristic, factor exposure, risk estimate와 statistical factor-return
estimate를 만들 수 있다. 결과는 경제적 의미, axis, unit와 time semantics가 맞는 reusable result로 저장해야 하며,
서로 다른 결과를 모두 `signal`이라는 이름으로 뭉개지 않는다.

#### Model-only scenario — Model signal을 portfolio 없이 연구

Model이 point-in-time feature로 다음 기간의 cross-sectional score를 만든다. User는 score coverage, IC와 stability를
평가하고 reusable result로 저장하지만 Strategy, target, order 또는 portfolio return을 만들지 않는다. 이 workflow는
완전한 Model research run이어야 한다.

#### Factor-return scenario — Statistical factor return과 executed portfolio return의 구분

Model이 한 시점의 cross-sectional exposure와 observed return을 사용해 factor-return regression coefficient를
추정한다. Result는 statistical estimate, regression specification, input period와 availability를 명시하며 portfolio
NAV나 executable factor return으로 표시하지 않는다. 같은 factor를 실제 portfolio로 평가하려면 별도 Strategy와
execution workflow를 선택해야 한다.

### 8.2 Strategy research

Strategy는 registered data와 compatible Model result를 소비해 signed weight, target, hold 또는 executable intent를
만든다. Deterministic rule Strategy는 Model 없이 raw registered data를 직접 사용할 수 있다. 내부에서 score를
계산하더라도 reusable signal을 publish한다면 Model result와 같은 semantic contract를 따라야 한다.

#### UC-SIGNAL-001 — Strategy 내부의 deterministic signal과 weight 조립

User는 price reversal Strategy를 선택한다. Strategy는 point-in-time price를 읽어 내부 reversal score와 signed
weight를 만들고 optional academic execution profile에서 long-short result를 평가한다. Reusable signal을 별도로
publish하지 않는다면 stored Model result나 enhanced-index portfolio를 만들지 않아도 workflow가 완결된다.

#### UC-SIGNAL-002 — Stored Model result를 여러 Strategy에서 재사용

한 Model이 monthly value characteristic을 materialize한다. Long-short research Strategy와 long-only construction
Strategy가 같은 result를 소비하되 각자 다른 weighting rule과 execution profile을 사용한다. Model은 다시 실행하지
않아도 되고, 두 Strategy result는 자신의 input dependency와 weighting semantics를 따로 보존한다.

### 8.3 Requirement discovery and compatibility

Model이나 Strategy가 필요한 label, feature, universe 또는 horizon을 input에서 찾지 못하면 §7.5 error contract로
현재 operation만 중단한다. Agent는 data 보강, derived data, 다른 component 또는 compatible local extension을
제안하고 package validation을 호출한다. 최초 dataset registration을 모든 future model에 맞게 확장하지 않는다.

### 8.4 Built-ins are examples and common vocabulary

자주 쓰는 rank, winsorization, neutralization, lag와 standardization은 deterministic built-in으로 제공할 수 있다.
Built-in은 결과 일관성을 제공하는 동시에 agent가 compatible local transform을 작성할 때 참고할 예시다. 사용자는
built-in을 조합하거나 package가 validation할 수 있는 local/external producer로 교체할 수 있다.

## 9. Alpha decision lifecycle

Alpha research의 중심 결과는 instrument별 signed weight다. Weight는 research 목적의 hypothetical portfolio에도,
다른 Strategy의 input에도, 선택한 instrument/exchange profile의 executable construction에도 사용할 수 있다. 특정
backtest나 enhanced-index 변환을 alpha lifecycle의 필수 종착점으로 두지 않는다.

### 9.1 Multiple valid entry paths

다음 경로는 모두 유효하며 서로를 선행 조건으로 요구하지 않는다.

- Strategy가 data에서 signal과 weight를 직접 만든다.
- Model이 stored result를 만들고 Strategy가 weight를 조립한다.
- Ensemble Strategy가 기존 Strategy result를 읽어 새 weight를 만든다.
- 기존 signed weight를 compatible analysis, construction 또는 execution workflow에서 재사용한다.

### 9.2 Signed alpha-weight result

Result는 decision time, instrument, signed weight와 weight semantics를 보존한다. Raw, gross/net normalized,
benchmark-relative와 physical weight는 같은 뜻이 아니므로 구분한다. Fixed/flexible budget, path dependency와 실제로
소비한 lineage는 재사용 판단에 필요한 evidence다.

### 9.3 Fixed와 flexible budget

Fixed budget은 선언한 gross/net budget을 채우는 것을 목표로 한다. Flexible budget은 약한 signal, 높은 cost 또는
risk 조건 때문에 일부를 cash/residual로 남길 수 있다. Package가 빈 weight를 자동 재정규화해 두 의미를 바꾸지 않는다.

#### UC-ALPHA-BUDGET-001 — 약한 signal의 residual

Flexible Strategy가 기준보다 강한 종목만 선택한 결과 gross budget의 40%만 사용한다. Result는 60% residual을
보존한다. Fixed-budget consumer가 이를 요구하면 자동 확대하지 않고 incompatibility를 보고해 user가 normalization
또는 다른 Strategy를 선택하게 한다.

### 9.4 Path-independent와 path-dependent alpha

Path-independent result는 동일 frozen input에서 prior holding과 fill history 없이 재현된다. Path-dependent result는
actual holding, cash, prior fill, cooldown 또는 Strategy memory에 의존한다. **두 result 모두 producer를 다시 실행하지
않고 frozen input으로 재사용할 수 있다.** Consumer Strategy는 필요한 artifact role, schema와 semantics를 선언하고
package가 이를 resolve한다. 실제로 소비한 artifact만 dependency edge가 되며 source result가 의존했던 actual
state·strategy state identity와 반영 범위는 새 result의 lineage에서도 보존된다.

이 재사용은 source result를 consumer의 현재 Account에서 다시 계산했다는 뜻이 아니다. Budget, schema 또는 semantics가
consumer 요구와 맞지 않으면 계산 전에 compatibility error로 실패한다. Compatible한 frozen alpha를 이후 physical
target이나 order로 변환할 때는 그 downstream operation이 현재 committed Account와 현재 execution input을 사용한다.

#### UC-ALPHA-PATH-001 — Path-dependent weight의 producer-independent 재사용

Turnover-aware Strategy가 account A의 actual holding과 strategy state를 소비해 path-dependent signed-weight result를
만든다. 이후 Ensemble Strategy가 이 frozen result와 다른 member result를 입력으로 조합한다. Source producer는 다시
실행되지 않고 parent result도 변경되지 않으며, Ensemble result는 consumed artifact와 source actual state·strategy
state identity 및 반영 범위 lineage를 보존한다. Ensemble weight를 account B의 executable target으로 변환하면 account B의 현재
committed holding과 현재 execution input을 사용하지만, source member가 account B에서 재계산되었다고 표시하지 않는다.

### 9.5 Research feedback와 execution feedback

Hypothetical research backtest와 MVP simulation은 selected execution profile이 만든 committed fill/account result만
다음 decision의 authoritative state로 사용한다. Strategy가 naive daily close 체결을 직접 가정하지 않는다.

### 9.6 Independent clocks

Observation, decision, execution과 monitoring evaluation time은 같을 수도 다를 수도 있다. Strategy decision이 없는
시점에도 actual account constraint를 평가할 수 있고, execution은 decision과 분리된 PIT-safe event에서 일어난다.
여기서 독립 clock은 별도 Clock object나 별도 runtime을 의무화한다는 뜻이 아니라, monitoring cadence와 frozen
evaluation time이 Strategy decision cadence에 종속되지 않는다는 뜻이다. 각 result는 자신이 평가한 instant와
permitted cutoff를 보존한다. Intraday event와 partial fill은 future work다.

### 9.7 Hold is an explicit decision

새로운 주문을 만들지 않는 `hold`도 정상적인 decision이다. Previous target을 무조건 재제출한다는 뜻이 아니며,
actual position을 그대로 관찰할지 여부는 Strategy와 execution policy가 명시한다. Pending execution state는 MVP에 없다.

### 9.8 Trigger and finalization

Calendar, data arrival, fill feedback 또는 user event가 decision을 trigger할 수 있다. 전략이 calendar cadence를
사용하면 cadence와 local decision time은 Strategy 정의에 속한다. Run 종료 시 result와 failure evidence를
확정해야 하지만, 특정 event class나 callback method는 PRD가 정하지 않는다.

Decision cadence는 strategy의 경제적 의미의 일부다. User는 strategy 정의만 읽고 그 strategy가 언제 판단하는지
알 수 있어야 하며, cadence를 확인하기 위해 실행 스크립트나 orchestration 설정을 읽어야 해서는 안 된다. 이는
strategy가 시간을 직접 진행시키거나 자신을 호출한다는 뜻이 아니다. Invocation이 시작된 뒤 과거 cadence를 바꾸거나
시간을 소급해서는 안 되며, 실행 시점 선택에 사용하는 정보는 그 시점에 관측 가능해야 한다.

판단 후보가 되는 session 목록과 open/close 시각은 선택 venue의 거래 calendar 사실이어야 하고 Strategy나 data
coverage에서 유도해서는 안 된다. Strategy는 “어떤 session마다 몇 시에 판단하는가”를 선언하지만 휴장일이나
session 자체를 만들어내지 않는다. Run은 명시적으로 동결된 session calendar 또는 선택 environment가 식별한
calendar provider의 결과를 사용한다. 특정 종목의 결측 때문에 후보 session이 사라지면 cadence 전체가 미래 정보에
오염된다. 새로운 trigger 종류는 product use case와 time semantics가 승인될 때 추가하며, 구체 scheduling API와
trigger representation은 architecture가 정한다.

#### UC-TRIGGER-001 — 선언된 decision cadence

Strategy 정의 안에서 "eligible session마다 04:00 Asia/Seoul에 판단한다" 또는 "5 eligible session마다
04:00에 판단한다"를 선언한다. Run 결과의 판단 시점은 그 선언과 frozen venue calendar의 교집합과 정확히
일치해야 한다. 같은 Strategy를 다른 기간에 실행해도 정의만 읽으면 cadence와 local time을 알 수 있다.

Daily close `2024-03-05` row는 `2024-03-05 15:30 Asia/Seoul`에 available해진다. 따라서
`2024-03-06 04:00` decision은 그 row를 읽을 수 있고, 그 decision의 next eligible close execution은
`2024-03-06 15:30`이다. `2024-03-05 04:00` decision은 같은 row를 읽을 수 없다. 04:00 timestamp가 dataset에
행으로 존재할 필요는 없다. 판단하지 않은 session은 실패가 아니라 정상적인 결과이며 재현 가능한 기록으로
남는다. Cadence 또는 local time을 바꾸면 경제적으로 다른 run으로 구분되어야 한다.

### 9.9 Parent/child research

Child research는 parent run의 frozen input과 artifact를 재사용해 대안을 평가하되 parent state를 바꾸지 않는다.

#### UC-ALPHA-CHILD-001 — 체결 규칙만 바꾼 child

Parent의 signed weight를 고정하고 next-close와 next-open 같은 두 full-fill convention을 child에서 비교한다. Model과
Strategy를 다시 실행하지 않으며 각 child는 execution assumption과 actual simulated fills를 별도 lineage로 보존한다.

### 9.10 Run 종료 결과

Run은 종료 시 최종 actual state와 최종 strategy state를 결과로 제공해야 하며, 그 결과만으로 이어지는 run을
시작할 수 있어야 한다. 이것은 중단된 run의 재개와 다르다. 중단 복구는 current scope가 아니다(§17.2).

### 9.11 Strategy state and adaptive belief update

Strategy는 이전 판단의 결과를 다음 판단으로 이어갈 수 있어야 한다.

- Strategy state의 내용과 구조는 strategy가 정하며 package는 이를 해석하지 않는다.
- Strategy state는 durable하고 portable해야 하며, 한 run의 종료 state를 다음 run의 시작 state로 사용할 수 있어야
  한다. Production에서 하루 단위로 실행하며 전날 state를 이어받는 것이 기준 사례다.
- **Strategy state의 갱신은 execution이나 fill 발생 여부에 종속되지 않는다.** 체결이 없는 세션에도, execution
  profile을 사용하지 않는 research-only strategy도 state를 이어갈 수 있어야 한다.
- Strategy state를 사용한 result는 그 사실을 드러내야 한다. 소비자가 "이 result는 data만으로 재현되지 않는다"를
  알 수 있어야 하기 때문이다.
- Strategy state는 최후 수단이다. 같은 값을 bounded lookback이나 durable artifact로 표현할 수 있으면 그쪽이
  재현 가능성이 높다.

Adaptive Strategy는 realized result나 new observation으로 belief, parameter 또는 member weight를 갱신할 수 있다.
특정 Bayesian class hierarchy를 요구하지 않고, update 전후의 state와 사용한 evidence를 비교 가능하게 보존한다.

#### UC-STATE-001 — 체결 없는 세션과 run 경계를 넘는 state 연속성

Strategy가 판단 결과를 state로 남긴다. 그 세션에 주문이 없거나 dealt quantity가 0이어도 state는 이어진다. Run이
끝나면 최종 state를 결과로 얻을 수 있고, 다음 run의 시작 state로 명시적으로 지정해 이어서 실행할 수 있다. 이때
이전 run의 state를 자동으로 선택하지 않는다.

#### UC-ALPHA-ADAPTIVE-001 — Fill 이후 ensemble belief 갱신

Ensemble Strategy가 member별 realized outcome을 받은 뒤 다음 decision의 member weight를 바꾼다. Result는 어떤
feedback까지 반영했는지 보여준다. 같은 update를 feedback 없이 재생하거나 미래 fill을 앞당겨 사용해서는 안 된다.

## 10. Ensemble and portfolio construction

Ensemble은 선택 가능한 Strategy composition이다. Portfolio construction은 Model-only 또는 non-portfolio
analysis에는 필요하지 않지만, **새로운 portfolio return이나 execution outcome을 만드는 모든 Strategy run에는
필수 경계**다. Enhanced index, academic long-short와 simple top-N long-only는 construction 규칙이 서로 다를 뿐
이 경계를 동일하게 통과한다.

### 10.1 Ensemble is a Strategy

Ensemble Strategy는 기존 Strategy 또는 signed alpha-weight result를 member로 불러와 combine, netting과 crossing을
수행한다. Member producer가 direct Strategy인지 stored model output을 소비했는지는 ensemble의 public contract가 아니다.

#### UC-ENSEMBLE-001 — 기존 Strategy result의 조합

Value와 momentum Strategy의 signed weights를 저장한 뒤 ensemble이 두 result를 읽어 ticker-level netting을 한다.
한 member의 long과 다른 member의 short가 상쇄된 수량, 최종 signed weight와 member lineage가 확인 가능해야 한다.

### 10.2 Mandatory construction boundary for executable runs

Strategy result는 academic signed, long-only physical 또는 benchmark-relative enhanced-index construction으로
변환할 수 있다. 어떤 규칙을 선택해도 실행 전에 budget, direction, instrument/cash target과 source lineage가
동결된 intended portfolio를 만든다. Strategy result나 raw weight를 execution profile에 직접 제출하지 않는다.
Derivative portfolio는 future work다.

#### UC-PORTFOLIO-001 — 같은 alpha의 서로 다른 portfolio use

같은 signed alpha result를 academic long-short construction과 equity long-only enhanced-index construction에
사용한다. 두 workflow는 서로 다른 investability, direction, budget과 cost requirement를 발견해 각각 frozen
intended portfolio를 만든다. 이후에는 같은 order conversion, fill, commit, valuation과 feedback lifecycle을
따른다. Alpha result 자체를 어느 한 portfolio 의미로 다시 쓰지 않는다.

### 10.3 Constraint adjustment and validation

Constraint adjustment는 proposed intent를 가능한 범위에서 수정하고, validation은 최종 candidate가 limit을 만족하는지
독립적으로 판정한다. Adjustment result가 있다는 사실만으로 compliance를 보증하지 않는다. Current MVP validation은
advisory이므로 `passed=false` finding도 기록한 뒤 같은 candidate의 execution을 계속한다. Missing benchmark처럼
평가 자체가 불가능한 경우에만 execution 시작 전에 operation이 실패한다. 이 workflow를 사용하지 않는 research에는
constraint declaration을 요구하지 않는다.

#### UC-CONSTRAINT-ADJUST-001 — 조정 후에도 남은 single-name breach

Single-name cap을 맞추려 target을 줄였지만 lot rounding 때문에 작은 breach가 남는다. Result는 original/adjusted
intent와 residual을 보여주고 validation은 `passed=false`와 exact excess를 별도 finding으로 남긴다. Current MVP는
이를 성공한 adjustment나 compliant result로 위장하지 않지만 같은 candidate의 execution을 계속한다.

### 10.4 Budget and residual evidence

Portfolio result는 requested budget, realized gross/net exposure, cash/residual과 중요한 clipping reason을 보여준다.
세부 optimizer variable, solver class와 internal batch layout은 architecture와 implementation이 결정한다.

### 10.5 ETF look-through는 user-authored Strategy behavior다

ETF look-through는 ETF position에서 자동으로 발생하는 package behavior가 아니다. ETF registration, 보유 수량 또는
constituent dataset이 존재한다는 이유만으로 look-through를 켜지 않는다. User Strategy가 PIT constituent data와
actual portfolio state를 명시적으로 선택하고 자신의 경제적 규칙으로 계산할 때만 look-through result가 존재한다.
이를 선택하지 않은 Strategy에서 ETF는 독립 physical instrument로 남는다.

Constituent data는 source identity, `available_at`, instrument/constituent identity와 weight unit을 표현하는
user-provided PIT data다. Mapping, coverage, stale/revision 처리, normalization과 cash residual의 경제적 의미는
Strategy가 소유한다. vqapr는 ETF ticker를 근거로 dataset을 자동 발견하거나 누락된 구성종목을 추정하지 않는다.

User Strategy가 decision time $t$의 actual portfolio state에서 만든 physical weight를 $p_t$, 자신이 consume한 구성종목
데이터로 만든 mapping을 $L_t$라고 하면 constituent exposure 계산은 예를 들어 다음 관계를 사용할 수 있다.

$$
x_t = L_t p_t
$$

이 식은 vqapr의 내장 ETF semantics가 아니라 Strategy가 선택할 수 있는 계산 예시다. Strategy가 이 방식을
사용한다면 direct stock과 ETF constituent exposure를 중복 없이 결합하고 그 계산 rule을 result에 남겨야 한다.

vqapr는 mapping을 만들지 않으므로 누락분을 자동 재정규화하거나 complete/partial/opaque policy를 대신 선택하지
않는다. User Strategy가 complete coverage를 요구하면 자신의 calculation/validation에서 실패시키고, partial을
허용하면 mapped/unmapped exposure와 limitation을 자신이 만든 result에 남긴다. Cash와 lot/cost clipping residual을
constituent exposure로 볼지도 Strategy의 경제적 정의지만, Account는 이를 physical cash로만 제공한다.

Look-through를 이용한 construction이 필요하면 user Strategy가 desired exposure, benchmark, constituent data와
marked actual portfolio state를 소비해 physical target이나 constraint input을 만든다. Product-provided construction은
ETF를 발견해 mapping을 자동 주입하지 않고 전달받은 explicit input만 처리한다. Expected cost는 target 선택을 위한
assumption일 뿐 actual transaction cost가 아니다.

User Strategy가 target/actual look-through를 publish한다면 둘은 다른 result여야 한다. Target은 construction intent를
설명하고 actual은 committed Fill 이후의 marked actual portfolio state로 다시 계산한다. vqapr는 그 result를 자동
생성·소비하지 않지만 result dependency는 실제로 읽힌 constituent data, actual state와 cutoff를 보존한다.

## 11. Path-dependent execution and signed compatibility

Executable Strategy run은 frozen intended portfolio를 만든다. Order conversion은 그 결과와 execution 시점의
committed account state, instrument rule과 PIT market input을 사용해 physical order를 만든다. 선택한 execution
profile은 market/fill assumption에 따라 Fill을 만들고, compatible state-transition rule을 통과한 Fill만 account에
atomic하게 commit한다. MVP simulation은 지원되는 order를 선택한 가격에 전량 체결하고 주식·ETF cash를 즉시
결제한다. Intraday order book/data, partial fill과 production integration은 future work다.

### 11.1 Closed-loop authority

Simulation의 authoritative state는 committed fill, cost, cash와 position이다. Requested order나 target은 realized
state가 아니며, 다음 decision에는 committed simulation result만 feedback한다.

#### UC-EXEC-001 — Decision과 MVP simulation execution의 분리

Strategy result나 frozen intended portfolio가 존재한다는 사실만으로 Fill이 생기지 않는다. 선택한 MVP execution
profile은 next daily close 같은 PIT-safe convention에서 execution-time order conversion을 수행한 뒤 지원되는
order를 전량 체결하고 cost와 즉시 결제 cash를 committed state에 반영한다. Academic과 physical profile 모두
같은 단계와 결과 lineage를 제공해야 한다.

### 11.2 Execution profile defines realism

MVP의 academic/hypothetical과 daily-bar physical simulation profile은 fill timing, tradability, direction,
instrument별 quantity granularity와 cost capability를 각자 선언한다. Account state-transition validity는 선택한
run이 음수 position을 허용하는지 여부만 판정하며 fractional 또는 lot quantity를 결정하지 않는다. Package 이름만
보고 현실성을 과장하지 않으며 result에는 full-fill과 instant-settlement 가정을 포함한 선택 profile의 limitation을
표시한다. Intraday simulation과 external OMS profile은 future work다.

#### Execution profile은 서로 다른 경제적 의미를 보존한다

Daily physical simulation과 academic hypothetical execution은 **같은 request/fill/commit/mark lifecycle**을
공유하지만 같은 realism을 가진 것으로 취급하지 않는다. 각 profile은 supported instrument, permitted direction,
instrument별 quantity semantics, fill timing, cost, cash treatment와 limitation을 독립적으로 선언한다. 각 run의
state-transition validity는 시작 시 동결되며 중간에 long-only와 signed 사이를 바꿀 수 없다. User는 invocation마다
compatible profile을 선택할 수 있어야 하며, profile을 교체해도 frozen intended portfolio의 의미를 암묵적으로
다시 쓰지 않는다.

이를 구현하는 base class, generic type, subclass, dependency injection과 plugin mechanism은 architecture와 public API
design이 정한다.

#### UC-EXEC-002 — Daily close engine의 명시적 한계

Daily close profile은 결정 당일 종가를 무조건 알고 체결한 것처럼 처리하지 않는다. Decision cutoff와 선택한 fill
timing이 PIT-safe인지 validation하고, volume impact, partial fill과 실제 settlement cycle을 모델링하지 않았다는
limitation을 남긴다.

### 11.3 Order conversion and evidence

실제 주문을 만드는 workflow는 frozen intended portfolio, execution 시점의 committed holding/cash, instrument
rule, price와 tradability를 사용한다. Strategy가 요구한 data와 execution profile이 요구한 data는 각각 명시적으로
resolve하며, purpose-specific registration alias를 통해 암묵적으로 선택하지 않는다. 필요한 binding이 없으면 §7의
progressive error로 mutation 전에 멈춘다. Fractional 허용, lot rounding, clipping, skip, rejection과
requested/dealt quantity는 instrument별 결과에서 확인 가능해야 한다.

### 11.4 Product and direction compatibility

Long-only equity, hypothetical short, borrow-aware short, future와 perpetual은 다른 execution capability다. 선택한
instrument/execution profile이 허용하지 않는 방향이나 lifecycle을 조용히 근사하지 않는다. 거래비용, cash clipping과
lifecycle behavior의 기준 사례는 §3.5 `UC-COST-*`, `UC-CLOSED-LOOP-001`과 future characterization을 따른다.

### 11.5 Monitoring without a decision

Constraint monitoring은 Strategy decision cadence와 독립적으로 committed actual account를 관찰할 수 있어야 한다.
User가 committed state와 frozen evaluation time을 선택해 monitoring을 실행하면, 새 decision이나 order가 없는
날에도 finding을 만들 수 있어야 한다. Monitoring finding은 계좌를 수정하거나 과거 fill을 rollback하지 않는다.
구체 public method와 automatic scheduling 여부는 public API와 architecture가 정한다.

#### UC-EXEC-003 — No-trade day의 actual constraint breach

가격 변화로 한 종목의 actual weight가 그 시점의 $\max(10\%, w_i^{index}(t))$ cap을 넘었지만 Strategy decision은
없다. Monitoring은 actual snapshot과 available benchmark weight를 사용해 breach를 기록한다. 새 order가 없다는
이유로 finding을 누락하지 않는다.

## 12. Research workspace, artifact graph and catalog

의미 있는 dataset, signal, weight, decision, execution result와 analysis는 producer와 process를 넘어 읽을 수 있는
versioned artifact로 보존한다. Workspace와 catalog의 목적은 class hierarchy를 노출하는 것이 아니라 재현, 비교,
lineage와 safe reuse를 가능하게 하는 것이다.

### 12.1 Typed and portable artifacts

Serialized data는 적합한 Python object로 읽을 수 있어야 하며 object 생성 시 schema와 semantic invariant를
validation한다. Unknown type/version, invalid key 또는 incompatible semantics를 raw dictionary로 통과시키지
않는다. Validation library와 internal object model은 architecture가 정한다.

#### UC-ARTIFACT-001 — External producer round-trip

외부 process가 documented artifact schema로 signal을 저장한다. vqapr는 이를 typed object로 읽고 local Strategy에
전달한다. Producer의 internal Python class를 import하지 않아도 compatibility와 lineage를 검사할 수 있어야 한다.

#### UC-ARTIFACT-002 — Invalid serialized result 거부

Weight artifact의 logical key가 중복되거나 declared semantics와 payload가 맞지 않는다. Object construction 또는
publication이 실패하고 invalid artifact는 catalog의 reusable success로 노출되지 않는다.

### 12.2 Dependency graph and identity

Artifact는 실제 input artifact/data/config와 producer identity를 가리킨다. 같은 frozen identity와 compatible output이
이미 있으면 재사용할 수 있고, input이나 semantic contract가 달라지면 별도 result로 취급한다. Content hash만 같다는
이유로 서로 다른 경제적 의미를 합치지 않는다.

### 12.3 Publication and failure evidence

Publication은 payload와 metadata가 함께 durable하게 commit되었을 때만 성공한다. Partial write는 reusable artifact로
보이지 않아야 한다. 실패한 research도 error identity, stage path, frozen inputs와 log reference를 남겨 agent가 다음
action을 제안하고 안전한 retry 여부를 판단할 수 있게 한다.

#### UC-RESEARCH-001 — 실패를 보존한 뒤 보강해 retry

Strategy가 benchmark-weight requirement 부족으로 실패한다. Catalog는 성공 result 대신 failure evidence를 남긴다.
User가 benchmark data를 등록한 뒤 새 invocation이 이전 error와 resolution lineage를 연결해 성공하며, 실패 기록을
삭제하지 않는다.

### 12.4 Workspace autonomy

Project는 supported local 또는 external storage option을 선택할 수 있다. Storage option이 달라도 artifact identity,
validation, durability와 observable publication outcome은 같아야 한다. Locking, database schema, payload format와
directory layout은 architecture가 결정한다.

## 13. Analysis, reporting and extensibility

Analysis와 reporting은 stored result를 소비하는 workflow다. 결과를 다시 계산하거나 account authority를 바꾸지 않고,
사용한 artifact와 limitation을 추적 가능하게 보여준다.

### 13.1 Analysis and reporting scenarios

#### UC-REPORT-001 — 같은 result의 여러 renderer

하나의 backtest result를 table, chart와 machine-readable report로 표현한다. Renderer가 달라도 return, cost, exposure와
failure count의 underlying value와 lineage는 같아야 한다.

#### UC-MONITOR-001 — Monitoring finding report

Actual-account finding을 daily report로 만든다. Report는 breach와 missing input을 구분하고, intended target을 actual
holding처럼 섞지 않는다.

### 13.2 Deterministic built-ins

자주 쓰는 signal transform, exposure analysis, portfolio diagnostic, artifact validation과 reporting은 deterministic
built-in으로 제공한다. Built-in은 공통 vocabulary와 일관성을 제공하고, agent가 compatible local extension을 만들 때
참조할 작동 예시가 된다.

### 13.3 Local and external extensions

User는 local Python module 또는 external process로 data producer, Strategy, executor, analysis와 renderer를 확장할 수
있다. 이 중 project-owned alpha logic의 기본 경로는 local Strategy다. Direct Strategy는 Model이나 materialization을
요구하지 않으며, stored signal 또는 다른 Strategy result가 필요할 때만 typed artifact input을 선언한다. Package는
각 extension kind의 documented input/output contract와 deterministic validation을 제공한다. Agent가 validation을
호출하고 오류를 해석하지만 extension의 compatibility를 최종 판정하는 책임은 package에 있다.

#### UC-EXTENSION-001 — Agent가 만든 local transform의 검증

Built-in 예시를 참고해 agent가 project-local neutralization transform을 작성한다. Package validation이 input
requirement, PIT behavior와 output artifact를 검사한다. 실패하면 agent는 error를 설명하고 수정안을 제시하며,
성공하기 전까지 compatible component로 등록하지 않는다.

#### UC-EXTENSION-002 — Project-local Strategy의 검증과 재현 가능한 실행

Fresh installed project에서 user가 documented public contract만 사용하는 local Strategy를 작성한다. Strategy는
필요한 dataset/artifact와 output semantics를 선언하고 package validation을 통과한 뒤에만 reusable extension으로
등록된다. 이후 research 또는 daily execution은 user가 선택한 exact registered version을 사용하고 실제 dependency를
result에 남긴다. 등록 뒤 source나 contract가 바뀌면 이전 registration을 암묵적으로 latest code에 연결하지 않고
compute 전에 drift를 명시적으로 보고해야 한다. Source fingerprint, loading, repeatability check와 registration
storage의 구체 방식은 architecture가 정한다. Local code validation은 security sandbox나 dependency installer를
의미하지 않는다.

### 13.4 Agent-readable guidance

Public docs는 user가 internal class hierarchy나 private source를 읽지 않고도 supported operation, required decision,
artifact meaning과 error recovery를 이해할 수 있게 한다. Agent용 guide는 stable error ID, common resolution pattern과
built-in extension example을 포함하되 package validation을 대신하지 않는다.

### 13.5 Package-provided agent skill

Bundled agent skill은 progressive workflow를 안내한다. 등록 단계에서는 꼭 필요한 semantic choice만 질문하고,
operation error가 발생하면 package evidence를 읽어 resolution candidate와 trade-off를 user에게 설명한다. Agent는
source의 경제적 의미, availability, universe, benchmark, alpha hypothesis, risk constraint와 execution policy처럼
결과 의미를 바꾸는 결정을 임의로 확정하지 않는다.

#### UC-AGENT-001 — Availability 후보를 제시하는 질문

등록하려는 `DATE`가 관측일인지 실제 공개 시각인지 불명확하다. Agent는 미래 정보 사용이 성과를 부풀리는
look-ahead 문제를 설명하고, 실제 release timestamp field 사용, source별 확인된 지연 규칙 또는 data 보강 같은 후보를
제시한다. User가 근거와 함께 binding을 선택한 뒤 package validation을 호출한다.

## 14. Future work — Production decision and OMS boundary

이 절 전체는 MVP requirement와 acceptance 대상이 아닌 future characterization이다. 향후 production integration의
핵심 후보는 broker-neutral intent와 authoritative outcome의 분리다. vqapr가 prepared decision을 외부 OMS에
전달해도 그 시점에는 holding, cash 또는 Strategy feedback state를 advance하지 않는 방향을 검토한다.

### 14.1 Prepared decision

Prepared decision은 frozen input, intended orders/target, policy identity와 idempotency identity를 가진 immutable
artifact다. 특정 broker API object를 canonical schema로 삼지 않는다.

### 14.2 OMS acknowledgement is not a fill — future characterization

전송 성공이나 OMS 접수는 execution 완료가 아니다. Confirmed fill, rejection, cancellation과 account snapshot만
authoritative result로 들어온다. Duplicate delivery는 같은 decision을 두 번 적용하지 않아야 한다.

#### UC-PROD-001 — Partial fill 뒤 다음 decision

Prepared order 100주 중 OMS가 40주만 체결한다. 다음 Strategy decision은 requested 100주가 아니라 confirmed 40주와
actual cash를 사용한다. 남은 60주의 pending/cancel 상태가 불명확하면 추정하지 않고 reconciliation error를 낸다.

#### UC-PROD-002 — Rejected decision의 state 보존

OMS가 주문을 reject한다. Rejection evidence는 보존하지만 vqapr는 intended position을 actual로 commit하지 않는다.
Retry 여부와 order 변경은 user-selected execution policy 또는 agent-guided decision을 거친다.

### 14.3 Reconciliation and recovery — future characterization

Production reconciliation은 outbox decision, OMS result와 account snapshot의 대응을 검사한다. Missing, duplicate,
out-of-order와 conflicting result를 구분하고 state mutation 전에 bounded error를 제공한다. Storage protocol, queue와
transaction implementation은 architecture가 정한다.

### 14.4 Production monitoring — future characterization

Monitoring은 OMS-confirmed actual account를 독립 clock에서 평가한다. Strategy data binding과 compliance data binding은
같은 source를 사용할 수 있지만 실제 dependency와 cutoff는 별도로 기록한다. Finding은 alert/evidence이며 external
account를 자동 수정하는 authority가 아니다.

## 15. Acceptance criteria

Acceptance는 내부 class, stage 수 또는 storage layout이 아니라 이 PRD의 observable use case로 판정한다.

### 15.1 Progressive onboarding and data

- Fresh project에서 installed docs와 bundled skill만으로 minimal data registration을 시작할 수 있다.
- `UC-DATA-001`처럼 field 이름을 강제하지 않고 selected instrument/availability binding, logical key와 selected
  data fields만 validation한다. Universal observation timestamp나 consumer-purpose price role을 요구하지 않는다.
- Availability가 불명확하면 `UC-AGENT-001`처럼 agent가 look-ahead와 delay-rule 후보를 설명하고 user가 선택한다.
- 아직 사용하지 않는 metadata나 optional workflow requirement가 최초 registration을 막지 않는다.
- 실제 current operation의 requirement gap은 `UC-DATA-002`, `UC-ERROR-001`처럼 package error → agent 제안 →
  user 결정 → package validation → safe retry로 이어진다.
- Frozen invocation과 `available_at <= evaluation_time`을 위반하는 data access는 거부된다.
- `UC-PIT-001`의 forward-return label materialization은 계산 전에 explicit horizon을 resolve한다. 누락 시
  producer calculation이나 reusable success를 만들지 않고 failure evidence만 남긴다. Horizon 보강 뒤의 새
  invocation은 이전 failure를 dependency로 연결하고 frozen evaluation time까지 이용 가능한 label만 발행한다.

### 15.2 Research composition

- `UC-SIGNAL-001`의 direct Strategy와 `UC-SIGNAL-002`의 stored model output 경로가 모두 동작한다.
- Model-only scenario처럼 portfolio 없이 Model signal을 연구·평가·저장할 수 있다.
- Factor-return scenario에서 statistical factor-return estimate를 executed portfolio return/NAV로 표시하지 않는다.
- Signed weight는 budget semantics와 actual dependency를 보존하고 producer를 다시 실행하지 않고 재사용할 수 있다.
- `UC-ALPHA-BUDGET-001`에서 flexible residual을 fixed budget으로 자동 확대하지 않는다.
- `UC-ALPHA-PATH-001`에서 path-dependent result를 producer rerun 없이 frozen member input으로 소비하고,
  source actual state·strategy state identity와 반영 범위를 새 result lineage에 보존하며 current-state recomputation으로
  표시하지 않는다.
- `UC-STATE-001`에서 체결이 없는 세션과 run 경계를 넘어 strategy state가 이어지고, 다음 run의 시작 state는
  명시적으로 지정된다. Strategy state 갱신이 execution 발생 여부에 종속되지 않는다.
- `UC-TRIGGER-001`에서 Strategy가 선언한 cadence와 04:00 local decision time을 frozen venue calendar와 결합한
  판단 시점이 실행 결과와 일치한다. 04:00에 data row가 없어도 event는 성립하며, 판단하지 않은 session은
  실패로 기록되지 않는다.
- `UC-ENSEMBLE-001`에서 기존 Strategy result를 member로 조합하고 ticker-level netting과 lineage를 확인할 수 있다.
- `UC-PORTFOLIO-001`처럼 같은 alpha를 서로 다른 valid construction/profile에 사용할 수 있고, 각 executable
  branch가 execution 전에 frozen intended portfolio를 만든다.
- `UC-ALPHA-CHILD-001`은 같은 exact parent intent를 Strategy/Model 재실행 없이 next-close와 next-open
  child에서 실행한다. 각 child는 별도 actual state, schedule/profile/convention, PIT price binding과 Fill
  dependency를 가지며 parent result는 불변이다. Adaptive scenario는 `UC-ALPHA-ADAPTIVE-001`의 state/evidence를
  별도로 만족한다.

### 15.3 Construction, execution and monitoring

- Constraint가 없는 research는 `UC-CONSTRAINT-001`처럼 실행되고, constraint workflow는 필요한 data를 호출 시점에
  발견한다.
- Academic long-short, peer momentum, top-N long-only와 enhanced index처럼 executable한 모든 Strategy는
  construction 규칙이 달라도 frozen intended portfolio → execution-time order conversion → selected profile →
  Fill → account commit → valuation → feedback의 같은 observable lifecycle을 따른다.
- MVP constraint는 no-short와 `single-name weight <= max(10%, index constituent weight)`뿐이며 benchmark weight는
  execution evaluation time에 available한 time-varying data를 사용한다.
- Adjustment와 advisory validation은 `UC-CONSTRAINT-ADJUST-001`처럼 single-name residual과 compliance finding을 구분하며, breach만으로 execution을 차단하지 않는다.
- `UC-EXEC-001`에서 Strategy decision과 selected full-fill·instant-settlement MVP execution outcome을 분리하고
  committed result만 다음 decision에 feedback한다.
- `UC-EXEC-002`는 fill timing과 model limitation을 명시하며 look-ahead를 허용하지 않는다.
- Fractional/lot quantity는 selected venue가 instrument별로 결정한다. Account validity는 signed 또는 long-only
  position transition만 검사하며 두 profile에서 같은 atomic commit/history/valuation 결과 shape를 사용한다.
- §3.5의 `UC-COST-001`~`UC-COST-004`, `UC-CLOSED-LOOP-001`, `UC-SCALE-001`과
  `UC-LOOKTHROUGH-001`~`003` current-scope outcome을 만족한다.
- Path-dependent, multi-instrument와 multi-frequency scenario에서 actual-state-dependent
  decision, shared portfolio state와 independent cadence를 검증한다.
- `UC-ACCOUNT-HISTORY-001`처럼 strategy state 없이 actual state 이력만으로 stop-loss와 cooldown 규칙을 표현할 수
  있고, actual state 이력 접근이 strategy state 보유 여부에 종속되지 않는다. 계좌 전체 session 시계열과 instrument
  단위 panel을 선택해 구독할 수 있다.
- `UC-EXEC-003`처럼 Strategy decision이 없는 evaluation time에도 actual-account monitoring finding을 만든다.
- Unsupported short, lifecycle 또는 cost policy를 다른 profile의 default로 조용히 대체하지 않는다.
- Partial fill, pending/cancel, 실제 주식·ETF settlement cycle과 production OMS behavior를 current support로 표시하지 않는다.
- Portfolio return, NAV, PnL과 turnover는 explicit execution/accounting 경로에서만 산출되며 signal 분석 result는 이
  수치를 포함하지 않는다(§4.2, §4.6).

### 15.4 Artifacts, reports and extensions

- `UC-ARTIFACT-001`처럼 producer의 private class 없이 serialized result를 typed Python object로 읽고 validation한다.
- `UC-ARTIFACT-002`의 invalid payload와 partial publication을 reusable success로 노출하지 않는다.
- Failure와 retry history는 `UC-RESEARCH-001`처럼 queryable evidence로 남는다.
- `UC-REPORT-001`, `UC-MONITOR-001`에서 stored result를 재실행 없이 report하고 actual과 intended state를 구분한다.
- `UC-EXTENSION-001`에서 agent는 built-in 예시로 local transform을 만들 수 있고 package가 compatibility를
  deterministic하게 판정한다.
- `UC-EXTENSION-002`에서 installed project의 local Strategy를 documented public contract로 검증·등록하고
  user-selected exact version으로 실행하며 source drift와 implicit latest selection을 compute 전에 거부한다.

### 15.5 Product acceptance inventory and implementation-status boundary

아래 legacy `GAP-*` ID는 architecture에서 사용해 온 stable cross-reference를 보존하기 위해 유지한다.
이름에 `GAP`이 포함되어 있다는 사실은 현재 구현이 미완성이라는 뜻이 아니다. PRD는 observable acceptance와
current/future scope만 규정한다. 구현 상태, public symbol, schema migration, test file과 closure evidence는
support map과 companion architecture에서 관리한다.

| requirement ID | product acceptance outcome | scope |
|---|---|---|
| `GAP-ONBOARD-001` | Installed project에서 onboarding 변경을 preview/apply/update/remove할 수 있고 product-owned 영역만 안전하고 idempotent하게 변경한다 | current |
| `GAP-TIME-001` | Source와 session timezone이 명시되며 ambiguous 또는 inconsistent timestamp는 state mutation 전에 실패한다 | current |
| `GAP-CONSTRAINT-001` | Standalone과 execution-enabled constraint evaluation이 같은 declared metric을 사용하고 advisory breach와 calculation failure를 구분한다 | current |
| `GAP-EXECUTION-PREPARATION-001` | Execution 직전의 actual state와 PIT input으로 target/order compatibility를 평가하고 required input 부재는 execution 전에 실패한다 | current |
| `GAP-EXCHANGE-BASE-001` | User가 compatible execution profile을 선택·교체할 수 있고 daily physical과 academic hypothetical semantics가 섞이지 않는다 | current |
| `GAP-LOOKBACK-001` | Exact rows/calendar lookback이 data access까지 강제되고 requested/available coverage가 evidence에 남는다 | current |
| `GAP-EXECUTION-FEEDBACK-001` | 다음 Strategy는 직전 decision 이후의 exact execution result와 requested/dealt/reason을 구분해 읽고 실제 dependency를 남긴다 | current |
| `GAP-PUBLIC-FACADE-001` | Installed package의 documented public surface만으로 Model, Strategy, composition, construction, analysis와 report workflow를 실행한다 | current |
| `GAP-PROJECT-CONFIGURATION-001` | Execution environment를 점진적으로 구성하되 시작된 run은 complete frozen input과 identity를 유지한다 | current |
| `GAP-RETURN-AUTHORITY-001` | Signal analysis는 non-portfolio diagnostic만 만들고 portfolio return/NAV/PnL/turnover는 explicit execution/accounting result에서만 나온다 | current |
| `GAP-IMPACT-001` | Market impact를 지원하려면 authoritative volume, PIT binding, price-impact semantics와 fee 중복 방지 계약을 먼저 정의한다 | future |
| `GAP-DIRECTION-001` | Academic과 physical profile은 같은 lifecycle을 사용하고, signed/long-only state validity와 venue별 instrument quantity rule 및 realism을 명시적으로 구분한다 | current |
| `GAP-REAL-SHORT-001` | Executable real short를 지원하려면 borrow, locate, collateral, margin, proceeds, recall과 fee authority를 함께 검증한다 | future |
| `GAP-MONITOR-001` | Decision이 없는 시점에도 committed actual state를 frozen evaluation time에서 독립적으로 monitoring한다 | current |
| `GAP-MATERIALIZATION-PIT-001` | Model calculation 전에 label horizon과 PIT requirement를 resolve하고 missing input은 reusable success 없이 실패한다 | current |
| `GAP-EXECUTION-CONVENTION-001` | 같은 frozen parent intent를 producer 재실행 없이 서로 다른 PIT-safe execution timing으로 비교하고 child state와 evidence를 격리한다 | current |
| `GAP-STRATEGY-COMPOSITION-001` | 여러 stored Strategy result를 producer 재실행 없이 조합하며 path-dependent source state와 feedback dependency를 보존한다 | current |
| `GAP-RECOVERY-001` | Process interruption 뒤 동일 frozen identity를 중복 decision/fill/state update 없이 재개하고 changed identity는 mutation 전에 분기 요구로 실패한다 | future (§17.2) |
| `GAP-ACCOUNT-HISTORY-001` | Actual state를 session 시계열과 instrument panel로 선언해 읽을 수 있고, 그 접근이 strategy state 보유에 종속되지 않으며, 기록하지 않은 항목은 추정 없이 실패한다 | current |
| `GAP-STRATEGY-STATE-001` | Strategy state를 package가 해석하지 않고 이어가며, 갱신이 execution 발생에 종속되지 않고, run 종료 state를 다음 run의 시작 state로 명시적으로 지정한다 | current |
| `GAP-CATALOG-001` | Concurrent publication과 process interruption에서도 partial result가 reusable success로 보이지 않고 conflict, idempotency와 recovery outcome이 결정적이다 | current local storage |

ETF look-through는 이 revision에서 `UC-LOOKTHROUGH-001`~`003`과 §10.5로 **user-authored Strategy behavior**임을
명시한다. vqapr가 제공할 current support는 user-declared PIT data consumption, actual portfolio-state 접근과 generic
result dependency이며, ETF-specific 자동 mapping/resolution/result 생성은 package scope가 아니다.

Production outbox/reconciliation과 lifecycle cash flow는 current readiness gap이 아니라 명시적인 future work다.
Merger, spin-off와 delisting의 원천 해석·변환은 security master/ETL 책임이므로 vqapr readiness gap이 아니다.

## 16. Compatibility gates and validation

Compatibility gate는 구현 구조가 아니라 기존 observable result의 의미가 보존되는지 판정한다.

### 16.1 Reference or calculation change

Reference code, borrowed calculation 또는 cost/metric rule을 바꾸면 source provenance와 영향을 받는 use-case ID를
식별한다. Frozen fixture에서 numerical result뿐 아니라 requested/dealt quantity, actual-state timing, PIT cutoff,
unsupported failure와 evidence가 이전 contract와 일치하거나 명시적으로 versioned change여야 한다.

### 16.2 Runtime or component change

Model, Strategy, execution mechanism, artifact backend나 local extension mechanism을 교체해도 다음을 재검증한다.

- same frozen input의 deterministic replay
- Decision과 full-fill MVP execution outcome의 분리 및 actual feedback
- hold/no-trade monitoring과 run 종료 결과의 이어받기
- typed artifact round-trip, failure evidence와 dependency lineage
- §3.5 stable current-scope use cases와 §15 acceptance scenario

Internal class나 callback 이름의 parity는 요구하지 않는다.

### 16.3 Schema and artifact change

Old artifact는 안전하게 읽히거나 explicit migration/unsupported error를 제공해야 한다. Schema change가 logical identity,
producer-independent loading, path-dependent source state와 반영 범위 lineage, partial publication 무결성 또는 actual/intended
state separation을 깨뜨려서는 안 된다. 여러 source state를 하나의 fabricated identity로 합쳐서도 안 된다.

### 16.4 Test philosophy

Tests는 PRD use case의 input, observable outcome, authority와 evidence를 검증한다. Prototype의 accidental class name,
private import, file layout, fixed global stage 목록 또는 특정 validation library를 제품 requirement로 승격하지 않는다.

## 17. Out of scope and roadmap

Current scope는 validated research, full-fill·instant-settlement simulation과 artifact composition이다. 다음 항목은
지원한다고 추정하지 않는다.

- Borrow, locate, margin, recall과 borrow fee를 포함한 executable real short
- Derivative margin, funding, expiry와 forced liquidation의 complete lifecycle
- Dividend/distribution과 기타 instrument lifecycle cash flow
- Partial fill, pending/cancel state와 stock/ETF 실제 settlement cycle
- Prepared production decision, external OMS reconciliation, concurrent in-flight decision과 live account authority
- Direct broker connectivity, secret management, always-on OMS/scheduler와 alert delivery
- User가 제공하지 않은 availability, universe 또는 shortability truth의 자동 추정
- Merger, spin-off와 delisting을 포함한 security-master event의 원천 해석·변환
- Unbounded autonomous Strategy state mutation

### 17.1 Asset-class expansion scenarios

새 asset class는 type label 추가로 완료되지 않는다. Quantity/notional, valuation, permitted direction, cost, settlement와
actual feedback이 closed loop에서 일관되게 작동해야 한다. `UC-ACADEMIC-001`은 공통 lifecycle 안의 별도
hypothetical run/state와 명시적 한계로 current scope다. `UC-FUTURE-001`, `UC-PERP-001`과
`UC-CASHFLOW-001`은 future characterization이며
current support claim이 아니다.

### 17.2 Optional future capabilities

Real short, derivatives, lifecycle cash flow, actual settlement, partial fill, alternative optimizer, AI-assisted Strategy,
distributed execution과 production integration은 독립적인 product decision으로 추가할 수 있다.

중단된 run의 재개도 여기에 속한다. 실패하거나 중단된 run은 current scope에서 처음부터 다시 실행한다. 장시간 run
이나 production 연속 운영에서 재개 수요가 검증되면 별도의 product decision으로 추가한다.

각 확장은 새
requirement를 해당 workflow에서 발견하고,
기존 minimal registration이나 unrelated research를 막지 않아야 한다. 구체적인 component hierarchy와 service topology는
architecture가 정한다.

## 18. Product-level conclusion

vqapr는 하나의 고정 research pipeline을 강제하지 않는다. 최소한의 semantic binding으로 시작하고, 선택한 workflow가
필요로 하는 requirement를 실행 시점에 발견하며, package의 deterministic error와 validation을 agent가 user decision으로
연결한다.

제품이 보존해야 할 핵심은 다음과 같다.

- Data availability, evaluation cutoff와 exact `rows`/`calendar` lookback의 PIT integrity
- Direct Strategy, stored model output와 ensemble Strategy의 선택 가능한 composition
- Path-dependent Strategy, multi-instrument portfolio와 multi-frequency workflow
- Hypothetical, long-only, long-short와 enhanced-index workflow의 명시적 의미
- Model result, Strategy decision과 selected execution outcome의 의미상 분리
- Simulation Account에 commit된 actual result의 authority
- Producer-independent typed artifacts, lineage, failure evidence와 safe reuse
- Decision과 독립적인 actual-account monitoring

Reference implementation, specific class hierarchy, global stage enum, storage backend와 validation library는 이
의미를 구현하는 수단이지 PRD의 목적이 아니다. Architecture는 stable use case마다 trigger, permitted input,
state transition, evidence와 validation을 추적 가능하게 설명해야 한다.
