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

이 문서가 `StrategyModel`, `DataModel`, `Account`, `Exchange` 같은 이름을 쓸 때는 **제품의 semantic role**을 뜻한다.
Python class를 뜻하지 않는다.

특히 **DataModel**과 **StrategyModel**은 두 semantic role의 이름이다. 같은 이름의 class, 상속 관계, 공통
부모를 요구하지 않는다. 두 역할이 무엇을 공유하고 그것을 어떤 구조로 구현할지는 architecture가 정한다.

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
- DataModel 또는 deterministic transform이 재사용 가능한 signal, feature, label, risk estimate를 만들어 축적한다.
- StrategyModel이 point-in-time data와 선택적 DataModel result를 소비해 경제적 판단을 만든다.
- 기존 StrategyModel을 member로 참조하는 ensemble StrategyModel이 저장된 결과를 조합하고 ticker 수준에서 netting한다.
- 판단을 실행 가능한 portfolio로 확정하고, 선택한 execution profile로 closed-loop simulation한다.
- StrategyModel decision과 독립적으로 schedule된 시점에 actual account를 monitoring한다.
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
   DataModel, StrategyModel, execution의 의미를 다시 정의하지 않는다.

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
DataModel materialization, StrategyModel research, composition, portfolio construction, execution, analysis, report를
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
registered PIT data -> DataModel / transform -> reusable research result -> analysis / reuse
   여기서 끝나도 완결된 workflow다. portfolio return을 주장하지 않기 때문이다.

[execution spine]
StrategyModel decision
  -> mandatory portfolio construction
  -> frozen intended portfolio
  -> execution-time order conversion (현재 committed state + 현재 PIT input)
  -> selected execution profile
  -> fills
  -> committed account state
  -> valuation / mark
  -> feedback -> 다음 StrategyModel decision
