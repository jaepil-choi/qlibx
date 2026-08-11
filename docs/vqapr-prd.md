# vqapr Product Requirements Document

Status: canonical product authority
Package / import / CLI name: `vqapr`
이름: **v**ibe **q**uant **a**sset **p**ricing / **a**lpha **p**ortfolio **r**esearch
Companion document: `docs/vqapr-architecture.md`
Implementation status: target product contract. `src/vqapr/`는 이 문서와 companion architecture가 승인된 뒤에 만든다.

---

## 0. 이 문서를 읽는 법

### 0.1 무엇이 normative인가

이 문서의 normative 요구사항은 vqapr가 제공해야 하는 **user-visible capability, 경제적 의미, observable
behavior, correctness boundary, stored result의 의미**를 규정한다.

다음은 요구사항이 **아니다**. 명시적으로 "external product contract"라고 선언한 경우만 예외다.

- 특정 Python class hierarchy, 상속 관계, object 개수
- module path, file layout, directory 이름
- storage engine, serialization format, validation library
- 특정 method name과 signature
- process 경계와 service topology

이 문서가 `Strategy`, `Model`, `Account`, `Exchange` 같은 이름을 쓸 때는 **제품의 semantic role**을 뜻한다.
Python class를 뜻하지 않는다.

> **Architecture candidate — non-normative**
>
> 이 표기가 붙은 이름, diagram, 구조 제안은 요구사항을 만족할 수 있는 하나의 후보다. 같은 product
> semantics와 acceptance criteria를 만족하는 다른 구조를 허용한다.

### 0.2 문서 사이의 authority 관계

| 문서 | authority |
|---|---|
| 이 PRD | 제품이 무엇을 보장하는가. 충돌 시 최종 authority. |
| `docs/vqapr-architecture.md` | 그 보장을 어떤 구조로 구현하는가. |
| implementation record | 왜 그 변경이 존재하고 무엇으로 검증했는가. |

구현이 architecture와 다르면 **구현이 틀린 것이 아니라** architecture 문서가 현재 설계가 아닌 것으로 본다.
architecture가 PRD와 다르면 architecture가 틀린 것이다.

### 0.3 안정 ID

`UC-*` ID는 안정적이다. 이름을 바꾸거나 재사용하지 않는다. Architecture는 각 `UC-*`에 대해 trigger,
permitted read, calculation, state transition, evidence, validation을 추적 가능하게 설명해야 한다.
Test는 이 ID의 observable outcome을 검증한다.

---

## 1. 제품 정의

### 1.1 vqapr는 무엇인가

vqapr는 **자체 research·execution capability를 소유하는 재사용 가능한 alpha research framework**다.

quantitative researcher와 그 연구를 돕는 coding agent가 다음을 하나의 누적 가능한 환경에서 수행한다.

- project data를 의미와 point-in-time availability가 명시된 logical dataset으로 등록한다.
- Model 또는 deterministic transform이 재사용 가능한 signal, feature, label, risk estimate를 만들어 축적한다.
- Strategy가 point-in-time data와 선택적 Model result를 소비해 경제적 판단을 만든다.
- 기존 Strategy를 member로 참조하는 ensemble Strategy가 저장된 결과를 조합하고 ticker 수준에서 netting한다.
- 판단을 실행 가능한 portfolio로 확정하고, 선택한 execution profile로 closed-loop simulation한다.
- Strategy decision과 독립적으로 schedule된 시점에 actual account를 monitoring한다.
- 성공, 실패, 미지원, diagnostic과 user decision을 다음 연구의 출발점으로 보존한다.

각 capability는 **독립적으로 사용할 수 있다.** 모든 연구가 하나의 end-to-end pipeline을 끝까지 따라야
한다고 강제하지 않는다.

### 1.2 vqapr는 자체 execution engine을 소유한다

이 절은 normative이며 본문의 다른 절보다 우선한다.

vqapr는 Qlib을 backtest runtime backend로 사용하지 않는다. `pyqlib`는 runtime, test, build dependency가
아니다. historical simulation과 선택된 execution profile의 상태 전이는 vqapr가 책임진다.

자체 engine을 갖는 이유는 다음 일곱 가지 product behavior가 외부 runtime의 lifecycle 위에서는 보장되지
않기 때문이다.

1. **Path-dependent strategy.** stop-loss, cooldown, turnover-aware rebalance, adaptive belief처럼 이전의
   committed fill, realized price, actual holding, cash 또는 bounded strategy state에 따라 다음 판단이 달라지는
   전략을 지원한다. weight 벡터를 날짜별로 독립 계산하는 방식만을 backtest로 간주하지 않는다.
2. **Multi-instrument portfolio.** 하나의 run과 account에서 여러 instrument의 position, shared cash, cost,
   exposure와 cross-instrument decision을 함께 처리한다. 종목별 계산을 지원한다는 사실만으로 portfolio-level
   동시성을 충족했다고 보지 않는다.
3. **Multi-frequency workflow.** observation, model calculation, decision, execution, valuation, monitoring이
   서로 다른 cadence를 가질 수 있다. daily observation과 valuation을 쓰면서 monthly rebalance와 daily
   monitoring을 수행할 수 있어야 한다.
4. **Point-in-time correctness.** 각 판단은 자신의 evaluation time에 허용된 정보만 사용하고, 미래 observation
   이나 아직 확정되지 않은 execution result를 읽지 않는다.
5. **Closed-loop feedback.** committed execution outcome과 그에 따른 actual state가 이후 decision의 입력이
   된다. requested target이나 가상의 post-trade state를 actual feedback으로 사용하지 않는다.
6. **Deterministic replay.** 같은 frozen input, data, policy에서 판단 순서, state transition, diagnostic,
   결과가 재현된다.
7. **Lifecycle extensibility.** 새 cadence, instrument lifecycle, monitoring requirement를 추가할 때 무관한
   Model, Strategy, execution의 의미를 다시 정의하지 않는다.

이 요구는 intraday order book, partial fill, 실제 settlement 또는 모든 asset class를 현재 지원한다는 뜻이
아니다. current/future 경계는 §13이 정한다.

### 1.3 Reference implementation은 authority가 아니다

Qlib, vn.py, NautilusTrader 등은 behavior comparison, calculation characterization, 설계 검토에 사용할 수
있다. 그러나 어느 것도 vqapr의 runtime dependency, state authority, public result format, workflow
coordinator가 아니다.

reference에서 차용한 계산도 이 PRD의 correctness, explicit failure, diagnostic preservation, portable result
요구를 만족해야 한다. reference version을 바꾸거나 대체해도 vqapr의 observable semantics가 암묵적으로
달라져서는 안 된다. 구체적 source, version, license, 차용 범위와 검증 방법은 architecture와 provenance
record가 관리한다.

본문에서 이 이름들을 언급하면 comparison 또는 provenance 대상만을 뜻한다.

### 1.4 주요 사용자와 product promise

주요 사용자는 quantitative researcher와 research engineer이며, **coding agent는 이들을 지원하는
first-class user**다.

사용자는 vqapr private source나 `site-packages` 내부를 읽을 필요가 없어야 한다. 대신 결과의 의미를 바꾸는
결정 — 데이터의 경제적 의미, availability, universe, benchmark, alpha hypothesis, risk constraint, execution
policy — 은 명시적으로 내려야 한다.

정상적인 사용을 위해 agent가 package source를 열어야 한다면 그것은 **public product surface의 결함**이다.

#### UC-FACADE-001 — 설치된 package의 public surface만으로 완주

fresh project에서 installed documentation, bundled agent skill, public API/CLI만 사용해 dataset registration,
Model materialization, Strategy research, composition, portfolio construction, execution, analysis, report를
수행할 수 있다. 어느 단계에서도 package 내부 module을 import하거나 source를 읽도록 요구하지 않는다.

### 1.5 설치 직후 사용자가 표현할 수 있어야 하는 것

```text
data/의 데이터를 등록해줘.
등록된 signal로 새로운 reversal alpha를 연구해줘.
저장된 alpha들을 ensemble해서 long-only enhanced index로 backtest해줘.
이번 결과가 어떤 data와 signal에 의존하는지 보여줘.
```

---

## 2. 제품 철학

### 2.1 Signed alpha가 중심 연구 자산이다

vqapr의 첫 번째 목적은 **signed cross-sectional alpha research**다. signal이 양수와 음수를 갖고 alpha
weight가 long/short intent를 표현하는 것은 정상적인 research behavior다.

실제 borrow 가능성이나 선택한 execution profile의 long-only 제약 때문에 **research intent를 미리 long-only로
축소하지 않는다.** 운용 portfolio가 long-only여도 original signed alpha를 덮어쓰지 않는다. 실현되지 않은
short intent, constraint clipping, residual, physical mapping은 별도 evidence로 남긴다.

단순 long-only strategy와 market-timing policy도 구성할 수 있다. cross-sectional stock-picking rebalance는
중요한 research profile이지만 package가 강제하는 유일한 흐름이 아니다.

### 2.2 Return을 주장하는 모든 것은 하나의 execution spine을 통과한다

vqapr에는 두 개의 루프가 있고, 척추는 하나다.

```text
[research loop]
registered PIT data -> Model / transform -> reusable research result -> analysis / reuse
   여기서 끝나도 완결된 workflow다. portfolio return을 주장하지 않기 때문이다.

[execution spine]
Strategy decision
  -> mandatory portfolio construction
  -> frozen intended portfolio
  -> execution-time order conversion (현재 committed state + 현재 PIT input)
  -> selected execution profile
  -> fills
  -> committed account state
  -> valuation / mark
  -> feedback -> 다음 Strategy decision
```

**규칙:** 새로운 portfolio return, NAV, PnL, turnover를 만드는 모든 workflow는 이 spine을 끝까지 통과한다.
우회 경로는 없다.

이 규칙이 막는 것은 구체적이다. weight 벡터와 다음 기간 수익률을 곱해 합산한 값을 backtest 결과라고
부르는 것, quantile spread나 signed basket return을 signal 분석 결과에 포함시키는 것, 거래비용·체결
가능성·현금 제약을 통과하지 않은 수치를 성과로 보고하는 것이다. 이런 값들은 execution과 accounting을
거치지 않았으므로 **이 제품에서는 portfolio return이 아니다.**

academic long-short와 physical long-only는 서로 다른 lifecycle이 아니라 **같은 lifecycle에 서로 다른
profile을 적용한 결과**다.

### 2.3 Model과 Strategy는 분리된 semantic role이다

**Model**은 point-in-time data를 소비해 다른 연구와 Strategy가 재사용할 수 있는 research result를 만든다.
prediction, signal, feature, firm characteristic, risk estimate, statistical factor-return estimate가 대표적이다.
Model의 정상적인 종착점은 reusable result와 그 평가 evidence이며, portfolio나 order를 만들 필요가 없다.

**Strategy**는 registered data와 선택적 Model result, 필요하면 actual portfolio state와 bounded strategy
state를 소비해 경제적 decision을 만든다. deterministic rule만으로 판단하는 Strategy는 Model을 선행 조건으로
요구하지 않는다.

두 result는 경제적 의미가 다르다. **signal을 weight로, statistical estimate를 executed portfolio return으로,
intended target을 actual holding으로 가장해서는 안 된다.** 같은 구현이 내부에서 signal과 weight를 연속
계산할 수는 있지만 public result와 acceptance에서는 두 역할을 구분해야 한다. 이것은 별도 Python class나
process를 두라는 요구가 아니다.

factor return도 마찬가지로 구분한다.

- cross-sectional regression coefficient나 statistical factor estimate는 **Model result**로 만들 수 있다.
- 실제 factor portfolio의 return, NAV, PnL, turnover는 **execution spine을 거친 결과**여야 한다.

### 2.4 Committed actual state만 authority다

vqapr에는 서로 바꾸어 쓸 수 없는 두 개의 runtime authority가 있다.

1. **Account authority** — committed fill과 mark가 만든 cash, position, cost, NAV와 그 이력
2. **Strategy-state authority** — Strategy가 명시적으로 반환하고 commit한 bounded private state

나머지는 authority가 아니다. intended portfolio, requested order, constraint adjustment result, validation
finding, monitoring finding, evidence는 **의도와 영수증**이다.

따라서 다음 네 단계를 항상 구분한다.

```text
intended  ≠  requested  ≠  dealt  ≠  committed
(목표)       (주문)       (체결)     (계좌 반영)
```

- Strategy intent는 fill도 realized holding도 아니다.
- simulation의 committed fill은 현실의 체결은 아니지만 **그 run의 authoritative execution result**다.
- 다음 decision은 requested target이 아니라 committed holding, cash, execution result를 본다.
- blocked 또는 zero-dealt order를 fill로 가장하지 않으며, 다음 decision이 이를 구분해 읽을 수 있다.
- monitoring finding은 prior fill을 rollback하거나 account를 소급 변경하지 않는다.

### 2.5 Durable typed artifact가 public integration point다

signal, alpha weight, ensemble weight, intended portfolio, constraint declaration/adjustment/validation, order,
fill, position, monitoring finding, analysis table은 최종 report의 부산물이 아니라 **first-class result**다.

runtime 내부에서는 목적에 맞는 어떤 표현을 써도 된다. 그러나 다음 경우의 public contract는 versioned
portable artifact다.

- 다른 run, process, agent가 결과를 재사용할 때
- producer를 다시 실행하지 않고 downstream 작업을 할 때
- project-local code와 built-in을 연결할 때
- 실패한 run을 감사할 때
- 외부 OMS나 reporter와 통신할 때

