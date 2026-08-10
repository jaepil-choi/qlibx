# qlibx Product Requirements Document

Status: canonical
Runtime: qlibx-owned event-driven engine (no Qlib runtime dependency)
Current package/import/CLI name: `qlibx`
Final rename target: `vqapr` (확정, 마지막 migration 단계까지 실행 보류)
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

`qlibx` runtime은 **event-driven callback semantics**를 제공해야 한다. Observation, model fit, decision,
execution, valuation과 monitoring은 필요한 cadence와 우선순위를 독립적으로 가질 수 있어야 하며, runtime이
등록된 callback을 결정론적 순서로 호출한다. 특정 component가 전체 lifecycle을 소유하는 하나의
strategy loop로 이 역할들을 합치지 않는다.

이 구조는 다음 observable property를 제공해야 한다.

- 같은 frozen input과 data에서 event 및 callback 순서와 결과가 재현된다.
- 각 callback은 event time과 역할에 허용된 정보만 소비하며 미래 또는 권한 밖 데이터를 우회해 읽지 못한다.
- Fill과 기타 current-scope committed outcome이 actual state에 반영된 뒤 다음 decision의 입력이 된다.
- 새로운 cadence나 lifecycle event를 추가해도 관련 없는 decision, execution 또는 monitoring behavior를
  다시 작성하지 않는다.

PRD는 이를 만족하는 구체적인 queue, context/view, scheduler, callback registry 또는 class decomposition을
지정하지 않는다.

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

본문에서 Qlib, vn.py 또는 NautilusTrader를 이름으로 언급하는 경우 §0.2의 reference source, provenance 또는
characterization 대상만을 뜻한다. 이들은 qlibx runtime dependency나 state authority가 아니다.

`Strategy`, `TradeDecision`, `Executor`, `Exchange`, `Position`, `Account`처럼 역할이 확립된 명칭은 별도 external
package가 명시되지 않는 한 qlibx-owned role을 뜻한다. Reference-specific object, record, pickle 또는 adapter는
optional payload/integration일 수 있지만 qlibx public artifact, validation, clock-bound view와 Ledger commit
boundary를 대체하지 않는다.

본문과 이 절이 충돌하면 §0의 runtime ownership이 우선한다.

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

`qlibx`는 자체 event-driven research와 execution runtime을 소유하는 **재사용 가능한 alpha research
framework**다. Qlib을 포함한 reference implementation은 검증된 산술과 설계의 비교·차용 대상으로만
사용한다.
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
- Decision이 만든 executable intent와 execution을 분리하고, 선택한 Executor, Exchange와 execution policy를
  통해 closed-loop lifecycle로 simulation한다. MVP execution profile은 지원되는 order가 전량 체결되고 주식·ETF의
  cash가 즉시 결제된다고 가정한다. Partial fill, 미체결 order lifecycle과 실제 결제주기는 future work다.
- Strategy decision과 독립적으로 schedule된 monitoring event에서 marked actual account snapshot과 PIT-safe
  compliance data를 평가한다. Decision이 없는 시점에도 monitoring할 수 있으며, finding은 account를 변경하거나
  주문을 직접 생성하지 않는다.
- 성공과 실패, input dependency와 intermediate result를 다음 연구의 출발점으로 보존한다.

이 capability는 독립적으로 사용할 수 있다. 모든 연구가 하나의 end-to-end pipeline을 끝까지 따라야 한다고
강제하지 않는다.

### 1.2 주요 사용자와 product promise

주요 사용자는 quantitative researcher와 research engineer이며, coding agent는 이들의 작업을 지원하는
first-class user다.

사용자는 reference implementation의 internal class hierarchy나 qlibx private source를 모두 알 필요가 없어야
한다. 대신 데이터의
경제적 의미, availability, universe, benchmark, alpha hypothesis, risk constraint와 execution policy처럼 결과의
의미를 바꾸는 결정은 명시적으로 내려야 한다.

예를 들어 data registration을 돕는 agent는 `DATE`라는 이름만 보고 event time이나 `available_at`을 추측해서는
안 된다. 다음처럼 정보가 실제로 알려진 시점과 look-ahead 위험을 설명하고 user의 명시적 결정을 받아야 한다.

```text
Agent: DATE 컬럼의 값은 데이터가 나타내는 사건의 발생 시점인가요, 아니면 그 행 전체를 시장 참여자가
       실제로 알 수 있게 된 시점인가요? 예를 들어 DATE=2025-01-02인 종가 행 전체를 같은 날 장 시작 전에
       사용할 수 없다면, DATE를 그 시점의 투자 결정 input으로 사용하면 look-ahead가 발생합니다.

Agent: qlibx는 모든 관측치에 available_at을 정해야 합니다. available_at은 "이 값으로 투자 결정을 내려도
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

qlibx의 첫 번째 목적은 **signed cross-sectional alpha research**다. Signal이 양수와 음수를 갖고 alpha
weight가 long과 short intent를 표현하는 것은 정상적인 research behavior다. 실제 borrow 가능성이나 선택한
execution profile의 long-only 제약 때문에 research intent를 미리 long-only로 축소하지 않는다.

Alpha research는 하나의 고정된 선형 pipeline이 아니다. 대표적인 composition은 다음과 같다.

```text
registered PIT data ─┬─> Strategy 내부 signal/feature 계산 ─────────────┐
                    └─> Model/transform ─> stored research data ──────┤
                                                                       v
                                                            signed alpha weights
                                                                       |
existing member Strategies / stored alpha-weight results ─> Ensemble Strategy (optional)
                                                                       |
                                                                       v
                                                    portfolio construction profile
                    ┌──────────────────────────────────┼──────────────────────────────┐
                    v                                  v                              v
         academic/hypothetical              directly investable             benchmark-relative
         long-short portfolio               long-only or real-short          enhanced index (optional)
                    └──────────────────────────────────┼──────────────────────────────┘
                                                       v
                                  declared instrument / exchange / execution profile
                                                       v
                         closed-loop research or realistic execution backtest
```

1. **Alpha research loop.** Strategy는 registered PIT data를 직접 받아 내부에서 signal/feature와 ticker-level
   signed weights까지 계산할 수 있다. 이 단계에서 academic/hypothetical exchange profile을 사용한 long-short
   closed-loop backtest로 hypothesis를 평가할 수 있다.
2. **Reusable model output.** 별도 Model 또는 transform은 feature, firm characteristic, signal, factor return과
   같은 derived research data를 먼저 만들고 저장할 수 있다. Strategy는 필요한 semantic category를 구분해
   불러와 signed weights를 조립한다.
3. **Strategy composition.** Ensemble은 별도의 후처리 단계로 강제되는 것이 아니라 기존 member Strategy와
   그 compatible stored alpha-weight result를 입력으로 삼는 하나의 Strategy다. Member contribution, 같은 ticker의
   반대 intent netting, crossing과 dependency를 관측 가능하게 남긴다.
4. **Portfolio construction 선택.** Signed weights는 declared instrument와 exchange semantics에 맞는 portfolio로
   변환한다. Long-only enhanced index는 benchmark-relative construction profile 중 하나일 뿐이며 필수 단계가
   아니다. 실제 short accounting과 derivative portfolio는 future extension이다.
5. **Execution 선택.** Research-purpose hypothetical portfolio, directly investable portfolio와 enhanced-index
   portfolio 모두 compatible instrument, exchange, Executor와 fill convention을 선택해 closed-loop backtest할 수
   있다. Intended result와 committed execution result를 함께 관측하며 둘을 같은 state로 취급하지 않는다.

실제 운용 portfolio가 long-only여도 original signed alpha를 덮어쓰지 않는다. 실현되지 않은 short intent,
constraint clipping, residual과 physical mapping은 별도 evidence로 남긴다.

단순 long-only strategy와 market-timing policy도 구성할 수 있다. Cross-sectional stock-picking rebalance는
중요한 research profile이지만 package가 모든 user에게 강제하는 유일한 기본 흐름은 아니다.

### 2.2 Signal과 alpha weight의 의미는 구분하되 component 분리를 강제하지 않는다

Signal/feature와 portfolio weight는 서로 다른 semantic result다. Signal 생성 결과는 특정 alpha나 portfolio에
종속되지 않은 reusable research result로 저장할 수 있어야 하며, signed alpha weight는 decision time별
portfolio intent와 budget semantics를 별도로 가져야 한다.

이 구분이 반드시 별도 runtime component를 뜻하지는 않는다. Strategy 하나가 data를 읽고 내부 signal을 계산한
뒤 곧바로 weight를 만들 수 있다. 반대로 Model 또는 deterministic transform이 feature, firm characteristic,
signal, factor return 등을 먼저 저장하고 여러 Strategy가 재사용할 수도 있다. 재사용하거나 public boundary를
넘는 intermediate result만 그 정확한 semantic category로 materialize하면 되며, factor return을 signal로 또는
signal을 weight로 가장해서는 안 된다.

하나 이상의 stored signal과 다른 point-in-time data를 조합해 signed alpha weights를 만들 수 있어야 한다.
여러 alpha weights는 원래 producer를 다시 실행하지 않고 결합할 수 있어야 하며, signed weights를 executable
physical target으로 변환하는 과정은 별도로 관측할 수 있어야 한다.

이들은 semantic responsibility와 stored-result boundary다. 반드시 별도 class, process 또는 service여야 한다는
요구사항은 아니다. 필요한 것은 같은 signal을 여러 Strategy가 재사용하고, 같은 alpha weights를 여러 ensemble과
portfolio construction profile이 재사용하며, 각 단계의 성능과 dependency를 독립적으로 평가할 수 있다는
것이다.

> **Architecture/implementation candidate — non-normative**
>
> 한 가지 구현 후보는 재사용할 signal이 있는 경우 signal 생성과 alpha-weight 결정을 별도 component로 두고,
> 단일 Strategy가 내부 signal을 즉시 소비하는 경우에는 같은 component 안에서 두 semantic result를 구분하는
> 것이다. 설명용 이름으로 `SignalProducer`, `Strategy`, `EnsembleStrategy`, `PortfolioConstructor`를 사용할 수
> 있지만 이 이름이나 class boundary는 public API 요구사항이 아니다.

### 2.3 연구와 실행을 분리하되 lineage로 연결한다

Research intent와 executable portfolio는 다른 객체다. Research가 반드시 order로 변환될 필요는 없지만,
execution을 선택하면 original intent부터 actual fill까지 하나의 lineage로 연결되어야 한다.

```text
stored signed alpha weights
    ├─ analysis / comparison / ensemble / export
    └─ physical portfolio construction
          -> executable physical target
          -> target-to-order conversion
          -> selected qlibx Executor / Exchange
          -> actual Position and feedback