```

**규칙:** 새로운 portfolio return, NAV, PnL, turnover를 만드는 모든 workflow는 이 spine을 끝까지 통과한다.
우회 경로는 없다.

이 규칙이 막는 것은 구체적이다. weight 벡터와 다음 기간 수익률을 곱해 합산한 값을 backtest 결과라고
부르는 것, quantile spread나 signed basket return을 signal 분석 결과에 포함시키는 것, 거래비용·체결
가능성·현금 제약을 통과하지 않은 수치를 성과로 보고하는 것이다. 이런 값들은 execution과 accounting을
거치지 않았으므로 **이 제품에서는 portfolio return이 아니다.**

academic long-short와 physical long-only는 서로 다른 lifecycle이 아니라 **같은 lifecycle에 서로 다른
profile을 적용한 결과**다.

### 2.3 DataModel과 StrategyModel은 분리된 semantic role이다

사용자가 작성하는 계산에는 두 역할이 있다.

| | 답하는 질문 | 출력 | execution | 계좌 |
|---|---|---|---|---|
| **DataModel** | *"이 값은 얼마인가"* | **값** | **거치지 않는다** | 없다 |
| **StrategyModel** | *"자본을 어떻게 나눌 것인가"* | **배분** | **반드시 거친다** | 있다 |

#### 판정 기준은 execution을 거치는가다

**배분은 체결될 수 있다.** 그리고 체결되면 return이 생기므로 §2.2에 따라 반드시 execution을 통과해야 한다.
**zero-friction academic profile을 선택해도 마찬가지다** — 비용이 0일 뿐 체결, 계좌 반영, feedback은 그대로
일어난다. **배분을 만들고 실행을 건너뛰는 경로는 없다.**

**값은 체결될 것이 없다.** 시가총액이나 베타를 "체결한다"는 말은 성립하지 않는다. 그래서 DataModel의 연산은
execution 앞에서 끝나며, 그 자체로 완결된 workflow다.

#### 계좌 접근은 이 차이의 결과다

- **배분을 만드는 역할은 계좌를 본다.** 체결 결과가 자기에게 돌아오므로 현재 보유와 이력을 볼 수 있어야
  한다 — turnover-aware rebalance, stop-loss, adaptive weighting이 전부 그것을 요구한다
  (`UC-ALPHA-PATH-001`, `UC-ACCOUNT-HISTORY-001`, `UC-ALPHA-ADAPTIVE-001`).
- **값을 만드는 역할에는 계좌가 없다.** 시가총액이 누구의 계좌냐에 따라 달라지면 그건 시가총액이 아니다.
  값이 계좌에 의존할 이유가 없으므로 DataModel은 actual state를 읽지 않는다.
- **배분은 계좌에 의존해도 된다.** 그 경우 path-dependent임을 드러내고 어떤 state를 보았는지 남기면 다른
  연구가 frozen input으로 재사용할 수 있다(§5.6).

> 계좌를 보느냐로 두 역할을 가르면 틀린다. 어떤 배분이 계좌를 쓰지 않을 수도 있지만, 그것이 그 역할이
> 계좌를 **볼 수 없다**는 뜻은 아니다.

#### DataModel은 필수 단계가 아니다

StrategyModel이 필요한 계산을 직접 수행해도 된다. DataModel은 **여러 소비자가 같은 값을 나눠 쓰거나 반복
계산을 피하기 위한 선택**이지 선행 조건이 아니다(§2.7).

> **Architecture candidate — non-normative**
>
> 두 역할은 *언제 계산할지 선언하는 방식*과 *이전 계산을 이어가는 방식*을 공유한다. 공통 부모를 두어 그
> 선언을 한 곳에 모으면 해석하는 코드가 하나가 되고, 새 cadence 종류를 추가할 때 한쪽만 고치는 사고가
> 없다. 같은 요구를 만족하는 다른 구조도 허용한다.

**DataModel**은 point-in-time data를 소비해 다른 연구와 StrategyModel이 재사용할 수 있는 research result를 만든다.
prediction, signal, feature, firm characteristic, risk estimate, statistical factor-return estimate가 대표적이다.
DataModel의 정상적인 종착점은 reusable result와 그 평가 evidence이며, portfolio나 order를 만들 필요가 없다.

**StrategyModel**은 registered data와 선택적 DataModel result, 필요하면 actual portfolio state와 bounded strategy
state를 소비해 경제적 decision을 만든다. deterministic rule만으로 판단하는 StrategyModel은 DataModel을 선행 조건으로
요구하지 않는다.

두 result는 경제적 의미가 다르다. **signal을 weight로, statistical estimate를 executed portfolio return으로,
intended target을 actual holding으로 가장해서는 안 된다.** 같은 구현이 내부에서 signal과 weight를 연속
계산할 수는 있지만 public result와 acceptance에서는 두 역할을 구분해야 한다. 이것은 별도 Python class나
process를 두라는 요구가 아니다.

factor return도 마찬가지로 구분한다.

- cross-sectional regression coefficient나 statistical factor estimate는 **DataModel result**로 만들 수 있다.
- 실제 factor portfolio의 return, NAV, PnL, turnover는 **execution spine을 거친 결과**여야 한다.

### 2.4 Committed runtime state만 authority다

vqapr에는 서로 바꾸어 쓸 수 없는 두 개의 runtime authority가 있다.

1. **Account authority** — committed fill과 mark가 만든 cash, position, cost, NAV와 그 이력
2. **Model-state authority** — DataModel 또는 StrategyModel이 명시적으로 commit한 bounded private
   computational state

Model state는 작은 strict-JSON `memory`와 선택적인 Model 고유 **private state payload**로 구성될 수 있지만,
둘은 하나의 state identity로 함께 저장·복원된다. committed state만 다음 Model invocation의 정상 입력이며,
working checkpoint, recorder, 임의의 로컬 파일은 authority가 아니다.

나머지는 authority가 아니다. intended portfolio, requested order, constraint adjustment result,
monitoring finding, evidence는 **의도와 영수증**이다.

따라서 다음 네 단계를 항상 구분한다.

```text
intended  ≠  requested  ≠  dealt  ≠  committed
(목표)       (주문)       (체결)     (계좌 반영)
```

- StrategyModel intent는 fill도 realized holding도 아니다.
- simulation의 committed fill은 현실의 체결은 아니지만 **그 run의 authoritative execution result**다.
- 다음 decision은 requested target이 아니라 committed holding, cash, execution result를 본다.
- blocked 또는 zero-dealt order를 fill로 가장하지 않으며, 다음 decision이 이를 구분해 읽을 수 있다.
- monitoring finding은 prior fill을 rollback하거나 account를 소급 변경하지 않는다.

### 2.5 Durable typed artifact가 public integration point다

signal, alpha weight, ensemble weight, intended portfolio, constraint declaration/adjustment, order,
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

사용자 고유의 signal model과 alpha logic은 project가 소유한다. **project-local StrategyModel이 alpha logic의
primary extension point**다. 사용자는 installed vqapr나 `site-packages`를 수정하지 않고 compatible한 local
Python implementation을 작성·검증·등록할 수 있어야 한다. DataModel이나 deterministic materialization은 그
StrategyModel이 reusable intermediate data를 요구할 때 선택하는 optional component이며 direct StrategyModel의 선행
조건이 아니다.

각 extension point마다 public input/output contract, machine-readable requirement와 schema, built-in과 같은
contract를 따르는 minimal working template, validation command, stage-specific error를 제공한다.

**dataset도 같은 대우를 받는다.** 등록 가능한 dataset이 만족해야 하는 조건 역시 machine-readable하게
발행된다(§4.0). 확장점만 계약을 발행하고 data는 안 하면, user의 agent가 무엇을 만들어야 하는지 알 수
없는 채로 준비를 시작하게 된다.

vqapr가 reference component를 제공할 수는 있지만 **project-owned proprietary alpha를 package built-in에
가두지 않는다.**

#### Built-in 계산 helper는 순수하다

구현이 어렵거나 실수하기 쉬운 계산만 built-in으로 제공한다. pandas·numpy·Python standard library로
명확하게 표현되는 one-liner를 package API로 다시 감싸지 않는다.

- **signal transform** — tie-aware Decimal rank, exact weighted neutralization, 그리고 reference market에서
  threshold를 계산해 전체 universe에 적용하는 명시적 Fama-French breakpoint
- **weighting** — 균등 배분, 크기 비례 배분, 예산 재조정

둘 다에 다음 제약이 붙는다. 이것이 없으면 built-in은 편의 함수가 아니라 **보이지 않는 곳에서 경제적
판단을 내리는 두 번째 StrategyModel**이 된다.

- registered data, account state, clock, execution profile에 **접근하지 않는다.** 필요한 값은 전부 인자로
  받는다. 크기 결정에 외부 panel(시가총액 등)이 필요하면 그 panel을 호출자가 넘긴다. 그래야 그 data가
  StrategyModel의 declared requirement를 거쳐 §4.6의 lineage에 남는다.
- **budget을 스스로 결정하지 않는다.** 선언된 것보다 적게 배분된 결과를 자동으로 채우지 않는다(§5.5).
- **결측을 조용히 처리하지 않는다.** 요구한 부수 입력이 없으면 계산 전에 실패하고, 해당 종목을 빼고
  나머지를 재정규화하지 않는다(§10.2).
- 연구 결과 자체의 결측 해소는 built-in weighting의 책임이 아니다. 별도의 명시적 built-in으로 제공하되,
  **어떤 종목이 왜 제외되었는지가 호출자에게 값으로 반환되어** result evidence에 실릴 수 있어야 한다.
- 같은 입력에 같은 출력을 낸다. run identity, decision time, account version을 알지 못하므로 실행 가능한
  intent를 스스로 만들지 못한다. intent 조립과 lineage 기록은 StrategyModel의 책임이다(§6.2).

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

### 2.9 BYOD — Bring Your Own Data

vqapr는 데이터를 소유하지도 가져오지도 않는다. vendor connector, downloader, bundled market dataset은 제품
범위가 아니다. **연구 데이터와 그 경제적 의미는 user project가 소유한다**(§12.4).

이 원칙은 두 방향으로 작동하며, 둘이 함께 있어야 성립한다.

- **의미를 강제하지 않는다.** field 이름, universe, currency, 관측 주기, asset class를 package가 미리 정하지
  않는다. 무엇이 instrument이고 어떤 값이 무엇을 뜻하는지는 user가 binding하며, 지금 필요하지 않은 semantic을
  미리 요구해 등록을 막지 않는다(§4.1).
- **형식을 읽어주지 않는다.** 원천이 xlsx든 database dump든 vendor API든, 그것을 선언된 columnar dataset으로
  만드는 것은 user project와 그 agent의 일이다. package는 형식 변환, 스키마 추론, 인코딩 처리, 시트 구조
  해석을 하지 않는다(§4.0).

**임의의 데이터를 받아들인다는 것은 임의의 형식을 읽는다는 뜻이 아니라 의미를 강제하지 않는다는 뜻이다.**

한쪽만 취하면 원칙이 무너진다. 의미도 형식도 열면 package 안에 임의 형식 reader가 들어오고, 형식을 닫으면서
의미를 package가 정하면 그것은 이미 user의 데이터가 아니다.

#### 따라오는 세 가지 의무

1. **package는 계약을 발행한다.** user 쪽이 무엇을 만들어야 하는지 error 이전에 알아야 하므로, 등록 가능한
   dataset이 만족해야 하는 조건을 machine-readable하게 발행한다(§4.0).
2. **만드는 쪽과 판정하는 쪽이 갈린다.** 계약을 만족하는 산출물을 만드는 것은 user 쪽이고, 만족하는지
   판정하는 것은 package다. package가 대신 만들어 주지 않으며, user가 판정을 대신하지도 않는다.
3. **준비를 돕는 것은 skill이다.** 원천을 읽어 축, availability, 체결 시각과 가격의 후보를 제안하는 것은
   agent가 자기 도구로 하는 일이며 package operation이 아니다(§11.1, §4.4).

가장 어려운 판단인 `available_at`도 이 원칙을 따른다. **package가 대신 고르지 않는다** — 추측하는 순간
look-ahead가 조용히 들어오고, 그 판단의 근거는 데이터가 아니라 도메인에 있기 때문이다(§4.2).

예외는 하나다. **계산이 만든 데이터의 `available_at`은 package가 정한다.** 그 값은 실제로 소비한 관측에서
결정되므로 생산자가 주장할 것이 아니다(§4.1, §4.5). 그 외에는 계산 결과도 원본과 같은 등록 계약을 따른다.

---

## 3. 시간과 point-in-time correctness

### 3.1 Operation occurrence와 세 timestamp authority를 분리한다

| 사실 | 의미 | 소유자 |
|---|---|---|
| **operation occurrence** | `(role, stable occurrence ID, evaluation_time)` entity | 해당 component configuration이 참조하는 frozen `OperationAgenda` |
| **evaluation time** | 현재 operation이 observation과 committed state를 읽는 cutoff | frozen occurrence |
| **availability time** | observation을 처음 사용할 수 있는 시각 (`available_at`) | dataset registration |
| **execution time** | accepted intent가 exact venue snapshot에서 실행되는 시각 | `FillConvention` |

`OperationAgenda`는 cron, RRULE, calendar inference가 아니다. run 시작 전에 이미 timezone-aware instant와 stable
occurrence identity의 유한한 순서로 resolve된 immutable economic input이다. StrategyModel, Valuation,
MonitoringPolicy configuration은 같은 agenda 형식을 사용하되 **각자 독립적인 agenda를 참조**한다.
RunDefinition은 그 reference를 바꾸지 않고 resolved identity와 inclusive `[start, end]` slice를 freeze한다.

observation row와 execution row는 occurrence가 아니다. daily observation을 intraday callback에서 읽거나,
minutely observation을 daily callback에서 읽을 수 있다. 같은 날짜에 callback이 zero, one, many일 수 있고
execution table에 390개 row가 있어도 390개 callback이 생기지 않는다.

### 3.2 PIT의 유일한 보편 술어

모든 data consumer는 다음만 만족하는 observation을 읽는다.

$$
available\_at \le evaluation\_time
$$

- StrategyModel의 evaluation time은 current callback occurrence의 instant다.
- order conversion과 execution validation의 evaluation time은 selected execution time이다.
- valuation과 monitoring은 각자 current occurrence를 evaluation time으로 사용한다.
- actual account snapshot의 `as_of`는 evaluation time보다 늦을 수 없다.

event timestamp가 dataset row로 존재할 필요는 없다. `2024-03-06 04:00` callback은 04:00 observation row가
없어도 발생하고, `available_at == 04:00`인 row는 보지만 1 microsecond 늦은 row는 보지 못한다.

Observation availability는 event를 emit하지 않는다. StrategyModel, child research, model inference가
permitted cutoff를 우회해 source를 직접 읽어서는 안 된다. compliance evaluator가 independent data를 읽어도
그 값은 explicit dependency와 availability cutoff 없이 Strategy input으로 자동 전달되지 않는다.

vqapr가 보장하는 것은 **선언된 availability의 준수**다. source의 실제 경제적 공시 시점에 대한 최종 확인은
user가 내리고, bundled agent skill이 근거 있는 후보를 제시한다(§11).

#### UC-TIME-001 — 명시적 timezone과 모호한 timestamp의 거부

모든 stored timestamp는 UTC instant로 정규화할 수 있는 aware datetime이어야 한다. agenda와 FillConvention의
local-date/time semantics는 explicit IANA timezone identity를 사용한다. 서로 다른 zone 이름은 같은 instant로
변환 가능하다는 이유만으로 충돌하지 않으며, ordering과 PIT 비교는 normalized instant로 수행한다.

DST 때문에 ambiguous/nonexistent한 local datetime은 artifact 생성 전에 explicit offset/fold로 하나의 instant로
resolve되어야 한다. resolve되지 않은 local time, naive datetime, 중복 occurrence identity, duplicate normalized
instant + stable ID, 결정적으로 정렬할 수 없는 occurrence와 모순된 timestamp는 관련 mutation 전에 실패한다.
same-day selector의 date는 FillConvention venue timezone으로 변환한 local date다. naive datetime을 임의의
timezone으로 해석하지 않는다.

### 3.3 Callback opportunity와 decision cadence를 분리한다

**user는 StrategyModel configuration을 읽고 어떤 callback agenda를 쓰는지 알 수 있어야 한다.** 긴 occurrence
목록은 immutable artifact에 둘 수 있지만 그 reference는 StrategyModel configuration의 명시적 경제 입력이다.
RunDefinition이나 Flow가 숨은 default로 바꾸지 않는다.

Flow는 frozen callback agenda의 current occurrence를 하나씩 전달한다. StrategyModel은 committed memory로
warm-up, cooldown, N번째 callback과 지금 판단할지를 계산해 다음 둘 중 하나를 반환한다.

```text
NoDecision        이번 callback opportunity에는 판단하지 않았다
PortfolioIntent   이번 callback opportunity에 frozen economic intent를 만들었다
```

agenda는 **호출 기회**만 정하고 decision을 미리 계산하지 않는다. StrategyModel은 전체 agenda나 future
occurrence를 보지 않는다. `NoDecision`도 성공한 invocation이므로 output validation 뒤 Model state를 commit하며,
이미 accepted된 pending intent가 있으면 그대로 유지한다. callback 자체가 실패하면 이전 committed Model state와
pending intent를 유지한다.

같은 callback agenda를 받아도 StrategyModel마다 committed state와 규칙으로 다른 decision cadence를 만든다.
보유기간, 회전율과 실제 리밸런싱 주기는 execution 결과에서 사후 계산한다. 판단해서 유지한 것과 판단하지 않은
것은 §6.7에 따라 구분한다.

DataModel materialization은 Strategy callback agenda를 공유하지 않는다. materialization operation이 지정한
evaluation times에서 계산하며 observation row, Strategy counter나 execution table에서 그 시각을 유도하지 않는다.

#### UC-TRIGGER-001 — 상태 있는 decision cadence

StrategyModel이 callback count를 committed memory에 보존하고 5번째 opportunity마다 판단한다. Flow는 frozen
agenda occurrence를 빠짐없이 전달할 뿐 5번째 decision을 미리 선택하지 않는다. 첫 네 callback은
`NoDecision`과 갱신된 state를, 다섯 번째 callback은 `PortfolioIntent`를 만든다. run을 나누더라도 다음 run의
initial state를 명시하면 같은 progression을 이어간다.

### 3.4 OperationAgenda는 execution input이 아니다

Strategy callback, valuation, monitoring은 role별 독립 finite `OperationAgenda`가 공급한다. ExecutionTable은
그 agenda의 날짜, frequency, occurrence를 만들거나 지우지 않는다.

```text
observation dataset    available_at <= evaluation_time으로 bounded consumer가 읽는다
OperationAgenda        callback·valuation·monitoring occurrence와 identity를 공급한다
execution table        selected execution_time의 exact venue snapshot을 Flow/Exchange만 읽는다
```

StrategyModel에는 current occurrence 하나만 전달한다. 전체 agenda, future occurrence, ExecutionTable,
execution-time price와 tradability로 가는 접근 경로가 없다. Flow는 agendas를 검증·freeze·merge·dispatch하지만
경제적 cadence나 decision을 만들지 않는다.

별도 venue calendar parquet, holiday inference와 calendar provider는 current 전제조건이 아니다. Project가
finite agenda를 준비하는 과정은 package runtime 밖이며, package는 frozen resolved occurrences만 소비한다.

#### UC-CALENDAR-001 — retired current requirement

이 ID는 재사용하지 않는다. daily 가격 coverage나 ExecutionTable에서 venue calendar 또는 callback schedule을
유도하는 capability는 current product contract에서 제거되었다. `OperationAgenda`는 open/close 의미나 미래 venue
상태를 제공하는 calendar가 아니라 component invocation의 명시적 유한 시각 목록이다.

### 3.5 Bounded lookback

historical data access는 선택한 operation이 선언한 **exact lookback**을 강제한다. current product contract는
두 종류뿐이다.

- **`rows`** — PIT gate를 통과한 행을 registered logical key로 결정적으로 정렬한 뒤 **instrument와 field의
  조합별로** 최근 N행까지 반환한다. instrument별로만 세지 않는다. 같은 dataset의 field라도 관측 시점이 다를
  수 있으므로 *"각 field의 최근 N개"*가 요청의 의미다. 모든 field가 같은 행에 실려 있으면 두 해석이 같은
  결과를 만든다.
- **`calendar`** — user가 명시한 timezone의 evaluation date에서 years/months/days를 달력 산술로 이동한 date의
  00:00부터 evaluation time까지 `available_at`이 포함되는 행을 반환한다. 거래일 수를 세는 `sessions`
  semantics가 **아니다.**

두 종류 모두 `available_at <= evaluation_time` 상한을 바꾸지 않고 **store query에 직접 반영**한다. 전체
history를 먼저 읽은 뒤 StrategyModel code에서 자르는 경로를 bounded access로 간주하지 않는다.

**두 종류 모두 과거 방향이다.** 미래 관측을 당겨 읽는 lookback은 없다. 미래 구간이 필요해 보이는 계산은
값을 나중 시점에 기록하고 소비자가 시점을 맞춰 읽는 방식으로 표현한다 — 예를 들어 "$t$의 20일 후 수익률"은
"$t{+}20$에 기록된 20일 수익률"과 같은 값이며, 후자는 미래를 읽지 않는다.

**체결은 이 절의 대상이 아니다.** lookback은 관측을 읽는 규칙이고, 체결은 그 시점의 한 값을 조회하는
것이다(§6.3). 창도 lookback도 거치지 않는다.

`rows`보다 적은 행만 존재하면 있는 만큼 반환하고 requested/actual coverage를 access evidence에 기록한다.
dataset 전체의 `available_at_min`만으로 instrument별 coverage를 추정하거나, 행이 전혀 없는 instrument를
declared universe 없이 존재한다고 추측하지 않는다. 계산에 필요한 최소 관측치와 ragged-panel 처리 방식은
해당 StrategyModel의 경제적 규칙이다.

calendar lookback은 years/months/days 중 적어도 하나가 양수여야 하고 timezone과 month-end clamp policy를
frozen input에 보존한다. 동일 `available_at`의 순서는 registered logical key로 결정해 같은 input에서 같은 row
set을 만든다.

#### UC-LOOKBACK-001 — Store까지 강제되는 exact lookback

StrategyModel이 60 rows lookback을 선언하면 그 제한이 store query까지 전달되어야 하고, lookback을 선언하지 않은
historical read는 실패해야 한다. access evidence에는 요청한 lookback과 실제 coverage 정보가 남는다.

### 3.6 Frequency-agnostic finite agenda와 intent-derived execution

observation availability, Strategy callback, decision, execution, valuation, monitoring은 같은 instant일 수도,
서로 다른 cadence일 수도 있다. Strategy가 `NoDecision`을 반환하거나 callback이 없는 instant에도 valuation과
monitoring은 자기 agenda에 따라 독립적으로 실행한다.

Flow는 component agendas를 `(instant, fixed role priority, stable occurrence ID)`로 하나의 finite runtime
agenda에 merge한다. valid `PortfolioIntent`가 생기면 Flow가 current occurrence의 `evaluation_time`을
accepted-intent/evidence의 non-overridable `decision_time`으로 stamp하고, `FillConvention`이 그 값과 frozen
execution input으로 **엄격히 뒤인** exact target 하나를 선택한다. Strategy가 selector-authoritative timestamp를
제출하거나 바꿀 수 없으며 `effective_after`는 current contract에 없다.

한 Strategy·Account에는 accepted pending intent 하나만 있다. 새 intent는 target resolution이 성공한 뒤 기존
pending pointer를 교체한다. 이전 decision trace는 남지만 별도 `SUPERSEDED` artifact는 만들지 않는다.
`NoDecision`은 pending pointer를 바꾸지 않는다.

같은 instant에는 이전에 accepted된 due execution, fill/Account commit·execution-required valuation·feedback,
Strategy callbacks, independent valuation, independent monitoring 순서다. originating intent의 same-time
execution은 `execution_time > decision_time` 때문에 허용되지 않는다.

RunDefinition의 timezone-aware `[start, end]`는 모든 operation과 execution chain의 inclusive hard boundary다.
target 없음, `execution_time <= decision_time`, `execution_time > end`, invalid intent/timezone/provenance는 그
callback 전체의 atomic failure다. 새 Model state, decision evidence, pending pointer, Account와 execution state를
commit하지 않고 이전 committed authority와 immutable evidence를 유지한다. successful finalization에는 pending
intent가 없다.

#### UC-TIME-002 — frequency-independent operation timing

다음 구성은 모두 같은 product contract를 사용한다.

- daily observation + 같은 날짜의 여러 Strategy callbacks + same-day close execution
- minutely observation + daily callback + next eligible open execution
- callback 없는 시각의 valuation·monitoring
- denser execution table을 추가해도 변하지 않는 frozen callback occurrence 집합·시각·순서

Flow-stamped decision time, selected target/snapshot, pending replacement, mutation 여부, fixed-priority trace,
agenda identities/slices와 permitted cutoff가 evidence에 남아야 한다. complete frozen inputs가 같으면 전체
trace가 재현된다. execution row density만 바꾼 비교에서 full downstream trace 동치는 selector-relevant target
candidates, selected snapshot, price/tradability, policy와 나머지 frozen inputs가 같고 추가 rows가
non-selected일 때만 요구한다.

intraday callback은 current capability다. partial fill, child order, TWAP/VWAP/pacing과 live wall-clock scheduling은
future work다.

---

## 4. Data registration과 requirement discovery

이 절의 목적은 처음부터 완전한 dataset schema를 요구하는 것이 **아니다.** vqapr는 현재 작업에 꼭 필요한
semantic binding만 먼저 확인하고, 실제 workflow component를 호출할 때 추가 requirement를 발견한다.
**등록 성공은 모든 downstream workflow와의 호환성 보증이 아니다.**

### 4.0 입력 계약 — 무엇을 읽고 무엇을 읽지 않는가

이 절은 §2.9 BYOD 원칙이 등록 단계에서 무엇을 뜻하는지 정한다.

vqapr는 **선언된 columnar dataset을 읽는다.** 원천이 무엇이든 — xlsx, csv, 데이터베이스 덤프, 벤더
API — 그것을 읽을 수 있는 형태로 만드는 것은 **user project와 그 agent의 책임**이다(§12.4).

package는 형식 변환, 스키마 추론, 인코딩 처리, 시트 구조 해석을 **하지 않는다.** 임의 형태의 연구
데이터를 받아들인다는 것은 임의 형식을 읽는다는 뜻이 아니라 **의미를 강제하지 않는다**는 뜻이다.

이것은 §4.4가 return→unit price 변환에 대해 이미 정한 것과 같은 경계다 — *"변환은 package operation이
아니다. agent skill이 가정을 설명하고 user가 확정하며, 결과 dataset은 동일한 최소 등록 계약을 따른다."*

#### 그래서 package는 계약을 발행해야 한다

user의 agent가 무엇을 만들어야 하는지 알아야 한다. 따라서 package는 **등록 가능한 dataset이 만족해야
하는 조건을 machine-readable하게 발행**한다. 이것은 error 이후가 아니라 **작업이 시작되기 전에** 필요하다.

발행되는 계약은 최소한 다음을 말한다: 요구되는 파일 형태, `available_at`의 의미와 타입, instrument와
logical key의 역할, field 선택 방식, 그리고 각 조건이 충족되지 않을 때의 stable error identity.

**계약을 만족하는 산출물을 만드는 것은 user 쪽이고, 만족하는지 판정하는 것은 package다.** package가
대신 만들어 주지 않으며, user가 판정을 대신하지도 않는다.

### 4.1 최소 등록

logical dataset은 physical file과 구분되는 versioned reference다. 최초 등록은 다음 semantic role만 요구한다.

1. instrument를 식별하는 field
2. observation을 사용할 수 있게 된 시점을 담은 **`available_at` 컬럼** (tz-aware)
3. 해당 dataset의 logical row key
4. 등록할 data field의 선택
5. **선택한 field 각각의 타입 선언** (`TIMESTAMP_TZ` · `DATE` · `INTEGER` · `DOUBLE` · `VARCHAR` · `BOOLEAN`)
6. 선언된 physical source identity

**타입은 user가 선언하고 package가 1회 대조한다** (2026-09-08 판정, `docs/issues/088`). parquet을
만드는 쪽이 user이므로 그 컬럼이 무엇인지도 user가 말한다. 등록은 파일을 `DESCRIBE`해서 선언과 다르면
거부하고, 같으면 그 선언이 dataset의 사실이 된다 -- consumer는 `DOUBLE` field를 `float`으로, `INTEGER`를
`int`로 받으며 그 사이의 변환은 없다. `DECIMAL` 컬럼은 선언할 수 없고 거부된다: 데이터 평면의 숫자는
한 종류씩이고, exact 산술은 execution 경계의 돈 쪽에 있다. 이는 `available_at`의 tz-aware 요구와 같은
모양의 계약이다 -- 계약이 타입을 말하고, user가 준비하고, package가 판정한다.

`available_at`은 **user가 준비 단계에서 계산해 넣은 컬럼**이다. package는 그 값이 어떤 가정에서 나왔는지
묻지도, 규칙으로 받아 평가하지도, 별도로 기록하지도 않는다 — **그 판단은 전적으로 user의 것이다.**
package가 하는 일은 명확한 디렉션을 주는 것과, 들어온 컬럼이 계약을 만족하는지 판정하는 것뿐이다.

field 이름은 강제하지 않는다. `ticker`, `symbol`, `종목코드` 중 무엇이 instrument인지 user가 binding한다.
기본 instrument-time panel에서는 `(available_at, instrument)`가 null 없이 해석 가능하고 유일한지 검사한다.
같은 instrument와 time에 여러 행이 필요한 event/long-form dataset은 event ID나 sequence 같은 추가 key axis를
선언하거나 별도 logical dataset으로 등록한다.

**`available_at`만이 모든 dataset에 공통으로 특별 취급되는 시간 경계다.** `fiscal_period`, `session_date`,
`event_time`, `revision`, `horizon_end`, unit, currency, universe coverage, missingness는 source가 제공하는
일반 column 또는 metadata다. 이를 필요로 하는 consumer가 명시적으로 요구하고 해석하며, 아직 선택하지 않은
workflow 때문에 최초 등록을 막지 않는다.

**field는 이름과 물리 위치의 binding이며, 물리 컬럼일 필요가 없다.** 등록은 소비자가 쓸 이름을 정하고 그
이름이 source의 어디에 해당하는지를 잇는다. 한 파일의 컬럼일 수도 있고, field별로 나뉘어 저장된 여러
파일일 수도 있다. **소비자는 이 차이를 보지 않으며**, 저장 방식을 바꿔도 소비자의 requirement 선언은
변하지 않는다.

**이름을 바꾸는 것은 되고 role을 새기는 것은 안 된다.** 물리 컬럼 이름이 길거나 단위를 포함하거나
식별자로 쓸 수 없는 문자를 담는 것은 흔하므로, 등록이 안정적인 이름을 부여할 수 있어야 한다. 그러나
`research_close`, `execution_price`, `valuation_price` 같은 **role**은 registration에 새기지 않는다. 이름은
그 값이 무엇인지를 말하고 role은 누가 읽을지를 말하는데, 후자를 등록이 미리 정하면 같은 field를
StrategyModel, execution, valuation이 각자 자기 requirement로 선택했다는 사실이 사라진다. 그래야 하나의
field가 여러 목적으로 쓰일 때 어느 소비자가 실제로 무엇을 읽었는지 lineage에 남는다.

**등록이 성공했다는 것은 선언된 availability를 지키겠다는 뜻이지 등록된 값이 point-in-time으로 안전하다는
뜻이 아니다.** 등록 과정에서 만들어진 값이 미래 관측을 반영하고 있는지는 package가 판정하지 않는다.
사용자가 등록 단계에서 그런 계산을 하지 않아도 자신의 데이터 준비 과정에서 미리 계산해 올 수 있으므로,
한쪽만 검사하는 것은 검사가 아니며 **보장하지 않는 것을 보장하는 것처럼 보이게 만든다.** 이 경계는
§3.2가 정한 것과 같다. 위험한 준비 방식을 걸러내는 것은 등록 이전의 agent 인터뷰가 담당한다(§11.1).

#### 계산이 만든 데이터도 같은 계약을 따른다

DataModel이나 StrategyModel이 만들어 저장한 데이터도 위와 **동일한 등록 계약**을 따른다. 소비자는 그것이 원본
source인지 계산 결과인지 몰라도 **같은 방식으로 읽을 수 있어야 한다.** 계산 결과라는 이유로 별도의 공개
읽기 방식을 요구하지 않는다.

다만 한 가지가 다르다. **계산 결과의 `available_at`은 package가 정한다.** 그 값이 실제로 소비한 관측에서
결정되기 때문이다. 생산자가 자기 결과의 유효 시점을 직접 주장하지 않으며, 실제로 읽은 것보다 이른 시점을
주장할 수 없다. 이 규칙이 없으면 계산 한 단계를 거칠 때마다 PIT 경계가 느슨해진다.

> **Architecture candidate — non-normative**
>
> 계산 결과를 원본과 **같은 등록·조회 경로**로 다루면 다음이 따라온다. 다른 구조로 같은 요구를 만족해도 된다.
>
> - 소비자 쪽에 "원본이냐 파생이냐"를 구분하는 분기가 생기지 않는다.
> - PIT 처리(`available_at` 필터, lookback 경계)가 한 곳에만 존재한다. 계산 결과 전용 경로를 따로 두면
>   그 처리를 두 번 구현하게 되고, 둘이 어긋나는 순간 파생 데이터에서만 look-ahead가 생긴다.
> - 계산이 여러 단으로 이어져도 개념이 늘지 않는다. 2단째 계산이 1단째 결과를 읽는 것은 그냥 데이터를
>   읽는 것이다.

#### UC-DATA-001 — 최소 등록과 field-name 자율성

원천에 `DATE`, `CODE`, `VALUE`, `FISCAL_PERIOD` 컬럼이 있다. user는 준비 단계에서 daily close 행의
`DATE=2024-03-05`가 `2024-03-05 15:30 Asia/Seoul`에 알 수 있게 된다고 확정하고 **그 값을 `available_at`
컬럼으로 계산해 넣는다.** 그 뒤 `CODE`를 instrument로, `available_at`을 시간 축으로, `(DATE, CODE)`를
logical key로 binding하고 필요한 data field를 선택한다.

`FISCAL_PERIOD`는 StrategyModel이 필요할 때 요구하는 일반 column이다. package는 field 이름을 바꾸거나
universal observation timestamp를 추가하라고 요구하지 않는다. currency나 universe metadata가 없다는
이유만으로 이 단계가 실패해서는 안 된다.

### 4.2 Availability는 추측하지 않는다

`available_at`은 **user가 준비 단계에서 계산해 넣는 컬럼**이며(§4.0), 그 값이 무엇이어야 하는지는
package가 정하지 않는다. source date를 자동으로 00:00으로 해석하는 일도, 지연 규칙을 대신 고르는 일도
없다.

**그러나 그 결정은 어렵고 look-ahead의 주된 원인이다.** 그래서 결정 자체는 user에게 남기되 bundled agent
skill이 data category, source 설명, 공개 관행을 근거로 하나 이상의 candidate를 제시하고 각 candidate의
가정과 look-ahead 영향을 설명한다. 일봉 종가는 `DATE` 당일 장 종료 시각, 재무제표는 별도 공시 timestamp
또는 확인된 publication lag를 제안할 수 있다.

이 candidate는 package default가 **아니다.** user가 근거를 확인해 선택하고, **그 선택을 자신의 준비
과정에서 컬럼 값으로 실현한다.** package는 그 규칙을 config로 받지 않으며 따라서 평가하지도 기록하지도
않는다. package가 판정하는 것은 들어온 컬럼이 계약을 만족하는가 — tz-aware인가, null이 없는가, logical
key와 함께 유일한가 — 뿐이다.

이것이 §3.2가 정한 경계와 같다. **vqapr가 보장하는 것은 선언된 availability의 준수이지 그 선언이 옳다는
것이 아니다.**

#### UC-AGENT-001 — Availability 후보를 제시하는 질문

등록하려는 `DATE`가 관측일인지 실제 공개 시각인지 불명확하다. agent는 미래 정보 사용이 성과를 부풀리는
look-ahead 문제를 설명하고, 실제 release timestamp field 사용, source별 확인된 지연 규칙, data 보강 같은
후보를 제시한다. user가 근거와 함께 하나를 확정하면 agent는 그 값을 담은 `available_at` 컬럼을 만드는
준비 작업을 돕고, 그 결과를 package validation에 넘긴다. **근거가 확인되기 전에는 `DATE`를 그대로
`available_at`으로 삼지 않는다.**

### 4.3 Progressive requirement discovery

StrategyModel, model, optimizer, report, executor는 **실제로 호출될 때** 자신에게 필요한 capability를 선언한다.
등록된 dataset이 requirement를 충족하지 못하면 package는 해당 operation을 state mutation 전에 멈추고
structured error를 낸다. **이 실패는 기존 registration 전체를 무효화하지 않는다.**

agent는 error와 skill 지침을 바탕으로 다음 후보 중 의미가 맞는 방법을 user에게 제시한다: 기존 dataset에
binding 추가, 같은 physical source를 다른 semantic contract의 새 dataset으로 등록, derived dataset 생성,
requirement가 적은 workflow profile 선택, compatible local extension 작성.

어떤 후보가 적절한지는 data의 경제적 의미와 user intent에 달려 있다. **package는 선택된 결과가 requirement를
만족하는지만 deterministic하게 판정한다.**

#### UC-DATA-002 — Downstream workflow에서 발견된 benchmark-weight requirement

가격 StrategyModel은 최소 등록된 dataset만으로 실행되지만, single-name cap을 선택한 execution workflow는 execution
evaluation 시점의 time-varying benchmark-weight binding을 추가로 요구한다. 해당 workflow를 처음 호출할 때
package는 requirement 미충족을 보고하고 order나 account mutation을 만들지 않는다. agent는 benchmark dataset
신규 등록, 기존 dataset의 binding 보강, constraint 없는 research 선택을 제시한다. user 선택 후 validation에
성공하면 **그 operation만** 안전하게 retry할 수 있어야 한다.

#### UC-PIT-001 — 파생 계산이 요구하는 binding의 늦은 발견

회계 항목으로 firm characteristic을 만드는 계산이 `fiscal_period` binding을 요구한다. 어느 회계연도의 값을
어느 형성 시점에 대응시킬지가 그 계산의 경제적 규칙이기 때문이다. 그런데 input dataset에는 그 binding이
없다.

package는 **계산 전에** 실패하고 어떤 requirement가 부족한지 보고한다. agent는 계산 가능한 derived field인지,
별도 dataset이 필요한지, 다른 계산을 선택할지를 설명해 user의 결정을 받는다. **임의의 회계연도 정렬이나
보고 지연을 채우지 않는다.** binding 보강 뒤의 새 invocation은 이전 failure를 dependency로 연결하고,
그 시점까지 이용 가능한 값만 발행한다.

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

**어느 관측을 체결가로 쓸지는 명시적 선언이며 package가 대신 고르거나 대체하지 않는다.** 선언한 값이
없거나 유효하지 않으면 다른 값으로 떨어지지 않고 실패한다. 값의 이름이 그 선택을 대신하지 않는 것도
§4.1과 같은 이유다 — 이름이 시가처럼 보인다는 사실은 그것을 체결가로 쓰겠다는 선언이 아니다. 체결가가
어디서 오고 무엇이 그것을 선언하는지는 §6.3이 정한다.

### 4.5 Universe, tradability와 market metadata는 필요할 때 요구한다

universe와 tradability는 모든 dataset의 등록 조건이 아니다. 횡단면 비교, benchmark-relative construction처럼
**필요한 operation이** 각자 coverage, membership time, tradability requirement를 선언한다.

OHLCV, 거래정지, lot size, price source도 이를 사용하는 execution 또는 analysis profile에서 요구한다. 단순
signal 연구가 사용하지 않는 market field 때문에 막혀서는 안 된다. 반대로 **실제 주문 생성은 필요한 price,
lot, tradability binding이 없는데도 추정 default로 진행해서는 안 된다.**

#### 두 가지 tradability를 구분한다

같은 말이 서로 다른 두 시점의 서로 다른 질문에 쓰인다.

| 질문 | 언제 | 누가 | 어디서 |
|---|---|---|---|
| 이 종목을 후보로 볼 것인가 | 판단 시점 | StrategyModel | 등록된 dataset |
| 이 종목의 비중을 바꿀 수 있는가 | 판단 시점 | StrategyModel | 등록된 dataset |
| 이 주문이 실제로 체결되는가 | **체결 시점** | execution | §6.3의 체결 테이블 |

세 번째가 나머지와 **다른 시각에 평가된다는 것**이 핵심이다. 판단과 체결 사이에 거래가 정지될 수 있고,
그러면 전략이 알던 것과 체결이 아는 것이 어긋난다. **이것은 결함이 아니라 판단과 체결을 분리한 이유 그
자체이며**, 그 어긋남은 체결되지 않은 수량과 사유로 남는다(§6.3).

#### 투자 유니버스는 전략의 책임이고 선택이다

연구 대상을 좁히는 것은 시장 사실이 아니라 경제적 판단이므로 StrategyModel이 소유한다. 매 판단마다
계산해도 되고, 유동성 상위 100종목 같은 기준을 미리 계산해 저장한 뒤 그 결과를 소비해도 된다. 후자는
§4.1의 등록 계약을 따르는 보통의 dataset이다.

**만들지 않아도 된다.** 그 경우 거래 불가 종목에도 주문이 생성되고 체결되지 않은 채 사유와 함께 남는다.
전략이 몰랐고 시장이 알려준 것이므로 이것도 정상적인 결과다. package가 투자 유니버스를 요구하거나
대신 만들지 않는다.

#### 모르는 것은 값이 아니다

tradability는 **참/거짓 두 값**이며 "모름"이라는 세 번째 상태를 갖지 않는다. 방향에 따라 다른 값을 갖지도
않는다 — 매수만 불가능하고 매도는 가능한 상태는 현재 범위 밖이다(§13.2).

해당 시점과 종목에 대한 관측이 아예 없다면 그것은 값의 문제가 아니라 **coverage의 문제**이며, 그것을
요구한 operation이 계산 전에 실패한다. package가 없는 관측을 tradable로도 non-tradable로도 해석하지
않는다. 어느 쪽으로 다룰지는 경제적 판단이므로 user가 데이터를 채우거나 명시적으로 제외한다.

#### 거래정지 데이터가 없는 경우

정지 이력을 갖고 있지 않은 project가 일반적이다. 이때 package는 **추측하지 않고**, user가 §3.4의 calendar
유도와 **같은 절차**로 유도 규칙을 선언한다. bundled agent skill이 후보와 각각의 위험을 설명하고, user가
근거와 함께 고르며, package는 선택된 규칙을 deterministic하게 검증하고 frozen input과 result limitation에
기록한다.

| 규칙 | 위험 |
|---|---|
| 명시적 정지 이력 | 없음. 있으면 이것을 쓴다 |
| 거래대금 또는 거래량이 0 | 거래 부진과 정지를 구분하지 못한다 |
| 고가·저가·종가가 모두 같다 | 가격 제한 도달의 근사. 저유동성 종목에서 오탐 |
| 관측 행이 아예 없다 | **정지·수집 누락·상장 전·자료 절단을 모두 뭉갠다.** 위험이 가장 크다 |

마지막 규칙도 후보에 포함한다. 다른 자료가 없는 user가 실제로 도달하는 유일한 경로이므로 금지해도
우회될 뿐이고, 선언된 규칙은 frozen input에 남아 재현되고 감사할 수 있다는 점에서 조용한 추측과 정반대다.

#### UC-TRADABILITY-001 — 정지 데이터 없이 시작하는 project

user가 일별 시세만 갖고 있고 거래정지 이력이 없다. package는 임의로 정지를 판정하지 않고, agent가 유도
규칙 후보와 각각의 위험을 설명한다. user가 규칙을 선택하면 package는 그것을 검증하고 유도 방식과 한계를
result에 기록한다. 같은 규칙과 같은 data에서 같은 판정이 재현되며, 규칙을 바꾸면 경제적으로 다른 run으로
구분된다. 어떤 시점·종목에 대해 판정할 관측이 없으면 그것을 요구한 operation이 계산 전에 실패하고,
package가 tradable 또는 non-tradable로 추정하지 않는다.

### 4.6 Dependency binding

각 operation은 **실제로 소비한** logical dataset, artifact, config identity를 결과 lineage에 기록한다. 같은
source를 쓰더라도 StrategyModel input, compliance input, reporting input은 서로 다른 binding일 수 있다. 등록되어
있지만 해당 operation이 읽지 않은 field나 dataset은 dependency로 기록하지 않는다.

---

## 5. Research — DataModel과 StrategyModel

DataModel과 StrategyModel은 서로 다른 질문에 답한다. 두 역할은 독립적으로 실행·평가할 수 있으며 하나의 의무적인
pipeline을 공유하지 않는다.

```text
registered PIT data -> DataModel -> reusable signal / estimate / research result
registered PIT data ------------------------------------┐
reusable DataModel result ----------------------------------┼-> StrategyModel result -> analysis / reuse
actual portfolio state, when required ------------------┘                          |
                                          executable run을 선택했다면 --------------┘
                                                        |
                                   frozen intended portfolio -> execution spine (§6)