downstream consumer는 producer가 vqapr built-in인지, local Python module인지, 외부 process인지 몰라도
schema, semantics, compatibility, lineage를 검사할 수 있어야 한다. 따라서 serialized data를 읽을 때 raw
`dict`로 넘기지 않고 **semantic role에 맞는 typed object를 생성**하며, 생성/역직렬화 경계에서 schema,
required field, type, version, cross-field invariant를 validation한다. invalid serialized state가 partially
constructed object로 runtime에 들어가서는 안 된다.

### 2.6 Package는 deterministic하고, 대화는 bundled agent skill이 담당한다

package의 계산·검증 behavior는 선언된 input을 받아 선언된 output을 만드는 deterministic library behavior다.
**user에게 질문하지 않고, 빠진 data를 비슷한 field로 대체하지 않으며, 경제적 의미를 추측하지 않는다.**

capability가 충족되지 않으면 package는 agent layer가 해석할 수 있도록 다음 사실을 machine-readable하게
보고한다.

- failure stage, stable error code, 실패한 requirement identity
- missing/invalid field, observed value shape, bounded offending example
- 어떤 validation rule 또는 compatibility condition이 충족되지 않았는가
- operation이 state를 commit했는지, deterministic retry에 필요한 precondition과 idempotency identity

package error는 **가능한 resolution이나 user에게 물을 질문을 결정하지 않는다.** bundled agent skill이
package error, skill 지침, project context, user가 제공한 의미를 함께 해석해 복수의 해결 경로를 만들고 각
경로의 가정과 trade-off를 설명한다. 경제적 의미나 authority를 바꾸는 선택은 agent가 대신 확정하지 않고
user가 판단하게 한다.

```text
deterministic package behavior
  requirement declaration -> validation -> structured failure / result

package-provided agent skill
  candidate 구성 -> 설명 -> user interview -> project 변경 -> package validation 재호출
```

package의 deterministic behavior가 agent skill을 호출하거나 대화 상태를 소유하지 않는다. skill도 package
validation을 우회하거나 missing semantics를 추측하지 않는다. **validation을 호출하는 주체가 agent여도,
deterministic하게 판정하고 machine-readable result를 반환하는 책임은 package에 있다.**

### 2.7 Built-in은 일관성을, local extension은 자율성을 제공한다

자주 쓰는 signal transform, exposure analysis, portfolio diagnostics, artifact validation, reporting은
deterministic built-in으로 제공한다. agent마다 같은 helper를 다르게 다시 만드는 일을 줄이고 공통 vocabulary를
주기 위해서다. built-in은 계산 기능이자 **executable example**이다 — valid config, typed input/output, expected
diagnostic, failure behavior를 함께 보여준다.

사용자 고유의 signal model과 alpha logic은 project가 소유한다. **project-local Strategy가 alpha logic의
primary extension point**다. 사용자는 installed vqapr나 `site-packages`를 수정하지 않고 compatible한 local
Python implementation을 작성·검증·등록할 수 있어야 한다. Model이나 deterministic materialization은 그
Strategy가 reusable intermediate data를 요구할 때 선택하는 optional component이며 direct Strategy의 선행
조건이 아니다.

각 extension point마다 public input/output contract, machine-readable requirement와 schema, built-in과 같은
contract를 따르는 minimal working template, validation command, stage-specific error를 제공한다.

vqapr가 reference component를 제공할 수는 있지만 **project-owned proprietary alpha를 package built-in에
가두지 않는다.**

#### Built-in weighting 함수는 순수하다

연구 결과를 portfolio weight로 바꾸는 계산(균등 배분, 크기 비례 배분, 예산 재조정 등)은 자주 반복되므로
built-in으로 제공한다. 이 built-in에는 다음 제약이 붙는다. 이것이 없으면 built-in은 편의 함수가 아니라
**보이지 않는 곳에서 경제적 판단을 내리는 두 번째 Strategy**가 된다.

- registered data, account state, clock, execution profile에 **접근하지 않는다.** 필요한 값은 전부 인자로
  받는다. 크기 결정에 외부 panel(시가총액 등)이 필요하면 그 panel을 호출자가 넘긴다. 그래야 그 data가
  Strategy의 declared requirement를 거쳐 §4.6의 lineage에 남는다.
- **budget을 스스로 결정하지 않는다.** 선언된 것보다 적게 배분된 결과를 자동으로 채우지 않는다(§5.5).
- **결측을 조용히 처리하지 않는다.** 요구한 부수 입력이 없으면 계산 전에 실패하고, 해당 종목을 빼고
  나머지를 재정규화하지 않는다(§10.2).
- 연구 결과 자체의 결측 해소는 built-in weighting의 책임이 아니다. 별도의 명시적 built-in으로 제공하되,
  **어떤 종목이 왜 제외되었는지가 호출자에게 값으로 반환되어** result evidence에 실릴 수 있어야 한다.
- 같은 입력에 같은 출력을 낸다. run identity, decision time, account version을 알지 못하므로 실행 가능한
  intent를 스스로 만들지 못한다. intent 조립과 lineage 기록은 Strategy의 책임이다(§6.2).

#### UC-BUILTIN-001 — Built-in weighting의 순수성과 명시적 결측 처리

user가 built-in weighting 함수로 portfolio weight를 만든다. 그 함수는 registered data, account state, clock에
접근하지 않고 전달받은 값만 사용한다. 크기 결정에 외부 panel이 필요한 함수는 선택된 instrument 중 panel에
없는 것이 있으면 **계산 전에 실패하고**, 그 종목을 빼고 재정규화하지 않는다. 연구 결과 자체의 결측은 이
함수가 처리하지 않으며 user가 명시적으로 해소한 뒤 호출한다. 어떤 종목이 왜 제외되었는지는 result
evidence에서 확인할 수 있다. 선택된 종목이 하나도 없으면 실패하지 않고 **빈 포지션 target**을 만든다(§6.7).

### 2.8 연구는 누적되어야 한다

성공한 trial만 남기면 같은 실패와 중복 hypothesis를 반복한다. vqapr는 성공, 실패, unsupported result,
diagnostic, user decision을 catalog에 남겨 다음 연구의 출발점으로 쓴다.

새 연구는 가능한 경우 다음을 먼저 확인한다: 유사한 signal/transform/hypothesis가 이미 있는가, 어떤 dataset과
operation이 쓰였는가, 기존 alpha와의 correlation·overlap·incremental contribution은 어떠한가, 실패 이유와
미충족 capability는 무엇이었는가, 재실행 없이 재사용할 수 있는가.

---

## 3. 시간과 point-in-time correctness

### 3.1 세 개의 시간축을 분리한다

| 축 | 의미 | 소유자 |
|---|---|---|
| **session time** | venue가 여는 날과 open/close 시각 | 선택한 venue의 거래 calendar (frozen run input) |
| **event time** | 어떤 operation이 평가되는 timezone-aware 시각 | run schedule |
| **availability time** | 그 관측을 처음 사용할 수 있는 시각 (`available_at`) | dataset registration |

**event time과 data row time은 같지 않다.** event timestamp가 dataset의 행으로 존재할 필요가 없다.
`2024-03-06 04:00`에 판단하는 Strategy는 데이터에 04:00 행이 하나도 없어도 정상적으로 그 시각에 판단한다.
그 시각에 보이는 것은 `available_at <= 2024-03-06 04:00`인 행들뿐이다.

### 3.2 PIT의 유일한 보편 술어

모든 data consumer는 다음만 만족하는 observation을 읽는다.

$$
available\_at \le evaluation\_time
$$

- Strategy와 alpha의 evaluation time은 **decision time**이다.
- order conversion, constraint adjustment, pre-execution validation의 evaluation time은 **execution time**이다.
- monitoring의 evaluation time은 **monitoring time**이다.
- actual account snapshot의 `as_of`도 evaluation time보다 늦을 수 없다. 이는 actual state가 과거 committed
  outcome만 담기 때문에 자연히 성립하며, 별도의 cutoff 장치를 요구하지 않는다.

vqapr가 보장하는 것은 **선언된 availability의 준수**다. source의 실제 경제적 공시 시점에 대한 최종 확인은
user가 내리고, bundled agent skill이 근거 있는 후보를 제시한다(§11).

Strategy, child research, model inference, inner execution component가 permitted cutoff를 우회해 source를
직접 읽어서는 안 된다.

compliance evaluator는 strategy가 소비하지 않는 independent registered data를 요구할 수 있다. 그러나 그
data나 monitoring finding을 alpha/strategy input으로 자동 전달하지 않는다. 이후 decision이 이를 사용하면
explicit dependency, availability cutoff, lineage를 가져야 한다.

#### UC-TIME-001 — 명시적 timezone과 모호한 timestamp의 거부

source timestamp와 session timezone이 명시되어야 하며, timezone이 없거나 서로 모순된 timestamp는 state
mutation 전에 실패한다. naive datetime을 임의의 timezone으로 해석하지 않는다.

### 3.3 Decision cadence는 strategy의 경제적 의미다

**user는 strategy 정의만 읽고 그 strategy가 언제 판단하는지 알 수 있어야 한다.** cadence를 확인하려고
실행 스크립트나 orchestration 설정을 읽어야 한다면 그것은 결함이다.

이것은 strategy가 시간을 직접 진행시키거나 자기를 호출한다는 뜻이 **아니다.** strategy는 "어떤 session마다
몇 시에 판단하는가"를 **선언**하고, run이 그 선언과 frozen calendar를 결합해 판단 시점을 만든다.

invocation이 시작된 뒤 과거 cadence를 바꾸거나 시간을 소급해서는 안 되며, 실행 시점 선택에 사용하는
정보는 그 시점에 관측 가능해야 한다.

#### UC-TRIGGER-001 — 선언된 decision cadence

Strategy 정의 안에서 "eligible session마다 04:00 Asia/Seoul에 판단한다" 또는 "5 eligible session마다 04:00에
판단한다"를 선언한다. run 결과의 판단 시점은 그 선언과 frozen venue calendar의 교집합과 정확히 일치해야
한다. 같은 Strategy를 다른 기간에 실행해도 정의만 읽으면 cadence와 local time을 알 수 있다.

daily close `2024-03-05` 행은 `2024-03-05 15:30 Asia/Seoul`에 available해진다. 따라서 `2024-03-06 04:00`
decision은 그 행을 읽을 수 있고, 그 decision의 next eligible close execution은 `2024-03-06 15:30`이다.
`2024-03-05 04:00` decision은 같은 행을 읽을 수 없다. 04:00 timestamp가 dataset에 행으로 존재할 필요는 없다.
판단하지 않은 session은 실패가 아니라 정상적인 결과이며 재현 가능한 기록으로 남는다. cadence나 local time을
바꾸면 **경제적으로 다른 run**으로 구분되어야 한다.

### 3.4 Session calendar는 venue fact다

판단 후보가 되는 session 목록과 open/close 시각은 **선택한 venue의 거래 calendar 사실**이어야 하고,
Strategy나 data coverage에서 유도해서는 안 된다.

Strategy는 휴장일이나 session 자체를 만들어내지 않는다. run은 명시적으로 동결된 session calendar 또는 선택
환경이 식별한 calendar provider의 결과를 사용한다.

이 규칙이 막는 것: 특정 종목의 결측 때문에 후보 session이 사라지면 cadence 전체가 미래 정보에 오염된다.
가격 행 coverage나 단순 weekday 추정으로 session calendar를 만들지 않는다.

### 3.5 Bounded lookback

historical data access는 선택한 operation이 선언한 **exact lookback**을 강제한다. current product contract는
두 종류뿐이다.

- **`rows`** — PIT gate를 통과한 행을 registered logical key로 결정적으로 정렬한 뒤 instrument별 최근 N행까지
  반환한다.
- **`calendar`** — user가 명시한 timezone의 evaluation date에서 years/months/days를 달력 산술로 이동한 date의
  00:00부터 evaluation time까지 `available_at`이 포함되는 행을 반환한다. 거래일 수를 세는 `sessions`
  semantics가 **아니다.**

두 종류 모두 `available_at <= evaluation_time` 상한을 바꾸지 않고 **store query에 직접 반영**한다. 전체
history를 먼저 읽은 뒤 Strategy code에서 자르는 경로를 bounded access로 간주하지 않는다.

`rows`보다 적은 행만 존재하면 있는 만큼 반환하고 requested/actual coverage를 access evidence에 기록한다.
dataset 전체의 `available_at_min`만으로 instrument별 coverage를 추정하거나, 행이 전혀 없는 instrument를
declared universe 없이 존재한다고 추측하지 않는다. 계산에 필요한 최소 관측치와 ragged-panel 처리 방식은
해당 Strategy의 경제적 규칙이다.

calendar lookback은 years/months/days 중 적어도 하나가 양수여야 하고 timezone과 month-end clamp policy를
frozen input에 보존한다. 동일 `available_at`의 순서는 registered logical key로 결정해 같은 input에서 같은 row
set을 만든다.

#### UC-LOOKBACK-001 — Store까지 강제되는 exact lookback

Strategy가 60 rows lookback을 선언하면 그 제한이 store query까지 전달되어야 하고, lookback을 선언하지 않은
historical read는 실패해야 한다. access evidence에는 요청한 lookback과 실제 coverage 정보가 남는다.

### 3.6 독립적인 clock

observation, decision, execution, monitoring의 evaluation time은 같을 수도 다를 수도 있다. Strategy decision이
없는 시점에도 actual account를 평가할 수 있고, execution은 decision과 분리된 PIT-safe 시점에 일어난다.

"독립 clock"은 별도의 clock object나 별도 runtime을 의무화한다는 뜻이 아니라, **monitoring cadence와 frozen
evaluation time이 Strategy decision cadence에 종속되지 않는다**는 뜻이다. 각 result는 자신이 평가한 instant와
permitted cutoff를 보존한다.

intraday event와 partial fill은 future work다.