```

Weight까지만 materialize하는 run은 완전한 research run일 수 있다. 다만 그 weight의 portfolio return, NAV,
PnL 또는 turnover를 주장하는 결과는 반드시 선택한 Exchange와 Account를 거쳐 산출한다. Weight artifact
자체는 이러한 수치를 담지 않는다. 반대로 execution profile에서는 weight가 중간 artifact이고 Strategy의
executable output은 executor-neutral decision/order intent다.

### 2.4 Decision과 execution은 closed-loop runtime에서 분리된다

Strategy는 decision time에 허용된 관측과 actual state를 보고 executable intent를 만든다. Executor는 별도의
execution event에서 그 intent를 execution policy와 Exchange에 전달하고 결과를 ledger에 commit한다. 따라서
Strategy가 결정과 체결을 동시에 수행하거나 특정 가격으로 즉시 체결되었다고 가정해서는 안 된다.

Current-scope closed loop은 다음 네 책임으로 고정한다.

```text
Strategy -> ExecutionPreparation -> BaseExchange -> Account commit / execution feedback
```

`Strategy`는 immutable `DecisionIntent`를 만든다. `ExecutionPreparation`은 execution event의 current Account,
허용된 market data와 선택적 constraint policy를 사용해 executable request와 finding을 만든다. Construction,
adjustment와 validation 계산은 이 한 경계 안에서 고정된 순서로 호출하며, user-configurable global stage list나
범용 stage registry를 제품 계약으로 두지 않는다. Constraint를 선택하지 않은 profile은 관련 계산과 benchmark
requirement를 건너뛴다.

Exchange 교체 가능성은 current product goal이다. 공통 abstract `BaseExchange`는 immutable batch request를 받아
typed result를 반환하고 Account나 StrategyMemory를 직접 변경하지 않는 lifecycle만 정의한다. `KrxExchange`와
`AcademicExchange`는 이 base를 공유하지만 request/result와 경제적 semantics는 분리한다. Daily physical flow와
academic hypothetical flow도 합치지 않는다.

Simulation에서는 Executor schedule, concrete Exchange, FillConvention과 fee model을 교체할 수 있어야 한다. MVP는
지원되는 order의 전량 체결과 주식·ETF cash의 즉시 결제를 가정한다. Intraday liquidity, partial fill, pending/cancel
state와 external OMS 연결은 같은 decision contract 뒤에 추가할 future capability다.

Simulation의 simulated fill은 현실 세계의 체결이라는 뜻은 아니지만, 해당 simulation run 안에서는 ledger에
commit된 actual result다. Requested target, submitted order 또는 hypothetical post-trade state를 actual state처럼
사용하지 않는다.

Closed loop은 단순한 signal evaluation과 다르다.

- 다음 decision은 requested target이 아니라 해당 run의 committed actual holding을 본다.
- Stop-loss policy는 realized price와 position history를 사용할 수 있다.
- Rebalance state, cooldown, risk regime와 fitted belief를 bounded memory로 이어갈 수 있다.
- Blocked order와 transaction cost가 다음 decision에 영향을 줄 수 있다.

Execution result와 actual Position/Account는 다음 decision에 허용된 bounded input으로 전달한다. 생성된 signal,
weight, physical target, order와 execution result는 intermediate artifact와 lineage로 기록한다. Zero-dealt 또는
blocked result는 `Fill`로 가장하지 않고 execution evidence로 전달한다.

따라서 **order conversion은 alpha의 downstream responsibility**지만, **execution feedback은 다음 decision
context로 돌아오는 return edge**다.

Constraint adjustment와 pre-execution validation은 `ExecutionPreparation`의 downstream execution path에 속한다.
Current MVP validation은 advisory compliance finding이다. Breach를 기록하지만 그것만으로 execution을 차단하지
않으며, required input이 없거나 계산 자체가 불가능한 경우에는 Exchange 호출 전에 explicit failure로 끝난다.
Constraint monitoring은 actual account를 읽는 independent observer이며, finding이 명시적으로 다음
trigger/decision input으로 채택되기 전에는 strategy feedback authority가 아니다.

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

Downstream consumer는 producer가 qlibx built-in, local Python module 또는 외부 process인지 몰라도 schema,
semantics, compatibility와 lineage를 검사할 수 있어야 한다. 따라서 local serialized data를 읽을 때 단순
`dict`로 넘기는 데서 끝내지 않고 semantic role에 맞는 typed Python object를 생성해야 하며, object 생성 또는
deserialization 경계에서 schema, required field, type, version과 cross-field invariant를 validation해야 한다.
Invalid serialized state는 partially constructed object로 runtime에 들어가서는 안 된다.

> **Architecture/implementation candidate — non-normative**
>
> Portable schema와 Python object validation을 함께 제공하기 위해 Pydantic `BaseModel`과 strict/frozen config를
> 사용할 수 있다. Pydantic은 편리한 구현 후보이지 public product requirement는 아니다. 다른 구현도 object
> construction 시 같은 validation, error translation과 serialization compatibility를 제공하면 허용한다.

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

qlibx package distribution은 현재 package version과 일치하는 agent skill resource를 포함해야 한다. Project
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

> **Architecture/implementation candidate — non-normative**
>
> Package가 versioned skill resource를 포함하고 onboarding이 Codex, Claude Code 등 selected target에 thin
> routing instruction을 생성할 수 있다. Copy, link, generated managed block 중 어떤 방식으로 skill을
> 노출할지는 같은 onboarding behavior를 만족하는 범위에서 implementation에서 결정한다.

### 2.7 Built-in은 일관성을, local extension은 자율성을 제공한다

자주 쓰는 signal transform, exposure analysis, portfolio diagnostics, artifact validation과 reporting은
deterministic built-in으로 제공한다. Agent마다 같은 helper를 다르게 다시 만드는 일을 줄이고 공통 vocabulary를
제공하기 위해서다. Built-in은 계산 기능뿐 아니라 valid config, typed input/output, expected diagnostic과
failure behavior를 보여주는 executable example 역할도 한다. Agent는 이 예시와 extension contract를 함께 사용해
더 정확하게 compatible한 local extension을 작성할 수 있어야 한다.

사용자 고유의 signal model과 alpha logic은 project가 소유한다. **Project-local Strategy가 alpha logic의
primary extension point**다. 사용자는 installed qlibx 또는 `site-packages`를 수정하지 않고 compatible한 local
Python implementation을 작성·검증·등록할 수 있어야 한다. Model이나 deterministic materialization은 그
Strategy가 reusable intermediate data를 요구할 때 선택하는 optional component이며 direct Strategy의 선행 조건이
아니다.

qlibx는 각 extension point에 대해 다음을 제공한다.

- Public input/output contract
- Machine-readable requirement와 schema
- Built-in과 같은 contract를 따르는 minimal working template와 executable sample
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
-> minimal logical dataset registration
   |-> Strategy: signal + signed weights + research backtest
   |-> Model: feature / characteristic / factor / stored signal
                 -> Strategy: signed weights + research backtest
   |-> existing Strategy results -> Ensemble Strategy -> combined signed weights

any compatible signed weights
   |-> hypothetical long-short analysis (academic Exchange/Account 경유, §4.2 3층)
   |-> selected portfolio construction
          |-> long-only / enhanced index
          |-> real or hypothetical long-short allowed by instrument/exchange
          -> pluggable executor -> actual simulated feedback

stored results -> analysis / report / later Strategy reuse
actual account -> independent constraint monitoring
```

각 branch는 선택 가능한 use case다. Backtest는 research 단계와 construction 이후 모두 실행할 수 있고, enhanced
index는 그중 하나의 option일 뿐이다. Artifact가 이미 존재하고 identity와 compatibility가 맞으면 upstream
producer를 다시 실행하지 않는다.

### 3.2 Semantic roles and result categories

#### Materialized research data

반복 사용을 위해 저장한 derived research data다. Signal, label, factor return, factor exposure, covariance와
rolling risk estimate는 서로 다른 semantic category이며 각자 axis, unit, time semantics와 compatibility를
선언한다.

Factor return처럼 portfolio 수익률을 담은 materialized data는 그것을 산출한 execution run과 Account state를
lineage로 가져야 한다. 산출 경로 없이 계산한 return 시계열은 이 category로 등록하지 않는다(§4.6).

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
typed input으로 재사용할 수 있으며 run identity, 실제로 의존한 Account/Memory state identity, feedback cursor와
execution profile을 기록해야 한다. 다른 Strategy나 Ensemble이 이를 소비하는 것은 저장된 alpha intent를 입력으로
사용한다는 뜻이지, 그 producer가 consumer의 현재 state에서 재실행되었음을 뜻하지 않는다. 이후 executable target이나
order를 만들 때는 별도 downstream operation이 현재 committed Account와 현재 execution input을 사용한다.

#### Ensemble result

여러 stored alpha-weight results를 member lineage와 함께 소비해 만든 combined signed weights다. Member
weighting, netting, crossing, residual과 normalization을 명시한다.

#### Executable physical target

Signed alpha weights, benchmark, current physical holdings와 cost assumption을 반영한 실제 instrument/cash target이다.
MVP hard constraint는 no-short와 time-varying single-name cap뿐이다.

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
아니라 Exchange 호출 전 `OperationError`다. Blocking, severity와 override policy는 future work다.

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