```

### 5.1 Reusable DataModel research

DataModel은 prediction, signal, feature, firm characteristic, factor exposure, risk estimate, statistical
factor-return estimate를 만들 수 있다. 결과는 경제적 의미, axis, unit, time semantics가 맞는 reusable result로
저장해야 하며, **서로 다른 결과를 모두 `signal`이라는 이름으로 뭉개지 않는다.**

#### DataModel 결과의 계약

- **§4.1의 dataset 계약을 그대로 따른다.** 소비자는 이것이 계산 결과인지 원본인지 몰라도 읽는다.
- **`available_at`은 package가 정한다**(§4.1). DataModel이 자기 결과의 유효 시점을 주장하지 않는다.
- **actual Account state를 소비할 수 없다**(§2.3). 계좌·체결에 의존하는 판단은 StrategyModel의 영역이다.
  다만 이전 Model state를 소비하는 순차 계산은 가능하다. account-state dependency와 model-state dependency를
  같은 `path-dependent` 표지 하나로 뭉개지 않는다.
- **배분을 만들지 않는다.** signal, characteristic, 분류처럼 계좌 없이 정의되는 값까지가 이 역할이며,
  그 값을 weight로 바꾸는 것은 StrategyModel의 판단이다.
- **execution을 거치지 않는다.** 체결될 것이 없기 때문이며, 그래서 DataModel run은 그 자체로 완결된다.

#### 반복 재학습은 새로운 capability를 요구하지 않는다

일정 구간으로 학습해 다음 구간을 예측하고 구간을 밀어가며 반복하는 방식(walk-forward)은 **이미 모든 계산에
적용되는 요구만 만족하면 된다.** 각 시점의 결과는 그 시점에 허용된 관측만 반영하고 자기 유효 시점을 갖는다.

따라서 전체 기간을 한 번에 학습해 만든 결과가 섞여 들어갈 수 없다 — 어느 시점에서도 그 시점 이후의 관측이
보이지 않기 때문이다. epoch별 학습 이력을 public result로 만들 필요는 없지만, 각 예측 결과는 자신이 소비한
committed Model state를 가리키고 그 state는 component/configuration과 training input/window identity를 보존해야
한다.

> **Architecture candidate — non-normative**
>
> walk-forward를 **execution loop 밖에서 미리 수행**하고 그 결과를 데이터로 남기는 구성을 권장한다.
> 같은 관찰 결과를 만드는 다른 구조도 허용한다.
>
> ```text
>  [밖] 학습 [20-01~06] → 예측 [20-07]  ┐
>       학습 [20-02~07] → 예측 [20-08]  ├→ 이어붙인 예측 데이터
>       ...                             ┘          │
>  [안] backtest는 그 데이터를 읽기만 한다  ◄───────┘
> ```
>
> 이 구성이 갖는 성질:
>
> - **학습이 계좌를 보지 않으므로** execution과 분리할 수 있다. 분리하지 못하는 경우(§13.2의 강화학습
>   계열)는 범위 밖이다.
> - 각 구간 학습이 **서로 독립이라 동시에 수행할 수 있다.**
> - backtest를 다시 돌리거나 전략을 바꿔 재실행해도 **재학습이 필요 없다.** 학습을 execution 안에 두면
>   실행할 때마다 반복된다.
> - 같은 예측 데이터를 **여러 전략이 나눠 쓸 수 있다.**
>
> 학습 주기와 예측 주기를 다르게 하고 싶다면(예: 월말 재학습 + 매일 예측), 학습 결과를 데이터로 남기고
> 예측 단계가 그중 그 시점에 유효한 것을 읽는 구성이 가능하다. 그러면 예측은 **고정된 학습 결과와 최신
> 입력**을 함께 쓰게 된다.

#### DataModel도 이전 계산을 이어갈 수 있다

DataModel은 이전 실행의 계산 상태를 다음 실행으로 이어갈 수 있으며, 그 규칙은 §5.7과 같다. 창이 한 칸 움직일 때
전체를 다시 계산하지 않고 증분으로 갱신하는 것이 대표적인 용도다.

이어가기를 선택하면 **결과가 순차 생성된다.** 시점 순서대로 만들어야 같은 값이 나오므로, 일부 구간만 다시
만들거나 병렬로 만들 수 없다. 그 사실이 결과에 남아야 하며, 그렇지 않으면 나중에 구간을 다시 생성하려는
시도가 조용히 다른 값을 만든다.

#### UC-MODEL-003 — Rolling CNN DataModel

DataModel이 직전 1,000거래일 residual로 CNN을 새로 학습하고 완료된 weight로 다음 125거래일의 종목별 score를
만든다. 다음 training boundary에서는 이전 subperiod weight를 warm start하지 않고 새 모델을 학습하며, 최종
DataModel result는 각 구간의 out-of-sample score를 시간축으로 연결한다. 같은 subperiod 안에서 중단된 학습은
§5.7의 working checkpoint로 재개할 수 있지만, 이것을 다음 subperiod로 weight를 이어 학습하는 것으로 해석하지
않는다. 각 score는 사용한 committed Model state를 가리키고 StrategyModel은 weight가 아니라 materialized score를
소비한다.

#### UC-MODEL-001 — Portfolio 없는 DataModel 연구

DataModel이 point-in-time feature로 다음 기간의 cross-sectional score를 만든다. user는 score coverage, IC,
stability를 평가하고 reusable result로 저장하지만 StrategyModel, target, order, portfolio return을 만들지 않는다.
**이 workflow는 완전한 DataModel research run이어야 한다.**

#### UC-MODEL-002 — Statistical factor return과 executed portfolio return의 구분

DataModel이 한 시점의 cross-sectional exposure와 observed return으로 factor-return regression coefficient를
추정한다. result는 statistical estimate, regression specification, input period, availability를 명시하며
**portfolio NAV나 executable factor return으로 표시하지 않는다.** 같은 factor를 실제 portfolio로 평가하려면
별도 StrategyModel과 execution workflow를 선택해야 한다.

#### UC-FACTOR-001 — Independent double sort로 구성한 팩터 수익률

user가 firm characteristic으로 sorted portfolio를 만들고 그 수익률로 팩터를 구성한다. 이것은 이 제품의
일급 research use case이며 다음을 만족해야 한다.

- **characteristic은 재사용 가능한 DataModel result다.** 회계 항목의 availability rule과 fiscal period 정렬은
  §4.1–4.2를 따르고, 그 가정(예: 확인된 보고 지연)이 result의 limitation에 남는다.
- **분류(membership)도 저장 가능한 result다.** universe 자격 조건, breakpoint를 계산한 기준 집합, 배정 결과와
  버킷별 구성종목 수를 보존한다. breakpoint 기준 집합이 최종 대상 집합과 다를 수 있으므로(예: 한 시장의
  분위수를 두 시장에 적용) 둘을 구분해 기록한다.
- **같은 분류를 쓴 여러 portfolio가 그 사실을 증명할 수 있어야 한다.** 각 버킷 portfolio의 result는 자신이
  소비한 membership을 dependency로 가리키며, 이를 통해 여러 result가 하나의 연구를 구성함을 확인할 수 있다.
  각 portfolio가 분류를 독립적으로 다시 계산하도록 강요하지 않는다.
- **버킷 수익률은 execution을 거쳐 산출한다.** §2.2를 우회하지 않는다. zero-friction profile을 선택하면
  거래비용 없는 정의상의 팩터 수익률이 나온다.
- **버킷 조합으로 만든 팩터와 signed portfolio로 직접 실행한 팩터가 zero-friction profile에서 일치해야 한다.**
  일치하지 않으면 실패가 아니라 관측 가능한 불일치로 보고한다.
- **리밸런싱 cadence는 명시적 선택이다.** 가중 방식에 따라 cadence가 결과를 바꿀 수도, 거의 바꾸지 않을 수도
  있다. 어느 쪽이든 package가 대신 고르지 않으며, 선택한 cadence가 result에 남는다.

보유 중 발생하는 상장폐지·거래정지 등 instrument lifecycle 사건의 해석은 현재 범위 밖이다(§13.2).
해당 종목이 조용히 제외되어서는 안 된다.

### 5.2 StrategyModel research

StrategyModel은 registered data와 compatible DataModel result를 소비해 경제적 판단을 만든다. deterministic rule
StrategyModel은 DataModel 없이 raw registered data를 직접 사용할 수 있다. 내부에서 score를 계산하더라도 **reusable
signal을 publish한다면 DataModel result와 같은 semantic contract를 따라야 한다.**

**내부에서** signal, score, rank 중 무엇을 계산하는지는 고정하지 않는다. 그러나 **public 결과는 배분**이다 —
어느 instrument에 자본의 얼마를 둘 것인가.

그리고 **그 배분은 실행된다.** 선택한 profile이 zero-friction academic이어도 체결, 계좌 반영, feedback이
일어나고 그 결과가 저장되어 다른 StrategyModel의 입력이 될 수 있다. **배분만 저장하고 실행을 건너뛰는
경로는 없다**(§2.3). 어느 경우에도 StrategyModel output 자체는 fill도 authoritative actual state도 아니다.

#### 내부 계산이 무엇을 가정하는지

내부 계산은 자유다. 그러나 **판단을 위해 내부에서 만든 성과 추정치는 체결·비용·현금 제약을 거치지 않은
값**임을 유의해야 한다. 비용이 없다고 가정한 성과로 후보를 고르면 **회전율이 높은 쪽으로 편향된다** —
실제로는 비용이 잠식할 후보가 좋아 보이기 때문이다.

같은 목적을 §5.4의 방식으로 표현하면 각 후보가 실제 체결과 비용을 거치므로 그 편향이 사라진다. 어느
경우든 내부 추정치를 portfolio return으로 **발표**하는 것은 §2.2가 금지한다.

§2.7의 built-in weighting 함수들은 공통적으로 instrument별 signed 값을 입력으로 받는다. 이는 **built-in을
호출하기로 선택한 StrategyModel만 구속하는 사실**이며, StrategyModel이 그 shape의 값을 만들어야 한다는 요구가 아니다.
built-in을 하나도 쓰지 않는 StrategyModel은 그런 중간값을 만들지 않고 곧바로 target을 구성해도 된다.

#### UC-SIGNAL-001 — StrategyModel 내부의 deterministic signal과 weight 조립

user가 price reversal StrategyModel을 선택한다. StrategyModel은 point-in-time price를 읽어 내부 reversal score와 signed
weight를 만들고 optional academic execution profile에서 long-short 결과를 평가한다. reusable signal을 별도로
publish하지 않는다면 stored DataModel result나 enhanced-index portfolio를 만들지 않아도 workflow가 완결된다.

#### UC-SIGNAL-002 — Stored DataModel result의 다중 재사용

한 DataModel이 monthly value characteristic을 materialize한다. long-short research StrategyModel과 long-only
construction StrategyModel이 같은 result를 소비하되 각자 다른 weighting rule과 execution profile을 사용한다.
DataModel은 다시 실행하지 않아도 되고, 두 StrategyModel result는 자신의 input dependency와 weighting semantics를 따로
보존한다.

### 5.3 Result category

각 category는 axis, unit, time semantics, compatibility를 스스로 선언한다. 서로 다른 category를 같은 이름으로
저장하지 않는다.

**모든 category는 §4.1의 dataset 계약 위에 얹힌다.** category가 다르다는 이유로 읽는 방식이 달라지지
않으며, 얹히는 것은 그 category가 추가로 선언해야 하는 의미뿐이다.

특히 StrategyModel이 만든 category(signed alpha-weight, ensemble)는 다음 셋을 **추가로 선언**한다.

| 선언 | 없으면 |
|---|---|
| weight가 raw / active / benchmark-relative / physical 중 무엇인지 | 초과비중과 실제 보유비중을 섞게 된다 |
| budget이 fixed인지 flexible인지 | 합이 0.4인 결과가 "의도한 40%"인지 "정규화 안 된 것"인지 모른다 |
| actual Account state나 Model state를 소비했는지 | 소비자가 dependency 종류와 재현 시작점을 알 수 없다 |

이 선언은 **결과를 만들 때 검증한다.** 선언과 실제 값이 어긋나면 — fixed gross 1.0을 선언했는데 합이
다르거나, long-only를 선언했는데 음수가 있으면 — 결과를 만들기 전에 실패한다.

**읽는 쪽에서는 값의 차이를 실패로 보지 않는다.** fixed 1.0 결과와 flexible 0.4 결과는 둘 다 정상이며, 그
둘을 어떻게 다룰지는 소비하는 StrategyModel의 경제적 결정이다. package가 생산자와 소비자 사이를 중재하지 않는다.

다만 **의미 불일치는 실패한다.** benchmark 대비 초과비중을 실제 보유비중으로 읽는 것은 경제적 선택이 아니라
단위 오류다.

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
| **actual-account monitoring finding** | committed fill 이후의 actual state를 monitoring time에 평가한 결과. 넘었다면 어느 제약과 그때의 한도·점검값을 싣는다 | account를 소급 변경하지 않는다. **compliance를 말하는 유일한 category다** — 조정 결과가 존재한다는 사실은 아무것도 보증하지 않는다 |
| **execution result** | committed fill, cost, account state, NAV, exposure, PnL, turnover | 유일하게 portfolio return을 주장할 수 있는 category |

statistical factor-return estimate는 regression specification과 input data를 dependency로 갖는다. 실제 factor
portfolio의 return을 담은 materialized data는 **그것을 산출한 execution과 actual state를 dependency로** 갖는다.
산출 경로 없이 portfolio return 시계열을 등록하지 않는다.

> **`constraint-adjustment result`의 "adjustment"는 사후 조정을 뜻하지 않는다.** 이 category가 담는 것은
> §7.1의 *"constraint 반영 구성"* — 제약을 반영해 만든 결과와 그 과정의 증거다. 제약 없이 만든 값을
> 나중에 자르고 남은 것을 재분배하는 절차가 아니며, 그런 절차는 수렴 보장이 없고 **잘릴 것을 미리 알았다면
> 다르게 구성했을 기회**를 없앤다. 이름은 안정 식별자(`UC-CONSTRAINT-ADJUST-001`)와 맞추기 위해 유지한다.

#### 진단 기록은 result category가 아니다

Model이 판단 과정에서 남긴 기록(§9.4)은 위 표의 어느 category도 아니다. **무엇이든 담을 수 있는 자유
형식이기 때문에** category가 보장하는 axis, unit, time semantics를 선언하지 않으며, 따라서 category가 하는
일 — 서로 다른 의미를 섞지 않게 막는 것 — 을 하지 못한다.

그래서 **진단 기록에 담긴 값으로 portfolio return, NAV, PnL, turnover를 주장하지 않는다.** weight와
수익률을 기록해 두고 그것을 성과로 보고하면 §2.2의 execution spine을 우회하는 것이며, 그 값은 체결·비용·
현금 제약을 거치지 않았으므로 이 제품에서는 portfolio return이 아니다. 성과를 주장하려면 execution
result에서 나와야 한다.

#### Signal과 weight는 shape가 같고 의미가 다르다

둘 다 instrument별 signed 값이므로 타입이 서로를 막아주지 않는다. 그러나 signal은 **확신의 방향과 크기**를,
weight는 **예산의 배분**을 뜻한다. signal을 그대로 weight로 사용하는 것은 "확신의 크기가 곧 배분 비율"이라는
경제적 주장이며, 그것이 의도였다면 명시적으로 선언되어야 한다.

따라서 **signal에서 weight로 가는 전환은 명시적 연산이어야 한다.** 타입 검사가 이 경계를 지켜주지 못하므로,
전환을 수행하는 연산을 통과했다는 사실 자체가 그 전환이 의도되었다는 증거가 된다.

### 5.4 Composition — StrategyModel이 StrategyModel의 결과를 구독한다

**StrategyModel은 다른 StrategyModel의 저장된 결과를 입력으로 삼을 수 있다.** 그 결과도 dataset이기
때문이다(§4.1). ensemble은 이 패턴의 한 사례일 뿐이며 별도의 후처리 단계로 강제되지 않는다.

```text
StrategyModel A   long-short alpha    → 실행 → 저장된 결과
StrategyModel B   ensemble            → A와 다른 member를 읽어 조합 → 실행 → 저장된 결과
StrategyModel C   enhanced index      → B와 benchmark를 읽어 long-only 배분 → 실행
```

**각 단계가 execution을 거친다**(§2.3). A와 B가 zero-friction academic profile을 쓰면 비용 없는 가상 체결이지만
계좌·NAV·feedback은 실제로 생긴다. 그래서 turnover-aware한 A가 자기 계좌를 볼 수 있고, adaptive한 B가
member의 realized outcome을 볼 수 있다(`UC-ALPHA-ADAPTIVE-001`).

#### 왜 한 계산 안에서 변환하지 않는가

이 체인은 §2.1의 *"운용 portfolio가 long-only여도 original signed alpha를 덮어쓰지 않는다"*를 **구조로
만족시킨다.** A의 결과가 독립된 result로 남기 때문이다. 한 계산 안에서 signed alpha를 long-only로 변환하면
원본이 중간값으로 사라지고, 그것을 보존하려면 별도 장치가 필요해진다.

그리고 benchmark나 배분 강도를 바꿔볼 때 **A와 B를 다시 실행하지 않아도 된다**(`UC-ALPHA-CHILD-001`).

`UC-ALPHA-PATH-001`이 account A와 account B를 구분하는 이유도 여기에 있다. A의 배분은 계좌 A 기준으로
만들어졌고, C가 계좌 C에서 그것을 사용해도 **A가 계좌 C에서 재계산된 것은 아니다.** 그 사실이 lineage에
남아야 한다.

#### 지원해야 하는 composition

- 같은 DataModel result를 서로 다른 StrategyModel이 재사용하고 독립적으로 평가한다.
- 같은 StrategyModel logic을 compatible한 여러 DataModel result와 비교한다.
- 여러 StrategyModel result를 producer 재실행 없이 조합한다.
- 저장된 배분을 다른 benchmark, 다른 제약, 다른 execution profile로 다시 사용한다.

#### 후보를 비교해 고르는 것도 같은 패턴이다

파라미터 후보 여럿을 비교해 그때그때 나은 것을 쓰고 싶을 수 있다. 이것은 **하나의 판단 안에서 후보를
돌려보는 것이 아니라** 위와 같은 composition으로 표현한다.

```text
후보 3개를 각각 실행   →  각자 성과와 배분을 남긴다
                              ↓