---

## 4. Data registration과 requirement discovery

이 절의 목적은 처음부터 완전한 dataset schema를 요구하는 것이 **아니다.** vqapr는 현재 작업에 꼭 필요한
semantic binding만 먼저 확인하고, 실제 workflow component를 호출할 때 추가 requirement를 발견한다.
**등록 성공은 모든 downstream workflow와의 호환성 보증이 아니다.**

### 4.1 최소 등록

logical dataset은 physical file과 구분되는 versioned reference다. 최초 등록은 다음 semantic role만 요구한다.

1. instrument를 식별하는 field
2. observation을 사용할 수 있게 된 시점을 뜻하는 `available_at` field 또는 user-confirmed availability rule
3. 해당 dataset의 logical row key
4. 등록할 data field의 선택
5. physical source identity와 provenance

field 이름은 강제하지 않는다. `ticker`, `symbol`, `종목코드` 중 무엇이 instrument인지 user가 binding한다.
기본 instrument-time panel에서는 `(available_at, instrument)`가 null 없이 해석 가능하고 유일한지 검사한다.
같은 instrument와 time에 여러 행이 필요한 event/long-form dataset은 event ID나 sequence 같은 추가 key axis를
선언하거나 별도 logical dataset으로 등록한다.

**`available_at`만이 모든 dataset에 공통으로 특별 취급되는 시간 경계다.** `fiscal_period`, `session_date`,
`event_time`, `revision`, `horizon_end`, unit, currency, universe coverage, missingness는 source가 제공하는
일반 column 또는 metadata다. 이를 필요로 하는 consumer가 명시적으로 요구하고 해석하며, 아직 선택하지 않은
workflow 때문에 최초 등록을 막지 않는다.

**consumer-purpose alias를 등록에 두지 않는다.** `research_close`, `execution_price`, `valuation_price` 같은
role을 registration에 새기지 않는다. 같은 `close` field를 Strategy, execution, valuation이 각자 자기
requirement로 선택한다. 그래야 하나의 field가 여러 목적으로 쓰일 때 어느 소비자가 실제로 무엇을 읽었는지
lineage에 남는다.

#### UC-DATA-001 — 최소 등록과 field-name 자율성

`DATE`, `CODE`, `VALUE`, `FISCAL_PERIOD` 컬럼이 있는 file에서 user는 `CODE`를 instrument로, source rule로
확정한 `DATE`를 `available_at`으로, `(DATE, CODE)`를 logical key로 binding하고 필요한 data field를 선택한다.
daily close 행의 `DATE=2024-03-05`가 해당 session 종가를 뜻한다면 확정된 availability rule은
`2024-03-05 15:30 Asia/Seoul`을 만든다. `FISCAL_PERIOD`는 Strategy가 필요할 때 요구하는 일반 column이다.
package는 field 이름을 바꾸거나 universal observation timestamp를 추가하라고 요구하지 않는다. currency나
universe metadata가 없다는 이유만으로 이 단계가 실패해서는 안 된다.

### 4.2 Availability는 추측하지 않는다

`DATE`를 `available_at`으로 바로 binding할 수 있는 것은 **user가 그 값이 실제 공개 시각이라고 확인한
경우뿐**이다. source date를 자동으로 00:00으로 해석하지 않는다.

별도 availability field가 없으면 bundled agent skill이 data category, source 설명, 공개 관행을 근거로 하나
이상의 지연 규칙 candidate를 제시하고 각 candidate의 가정과 look-ahead 영향을 설명한다. 일봉 종가는 `DATE`
당일 장 종료 시각, 재무제표는 별도 공시 timestamp 또는 확인된 publication lag를 제안할 수 있다.

이 candidate는 package default가 **아니며** user가 근거를 확인해 선택해야 한다. 선택된 규칙은 project config에
명시하고 package가 형식, coverage, PIT consistency를 deterministic하게 validation한다.

#### UC-AGENT-001 — Availability 후보를 제시하는 질문

등록하려는 `DATE`가 관측일인지 실제 공개 시각인지 불명확하다. agent는 미래 정보 사용이 성과를 부풀리는
look-ahead 문제를 설명하고, 실제 release timestamp field 사용, source별 확인된 지연 규칙, data 보강 같은
후보를 제시한다. user가 근거와 함께 binding을 선택한 뒤 package validation을 호출한다. **근거가 확인되기
전에는 `DATE`를 `available_at`으로 간주해 등록하지 않는다.**

### 4.3 Progressive requirement discovery

Strategy, model, optimizer, report, executor는 **실제로 호출될 때** 자신에게 필요한 capability를 선언한다.
등록된 dataset이 requirement를 충족하지 못하면 package는 해당 operation을 state mutation 전에 멈추고
structured error를 낸다. **이 실패는 기존 registration 전체를 무효화하지 않는다.**

agent는 error와 skill 지침을 바탕으로 다음 후보 중 의미가 맞는 방법을 user에게 제시한다: 기존 dataset에
binding 추가, 같은 physical source를 다른 semantic contract의 새 dataset으로 등록, derived dataset 생성,
requirement가 적은 workflow profile 선택, compatible local extension 작성.

어떤 후보가 적절한지는 data의 경제적 의미와 user intent에 달려 있다. **package는 선택된 결과가 requirement를
만족하는지만 deterministic하게 판정한다.**

#### UC-DATA-002 — Downstream workflow에서 발견된 benchmark-weight requirement

가격 Strategy는 최소 등록된 dataset만으로 실행되지만, single-name cap을 선택한 execution workflow는 execution
evaluation 시점의 time-varying benchmark-weight binding을 추가로 요구한다. 해당 workflow를 처음 호출할 때
package는 requirement 미충족을 보고하고 order나 account mutation을 만들지 않는다. agent는 benchmark dataset
신규 등록, 기존 dataset의 binding 보강, constraint 없는 research 선택을 제시한다. user 선택 후 validation에
성공하면 **그 operation만** 안전하게 retry할 수 있어야 한다.

#### UC-PIT-001 — Label horizon의 늦은 발견

forward-return label을 만드는 model이 `horizon_end`를 요구하지만 input dataset에는 binding이 없다. package는
model materialization **전에** 실패하고 어떤 requirement가 부족한지 보고한다. agent는 계산 가능한 derived
field인지, 별도 dataset이 필요한지, model을 바꿀지를 설명해 user의 결정을 받는다. 임의의 horizon이나 delay를
채우지 않는다. horizon 보강 뒤의 새 invocation은 이전 failure를 dependency로 연결하고, frozen evaluation
time까지 이용 가능한 label만 발행한다.

### 4.4 Price axis와 derived unit price

execution을 선택한 workflow는 예외 없이 **가격 축**을 요구한다. vqapr에는 return-native 체결 경로가 없으며,
모든 체결과 valuation은 수량과 가격으로 표현한다.

source가 기간 return만 제공하면 그것을 unit price 시계열로 변환한 dataset을 등록한다.

$$
P_0 = b > 0, \qquad P_t = P_{t-1}(1 + r_t)
$$

이 값은 observed market price가 아니라 **derived unit NAV**다. 변환은 package operation이 아니다. bundled
agent skill이 base $b$와 변환 가정을 설명하고 user가 확정하며, 결과 dataset은 다른 dataset과 동일한 최소 등록
계약(§4.1)을 따른다. package는 이 변환을 위한 별도 schema, transform registry, derived-binding metadata를 두지
않는다. 가격의 양수성과 체결 가능성은 execution 시점에 판정한다.

return-native fallback은 제공하지 않는다. 가격 축 없이 portfolio 수익률을 주장하는 경로는 §10.2가 금지한다.

### 4.5 Universe, tradability와 market metadata는 필요할 때 요구한다

universe와 tradability는 모든 dataset의 등록 조건이 아니다. 횡단면 비교, benchmark-relative construction, 실제
주문 생성처럼 **필요한 operation이** 각자 coverage, membership time, tradability requirement를 선언한다.
unknown을 자동으로 tradable 또는 non-member로 바꾸지 않고 해당 operation의 policy에 따라 fail, exclude,
warn한다.

OHLCV, 상하한가, 거래정지, lot size, price source도 이를 사용하는 execution 또는 analysis profile에서
요구한다. 단순 signal 연구가 사용하지 않는 market field 때문에 막혀서는 안 된다. 반대로 **실제 주문 생성은
필요한 price, lot, tradability binding이 없는데도 추정 default로 진행해서는 안 된다.**

### 4.6 Dependency binding

각 operation은 **실제로 소비한** logical dataset, artifact, config identity를 결과 lineage에 기록한다. 같은
source를 쓰더라도 Strategy input, compliance input, reporting input은 서로 다른 binding일 수 있다. 등록되어
있지만 해당 operation이 읽지 않은 field나 dataset은 dependency로 기록하지 않는다.

---

## 5. Research — Model과 Strategy

Model과 Strategy는 서로 다른 질문에 답한다. 두 역할은 독립적으로 실행·평가할 수 있으며 하나의 의무적인
pipeline을 공유하지 않는다.

```text
registered PIT data -> Model -> reusable signal / estimate / research result
registered PIT data ------------------------------------┐
reusable Model result ----------------------------------┼-> Strategy result -> analysis / reuse
actual portfolio state, when required ------------------┘                          |
                                          executable run을 선택했다면 --------------┘
                                                        |
                                   frozen intended portfolio -> execution spine (§6)
```

### 5.1 Reusable Model research

Model은 prediction, signal, feature, firm characteristic, factor exposure, risk estimate, statistical
factor-return estimate를 만들 수 있다. 결과는 경제적 의미, axis, unit, time semantics가 맞는 reusable result로
저장해야 하며, **서로 다른 결과를 모두 `signal`이라는 이름으로 뭉개지 않는다.**

#### UC-MODEL-001 — Portfolio 없는 Model 연구

Model이 point-in-time feature로 다음 기간의 cross-sectional score를 만든다. user는 score coverage, IC,
stability를 평가하고 reusable result로 저장하지만 Strategy, target, order, portfolio return을 만들지 않는다.
**이 workflow는 완전한 Model research run이어야 한다.**

#### UC-MODEL-002 — Statistical factor return과 executed portfolio return의 구분

Model이 한 시점의 cross-sectional exposure와 observed return으로 factor-return regression coefficient를
추정한다. result는 statistical estimate, regression specification, input period, availability를 명시하며
**portfolio NAV나 executable factor return으로 표시하지 않는다.** 같은 factor를 실제 portfolio로 평가하려면
별도 Strategy와 execution workflow를 선택해야 한다.

### 5.2 Strategy research

Strategy는 registered data와 compatible Model result를 소비해 경제적 판단을 만든다. deterministic rule
Strategy는 Model 없이 raw registered data를 직접 사용할 수 있다. 내부에서 score를 계산하더라도 **reusable
signal을 publish한다면 Model result와 같은 semantic contract를 따라야 한다.**

이 PRD는 Strategy가 signal, score, weight, target 중 무엇을 public output으로 내는지 고정하지 않는다. 어떤
shape를 고르든 downstream execution lifecycle은 변하지 않는다(§6). 어느 경우에도 Strategy output 자체는 fill도
authoritative actual state도 아니다.

§2.7의 built-in weighting 함수들은 공통적으로 instrument별 signed 값을 입력으로 받는다. 이는 **built-in을
호출하기로 선택한 Strategy만 구속하는 사실**이며, Strategy가 그 shape의 값을 만들어야 한다는 요구가 아니다.
built-in을 하나도 쓰지 않는 Strategy는 그런 중간값을 만들지 않고 곧바로 target을 구성해도 된다.

#### UC-SIGNAL-001 — Strategy 내부의 deterministic signal과 weight 조립

user가 price reversal Strategy를 선택한다. Strategy는 point-in-time price를 읽어 내부 reversal score와 signed
weight를 만들고 optional academic execution profile에서 long-short 결과를 평가한다. reusable signal을 별도로
publish하지 않는다면 stored Model result나 enhanced-index portfolio를 만들지 않아도 workflow가 완결된다.

#### UC-SIGNAL-002 — Stored Model result의 다중 재사용

한 Model이 monthly value characteristic을 materialize한다. long-short research Strategy와 long-only
construction Strategy가 같은 result를 소비하되 각자 다른 weighting rule과 execution profile을 사용한다.
Model은 다시 실행하지 않아도 되고, 두 Strategy result는 자신의 input dependency와 weighting semantics를 따로
보존한다.

### 5.3 Result category

각 category는 axis, unit, time semantics, compatibility를 스스로 선언한다. 서로 다른 category를 같은 이름으로
저장하지 않는다.

| category | 의미 | 반드시 구분되는 이유 |
|---|---|---|
| **materialized research data** | 반복 사용을 위해 저장한 derived research data (signal, label, factor return, exposure, covariance, rolling risk estimate) | statistical estimate와 executed portfolio return을 같은 category로 표시하면 §2.2가 무너진다 |
| **stored signal** | reusable instrument/time information surface. signal semantics, axis, unit, direction, availability, coverage, producer, input lineage 포함 | **signal은 portfolio weight를 의미하지 않는다** |
| **portfolio weight** | 예산을 instrument별로 배분한 signed 값 | signal과 **shape가 같고 의미가 다르다** (아래 참고) |
| **signed alpha-weight result** | decision time별 instrument signed weight와 budget semantics. weight가 raw / active / benchmark-relative / physical 중 무엇인지 명시 | 네 가지는 같은 뜻이 아니다 |
| **ensemble result** | 여러 stored alpha-weight result를 member lineage와 함께 조합한 combined signed weight. member weighting, netting, crossing, residual, normalization 명시 | member 기여와 상쇄가 보이지 않으면 재사용이 불가능하다 |
| **frozen intended portfolio** | 실행 전에 동결한 instrument target과 budget semantics | **아직 order도 fill도 actual holding도 아니다** |
| **constraint declaration** | 선택한 workflow에 적용할 versioned limit intent | §7 |
| **constraint-adjustment result** | proposed target/order를 declared constraint에 맞게 best-effort로 조정한 결과 | **존재한다는 사실이 compliance를 보증하지 않는다** |
| **requested orders and conversion evidence** | requested order와 instrument별 conversion, rounding, clipping, skip/failure reason | requested ≠ dealt |
| **pre-execution validation finding** | 최종 제출 후보를 독립 평가한 advisory result | adjustment result와 별개의 판정이다 |
| **actual-account monitoring finding** | committed fill 이후의 actual state를 monitoring time에 평가한 결과 | account를 소급 변경하지 않는다 |
| **execution result** | committed fill, cost, account state, NAV, exposure, PnL, turnover | 유일하게 portfolio return을 주장할 수 있는 category |