Exact signed portfolio artifact를 explicit academic listing과 PIT reference price로 평가한 결과다. Fractional signed
quantity, hypothetical Fill, financing balance, NAV, gross/net exposure, PnL, turnover와 checkpoint를 포함하지만
actual Account 또는 broker-executable order가 아니다. Profile의 zero-friction과 full-fill 가정 및 미모델링된
borrow·margin·lifecycle 항목을 결과에 직렬화한다.

#### Prepared production decision — future work

향후 production integration에서 external OMS에 전달할 수 있는 immutable broker-neutral decision artifact 후보다.
MVP 계약과 acceptance 대상이 아니며, 생성만으로 authoritative strategy state를 advance하지 않는다는 경계만
future characterization으로 보존한다.

> **Architecture/implementation candidate — non-normative**
>
> Python 구현과 portable schema에서 위 역할을 구분하기 위한 후보 이름으로 `ResearchDataArtifact`,
> `SignalArtifact`, `AlphaWeightArtifact`, `PhysicalTargetArtifact`, `DecisionContext`와 `PreparedDecision`을
> 사용할 수 있다. 이 이름은 class, inheritance 또는 public import path를 확정하지 않는다.

### 3.3 Alpha output과 executable Strategy output의 구분

Alpha research의 observable output은 signed weights다. Closed-loop execution에 참여하는 Strategy의 observable
output은 executor-neutral decision/order intent다. 두 요구사항은 동시에 성립하며, alpha 연구 결과를 weight로
재사용하는 것과 qlibx feedback loop에서 executable intent를 출력하는 것은 충돌하지 않는다. Executor와
Exchange가 이후 execution event에서 intent를 처리하므로 Strategy output 자체는 fill이나 authoritative state가
아니다.

> **Architecture/implementation candidate — non-normative**
>
> 한 가지 구현 후보는 weight-producing callable과 event-driven Strategy callback을 분리하는 것이다. 설명용
> method shape는 `alpha_decision(view) -> signed weights`와
> `on_decision(event, view) -> decision intent`일 수 있다.

### 3.4 System mental model

qlibx는 data meaning과 availability를 강제하는 view, event/callback 순서, Strategy decision, execution,
Ledger commit, evidence와 monitoring으로 이어지는 runtime을 소유한다. Reference implementation에서 검증된
산술과 구조는 characterization 후 차용할 수 있지만 reference lifecycle이나 default가 qlibx public contract를
결정하지 않는다.

Data meaning, execution policy와 authority가 먼저 확정되고, runtime 결과가 portable evidence, dependency
lineage, reconciliation, analysis와 reporting으로 이어져야 한다. 이 responsibility ordering은 필요하지만
내부 plane, service 또는 package layout을 규정하지 않는다.

> **Architecture/implementation candidate — non-normative**
>
> ```text
> project semantics
>   data meaning / availability / requirements / config / provenance / constraint policy
>              |
>              v
> qlibx event-driven runtime
>   Clock / Event / View / Strategy / Executor / Exchange / Ledger
>              |
>              v
> qlibx evidence boundary
>   portable results / validation findings / monitoring / dependency graph / catalog / reports
> ```

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

##### UC-LOOKTHROUGH-001 — User Strategy의 명시적 ETF exposure 계산

Constituent A/B를 각각 50% 보유한 ETF와 A direct stock을 함께 보유해도 qlibx는 Instrument 또는 Account position만
보고 look-through를 자동 수행하지 않는다. User가 Strategy에 index/ETF constituent dataset binding과 actual account
state requirement를 명시하고 둘을 직접 consume한 경우에만 Strategy code가 constituent exposure를 계산한다.
그 Strategy는 direct stock과 ETF constituent exposure를 정확히 한 번 합산하고 physical cash/residual을 별도로
취급한다. 같은 ETF를 아무 constituent binding 없이 사용하는 다른 Strategy에서는 ETF가 opaque physical
Instrument로 남아야 한다.

##### UC-LOOKTHROUGH-002 — User Strategy의 PIT constituent consumption

ETF constituent 구성이 바뀌었지만 새 observation의 `available_at`이 decision time보다 늦으면 StrategyView는
그 observation을 노출하지 않는다. Look-through를 선택한 user Strategy는 자신이 구독한 binding에서 그 시각에
읽을 수 있는 구성종목만 consume하고, snapshot 선택·coverage·stale/revision 처리와 재정규화 여부를 Strategy의
경제적 규칙으로 명시한다. qlibx가 ETF Instrument를 근거로 constituent dataset을 자동 발견하거나 latest 구성을
대입하지 않는다.

##### UC-LOOKTHROUGH-003 — Actual holding을 읽는 user recomputation

ETF와 direct stock이 체결된 뒤 가격 drift 또는 다음 rebalance가 발생하면 look-through를 구현한 user Strategy는
다음 callback에서 requested target이 아니라 StrategyView가 허용한 marked actual AccountSnapshot을 직접 읽어
exposure를 다시 계산한다. qlibx는 계산값을 Account에 자동 주입하거나 다음 Strategy에 자동 feedback하지 않는다.
User가 결과를 artifact로 publish한다면 consumed constituent binding, AccountSnapshot과 target/actual 구분을
lineage로 보존하며 intended exposure를 actual compliance state로 가장하지 않는다.

##### UC-ACADEMIC-001 — Signed portfolio의 명시적 가상 거래

사용자가 `hypothetical_signed` portfolio artifact와 Stock, ETF, tracking-only Index 또는 synthetic-unit-price
Factor listing을 `academic.zero-friction.signed-fractional.v1` venue에 제출하면, decision session 다음 session
종가의 PIT price로 signed fractional target을 전량 가상 체결한다. 거래비용·tax·slippage·market impact·borrow
cost는 명시적인 0이고 turnover는 별도 기록한다. Listing, exact-time price, positive NAV 또는 supported profile이
없으면 해당 rebalance 전체를 state mutation 전에 거부한다. 결과와 checkpoint는 `hypothetical`로 표시하며
production Account, borrow/locate, collateral, margin 또는 executable real short capability로 주장하지 않는다.

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
변환은 qlibx가 아니라 security master와 ETL pipeline 책임이다. qlibx는 향후에도 그 원천 corporate action을
자체 해석하지 않고 이미 정규화된 instrument/reference data만 소비한다.

같은 frozen config와 data에서 event 순서와 결과가 재현되어야 한다는 요구는 모든 use case에 적용되는
cross-cutting invariant다. 3,000종목 실행에서 어떤 validation object를 언제 생성하는지는 architecture와
성능 검증이 결정하며 PRD use case가 특정 library나 hot-path representation을 강제하지 않는다.

## 4. Product invariants

### 4.1 Contract-owned, reference-informed

- qlibx가 product semantics, failure behavior, state authority와 artifact portability를 소유한다.
- Reference implementation의 계산 또는 구조는 source provenance와 version을 기록하고 characterization test로
  동등성이 확인된 범위에서 차용할 수 있다.
- Reference snapshot이나 차용한 산술을 갱신해도 qlibx public semantics가 암묵적으로 바뀌어서는 안 된다.
- External runtime lifecycle을 canonical execution path로 두거나 qlibx event/clock/view/ledger authority를
  우회하지 않는다.
- 같은 product contract를 만족하는 built-in과 local extension은 producer identity와 무관하게 같은 validation과
  artifact boundary를 통과한다.

### 4.2 Long-short research와 executable short를 구분한다

다음은 서로 다른 capability다.

1. Signal/prediction/label의 IC, RankIC와 rank-based diagnostic — portfolio를 구성하지 않는다
2. Execution을 거쳐 산출·저장된 return/NAV 시계열에 대한 분석 — attribution, correlation, factor
   regression처럼 기존 result를 읽으며 새 return을 만들지 않는다
3. Explicit academic listing, hypothetical Fill과 signed research state를 사용하는 가상 execution
4. Orders, production Position/Account와 actual fill을 통과하는 executable real short portfolio

첫 번째 층만 execution state를 경유하지 않는다. **새로운 portfolio return을 만드는 것은 세 번째 층부터이며,
두 번째 층은 그 이상의 층이 만든 result를 읽는 분석이다.** Quantile spread와 signed basket return처럼 basket
수익률을 뜻하는 지표는 첫 번째 층이 아니라 세 번째 층 경로로 산출한다. 세 번째 층은 production Account와
분리된 academic state에서만 성립한다.

네 번째 층은 resolved instrument semantics와 execution policy가 결정한 position direction(§7.12)에 따른다.
`hypothetical_short`의 음수 position은 research 관측을 위한 것이며 borrow, 담보, 차입 비용과 locate 가능성을
모델링하지 않는다. 이를 executable real short 또는 actual Account state로 표시하지 않는다.

### 4.3 Actual state가 authority다

- Requested target은 intention이며 realized holding이 아니다.
- Constraint adjustment와 pre-execution validation은 proposed 또는 hypothetical post-trade state를 평가한다.
- Current MVP constraint validation의 breach는 advisory evidence이며 actual state도 execution failure도 아니다.
- Simulation의 다음 decision은 qlibx Ledger에 commit된 actual Position, cash와 dealt quantity를 본다.
- Constraint monitoring은 actual account snapshot만 authoritative compliance state로 평가한다.
- MVP에서 지원되는 order는 선택된 Exchange rule에 따라 전량 체결되고 주식·ETF cash는 즉시 결제된다. Partial,
  pending, cancel과 reject lifecycle은 future work다.
- Intended ledger나 prior target을 actual state처럼 사용하지 않는다.
- Monitoring finding은 prior fill을 rollback하거나 account를 소급 변경하지 않는다.

### 4.4 Point-in-time과 data meaning을 강제한다