그 성과를 읽어 시점별 "그때까지 최선인 후보"를 만든다   ← 값이므로 §2.3의 DataModel
                              ↓
그 라벨이 가리키는 후보의 배분을 읽어 판단한다          ← StrategyModel
```

**반복 재학습(§5.1), 체결 규약 비교(`UC-ALPHA-CHILD-001`), 파라미터 선택은 같은 형태다** — 후보를 각각
실행하고 그 결과를 읽어 조합한다. *"안에서 돌려보고 싶다"*는 요구는 매번 *"밖에서 각각 돌리고 결과를
조합한다"*로 표현된다.

**한계.** 후보가 자기 보유에 의존하는 경우(turnover-aware 등) 그 후보의 배분은 *"그 후보가 계속
실행되었다면"*의 보유를 전제로 계산된 것이다. 중간에 후보를 바꾸면 실제 보유와 어긋나므로 근사가 된다.
이 차이는 결과에서 확인할 수 있어야 한다.

그리고 **자기 실현 성과로 조절하는 것은 이 패턴이 필요 없다.** actual state 이력(§6.6)과 state(§5.7)만으로
표현되며, 가상 성과가 아니라 실제 체결과 비용을 겪은 성과를 쓰므로 더 정확하다(`UC-ALPHA-ADAPTIVE-001`).

#### UC-ENSEMBLE-001 — 기존 StrategyModel result의 조합

value와 momentum StrategyModel의 signed weight를 저장한 뒤 ensemble이 두 result를 읽어 ticker-level netting을 한다.
한 member의 long과 다른 member의 short가 상쇄된 수량, 최종 signed weight, member lineage가 확인 가능해야 한다.

**상쇄된 수량은 weight 공간에서 읽는다.** 발행되는 배분은 weight economics만 허용하므로 수량으로 표현할
자리가 없고, 기록된 수량을 체결로 읽는 것은 §9.4가 금지한다. 상쇄는 **예산을 맞추기 전** 단계에서
기록하며, ensemble이 예산을 맞췄다면 맞춘 다음 단계도 함께 남긴다. 둘은 같은 행의 다른 **컴럼**이다 —
두 행으로 나누면 발행 키가 중복된다(아키텍처 §9.2).

**member lineage는 한 칸 건너서 따라간다.** ensemble의 발행물은 자기가 읽은 source를 기록하고, 그중
어느 것이 member인지는 그 source의 발행 envelope가 배분 operation이었는지로 정해진다. 그래야 관측
데이터셋이 member로 둔갓해지지 않는다.

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

#### budget semantics는 현금 범위 선언이다

이 구분은 **현금에 허용 범위를 선언**하는 것으로 표현된다. 별도 개념이 아니라 제약의 한 종류다.

| | 현금 범위 |
|---|---|
| fixed budget | 하한 = 상한 = 0 — 전부 배분해야 한다 |
| flexible budget | 하한 0, 상한 자유 — 남겨도 된다 |
| 의도된 현금 보유 | 원하는 값으로 하한·상한을 좁게 지정 |

**의도된 cash는 범위를 좁게 선언한 것이고, 잔여는 넓게 두고 남은 것이다.** 그래서 결과만 봐도 어느 쪽인지
알 수 있다. 그리고 현금은 **유도값이 아니라 결정된 값**이므로 결과에 그대로 남는다.

#### 현금 하한은 거래비용이 들어갈 자리이기도 하다

배분은 판단 시점에 비중으로 정해지고 체결은 나중에 수량과 금액으로 일어난다. 이때 **가격이 얼마나
움직였는지는 문제가 되지 않는다** — 체결 시점의 자산 가치로 다시 계산하므로 보유분과 목표 금액이 함께
움직여 상쇄된다.

문제가 되는 것은 **거래비용**이다. 비용은 목표 금액 위에 얹히므로 현금 하한을 0으로 선언하면, 즉 전액을
배분하겠다고 선언하면 **비용만큼은 반드시 모자란다.** 매도 실패와 수량 반올림도 같은 방향으로 작은 차이를
만든다.

그래서 현금 하한을 0보다 크게 두는 것은 예산 의미를 표현하는 동시에 **체결에서 생기는 차이를 흡수할 자리를
만드는 것**이다. 이것을 하지 않은 결과로 일부 주문이 줄거나 체결되지 않는 것은 오류가 아니라 §6.3이 정한
정상 동작이며, 어느 종목이 왜 줄었는지가 결과에 남는다.

#### 실현된 budget은 의도한 budget과 다를 수 있다

constraint 조정, lot rounding, cash clipping을 거치면 실현 gross/net이 의도한 값과 달라진다. 결과는 **의도한
budget과 실현된 budget을 함께** 보여야 하며, 하나를 다른 하나로 대체해 보고하지 않는다(§9.4).

#### UC-ALPHA-BUDGET-001 — 약한 signal의 residual

StrategyModel이 flexible budget을 선언하고, 기준보다 강한 종목만 선택한 결과 gross budget의 40%만 사용한다.
결과는 자기 선언과 함께 저장되며 **package가 이를 1.0으로 자동 확대하지 않는다.**

**선언과 실제 weight가 어긋나면 결과를 만들기 전에 실패한다.** fixed gross 1.0을 선언했는데 합이 0.4이거나,
long-only를 선언했는데 음수가 있는 경우다. **선언을 지키는 것은 StrategyModel의 책임**이며 package가 대신
맞춰주지 않는다.

이 결과를 읽는 다른 StrategyModel은 선언을 보고 **자기 규칙으로** 처리한다. 1.0으로 늘려 쓸지 0.4 그대로 쓸지는
그 StrategyModel의 경제적 결정이며, package가 두 결과의 budget이 다르다는 이유로 실패시키지 않는다.

### 5.6 Path-independent와 path-dependent alpha

path-independent result는 동일 frozen input에서 prior holding과 fill history 없이 재현된다. path-dependent
result는 actual holding, cash, prior fill, cooldown, strategy state에 의존한다.

**두 result 모두 producer를 다시 실행하지 않고 frozen input으로 재사용할 수 있다.** consumer StrategyModel은
필요한 artifact role, schema, semantics를 선언하고 package가 이를 resolve한다. 실제로 소비한 artifact만
dependency edge가 되며, source result가 의존했던 actual state·strategy state identity와 반영 범위는 새
result의 lineage에서도 보존된다.

재사용은 **source result를 consumer의 현재 account에서 다시 계산했다는 뜻이 아니다.** budget, schema,
semantics가 consumer 요구와 맞지 않으면 계산 전에 compatibility error로 실패한다.

#### UC-ALPHA-PATH-001 — Path-dependent weight의 producer-independent 재사용

turnover-aware StrategyModel이 account A의 actual holding과 strategy state를 소비해 path-dependent signed-weight
result를 만든다. 이후 ensemble StrategyModel이 이 frozen result와 다른 member result를 조합한다. source producer는
다시 실행되지 않고 parent result도 변경되지 않으며, ensemble result는 consumed artifact와 source actual
state·strategy state identity 및 반영 범위 lineage를 보존한다. ensemble weight를 account B의 executable
target으로 변환하면 account B의 현재 committed holding과 현재 execution input을 사용하지만, **source member가
account B에서 재계산되었다고 표시하지 않는다.**

#### UC-ALPHA-CHILD-001 — 체결 규칙만 바꾼 child research

parent의 signed weight를 고정하고 next-close와 next-open 같은 두 full-fill convention을 child에서 비교한다.
DataModel과 StrategyModel을 다시 실행하지 않으며, 각 child는 별도 actual state, execution assumption, PIT price
binding, fill dependency를 보존하고 parent result는 불변이다.

### 5.7 Model state

Model은 이전 계산의 결과를 다음 계산으로 이어갈 수 있어야 한다. **이 절의 규칙은 두 종류 모두에
적용된다** — StrategyModel은 이전 판단을, DataModel은 이전 계산 상태를 이어간다(§5.1).

- **하나의 bounded state 표면이다.** Model이 임의의 이름으로 독립된 상태를 늘리지 않는다. `memory`와 선택적
  `payload`는 서로 다른 authority가 아니라 하나의 state identity를 이룬다. 여기서 bounded는 byte 상한이 아니라
  상태 표면이 하나로 닫혀 있다는 뜻이다.
- **`memory`는 strict JSON이다.** 진행 위치, 최근 시점, 작은 계수처럼 구조적이고 portable한 값을 담는다.
- **`payload`는 선택적인 Model 고유 private state다.** 신경망 weight처럼 JSON에 맞지 않는 상태를 담으며,
  Model이 저장·복원 방법을 제공하고 package는 내부 의미를 해석하지 않는다. payload가 없는 Model은 기존
  memory만 사용한다.
- **상태는 compatible runtime 사이에서 위치와 process를 바꾸어 복원할 수 있어야 한다.** 로컬 payload 경로를
  memory에 넣는 것은 state가 아니며, 경로가 바뀌어도 복원 가능한 framework-managed state reference를 사용한다.
- **저장되는 값은 Model이 들고 있는 객체와 분리된다.** Model이 이후에 같은 객체를 계속 변경해도 이미
  기록된 state가 따라 바뀌어서는 안 된다. 그렇지 않으면 이력 전체가 마지막 값 하나로 붕괴한다.
- durable하고 portable해야 하며, 한 run의 종료 state를 다음 run의 시작 state로 사용할 수 있어야 한다.
  production에서 하루 단위로 실행하며 전날 state를 이어받는 것이 기준 사례다.
- **갱신은 decision, execution이나 fill 발생 여부에 종속되지 않는다.** 현재 callback occurrence가 성공해
  `NoDecision`을 반환한 경우에도 StrategyModel의 progression state는 commit된다. 판단했지만 주문이 없거나
  dealt quantity가 0인 occurrence에도 state는 이어지고, execution을 거치지 않는 DataModel도 마찬가지다.
- state를 사용한 result는 consumed Model state identity를 드러내야 한다. actual Account state dependency는
  별도로 표시한다. 그래야 순차 계산과 계좌 경로 의존성을 구분할 수 있다.
- **state는 최후 수단이다.** 같은 값을 bounded lookback이나 actual-state 이력(§6.6)이나 durable
  artifact로 표현할 수 있으면 그쪽이 재현 가능성이 높다.

#### Working checkpoint와 committed state

긴 Model invocation은 현재 memory와 payload를 working checkpoint로 저장할 수 있다. 이것은 같은 frozen
operation을 중간부터 재시도하기 위한 staging state이지, 정상 inference나 downstream 소비에 쓰는 committed
state가 아니다.

1. working checkpoint는 정상 inference에 사용하지 않는다.
2. 새 계산이 완료되기 전까지 기존 committed state를 유지한다.
3. working checkpoint는 같은 frozen operation identity에서만 재개한다.
4. 계산과 output validation이 완료된 후에만 새 state를 committed state로 교체한다.

adaptive StrategyModel은 realized result나 new observation으로 belief, parameter, member weight를 갱신할 수 있다.
특정 Bayesian class hierarchy를 요구하지 않고, update 전후의 state와 사용한 evidence를 비교 가능하게 보존한다.

#### UC-STATE-001 — 체결 없는 callback과 run 경계를 넘는 state 연속성

StrategyModel이 callback occurrence 횟수와 판단 결과를 state로 남긴다. callback이 `NoDecision`을 반환하거나,
판단한 occurrence에 주문이 없거나 dealt quantity가 0이어도 성공한 invocation의 state는 이어진다. callback 실패나
invalid output에서는 이전 committed state를 유지한다. run이 끝나면 최종 state를 결과로 얻을 수 있고, 다음
run의 시작 state로 **명시적으로 지정해** 이어서 실행할 수 있다. 이때 이전 run의 state를 자동으로 선택하지
않는다.

#### UC-STATE-002 — Payload checkpoint 재개

CNN DataModel이 epoch 37까지 학습한 뒤 memory와 model weight, optimizer state, random-number-generator state,
학습 규칙이 요구하는 이전 weight를 working checkpoint로 저장하고 process가 중단된다. 같은 Model implementation,
configuration, training data/window, seed policy, operation identity로 다시 실행하면 저장된 payload를 복원해 epoch
38부터 계속한다. 이 중 하나라도 다르면 checkpoint를 자동 재사용하지 않는다. 학습 완료 전 checkpoint는
downstream inference에 보이지 않고, 완료와 output validation 뒤에만 새 committed Model state가 된다.

#### UC-ALPHA-ADAPTIVE-001 — Fill 이후 ensemble belief 갱신

ensemble StrategyModel이 member별 realized outcome을 받은 뒤 다음 decision의 member weight를 바꾼다. result는 어떤
feedback까지 반영했는지 보여준다. 같은 update를 feedback 없이 재생하거나 미래 fill을 앞당겨 사용해서는 안 된다.

---

## 6. Executable lifecycle

### 6.1 하나의 spine

portfolio return, NAV, PnL, turnover를 만드는 모든 run은 다음을 순서대로 통과한다. academic long-short와
physical long-only의 차이는 **선택한 profile이 허용하는 direction, instrument별 quantity granularity, price,
cost, realism**뿐이다.

```text
StrategyModel decision
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

executable StrategyModel run은 signed, long-only, benchmark-relative 여부와 무관하게 현재 연구 결과를 **실행 가능한
하나의 frozen intended portfolio**로 확정한다. construction 규칙은 profile마다 다를 수 있지만 이 경계를
우회할 수 없다.

frozen intended portfolio는 budget semantics, direction, instrument target, source lineage를 동결한다. cash를
의도된 포지션으로 표현할지 잔여로 표현할지는 §5.5의 구분을 따른다. **StrategyModel result나 raw weight를
execution profile에 직접 제출하지 않는다.**

construction 내부에서 §2.7의 built-in weighting 함수를 조합할 수 있다. 그러나 그 함수들은 run identity,
decision time, account version을 알지 못하므로 실행 가능한 intent를 만들지 못한다. **intent 조립과 lineage
기록은 StrategyModel의 책임이며 이 경계는 built-in 사용 여부와 무관하다.**

DataModel-only 또는 non-portfolio analysis에는 construction이 필요하지 않다.

#### UC-PORTFOLIO-001 — 같은 alpha의 서로 다른 portfolio 사용

같은 signed alpha result를 academic long-short construction과 equity long-only enhanced-index construction에
사용한다. 두 workflow는 서로 다른 investability, direction, budget, cost requirement를 발견해 각각 frozen
intended portfolio를 만든다. 이후에는 같은 order conversion, fill, commit, valuation, feedback lifecycle을
따른다. **alpha result 자체를 어느 한 portfolio 의미로 다시 쓰지 않는다.**

### 6.3 Order conversion은 execution time의 책임이다

실제 주문을 만드는 단계는 frozen intended portfolio, **execution 시점의** committed holding/cash, instrument
rule, 그리고 그 시점의 체결 가격과 거래 가능 여부를 사용한다. decision time의 stale quantity를 재사용하지
않는다.

StrategyModel이 요구한 data와 execution이 사용하는 값은 **서로 다른 경로로 얻으며**, 어느 쪽도
purpose-specific registration alias를 통해 암묵적으로 선택하지 않는다. 필요한 것이 없으면 §10의
progressive error로 mutation 전에 멈춘다.

instrument별로 fractional 허용, lot rounding, clipping, skip, rejection, requested/dealt quantity가 확인
가능해야 한다.

#### 체결 테이블

체결에 필요한 **거래 가능 여부와 체결 가격**은 관측 data와 다른 성격을 가지며, 별도의 고정된 형태로
선언한다. 여기에는 최소한 다음이 포함된다.

```text
체결 시각 · instrument · 거래 가능 여부(참/거짓) · 체결 가격(하나 이상)
```

**이것은 execution을 선택한 run의 전제조건**이며, 없으면 그 run은 시작 전에 실패한다. 반대로 execution을
선택하지 않은 workflow — DataModel 연구, signal 분석 — 는 이것 없이 완결된다(`UC-MODEL-001`,
`UC-CONSTRAINT-001`).

##### callback source가 아니라 exact execution snapshot input이다

체결 테이블의 row density와 `trade_at` 집합은 Strategy callback, valuation, monitoring occurrence를 만들거나
지우지 않는다(§3.4). 같은 `trade_at`의 instrument 행은 하나의 exact venue snapshot을 이룬다.

StrategyModel이 `PortfolioIntent`를 반환하면 Flow는 current occurrence의 `evaluation_time`을 non-overridable
`decision_time` metadata로 stamp한다. `FillConvention`은 이 decision time과 frozen execution input으로
strictly-later exact target 하나, snapshot selector, trade-price binding을 결정한다. same-day close와 next
eligible open은 같은 intent를 다른 selector로 실행하는 profile이다.

target은 valid intent가 생긴 뒤에만 resolve한다. `NoDecision`에는 execution row를 요구하지 않는다. exact
target 없음, target이 `decision_time`과 같거나 더 이른 시각임, run end 밖, invalid
timezone·intent·provenance는 callback
전체를 atomic하게 실패시킨다. 새 Model state, decision evidence, pending intent, Account와 execution state를
commit하지 않는다.

StrategyModel은 current occurrence와 PIT-bounded observation만 받고 ExecutionTable, selected target과 future
execution rows를 읽을 수 없다.

##### 관측이 아니라 그 시점의 사실이다

관측 data는 *"이 시각까지 알 수 있었던 것"*을 범위로 읽는다(§3.2). 체결은 다르다. **체결 시각의 값을
정확히 하나 조회한다.** 지연을 두고 알게 되는 관측이 아니라 그 순간의 시장 상태이기 때문이다.

그래서 체결 테이블에는 availability 경계도 lookback도 적용되지 않으며, §3.5의 대상이 아니다.

##### StrategyModel과 DataModel은 이것을 읽지 못한다

**결정.** 연구를 수행하는 어떤 계산도 체결 테이블에 접근하지 못한다.

- **왜**: 접근할 수 있으면 어느 종목이 그날 정지될지를 판단 시점에 알게 된다. 그리고 판단이 일별 관측을
  쓰면서 체결은 더 촘촘한 시간 단위로 이루어지는 구성이 표현되지 않는다.
- 판단에 필요한 거래 가능 여부는 **등록된 data로 따로 소비한다**(§4.5). 두 값이 어긋날 수 있으며, 그
  어긋남이 곧 체결되지 않은 수량이다.

##### 관측이 없는 것과 거래할 수 없는 것을 구분한다

```text
조회됐고 거래 불가        상장돼 있으나 그 시점 거래할 수 없다
조회 자체에 없음          그 시점 이 시장에 존재하지 않는다
```

둘 다 체결되지 않지만 **결과에서 사유가 구분되어야 한다.** 체결 테이블은 user가 그 시장의 완전한 상태로
선언한 것이므로, 없는 것을 없다고 다루는 것은 추측이 아니라 선언을 따르는 것이다.

##### 체결 시각과 체결 가격은 선언된다

*"판단으로부터 언제 체결되는가"*와 *"그 시점의 어느 값으로 체결하는가"*는 execution profile이 선언하며,
StrategyModel이나 run script가 정하지 않는다. 같은 판단을 다른 체결 규약으로 비교할 때 **연구를 다시
실행하지 않아도 되어야 한다**(`UC-ALPHA-CHILD-001`).

체결 가격으로 선언된 값이 그 시각의 실제 관측 시점보다 이르다면 — 예를 들어 장 종료 시점에 체결하면서
개장 가격을 사용한다면 — 그것은 미래 정보를 쓰는 것이 아니라 **실제로 거래할 수 없는 가격을 사용하는
것**이다. package는 값의 관측 시점을 알지 못하므로 이를 판정할 수 없고, 따라서 이것은 검증 대상이 아니라
선택된 profile의 **한계로 기록**된다. 근거 있는 후보를 제시하고 이 한계를 설명하는 것은 agent의 몫이다(§11).

#### UC-FILL-001 — 체결 가격의 명시 선언과 대체 금지

execution profile이 어느 값으로 체결할지 선언한다. 그 시점에 그 값이 없거나 유효하지 않으면 package는
**다른 값으로 대체하지 않고** order나 account mutation을 만들기 전에 실패한다. 매수와 매도에 서로 다른
값을 선언한 경우 한쪽이 없다고 다른 쪽으로 채우지 않는다. 이것은 `UC-COST-004`가 비용 정책에 요구하는
것과 같은 규칙이다.

#### UC-TRADABILITY-002 — 판단 이후에 발생한 거래정지

StrategyModel이 거래 가능하다고 알고 있던 종목이 체결 시점에는 거래할 수 없게 되었다. package는 그
종목에 대해 **체결 수량 0과 사유**를 기록하고, 같은 결정에 포함된 나머지 종목의 체결은 정상적으로
진행한다. 이 결과는 **판단하지 않음**, **판단해서 유지함**, **체결 수량 0**이 서로 구분되어야 한다는
§6.7의 요구를 그대로 따른다. 반대로 체결 가격 자체를 얻을 수 없는 경우는 이와 다른 실패이며 그 결정의
주문 집합 전체가 mutation 전에 중단된다.

#### UC-EXEC-001 — Decision과 execution의 분리

StrategyModel result나 frozen intended portfolio가 존재한다는 사실만으로 fill이 생기지 않는다. 선택한 MVP execution
profile은 accepted intent의 Flow-stamped decision time 뒤 `FillConvention`이 선택한 exact target에서
execution-time order conversion을 수행한 뒤 지원되는 order를 전량 체결하고 cost와 즉시 결제 cash를 committed
state에 반영한다. **execution time에 새로 보이는 정보로 과거 StrategyModel intent를 암묵적으로 다시 계산하지
않는다.**

#### UC-EXEC-002 — Daily close profile의 명시적 한계