statistical factor-return estimate는 regression specification과 input data를 dependency로 갖는다. 실제 factor
portfolio의 return을 담은 materialized data는 **그것을 산출한 execution과 actual state를 dependency로** 갖는다.
산출 경로 없이 portfolio return 시계열을 등록하지 않는다.

#### Signal과 weight는 shape가 같고 의미가 다르다

둘 다 instrument별 signed 값이므로 타입이 서로를 막아주지 않는다. 그러나 signal은 **확신의 방향과 크기**를,
weight는 **예산의 배분**을 뜻한다. signal을 그대로 weight로 사용하는 것은 "확신의 크기가 곧 배분 비율"이라는
경제적 주장이며, 그것이 의도였다면 명시적으로 선언되어야 한다.

따라서 **signal에서 weight로 가는 전환은 명시적 연산이어야 한다.** 타입 검사가 이 경계를 지켜주지 못하므로,
전환을 수행하는 연산을 통과했다는 사실 자체가 그 전환이 의도되었다는 증거가 된다.

### 5.4 Composition — Ensemble은 하나의 Strategy다

ensemble은 별도의 후처리 단계로 강제되는 것이 아니라, **기존 member Strategy와 그 compatible stored
alpha-weight result를 입력으로 삼는 하나의 Strategy**다. member producer가 direct Strategy인지 stored model
output을 소비했는지는 ensemble의 public contract가 아니다.

다음 composition을 모두 지원해야 한다.

- 같은 Model result를 서로 다른 Strategy가 재사용하고 독립적으로 평가한다.
- 같은 Strategy logic을 compatible한 여러 Model result와 비교한다.
- 여러 Strategy result를 producer 재실행 없이 조합한다.

#### UC-ENSEMBLE-001 — 기존 Strategy result의 조합

value와 momentum Strategy의 signed weight를 저장한 뒤 ensemble이 두 result를 읽어 ticker-level netting을 한다.
한 member의 long과 다른 member의 short가 상쇄된 수량, 최종 signed weight, member lineage가 확인 가능해야 한다.

### 5.5 Budget semantics

**fixed budget**은 선언한 gross/net budget을 채우는 것을 목표로 한다. **flexible budget**은 약한 signal, 높은
cost, risk 조건 때문에 일부를 cash/residual로 남길 수 있다. package가 빈 weight를 자동 재정규화해 두 의미를
바꾸지 않는다.

budget을 **weight를 만드는 연산이 스스로 결정하지 않는다.** 선언된 예산보다 적게 배분된 결과를 연산이 자동으로
채우면 flexible을 fixed로 몰래 바꾸는 것이므로 금지한다.

#### 의도된 cash와 잔여는 다르다

배분되지 않은 부분은 산술적으로 언제나 현금이다. 그러나 다음 둘은 경제적 의미가 다르다.

- **의도된 cash 포지션.** 무위험자산 비중을 알파의 일부로 삼는 전략(betting-against-beta의 leverage/무위험자산
  구성, risk parity의 cash sleeve, market timing의 현금 비중)에서 cash는 **선택한 포지션**이다.
- **배분하지 못한 잔여.** flexible budget에서 약한 signal, 높은 cost, risk 조건 때문에 남은 부분이다.

두 경우의 숫자가 같아도 같은 것으로 보고해서는 안 된다. 결과는 어느 쪽인지 구분할 수 있어야 한다.

#### 실현된 budget은 의도한 budget과 다를 수 있다

constraint 조정, lot rounding, cash clipping을 거치면 실현 gross/net이 의도한 값과 달라진다. 결과는 **의도한
budget과 실현된 budget을 함께** 보여야 하며, 하나를 다른 하나로 대체해 보고하지 않는다(§9.4).

#### UC-ALPHA-BUDGET-001 — 약한 signal의 residual

flexible Strategy가 기준보다 강한 종목만 선택한 결과 gross budget의 40%만 사용한다. result는 60% residual을
보존한다. fixed-budget consumer가 이를 요구하면 **자동 확대하지 않고** incompatibility를 보고해 user가
normalization 또는 다른 Strategy를 선택하게 한다.

### 5.6 Path-independent와 path-dependent alpha

path-independent result는 동일 frozen input에서 prior holding과 fill history 없이 재현된다. path-dependent
result는 actual holding, cash, prior fill, cooldown, strategy state에 의존한다.

**두 result 모두 producer를 다시 실행하지 않고 frozen input으로 재사용할 수 있다.** consumer Strategy는
필요한 artifact role, schema, semantics를 선언하고 package가 이를 resolve한다. 실제로 소비한 artifact만
dependency edge가 되며, source result가 의존했던 actual state·strategy state identity와 반영 범위는 새
result의 lineage에서도 보존된다.

재사용은 **source result를 consumer의 현재 account에서 다시 계산했다는 뜻이 아니다.** budget, schema,
semantics가 consumer 요구와 맞지 않으면 계산 전에 compatibility error로 실패한다.

#### UC-ALPHA-PATH-001 — Path-dependent weight의 producer-independent 재사용

turnover-aware Strategy가 account A의 actual holding과 strategy state를 소비해 path-dependent signed-weight
result를 만든다. 이후 ensemble Strategy가 이 frozen result와 다른 member result를 조합한다. source producer는
다시 실행되지 않고 parent result도 변경되지 않으며, ensemble result는 consumed artifact와 source actual
state·strategy state identity 및 반영 범위 lineage를 보존한다. ensemble weight를 account B의 executable
target으로 변환하면 account B의 현재 committed holding과 현재 execution input을 사용하지만, **source member가
account B에서 재계산되었다고 표시하지 않는다.**

#### UC-ALPHA-CHILD-001 — 체결 규칙만 바꾼 child research

parent의 signed weight를 고정하고 next-close와 next-open 같은 두 full-fill convention을 child에서 비교한다.
Model과 Strategy를 다시 실행하지 않으며, 각 child는 별도 actual state, execution assumption, PIT price
binding, fill dependency를 보존하고 parent result는 불변이다.

### 5.7 Strategy state

Strategy는 이전 판단의 결과를 다음 판단으로 이어갈 수 있어야 한다.

- **내용과 구조는 strategy가 정하며 package는 이를 해석하지 않는다.**
- **하나의 bounded value다.** Strategy가 임의의 이름으로 상태를 늘려갈 수 있는 표면을 제공하지 않는다.
  package가 해석하지 않으면서도 durable·portable하려면 값의 **범위와 형식**이 정해져 있어야 한다.
  범위가 없는 state는 저장할 수도, 다음 run에 넘길 수도, "무엇이 바뀌었는가"를 보일 수도 없다.
- **portable format으로 표현 가능해야 한다.** 표현할 수 없는 값(비유한 수치, 문자열이 아닌 key, 임의의
  in-memory 객체)은 계산 전에 거부한다. 저장 시점에 조용히 잘라내지 않는다.
- **저장되는 값은 Strategy가 들고 있는 객체와 분리된다.** Strategy가 이후에 같은 객체를 계속 변경해도 이미
  기록된 state가 따라 바뀌어서는 안 된다. 그렇지 않으면 이력 전체가 마지막 값 하나로 붕괴한다.
- durable하고 portable해야 하며, 한 run의 종료 state를 다음 run의 시작 state로 사용할 수 있어야 한다.
  production에서 하루 단위로 실행하며 전날 state를 이어받는 것이 기준 사례다.
- **갱신은 execution이나 fill 발생 여부에 종속되지 않는다.** 체결이 없는 세션에도, execution profile을 쓰지
  않는 research-only strategy도 state를 이어갈 수 있다.
- strategy state를 사용한 result는 그 사실을 드러내야 한다. 소비자가 "이 result는 data만으로 재현되지 않는다"를
  알아야 하기 때문이다.
- **strategy state는 최후 수단이다.** 같은 값을 bounded lookback이나 actual-state 이력(§6.6)이나 durable
  artifact로 표현할 수 있으면 그쪽이 재현 가능성이 높다.

adaptive Strategy는 realized result나 new observation으로 belief, parameter, member weight를 갱신할 수 있다.
특정 Bayesian class hierarchy를 요구하지 않고, update 전후의 state와 사용한 evidence를 비교 가능하게 보존한다.

#### UC-STATE-001 — 체결 없는 세션과 run 경계를 넘는 state 연속성

Strategy가 판단 결과를 state로 남긴다. 그 세션에 주문이 없거나 dealt quantity가 0이어도 state는 이어진다.
run이 끝나면 최종 state를 결과로 얻을 수 있고, 다음 run의 시작 state로 **명시적으로 지정해** 이어서 실행할
수 있다. 이때 이전 run의 state를 자동으로 선택하지 않는다.

#### UC-ALPHA-ADAPTIVE-001 — Fill 이후 ensemble belief 갱신

ensemble Strategy가 member별 realized outcome을 받은 뒤 다음 decision의 member weight를 바꾼다. result는 어떤
feedback까지 반영했는지 보여준다. 같은 update를 feedback 없이 재생하거나 미래 fill을 앞당겨 사용해서는 안 된다.

---

## 6. Executable lifecycle

### 6.1 하나의 spine

portfolio return, NAV, PnL, turnover를 만드는 모든 run은 다음을 순서대로 통과한다. academic long-short와
physical long-only의 차이는 **선택한 profile이 허용하는 direction, instrument별 quantity granularity, price,
cost, realism**뿐이다.

```text
Strategy decision
  -> mandatory portfolio construction
  -> frozen intended portfolio
  -> execution-time order conversion
  -> selected execution profile -> fills
  -> account commit
  -> valuation / mark
  -> feedback
```

같은 단계와 같은 결과 lineage를 두 profile 모두 제공해야 한다.

### 6.2 Portfolio construction은 필수 경계다

executable Strategy run은 signed, long-only, benchmark-relative 여부와 무관하게 현재 연구 결과를 **실행 가능한
하나의 frozen intended portfolio**로 확정한다. construction 규칙은 profile마다 다를 수 있지만 이 경계를
우회할 수 없다.

frozen intended portfolio는 budget semantics, direction, instrument target, source lineage를 동결한다. cash를
의도된 포지션으로 표현할지 잔여로 표현할지는 §5.5의 구분을 따른다. **Strategy result나 raw weight를
execution profile에 직접 제출하지 않는다.**

construction 내부에서 §2.7의 built-in weighting 함수를 조합할 수 있다. 그러나 그 함수들은 run identity,
decision time, account version을 알지 못하므로 실행 가능한 intent를 만들지 못한다. **intent 조립과 lineage
기록은 Strategy의 책임이며 이 경계는 built-in 사용 여부와 무관하다.**

Model-only 또는 non-portfolio analysis에는 construction이 필요하지 않다.

#### UC-PORTFOLIO-001 — 같은 alpha의 서로 다른 portfolio 사용

같은 signed alpha result를 academic long-short construction과 equity long-only enhanced-index construction에
사용한다. 두 workflow는 서로 다른 investability, direction, budget, cost requirement를 발견해 각각 frozen
intended portfolio를 만든다. 이후에는 같은 order conversion, fill, commit, valuation, feedback lifecycle을
따른다. **alpha result 자체를 어느 한 portfolio 의미로 다시 쓰지 않는다.**

### 6.3 Order conversion은 execution time의 책임이다

실제 주문을 만드는 단계는 frozen intended portfolio, **execution 시점의** committed holding/cash, instrument
rule, price, tradability를 사용한다. decision time의 stale quantity를 재사용하지 않는다.

Strategy가 요구한 data와 execution profile이 요구한 data는 **각각 명시적으로 resolve**하며,
purpose-specific registration alias를 통해 암묵적으로 선택하지 않는다. 필요한 binding이 없으면 §10의
progressive error로 mutation 전에 멈춘다.

instrument별로 fractional 허용, lot rounding, clipping, skip, rejection, requested/dealt quantity가 확인
가능해야 한다.

#### UC-EXEC-001 — Decision과 execution의 분리

Strategy result나 frozen intended portfolio가 존재한다는 사실만으로 fill이 생기지 않는다. 선택한 MVP execution
profile은 next daily close 같은 PIT-safe convention에서 execution-time order conversion을 수행한 뒤 지원되는
order를 전량 체결하고 cost와 즉시 결제 cash를 committed state에 반영한다. **execution time에 새로 보이는
정보로 과거 Strategy intent를 암묵적으로 다시 계산하지 않는다.**

#### UC-EXEC-002 — Daily close profile의 명시적 한계

daily close profile은 결정 당일 종가를 무조건 알고 체결한 것처럼 처리하지 않는다. decision cutoff와 선택한
fill timing이 PIT-safe인지 validation하고, volume impact, partial fill, 실제 settlement cycle을 모델링하지
않았다는 limitation을 결과에 남긴다.

### 6.4 Execution profile이 realism을 정의한다