모든 data consumer는 선언된 `available_at <= evaluation_time`인 observation만 사용한다. Strategy와 alpha의
evaluation time은 decision time이고, `ExecutionPreparation`의 constraint adjustment/validation은 execution event
time, monitoring은 monitoring time이다. Actual account snapshot의 `as_of`도 evaluation time보다 늦을 수 없다.
qlibx가 보장하는 것은 선언된 availability의 준수다. Bundled agent skill은 source와 data category에 맞는
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
- Exchange와 Account를 거치지 않고 계산한 값을 portfolio return, NAV, PnL 또는 turnover로 보고

Constraint adjustment의 unresolved residual, advisory validation breach, actual-account breach와 evaluator runtime
failure는 다른 result/status다. Adjustment result가 존재한다는 이유로 compliant success를 선언하지 않고,
advisory breach를 execution failure로 바꾸거나 actual breach를 계산 failure로 숨기지도 않는다.

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
- Strategy, portfolio construction, Executor, Exchange와 Ledger 사이의 compatibility contract
- Order conversion semantics와 clipping/failure diagnostics
- Constraint declaration, best-effort adjustment, pre-execution validation과 finding contracts
- Signed alpha diagnostics와 long-only physical construction
- User Strategy가 명시적으로 구성하는 ETF/index look-through와 cash residual
- Instrument semantics, execution-policy resolution과 unsupported behavior의 명시적 실패
- Portable artifact envelope, dependency lineage, file-backed catalog와 reporting
- Trigger, finalization, checkpoint와 resume policy
- Dense actual-account constraint monitoring과 historical re-evaluation
- Agent-readable documentation, capability gap과 stage-based errors

### 5.2 qlibx execution runtime이 소유하는 것

qlibx-owned event-driven runtime은 다음 responsibility를 직접 소유한다.

- Clock progression, timer, event priority와 deterministic callback ordering
- Role-scoped view와 `available_at <= clock.now()` 강제
- Strategy callback, executable decision intent와 empty-order hold
- Decision과 분리된 Executor scheduling과 execution event
- Exchange의 requested/dealt quantity, tradability, clipping, fill과 transaction-cost 계산
- Ledger의 Position, cash, Account와 lifecycle cash-flow commit
- Bar-end mark-to-market, actual-state feedback와 independent monitoring event
- 같은 frozen input에서 재현 가능한 diagnostics, artifacts와 checkpoint

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

qlibx는 broker SDK wrapper나 always-on OMS가 아니다.

### 5.5 Reference implementation 사용 경계

Qlib, vn.py와 NautilusTrader는 §0.2에 선언된 산술·구조의 비교 및 차용 source다. 이들은 qlibx runtime
dependency, state authority, default project catalog 또는 workflow coordinator가 아니다. Reference-specific
object, pickle, recorder나 process-global provider는 portable qlibx artifact와 clock-bound access를 대체하지
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
- Exact signed portfolio artifact를 사용하는 zero-friction fractional AcademicExchange (§7.12)
- ETF의 physical/opaque 처리와 user Strategy가 명시적으로 PIT constituent data를 구독·소비해 계산하는 look-through
- Historical backtest와 portable research catalog
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

§3.5의 `UC-COST-001`~`UC-SCALE-001`, `UC-LOOKTHROUGH-001`~`003`과 `UC-ACADEMIC-001`은 현재 scope의
characterization과 acceptance 대상이다. `UC-FUTURE-001`, `UC-PERP-001`, `UC-CASHFLOW-001`과
`UC-SETTLEMENT-001`은 architecture 확장 가능성을 검토하기 위한 future characterization이며 현재 지원을
의미하지 않는다.

## 6. User, agent and config-driven workflow

### 6.1 Initial setup

사용자는 package를 설치한 뒤 project root에서 qlibx project를 초기화한다. Initial setup은 다음을 만든다.

- Project-owned config와 schema version
- Data, artifact, catalog와 extension locations
- Version-matched bundled agent skill을 selected coding-agent target에서 사용할 수 있게 하는 onboarding result
- Installed documentation과 capability inventory
- qlibx runtime, artifact schema와 extension-contract version information

설치 후 정상 사용에 qlibx source checkout이나 reference implementation internal 탐색을 요구하지 않는다. Sample data와 sample
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

> **확정된 최종 rename — 아직 적용하지 않는다.** 현재 package, import, CLI와 generated skill path의
> normative name은 `qlibx`다. 최종 migration 단계에서만 `vqapr`(vibe quant alpha portfolio / asset pricing
> research)로 한 번에 변경한다. 그때 위 세 path, import/CLI, artifact schema identity, installed docs와
> migration guide를 같은 change set에서 갱신한다. 그 전까지 위 `qlibx` path가 유효한 normative contract다.

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

### 6.7 Local component configuration

Project-local component는 explicit class/module reference와 validated parameter로 구성할 수 있다. Config에서
component를 import하고 object를 생성하는 것만으로 compatibility가 증명되지는 않는다. qlibx는 다음을
deterministic하게 validation한다.

- Allowed extension boundary
- Capability and type validation
- Semantic input/output binding
- Version and source fingerprint
- Safe error classification
- Portable resolved config
- Construction-time object validation과 bounded import/initialization error

### 6.8 Public workflow orchestration

Public workflow는 다음 lifecycle을 package-owned contract로 실행한다.

```text
resolve frozen invocation
-> instantiate and validate datasets/components
-> optionally materialize or load model state only when the selected component requests it
-> run Strategy / execution / analysis stages selected by the user
-> publish typed portable artifacts and terminal status
```

External experiment frontend나 model trainer는 optional adapter 뒤에서 호출할 수 있다. 그러나 그것이 data
registration interview, artifact DAG, catalog publication, signed accounting, physical construction 또는 closed-loop
simulation execution을 대신하지 않는다. External run ID, pickle이나 tracking record는
portable qlibx artifact에 lineage로 연결할 수 있지만 유일한 canonical result가 아니다.

### 6.9 Workflow completion

각 stage는 다음 중 하나로 끝난다.

- `complete`: required outputs와 validation이 모두 존재
- `incomplete`: 일부 output은 있으나 requirement 미충족
- `failed`: deterministic contract 또는 runtime failure
- `unsupported`: 선택한 component/profile이 capability를 제공하지 않음

Required output에 대한 warning-and-skip은 `complete`가 될 수 없다.

## 7. Project, data and capability contracts

이 절의 목적은 처음부터 완전한 dataset·project schema를 요구하는 것이 아니다. qlibx는 현재 작업에 꼭 필요한
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

Field 이름은 강제하지 않는다. 예를 들어 `ticker`, `symbol`, `종목코드` 중 무엇이 instrument인지 user가 binding할
수 있다. 기본 instrument-time panel에서는 `(available_at, instrument)`가 null 없이 해석 가능하고 유일한지
검사한다. 같은 instrument와 time에 여러 행이 필요한 event/long-form dataset은 event ID나 sequence 같은 추가 key
axis를 선언하거나 별도 logical dataset으로 등록한다.

Registration result는 선택된 binding, physical source fingerprint와 validation evidence를 보존한다. Event time,
unit, currency, timezone, universe coverage와 missingness 같은 metadata는 등록 시 알려져 있으면 기록하지만, 아직
선택하지 않은 workflow가 필요로 한다는 이유만으로 최초 등록을 막지 않는다.

`DATE`를 `available_at`으로 바로 binding할 수 있는 것은 user가 그 값이 실제 공개 시각이라고 확인한 경우뿐이다.
별도 availability field가 없다면 bundled agent skill은 data category와 source 관행에 근거한 지연 규칙 후보와
각 후보의 look-ahead 위험을 설명한다. Package가 임의의 지연을 선택하지 않으며, user가 선택한 rule만
결정적으로 validation하고 적용한다.

#### UC-DATA-001 — 최소 등록과 field-name 자율성

`DATE`, `CODE`, `VALUE` 컬럼이 있는 file에서 user는 `CODE`를 instrument, 확인된 `DATE`를 `available_at`으로
binding한다. Package는 이름을 바꾸라고 요구하지 않고 `(DATE, CODE)`의 parseability, null과 uniqueness를 검사해
logical dataset을 등록한다. Currency나 universe metadata가 없다는 이유만으로 이 단계가 실패해서는 안 된다.

### 7.2.1 Price axis and derived unit price

Execution을 선택한 workflow는 예외 없이 가격 축을 요구한다. qlibx에는 return-native 체결 경로가 없으며,
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
execution preparation 시점의 time-varying benchmark-weight binding을 추가로 요구한다. 해당 workflow를 처음
호출할 때 package는 requirement가 충족되지 않았음을 보고하고 Exchange request와 account mutation을 만들지 않는다.
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

Dataset view의 historical read는 operation이 `ComponentRequirement`에 선언한 exact lookback을 강제한다. Current
product contract는 다음 두 종류뿐이다.

- `rows`: PIT gate를 통과한 행을 registered logical key로 결정적으로 정렬한 뒤 instrument별 최근 N행까지 반환한다.
- `calendar`: user가 명시한 timezone의 evaluation date에서 years/months/days를 달력 산술로 이동한 date의 00:00부터
  evaluation time까지 `available_at`이 포함되는 행을 반환한다. 거래일 수를 세는 `sessions` semantics가 아니다.

두 종류 모두 `available_at <= evaluation_time` 상한을 바꾸지 않고 Store query에 직접 반영한다. 전체 history를
먼저 읽은 뒤 Strategy code에서 자르는 경로를 bounded access로 간주하지 않는다. `rows`보다 적은 행만 존재하면
있는 만큼 반환하고 requested/actual count를 access evidence에 기록한다. Dataset-wide `available_at_min`만으로
instrument별 coverage를 추정하거나, row가 전혀 없는 instrument를 declared universe 없이 존재한다고 추측하지 않는다.
계산에 필요한 최소 관측치와 ragged-panel 처리 방식은 해당 Strategy의 경제적 규칙이다.

`CalendarLookback`은 years/months/days 중 적어도 하나가 양수여야 하고 timezone과 month-end clamp policy를 frozen
config에 보존한다. 동일 `available_at`의 순서는 registered logical key로 결정해 같은 input에서 같은 row set을 만든다.

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