daily close profile은 명시적 callback occurrence 뒤 `same-day close` selector가 exact close snapshot을 찾은
경우에만 실행한다. decision time과 execution time의 equality override는 없고 target이 없거나 run horizon 밖이면
callback acceptance가 atomic하게 실패한다. volume impact, partial fill, 실제 settlement cycle을 모델링하지
않았다는 limitation을 결과에 남긴다.

**주문 수량이 확정되는 시점과 체결 시점이 같다는 것도 명시된 limitation이다.** 목표 배분을 체결 시점의
가격으로 수량으로 바꾸고 그 자리에서 체결하므로, 실제 운용에서 주문 수량을 미리 확정하기 때문에 생기는
비중 오차는 이 profile에 없다. 실제 주문 형태가 필요하면 판단 시점의 기록으로 남기며(§9.4), 그 기록은
체결이 아니다.

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

user가 signed StrategyModel result를 academic profile로 실행하면 먼저 frozen intended portfolio를 확정하고,
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
SELL tax는 명시적인 0bp이며 BUY와 SELL policy가 다르다. 각 주문에는 **instrument 종류와 방향에** 맞는
policy가 정확히 하나 적용되고(§8), fill은 total cost와 **적용 policy identity**를 보존해야 한다.

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

StrategyModel과 monitoring은 actual state를 현재 시점의 한 장면으로만이 아니라 **관측 이력**으로 읽을 수 있어야
한다.

- 관측 단위는 최소한 둘을 선택할 수 있다: **계좌 전체의 evaluation-time 시계열**(cash, NAV, 실현손익 등)과
  **instrument 단위 panel**(보유 수량, 진입 평단, 실현손익 등).
- 소비자는 필요한 관측 항목과 범위를 **선언**하고, 선언하지 않은 항목은 보이지 않는다. registered data
  관측과 같은 원칙이다.
- 기록 대상은 **committed state transition이 이미 계산하는 값**이다. 이력을 위해 별도 계산을 하지 않으며,
  그 집합 밖의 항목을 요구하면 **계산 전에 실패한다.** 추정하거나 다른 값으로 대체하지 않는다.
- **stop-loss, cooldown, 연속 손실 판정 같은 규칙은 strategy state 없이 actual state 이력만으로 표현될 수
  있어야 한다.**
- **actual state 이력 접근은 strategy state 보유 여부에 종속되지 않는다.**

#### UC-ACCOUNT-HISTORY-001 — StrategyModel state 없는 stop-loss

StrategyModel이 진입 평단과 최근 N개 committed Account version의 실현손익 이력을 선언해 읽고, 손실 한도를 넘은 종목을 청산 대상으로
판정한다. 이 판정에 strategy state를 사용하지 않으며, 실제로 소비한 actual-state 항목과 범위가 result의
dependency로 남는다. 선언하지 않은 항목은 읽을 수 없고, **기록되지 않은 항목을 요구하면 계산 전에
실패한다.**

#### UC-CLOSED-LOOP-001 — Actual execution feedback

첫 decision의 전량 fill과 transaction cost가 commit된 뒤, 다음 decision은 requested target이나 비용 차감 전
현금이 아니라 **actual cash, NAV, position, prior execution result**를 소비해야 한다. MVP의 주식·ETF cash는
fill과 동시에 결제된 것으로 처리한다.

#### 경로 의존 시나리오 — Actual fill에 의존하는 stop-loss

StrategyModel이 첫 decision에서 주식을 매수했지만 cost와 clipping 때문에 requested quantity보다 적게 체결된다.
이후 marked price가 **actual entry price** 대비 user-declared stop-loss threshold를 넘게 하락하면 다음
decision은 requested target이 아니라 committed quantity와 actual fill price를 사용해 exit intent를 만든다.
두 decision을 날짜별 독립 weight 계산으로 대체하거나 미래 fill을 앞당겨 사용해서는 안 된다.

#### Multi-instrument 시나리오 — 하나의 portfolio에서 여러 instrument

한 StrategyModel이 여러 주식과 ETF를 같은 decision에서 선택하면 shared cash, instrument별 cost, actual holding을
하나의 portfolio constraint 안에서 처리해야 한다. 종목별 requested/dealt quantity와 failure reason을 모두
보존하며, 한 instrument의 cash consumption이나 blocked execution이 다른 instrument의 결과와 다음 decision에
미치는 영향을 재현할 수 있어야 한다.

#### Multi-frequency 시나리오 — 서로 다른 data와 decision cadence

daily observation과 valuation을 사용하면서 monthly StrategyModel rebalance와 daily actual-account monitoring을
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

callback occurrence의 `NoDecision`만 **판단하지 않음**을 뜻한다. 명시적 hold는 유효한 StrategyModel decision이며
execution spine을 통과하되 새 주문을 만들지 않는다. dealt 0은 유효한 decision과 order conversion 뒤 Exchange가
만든 실행 결과다. 이 셋은 같은 null 값이나 빈 batch로 합치지 않는다.

#### 금지 — 가짜 hold

current target을 반복 제출해 hold를 흉내 내고 price-drift rebalance를 발생시키는 것을 금지한다.

### 6.8 Monitoring은 decision과 독립이다

constraint monitoring은 StrategyModel decision cadence와 독립적인 finite agenda로 committed actual account를
관찰할 수 있어야 한다. current monitoring occurrence의 frozen evaluation time에서 새 decision이나 order가 없는
instant에도 finding을 만들 수 있어야 한다. **monitoring finding은 계좌를 수정하거나 과거 fill을 rollback하지
않는다.**

#### UC-EXEC-003 — No-trade day의 actual constraint breach

가격 변화로 한 종목의 actual weight가 그 시점의 $\max(10\%, w_i^{index}(t))$ cap을 넘었지만 StrategyModel decision은
없다. monitoring은 actual snapshot과 available benchmark weight를 사용해 breach를 기록한다. **새 order가 없다는
이유로 finding을 누락하지 않는다.**

### 6.9 Run 종료 결과

run은 inclusive `end`의 due chain을 모두 처리한 뒤 pending intent가 없을 때만 성공적으로 종료한다. 최종 actual
state와 최종 Model state를 결과로 제공하며, 그 결과만으로 이어지는 run을 시작할 수 있어야 한다. 이것은
**중단된 run의 재개와 다르다.** pending intent 이월과 중단 복구는 current scope가 아니다(§13.2).

---

## 7. Constraints

constraint는 모든 research workflow의 선행 조건이 아니다. constraint adjustment와 actual-account monitoring을
**선택한 경우에만** 해당 operation이 metric, bound, evaluation scope, 필요한 data를 요구한다.

**constraint는 user가 작성할 수 있는 확장점이다**(§12.3). package가 목록을 닫아둘 근거가 없다 — constraint
metric의 경제적 의미와 bound는 user project가 소유하기 때문이다(§12.4). package가 제공하는 것은 계약과
그 계약을 지키는지에 대한 deterministic 판정이다.

선언된 constraint는 **성격이 다른 두 가지 일**에 쓰이며, 같은 선언이 그 둘 모두에게 간다.

```text
선언 ──►  판단 시점의 bound        (구성)      — 지키려고 최선을 다하는 자리
선언 ──►  committed state 판정      (monitoring, 별도 cadence) — 지켜졌는지 관찰하는 자리
```

**둘은 같은 질문의 앞뒤가 아니라 서로 다른 질문이다.** 구성은 *"이 한계 안에서 할 수 있는 최선이
무엇인가"*이고 best effort다 — 신호가 원하는 portfolio와 한계가 허용하는 portfolio가 다르면 후자를
만든다. monitoring은 *"실제로 들고 있는 것이 한계를 넘었는가"*이고 사실 관찰이다 — 최선을 다했는지와
무관하게, 넘었으면 넘은 것이다.

**구성이 최선을 다했는지를 따로 채점하지 않는다.** 판단이 한계 밖으로 나갔다면 그것은 위반이고,
위반은 monitoring이 잡는다. 같은 판단을 두 번 채점하면 두 채점이 갈릴 수 있고, 그때 어느 쪽이 그
전략에 대한 사실인지 말할 방법이 없다.

따라서 constraint 선언은 자신이 요구하는 data를 스스로 선언해야 하고, 그 data가 없으면 **결과를 만들기
전에 실패한다.** 어느 constraint가 어떤 값을 어떤 bound와 비교해 얼마나 초과했는지가 결과에 남아야 하므로,
선언은 숫자 상하한이 아니라 **정체를 가진 것**이어야 한다.

package가 built-in으로 제공하는 hard constraint는 두 개다.

$$
w_i(t) \ge 0
$$

$$
w_i(t) \le \max\left(10\%,\; w_i^{index}(t)\right)
$$

첫 식은 no-short다. 둘째 식의 benchmark constituent weight는 **time-varying PIT data**이며 해당 constraint를
선택한 workflow가 명시적으로 구독한다. 종목이 benchmark 비구성종목임이 **확인되면** $w_i^{index}(t)=0$이지만,
구성 여부나 weight data가 **누락되면 0으로 추정하지 않고 constraint evaluation을 실패시킨다.**

**package가 제공하는** sector, turnover, liquidity, leverage, gross/net exposure 정책과 blocking·severity·
override policy는 future work다. user가 위 계약(요구 data 선언 → bound 투영 → 측정)으로 표현할 수 있는
constraint를 직접 작성하는 것은 막지 않으며, 그 계약으로 표현되지 않는 것은 지금 범위 밖이다.

### 7.1 두 가지 서로 다른 결과

| 결과 | **언제** | 무엇 |
|---|---|---|
| **constraint 반영 구성** | **판단 시점** | 제약을 반영해 portfolio를 만든다. 원래 의도, 반영된 결과, constraint별 before/after, 해소되지 않은 잔여를 보존한다 |
| **actual-account monitoring** | 별도 cadence | committed state를 monitoring time에 평가한다. 넘었다면 **어느 constraint를 넘었는지와 그 시점의 한도·점검값**을 남긴다 |

**위반 기록은 그 세 가지면 충분하다** — 어느 규칙, 얼마가 한계였고, 실제로 얼마였나. 그 이상을 요구하지
않는 것이 의도다: 판정마다 읽은 것을 전부 따라 적게 만들면 관찰이 무거워지고, 무거운 관찰은 cadence를
늘릴 수 없어 결국 덜 관찰하게 된다.

**execution은 제약을 평가하지 않는다.** 제약 평가는 경제적 판단이고, execution은 이미 확정된 것을 체결시킬
뿐이다(§2.4). 제약을 execution 단계로 미루면 그 시점에 할 수 있는 일이 "기록"밖에 없어 — 다시 최적화하는
것은 판단을 되돌리는 것이므로 §2.4가 금지한다.

**구성 결과가 존재한다는 사실만으로 compliance를 선언하지 않는다.** compliance를 말하는 것은 monitoring
이고, 그것은 계획이 아니라 **실제로 committed된 것**을 본다. 한계를 넘은 판단이 나갔다는 이유로 run을
중단하지 않는다 — 그러면 그 전략이 실제로 무엇을 하는지 끝까지 볼 수 없고, `UC-CONSTRAINT-ADJUST-001`
처럼 판단 시점에 알 수 없는 breach는 애초에 그 방법으로 잡히지도 않는다.

required input 부재나 evaluator 계산 실패는 finding이 아니라 **결과를 만들기 전의 structured operation
error**다. blocking, severity, override policy는 future work다.

#### UC-CONSTRAINT-001 — Constraint 없는 signal research

user가 stored signal의 IC와 hypothetical long-short 결과만 분석한다. portfolio constraint나 compliance dataset을
등록하지 않아도 이 workflow는 실행되어야 한다.

#### UC-CONSTRAINT-002 — Time-varying single-name cap

user가 single-name cap을 켠 전략이 판단을 만들려 한다. **그 판단 시점에** 사용할 수 있는 benchmark
constituent weight binding이 없으면 package는 constraint 평가 전에 missing requirement를 보고하고 **portfolio
결과를 만들지 않는다.** 따라서 주문도 account mutation도 생기지 않는다. weight가 3%인 종목의 cap은 10%,
15%인 종목의 cap은 15%다.

#### UC-CONSTRAINT-ADJUST-001 — 판단 시점에 알 수 없는 breach

판단 시점에 weight 공간에서 제약을 만족시켰어도, **정수 수량 변환 때문에 실제 비중이 한계를 살짝 넘을 수
있다.** 이 차이는 판단 시점에 알 수 없다 — 그때는 아직 어느 가격에 몇 주가 체결될지 정해지지 않았기
때문이다.

그 차이는 requested/dealt 진단에 남고, **committed state의 실제 위반은 monitoring이 잡는다**(`UC-EXEC-003`).
package는 이를 성공한 조정이나 compliant result로 위장하지 않지만, 그 때문에 execution을 되돌리거나 중단하지도
않는다.

---

## 8. Instrument semantics

instrument type, venue, execution profile은 가능한 position direction, lifecycle cash flow, settlement, cost
policy를 결정한다. `long_only`, `hypothetical_short`, borrow-aware short, derivative exposure를 같은 capability로
취급하지 않는다.

다만 이 의미는 해당 instrument를 실제로 연구하거나 실행할 때 요구하며, **무관한 dataset registration을 막는
전역 schema가 되어서는 안 된다.**

#### 정책은 instrument 종류에 걸린다

거래비용, 허용 방향, lifecycle 같은 정책은 **개별 instrument가 아니라 그 종류**에 선언한다. 3,000종목을
거래해도 주식용 규칙 하나와 ETF용 규칙 하나면 된다.

- **왜**: 종목마다 요율을 적으면 세율이 바뀔 때 3,000줄을 고쳐야 하고, `UC-COST-002`의 시기별 요율은
  종목마다 시계열이 되어 감당할 수 없다.
- 종목의 **종류**는 그 종목의 성질이고 **요율**은 venue의 성질이다. 둘은 다른 곳에 선언되며, 정책은
  종류를 키로 삼아 둘을 잇는다.

#### 적용되는 정책은 정확히 하나여야 한다

한 주문에 적용 가능한 정책이 **0개면 실패**하고 **2개 이상이어도 실패**한다.

- **0개 실패**가 `UC-COST-004`가 요구하는 것이다 — 비슷한 종류의 정책으로 대체하지 않는다.
- **2개 이상 실패**는 모호한 정책으로 조용히 계산하지 않기 위해서다. 같은 선택자에 적용 기간이 겹치는
  정책은 **선언 시점에** 거부한다.

현재 `hypothetical_short`는 explicit academic listing, next-eligible-close PIT price, zero-friction full-fill
profile, 분리된 signed state ledger에서만 지원한다. physical KRX profile은 계속 long-only이며 real short
capability를 추론하지 않는다.

### 8.1 Long-short research와 executable short의 네 층

다음은 서로 다른 capability다.

| 층 | 무엇 | §2.3의 역할 |
|---|---|---|
| 1 | signal/prediction/label의 IC, RankIC, rank-based diagnostic — **portfolio를 구성하지 않는다** | **DataModel** |
| 2 | execution을 거쳐 산출·저장된 return/NAV 시계열에 대한 분석 — attribution, correlation, factor regression처럼 기존 result를 읽으며 **새 return을 만들지 않는다** | analysis |
| 3 | explicit academic listing, hypothetical fill, signed state-transition rule을 사용하는 가상 execution | **StrategyModel** |
| 4 | order, production position/account, actual fill을 통과하는 **executable real short portfolio** | **StrategyModel** |

**이 분류는 §2.3의 경계와 같은 것을 다른 각도에서 말한다.** 1층은 배분을 만들지 않으므로 execution이
없고, 3·4층은 배분을 만들므로 반드시 execution을 거친다.

첫 번째 층만 execution state를 경유하지 않는다. **새로운 portfolio return을 만드는 것은 세 번째 층부터이며,
두 번째 층은 그 이상의 층이 만든 result를 읽는 분석이다.** quantile spread와 signed basket return처럼 basket
수익률을 뜻하는 지표는 첫 번째 층이 아니라 세 번째 층 경로로 산출한다.

세 번째와 네 번째 층은 같은 fill → commit → valuation lifecycle을 사용하되, 서로 다른 run과 명시적으로 다른
state-transition validity, venue rule, realism label을 갖는다. `hypothetical_short`의 음수 position은 research
관측을 위한 committed hypothetical state이며 borrow, 담보, 차입 비용, locate 가능성을 모델링하지 않는다.

### 8.2 ETF look-through는 user-authored StrategyModel behavior다

ETF look-through는 ETF position에서 **자동으로 발생하는 package behavior가 아니다.** ETF registration, 보유
수량, constituent dataset이 존재한다는 이유만으로 look-through를 켜지 않는다.

constituent data는 source identity, `available_at`, instrument/constituent identity, weight unit을 표현하는
user-provided PIT data다. mapping, coverage, stale/revision 처리, normalization, cash residual의 경제적 의미는
**StrategyModel이 소유한다.** vqapr는 ETF ticker를 근거로 dataset을 자동 발견하거나 누락된 구성종목을 추정하지
않는다.

StrategyModel이 decision time $t$의 actual portfolio state에서 만든 physical weight를 $p_t$, 자신이 소비한 구성종목
데이터로 만든 mapping을 $L_t$라 하면 constituent exposure는 예를 들어 $x_t = L_t p_t$로 계산할 수 있다.
**이 식은 vqapr의 내장 ETF semantics가 아니라 StrategyModel이 선택할 수 있는 계산 예시다.**

#### 구성종목 데이터의 형태

한 시점에 하나의 ETF가 **여러 구성종목 행**을 갖는다. 따라서 §4.1의 **추가 key axis**를 선언해 등록한다.
그리고 `UC-LOOKTHROUGH-002`가 PIT 소비를 요구하므로 **정적 설정이 아니라 등록된 dataset**이어야 한다 —
구성이 바뀌는 시점과 그 사실을 알 수 있게 된 시점이 데이터에 있어야 하기 때문이다.

#### 제약은 physical 보유에만 건다

look-through로 계산한 노출에는 제약을 걸지 않는다. **제약은 실제 보유 비중을 대상으로 한다.**

- **왜**: 계좌에 남는 것은 physical 보유이고, monitoring이 실제 위반을 판정하려면 그 대상이어야 한다(§7.1).
  노출은 계산값이라 **mapping이 바뀌면 과거 판정까지 달라진다.**
- 두 쓰임이 다르다 — look-through는 *"무엇을 원하는가"*에 쓰이고, 제약은 *"무엇을 보유할 수 있는가"*에
  쓰인다.

#### UC-LOOKTHROUGH-001 — 명시적 ETF exposure 계산

constituent A/B를 각각 50% 보유한 ETF와 A direct stock을 함께 보유해도 vqapr는 instrument나 account position만
보고 look-through를 자동 수행하지 않는다. user가 StrategyModel에 constituent dataset binding과 actual account state
requirement를 명시하고 둘을 직접 소비한 경우에만 StrategyModel code가 constituent exposure를 계산한다. 그 StrategyModel은
direct stock과 ETF constituent exposure를 **정확히 한 번** 합산하고 physical cash/residual을 별도로 취급한다.
같은 ETF를 아무 constituent binding 없이 사용하는 다른 StrategyModel에서는 ETF가 opaque physical instrument로
남아야 한다.

#### UC-LOOKTHROUGH-002 — PIT constituent consumption

ETF 구성이 바뀌었지만 새 observation의 `available_at`이 decision time보다 늦으면 vqapr는 그 observation을
노출하지 않는다. look-through를 선택한 StrategyModel은 그 시각에 읽을 수 있는 구성종목만 소비하고, snapshot 선택,
coverage, stale/revision 처리, 재정규화 여부를 자신의 경제적 규칙으로 명시한다.

#### UC-LOOKTHROUGH-003 — Actual holding을 읽는 recomputation

ETF와 direct stock이 체결된 뒤 가격 drift 또는 다음 rebalance가 발생하면 StrategyModel은 다음 decision에서
requested target이 아니라 그 시점에 허용된 **marked actual portfolio state**를 읽어 exposure를 다시 계산한다.
vqapr는 계산값을 account에 자동 주입하거나 다음 StrategyModel에 자동 feedback하지 않는다. user가 결과를
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
StrategyModel에 전달한다. producer의 internal class를 import하지 않아도 compatibility와 lineage를 검사할 수 있어야
한다.

#### UC-ARTIFACT-002 — Invalid serialized result 거부

weight artifact의 logical key가 중복되거나 declared semantics와 payload가 맞지 않는다. object construction 또는
publication이 실패하고 invalid artifact는 catalog의 reusable success로 노출되지 않는다.

### 9.2 Dependency graph와 identity

artifact는 **실제** input artifact/data/config와 producer identity를 가리킨다. 같은 frozen identity와
compatible output이 이미 있으면 재사용할 수 있고, input이나 semantic contract가 달라지면 별도 result로
취급한다. content hash만 같다는 이유로 서로 다른 경제적 의미를 합치지 않는다.

경제적으로 다른 cadence, calendar, StrategyModel version, execution profile, account validity, data source를 같은
run으로 취급하지 않는다.

### 9.3 Publication은 원자적이다

publication은 payload와 metadata가 함께 durable하게 commit되었을 때만 성공한다. **partial write는 reusable
artifact로 보이지 않아야 한다.** 실패한 research도 error identity, stage path, frozen input, log reference를
남겨 agent가 다음 action을 제안하고 안전한 retry 여부를 판단할 수 있게 한다.

#### UC-ARTIFACT-003 — 동시 publication과 중단

concurrent publication과 process interruption에서도 partial result가 reusable success로 보이지 않고, conflict,
idempotency, recovery outcome이 결정적이어야 한다.

#### UC-RESEARCH-001 — 실패를 보존한 뒤 보강해 retry

StrategyModel이 benchmark-weight requirement 부족으로 실패한다. catalog는 성공 result 대신 failure evidence를
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

하나의 backtest result를 여러 renderer로 표현한다. renderer가 달라도 return, cost, exposure, failure
count의 **underlying value와 lineage는 같아야 한다.** 요구사항은 *값이 renderer와 독립*이라는 것이지
vqapr가 특정 renderer를 출하한다는 것이 아니다.