MVP의 academic/hypothetical profile과 daily-bar physical simulation profile은 fill timing, tradability,
direction, instrument별 quantity granularity, cost capability를 **각자 선언한다.**

여기서 두 가지를 반드시 분리한다.

| 무엇 | 누가 결정하는가 |
|---|---|
| fractional 허용 여부, lot/quantity step, rounding, price source, cost, fill timing | **선택한 execution profile이 해당 venue의 instrument listing에 대해** |
| 음수 position 허용 여부 | **run 시작 시 동결된 account state-transition validity** |

account state-transition validity는 **음수 position 허용 여부만** 판정하며 fractional 또는 lot quantity를
결정하지 않는다. 이 둘을 하나의 스위치로 합치면 "academic이니까 소수점"이라는 잘못된 결합이 생기고, 같은
instrument를 다른 venue에서 다르게 다룰 수 없게 된다.

각 run의 state-transition validity는 시작 시 동결되며 중간에 long-only와 signed 사이를 바꿀 수 없다. user는
invocation마다 compatible profile을 선택할 수 있어야 하며, profile을 교체해도 frozen intended portfolio의
의미를 암묵적으로 다시 쓰지 않는다.

**package나 profile의 이름만 보고 현실성을 과장하지 않는다.** "KRX"라는 label 자체가 실제 거래소 완전
재현을 뜻하지 않으며, 구현된 rule과 명시된 limitation만 주장한다.

#### UC-PROFILE-001 — Profile 선택과 교체

user가 같은 frozen intended portfolio를 서로 다른 compatible execution profile에서 실행한다. 각 run은 자신의
supported instrument, permitted direction, quantity semantics, fill timing, cost, cash treatment, limitation을
독립적으로 기록한다. daily physical과 academic hypothetical semantics가 하나의 결과 안에서 섞이지 않는다.

#### UC-ACADEMIC-001 — Signed portfolio의 명시적 가상 거래

user가 signed Strategy result를 academic profile로 실행하면 먼저 frozen intended portfolio를 확정하고,
execution 시점의 committed hypothetical account state와 PIT reference price를 사용해 physical profile과 같은
order → fill → commit → valuation lifecycle을 따른다. 선택한 academic venue는 Stock, ETF, tracking-only Index,
synthetic-unit-price Factor의 listing과 instrument별 fractional/lot 규칙을 판정한다. fractional execution을
허용한 instrument는 signed fractional quantity를 전량 가상 체결할 수 있다.

거래비용·tax·slippage·market impact·borrow cost는 이 fixture에서 명시적인 0이고 turnover는 별도 기록한다.
listing, exact-time price, positive NAV, compatible signed state transition, supported quantity rule 중 하나라도
없으면 해당 rebalance 전체를 mutation 전에 거부한다. 결과는 `hypothetical`로 표시하며 broker-confirmed
production state, borrow/locate, collateral, margin 또는 executable real short capability로 주장하지 않는다.

### 6.5 Transaction cost

#### UC-COST-001 — 상품과 방향에 따른 거래비용

같은 execution date의 fixture에서 주식과 ETF를 같은 venue/profile로 거래한다. equity SELL tax는 15bp, ETF
SELL tax는 명시적인 0bp이며 BUY와 SELL policy가 다르다. 각 주문에는 상품과 방향에 맞는 policy가 적용되고,
fill은 total cost와 **적용 policy identity**를 보존해야 한다.

#### UC-COST-002 — Effective-dated 거래비용

2024년과 2025년에 서로 다른 cost policy가 등록된 상태에서 경제적으로 같은 주문을 실행하면 각 execution
time에 유효한 policy가 선택되어 비용이 달라져야 한다. fill과 run evidence는 적용한 policy version, rule
identity, effective time을 보존한다.

#### UC-COST-003 — Cost-aware cash clipping

주문 원금만으로는 전량 BUY가 가능하지만 거래비용을 포함하면 현금이 부족한 경우, actual fill quantity는
비용을 포함한 가용 현금에 맞게 줄어야 한다. **clipping에 사용한 policy와 최종 fill 비용에 사용한 policy는
같아야 하며**, requested/dealt quantity와 clipping reason을 보존한다.

#### UC-COST-004 — 잘못된 비용 fallback 금지

ETF에 필요한 exact cost policy가 없고 Equity policy만 존재하는 경우, ETF가 Equity와 관련된 상품이라는 이유로
Equity policy를 암묵적으로 적용하지 않는다. execution은 missing/unsupported policy로 실패하고 fill이나 account
mutation을 만들지 않으며 failure evidence를 남긴다.

### 6.6 Account authority와 actual state 이력

simulation의 authoritative state는 committed fill, cost, cash, position이다.

#### 이력으로서의 actual state

Strategy와 monitoring은 actual state를 현재 시점의 한 장면으로만이 아니라 **관측 이력**으로 읽을 수 있어야
한다.

- 관측 단위는 최소한 둘을 선택할 수 있다: **계좌 전체의 session 시계열**(cash, NAV, 실현손익 등)과
  **instrument 단위 panel**(보유 수량, 진입 평단, 실현손익 등).
- 소비자는 필요한 관측 항목과 범위를 **선언**하고, 선언하지 않은 항목은 보이지 않는다. registered data
  관측과 같은 원칙이다.
- 기록 대상은 **committed state transition이 이미 계산하는 값**이다. 이력을 위해 별도 계산을 하지 않으며,
  그 집합 밖의 항목을 요구하면 **계산 전에 실패한다.** 추정하거나 다른 값으로 대체하지 않는다.
- **stop-loss, cooldown, 연속 손실 판정 같은 규칙은 strategy state 없이 actual state 이력만으로 표현될 수
  있어야 한다.**
- **actual state 이력 접근은 strategy state 보유 여부에 종속되지 않는다.**

#### UC-ACCOUNT-HISTORY-001 — Strategy state 없는 stop-loss

Strategy가 진입 평단과 최근 세션의 실현손익 이력을 선언해 읽고, 손실 한도를 넘은 종목을 청산 대상으로
판정한다. 이 판정에 strategy state를 사용하지 않으며, 실제로 소비한 actual-state 항목과 범위가 result의
dependency로 남는다. 선언하지 않은 항목은 읽을 수 없고, **기록되지 않은 항목을 요구하면 계산 전에
실패한다.**

#### UC-CLOSED-LOOP-001 — Actual execution feedback

첫 decision의 전량 fill과 transaction cost가 commit된 뒤, 다음 decision은 requested target이나 비용 차감 전
현금이 아니라 **actual cash, NAV, position, prior execution result**를 소비해야 한다. MVP의 주식·ETF cash는
fill과 동시에 결제된 것으로 처리한다.

#### 경로 의존 시나리오 — Actual fill에 의존하는 stop-loss

Strategy가 첫 decision에서 주식을 매수했지만 cost와 clipping 때문에 requested quantity보다 적게 체결된다.
이후 marked price가 **actual entry price** 대비 user-declared stop-loss threshold를 넘게 하락하면 다음
decision은 requested target이 아니라 committed quantity와 actual fill price를 사용해 exit intent를 만든다.
두 decision을 날짜별 독립 weight 계산으로 대체하거나 미래 fill을 앞당겨 사용해서는 안 된다.

#### Multi-instrument 시나리오 — 하나의 portfolio에서 여러 instrument

한 Strategy가 여러 주식과 ETF를 같은 decision에서 선택하면 shared cash, instrument별 cost, actual holding을
하나의 portfolio constraint 안에서 처리해야 한다. 종목별 requested/dealt quantity와 failure reason을 모두
보존하며, 한 instrument의 cash consumption이나 blocked execution이 다른 instrument의 결과와 다음 decision에
미치는 영향을 재현할 수 있어야 한다.

#### Multi-frequency 시나리오 — 서로 다른 data와 decision cadence

daily observation과 valuation을 사용하면서 monthly Strategy rebalance와 daily actual-account monitoring을
수행한다. 각 operation은 자신의 evaluation time과 permitted cutoff를 보존하고, rebalance가 없는 날에도
valuation과 monitoring 결과를 만들 수 있어야 한다. 이 use case는 intraday order book이나 partial fill 지원을
의미하지 않는다.

#### UC-SCALE-001 — 대규모 횡단면 실행

약 3,000개 주식으로 구성된 일별 횡단면 universe에서 한 decision time의 주문 집합을 처리할 때 종목별 fill과
diagnostic을 누락하지 않고 시간 축 closed loop를 유지해야 한다. supported resource profile에서 batch와
equivalent single-name characterization의 경제적 결과가 일치해야 한다.

### 6.7 Hold는 명시적 판단이다

새로운 주문을 만들지 않는 hold도 정상적인 decision이다. 이것은 previous target을 무조건 재제출한다는 뜻이
**아니다.**

hold를 별도 action이나 "결과 없음"으로 표현하면 세 가지가 구분되지 않는다: **판단하지 않음**, **판단해서
유지함**, **주문했지만 dealt 0**. 세 경우는 경제적 의미가 다르므로 결과에서 구분되어야 한다.

#### 금지 — 가짜 hold

current target을 반복 제출해 hold를 흉내 내고 price-drift rebalance를 발생시키는 것을 금지한다.

### 6.8 Monitoring은 decision과 독립이다

constraint monitoring은 Strategy decision cadence와 독립적으로 committed actual account를 관찰할 수 있어야
한다. user가 committed state와 frozen evaluation time을 선택해 monitoring을 실행하면, 새 decision이나 order가
없는 날에도 finding을 만들 수 있어야 한다. **monitoring finding은 계좌를 수정하거나 과거 fill을 rollback하지
않는다.**

#### UC-EXEC-003 — No-trade day의 actual constraint breach

가격 변화로 한 종목의 actual weight가 그 시점의 $\max(10\%, w_i^{index}(t))$ cap을 넘었지만 Strategy decision은
없다. monitoring은 actual snapshot과 available benchmark weight를 사용해 breach를 기록한다. **새 order가 없다는
이유로 finding을 누락하지 않는다.**

### 6.9 Run 종료 결과

run은 종료 시 최종 actual state와 최종 strategy state를 결과로 제공해야 하며, 그 결과만으로 이어지는 run을
시작할 수 있어야 한다. 이것은 **중단된 run의 재개와 다르다.** 중단 복구는 current scope가 아니다(§13.2).

---

## 7. Constraints

constraint는 모든 research workflow의 선행 조건이 아니다. constraint adjustment, pre-execution validation,
actual-account monitoring을 **선택한 경우에만** 해당 operation이 metric, bound, evaluation scope, 필요한 data를
요구한다.

MVP가 지원하는 hard constraint는 두 개뿐이다.

$$
w_i(t) \ge 0
$$

$$
w_i(t) \le \max\left(10\%,\; w_i^{index}(t)\right)
$$

첫 식은 no-short다. 둘째 식의 benchmark constituent weight는 **time-varying PIT data**이며 해당 constraint를
선택한 workflow가 명시적으로 구독한다. 종목이 benchmark 비구성종목임이 **확인되면** $w_i^{index}(t)=0$이지만,
구성 여부나 weight data가 **누락되면 0으로 추정하지 않고 constraint evaluation을 실패시킨다.**

sector, turnover, liquidity, leverage, gross/net exposure, override policy는 future work다.

### 7.1 세 가지 서로 다른 결과

- **adjustment** — proposed intent를 가능한 범위에서 수정한다. original/adjusted intent, hypothetical
  post-trade state, constraint별 before/after value, method/status, unresolved residual을 보존한다.
- **pre-execution validation** — 최종 candidate가 limit을 만족하는지 독립적으로 판정한다. constraint별
  measured value, bound, excess, pass/fail status, exact input lineage를 포함한다.
- **actual-account monitoring** — committed state를 monitoring time에 평가한다.

**adjustment result가 존재한다는 사실만으로 compliance를 선언하지 않는다.** current MVP validation은
advisory이므로 breach finding을 기록한 뒤 같은 candidate의 execution을 계속하며, profile별 blocking switch를
두지 않는다. required input 부재나 evaluator 계산 실패는 finding이 아니라 **execution 시작 전의 structured
operation error**다. blocking, severity, override policy는 future work다.

#### UC-CONSTRAINT-001 — Constraint 없는 signal research

user가 stored signal의 IC와 hypothetical long-short 결과만 분석한다. portfolio constraint나 compliance dataset을
등록하지 않아도 이 workflow는 실행되어야 한다.

#### UC-CONSTRAINT-002 — Time-varying single-name cap

user가 single-name cap을 켠 뒤 physical target을 주문으로 바꾸려 한다. execution preparation 시점에 사용할 수
있는 benchmark constituent weight binding이 없으면 package는 constraint evaluation 전에 missing requirement를
보고하고 주문이나 account mutation을 만들지 않는다. weight가 3%인 종목의 cap은 10%, 15%인 종목의 cap은
15%다.

#### UC-CONSTRAINT-ADJUST-001 — 조정 후에도 남은 breach

single-name cap을 맞추려 target을 줄였지만 lot rounding 때문에 작은 breach가 남는다. result는
original/adjusted intent와 residual을 보여주고, validation은 fail 판정과 exact excess를 **별도 finding**으로
남긴다. current MVP는 이를 성공한 adjustment나 compliant result로 위장하지 않지만 같은 candidate의 execution을
계속한다.

---

## 8. Instrument semantics

instrument type, venue, execution profile은 가능한 position direction, lifecycle cash flow, settlement, cost
policy를 결정한다. `long_only`, `hypothetical_short`, borrow-aware short, derivative exposure를 같은 capability로
취급하지 않는다.

다만 이 의미는 해당 instrument를 실제로 연구하거나 실행할 때 요구하며, **무관한 dataset registration을 막는
전역 schema가 되어서는 안 된다.**