Downstream consumer는 producer가 qlibx built-in, Qlib component, local Python module 또는 external process인지 몰라도
serialized result를 적합한 Python object로 읽고 schema, semantics, compatibility와 lineage를 검사할 수 있어야 한다.
Object construction 시 validation하는 typed model이 유용하며 Pydantic은 구현 후보지만 제품 계약으로 강제하지 않는다.

### 7.10 Frozen invocation

한 operation이 시작되면 그 invocation이 소비하는 config, binding, data cutoff와 component identity를 동결한다.
동시 수정은 다음 invocation에만 반영한다. Failure evidence도 같은 frozen input identity를 가리켜야 안전한 retry와
비교가 가능하다.

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

## 8. Signal and model research

Signal research에는 하나의 의무적인 pipeline이 없다. Strategy가 raw data에서 signal과 signed weight를 한 번에
만들 수도 있고, model이 reusable intermediate result를 먼저 materialize한 뒤 Strategy가 이를 소비할 수도 있다.
두 방식은 같은 artifact validation과 PIT rule을 따르지만 producer의 internal class hierarchy를 공유할 필요는 없다.

### 8.1 Direct Strategy research

Strategy는 registered data를 받아 feature transform, signal과 signed weight를 내부에서 조립하고 hypothetical
long-short backtest까지 수행할 수 있다. 중간 signal 저장이 연구 목적에 필요하지 않다면 별도 model stage를
강제하지 않는다.

#### UC-SIGNAL-001 — Strategy 내부의 signal과 weight 조립

User는 price reversal Strategy를 선택한다. Strategy는 point-in-time price를 읽어 reversal score와 signed weight를
만들고 academic exchange profile에서 long-short result를 평가한다. Workflow는 stored signal이나 enhanced-index
portfolio를 만들지 않아도 완결된다.

### 8.2 Reusable model output

Model은 prediction뿐 아니라 firm characteristic, feature, factor exposure, factor return 또는 risk estimate를 만들 수
있다. 결과는 경제적 의미와 axis가 맞는 typed artifact로 저장되며, Strategy는 compatible result를 불러 signed
weight를 조립한다. 서로 의미가 다른 결과를 모두 `signal`이라는 이름으로 뭉개지 않는다.

#### UC-SIGNAL-002 — Stored signal을 여러 Strategy에서 재사용

한 model이 monthly value characteristic을 materialize한다. Long-short research Strategy와 long-only construction
Strategy가 같은 result를 소비하되 각자 다른 weighting rule과 execution profile을 사용한다. Model producer는 다시
실행하지 않아도 되고, 두 Strategy result는 자신의 input lineage와 weighting semantics를 따로 보존한다.

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
package가 이를 resolve한다. 실제로 소비한 artifact만 dependency edge가 되며 source result가 의존했던 Account/Memory
state identity와 feedback cursor는 새 result의 lineage에서도 보존된다.

이 재사용은 source result를 consumer의 현재 Account에서 다시 계산했다는 뜻이 아니다. Budget, schema 또는 semantics가
consumer 요구와 맞지 않으면 계산 전에 compatibility error로 실패한다. Compatible한 frozen alpha를 이후 physical
target이나 order로 변환할 때는 그 downstream operation이 현재 committed Account와 현재 execution input을 사용한다.

#### UC-ALPHA-PATH-001 — Path-dependent weight의 producer-independent 재사용

Turnover-aware Strategy가 account A의 actual holding과 Memory cursor를 소비해 path-dependent signed-weight result를
만든다. 이후 Ensemble Strategy가 이 frozen result와 다른 member result를 입력으로 조합한다. Source producer는 다시
실행되지 않고 parent result도 변경되지 않으며, Ensemble result는 consumed artifact와 source Account/Memory state
identity 및 cursor lineage를 보존한다. Ensemble weight를 account B의 executable target으로 변환하면 account B의 현재
committed holding과 현재 execution input을 사용하지만, source member가 account B에서 재계산되었다고 표시하지 않는다.

### 9.5 Research feedback와 execution feedback

Hypothetical research backtest와 MVP simulation은 별도 executor가 만든 committed fill/account result만 다음
decision의 authoritative state로 사용한다. Strategy가 naive daily close 체결을 직접 가정하지 않는다.

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

Calendar, data arrival, fill feedback 또는 user event가 decision을 trigger할 수 있다. Run 종료 시 result와 failure
evidence를 확정해야 하지만, 특정 event class나 callback method는 PRD가 정하지 않는다.

Current public daily profile에서는 invocation의 frozen `DailySimulationSpec.decision_times`가 decision cadence를
소유한다. Strategy가 schedule을 등록하거나 Clock을 직접 조작하지 않는다. Entry/exit 조건은 같은 decision callback의
`HOLD`/`TARGET`으로 표현한다. 새로운 trigger 종류가 실제 current-scope capability로 승인될 때 scheduler contract를
확장하며, 미리 generic TriggerPolicy 계층을 요구하지 않는다.

### 9.9 Parent/child research

Child research는 parent run의 frozen input과 artifact를 재사용해 대안을 평가하되 parent state를 바꾸지 않는다.

#### UC-ALPHA-CHILD-001 — 체결 규칙만 바꾼 child

Parent의 signed weight를 고정하고 next-close와 next-open 같은 두 full-fill convention을 child에서 비교한다. Model과
Strategy를 다시 실행하지 않으며 각 child는 execution assumption과 actual simulated fills를 별도 lineage로 보존한다.

### 9.10 Checkpoint와 resume

중단된 run은 committed artifact와 feedback cursor에서 재개할 수 있어야 한다. Resume은 이미 commit된 decision이나
fill을 중복 적용하지 않고, input/config identity가 달라졌다면 새 run 또는 explicit branch를 요구한다.

Default local daily flow는 callback별 Account/Memory CAS 결과와 scheduler position을 versioned recovery point로
먼저 durable publication한 뒤 같은 candidate를 live authority에 적용한다. Process가 그 사이 어느 지점에서 종료돼도
resume은 recovery point에서 Account journal과 Strategy Memory를 복원하고, 누락된 typed evidence만 idempotent하게
발행한 뒤 저장된 event position보다 뒤의 callback만 실행한다.

Resume identity는 run request, config, execution profile, logical dataset registration과 Strategy를 포함한다. 하나라도
달라지면 `RESUME_BRANCH_REQUIRED`로 mutation 전에 실패하며, changed identity는 새 run 또는 명시적 parent-checkpoint
branch로만 진행한다. 이 계약은 local daily simulation 범위이며 external OMS와 distributed transaction을 뜻하지 않는다.

### 9.11 Adaptive alpha research and belief update

Adaptive Strategy는 realized result나 new observation으로 belief, parameter 또는 member weight를 갱신할 수 있다.
특정 Bayesian class hierarchy를 요구하지 않고, update 전후의 state와 사용한 evidence를 비교 가능하게 보존한다.

#### UC-ALPHA-ADAPTIVE-001 — Fill 이후 ensemble belief 갱신

Ensemble Strategy가 member별 realized outcome을 받은 뒤 다음 decision의 member weight를 바꾼다. Result는 어떤
feedback까지 반영했는지 보여준다. 같은 update를 feedback 없이 재생하거나 미래 fill을 앞당겨 사용해서는 안 된다.

## 10. Ensemble and portfolio construction

Ensemble과 portfolio construction은 alpha research 이후 반드시 거쳐야 하는 고정 단계가 아니다. 둘 다 기존 result를
소비해 새로운 intent를 만드는 선택 가능한 Strategy/workflow다. Enhanced index는 qlibx가 잘 지원해야 할 주요
flow지만 package 전체의 canonical flow는 아니다.

### 10.1 Ensemble is a Strategy

Ensemble Strategy는 기존 Strategy 또는 signed alpha-weight result를 member로 불러와 combine, netting과 crossing을
수행한다. Member producer가 direct Strategy인지 stored model output을 소비했는지는 ensemble의 public contract가 아니다.

#### UC-ENSEMBLE-001 — 기존 Strategy result의 조합

Value와 momentum Strategy의 signed weights를 저장한 뒤 ensemble이 두 result를 읽어 ticker-level netting을 한다.
한 member의 long과 다른 member의 short가 상쇄된 수량, 최종 signed weight와 member lineage가 확인 가능해야 한다.

### 10.2 Optional construction modes

Signed weight는 그대로 hypothetical long-short portfolio로 평가하거나 long-only physical portfolio 또는
benchmark-relative enhanced index로 변환할 수 있다. Derivative portfolio는 future work다. Enhanced-index 변환 뒤에도
같은 execution boundary를 통해 backtest할 수 있다.

#### UC-PORTFOLIO-001 — 같은 alpha의 서로 다른 portfolio use

같은 signed alpha result를 hypothetical long-short analysis와 equity long-only enhanced-index construction에
사용한다. 두 workflow는 서로 다른 investability, direction, budget과 cost requirement를 발견하고 각자 결과를
만든다. Alpha result 자체를 어느 한 portfolio 의미로 다시 쓰지 않는다.

### 10.3 Constraint adjustment and validation

Constraint adjustment는 proposed intent를 가능한 범위에서 수정하고, validation은 최종 candidate가 limit을 만족하는지
독립적으로 판정한다. Adjustment result가 있다는 사실만으로 compliance를 보증하지 않는다. Current MVP validation은
advisory이므로 `passed=false` finding도 기록한 뒤 같은 candidate의 execution을 계속한다. Missing benchmark처럼
평가 자체가 불가능한 경우에만 Exchange 호출 전에 operation이 실패한다. 이 workflow를 사용하지 않는 research에는
constraint declaration을 요구하지 않는다.

#### UC-CONSTRAINT-ADJUST-001 — 조정 후에도 남은 single-name breach