vqapr는 **table renderer와 machine-readable renderer를 제공하고 visualization은 제공하지 않는다.**
chart는 같은 값 위에 user가 구성하는 renderer다(§12.4의 "report composition"). 이것이 가능한 이유는
§9.1의 diagnostic table과 저장된 result가 다른 dataset과 **같은 방식으로 읽히기** 때문이다 — 시각화에
필요한 값이 이미 조회 가능한 형태로 있다. agent가 first-class user이므로(§1.4) machine-readable 표현이
우선순위를 갖는다.

#### UC-REPORT-002 — Model diagnostic table

**DataModel과 StrategyModel 모두** 계산 과정에서 사용한 signal, 선택 여부, 원 weight, 제외 사유 같은
정보를 user-declared typed schema에 따라 기록할 수 있다. 출력으로 표현할 수 없는 것이 있기 때문이다 —
어느 종목을 왜 제외했는지는 살아남은 종목당 한 행인 출력에 담기지 않는다.

기록된 각 행에는 **어느 run의 누가, 어느 시각에, 그 시각이 어떤 종류의 시각인지**가 함께 남아야 한다.
이것을 producer가 주장하지 않고 package가 붙이며, user가 선언한 schema가 이 항목들을 덮어쓰려 하면 기록
전에 실패한다. 판단 시각과 값의 유효 시각은 서로 다른 의미이므로, 시각만 있고 그것이 어느 종류인지 없으면
읽는 쪽이 두 테이블을 같은 뜻으로 해석하게 된다(§3.1).

실제 주문서 형태로 기록하는 것도 이 범주다. 판단 시점에 아는 가격으로 수량을 계산해 남길 수 있으며,
**그렇게 기록된 수량은 체결이 아니다.** 실제 체결은 §6.3의 경로를 지나 별도의 결과로 남고 기록된 수량과
다를 수 있으므로, 둘을 같은 것으로 읽거나 기록된 쪽을 실제 거래로 보고하지 않는다.

기록된 값은 Model state나 Account authority가 아니며 **Model이 다시 읽을 수 없다.** run이 끝난 뒤에는
producer를 재실행하지 않고 report와 분석에서 사용할 수 있는 versioned table artifact로 조회할 수 있어야
하며, 이때 다른 저장된 결과와 **같은 방식으로** 읽힌다. 실패하거나 중단된 publication의 일부 row를
complete result로 노출하지 않는다. 이 기록은 §5.3의 result category가 아니며 portfolio return의 출처가
될 수 없다.

epoch, loss, learning rate, checkpoint/state identity는 diagnostic으로 기록할 수 있다. 그러나 model weight,
optimizer state, random-number-generator state처럼 학습 재개에 필요한 private payload를 recorder에 저장하거나
recorder를 읽어 복원하지 않는다. recorder row가 남았다는 사실은 checkpoint나 Model invocation의 완료를
증명하지 않는다.

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
- **선언한 체결 가격이 없을 때 다른 값으로 대체** (§6.3)
- **관측이 없는 시점의 행을 직전 관측으로 합성해 체결이나 평가에 사용** — 없는 관측을 만들어내는 것은
  값을 대체하는 것보다 한 단계 더 나아간 것이며, 거래할 수 없었던 종목을 거래 가능한 것으로 보이게 한다
- failed artifact publication을 complete로 표시
- **explicit execution과 accounting을 거치지 않고 계산한 값을 portfolio return, NAV, PnL, turnover로 보고**
  — Model이 판단 과정에서 남긴 진단 기록을 그 출처로 삼는 경우를 포함한다(§5.3, §9.4)

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
- Model invocation의 working checkpoint는 기존 committed Model state를 바꾸지 않는다. 새 output과 state가
  validation을 통과해야 새 state가 committed되고, 미완성 output은 reusable result로 노출되지 않는다.
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

vqapr distribution은 현재 package version과 일치하는 agent skill resource(§11.2가 정한 집합)를 포함해야 한다. project onboarding은
사용자가 선택한 coding-agent environment에서 이 skill을 사용할 수 있게 한다.

skill은 다음을 담당한다: public status·capability inventory·schema·example·error 조회, package error와 skill
지침에서 복수의 resolution 경로 구성과 설명, 경제적 의미가 필요한 선택의 user 확인, user-confirmed project
config 또는 local extension 작성과 package validation 호출, 같은 public operation retry와 result·limitation·
changed files 요약.

skill은 public error의 stage를 기준으로 version-matched guidance를 찾고, 해당 단계의 계약, 자주 발생하는 실패,
가능한 복수의 해결 경로, user confirmation이 필요한 선택, retry할 public operation을 제시한다.

agent-specific instruction file은 bundled skill과 installed documentation을 찾게 하는 **thin routing layer**다.
product fact와 schema를 agent-specific file에 복제해 stale하게 만들지 않는다.

#### skill은 error 이후가 아니라 등록 이전부터 개입한다

위 목록은 package error에서 시작한다. 그러나 **등록할 것이 무엇인지 정하는 단계가 그 앞에 있고**, 그
단계에 package는 관여하지 않는다. 임의 형태의 연구 데이터를 받아들이기로 한 이상 그 의미를 확인하는
일이 남으며, 그것이 skill의 자리다.

skill은 user가 가진 원천을 **먼저 읽어** 다음을 근거와 함께 제안한다: instrument와 시간 축의 후보,
`available_at` 값의 후보(§4.2), 체결 시각과 체결 가격 후보(§6.3), 거래 가능 여부의 유도 규칙 후보(§4.5).

**이때 읽는 것은 package가 아니라 agent 자신의 도구다.** 원천은 xlsx일 수도 csv일 수도 데이터베이스일
수도 있고 그 안의 구조는 아무도 미리 모른다. package는 그런 형식을 읽지 않으며(§4.0), 그것을 읽어
파악하는 일은 skill이 자기 환경에서 한다. **두 읽기를 같은 것으로 보면 package에 임의 형식 reader를
넣게 된다.**

제안은 두 곳으로 착지한다 — **준비된 dataset**(user의 agent가 만든다)과 그것을 읽는 **project config**.
package는 후자를 받아 전자가 계약을 만족하는지 deterministic하게 검증한다.

#### 데이터가 증명하는 것과 이름으로만 아는 것을 구분한다

제안의 근거는 두 종류이며, 확정 절차가 다르다.

| | 예 | 처리 |
|---|---|---|
| **데이터가 증명한다** | 네 값 사이에 항상 성립하는 대소 관계 → 시세 구조 · 논리 key의 유일성 위반 → 추가 key axis 필요 · 낮은 카디널리티 문자열과 값의 쌍 → field별 저장 | agent가 확정해도 된다 |
| **이름으로만 안다** | 넷 중 어느 것이 개장 가격인가 · 날짜가 관측일인가 공개 시각인가 · boolean이 정지인가 다른 상태인가 | **user 확정 필수** (§4.2) |

아래쪽은 데이터로 반증되지 않는다 — 개장 가격과 종가를 뒤바꿔 제안해도 둘 다 고가·저가 사이에 있다.
그래서 §4.2의 원칙이 그대로 적용된다: **근거가 확인되기 전에는 등록하지 않는다.**

#### agent는 package가 원리적으로 검증할 수 없는 것을 경고한다

§2.6은 package가 판정하고 skill이 대화한다고 정했다. 여기에 한 가지가 더해진다 — **package가 알 수 없는
사실을 aware하게 만드는 것**이다.

대표적인 예가 체결 가격의 관측 시점이다(§6.3). package가 아는 것은 체결 시각뿐이고 그 값이 실제로 언제
관측되었는지는 데이터에 없으므로, 장 종료 시점에 개장 가격으로 체결하는 구성을 package는 통과시킨다.
skill은 이름과 도메인 지식으로 그것을 알아보고 그 가격에 실제로 거래할 수 없다는 사실과 대안을 설명한다.

이 경고의 결과물은 **새로운 검증이 아니라 result의 limitation**이다. package의 판정 범위를 넓히지 않으며,
넓히려는 시도가 §4.1이 말한 "반쪽 보장"을 만든다.

#### 등록에서 권장되지 않는 준비 방식은 skill이 다룬다

이동평균, 누적합, 순위, 시간축 집계처럼 **어떤 시점의 값이 다른 시점의 관측에 의존하게 만드는 계산**은
등록 단계에서 수행하지 않는 것이 원칙이다. 그러나 이것은 package가 강제하는 규칙이 아니다 — user가 자신의
데이터 준비 과정에서 미리 계산해 올 수 있으므로 한쪽만 막는 것은 막는 것이 아니고, 막는 것처럼 보이면
오히려 방심을 만든다(§4.1).

따라서 이 구분은 **skill의 지침으로 유지**한다. skill은 등록 정의를 검토해 해당 패턴을 발견하면 그것이
왜 위험한지와 DataModel로 표현하는 대안을 설명하고, user가 그대로 진행하기로 하면 그 선택이 result의
limitation에 남는다.

#### UC-AGENT-002 — 데이터를 읽고 등록을 제안한다

user가 데이터 위치만 알려준다. agent는 파일을 읽어 축, availability, 체결 시각과 가격, 거래 가능 여부의
후보를 근거와 함께 제시하고, **데이터로 확인되는 것과 user 확정이 필요한 것을 구분해** 보여준다. user가
선택하면 agent는 project config를 작성하고 package validation을 호출한다. package가 검증할 수 없지만
결과의 의미를 바꾸는 사실 — 체결 가격의 관측 시점, 유도된 거래 가능 여부의 한계 — 은 확인 대상으로
제시되고 result의 limitation에 남는다. **agent의 제안이 package validation을 대체하거나 우회하지 않는다.**

### 11.2 Skill set — normative product contract

vqapr는 skill 하나가 아니라 **skill 집합**을 출하한다.

이유는 discovery에 있다. agent가 시작할 때 미리 읽는 것은 각 skill의 `name`과 `description`뿐이고, 본문은
그 skill이 관련 있다고 판정된 **뒤에야** 읽힌다. 그러므로 description이 "언제 이것을 써야 하는가"를 말하지
못하면 skill은 발견되지 않는다. 그런데 vqapr 전체를 하나로 표현하면 description은 프레임워크 소개문 말고는
될 수가 없다 — "등록하고 싶다"와 "결과를 그림으로 보고 싶다"는 서로 다른 요청인데 같은 문장이 둘 다를
대표하게 되기 때문이다.

경계는 임의로 긋지 않는다. **user가 무엇을 하려고 왔는가**가 축이며, §12.3이 이미 정한 확장점 넷이 그
축의 절반을 그대로 준다.

| skill | 담당 | 주요 절 |
|---|---|---|
| `introduce-vqapr` | vqapr가 무엇인지, workspace 만들기, sample journey, 다른 skill로의 routing | §1.4·1.5, §11.3·11.4 |
| `register-dataset` | user의 원천을 읽고 의미를 인터뷰해 dataset 등록까지 | §3, §4, §11.1 |
| `make-datamodel` | 재사용 가능한 파생 panel 작성과 검증 | §5.1, §2.3 |
| `make-strategy` | signed weight와 intended position을 만드는 코드 | §5.2·5.4·5.5·5.6·5.7 |
| `make-exchange` | 언제·얼마에·어떤 단위로 체결되는가 | §6.3·6.4·6.5, §8 |
| `make-constraint` | 무엇을 지켜야 하는가, adjust와 report | §7 |
| `run-backtest` | run 선언, `check`, 실행 | §6.1·6.2·6.9, §3.6 |
| `analyze-result` | 끝난 run의 기록을 답·표·그림으로 | §9.1·9.4, §2.8 |
| `inspect-workspace` | workspace가 무엇을 들고 있는가, 재사용 판정, 삭제 | §9.6, §2.8 |

각 skill의 `description`은 **무엇을 하는가와 언제 쓰는가를 모두** 담고, 3인칭으로 쓰며, user가 실제로 말할
법한 단어를 앞쪽에 둔다. description 문구 자체는 각 `SKILL.md`가 소유한다 — 이 표에 복제하면 둘 중 하나는
반드시 stale해진다(§11.1).

**failure recovery는 skill이 아니다.** refusal은 status(누가 행동해야 하는가), stage(어디서 닫혔는가),
cause(무엇이 일어났는가)를 스스로 싣고, `fix`·`requirement`·`observed`·`source`가 나머지를 싣는다(§10.1).
그것을 산문으로 다시 말하는 skill은 봉투가 이미 답한 것을 중복하고 릴리스마다 낡는다. 봉투가 원리적으로
실을 수 없는 것 — 왜 naive timestamp를 대신 변환하지 않는가 같은 도메인 지식 — 만 그것을 소유하는 skill의
reference에 남는다.

#### 설치 경로

다음 path는 selected target이 skill을 발견하기 위해 사용하는 **normative product contract**다. 일반적인
directory convention이나 architecture candidate가 아니다.

| target | skill directory |
|---|---|
| Codex | `.agents/skills/vqapr-<skill-name>/` |
| Claude Code | `.claude/skills/vqapr-<skill-name>/` |
| explicit custom root | `<user-selected-output>/vqapr-<skill-name>/` |

각 directory의 required entrypoint는 그 안의 `SKILL.md`다. `references/`, `scripts/`, `examples/`, `assets/`
같은 보조 resource는 해당 target protocol이 허용하는 범위에서 둘 수 있으며, SKILL.md에서 **한 단계 깊이로만**
가리킨다 — reference가 다시 reference를 가리키면 읽는 쪽이 부분 읽기로 끝내고 불완전한 정보를 얻는다.

custom target root는 user가 명시적으로 선택해야 하며 package가 임의의 output location을 추측하지 않는다.

#### 여러 target에 설치된 같은 skill은 byte-identical하다

한 target을 authoritative로 두고 다른 target에 pointer를 놓지 않는다. 모든 target이 같은 bytes를 받는다.

pointer 방식은 복사본이 stale해지는 것을 막으려는 것이었다. 그러나 §11.3의 출하 해시 판정이 생기면 복사본이
어긋났다는 사실 자체가 target별로 드러나므로, 막을 이유가 사라진다. 반대로 pointer는 읽는 쪽에 한 단계를
더 강요하고, 그것은 위에서 금지한 중첩 참조와 같은 문제다.

이 규칙 때문에 skill 안에서의 상대 경로가 target과 무관해진다 — §11.3의 해시 표가 target별로 항목을 두
벌 갖지 않는 이유다.

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

#### 설치본의 출처는 출하 해시로 판정한다

"설치본이 우리가 준 그대로인가"는 manifest가 아니라 **내용**이 답해야 한다. manifest는 지워질 수 있고,
skill directory는 손으로 복사되거나 git으로 clone되어 manifest 없이 도착할 수 있다. 그런 설치본도 판정되어야
한다.

그래서 package는 자신이 **정식 릴리스에서 출하한 적 있는 모든 파일 내용의 해시**를 들고 다닌다. 키는 skill
안에서의 상대 경로이며, 값은 그 내용이 처음 출하된 릴리스다.

판정은 두 물음으로 끝난다.

| 지금 출하본과 같은가 | 출하한 적 있는 내용인가 | 판정 |
|---|---|---|
| 그렇다 | — | `current` |
| 아니다 | 그렇다 | `outdated` — 이전 릴리스의 정본이다 |
| 아니다 | 아니다 | `modified` — 우리가 출하한 어떤 판과도 다르다 |

`outdated`는 **확인 없이 갱신한다.** 잃을 것이 없다 — 사용자가 손대지 않은 이전 릴리스의 정본이기 때문이다.
`modified`는 **명시적 확인 없이 덮어쓰지 않는다.** 사용자의 작업이 거기 있다.

이 표는 릴리스 시점에 실제로 출하되는 내용에서 생성되며, 표에 없는 내용으로 릴리스하려는 시도는 실패한다.
손으로 관리하면 반드시 잊는다.

**표에서 항목을 제거하지 않는다.** 오래된 릴리스의 해시를 지우면 그 판을 설치해둔 사용자는 손대지 않았는데
`modified` 판정을 받고, 확인 절차를 습관적으로 건너뛰는 법을 배운다 — 이 판정이 막으려던 바로 그 습관이다.

판정은 target별·파일별로 이루어진다. 한 target의 사본만 수정된 경우 그 사실이 그대로 보고된다.

**우리가 출하한 적 없는 경로에 있는 파일은 우리 것이 아니다.** 그것은 보고되며 제거되지 않는다. skill
directory는 user가 자기 메모를 둘 수 있는 곳이고, 그것을 지우는 것은 vqapr가 소유하지 않은 것을 지우는
일이다.

#### 낡은 설치본은 명령을 방해하지 않고 알려진다

설치본이 낡았다는 사실은 refusal이 아니다. 명령은 정상적으로 끝나고, 경고는 **stdout이 아닌 곳으로** 나간다.
stdout은 §10.1의 단일 봉투 하나만 싣는다 — agent의 파싱 경로가 하나라는 것이 그 봉투의 존재 이유이므로,
경고 한 줄 때문에 그것을 깨지 않는다.

경고할 자리는 skill 관련 명령 하나가 아니다. 낡은 skill이 해를 끼치는 순간은 agent가 그것을 읽고 **다른**
명령을 실행할 때이므로, 판정은 특정 명령이 아니라 공유 경로에 있어야 한다.

#### UC-ONBOARD-001 — Preview / apply / update / remove

installed project에서 onboarding 변경을 preview, apply, update, remove할 수 있고 product-owned 영역만 안전하고
idempotent하게 변경한다.

#### UC-ONBOARD-002 — 낡은 것과 수정된 것을 구별한다

user가 package를 upgrade한다. 설치되어 있던 skill 중 일부는 그 사이 내용이 바뀌었고 일부는 그대로다.
user는 그중 하나의 reference file을 자기 프로젝트에 맞게 편집해 두었고, 다른 skill directory에는 자기 메모
파일을 하나 넣어 두었다.

update는 **바뀐 skill만** 대상으로 하고, 그중 user가 손대지 않은 파일은 확인 없이 갱신하며, 편집된 파일은
갱신하지 않고 그 사실과 이유를 보고한다. user의 메모 파일은 언급되되 제거되지 않는다. user가 명시적으로
덮어쓰기를 요청하면 편집된 파일도 갱신된다. 어느 경우에도 어떤 파일이 왜 그렇게 처리되었는지가 결과에
남는다.

### 11.4 Optional sample journey

fresh user가 전체 mental model을 확인할 수 있도록 package는 명시적으로 materialize할 수 있는 작은 sample data,
sample project-local logic, config, expected result를 제공한다.