현재 `hypothetical_short`는 explicit academic listing, next-session-close PIT price, zero-friction full-fill
profile, 분리된 signed state ledger에서만 지원한다. physical KRX profile은 계속 long-only이며 real short
capability를 추론하지 않는다.

### 8.1 Long-short research와 executable short의 네 층

다음은 서로 다른 capability다.

1. signal/prediction/label의 IC, RankIC, rank-based diagnostic — **portfolio를 구성하지 않는다**
2. execution을 거쳐 산출·저장된 return/NAV 시계열에 대한 분석 — attribution, correlation, factor regression처럼
   기존 result를 읽으며 **새 return을 만들지 않는다**
3. explicit academic listing, hypothetical fill, signed state-transition rule을 사용하는 가상 execution
4. order, production position/account, actual fill을 통과하는 **executable real short portfolio**

첫 번째 층만 execution state를 경유하지 않는다. **새로운 portfolio return을 만드는 것은 세 번째 층부터이며,
두 번째 층은 그 이상의 층이 만든 result를 읽는 분석이다.** quantile spread와 signed basket return처럼 basket
수익률을 뜻하는 지표는 첫 번째 층이 아니라 세 번째 층 경로로 산출한다.

세 번째와 네 번째 층은 같은 fill → commit → valuation lifecycle을 사용하되, 서로 다른 run과 명시적으로 다른
state-transition validity, venue rule, realism label을 갖는다. `hypothetical_short`의 음수 position은 research
관측을 위한 committed hypothetical state이며 borrow, 담보, 차입 비용, locate 가능성을 모델링하지 않는다.

### 8.2 ETF look-through는 user-authored Strategy behavior다

ETF look-through는 ETF position에서 **자동으로 발생하는 package behavior가 아니다.** ETF registration, 보유
수량, constituent dataset이 존재한다는 이유만으로 look-through를 켜지 않는다.

constituent data는 source identity, `available_at`, instrument/constituent identity, weight unit을 표현하는
user-provided PIT data다. mapping, coverage, stale/revision 처리, normalization, cash residual의 경제적 의미는
**Strategy가 소유한다.** vqapr는 ETF ticker를 근거로 dataset을 자동 발견하거나 누락된 구성종목을 추정하지
않는다.

Strategy가 decision time $t$의 actual portfolio state에서 만든 physical weight를 $p_t$, 자신이 소비한 구성종목
데이터로 만든 mapping을 $L_t$라 하면 constituent exposure는 예를 들어 $x_t = L_t p_t$로 계산할 수 있다.
**이 식은 vqapr의 내장 ETF semantics가 아니라 Strategy가 선택할 수 있는 계산 예시다.**

#### UC-LOOKTHROUGH-001 — 명시적 ETF exposure 계산

constituent A/B를 각각 50% 보유한 ETF와 A direct stock을 함께 보유해도 vqapr는 instrument나 account position만
보고 look-through를 자동 수행하지 않는다. user가 Strategy에 constituent dataset binding과 actual account state
requirement를 명시하고 둘을 직접 소비한 경우에만 Strategy code가 constituent exposure를 계산한다. 그 Strategy는
direct stock과 ETF constituent exposure를 **정확히 한 번** 합산하고 physical cash/residual을 별도로 취급한다.
같은 ETF를 아무 constituent binding 없이 사용하는 다른 Strategy에서는 ETF가 opaque physical instrument로
남아야 한다.

#### UC-LOOKTHROUGH-002 — PIT constituent consumption

ETF 구성이 바뀌었지만 새 observation의 `available_at`이 decision time보다 늦으면 vqapr는 그 observation을
노출하지 않는다. look-through를 선택한 Strategy는 그 시각에 읽을 수 있는 구성종목만 소비하고, snapshot 선택,
coverage, stale/revision 처리, 재정규화 여부를 자신의 경제적 규칙으로 명시한다.

#### UC-LOOKTHROUGH-003 — Actual holding을 읽는 recomputation

ETF와 direct stock이 체결된 뒤 가격 drift 또는 다음 rebalance가 발생하면 Strategy는 다음 decision에서
requested target이 아니라 그 시점에 허용된 **marked actual portfolio state**를 읽어 exposure를 다시 계산한다.
vqapr는 계산값을 account에 자동 주입하거나 다음 Strategy에 자동 feedback하지 않는다. user가 결과를
publish한다면 consumed constituent binding, actual-state identity, target/actual 구분을 lineage로 보존하며
**intended exposure를 actual compliance state로 가장하지 않는다.**

---

## 9. Artifacts, catalog, evidence

의미 있는 dataset, signal, weight, decision, execution result, analysis는 producer와 process를 넘어 읽을 수 있는
versioned artifact로 보존한다. 목적은 class hierarchy를 노출하는 것이 아니라 **재현, 비교, lineage, safe
reuse**다.

### 9.1 Typed and portable

serialized data는 적합한 typed object로 읽을 수 있어야 하며 object 생성 시 schema와 semantic invariant를
validation한다. unknown type/version, invalid key, incompatible semantics를 raw dictionary로 통과시키지 않는다.

pickle, experiment-tracking run, process memory는 유용한 internal representation일 수 있지만 **유일한 public
result가 아니다.**

#### UC-ARTIFACT-001 — External producer round-trip

외부 process가 documented artifact schema로 signal을 저장한다. vqapr는 이를 typed object로 읽고 local
Strategy에 전달한다. producer의 internal class를 import하지 않아도 compatibility와 lineage를 검사할 수 있어야
한다.

#### UC-ARTIFACT-002 — Invalid serialized result 거부

weight artifact의 logical key가 중복되거나 declared semantics와 payload가 맞지 않는다. object construction 또는
publication이 실패하고 invalid artifact는 catalog의 reusable success로 노출되지 않는다.

### 9.2 Dependency graph와 identity

artifact는 **실제** input artifact/data/config와 producer identity를 가리킨다. 같은 frozen identity와
compatible output이 이미 있으면 재사용할 수 있고, input이나 semantic contract가 달라지면 별도 result로
취급한다. content hash만 같다는 이유로 서로 다른 경제적 의미를 합치지 않는다.

경제적으로 다른 cadence, calendar, Strategy version, execution profile, account validity, data source를 같은
run으로 취급하지 않는다.

### 9.3 Publication은 원자적이다

publication은 payload와 metadata가 함께 durable하게 commit되었을 때만 성공한다. **partial write는 reusable
artifact로 보이지 않아야 한다.** 실패한 research도 error identity, stage path, frozen input, log reference를
남겨 agent가 다음 action을 제안하고 안전한 retry 여부를 판단할 수 있게 한다.

#### UC-ARTIFACT-003 — 동시 publication과 중단

concurrent publication과 process interruption에서도 partial result가 reusable success로 보이지 않고, conflict,
idempotency, recovery outcome이 결정적이어야 한다.

#### UC-RESEARCH-001 — 실패를 보존한 뒤 보강해 retry

Strategy가 benchmark-weight requirement 부족으로 실패한다. catalog는 성공 result 대신 failure evidence를
남긴다. user가 benchmark data를 등록한 뒤 새 invocation이 이전 error와 resolution lineage를 연결해 성공하며,
**실패 기록을 삭제하지 않는다.**

### 9.4 Intended와 realized를 나란히 보여준다

report는 최소한 다음을 구분해 보여준다.

- intended target
- requested order
- dealt quantity와 fill
- committed position / cash / NAV
- rounding, clipping, rejection, missing-data reason
- 선택한 profile, state-transition validity, realism limitation

#### UC-REPORT-001 — 같은 result의 여러 renderer

하나의 backtest result를 table, chart, machine-readable report로 표현한다. renderer가 달라도 return, cost,
exposure, failure count의 underlying value와 lineage는 같아야 한다.

#### UC-MONITOR-001 — Monitoring finding report

actual-account finding을 daily report로 만든다. report는 breach와 missing input을 구분하고, **intended target을
actual holding처럼 섞지 않는다.**

### 9.5 Workspace autonomy

project는 supported local 또는 external storage option을 선택할 수 있다. storage option이 달라도 artifact
identity, validation, durability, observable publication outcome은 같아야 한다. locking, database schema, payload
format, directory layout은 architecture가 결정한다.

### 9.6 Reuse 판정

identity와 compatibility가 일치하면 stored signal, model prediction, alpha weight, ensemble result, intended
portfolio를 producer rerun 없이 사용할 수 있다. reuse는 단순 path 복사가 아니며 consumer는 artifact schema와
semantic type, time/axis/universe/currency compatibility, input·producer fingerprint, path-dependency와
actual-state dependency, terminal status와 coverage, parent/member lineage를 검사한다.

---

## 10. Failure discipline

### 10.1 Hierarchical operation error

모든 workflow를 하나의 거대한 표준 stage 목록에 맞추지 않는다. 실행한 operation이 자신의 stage path를
세분화해 보고하고, **사용하지 않은 optional stage는 나타나지 않는다.**

```text
dataset.register.key_uniqueness
strategy.run.requirements.universe
execution.submit.constraint_validation
account.reconcile.fills
```

package error는 최소한 다음을 machine-readable하게 제공한다.

- 실패한 operation과 hierarchical stage path
- 충족되지 않은 requirement ID와 bounded diagnostic
- state 또는 artifact가 commit되었는지 여부
- retry 전에 충족해야 할 precondition과 idempotency 정보
- 상관관계 추적을 위한 error identity

resolution candidate와 user에게 물을 질문은 package의 고정 error schema가 아니라 agent layer가 결정한다(§2.6).

#### UC-ERROR-001 — Optional stage가 없는 짧은 workflow

등록된 signal을 단순 분석하는 workflow는 model training, optimization, order, execution stage를 생성하지 않는다.
분석 입력이 부족하면 실제 경로인 `analysis.run.requirements`에서 실패한다. **존재하지 않는 optional stage를
통과한 것처럼 보고하거나 unrelated capability를 미리 요구해서는 안 된다.**

### 10.2 명시적 실패가 silent fallback보다 우선한다

다음은 같은 success type으로 숨기지 않는다.

- tradable instrument만 남기고 target weight를 자동 재정규화
- untradable target을 reason 없이 skip
- solver constraint를 제거하거나 current portfolio를 target처럼 반환
- missing analysis dependency를 warning만 남기고 required output을 생략
- unknown field, instrument, exposure axis를 임의로 제외
- 비슷한 field, 이전 price, 다른 cost policy로의 silent fallback
- failed artifact publication을 complete로 표시
- **explicit execution과 accounting을 거치지 않고 계산한 값을 portfolio return, NAV, PnL, turnover로 보고**

이 목록은 **built-in에도 동일하게 구속된다.** 특히 첫 항목은 built-in weighting 함수가 결측 종목을 빼고
나머지를 재정규화하는 경우를 포함한다. 그 편의는 사용자가 요청하지 않은 portfolio를 만들면서 그 사실을
호출부에도 evidence에도 남기지 않으므로, built-in이 저지르면 오히려 더 나쁘다(§2.7).

constraint adjustment의 unresolved residual, advisory validation breach, actual-account breach, evaluator runtime
failure는 서로 다른 result/status다. adjustment result가 존재한다는 이유로 compliant success를 선언하지 않고,
advisory breach를 execution failure로 바꾸거나 actual breach를 계산 failure로 숨기지도 않는다.

#### UC-RETURN-001 — Return authority

signal analysis는 non-portfolio diagnostic만 만들고, portfolio return/NAV/PnL/turnover는 explicit
execution/accounting result에서만 나온다.

### 10.3 Mutation 경계

- pre-commit 단계의 실패는 position, cash, version, journal을 **하나도** 바꾸지 않는다.
- commit 이후의 publication 실패는 mutation 여부와 정확한 account version을 기록한다.
- retry는 같은 operation identity와 expected account version에서만 idempotent해야 한다.
- **failure를 warning-and-skip으로 숨기지 않는다.**

### 10.4 Workflow completion status

각 stage는 다음 중 하나로 끝난다.

- `complete` — required output과 validation이 모두 존재
- `incomplete` — 일부 output은 있으나 requirement 미충족
- `failed` — deterministic contract 또는 runtime failure
- `unsupported` — 선택한 component/profile이 capability를 제공하지 않음

**required output에 대한 warning-and-skip은 `complete`가 될 수 없다.**

---

## 11. Agent surface

### 11.1 Bundled agent skill

vqapr distribution은 현재 package version과 일치하는 agent skill resource를 포함해야 한다. project onboarding은
사용자가 선택한 coding-agent environment에서 이 skill을 사용할 수 있게 한다.

skill은 다음을 담당한다: public status·capability inventory·schema·example·error 조회, package error와 skill
지침에서 복수의 resolution 경로 구성과 설명, 경제적 의미가 필요한 선택의 user 확인, user-confirmed project
config 또는 local extension 작성과 package validation 호출, 같은 public operation retry와 result·limitation·
changed files 요약.

skill은 public error의 stage를 기준으로 version-matched guidance를 찾고, 해당 단계의 계약, 자주 발생하는 실패,
가능한 복수의 해결 경로, user confirmation이 필요한 선택, retry할 public operation을 제시한다.

agent-specific instruction file은 bundled skill과 installed documentation을 찾게 하는 **thin routing layer**다.
product fact와 schema를 agent-specific file에 복제해 stale하게 만들지 않는다.

### 11.2 Skill entrypoint — normative product contract

다음 path는 selected target이 skill을 발견하기 위해 사용하는 **normative product contract**다. 일반적인
directory convention이나 architecture candidate가 아니다.