Single-name cap을 맞추려 target을 줄였지만 lot rounding 때문에 작은 breach가 남는다. Result는 original/adjusted
intent와 residual을 보여주고 validation은 `passed=false`와 exact excess를 별도 finding으로 남긴다. Current MVP는
이를 성공한 adjustment나 compliant result로 위장하지 않지만 같은 candidate의 execution을 계속한다.

### 10.4 Budget and residual evidence

Portfolio result는 requested budget, realized gross/net exposure, cash/residual과 중요한 clipping reason을 보여준다.
세부 optimizer variable, solver class와 internal batch layout은 architecture와 implementation이 결정한다.

### 10.5 ETF look-through는 user-authored Strategy behavior다

ETF look-through는 Instrument capability나 Account의 자동 behavior가 아니다. Exchange와 Account는 ETF를 항상
독립 physical Instrument로 체결·보유한다. ETF registration, 보유 수량 존재 또는 constituent dataset 등록만으로
look-through가 켜지지 않는다. User가 특정 Strategy callback에 index/ETF constituent data binding과 actual account
state requirement를 선언하고 그 Strategy code가 둘을 직접 consume해 계산할 때만 look-through가 존재한다.
아무 계산도 선언하지 않은 Strategy에서 ETF는 opaque이며, Instrument에 `opaque/transparent` mode를 두지 않는다.

구성종목 데이터는 다른 research data와 같은 user-provided versioned PIT dataset이다. User는 logical dataset을
등록하고 Strategy requirement로 구독한 뒤 clock-bound StrategyView에서 consume한다. Dataset observation은 source
identity, `available_at`, instrument/constituent identity와 weight unit을 표현할 수 있어야 한다. qlibx는 이 데이터를
ETF Instrument와 자동 연결하거나 `LookthroughSnapshot`이라는 특별한 package-owned
schema로 강제하지 않는다. 구체 schema, mapping, coverage와 normalization의 경제적 의미는 user Strategy가 소유한다.
여기서 구독은 runtime MessageBus가 아니라 Strategy가 logical dataset binding을 requirement로 선언한다는 뜻이다.

User Strategy가 decision time $t$에 AccountSnapshot에서 만든 physical weight를 $p_t$, 자신이 consume한 구성종목
데이터로 만든 mapping을 $L_t$라고 하면 constituent exposure 계산은 예를 들어 다음 관계를 사용할 수 있다.

$$
x_t = L_t p_t
$$

이 식은 qlibx의 내장 ETF semantics가 아니라 Strategy가 선택한 계산이다. Strategy가 이 방식을 사용한다면 direct
stock column과 ETF constituent column을 직접 구성하고 한 result에서 정확히 한 번 적용해야 한다. 이미 mapped된
값을 다시 mapping하거나 ETF weight를 benchmark에 중복 가산하는 오류도 해당 Strategy의 validation 책임이다.

qlibx는 mapping을 만들지 않으므로 누락분을 자동 재정규화하거나 complete/partial/opaque policy를 대신 선택하지
않는다. User Strategy가 complete coverage를 요구하면 자신의 calculation/validation에서 실패시키고, partial을
허용하면 mapped/unmapped exposure와 limitation을 자신이 만든 result에 남긴다. Cash와 lot/cost clipping residual을
constituent exposure로 볼지도 Strategy의 경제적 정의지만, Account는 이를 physical cash로만 제공한다.

Look-through를 이용한 construction이 필요하면 user Strategy가 desired exposure, benchmark, constituent binding과
marked actual AccountSnapshot을 소비해 physical target이나 constraint input을
만든다. Built-in construction은 ETF를 발견해 mapping을 주입하지 않고 전달받은 명시적 input만 처리한다. Expected
cost는 target 선택을 위한 assumption일 뿐 actual transaction cost가 아니며, 최종 order clipping과 Fill 비용은
§11의 Exchange exact rule이 계산한다.

User Strategy가 target/actual look-through를 publish한다면 둘은 다른 result여야 한다. Target은 construction intent를
설명하고 actual은 committed Fill 이후 다음 callback에서 읽은 marked AccountSnapshot으로 다시 계산한다. qlibx는
그 result를 자동 생성·소비하지 않지만 generic artifact lineage는 실제로 읽힌 constituent dataset binding,
AccountSnapshot과 cutoff를 보존한다.

## 11. Event-driven execution and signed compatibility

Strategy는 executor-neutral decision intent를 만들고, 별도 executor가 선택한 market/fill model로 처리한다.
MVP simulation은 지원되는 order를 선택한 가격에 전량 체결하고 주식·ETF cash를 즉시 결제한다. Intraday order
book/data, partial fill과 production adapter는 이 경계를 재사용할 future work다.

### 11.1 Closed-loop authority

Simulation의 authoritative state는 simulated executor와 Ledger가 commit한 fill, cost, cash와 position이다.
Requested order나 target은 realized state가 아니며, 다음 decision에는 committed simulation result만 feedback한다.

#### UC-EXEC-001 — Decision과 MVP simulation execution의 분리

Signed intent는 Strategy callback에서 Fill을 직접 만들지 않는다. 별도 MVP executor가 next daily close 같은
PIT-safe convention에서 지원되는 order를 전량 체결하고 cost와 즉시 결제 cash를 Account에 commit한다.

### 11.2 Execution profile defines realism

MVP의 academic/hypothetical과 daily-bar simulation profile은 fill timing, tradability, short와 cost capability를
각자 선언한다. Package 이름만 보고 현실성을 과장하지 않으며 result에는 full-fill과 instant-settlement 가정을
포함한 선택 profile의 limitation을 표시한다. Intraday simulation과 external OMS profile은 future work다.

#### BaseExchange와 분리된 concrete semantics

Exchange 교체 경계는 generic abstract `BaseExchange[RequestT, ResultT]`다. Base는 stable `exchange_id`, immutable
batch request, typed result와 Account/Memory non-mutation만 강제한다. `KrxExchange`는 physical order, cash, holding,
lot와 fee를 계산하고, `AcademicExchange`는 signed/fractional target을 zero-friction hypothetical state로 계산한다.
두 subclass는 request/result type과 ledger semantics를 공유하지 않으며, daily와 academic public flow도 분리한다.
Plugin registry와 arbitrary class-path loading은 current requirement가 아니다.

#### UC-EXEC-002 — Daily close engine의 명시적 한계

Daily close executor는 결정 당일 종가를 무조건 알고 체결한 것처럼 처리하지 않는다. Decision cutoff와 선택한 fill
timing이 PIT-safe인지 validation하고, volume impact, partial fill과 실제 settlement cycle을 모델링하지 않았다는
limitation을 남긴다.

### 11.3 Order conversion and evidence

실제 주문을 만드는 workflow는 target, actual holding, cash, price, lot와 tradability를 사용한다. 필요한 binding이
없으면 §7의 progressive error로 멈춘다. Rounding, clipping, skip, rejection과 requested/dealt quantity는 결과에서
확인 가능해야 한다.

### 11.4 Product and direction compatibility

Long-only equity, hypothetical short, borrow-aware short, future와 perpetual은 다른 execution capability다. 선택한
instrument/exchange profile이 허용하지 않는 방향이나 lifecycle을 조용히 근사하지 않는다. 거래비용, cash clipping과
lifecycle behavior의 기준 사례는 §3.5 `UC-COST-*`, `UC-CLOSED-LOOP-001`과 future characterization을 따른다.

### 11.5 Monitoring without a decision

Constraint monitoring은 Strategy decision cadence와 독립적으로 actual account를 관찰한다. 현재 public contract는
`QlibxProject.monitor_constraints()`에 committed checkpoint와 frozen `evaluation_time`을 명시해 호출하는 standalone
operation이다. 새 decision이나 order가 없는 날에도 caller 또는 선택적 scheduler가 이 operation을 호출해 finding을
만들 수 있다. `run_daily()`가 이를 자동 실행하지 않으며 finding은 계좌를 수정하거나 과거 fill을 rollback하지 않는다.

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
validation한다. Pydantic은 편리한 구현 후보지만 강제하지 않는다. Unknown type/version, invalid key 또는 incompatible
semantics를 raw dictionary로 통과시키지 않는다.

#### UC-ARTIFACT-001 — External producer round-trip

외부 process가 documented artifact schema로 signal을 저장한다. qlibx는 이를 typed object로 읽고 local Strategy에
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

Project는 local file, object store 또는 external experiment tracker를 선택할 수 있다. Backend가 달라도 artifact identity,
validation과 observable publication outcome은 같아야 한다. Locking, database schema와 directory layout은 architecture가
결정한다.

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

#### UC-EXTENSION-002 — Project-local Strategy의 검증과 exact 등록 실행

Fresh installed project에서 user가 curated top-level `qlibx` contract만 import하는 local Strategy module을 작성한다.
Strategy는 fixed module symbol, dataset/artifact requirement와 typed output을 선언한다. Package는 configured extension
root 안의 source를 hash하고 두 fresh instance가 같은 requirement, output과 access evidence를 만드는지 검증한 뒤에만
registration artifact를 publish한다. Research 또는 daily 실행은 caller가 지정한 exact registration artifact ID의
source/schema를 다시 확인하고, 실제로 소비한 typed artifact와 registration을 lineage로 남긴다. Source가 바뀌면 기존
registration 실행은 compute 전에 실패하며 latest/first-compatible registration을 자동 선택하지 않는다. Local Python
module은 trusted project code이며 이 validation은 security sandbox나 dependency installer가 아니다.

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
핵심 후보는 broker-neutral intent와 authoritative outcome의 분리다. qlibx가 prepared decision을 외부 OMS에
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

OMS가 주문을 reject한다. Rejection evidence는 보존하지만 qlibx는 intended position을 actual로 commit하지 않는다.
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
- `UC-DATA-001`처럼 field 이름을 강제하지 않고 selected instrument/availability binding과 logical key를 validation한다.
- Availability가 불명확하면 `UC-AGENT-001`처럼 agent가 look-ahead와 delay-rule 후보를 설명하고 user가 선택한다.
- 아직 사용하지 않는 metadata나 optional workflow requirement가 최초 registration을 막지 않는다.
- 실제 current operation의 requirement gap은 `UC-DATA-002`, `UC-ERROR-001`처럼 package error → agent 제안 →
  user 결정 → package validation → safe retry로 이어진다.