```text
sample data registration
|-> direct StrategyModel: signal + signed weights + research backtest
|-> DataModel output -> StrategyModel: signed weights + research backtest
|-> optional Ensemble StrategyModel
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
대화나 점진적 configuration을 package가 세션 사이에 암묵적으로 보존하는 것은 current requirement가 아니다.
Model state 연속성은 §5.7의 명시적인 committed state 선택으로만 제공한다.

working checkpoint를 재개할 때는 적어도 Model implementation, configuration, dataset binding과 cutoff, training
window, random-seed policy, operation/subperiod identity가 동결된 값과 같아야 한다. 하나라도 다르면 같은 계산의
재시도로 취급하지 않는다.

#### UC-CONFIG-001 — 점진적 구성과 완전한 freeze

user가 여러 번의 상호작용으로 execution environment를 구성한 뒤 run을 시작한다. 시작된 run은 complete frozen
input과 안정적인 identity를 유지하고, 이후 project 변경의 영향을 받지 않는다.

### 12.2 Config는 의미를 선언하지만 의미를 대신하지 않는다

config-driven workflow는 reproducibility를 위한 수단이다. 비슷한 field name, class path, default 값이 경제적
의미를 확정하지 않는다. **user-confirmed binding과 validated contract만 frozen config에 들어간다.**

### 12.3 Local extension

#### user가 작성할 수 있는 것은 넷이다

| 확장점 | 무엇을 정하는가 | package built-in |
|---|---|---|
| **DataModel** | 어떤 값을 만드는가 | 없음 |
| **StrategyModel** | 자본을 어떻게 나누는가 | **없음** — §2.7의 proprietary alpha 원칙 |
| **Exchange** | 어느 venue에서 어떤 규칙으로 체결되는가 | 있음 (academic, physical) |
| **Constraint** | 무엇을 지켜야 하는가 | 있음 (§7의 둘) |

**user가 작성할 수 없는 것**: actual account authority와 그 상태 전이 유효성, valuation과 NAV 정의,
intended→requested 변환, run lifecycle과 이벤트 순서, evidence 기록. 이들은 결과의 의미를 정의하므로
project마다 달라지면 **두 run을 비교할 수 없게 된다.**

**built-in과 project-local extension은 같은 등록·검증 경로를 통과한다.** package가 자기 built-in에만
허용하는 내부 접근이 있으면 built-in은 §2.7이 약속한 executable example이 아니라 재현할 수 없는 예시가
된다. built-in이 사용하는 capability는 project-local extension도 사용할 수 있어야 한다.

#### 식별과 검증

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

#### UC-EXTENSION-002 — Project-local StrategyModel의 검증과 재현 가능한 실행

fresh installed project에서 user가 documented public contract만 사용하는 local StrategyModel을 작성한다. StrategyModel은
필요한 dataset/artifact와 output semantics를 선언하고 package validation을 통과한 뒤에만 reusable extension으로
등록된다. 이후 research 또는 daily execution은 user가 선택한 **exact registered version**을 사용하고 실제
dependency를 result에 남긴다. 등록 뒤 source나 contract가 바뀌면 이전 registration을 암묵적으로 latest code에
연결하지 않고 **compute 전에 drift를 명시적으로 보고**해야 한다.

#### UC-EXTENSION-003 — Project-local Exchange와 Constraint

user가 자기 venue의 체결 규칙을 표현하는 local Exchange를, 그리고 자기 mandate를 표현하는 local
Constraint를 작성한다. 둘 다 built-in과 **같은 계약, 같은 검증, 같은 등록 경로**를 사용하며, 등록 결과와
frozen run input에서 built-in과 구분되지 않는다. local Constraint는 자신이 요구하는 data를 선언하고, 그
data가 없으면 결과를 만들기 전에 실패한다. local Exchange는 자기 체결 테이블·수량 규칙·비용 규칙을
선언하며, package는 그것이 §6.3의 불변식을 지키는지 deterministic하게 판정한다. **어느 쪽도 account
authority, valuation, run lifecycle을 재정의할 수 없다.**

### 12.4 누가 무엇을 소유하는가

**vqapr가 소유:** project initialization과 frozen invocation, logical dataset registration과 capability binding,
field semantics·unit·currency·timezone·universe·tradability 구분, point-in-time materialization과 bounded access,
signal/alpha weight/ensemble/intended portfolio/artifact contract, DataModel result·StrategyModel intent·execution
profile·actual-state result 사이의 compatibility, order conversion semantics와 clipping/failure diagnostics,
constraint declaration·adjustment·validation·finding contract, signed alpha diagnostics와 long-only physical
construction, instrument semantics와 execution-policy resolution, portable artifact envelope·lineage·catalog·
  reporting, Model state reference와 working/committed 저장 lifecycle, deterministic component-agenda callback 전달과 run
  종료 evidence 확정, actual-account monitoring, agent-readable documentation과 stage-based error.

**user project가 소유:** source data와 그 경제적 의미, availability·delivery lag·restatement 가정, universe·
benchmark·sector·factor 정의, signal model과 alpha policy code, risk·cost·constraint·execution policy, constraint
  metric의 경제적 의미와 bound, compliance reference data의 applicability, project-local extension과 report
  composition, StrategyModel의 decision-trigger 규칙과 Model payload의 내용·저장·복원 구현, research objective와
  promotion decision.

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
- private payload의 로컬 파일 경로를 memory에 넣어 durable Model state라고 주장
- consumer-purpose alias를 dataset registration에 새기는 것
- observation coverage나 execution rows로 operation occurrence를 만들거나 StrategyModel의 decision을 Flow가
  대신 계산하는 것
- StrategyModel이나 DataModel에 체결 테이블, 전체 agenda 또는 future occurrence 목록을 노출하는 것

---

## 13. Current scope와 future work

### 13.1 Current scope

physical simulation의 현재 scope는 **주식과 ETF**다. 별도 academic profile은 Stock, ETF, Index, Factor의
hypothetical signed evaluation을 지원한다.

- cross-sectional signed signal과 alpha research
- ML training/inference (model implementation은 project 소유)
- 동일한 frozen Model invocation 안에서 private payload checkpoint를 저장하고 재개
- stored signal/alpha reuse와 ensemble
- 반복 재학습을 포함한 파생 데이터 생산과 재사용
- long-only enhanced-index physical portfolio
- zero-friction fractional academic execution profile
- ETF의 physical/opaque 처리와 user StrategyModel이 명시적으로 PIT constituent data를 소비해 계산하는 look-through
- historical backtest와 portable research catalog
- actual fill, marked state, bounded strategy state에 의존하는 path-dependent StrategyModel
- 하나의 portfolio에서 여러 주식·ETF와 shared cash를 함께 처리하는 multi-instrument simulation
- daily observation/valuation, 선택적 lower-frequency decision, 독립 monitoring을 결합하는 multi-frequency workflow
- stateful callback decision trigger, explicit hold, dense actual-account evidence
- standalone constraint adjustment와 independent monitoring artifact
- MVP hard constraint: no-short와 time-varying single-name cap
- **지원되는 order의 전량 체결과 주식·ETF cash의 즉시 결제를 가정한 simulation**
- 가격 축을 갖춘 source 또는 §4.4로 등록한 derived unit price를 사용하는 closed-loop research

### 13.2 Out of scope — 지원한다고 추정하지 않는다

- borrow, locate, margin, recall, borrow fee를 포함한 executable real short
- derivative margin, funding, expiry, 강제청산의 complete lifecycle
- **차입** — 보유 현금보다 많이 투자하는 것. 아래 참고
- dividend/distribution과 기타 instrument lifecycle cash flow
- partial fill, pending/cancel order state, 실제 주식·ETF settlement cycle
- prepared production decision, external OMS reconciliation, live account authority
- direct broker connectivity, secret management, always-on OMS/scheduler, alert delivery
- user가 제공하지 않은 availability, universe, shortability truth의 자동 추정
- **방향별 거래 가능 여부** — 매수만 불가능하고 매도는 가능한 상태. 거래 가능 여부는 참/거짓 하나이며
  방향을 가르지 않는다(§4.5). 아래 참고
- **가격 제한(상하한가) 모델링** — 상한가·하한가 도달 여부의 판정과 그에 따른 체결 제약
- merger, spin-off, delisting을 포함한 security-master event의 **원천 해석·변환**
- **상태 표면의 자율적 확장** — Model이 `memory`와 `payload` 밖에 임의의 이름으로 durable state를 늘려가는
  것. **크기의 문제가 아니다** — payload는 신경망 weight처럼 큰 값을 담을 수 있다. 표면이 하나로 닫혀
  있지 않으면 무엇을 저장하고 무엇을 다음 invocation에 넘길지 정할 수 없다(§5.7)
- **중첩 실행** — 하나의 판단 안에서 다른 판단 과정을 실행하는 것. 파라미터 후보를 각각 backtest해
  비교하는 것이 대표적이다. 같은 목적은 **각 후보를 별도 run으로 실행하고 그 결과를 조합하는 것**으로
  표현한다(§5.4)
- **future agenda를 읽어 판단하는 Strategy trigger** — StrategyModel은 current occurrence만 보므로 자신이
  마지막 occurrence인지 판정하지 못한다. month-end callback이 필요하면 project가 그 instant를 Strategy
  configuration이 참조하는 finite agenda에 명시한다. package가 calendar를 추론하거나 Flow가 decision을
  대신 선택하지 않는다
- **actual state에 의존하는 model 학습** — 자기 매매 결과를 보고 정책을 갱신하는 방식(강화학습 계열).
  §2.3이 DataModel을 execution 경로 밖에 둘 수 있는 것은 학습이 계좌를 보지 않기 때문이며, 이 예외를 열면
  파생 데이터의 재사용 가능성이 무너진다
- **중단된 simulation run 전체의 재개** — event cursor, decision, fill, Account commit, publication을 포함한
  run은 current scope에서 처음부터 다시 실행한다. §5.7의 단일 Model 학습 checkpoint 재개와는 다른 기능이다

merger, spin-off, delisting처럼 instrument identity, tradability, reference state를 바꾸는 사건의 해석과 변환은
vqapr가 아니라 **security master와 ETL pipeline의 책임**이다. vqapr는 향후에도 원천 corporate action을 자체
해석하지 않고 이미 정규화된 instrument/reference data만 소비한다. 따라서 이것은 vqapr의 readiness gap이 아니다.

#### 차입은 exposure를 키우는 것과 다르다

**gross exposure를 키우는 것 자체는 차입이 아니다.** 자본 100에서 long 200 / short 100을 잡으면 공매도 대금이
매수를 조달하므로 보유 현금이 정확히 0이 되고 빌린 것은 없다. 이런 portfolio는 현재 범위 안이다.

**차입은 보유 현금이 음수가 되는 것**이다. 이것은 범위 밖이며, 계좌 상태가 그렇게 되는 결과는 계산 전에
실패한다. 차입을 지원하려면 **차입 비용, 유지증거금, 강제청산**을 함께 정의해야 한다. 그것 없이 차입만
허용하면 레버리지를 키울수록 대가 없이 수익이 커지는 결과를 보고하게 된다. `UC-REAL-SHORT-001`이
executable short에 요구하는 것과 같은 조건이다.

**유휴자본이 수익을 내는지는 user가 선언한다.** 보유 현금 자체는 이자를 만들지 않는다(그것은
`UC-CASHFLOW-001`의 future 항목이다). 무위험자산 수익을 반영하려면 §4.4로 등록한 자산을 **포지션으로**
보유한다. 그러면 무엇을 얼마나 들었는지가 result의 dependency로 남는다. package가 유휴자본에 조용히 수익을
붙이지 않는다.

#### 방향별 거래 가능 여부는 지정가 주문이 들어올 때 되살아난다

방향을 가르는 이유가 서로 다른 여러 가지다. 상한가는 매수만, 하한가는 매도만, 공매도 금지 종목 지정은
매도만 막고, 유동성 부족은 양쪽에 걸린다. 이것들을 참/거짓 두 개로 뭉치면 **왜 거래할 수 없는지가
사라진다.** 그리고 상하한가를 제대로 다루려면 가격 제한 자체를 모델링해야 하므로 지금 하려는 것보다 훨씬
크다.

현재 필요한 것은 하나뿐이다 — **이 종목을 이번 체결에서 뺀다.**

**이 질문은 지정가 주문이 범위에 들어올 때 되살아난다.** 현재는 지원되는 주문을 전량 체결하므로 매수와
매도가 다른 가격 조건을 볼 일이 없다. 지정가 매칭이 생기면 매수 지정가는 저가와, 매도 지정가는 고가와
비교해야 하고 그때 방향이 갈린다. 그 기능을 만들 때 이 항목을 함께 본다.

#### 왜 중첩 실행을 범위 밖에 두는가

하나의 판단 안에서 다른 판단 과정을 실행하면 **시간을 진행시키는 주체가 둘 이상이 된다.** 깊이에 경계가
없어지고, 계산량이 후보 수와 재생 구간의 곱으로 늘어난다.

그리고 **바깥에서 표현할 수 있다.** 후보를 각각 실행하고 그 결과를 읽어 고르는 것은 이미 지원하는
composition이다(§5.4). 바깥으로 빼면 각 후보가 실제 체결과 비용을 거치고, 후보 성과를 읽는 시점 경계도
다른 관측과 같은 방식으로 지켜진다.

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
decision으로 추가한다. 이 future use case는 event cursor와 Account/execution commit을 포함하며, 현재 지원하는
`UC-STATE-002`의 단일 Model invocation checkpoint 재개를 포함 범위가 더 큰 것으로 바꾸지 않는다.

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
- `UC-PIT-001`처럼 파생 계산이 요구하는 binding이 없으면 계산 전에 실패하고 reusable success를 만들지 않는다.
- `UC-LOOKBACK-001`의 exact lookback이 store query까지 강제되고 coverage가 evidence에 남는다. **모든 lookback은
  과거 방향이며 미래 관측을 당겨 읽는 경로가 없다.** `rows`는 (instrument × field)별로 센다.
- 계산이 만든 데이터도 원본과 같은 등록 계약으로 읽히고, 그 `available_at`은 **생산자가 아니라 package가
  정한다.**
- `UC-DATA-003`처럼 field가 물리 컬럼인지 별도 저장 단위인지에 따라 소비자의 requirement 선언이 달라지지
  않는다. 저장 방식을 바꿔도 소비자가 변하지 않는다.
- 등록은 **선언된 availability의 준수만** 보장하며, 등록된 값이 point-in-time으로 안전한지는 판정하지
  않는다. 그 확인은 `UC-AGENT-002`의 인터뷰가 담당하고 결과는 limitation으로 남는다.

### 14.2 Research composition

- `UC-SIGNAL-001`의 direct StrategyModel과 `UC-SIGNAL-002`의 stored model output 경로가 모두 동작한다.
- `UC-MODEL-001`처럼 portfolio 없이 DataModel signal을 연구·평가·저장할 수 있다.
- `UC-MODEL-002`에서 statistical factor-return estimate를 executed portfolio return/NAV로 표시하지 않는다.
- DataModel이 actual Account state를 소비하지 않으며, 반복 재학습이 같은 DataModel의 여러 실행으로 표현된다.
  이전 Model state를 이어간 결과는 순차 생성임이 드러나고 actual-state dependency와 구분된다.
- `UC-MODEL-003`에서 각 rolling window의 CNN을 fresh initialization하고 subperiod 사이에 weight를 warm start하지
  않으며, 각 out-of-sample score가 사용한 committed Model state를 가리킨다. StrategyModel은 weight가 아니라
  materialized score를 소비한다.
- `UC-FACTOR-001`에서 characteristic과 membership을 재사용 가능한 result로 만들고, 같은 membership을 소비한
  여러 버킷 portfolio가 그 사실을 dependency로 증명하며, 버킷 조합 팩터와 직접 실행 팩터가 zero-friction
  profile에서 일치한다.
- signed weight는 budget semantics와 actual dependency를 보존하고 producer 재실행 없이 재사용할 수 있다.
- `UC-ALPHA-BUDGET-001`에서 flexible residual을 fixed budget으로 자동 확대하지 않고, **선언과 실제 weight가
  어긋나면 결과를 만들기 전에 실패한다.** 두 결과의 budget이 다르다는 이유로 소비를 막지는 않는다.
- `UC-BUILTIN-001`에서 built-in weighting 함수가 data/state/clock에 접근하지 않고, 부수 입력의 결측에 계산 전
  실패하며, 종목을 빼고 재정규화하지 않는다. 제외된 종목은 호출자에게 값으로 반환되어 evidence에 남는다.
- `UC-ALPHA-PATH-001`에서 path-dependent result를 producer rerun 없이 frozen member input으로 소비하고, source
  state identity와 반영 범위를 새 lineage에 보존하며 current-state recomputation으로 표시하지 않는다.
- `UC-STATE-001`에서 체결이 없는 callback과 run 경계를 넘어 Model state가 이어지고, 다음 run의 시작 state는
  명시적으로 지정된다. state 갱신이 execution 발생 여부에 종속되지 않는다.
- `UC-STATE-002`에서 JSON memory와 optional payload가 같은 state identity로 저장·복원되고, 같은 frozen
  operation만 working checkpoint를 재개한다. 다른 identity는 거부되고, 새 계산이 완료되기 전에는 기존
  committed state가 유지된다.
- state reference는 Model이 기록한 로컬 payload 경로에 의존하지 않고 compatible process에서 memory와 payload를
  함께 복원한다. payload가 없는 Model은 strict JSON memory만으로 같은 계약을 만족한다.
- `UC-CALENDAR-001`은 retired current requirement로 남아 ID가 재사용되지 않는다. component-owned
  `OperationAgenda`는 venue calendar inference가 아니라 explicit finite occurrence input이다.
- `UC-TRIGGER-001`에서 Flow가 frozen callback occurrence를 하나씩 전달하고 StrategyModel이 committed state로
  cadence를 계산한다. 해당 evaluation time에 observation row나 execution row가 없어도 callback은 성립하며,
  `NoDecision`은 실패가 아니라 state를 이어가고 기존 pending intent를 유지하는 정상 결과다.
- `UC-TIME-002`에서 Strategy·Valuation·Monitoring의 독립 agenda, Flow-stamped decision time,
  intent-derived exact target, latest pending replacement, fixed priority와 inclusive run horizon이 같은
  observable trace로 검증된다.
- `UC-ENSEMBLE-001`에서 기존 StrategyModel result를 member로 조합하고 ticker-level netting과 lineage를 확인할 수 있다.
- `UC-ALPHA-CHILD-001`은 같은 exact parent intent를 StrategyModel/DataModel 재실행 없이 두 execution convention에서
  비교하며 parent result는 불변이다. adaptive scenario는 `UC-ALPHA-ADAPTIVE-001`의 state/evidence를 별도로
  만족한다.

### 14.3 Construction, execution, monitoring

- constraint가 없는 research는 `UC-CONSTRAINT-001`처럼 실행되고, constraint workflow는 필요한 data를 호출
  시점에 발견한다. (`UC-CONSTRAINT-002`)
- academic long-short, peer momentum, top-N long-only, enhanced index처럼 executable한 모든 StrategyModel은
  construction 규칙이 달라도 **frozen intended portfolio → execution-time order conversion → selected profile →
  fill → account commit → valuation → feedback**의 같은 observable lifecycle을 따른다. (`UC-PORTFOLIO-001`,
  `UC-PROFILE-001`)
- 제약은 **판단 시점에** 반영되고 그 결과가 만들어질 때 독립적으로 검증된다. **execution 경로에는 제약
  평가가 없다**(§7.1). 수량 변환 때문에 뒤늦게 생긴 위반은 `UC-CONSTRAINT-ADJUST-001`처럼 진단에 남고
  `UC-EXEC-003`의 monitoring이 잡으며, 그 때문에 execution을 되돌리지 않는다.
- budget은 현금 범위 선언으로 표현되고, 현금은 유도값이 아니라 결과에 남는 결정된 값이다(§5.5).
- `UC-EXEC-001`에서 decision과 execution outcome을 분리하고 committed result만 다음 decision에 feedback한다.
- `UC-EXEC-002`는 fill timing과 model limitation을 명시하며 look-ahead를 허용하지 않는다.
- execution input row density는 callback occurrence 집합·시각·순서를 바꾸지 않는다. full downstream trace
  동치는 selector-relevant target candidates, selected snapshot, price/tradability와 다른 frozen inputs가
  동일하고 추가 rows가 non-selected일 때만 요구한다.
- target 없음, `execution_time <= decision_time`, target after `end`, invalid timezone/intent/provenance는
  callback 전체를 atomic하게 실패시키며 이전 pending intent와 committed authority를 유지한다.
- 새 accepted intent는 target resolution 뒤 single pending pointer를 교체한다. 이전 decision trace는 남고
  별도 `SUPERSEDED` artifact는 없다.
- 같은 instant의 이전 due execution·Account commit·feedback은 later callback보다 먼저이며, independent
  valuation과 monitoring이 뒤따른다.
- **fractional/lot quantity는 selected venue가 instrument별로 결정한다.** account validity는 signed 또는
  long-only position transition만 검사하며, 두 profile에서 같은 atomic commit/history/valuation 결과 shape를
  사용한다. (`UC-ACADEMIC-001`)
- `UC-COST-001`~`UC-COST-004`, `UC-CLOSED-LOOP-001`, `UC-SCALE-001`, `UC-LOOKTHROUGH-001`~`003`의
  current-scope outcome을 만족한다.
- path-dependent, multi-instrument, multi-frequency 시나리오에서 actual-state-dependent decision, shared portfolio
  state, independent cadence를 검증한다.
- `UC-ACCOUNT-HISTORY-001`처럼 strategy state 없이 actual state 이력만으로 stop-loss와 cooldown을 표현할 수 있고,
  이력 접근이 strategy state 보유 여부에 종속되지 않는다. 계좌 evaluation-time 시계열과 instrument panel을 선택해
  구독할 수 있다.
- `UC-EXEC-003`처럼 decision이 없는 evaluation time에도 monitoring finding을 만든다.
- execution이 있는 run은 §6.3의 체결 테이블 없이 시작하지 못하고, execution이 없는 workflow는 그것 없이
  완결된다. (`UC-MODEL-001`, `UC-CONSTRAINT-001`)
- `UC-TRADABILITY-002`처럼 판단 이후 발생한 거래정지가 그 종목의 체결 수량 0과 사유로 남고 같은 결정의
  나머지 종목 체결을 막지 않는다. 반대로 `UC-FILL-001`의 체결 가격 부재는 그 결정의 주문 집합 전체를
  mutation 전에 중단시킨다. **두 실패는 같은 등급이 아니다.**
- 어느 종목이 왜 줄었거나 체결되지 않았는지가 결과에서 확인된다. 남은 현금을 종목 전체에 나눠 조용히
  줄이는 방식으로 처리하지 않는다.
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
- `UC-REPORT-002`에서 DataModel과 StrategyModel의 diagnostic row를 typed table artifact로 보존하고, producer
  재실행 없이 report하며, 이를 Model state나 actual state로 취급하지 않는다. 각 행은 어느 run의 누가 어느
  시각에 남겼고 **그 시각이 어떤 종류인지**를 함께 갖고, producer가 그 값을 주장하지 못한다.
- recorder는 Model payload나 checkpoint 저장소가 아니며, recorder만으로 중단된 학습을 복원할 수 없다.
- diagnostic 기록은 §5.3의 result category가 아니며 portfolio return, NAV, PnL, turnover의 출처가 되지
  않는다.
- `UC-REPORT-001`의 renderer 독립성은 **값과 renderer가 분리되어 있다는 것**으로 판정한다. vqapr는 table과
  machine-readable renderer를 제공하고 visualization은 제공하지 않으며, 그 부재가 결함이 아니라 §12.4의
  소유권 경계다.
- constraint 선언이 정체를 유지해 **어느 constraint가 얼마나 초과했는지**가 결과에 남고, 구성과
  monitoring이 같은 선언을 소비한다. 선언이 요구한 data가 없으면 결과를 만들기 전에 실패한다.
  (`UC-CONSTRAINT-002`, `UC-EXEC-003`)
- `UC-EXTENSION-001`에서 agent가 만든 local transform의 compatibility를 package가 deterministic하게 판정한다.
- `UC-EXTENSION-003`에서 local Exchange와 local Constraint가 built-in과 같은 경로로 등록되고, frozen run
  input에서 built-in과 구분되지 않는다. built-in만 쓸 수 있는 내부 capability가 존재하지 않는다.
- `UC-EXTENSION-002`에서 local StrategyModel을 documented public contract로 검증·등록하고 user-selected exact
  version으로 실행하며 source drift와 implicit latest selection을 compute 전에 거부한다.

---

## 15. Compatibility gates

compatibility gate는 구현 구조가 아니라 **기존 observable result의 의미가 보존되는지** 판정한다.

### 15.1 Reference 또는 calculation 변경

reference code, borrowed calculation, cost/metric rule을 바꾸면 source provenance와 영향받는 use-case ID를
식별한다. frozen fixture에서 numerical result뿐 아니라 requested/dealt quantity, actual-state timing, PIT cutoff,
unsupported failure, evidence가 이전 contract와 일치하거나 **명시적으로 versioned change**여야 한다.

### 15.2 Runtime 또는 component 변경

DataModel, StrategyModel, execution mechanism, artifact backend, extension mechanism을 교체해도 다음을 재검증한다.

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
2. **operation time과 data row time의 분리** — component-owned finite agendas가 callback·valuation·monitoring
   occurrence를 만들고 ExecutionTable은 intent-derived exact execution snapshot만 제공한다
3. direct StrategyModel, stored model output, ensemble StrategyModel의 선택 가능한 composition
4. path-dependent StrategyModel, multi-instrument portfolio, multi-frequency workflow
5. **portfolio return을 주장하는 모든 것은 하나의 execution spine을 통과한다**
6. DataModel result, StrategyModel decision, execution outcome의 semantic 분리
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
| `UC-TIME-002` | §3.6 | current |
| `UC-TRIGGER-001` | §3.3 | current |
| `UC-LOOKBACK-001` | §3.5 | current |
| `UC-DATA-001`, `UC-DATA-003` | §4.1 | current |
| `UC-AGENT-001` | §4.2 | current |
| `UC-DATA-002` | §4.3 | current |
| `UC-PIT-001` | §4.3 | current |
| `UC-TRADABILITY-001` | §4.5 | current |
| `UC-CALENDAR-001` | §3.4 | retired — ID reserved, capability removed |
| `UC-MODEL-001`, `UC-MODEL-002`, `UC-MODEL-003`, `UC-FACTOR-001` | §5.1 | current |
| `UC-SIGNAL-001`, `UC-SIGNAL-002` | §5.2 | current |
| `UC-ENSEMBLE-001` | §5.4 | current |
| `UC-ALPHA-BUDGET-001` | §5.5 | current |
| `UC-BUILTIN-001` | §2.7 | current |
| `UC-ALPHA-PATH-001`, `UC-ALPHA-CHILD-001` | §5.6 | current |
| `UC-STATE-001`, `UC-STATE-002`, `UC-ALPHA-ADAPTIVE-001` | §5.7 | current |
| `UC-PORTFOLIO-001` | §6.2 | current |
| `UC-EXEC-001`, `UC-EXEC-002`, `UC-FILL-001`, `UC-TRADABILITY-002` | §6.3 | current |
| `UC-PROFILE-001`, `UC-ACADEMIC-001` | §6.4 | current |
| `UC-COST-001` ~ `UC-COST-004` | §6.5 | current |
| `UC-ACCOUNT-HISTORY-001`, `UC-CLOSED-LOOP-001`, `UC-SCALE-001` | §6.6 | current |
| `UC-EXEC-003` | §6.8 | current |
| `UC-CONSTRAINT-001`, `UC-CONSTRAINT-002`, `UC-CONSTRAINT-ADJUST-001` | §7 | current |
| `UC-LOOKTHROUGH-001` ~ `003` | §8.2 | current |
| `UC-ARTIFACT-001` ~ `003`, `UC-RESEARCH-001` | §9 | current |
| `UC-REPORT-001`, `UC-REPORT-002`, `UC-MONITOR-001` | §9.4 | current |
| `UC-ERROR-001`, `UC-RETURN-001` | §10 | current |
| `UC-AGENT-002` | §11.1 | current |
| `UC-ONBOARD-001`, `UC-ONBOARD-002` | §11.3 | current |
| `UC-CONFIG-001` | §12.1 | current |
| `UC-EXTENSION-001`, `UC-EXTENSION-002` | §12.3 | current |
| `UC-FUTURE-001`, `UC-PERP-001`, `UC-CASHFLOW-001`, `UC-SETTLEMENT-001` | §13.3 | future |
| `UC-PROD-001`, `UC-PROD-002`, `UC-RECOVERY-001`, `UC-IMPACT-001`, `UC-REAL-SHORT-001` | §13.3 | future |

## Appendix B. 이 경계를 확인한 연구 사례

이 문서의 요구사항 중 여럿은 **실제 연구를 문서에 대입해보다가** 발견했다. 나중에 읽는 사람이 "왜 이렇게
정했나"와 "왜 여기서 멈췄나"를 알 수 있도록, 각 결정을 낳은 구체적 사례를 남긴다.

이 표는 normative가 아니다. 요구사항 자체는 본문에 있다.

### B.1 KRX daily 두 전략 — peer momentum long-short와 5일 top-10 long-only

| 확인한 것 | 정해진 것 |
|---|---|
| 두 전략이 같은 lifecycle을 통과하는가 | 통과한다. 다른 것은 판단 로직과 profile 정책뿐 (§6.1) |
| 등록에 목적별 role(`research_close` 같은)이 필요한가 | 필요 없다. 소비자가 각자 field를 요구한다 (§4.1) |
| 체결 기록의 길이가 거래 횟수인가 | 아니다. dealt 0인 진단 레코드가 섞인다 → intended/requested/dealt/committed 4단 구분 (§2.4) |
| lookback이 다른 두 전략의 첫 판단 시점 | warm-up을 Strategy memory로 표현하고, 그 callback은 실패가 아니라 `NoDecision` |

### B.2 Fama-French 스타일 팩터 — independent double sort

| 확인한 것 | 정해진 것 |
|---|---|
| "매년 6월 마지막 거래일" cadence를 표현할 수 있는가 | project가 해당 instant를 explicit finite agenda로 준비하면 표현할 수 있다. package가 calendar를 추론하거나 Strategy에 future agenda를 보여주지는 않는다 (§3.3–§3.4) |
| 거래소 calendar 파일 없이 시작할 수 있는가 | 가능하다. callback agenda는 project가 준비한 explicit occurrences이고 execution parquet은 selected target의 exact snapshot만 제공한다 (§3.4, §6.3) |
| 여러 버킷 portfolio가 같은 분류를 썼음을 증명할 수 있는가 | 분류를 재사용 가능한 result로 만들면 dependency로 증명된다. 별도 grouping 개념은 만들지 않았다 (`UC-FACTOR-001`) |
| 버킷별 구성종목 수를 어디서 얻는가 | 분류 result에 이미 있다. actual state에 물을 필요가 없다 |
| 가중 방식과 리밸런싱 주기의 관계 | 시가총액 가중은 보유만 해도 유지되지만 균등 가중은 그렇지 않다. 따라서 cadence가 결과를 바꾸며 **어느 cadence도 정답이 아니다.** package가 대신 고르지 않는다 |

검토 대상: Kimchi Factor 방법론 재현 (KOSPI 기준 breakpoint를 양 시장에 적용, 3개월 보고 지연, 6월 형성,
VW/EW, 2×3과 5분위, 일간·월간 독립 산출).

### B.3 Betting-Against-Beta — 레버리지처럼 보이는 것

$$r_{BAB} = \frac{1}{\beta_L}(r_L - r_f) - \frac{1}{\beta_H}(r_H - r_f)$$

| 확인한 것 | 정해진 것 |
|---|---|
| BAB에 차입이 필요한가 | **필요 없었다.** 자본 100 기준 long 1.43 / short 0.71이면 보유 현금이 +0.28이다. "leverage"는 β 조정이지 금융 차입이 아니었다 |
| exposure를 키우는 것과 차입의 경계 | 보유 현금이 음수가 되는 것만 차입이다. long 2.0 / short 1.0은 현금이 0이 될 뿐 빌린 것이 없다 (§13.2) |
| 차입을 허용해야 하는가 | **아니다.** 차입 비용·유지증거금·강제청산 없이 허용하면 레버리지를 키울수록 대가 없이 수익이 커진다 |
| 유휴자본의 $r_f$를 어떻게 반영하는가 | 현금에 이자를 자동으로 붙이지 않는다. §4.4로 등록한 무위험자산을 **포지션으로** 보유해 user가 선언한다 (§13.2) |
| 예산이 항상 gross 1 또는 ±1인가 | **아니다.** BAB는 매 리밸런싱마다 $\beta$에 따라 예산이 달라진다. 예산 표현을 하나로 고정하지 않은 이유의 실제 근거다 (§5.5) |

### B.4 ML 연구와 DataModel의 시간 경계

StrategyModel은 판단 1회에 평가 시각이 하나지만, 반복 계산 결과를 만드는 DataModel은 **출력 행마다 평가 시각이
하나**다. 이 차이를 어떻게 다룰지가 오래 열려 있었고, 참조 구현(Qlib)의 실제 구조를 확인하면서 정리했다.

| 확인한 것 | 정해진 것 |
|---|---|
| 참조 구현은 ML을 어떻게 다루나 | **학습을 backtest loop 안에 넣지 않았다.** 미리 계산한 예측표를 loop가 읽을 뿐이다. 이 제품의 DataModel/StrategyModel 분리와 같은 구조다 |
| 반복 계산의 look-ahead를 무엇이 막나 | **각 시점에 허용된 관측만 보이는 것 자체가 막는다.** 전체 기간을 한 번에 학습한 결과가 섞여 들어갈 경로가 없으므로 별도 감지 장치를 두지 않는다 |
| 미래를 읽는 계산이 필요한가 | **필요 없다.** "$t$의 20일 후 수익률"은 "$t{+}20$에 기록된 20일 수익률"과 같은 값이고, 후자는 미래를 읽지 않는다(§3.5) |
| 반복 재학습이 새 개념인가 | **아니다.** 이미 모든 계산에 적용되는 요구만 만족하면 된다(§5.1) |
| 한 번에 넓은 구간을 계산하면 빠르지 않나 | **`available_at`이 늦어져 쓸모없어진다.** 넓게 읽을수록 결과가 늦게 유효해지므로 금지 규칙 없이 억제된다 |
| 계산 결과를 어떻게 다루나 | **원본과 같은 등록 계약**을 따르고 같은 방식으로 읽힌다(§4.1) |

**기록해 둘 오판**: 검토 중에 "시점마다 관측 범위를 다시 잡으면 계산량이 불가능하다"고 판단한 적이 있으나,
이는 **매 시점 원본을 다시 조회한다고 가정**했기 때문이었다. 한 번 읽고 필요한 구간만 잘라 쓰면 지금까지
검토한 사례 대부분이 감당 가능하다. 이 오판 때문에 하마터면 PIT 경계를 성능과 맞바꿀 뻔했다.

**취소한 요구사항**: 반복 재학습 결과에 "어느 구간의 학습에서 나왔는지"를 남기도록 요구하려 했으나 취소했다.
전체 기간 학습이 애초에 불가능하므로 구분할 대상이 없다.

### B.5 Enhanced index — 제약이 걸린 portfolio

벤치마크를 따라가되 알파로 기울이고, 공매도 금지와 종목별 상한을 함께 만족시켜야 하는 전략을 대입했다.
기존 구현이 이 문제를 어떻게 풀었는지도 함께 확인했다.

| 확인한 것 | 정해진 것 |
|---|---|
| 상한에 걸려 잘린 비중은 어디로 가나 | **질문이 성립하지 않는다.** 자르고 재분배하는 것이 아니라 제약을 반영해 한 번에 구성한다. 현금이 결정 변수이므로 잔여를 흡수한다 |
| 그러면 budget이란 무엇인가 | **현금 범위 선언**이다. 별도 개념이 아니라 제약의 한 종류다(§5.5) |
| 현금을 유도할 수 있나 | **없다.** 결정된 값이며 결과에 남는다 |
| 제약을 언제 평가하나 | **판단 시점.** execution은 체결만 한다. execution으로 미루면 그 시점에 할 수 있는 일이 기록밖에 없고, 다시 최적화하는 것은 §2.4가 금지한다 |
| 거래 불가 종목은 | 제외가 아니라 **현재 비중 고정**을 제약으로 표현한다. 조용히 빠지면 §10.2 위반이다 |
| 계산 결과를 믿나 | **아니다.** 만들어진 결과가 선언한 제약을 실제로 만족하는지 독립적으로 다시 판정한다 |
| 수량 변환 때문에 생긴 위반은 | 판단 시점에 알 수 없다. 진단에 남기고 **monitoring이 잡는다**(`UC-EXEC-003`) |

이 대입으로 오래 열려 있던 "budget과 cash를 어떻게 표현하는가"가 닫혔다. 열려 있던 이유가 *"조정이 실현
budget을 바꾼다"*였는데, **조정이 아니라 제약 하 구성**이므로 의도(선언한 범위)와 실현(결정된 값)이 어긋나는
것이 아니라 애초에 서로 다른 자리에 있다.

### B.6 두 역할의 경계 — 무엇으로 가르는가

alpha → ensemble → enhanced index로 이어지는 체인을 대입하면서 §2.3의 경계를 다시 확인했다.

| 확인한 것 | 정해진 것 |
|---|---|
| 두 역할을 무엇으로 가르나 | **execution을 거치는가.** 계좌 접근과 출력 형태는 그 결과다 |
| 배분만 만들고 실행을 건너뛸 수 있나 | **없다.** zero-friction profile을 써도 체결·계좌·feedback은 일어난다 |
| 왜 그런가 | 배분은 체결될 수 있고, 체결되면 return이 생기므로 §2.2가 적용된다 |
| 값과 배분의 차이는 | 시가총액은 계좌가 없어도 정의되지만 weight는 *"무엇의"*가 전제된다 |
| enhanced index는 | 별도 StrategyModel이며, 저장된 alpha를 구독하고 자기도 실행된다(§5.4) |

**기록해 둘 오판 두 개.**

1. *"long-short alpha와 ensemble은 계좌를 안 보니 값을 만드는 역할"* — **"이 예시가 계좌를 안 쓸 수도 있다"와
   "이 역할은 계좌를 볼 수 없다"를 뒤바꿨다.** 그렇게 두면 turnover-aware rebalance, stop-loss, adaptive
   ensemble이 전부 표현 불가능해진다.
2. *"실행 여부는 workflow 선택"* — 정반대다. 배분을 만드는 역할은 실행을 건너뛸 수 없다.

두 오판 모두 **판정 기준을 계좌 접근으로 잡았기 때문**이다. execution 통과 여부로 잡으면 나오지 않는다.
§8.1의 네 층이 같은 경계를 다른 각도에서 이미 말하고 있었다는 것도 뒤늦게 확인했다.

### B.7 데이터 등록과 체결 — 관측과 체결은 다른 세계다

거래정지 데이터가 없는 project와 "다음날 시가로 체결"을 대입하면서, **관측을 읽는 것과 체결하는 것이
같은 계약을 쓸 수 있는가**를 확인했다.

| 확인한 것 | 정해진 것 |
|---|---|
| 둘이 같은 등록·조회 경로를 쓸 수 있나 | **없다.** 관측은 `available_at ≤ t`로 범위를 읽고 체결은 그 시각의 값 하나를 조회한다. **부등호냐 등호냐가 두 세계를 가른다** |
| 그럼 체결 대상에 availability가 필요한가 | **아니다.** availability는 관측자가 미래를 못 보게 하는 장치인데, 체결에는 관측자가 없다. 그 시각의 시장 상태 자체다 |
| 전략이 그것을 읽어도 되나 | **안 된다.** 읽을 수 있으면 어느 종목이 그날 거래 불가가 될지를 판단 시점에 알게 된다. 판단이 일별 관측을 쓰면서 체결은 더 촘촘한 단위로 이루어지는 구성도 표현되지 않는다 |
| 그럼 전략은 거래 가능 여부를 어떻게 아나 | **등록된 data로 따로 소비한다.** 그리고 그것은 **선택**이다. 만들지 않으면 거래 불가 종목에도 주문이 나가고 사유와 함께 남는다 |
| 두 값이 어긋나면 | **그것이 판단과 체결을 나눈 이유 그 자체다.** 하나로 합치면 "전략이 틀렸다"를 표현할 방법이 사라진다 |
| 거래 가능 여부는 몇 개의 값인가 | **참/거짓 하나.** 방향을 가르는 이유가 서로 다르므로 둘로 뭉치면 왜 거래할 수 없는지가 사라진다(§13.2) |
| 관측이 없는 것은 어떤 값인가 | **값이 아니다.** coverage의 문제이며 요구한 operation이 계산 전에 실패한다 |
| 체결 실패는 한 종류인가 | **아니다.** 거래 불가와 관측 부재는 시장 사실이므로 그 종목만 체결 수량 0이고, 거래 가능하다면서 가격이 없는 것은 계약 위반이므로 주문 집합 전체가 중단된다 |
| 등록이 무엇을 보장하나 | **선언된 availability의 준수까지.** 등록된 값이 point-in-time으로 안전한지는 판정하지 않으며, 판정하는 척하면 안 된다 |

**기록해 둘 오판 넷.**

1. *"세로로 긴 표(항목·값 두 컬럼)가 유연해서 좋다"* — **좋은 것은 폴더로 나누는 쪽이고 스키마로 만드는
   쪽이 아니다.** 값 컬럼 하나에 여러 타입이 섞이고 무엇을 읽든 조건이 붙는다. **파티션 키가 스키마를
   결정하게** 하면 그 단점이 전부 사라진다.
2. *"등록 단계에서 위험한 계산을 막을 수 있다"* — **한쪽 문만 잠그는 것.** user가 자신의 데이터 준비
   과정에서 미리 계산해 오면 똑같다. 그리고 막는 것처럼 보이면 방심을 만든다 — **반쪽 보장은 무보장보다
   나쁘다.** §3.2가 이미 정해 둔 경계였다.
3. *"장 종료 시점에 개장 가격으로 체결하면 look-ahead다"* — **방향이 반대다.** 미래를 훔치는 것이 아니라
   지나간 가격을 붙잡는 것이다. 그리고 **package는 값의 관측 시점을 알 수 없으므로 판정할 수 없다.**
   검증이 아니라 limitation의 자리다.
4. *"판단은 했는데 아직 체결되지 않은 것이 겹치면 문제"* — **다른 프레임워크의 문제를 우리 것으로 착각한
   것.** 주문이 살아남는 구조에서는 관리 대상이지만, 여기서는 체결 시점에 전부 결정되고 다음으로 넘어가지
   않는다. 겹친 판단은 그 시점의 실제 계좌를 정확히 읽었을 뿐이며 `UC-CLOSED-LOOP-001` 위반이 아니다.

**참고한 것과 가져오지 않은 것.**

- 기존 구현 하나는 관측이 없는 시점의 행을 **직전 값으로 합성**해 체결에 쓴다. 거래정지된 종목을 직전
  가격에 사고팔 수 있게 되므로 §10.2 목록에 이 항목을 추가했다.
- 다른 구현 하나는 예측값 전체를 전략에 넘기고 **관례로만** 시점 경계를 지킨다. §2.2가 *"접근 불가능성으로
  강제해야 한다"*고 한 것의 실물 반례다.
- 또 다른 구현은 데이터 타입을 고정해 등록이라는 개념 자체가 없다. 그러면 인터뷰도 없어지지만 임의 형태의
  연구 데이터를 담지 못한다. **임의 등록을 고른 대가가 §11.1의 인터뷰**라는 것을 이 대비에서 확인했다.

### B.8 실제 인핸스드 인덱스 운용 연구 — 회전율은 무엇에 대해 재는가

알파 15개를 세 계열로 앙상블하고 KOSPI 200 대비 초과·미달 보유비중으로 바꾸는 실제 연구를 대입했다.
B.5가 이 문제의 구조를 확인한 것이라면, 여기서는 **전체 규모의 연구가 실제로 흐르는지**를 확인했다.

| 확인한 것 | 정해진 것 |
|---|---|
| 목표 배분끼리 뺀 값을 회전율이라 부를 수 있나 | **없다.** 시가총액 가중 지수는 보유만 해도 따라가므로 그 표류는 거래가 아니다. 목표끼리 빼면 **거래하지 않은 것을 거래로 센다.** §10.2가 turnover를 금지 목록에 넣은 것이 이 경우다 |
| 그것을 막는 것은 무엇인가 | **판단이 실제 보유를 보는 것**과 **주문이 committed 보유에서 만들어지는 것**. 둘 다 §2.4가 이미 요구한 것이며 별도 장치가 아니다 |
| ETF를 보유하면 생기는 하한·상한은 새 제약인가 | **아니다.** 직접 보유가 음수일 수 없다는 것과 종목별 상한, 두 가지에서 유도된다. 제약은 실제 보유에만 걸고 노출은 목적함수에만 쓴다(§8.2) |
| 실제 운용의 주문서는 어디에 있나 | **판단 시점의 진단 기록.** 체결 경로가 아니며 기록된 수량은 체결이 아니다(§9.4) |
| 리밸런싱 주기는 선언인가 | **아니다.** 회전율에서 역산한 사후 통계다. cadence는 판단 시점만 정한다(§3.3) |
| 거래정지 종목의 평가는 | **문제되지 않는다.** 거래가 정지되어도 관측은 존재하므로 평가는 정상이고 체결만 이루어지지 않는다 |

**기록해 둘 오판 둘.**

1. *"평균 리밸런싱 주기가 곧 cadence 선언"* — cadence는 **언제 판단할지**만 정하고 포트폴리오가 얼마나
   자주 바뀌는지는 결과다. 매 callback에서 판단하면서 대부분 유지하는 것이 정상이며, 그 둘은 §6.7이 구분하라고
   요구하는 서로 다른 사실이다.
2. *"주문서가 곧 체결 시점의 주문 집합"* — **시점이 다르다.** 실제 주문서는 체결 이전에 이미 아는 가격으로
   수량을 확정하고, 우리 체결은 수량 확정과 체결이 같은 순간이다. 둘을 같은 이름으로 부르면 그 가정이
   숨는다. 이 차이는 legacy OMS의 운영 형태에서 오는 것이므로 **기록으로 남기고 구조는 건드리지 않는다.**

**참조한 구현에서 확인한 것.** 그 구현의 설정 파일에 *"회전율 제약은 배치 계산이 이전 보유를 모르므로
진단 전용이며 코드에서 소비하지 않는다"*고 적혀 있다. 판단이 계좌를 보지 않으면 회전율 제약을 쓸 수 없다는
것을 그 구현이 스스로 기록해 둔 셈이고, 이 제품이 닫힌 고리를 요구하는 이유(§1.2)를 뒷받침한다.