| target | skill directory | required entrypoint |
|---|---|---|
| Codex | `.agents/skills/vqapr/` | `.agents/skills/vqapr/SKILL.md` |
| Claude Code | `.claude/skills/vqapr-skill/` | `.claude/skills/vqapr-skill/SKILL.md` |
| explicit custom root | `<user-selected-output>/vqapr/` | `<user-selected-output>/vqapr/SKILL.md` |

custom target root는 user가 명시적으로 선택해야 하며 package가 임의의 output location을 추측하지 않는다. 각
skill directory 안의 `references/`, `scripts/`, `examples/` 같은 보조 resource는 해당 target protocol과 generated
manifest가 허용하는 범위에서 둘 수 있다.

### 11.3 Safe and idempotent onboarding

onboarding은 project file을 소유한다고 가정하지 않는다. 실행 전에 target agent, 생성·수정할 exact path,
instruction file의 managed block, skill resource version, validation command를 preview하는 **dry-run**을 제공해야
한다.

실제 적용은 다음을 만족한다.

- 기존 `AGENTS.md`, `CLAUDE.md` 같은 instruction file을 발견하고 **vqapr가 소유하는 marked block만**
  추가·갱신·제거한다.
- supported instruction file이 없으면 creation target을 preview하고 user가 요청한 경우에만 새로 만든다.
- 같은 target과 version으로 반복 실행해도 duplicate block, duplicate skill, 의미 없는 diff를 만들지 않는다.
- 여러 agent target을 선택하면 각 target의 변경을 독립적으로 보여주고 검증한다.
- 생성한 skill file이 user에 의해 수정되었으면 content fingerprint 차이를 감지하고 명시적 확인 없이 덮어쓰지
  않는다.
- update는 vqapr-owned file/block만 갱신하고 같은 directory의 user-owned extension file을 보존한다.
- remove는 vqapr-owned block과 확인된 generated file만 제거하며 instruction file의 나머지 내용이나 project
  artifact를 삭제하지 않는다.
- 결과에 package version, skill schema/version, target type을 기록하고 target별 structure를 validation한다.

#### UC-ONBOARD-001 — Preview / apply / update / remove

installed project에서 onboarding 변경을 preview, apply, update, remove할 수 있고 product-owned 영역만 안전하고
idempotent하게 변경한다.

### 11.4 Optional sample journey

fresh user가 전체 mental model을 확인할 수 있도록 package는 명시적으로 materialize할 수 있는 작은 sample data,
sample project-local logic, config, expected result를 제공한다.

```text
sample data registration
|-> direct Strategy: signal + signed weights + research backtest
|-> Model output -> Strategy: signed weights + research backtest
|-> optional Ensemble Strategy
|-> optional physical / enhanced-index construction -> selected execution profile
-> portable artifacts, report, catalog lookup
```

sample은 reference journey이지 hidden built-in alpha나 mandatory starter layout이 아니다. user가 요청하지 않은
project에 자동 생성하지 않으며, 생성된 file은 product-owned example과 user-owned research code를 구분해야 한다.

---

## 12. Product boundaries

### 12.1 Frozen invocation과 incremental configuration

한 operation이 시작되면 그 invocation이 소비하는 config, binding, data cutoff, component identity를 **동결한다.**
동시 수정은 다음 invocation에만 반영한다. failure evidence도 같은 frozen input identity를 가리켜야 안전한
retry와 비교가 가능하다.

**freeze 시점은 operation이 시작될 때다.** 그 전에 어떤 순서로 config를 조립했는지는 규정하지 않는다. user나
agent는 instrument와 execution assumption 같은 environment decision을 한 번에 모두 입력하지 않고 **점진적으로**
확정할 수 있어야 한다. 이 요구는 §1.4와 §4.2의 인터뷰 기반 onboarding에서 나온다 — agent는 "어떤 종목을
거래하나요", "체결 가정은 무엇인가요"를 한 번에 하나씩 확인한다. 거대한 spec 생성자를 한 번에 채우는 표면만
제공하면 그 대화 형태를 표현할 수 없다.

두 behavior를 함께 유지한다.

- **frozen input은 완전하다.** 이전의 mutable configuration을 암묵적으로 다시 읽지 않고, 보존된 input만으로
  실행과 재현이 가능해야 한다.
- **run은 시작 시점의 설정을 본다.** invocation 시작 후의 project 변경은 그 run의 identity를 바꾸지 않는다.

환경변수, mutable global default, 실행 시점의 암묵적 file discovery는 frozen result identity 밖에 남지 않는다.
누적 상태의 세션 간 persistence는 current requirement가 아니다.

#### UC-CONFIG-001 — 점진적 구성과 완전한 freeze

user가 여러 번의 상호작용으로 execution environment를 구성한 뒤 run을 시작한다. 시작된 run은 complete frozen
input과 안정적인 identity를 유지하고, 이후 project 변경의 영향을 받지 않는다.

### 12.2 Config는 의미를 선언하지만 의미를 대신하지 않는다

config-driven workflow는 reproducibility를 위한 수단이다. 비슷한 field name, class path, default 값이 경제적
의미를 확정하지 않는다. **user-confirmed binding과 validated contract만 frozen config에 들어간다.**

### 12.3 Local extension

project-local extension은 user가 선택한 source, version, validated parameter로 명시적으로 식별할 수 있어야
한다. **source를 찾거나 load할 수 있다는 사실만으로 compatibility가 증명되지 않는다.** vqapr는 allowed
extension boundary, capability/type validation, semantic input/output binding, version과 source fingerprint,
safe error classification, portable resolved config, bounded loading error와 partial registration 방지를
deterministic하게 validation한다.

local code validation은 security sandbox나 dependency installer를 의미하지 않는다.

#### UC-EXTENSION-001 — Agent가 만든 local transform의 검증

built-in 예시를 참고해 agent가 project-local neutralization transform을 작성한다. package validation이 input
requirement, PIT behavior, output artifact를 검사한다. 실패하면 agent는 error를 설명하고 수정안을 제시하며,
성공하기 전까지 compatible component로 등록하지 않는다.

#### UC-EXTENSION-002 — Project-local Strategy의 검증과 재현 가능한 실행

fresh installed project에서 user가 documented public contract만 사용하는 local Strategy를 작성한다. Strategy는
필요한 dataset/artifact와 output semantics를 선언하고 package validation을 통과한 뒤에만 reusable extension으로
등록된다. 이후 research 또는 daily execution은 user가 선택한 **exact registered version**을 사용하고 실제
dependency를 result에 남긴다. 등록 뒤 source나 contract가 바뀌면 이전 registration을 암묵적으로 latest code에
연결하지 않고 **compute 전에 drift를 명시적으로 보고**해야 한다.

### 12.4 누가 무엇을 소유하는가

**vqapr가 소유:** project initialization과 frozen invocation, logical dataset registration과 capability binding,
field semantics·unit·currency·timezone·universe·tradability 구분, point-in-time materialization과 bounded access,
signal/alpha weight/ensemble/intended portfolio/artifact contract, Model result·Strategy intent·execution
profile·actual-state result 사이의 compatibility, order conversion semantics와 clipping/failure diagnostics,
constraint declaration·adjustment·validation·finding contract, signed alpha diagnostics와 long-only physical
construction, instrument semantics와 execution-policy resolution, portable artifact envelope·lineage·catalog·
reporting, trigger와 run 종료 evidence 확정, actual-account monitoring, agent-readable documentation과
stage-based error.

**user project가 소유:** source data와 그 경제적 의미, availability·delivery lag·restatement 가정, universe·
benchmark·sector·factor 정의, signal model과 alpha policy code, risk·cost·constraint·execution policy, constraint
metric의 경제적 의미와 bound, compliance reference data의 applicability, project-local extension과 report
composition, research objective와 promotion decision.

**external production runtime / OMS가 소유 (future boundary):** broker connectivity·authentication·secret,
broker-specific identifier와 order type, order slicing·pacing·venue·retry·replace·cancel, always-on scheduling과
account polling, market-session operational control와 kill switch, validation override approval과 alert delivery,
confirmed order·fill·reject reason·account snapshot publication.

**vqapr는 broker SDK wrapper나 always-on OMS가 아니다.**

### 12.5 금지 behavior

- reference implementation fork를 기본 product runtime으로 사용
- position-direction contract 없이 negative position을 executable short라고 주장
- requested target을 realized holding으로 취급
- process-global provider를 concurrent run 사이에서 무보호 mutation
- current target을 반복 제출해 hold를 흉내 내고 price-drift rebalance 생성
- 한 decision의 order diagnostic을 마지막 한 건만 보존
- composite account return을 signed active strategy return으로 사용
- constraint adjustment result를 independent validation 없이 compliant로 표시
- requested/hypothetical state를 actual compliance monitoring state로 사용
- compliance-only data를 undeclared strategy input으로 전달
- pickle-only result를 portable public artifact라고 주장
- consumer-purpose alias를 dataset registration에 새기는 것
- session calendar를 data coverage에서 유도하는 것

---

## 13. Current scope와 future work

### 13.1 Current scope

physical simulation의 현재 scope는 **주식과 ETF**다. 별도 academic profile은 Stock, ETF, Index, Factor의
hypothetical signed evaluation을 지원한다.

- cross-sectional signed signal과 alpha research
- ML training/inference (model implementation은 project 소유)
- stored signal/alpha reuse와 ensemble
- long-only enhanced-index physical portfolio
- zero-friction fractional academic execution profile
- ETF의 physical/opaque 처리와 user Strategy가 명시적으로 PIT constituent data를 소비해 계산하는 look-through
- historical backtest와 portable research catalog
- actual fill, marked state, bounded strategy state에 의존하는 path-dependent Strategy
- 하나의 portfolio에서 여러 주식·ETF와 shared cash를 함께 처리하는 multi-instrument simulation
- daily observation/valuation, 선택적 lower-frequency decision, 독립 monitoring을 결합하는 multi-frequency workflow
- selective decision trigger, explicit hold, dense actual-account evidence
- standalone constraint adjustment, advisory pre-execution validation, independent monitoring artifact
- MVP hard constraint: no-short와 time-varying single-name cap
- **지원되는 order의 전량 체결과 주식·ETF cash의 즉시 결제를 가정한 simulation**
- 가격 축을 갖춘 source 또는 §4.4로 등록한 derived unit price를 사용하는 closed-loop research

### 13.2 Out of scope — 지원한다고 추정하지 않는다

- borrow, locate, margin, recall, borrow fee를 포함한 executable real short
- derivative margin, funding, expiry, 강제청산의 complete lifecycle
- dividend/distribution과 기타 instrument lifecycle cash flow
- partial fill, pending/cancel order state, 실제 주식·ETF settlement cycle
- prepared production decision, external OMS reconciliation, live account authority
- direct broker connectivity, secret management, always-on OMS/scheduler, alert delivery
- user가 제공하지 않은 availability, universe, shortability truth의 자동 추정
- merger, spin-off, delisting을 포함한 security-master event의 **원천 해석·변환**
- unbounded autonomous strategy state mutation
- **중단된 run의 재개** — 실패하거나 중단된 run은 current scope에서 처음부터 다시 실행한다

merger, spin-off, delisting처럼 instrument identity, tradability, reference state를 바꾸는 사건의 해석과 변환은
vqapr가 아니라 **security master와 ETL pipeline의 책임**이다. vqapr는 향후에도 원천 corporate action을 자체
해석하지 않고 이미 정규화된 instrument/reference data만 소비한다. 따라서 이것은 vqapr의 readiness gap이 아니다.

### 13.3 Future characterization — current support가 아님

이 절의 use case는 향후 확장 시 만족해야 할 경계를 미리 고정한다. **현재 지원을 의미하지 않는다.**

#### UC-FUTURE-001 — 만기 있는 증거금 계약

만기, contract multiplier, settlement currency가 있는 Future position은 settlement time마다 variation margin을
cash에 반영하고 만기에는 final settlement와 position 종료를 수행해야 한다. 만기 이후 주문은 거부되어야 한다.

#### UC-PERP-001 — 만기 없는 perpetual contract

expiry가 없는 perpetual position은 정해진 funding time에 당시 관측 가능한 funding rate로 cash flow를 발생시키고
position을 유지해야 한다. 이 상품에는 expiry event나 final expiry settlement를 만들지 않는다.

#### UC-CASHFLOW-001 — 거래비용과 lifecycle cash flow의 구분

fill fee와 tax만 transaction cost로 집계한다. 향후 dividend/distribution, variation margin, perpetual funding을
지원한다면 transaction cost가 아닌 **lifecycle cash flow**로 별도 집계하고 account cash/PnL에 명시적으로
commit해야 한다. 해당 data와 policy가 없으면 cash flow를 자동 추정하지 않는다.

#### UC-SETTLEMENT-001 — 주식·ETF 실제 결제주기

MVP는 주식과 ETF의 fill 원금·비용이 즉시 cash에 반영된다고 가정한다. unsettled cash, receivable/payable,
settlement calendar, buying-power 차이는 future work이며 **현재 결과 limitation에 즉시 결제 가정을 남긴다.**

#### UC-PROD-001 — Partial fill 뒤의 다음 decision

prepared order 100주 중 OMS가 40주만 체결한다. 다음 decision은 requested 100주가 아니라 confirmed 40주와
actual cash를 사용한다. 남은 60주의 pending/cancel 상태가 불명확하면 추정하지 않고 reconciliation error를 낸다.

#### UC-PROD-002 — Rejected decision의 state 보존

OMS가 주문을 reject한다. rejection evidence는 보존하지만 vqapr는 intended position을 actual로 commit하지 않는다.
전송 성공이나 OMS 접수는 execution 완료가 아니며, confirmed fill·rejection·cancellation·account snapshot만
authoritative result로 들어온다. duplicate delivery는 같은 decision을 두 번 적용하지 않아야 한다.

#### UC-RECOVERY-001 — 중단된 run의 재개