- Frozen invocation과 `available_at <= evaluation_time`을 위반하는 data access는 거부된다.
- `UC-PIT-001`의 public direct materialization은 forward-return label 계산 전에 `label.horizon_end`를 resolve한다.
  누락 시 producer를 호출하거나 reusable result, Account, Memory, dataset registration을 변경하지 않고 failure
  evidence만 남긴다. 명시적 immutable horizon registration 뒤의 새 invocation은 이전 failure를 lineage로 연결하고
  frozen evaluation time까지 이용 가능한 label만 `forward_return_label_result:v1`로 발행한다.

### 15.2 Research composition

- `UC-SIGNAL-001`의 direct Strategy와 `UC-SIGNAL-002`의 stored model output 경로가 모두 동작한다.
- Signed weight는 budget semantics와 actual dependency를 보존하고 producer를 다시 실행하지 않고 재사용할 수 있다.
- `UC-ALPHA-BUDGET-001`에서 flexible residual을 fixed budget으로 자동 확대하지 않는다.
- `UC-ALPHA-PATH-001`에서 path-dependent result를 producer rerun 없이 frozen member input으로 소비하고,
  source Account/Memory state identity와 cursor를 새 result lineage에 보존하며 current-state recomputation으로
  표시하지 않는다.
- `UC-ENSEMBLE-001`에서 기존 Strategy result를 member로 조합하고 ticker-level netting과 lineage를 확인할 수 있다.
- `UC-PORTFOLIO-001`처럼 같은 alpha를 서로 다른 valid instrument/exchange construction에 사용할 수 있다.
- `UC-ALPHA-CHILD-001`은 같은 exact `decision_intent:v1` parent를 Strategy/Model 재실행 없이 next-close와
  next-open child에서 실행한다. 각 child는 별도 Account, schedule/profile/convention, PIT price binding과 Fill
  lineage를 가지며 parent artifact는 불변이다. Adaptive scenario는 `UC-ALPHA-ADAPTIVE-001`의 state/evidence를
  별도로 만족한다.

### 15.3 Construction, execution and monitoring

- Constraint가 없는 research는 `UC-CONSTRAINT-001`처럼 실행되고, constraint workflow는 필요한 data를 호출 시점에
  발견한다.
- MVP constraint는 no-short와 `single-name weight <= max(10%, index constituent weight)`뿐이며 benchmark weight는
  execution preparation time에 available한 time-varying data를 사용한다.
- Adjustment와 advisory validation은 `UC-CONSTRAINT-ADJUST-001`처럼 single-name residual과 compliance finding을 구분하며, breach만으로 execution을 차단하지 않는다.
- `UC-EXEC-001`에서 Strategy decision, execution-time `ExecutionPreparation`, selected `BaseExchange`와 full-fill·instant-settlement MVP simulation을 분리하고 committed
  result만 다음 decision에 feedback한다.
- `UC-EXEC-002`는 fill timing과 model limitation을 명시하며 look-ahead를 허용하지 않는다.
- §3.5의 `UC-COST-001`~`UC-COST-004`, `UC-CLOSED-LOOP-001`, `UC-SCALE-001`과
  `UC-LOOKTHROUGH-001`~`003` current-scope outcome을 만족한다.
- `UC-EXEC-003`처럼 Strategy decision이 없는 clock에도 actual-account monitoring finding을 만든다.
- Unsupported short, lifecycle 또는 cost policy를 다른 profile의 default로 조용히 대체하지 않는다.
- Partial fill, pending/cancel, 실제 주식·ETF settlement cycle과 production OMS behavior를 current support로 표시하지 않는다.
- Portfolio return, NAV, PnL과 turnover는 Exchange/Account 경로에서만 산출되며 signal 분석 result는 이
  수치를 포함하지 않는다(§4.2, §4.6).

### 15.4 Artifacts, reports and extensions

- `UC-ARTIFACT-001`처럼 producer의 private class 없이 serialized result를 typed Python object로 읽고 validation한다.
- `UC-ARTIFACT-002`의 invalid payload와 partial publication을 reusable success로 노출하지 않는다.
- Failure와 retry history는 `UC-RESEARCH-001`처럼 queryable evidence로 남는다.
- `UC-REPORT-001`, `UC-MONITOR-001`에서 stored result를 재실행 없이 report하고 actual과 intended state를 구분한다.
- `UC-EXTENSION-001`에서 agent는 built-in 예시로 local transform을 만들 수 있고 package가 compatibility를
  deterministic하게 판정한다.
- `UC-EXTENSION-002`에서 installed project의 local Strategy를 public contract로 검증·등록하고 exact registration
  ID로 research/daily 실행하며, source drift와 implicit latest selection을 compute 전에 거부한다.

### 15.5 Current requirement/design readiness gaps

다음 항목은 out of scope가 아니라 **현재 product requirement의 미완성 지점**이다. Architecture 또는 product
decision이 closure evidence를 정의하고 acceptance fixture가 통과하기 전에는 관련 capability를 current support로
표시하지 않는다. 이 표는 필요한 observable closure를 규정한다. `BaseExchange` hierarchy는 user가 명시적으로
선택한 product contract이므로 일반적인 internal class-name 비고정 원칙의 예외다.

| gap ID | 현재 부족한 점 | closure outcome |
|---|---|---|
| `GAP-ONBOARD-001` (safe onboarding lifecycle closed) | 설치 project에서 target별 preview/apply/update/remove를 제공하고, qlibx-owned block과 fingerprint가 확인된 generated file만 변경한다. 기존 schema v1 결과는 안전하게 update/remove하며 modified generated file, malformed marker와 unsafe manifest path는 target mutation 전에 실패한다 | `tests/test_onboarding.py`와 `tests/test_cli.py`에서 fresh/existing instruction file, CRLF byte preservation, idempotency, obsolete-file cleanup, extension preservation, v1 migration, remove preview/apply, target isolation과 typed post-apply validation evidence를 검증한다 |
| `GAP-TIME-001` (declared time semantics closed) | Naive source timestamp는 declared `source_timezone` 없이 등록되지 않고, session query는 caller가 선언한 session timezone의 calendar day로 관측치를 선택한다. Offset-qualified source의 unused timezone과 ambiguous local time은 mutation 전에 실패한다 | `tests/test_data_registration.py`에서 source localization과 PIT cutoff를, `tests/test_session_timezone.py`에서 UTC/KST 날짜 경계의 session selection을 검증한다 |
| `GAP-CONSTRAINT-001` | 설치 프로젝트의 standalone constraint workflow는 no-short·10% floor·PIT benchmark cap adjustment와 독립 validation을 제공한다. 그러나 public result는 아직 `eligible`을 사용하며 새 advisory `passed`/`compliant` semantics와 맞지 않는다 | 기존 adjustment 산술과 benchmark identity 검증을 보존하면서 validation schema, sample과 tests를 advisory finding으로 migration하고 missing input/evaluator failure만 `OperationError`인지 검증한다 |
| `GAP-EXECUTION-PREPARATION-001` | `run_daily()`는 Strategy weight를 바로 `DecisionIntent`와 sizing으로 넘기며 execution-time Account/price/lot/benchmark를 사용하는 단일 preparation 경계와 optional constraint 연결이 없다 | Constraint 없는 pass-through가 기존 daily result와 동일하고, constraint profile은 execution event에서 construct/adjust/validate를 고정 순서로 호출해 finding과 request lineage를 남긴 뒤 breach 여부와 무관하게 Exchange를 호출한다 |
| `GAP-EXCHANGE-BASE-001` | `KrxExchange`와 `AcademicExchange`는 별도 concrete class지만 공통 `BaseExchange`가 없고 public composition은 concrete type에 직접 결합되어 있다 | Generic abstract base가 stable exchange identity, immutable request, typed result와 Account/Memory non-mutation을 강제한다. 두 subclass와 두 flow의 서로 다른 semantics/result는 유지하며 기존 numerical/replay acceptance가 동일하다 |
| `GAP-LOOKBACK-001` | `ComponentRequirement`와 current `DatasetView.history()`에는 exact `rows`/`calendar` lookback이 없어 PIT 상한 이전의 전체 history를 읽는다 | Requirement→ResolvedBinding→Store query→AccessRecord 전체에서 rows/calendar semantics를 강제한다. 신규 registration은 content-addressed normalized Parquet query snapshot을 만들고 DuckDB predicate/projection pushdown으로 읽는다. 기존 registration은 explicit `QlibxProject.reindex_datasets()` 전에는 `DATASET_QUERY_SNAPSHOT_REQUIRED`로 실패하며 lazy query-time migration은 허용하지 않는다 |
| `GAP-EXECUTION-FEEDBACK-001` | Execution artifact에는 zero-dealt diagnostic이 있지만 current StrategyView는 prior execution result를 직접 노출하지 않아 전량 blocked result가 다음 Strategy input에 도달하지 않는다 | `latest_execution_result()`가 exact execution artifact와 requested/dealt/reason을 노출하고 실제 access lineage를 기록한다. Zero-dealt는 Fill/Account mutation을 만들지 않으며 current profile은 decision 사이에 소비할 execution result가 하나라는 schedule invariant를 검증한다 |
| `GAP-PUBLIC-FACADE-001` | Ensemble, stored-signal strategy, portfolio construction과 analysis/report sample이 `qlibx.flow` concrete class를 직접 조립해 `QlibxProject._with_catalog_session()` 경계를 우회한다 | `QlibxProject`가 기존 flow를 감싼 public methods를 제공하고 bundled samples/tests가 facade를 사용한다. Catalog session conflict는 raw exception이 아니라 typed `OperationOutcome`이다. 지원 import surface는 `from qlibx import ...`로 고정하고 제거되는 root/context module에는 compatibility shim을 두지 않는다 |
| `GAP-RETURN-AUTHORITY-001` | `analyze_signal`이 Exchange와 Account를 거치지 않고 `hypothetical_long_short_return`을 계산해 public analysis artifact로 발행한다. §4.2와 §4.6이 금지한 경로다 | 해당 metric과 그 계산을 제거해 signal 분석이 portfolio 수익률을 산출하지 않는다. Bundled showcase는 같은 1기간 수치를 academic execution 경로로 재현해 두 경로가 일치함을 증거로 남긴다 |
| `GAP-IMPACT-001` | 현재 Exchange의 participation 산술은 observed available volume을 사용할 수 있지만 total-market-volume authority가 없다. 따라서 market-impact parameter는 public daily profile에서 지원하지 않으며 impact 미모델링 limitation을 유지한다 | total-market-volume semantic role, PIT binding, price-impact oracle, fee/impact 비중복 검증이 모두 추가되어야 한다 |
| `GAP-DIRECTION-001` (hypothetical direction closed) | Explicit AcademicExchange listing이 Stock/ETF/Index/Factor의 `hypothetical_short`를 production Account와 분리해 지원한다. Fixed zero-friction profile, signed fractional quantity, next-session-close PIT price, state checkpoint와 hypothetical limitation을 보존한다 | `tests/test_academic_exchange.py`와 `tests/test_public_academic.py`에서 direction/price semantics, long-short/flip, all-or-fail preflight, lineage, replay와 checkpoint recovery를 검증한다 |
| `GAP-REAL-SHORT-001` | Production KRX와 Account는 long-only다. Borrow availability, locate, collateral, margin, short proceeds, recall과 borrow fee authority가 없으므로 executable real short를 current support로 주장하지 않는다 | explicit real-short instrument direction, borrow/collateral/locate policy, Account short invariants와 independent reconciliation이 함께 검증되어야 한다 |
| `GAP-MONITOR-001` (public no-trade monitoring closed) | 설치 project가 committed Account checkpoint에서 독립 constraint monitoring을 frozen spec으로 실행한다. 같은 evaluation instant가 Account valuation과 benchmark PIT cutoff를 결정하며, wall clock이나 daily flow 자동 삽입을 사용하지 않는다 | `tests/test_public_constraints.py`에서 checkpoint 복원, 동일 spec의 동일 artifact identity, held-position mark freshness, stale valuation과 손상 checkpoint의 typed failure를 검증한다 |
| `GAP-MATERIALIZATION-PIT-001` (public direct forward-label materialization closed) | `QlibxProject.materialize()`가 generic `MaterializationOperation` requirement를 producer 실행 전에 resolve하고, built-in `ForwardReturnLabelModel`은 start/end value와 explicit `horizon_end`를 읽어 PIT-bounded `forward_return_label_result:v1`을 만든다. 이는 direct invocation 지원이며 scheduled materialization이나 model registry 지원을 뜻하지 않는다 | `tests/test_materialization.py`, `tests/acceptance/test_materialization_scenarios.py`, `tests/test_public_materialization_sample.py`가 missing/ambiguous horizon의 pre-compute failure, no reusable success/state mutation, immutable binding 추가 후 linked retry, real-DW 수치, future-hidden label, installed public sample을 검증한다 |
| `GAP-EXECUTION-CONVENTION-001` (public frozen close/open comparison closed) | `FrozenDailyExecutionSpec`과 `QlibxProject.execute_frozen_daily()`가 exact `decision_intent:v1` parent를 package-owned next-session-close/open timing으로 실행한다. `session_closes`는 mark/monitor cadence로 유지되고 next-open은 별도 `session_opens`와 open-price binding을 요구한다. Intraday VWAP, market impact와 production OMS는 포함하지 않는다 | `tests/acceptance/test_execution_scenarios.py`와 `tests/test_execution_convention_sample.py`가 real-DW open/close 가격·수량, producer non-rerun, parent hash 불변, child Account/lineage 격리, missing/future-hidden price와 missing schedule의 pre-mutation failure, recovery execution time, installed public sample을 검증한다 |
| `GAP-STRATEGY-COMPOSITION-001` (installed frozen composition closed; v3 migration pending) | Current `strategy_result:v2` exact member composition은 서로 다른 path-dependent source의 Account/Memory identity와 cursor를 보존한다. Exact lookback과 execution feedback closure는 canonical result를 `strategy_result:v3`으로 한 번만 올린다 | v3 전환 뒤 producer와 모든 exact consumer는 v3만 사용한다. v1/v2는 `STRATEGY_RESULT_SCHEMA_UNSUPPORTED`로 실패하고 migration adapter/CLI 없이 producer를 재실행한다. Composition은 v3의 dataset/execution access와 source lineage를 그대로 보존한다 |
| `GAP-RECOVERY-001` (default local daily flow closed) | Versioned recovery point가 Account checkpoint, Strategy Memory, feedback cursor, scheduler position과 누락 가능 evidence를 묶는다. External Account/OMS와 distributed recovery는 별도 contract가 필요하다 | `tests/scenarios/recovery.yaml`의 real-DW process-crash matrix에서 각 crash point의 resume이 uninterrupted result와 같고 decision/Fill/Memory를 중복 적용하지 않으며 changed identity는 mutation 전 `RESUME_BRANCH_REQUIRED`로 실패한다 |
| `GAP-CATALOG-001` (default local backend closed) | DuckDB schema v1, bounded cross-process writer lock, payload staging, append-only publication audit와 abandoned pre-commit recovery를 current local backend가 제공한다. External backend와 multi-host filesystem은 별도 contract validation이 필요하다 | `tests/scenarios/catalog_recovery.yaml`의 concurrent writer와 process-crash fixture에서 partial payload가 reusable success로 보이지 않고 conflict/idempotent/recovery 결과가 deterministic하다 |

ETF look-through는 이 revision에서 `UC-LOOKTHROUGH-001`~`003`과 §10.5로 **user-authored Strategy behavior**임을
명시한다. qlibx가 제공할 current support는 user-declared PIT data consumption, actual AccountSnapshot 접근과 generic
artifact lineage이며, ETF-specific 자동 mapping/resolution/result 생성은 package scope가 아니다.

Production outbox/reconciliation과 lifecycle cash flow는 current readiness gap이 아니라 명시적인 future work다.
Merger, spin-off와 delisting의 원천 해석·변환은 security master/ETL 책임이므로 qlibx readiness gap이 아니다.

## 16. Compatibility gates and validation

Compatibility gate는 구현 구조가 아니라 기존 observable result의 의미가 보존되는지 판정한다.

### 16.1 Reference or calculation change

Reference code, borrowed calculation 또는 cost/metric rule을 바꾸면 source provenance와 영향을 받는 use-case ID를
식별한다. Frozen fixture에서 numerical result뿐 아니라 requested/dealt quantity, actual-state timing, PIT cutoff,
unsupported failure와 evidence가 이전 contract와 일치하거나 명시적으로 versioned change여야 한다.

### 16.2 Runtime or component change

Strategy, executor, artifact backend나 local extension mechanism을 교체해도 다음을 재검증한다.

- same frozen input의 deterministic replay
- Decision과 full-fill MVP executor의 분리 및 actual feedback
- hold/no-trade monitoring과 checkpoint/resume
- typed artifact round-trip, failure evidence와 dependency lineage
- §3.5 stable current-scope use cases와 §15 acceptance scenario

Internal class나 callback 이름의 parity는 요구하지 않는다.

### 16.3 Schema and artifact change

Old artifact는 안전하게 읽히거나 explicit migration/unsupported error를 제공해야 한다. Schema change가 logical identity,
producer-independent loading, path-dependent source state/cursor lineage, partial publication recovery 또는 actual/intended
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
actual feedback이 closed loop에서 일관되게 작동해야 한다. `UC-ACADEMIC-001`은 분리된 hypothetical state와 명시적
한계 안에서 current support다. `UC-FUTURE-001`, `UC-PERP-001`과 `UC-CASHFLOW-001`은 future characterization이며
current support claim이 아니다.

### 17.2 Optional future capabilities

Real short, derivatives, lifecycle cash flow, actual settlement, partial fill, alternative optimizer, AI-assisted Strategy,
distributed execution과 production integration은 독립적인 product decision으로 추가할 수 있다. 각 확장은 새
requirement를 해당 workflow에서 발견하고,
기존 minimal registration이나 unrelated research를 막지 않아야 한다. 구체적인 component hierarchy와 service topology는
architecture가 정한다.

## 18. Product-level conclusion

qlibx는 하나의 고정 research pipeline을 강제하지 않는다. 최소한의 semantic binding으로 시작하고, 선택한 workflow가
필요로 하는 requirement를 실행 시점에 발견하며, package의 deterministic error와 validation을 agent가 user decision으로
연결한다.

제품이 보존해야 할 핵심은 다음과 같다.

- Data availability, evaluation cutoff와 exact `rows`/`calendar` lookback의 PIT integrity
- Direct Strategy, stored model output와 ensemble Strategy의 선택 가능한 composition
- Hypothetical, long-only, long-short와 enhanced-index workflow의 명시적 의미
- Strategy decision, execution-time `ExecutionPreparation`과 selected `BaseExchange`의 분리
- Simulation Account에 commit된 actual result의 authority
- Producer-independent typed artifacts, lineage, failure evidence와 safe reuse
- Decision과 독립적인 actual-account monitoring

User가 product contract로 확정한 `BaseExchange`와 분리된 `KrxExchange`/`AcademicExchange` hierarchy를 제외하면,
reference implementation, 다른 specific class hierarchy, global stage enum, storage backend나 validation library는 이 의미를
구현하는 수단이지 PRD의 목적이 아니다. Architecture는 stable use case마다 trigger, permitted input, state transition,
evidence와 validation을 추적 가능하게 설명해야 한다.