process interruption 뒤 동일 frozen identity를 중복 decision/fill/state update 없이 재개하고, changed identity는
mutation 전에 분기 요구로 실패한다. 장시간 run이나 production 연속 운영에서 재개 수요가 검증되면 별도 product
decision으로 추가한다.

#### UC-IMPACT-001 — Market impact

market impact를 지원하려면 authoritative volume, PIT binding, price-impact semantics, fee 중복 방지 계약을 먼저
정의한다.

#### UC-REAL-SHORT-001 — Executable real short

executable real short를 지원하려면 borrow, locate, collateral, margin, proceeds, recall, fee authority를 함께
검증한다.

### 13.4 Asset-class 확장의 조건

새 asset class는 **type label 추가로 완료되지 않는다.** quantity/notional, valuation, permitted direction, cost,
settlement, actual feedback이 closed loop에서 일관되게 작동해야 한다. 각 확장은 새 requirement를 해당
workflow에서 발견하고, 기존 minimal registration이나 무관한 research를 막지 않아야 한다.

---

## 14. Acceptance criteria

acceptance는 내부 class, stage 수, storage layout이 아니라 **이 PRD의 observable use case**로 판정한다.

### 14.1 Onboarding과 data

- fresh project에서 installed docs와 bundled skill만으로 minimal data registration을 시작할 수 있다.
  (`UC-ONBOARD-001`, `UC-FACADE-001`)
- `UC-DATA-001`처럼 field 이름을 강제하지 않고 selected binding, logical key, selected field만 validation한다.
  universal observation timestamp나 consumer-purpose price role을 요구하지 않는다.
- availability가 불명확하면 `UC-AGENT-001`처럼 agent가 look-ahead와 delay-rule 후보를 설명하고 user가 선택한다.
- 아직 사용하지 않는 metadata나 optional workflow requirement가 최초 registration을 막지 않는다.
- requirement gap은 `UC-DATA-002`, `UC-ERROR-001`처럼 package error → agent 제안 → user 결정 → package
  validation → safe retry로 이어진다.
- frozen invocation과 `available_at <= evaluation_time`을 위반하는 data access는 거부된다. (`UC-TIME-001`,
  `UC-CONFIG-001`)
- `UC-PIT-001`의 forward-return label materialization은 계산 전에 explicit horizon을 resolve하고, 누락 시
  reusable success를 만들지 않는다.
- `UC-LOOKBACK-001`의 exact lookback이 store query까지 강제되고 coverage가 evidence에 남는다.

### 14.2 Research composition

- `UC-SIGNAL-001`의 direct Strategy와 `UC-SIGNAL-002`의 stored model output 경로가 모두 동작한다.
- `UC-MODEL-001`처럼 portfolio 없이 Model signal을 연구·평가·저장할 수 있다.
- `UC-MODEL-002`에서 statistical factor-return estimate를 executed portfolio return/NAV로 표시하지 않는다.
- signed weight는 budget semantics와 actual dependency를 보존하고 producer 재실행 없이 재사용할 수 있다.
- `UC-ALPHA-BUDGET-001`에서 flexible residual을 fixed budget으로 자동 확대하지 않는다.
- `UC-BUILTIN-001`에서 built-in weighting 함수가 data/state/clock에 접근하지 않고, 부수 입력의 결측에 계산 전
  실패하며, 종목을 빼고 재정규화하지 않는다. 제외된 종목은 호출자에게 값으로 반환되어 evidence에 남는다.
- `UC-ALPHA-PATH-001`에서 path-dependent result를 producer rerun 없이 frozen member input으로 소비하고, source
  state identity와 반영 범위를 새 lineage에 보존하며 current-state recomputation으로 표시하지 않는다.
- `UC-STATE-001`에서 체결이 없는 세션과 run 경계를 넘어 strategy state가 이어지고, 다음 run의 시작 state는
  명시적으로 지정된다. state 갱신이 execution 발생 여부에 종속되지 않는다.
- `UC-TRIGGER-001`에서 Strategy가 선언한 cadence와 local decision time을 frozen venue calendar와 결합한 판단
  시점이 실행 결과와 일치한다. 해당 시각에 data row가 없어도 event는 성립하며, 판단하지 않은 session은 실패로
  기록되지 않는다.
- `UC-ENSEMBLE-001`에서 기존 Strategy result를 member로 조합하고 ticker-level netting과 lineage를 확인할 수 있다.
- `UC-ALPHA-CHILD-001`은 같은 exact parent intent를 Strategy/Model 재실행 없이 두 execution convention에서
  비교하며 parent result는 불변이다. adaptive scenario는 `UC-ALPHA-ADAPTIVE-001`의 state/evidence를 별도로
  만족한다.

### 14.3 Construction, execution, monitoring

- constraint가 없는 research는 `UC-CONSTRAINT-001`처럼 실행되고, constraint workflow는 필요한 data를 호출
  시점에 발견한다. (`UC-CONSTRAINT-002`)
- academic long-short, peer momentum, top-N long-only, enhanced index처럼 executable한 모든 Strategy는
  construction 규칙이 달라도 **frozen intended portfolio → execution-time order conversion → selected profile →
  fill → account commit → valuation → feedback**의 같은 observable lifecycle을 따른다. (`UC-PORTFOLIO-001`,
  `UC-PROFILE-001`)
- adjustment와 advisory validation은 `UC-CONSTRAINT-ADJUST-001`처럼 residual과 compliance finding을 구분하며,
  breach만으로 execution을 차단하지 않는다.
- `UC-EXEC-001`에서 decision과 execution outcome을 분리하고 committed result만 다음 decision에 feedback한다.
- `UC-EXEC-002`는 fill timing과 model limitation을 명시하며 look-ahead를 허용하지 않는다.
- **fractional/lot quantity는 selected venue가 instrument별로 결정한다.** account validity는 signed 또는
  long-only position transition만 검사하며, 두 profile에서 같은 atomic commit/history/valuation 결과 shape를
  사용한다. (`UC-ACADEMIC-001`)
- `UC-COST-001`~`UC-COST-004`, `UC-CLOSED-LOOP-001`, `UC-SCALE-001`, `UC-LOOKTHROUGH-001`~`003`의
  current-scope outcome을 만족한다.
- path-dependent, multi-instrument, multi-frequency 시나리오에서 actual-state-dependent decision, shared portfolio
  state, independent cadence를 검증한다.
- `UC-ACCOUNT-HISTORY-001`처럼 strategy state 없이 actual state 이력만으로 stop-loss와 cooldown을 표현할 수 있고,
  이력 접근이 strategy state 보유 여부에 종속되지 않는다. 계좌 session 시계열과 instrument panel을 선택해
  구독할 수 있다.
- `UC-EXEC-003`처럼 decision이 없는 evaluation time에도 monitoring finding을 만든다.
- unsupported short, lifecycle, cost policy를 다른 profile의 default로 조용히 대체하지 않는다.
- partial fill, pending/cancel, 실제 settlement cycle, production OMS behavior를 current support로 표시하지 않는다.
- portfolio return, NAV, PnL, turnover는 explicit execution/accounting 경로에서만 산출된다. (`UC-RETURN-001`)

### 14.4 Artifacts, reports, extensions

- `UC-ARTIFACT-001`처럼 producer의 private class 없이 serialized result를 typed object로 읽고 validation한다.
- `UC-ARTIFACT-002`의 invalid payload와 partial publication을 reusable success로 노출하지 않는다.
  (`UC-ARTIFACT-003`)
- 실패와 retry history는 `UC-RESEARCH-001`처럼 queryable evidence로 남는다.
- `UC-REPORT-001`, `UC-MONITOR-001`에서 stored result를 재실행 없이 report하고 actual과 intended state를
  구분한다.
- `UC-EXTENSION-001`에서 agent가 만든 local transform의 compatibility를 package가 deterministic하게 판정한다.
- `UC-EXTENSION-002`에서 local Strategy를 documented public contract로 검증·등록하고 user-selected exact
  version으로 실행하며 source drift와 implicit latest selection을 compute 전에 거부한다.

---

## 15. Compatibility gates

compatibility gate는 구현 구조가 아니라 **기존 observable result의 의미가 보존되는지** 판정한다.

### 15.1 Reference 또는 calculation 변경

reference code, borrowed calculation, cost/metric rule을 바꾸면 source provenance와 영향받는 use-case ID를
식별한다. frozen fixture에서 numerical result뿐 아니라 requested/dealt quantity, actual-state timing, PIT cutoff,
unsupported failure, evidence가 이전 contract와 일치하거나 **명시적으로 versioned change**여야 한다.

### 15.2 Runtime 또는 component 변경

Model, Strategy, execution mechanism, artifact backend, extension mechanism을 교체해도 다음을 재검증한다.

- same frozen input의 deterministic replay
- decision과 execution outcome의 분리 및 actual feedback
- hold/no-trade monitoring과 run 종료 결과의 이어받기
- typed artifact round-trip, failure evidence, dependency lineage
- §14의 acceptance scenario 전체

**internal class나 callback 이름의 parity는 요구하지 않는다.**

### 15.3 Schema 변경

old artifact는 안전하게 읽히거나 explicit migration/unsupported error를 제공해야 한다. schema change가 logical
identity, producer-independent loading, path-dependent source state lineage, partial publication 무결성,
actual/intended state separation을 깨뜨려서는 안 된다. 여러 source state를 하나의 fabricated identity로 합쳐서도
안 된다.

### 15.4 Test 철학

test는 PRD use case의 input, observable outcome, authority, evidence를 검증한다. prototype의 우연한 class name,
private import, file layout, 고정 global stage 목록, 특정 validation library를 제품 requirement로 승격하지 않는다.

---

## 16. 결론

vqapr는 하나의 고정 research pipeline을 강제하지 않는다. 최소한의 semantic binding으로 시작하고, 선택한
workflow가 필요로 하는 requirement를 실행 시점에 발견하며, package의 deterministic error와 validation을 agent가
user decision으로 연결한다.

제품이 보존해야 할 핵심은 다음과 같다.

1. **`available_at <= evaluation_time`과 exact `rows`/`calendar` lookback의 PIT integrity**
2. **event time과 data row time의 분리** — 판단 시각은 데이터가 아니라 venue calendar와 strategy 선언에서 온다
3. direct Strategy, stored model output, ensemble Strategy의 선택 가능한 composition
4. path-dependent Strategy, multi-instrument portfolio, multi-frequency workflow
5. **portfolio return을 주장하는 모든 것은 하나의 execution spine을 통과한다**
6. Model result, Strategy decision, execution outcome의 semantic 분리
7. **committed actual state만이 authority다** — intended ≠ requested ≠ dealt ≠ committed
8. **fractional/lot은 venue listing이, 음수 position 허용은 account validity가 결정한다**
9. producer-independent typed artifact, lineage, failure evidence, safe reuse
10. decision과 독립적인 actual-account monitoring

reference implementation, 특정 class hierarchy, global stage enum, storage backend, validation library는 이 의미를
구현하는 **수단이지 목적이 아니다.**

---

## Appendix A. Use-case index

| ID | 절 | scope |
|---|---|---|
| `UC-FACADE-001` | §1.4 | current |
| `UC-TIME-001` | §3.2 | current |
| `UC-TRIGGER-001` | §3.3 | current |
| `UC-LOOKBACK-001` | §3.5 | current |
| `UC-DATA-001` | §4.1 | current |
| `UC-AGENT-001` | §4.2 | current |
| `UC-DATA-002` | §4.3 | current |
| `UC-PIT-001` | §4.3 | current |
| `UC-MODEL-001`, `UC-MODEL-002` | §5.1 | current |
| `UC-SIGNAL-001`, `UC-SIGNAL-002` | §5.2 | current |
| `UC-ENSEMBLE-001` | §5.4 | current |
| `UC-ALPHA-BUDGET-001` | §5.5 | current |
| `UC-BUILTIN-001` | §2.7 | current |
| `UC-ALPHA-PATH-001`, `UC-ALPHA-CHILD-001` | §5.6 | current |
| `UC-STATE-001`, `UC-ALPHA-ADAPTIVE-001` | §5.7 | current |
| `UC-PORTFOLIO-001` | §6.2 | current |
| `UC-EXEC-001`, `UC-EXEC-002` | §6.3 | current |
| `UC-PROFILE-001`, `UC-ACADEMIC-001` | §6.4 | current |
| `UC-COST-001` ~ `UC-COST-004` | §6.5 | current |
| `UC-ACCOUNT-HISTORY-001`, `UC-CLOSED-LOOP-001`, `UC-SCALE-001` | §6.6 | current |
| `UC-EXEC-003` | §6.8 | current |
| `UC-CONSTRAINT-001`, `UC-CONSTRAINT-002`, `UC-CONSTRAINT-ADJUST-001` | §7 | current |
| `UC-LOOKTHROUGH-001` ~ `003` | §8.2 | current |
| `UC-ARTIFACT-001` ~ `003`, `UC-RESEARCH-001` | §9 | current |
| `UC-REPORT-001`, `UC-MONITOR-001` | §9.4 | current |
| `UC-ERROR-001`, `UC-RETURN-001` | §10 | current |
| `UC-ONBOARD-001` | §11.3 | current |
| `UC-CONFIG-001` | §12.1 | current |
| `UC-EXTENSION-001`, `UC-EXTENSION-002` | §12.3 | current |
| `UC-FUTURE-001`, `UC-PERP-001`, `UC-CASHFLOW-001`, `UC-SETTLEMENT-001` | §13.3 | future |
| `UC-PROD-001`, `UC-PROD-002`, `UC-RECOVERY-001`, `UC-IMPACT-001`, `UC-REAL-SHORT-001` | §13.3 | future |
