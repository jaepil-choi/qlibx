# qlibx Product Requirements Document

## 1. Product overview

### 1.1 제품 정의

`qlibx`는 Qlib을 실행 기반으로 사용하는 alpha research framework다. Quant researcher와 AI coding
agent가 다음 작업을 하나의 재사용 가능한 연구 환경에서 수행하도록 돕는다.

- 프로젝트 데이터를 logical dataset으로 등록한다.
- Signed long-short alpha를 만들고 평가한다.
- 고정된 규칙 또는 적응형 `StrategyAgent`를 실행한다.
- 저장된 alpha를 다시 실행하지 않고 ensemble한다.
- Signed active intent를 long-only enhanced index portfolio로 변환한다.
- Qlib의 order, fill, position, account lifecycle에서 portfolio를 실행한다.
- 성공과 실패를 포함한 연구 이력을 남겨 다음 연구의 출발점으로 사용한다.
- Built-in module을 project-local Python module로 교체하거나 확장한다.

이 기능들은 독립적으로 사용할 수 있다. `qlibx`는 모든 연구가 하나의 end-to-end pipeline을 따라야
한다고 강제하지 않는다.

### 1.2 제품 철학

#### Qlib을 backtest와 execution engine으로 사용한다

Qlib은 strategy가 decision time에 관측 가능한 상태를 보고, order를 제출하고, fill을 받은 뒤, 이후
decision에서 실제 portfolio 상태를 다시 보는 closed-loop backtest lifecycle을 제공한다. `qlibx`는
이 lifecycle을 다시 만들지 않고 최대한 Qlib에 맡긴다.

`qlibx`가 담당하는 부분은 그 주위의 research automation이다. Data contract, strategy research,
reusable alpha, ensemble, enhanced index construction, signed-alpha compatibility, result storage와
agent-facing tool을 제공한다.

#### AI coding agent가 public surface만으로 사용할 수 있어야 한다

Agent는 private implementation을 읽지 않고도 qlibx 사용법을 확인하고, project를 초기화하고, data를
등록하고, research를 실행하고, 기존 결과를 조회하고, local extension을 추가할 수 있어야 한다.

이를 위해 설치된 package는 사람용 문서뿐 아니라 agent가 필요한 부분만 조회할 수 있는 help,
machine-readable schema, examples, error description과 task instruction을 제공해야 한다.

#### Core package는 계약을 판정하고, agent layer가 user와 대화한다

`qlibx` core package는 명시된 input contract를 받아 명시된 output을 만드는 deterministic library다. User
에게 질문하지 않고, 부족한 data를 스스로 찾아 등록하지 않으며, 빠진 input을 유사한 다른 값으로 추정하지
않는다.

많은 capability는 특정 data가 등록되어 있어야만 성립한다. 예를 들어 beta residualization은 market return을
요구하고, market return은 index return 또는 market-capitalization weighting 중 하나로 만들어져야 한다.
OHLCV 가격만 등록된 project에서는 이 중 어느 경로도 성립하지 않으므로 beta를 추정할 수 없다.

이때 core package가 할 일은 조용히 비어 있는 결과를 돌려주거나 임의의 proxy로 대체하는 것이 아니라,
**무엇이 왜 부족하고 어떤 경로로 충족할 수 있는지를 machine-readable하게 보고하는 것**이다. 이 보고를
받은 agent layer가 user에게 설명하고, 함께 interview하여 필요한 data registration이나 config 작성을
완성한 뒤 같은 capability를 다시 실행한다.

```text
core package        : capability requirement 선언 -> 충족 판정 -> requirement gap 보고
agent layer (skill) : gap 해석 -> user와 interview -> registration/config 완성 -> 재실행
```

이 분리 덕분에 core package는 대화형 상태를 갖지 않고 테스트 가능하게 유지되고, agent는 package
내부 source를 읽지 않고도 무엇을 물어야 할지 알 수 있다. 이 흐름은 alpha operation에만 적용되는 것이
아니라 data, strategy, exposure analysis, portfolio construction, execution, reporting과 extension을 포함한
**모든 capability에 동일하게 적용된다**. 상세 contract는 section 5.4와 5.5에서 정의한다.

#### 새 연구는 기존 evidence에서 시작한다

성공한 alpha뿐 아니라 실패, invalid run, 이미 검색한 parameter range와 research decision도 조회할 수
있어야 한다. Agent는 새 trial을 제안하기 전에 이 context를 확인하고, 기존 연구의 단순한 parameter,
sign 또는 scale variation이 아닌 이유를 설명해야 한다.

#### Built-in은 일관성을 제공하고 local extension은 자율성을 제공한다

자주 사용하는 signal processing, exposure analysis, portfolio diagnostics와 reporting은 deterministic한
built-in으로 제공한다. Agent마다 같은 helper를 다르게 다시 구현하는 문제를 줄이고 공통 vocabulary를
제공하기 위해서다.

Built-in만 허용하는 것은 아니다. 사용자나 agent는 compatible한 local Python file을 만들고 project에
등록하여 workflow에 연결할 수 있어야 한다. 이를 위해 installed `qlibx`, Qlib 또는 site-packages를
수정할 필요가 없어야 한다.

#### Stored result가 module 사이의 public integration point다

Data loader, transform, strategy, model, evaluator, ensemble, optimizer, backtest와 reporter는 문서화된
serializable artifact를 주고받아야 한다. 사용자는 raw backtest result를 꺼내 독립적인 Python code로
처리하고, compatible한 result를 다시 workflow에 연결할 수 있어야 한다.

#### 한 repository와 한 branch에서 병렬 연구한다

여러 agent가 하나의 repository와 shared branch에서 동시에 작업할 수 있어야 한다. Agent별 Git
worktree는 필요하지 않다. Session isolation, frozen run input, conflict detection과 safe result
publication은 사용자가 매번 요청하는 option이 아니라 기본 behavior다.

### 1.3 지원하는 전체 research flow

```text
project-owned data
-> point-in-time availability를 가진 logical dataset
-> fixed 또는 adaptive StrategyAgent
-> ticker-level signed alpha
-> stored-alpha ensemble과 ticker-level netting
-> benchmark-relative active intent
-> long-only enhanced index portfolio
-> Qlib order / fill / position / account lifecycle
-> reusable artifact, report와 next-decision feedback
```

`qlibx`의 중요한 capability는 long-short alpha research, 여러 long-short alpha의 ensemble, long-only
enhanced index portfolio와 실제 Qlib execution을 하나의 lineage로 연결하면서 original active intent와
realized result를 함께 관측할 수 있다는 점이다.

## 2. Product boundaries

### 2.1 qlibx가 담당하는 것

- Project와 dataset contract
- Agent onboarding, documentation과 skill resource
- 모든 capability의 requirement 선언, 충족 판정과 requirement gap 보고
- StrategyAgent input, output, state와 nested research
- Signed alpha, transform, budget과 diagnostics
- Stored-alpha ensemble과 enhanced index construction
- Qlib long-only account에서 signed alpha를 관측하기 위한 compatibility mode
- Research workspace, artifact와 centralized catalog
- Project-local extension registration과 artifact compatibility
- 병렬 agent의 isolation과 conflict behavior

### 2.2 Qlib에 맡기는 것

- 기본 closed-loop backtest schedule
- Exchange와 tradability behavior
- Order submission과 dealt quantity
- Partial fill, suspension, price limit과 volume limit
- Position, cash, cost, account value와 portfolio feedback

`qlibx`는 Qlib input을 adapt하고 output을 관측할 수 있지만, Qlib account와 별도로 움직일 수 있는 두
번째 execution engine을 유지해서는 안 된다.

### 2.3 사용자의 project가 소유하는 것

- Source data와 preprocessed data
- Dataset, strategy, model, portfolio와 reporting config
- 조직별 benchmark, sector, factor, constraint와 cost definition
- Local extension source
- Research objective, evaluation policy와 promotion decision

`qlibx` 설치와 upgrade는 project-owned definition을 자동으로 설치하거나 조용히 수정해서는 안 된다.

### 2.4 Out of scope

- Qlib 자체에 native short-position support를 추가하는 일
- Qlib의 core order, fill, account 또는 backtest engine을 대체하는 일
- Upstream market-data normalization system을 만드는 일
- Git branch, worktree 또는 merge를 관리하는 일
- Signal이 완전한 market-neutral 또는 sector-neutral임을 보장하는 일
- User-defined evidence와 criteria 없이 경제적 가설의 투자 가능성을 대신 결정하는 일

### 2.5 금지해야 하는 behavior

- 명시적인 요청 없이 data registration 과정에서 user source data를 이동하거나 수정한다.
- Project extension을 추가하기 위해 installed `qlibx`, Qlib 또는 site-packages를 수정한다.
- Synthetic inverse ticker 매수로 underlying short를 흉내 낸다.
- Long leg와 short leg를 관계없는 account에서 실행한 뒤 PnL만 합친다.
- Requested target 또는 별도 signed ledger를 realized Qlib holding으로 취급한다.
- Flexible budget의 unused amount를 복원하거나 관계없는 security에 배분한다.
- 이미 관측한 기간을 true forward out-of-sample로 표시한다.
- 다른 agent가 config를 수정하여 이미 시작된 run의 의미를 바꾸게 한다.
- Required data가 없을 때 해당 항목을 조용히 생략하거나 비어 있는 값으로 채운 부분 결과를 정상 결과로
  반환한다.
- Required data를 유사한 다른 dataset, 유사한 column 이름 또는 임의의 proxy로 대체한다.
- 어떤 requirement가 왜 충족되지 않았는지 알리지 않고 실패한다.
- Core package가 user에게 직접 질문하거나, agent와 user의 확인 없이 data registration을 수행한다.

## 3. Human user journey

Human user는 package 내부 구조를 배우거나 모든 config를 직접 작성할 필요가 없어야 한다.

### 3.1 qlibx 설치

User는 기존 repository에 `uv add qlibx`로 package를 추가하고, 사용할 data를 `data/` 같은 project-owned
location에 둔다. Package에는 project-specific dataset이나 strategy config가 포함되지 않는다.

### 3.2 Coding agent 준비

User는 사용하는 coding agent에 맞는 qlibx onboarding action을 실행한다. 의도하는 사용 경험은 다음과
같다.

```text
qlibx init --append-instruction
qlibx add skill --target claude
```

최종 CLI 이름과 option은 이 PRD에서 확정하지 않는다. 필요한 product result는 다음과 같다.

- `AGENTS.md`, `CLAUDE.md` 또는 사용자가 선택한 agent instruction file에 qlibx instruction을 안전하게
  추가한다.
- 대상 instruction file이 없으면 user 선택에 따라 새로 만든다.
- Agent tool에 맞는 qlibx skill과 supporting file을 tool-specific 또는 user-selected directory에
  생성한다.
- Setup을 반복해도 managed instruction block이 중복되지 않는다.
- 기존 user-authored content를 덮어쓰지 않는다.

### 3.3 Agent에게 data registration 요청

Onboarding이 끝나면 user request는 짧을 수 있다.

```text
data/에 있는 데이터를 qlibx에 등록해줘.
```

Installed instruction과 skill은 agent에게 qlibx documentation을 찾는 법, source data를 수정하지 않고
inspect하는 법, project config를 만드는 법, dataset contract를 validate하는 법과 unresolved ambiguity를
보고하는 법을 알려줘야 한다.

User는 다음 결과를 review한다.

- 생성하거나 수정한 config
- Logical dataset name과 schema
- Time과 availability assumption
- Validation과 bounded load smoke result
- Agent가 추측하지 않고 남긴 질문

### 3.4 Agent에게 alpha research 요청

User는 qlibx operation을 설명하는 대신 research objective를 말할 수 있어야 한다.

```text
등록된 데이터로 새로운 reversal alpha를 연구해줘.
기존 연구와 겹치지 않는지 먼저 확인하고 결과와 실패를 모두 남겨줘.
```

Installed skill은 agent가 prior research를 조회하고, bounded proposal을 등록하고, isolated session에서
trial을 실행하고, artifact와 decision을 publish하도록 안내해야 한다.

### 3.5 Stored result 재사용

User는 stored alpha 비교, ensemble, enhanced index portfolio, Qlib backtest 또는 custom report를 요청할
수 있다. Result identity를 정의하는 input이 바뀌지 않았다면 original strategy를 다시 실행하지 않고
stored artifact를 재사용해야 한다.

### 3.6 Project 기능 확장

Built-in module이 충분하지 않으면 user는 local Python implementation을 요청할 수 있다.

```text
exponential signal decay를 qlibx local extension으로 추가해줘.
qlibx package는 수정하지 말고 기존 signal transform과 호환되게 만들어줘.
```

Agent는 public qlibx contract를 사용해 component를 scaffold, validate, register해야 한다.

## 4. AI agent journey

AI agent용 behavior는 핵심 product requirement이므로 human journey보다 상세히 정의한다.

### 4.1 qlibx instruction 로드

Agent는 repository instruction 또는 installed qlibx skill에서 시작한다. 이 resource는 다음을 알려줘야
한다.

- qlibx help와 agent-facing documentation을 조회하는 방법
- 선택된 project config, state, research와 extension root를 찾는 방법
- Artifact별 public schema와 example을 찾는 방법
- 어떤 operation이 read-only이고 어떤 operation이 project file을 만드는지
- Error detail과 suggested next action을 조회하는 방법
- Shared branch와 no-worktree가 default behavior라는 사실
- Project work를 위해 installed package source를 수정하면 안 된다는 사실

Agent는 private source를 읽거나 전체 manual을 한 번에 load하지 않고 `--help`와 유사한 public surface를
통해 task-specific documentation을 bounded하게 가져올 수 있어야 한다.

### 4.2 Project 상태 확인

Agent는 변경 전에 다음을 확인한다.

- qlibx initialization 여부
- Active project manifest와 selected root
- qlibx와 schema version
- Registered dataset과 component
- Centralized research catalog와 active session
- 요청한 action이 만들거나 바꿀 file

### 4.3 Project data 등록

Data registration request를 받으면 agent는:

1. candidate file을 read-only로 inspect한다.
2. installed dataset schema와 example을 조회한다.
3. date, ticker, value, frequency, timezone과 availability semantics를 확인한다.
4. 의미를 안전하게 확정할 수 없으면 user에게 질문한다.
5. Project가 선택한 config root에 config를 만든다.
6. Key, type, uniqueness, output shape와 time semantics를 validate한다.
7. Logical dataset을 register하고 bounded load smoke를 수행한다.
8. Dataset ID, changed file, validation result와 limitation을 반환한다.

Agent는 비슷해 보이는 column name만으로 경제적 의미를 확정해서는 안 된다.

Basic registration은 source를 project 안에서 안전하게 다시 찾고 읽을 수 있게 만드는 단계다. 이 단계는
availability, ticker, key, dtype과 opaque information column을 기록하지만, 특정 strategy나 capability가
요구하는 semantic role을 source column에 부여하지 않는다. 예를 들어 source의 `시가`를
`open_price`로 해석하는 결정은 basic registration에 포함되지 않는다.

Capability가 선택된 뒤에는 별도의 **capability input binding** 단계가 수행된다. Agent는 basic
registration 결과의 field inventory만 읽어 requirement와 맞을 가능성이 있는 source field를 user에게
제안하고, user가 명시적으로 확인한 뒤에만 project-owned binding YAML을 작성하거나 변경한다. Candidate
mapping은 user 확인 전에는 실행 가능한 binding이 아니며, source Parquet이나 basic registration
provenance를 변경하지 않는다.

이 절차는 user가 registration을 직접 요청했을 때뿐 아니라, section 4.8의 requirement gap을 해소하는
과정에서도 동일하게 사용한다.

### 4.4 Alpha trial 준비

새 alpha experiment를 실행하기 전에 agent는:

1. registered alpha와 superseded alpha를 조회한다.
2. failed trial과 invalid trial도 포함해 확인한다.
3. nearest semantic neighbor와 empirical neighbor를 찾는다.
4. searched parameter range와 active proposal을 확인한다.
5. hypothesis, mechanism, input, clock, horizon, transform, evaluation segment와 stopping condition을 가진
   bounded proposal을 작성한다.
6. candidate가 new alpha인지, existing alpha family variation인지, diagnostic trial인지 구분한다.

### 4.5 Research 실행과 publish

Agent는 isolated research session을 시작한다. Run 시작 시 resolved config, dataset snapshot, component
version과 seed를 해당 run에 고정한다.

Research workspace는 scratchpad로 사용할 수 있다. Completed trial은 다음을 publish해야 한다.

- Canonical run record
- Input과 output artifact ID
- Metric, exposure, turnover, cost와 availability diagnostics
- Success, failure 또는 invalid status
- Existing research와의 비교
- Concise research decision과 next action

Scratch에만 남은 incomplete output은 completed alpha로 catalog에 나타나서는 안 된다.

### 4.6 Built-in 사용 또는 extension 추가

Agent는 common helper를 작성하기 전에 installed documentation에서 현재 version의 built-in과 extension
contract를 확인한다. Compatible built-in이 없으면 해당 extension point가 요구하는 input, output,
lifecycle과 validation rule을 읽고 project-local code를 만든다. 실제 연결 방식은 그 extension contract에
따르며 site-packages를 수정하지 않는다.

Built-in을 선택할 때는 그 capability의 requirement 선언도 함께 확인한다. 요구되는 data가 아직 등록되어
있지 않으면 실행을 시도하기 전에 section 4.8의 절차로 넘어간다.

### 4.8 Capability requirement gap 해소

이 절차는 특정 단계에 고정된 순서가 아니라, 4.3부터 4.7까지 어느 지점에서든 capability가 requirement
gap을 보고하면 발생하는 cross-cutting behavior다.

Agent가 요청받은 작업이 등록되지 않은 data를 요구하는 경우:

1. Capability의 requirement 선언을 조회하거나 반환된 requirement gap을 읽는다.
2. 어떤 capability가 무엇을 왜 요구하는지 user에게 설명한다.
3. Acceptable derivation alternative와 각각에 필요한 data를 제시한다.
4. User가 보유한 source data에서 어떤 alternative가 가능한지 함께 확인한다.
5. 선택된 alternative에 대해 section 4.3의 registration interview를 수행한다.
6. 원래 요청을 다시 실행한다.
7. 선택한 alternative, 적용한 가정과 남은 limitation을 research record에 남긴다.

Agent는 requirement gap을 만났을 때 user 확인 없이 alternative를 선택하거나, 요구된 data를 유사한 다른
dataset으로 대체하거나, 해당 항목을 제외한 부분 결과를 완료된 결과로 보고해서는 안 된다. 어떤
alternative도 불가능하면 그 사실과 이유를 user에게 보고한다.

#### Example — Open Close Rebound strategy input binding

`open_close_rebound` strategy가 canonical pandas input `open_price`와 `close_price`를 요구하고, user가
basic registration한 OHLCV dataset에는 `시가`, `고가`, `저가`, `종가`, `거래량`이라는 opaque field가
있을 수 있다.

이 경우 qlibx core는 `시가`나 `종가`의 경제적 의미를 추측하지 않는다. Read-only plan은
`open_price`와 `close_price`가 아직 binding되지 않았다는 requirement gap과 registered field inventory를
반환한다. Agent layer는 generated skill의 resolution interview에 따라 다음처럼 user에게 확인한다.

> 지금 구현하려는 `open_close_rebound` strategy는 `open_price`와 `close_price`를 필요로 합니다.
> 등록된 dataset에서 `시가`를 `open_price`로, `종가`를 `close_price`로 binding하려고 합니다.
> 이 mapping이 맞습니까?

확인 후 작성되는 project-owned binding config의 conceptual shape은 다음과 같다. Exact schema는
installed version의 machine-readable schema가 정한다.

```yaml
schema_version: 1
binding:
  id: open_close_rebound.krx_daily_v1
  strategy: {id: open_close_rebound, version: "1"}
  inputs:
    universe:
      registered_dataset: krx_daily_universe
    market_data:
      registered_dataset: krx_daily_ohlcv
      fields:
        open_price: 시가
        close_price: 종가
```

User가 확인하기 전에는 agent가 config를 쓰거나 strategy를 실행하지 않는다. 확인 후 agent는
project-owned binding YAML에 strategy ID/version, input role, registered dataset ID와 exact
canonical-to-source field mapping만 기록한다. Pandas shape, dtype, lookback과 field semantics는 versioned
Strategy manifest가 소유하며 binding YAML에서 반복하지 않는다. Core는 실제 대화가 일어났음을 증명할
수 없으므로 question text나 confirmation status도 binding에 저장하지 않는다. Generated skill이
user 확인 전에는 binding을 쓰지 못하게 하는 것이 agent-layer policy다.

Resolver는 manifest와 binding YAML 및 registered dataset만 사용해 canonical 이름의 bounded pandas
object를 만들고 strategy implementation에는 `universe`, `market_data` 같은 canonical pandas input만
전달한다. `market_data` 안의 column은 `open_price`, `close_price`로 보인다. Strategy는 source
column명, registration, catalog, YAML 또는 agent를 알지 못한다.

### 4.7 Stored evidence에서 다음 연구 시작

다른 agent는 이전 agent의 전체 scratchpad를 읽지 않고도 proposal, run, artifact, decision과
nearest-neighbor record를 catalog에서 가져와 다음 trial을 정의할 수 있어야 한다.

Parallel session은 qlibx가 자동으로 처리한다. Agent는 user에게 branch, worktree, lock 또는 database
write mechanism을 지정해 달라고 요구하지 않는다.

## 5. Agent onboarding and documentation requirements

### 5.1 Agent-readable documentation

Installed package는 다음 주제의 version-matched documentation을 제공해야 한다.

- Project initialization
- Data discovery, config authoring, validation과 registration
- StrategyAgent와 nested child research
- Alpha transform, exposure analysis와 budget behavior
- Research catalog와 orthogonality workflow
- Ensemble, enhanced index construction과 Qlib execution
- 현재 제공되는 extension point, 정확한 input/output contract와 local extension authoring
- Raw artifact와 reporting contract
- 각 capability의 requirement 선언, acceptable derivation alternative와 gap 해소 절차
- Error code와 recovery guidance

Documentation은 help-style public command와 installed file 양쪽에서 접근할 수 있어야 한다.
Machine-readable schema와 example은 private Python module import 없이 찾을 수 있어야 한다.

### 5.2 Instruction file integration

qlibx는 coding-agent instruction file을 설정하는 onboarding action을 제공해야 한다.

Required behavior:

- `AGENTS.md`, `CLAUDE.md` 같은 supported instruction file을 detect한다.
- User가 한 개 이상의 target을 선택할 수 있다.
- Existing file에는 명확한 delimiter를 가진 qlibx-managed block만 append한다.
- File이 없고 user가 creation을 요청하면 새로 만든다.
- Managed block 밖의 user-authored content를 그대로 보존한다.
- Write 전에 dry-run을 제공한다.
- 같은 action을 반복해도 idempotent하다.
- Old managed block을 update할 때 두 번째 block을 추가하지 않는다.
- Managed block만 안전하게 제거할 수 있다.

Managed block은 짧아야 한다. 전체 documentation을 repository마다 복사하지 않고, version-matched help,
schema와 skill을 찾는 방법을 agent에게 알려준다.

### 5.3 Skill generation

qlibx는 coding-agent skill과 skill에 필요한 reference, script, example을 생성할 수 있어야 한다.

Possible output:

```text
.claude/skills/qlibx-skill/SKILL.md
.agents/skills/qlibx/SKILL.md
<user-selected-output>/qlibx/SKILL.md
```

이 path는 example이며 mandatory project layout이 아니다.

Skill generator는:

- Agent tool별 template을 지원한다.
- Explicit output directory를 받을 수 있다.
- 만들거나 update할 file을 사전에 보여준다.
- User가 수정한 skill file을 confirmation 없이 덮어쓰지 않는다.
- qlibx version과 instruction schema version을 기록한다.
- 생성된 skill structure를 validate한다.
- Generated skill update 시 user-owned extension file을 보존한다.

최소한 다음 skill content를 제공한다.

- Project와 data registration
- Orthogonal alpha research
- 현재 qlibx version에서 제공되는 extension point와 project-local extension authoring

Skill은 extension point 이름만 나열해서는 안 된다. 각 point가 workflow의 어디에 연결되는지, 어떤
input을 요구하고 어떤 output을 반환해야 하는지, data/time boundary, validation 방법과 minimal example을
agent가 실제 code를 작성할 수 있을 정도로 포함하거나 version-matched installed documentation으로
정확히 안내해야 한다.

Final packaging과 command name은 interface design에서 확정할 수 있다. 필요한 결과는 agent가 public qlibx
workflow를 수행하도록 안내하는 valid, discoverable, versioned skill이다.

Skill은 section 5.5의 requirement gap을 받았을 때 수행할 resolution interview 절차를 반드시 포함한다.
Requirement gap을 단순 실패로 보고하고 종료하는 skill은 이 요구사항을 충족하지 않는다.

### 5.4 Capability requirement contract

Section 1.2에서 정의한 분리를 실현하기 위해, 실행에 특정 registered input이 필요한 모든 capability는 그
requirement를 machine-readable하게 선언해야 한다.

여기서 capability는 built-in signal operation, exposure analyzer, portfolio constructor, execution profile,
StrategyAgent definition, reporting analysis와 project-local extension을 모두 포함한다. "이 capability는
어떤 data가 있어야 동작하는가"라는 질문은 이 중 어느 것에 대해서도 동일한 방식으로 답할 수 있어야 한다.

각 requirement 선언은 최소 다음을 포함한다.

- Stable requirement ID와 role name
- 경제적 의미, axis, unit과 currency
- 이 requirement가 어떤 계산에 쓰이는지
- 충족 여부를 판정하는 방법
- Point-in-time과 availability 조건
- Requirement가 optional인지 mandatory인지, optional이면 없을 때 결과가 어떻게 달라지는지
- 이 requirement를 충족하는 acceptable derivation alternative 목록
- Gap 해소를 위해 실행할 public command

Pandas data를 소비하는 requirement는 위 항목에 더해 runtime pandas type, table/matrix shape,
required semantic field 또는 column, dtype, index/column axis와 nullability를 machine-readable하게
선언한다. Strategy requirement의 canonical role과 source field name은 같은 개념이 아니다.
`open_price` requirement가 source의 `시가` field로 충족될 수는 있지만, 그 관계는 user-confirmed
capability input binding에만 기록한다.

Requirement는 단일 dataset 목록이 아니라 **derivation alternative를 가진 선택지**로 표현한다. 하나의
requirement를 서로 다른 input 조합으로 충족할 수 있기 때문이다.

```text
requirement: market_return
  alternative A: registered index return dataset
  alternative B: market_capitalization + instrument return  -> cap-weighted market return
  neither satisfied -> requirement gap
```

Requirement 선언은 사람용 설명에만 존재해서는 안 된다. Installed help와 machine-readable schema에서
조회할 수 있어야 하고, generated skill에 포함되거나 version-matched resource로 정확히 연결되어야 한다.
Agent는 capability를 실행하기 전에 requirement를 조회하여 gap을 미리 확인할 수 있어야 한다.

Capability가 실제로 요구하지 않는 input을 requirement로 선언해서는 안 된다. 선언과 실제 실행 조건은
일치해야 한다.

Requirement plan은 confirmed binding, unresolved role과 registered field inventory를 구분한다. Agent나
tool이 제안한 candidate field는 user가 확인하기 전까지 requirement evidence가 아니며 `ready=true`를
만들 수 없다. Binding config는 registered dataset ID만 참조할 수 있고 raw path를 직접 참조해서는 안
된다. 같은 registered dataset은 서로 다른 capability/version에 대해 서로 다른 confirmed binding을
가질 수 있다.

Requirement declaration과 resolution은 literal user question을 포함하지 않는다. Core는 required
semantics, missing role/field, acceptable alternative, registered field inventory와 next command 같은
사실만 반환한다. Generated skill은 이 사실에서 exact candidate mapping을 만들고 user에게 자연어로
확인하며, 확인된 결과만 YAML에 기록한다. 따라서 interview wording은 product domain contract가 아니라
agent behavior다.

### 5.5 Requirement gap과 resolution interview

Requirement가 충족되지 않으면 capability는 계산을 시도하지 않고 **requirement gap**을 보고한다.

Requirement gap 보고는 structured error 또는 structured plan result 형태이며 최소 다음을 포함한다.

- Stable error code
- 요청한 capability ID와 version
- 충족되지 않은 requirement 목록과 각각의 이유
- 각 requirement의 acceptable derivation alternative
- 이미 충족된 requirement
- User에게 확인해야 하는 질문
- 다음에 실행할 public command
- Gap 해소 후 동일 요청을 다시 실행할 수 있는지 여부

Capability는 실행 전에 gap을 조회할 수 있는 **plan 형태**와, 실행 시점에 gap을 발견하면 실패하는
**error 형태**를 모두 제공해야 한다. Plan 형태는 read-only이며 아무것도 만들지 않는다. 이 두 형태는 같은
requirement 선언에서 파생되어야 하며 서로 다른 판정을 내려서는 안 된다.

Requirement gap을 받은 agent는 다음을 수행한다.

1. 어떤 capability가 무엇을 요구하는지 user에게 설명한다.
2. Acceptable derivation alternative와 각각에 필요한 data를 제시한다.
3. User가 보유한 data로 어떤 alternative가 가능한지 함께 확인한다.
4. 선택된 alternative에 대해 section 4.3의 data registration interview를 수행한다.
5. Registration이나 config 작성을 완료한 뒤 원래 capability를 다시 실행한다.
6. 어떤 alternative를 선택했고 어떤 가정을 적용했는지 research record에 남긴다.

Agent는 user 확인 없이 alternative를 임의로 선택하지 않는다. 어떤 alternative도 불가능하면 그 사실과
이유를 user에게 보고하고, 해당 capability를 우회하거나 대체 proxy로 결과를 만들어내지 않는다.

Optional requirement가 충족되지 않아 결과의 일부 항목을 계산할 수 없으면, 해당 항목을 조용히 생략하지
않고 계산하지 못했다는 사실과 이유를 결과에 명시적으로 기록한다.

### 5.6 Stage-based error contract

#### Error는 agent layer와의 프로토콜이다

Section 1.2의 분업이 error에도 그대로 적용된다. Core package는 **어느 단계에서 무엇이 관측되었는지**를
보고하고, 그것을 어떻게 고칠지는 agent layer가 skill을 읽고 판단한다.

이 경계가 중요한 이유는 **고치는 방법이 하나가 아니기 때문**이다. 예를 들어 numeric 연산을 하는
Strategy가 문자열이 섞인 column에서 실패했다면, 유효한 해결이 최소 두 가지다.

- Strategy 안에서 해당 column을 명시적으로 cast한다.
- Registration 단계로 돌아가 preprocess한 뒤 다시 register한다.

어느 쪽이 옳은지는 그 문자열이 data quality 결함인지 의도된 column인지에 달려 있고, core package는
그것을 알 수 없다. 따라서 core는 처방하지 않는다. 관측한 사실과 계약이 요구한 것을 보고하고, 선택은
user와 agent에게 남긴다.

#### Error code는 workflow stage를 가리킨다

Error code는 "어떤 종류의 규칙이 깨졌는가"가 아니라 **"user journey의 어느 단계에서 막혔는가"**를
나타낸다. 규칙의 종류는 core가 답할 수 있지만 agent가 쓸 수 없는 정보다. 반면 단계는 agent가 어떤
skill을 열고 어떤 범위의 수정이 정당한지를 곧바로 결정하게 한다.

| stage code | 단계 | 대응하는 절 |
| --- | --- | --- |
| `ONBOARDING` | Agent 준비, documentation, skill, instruction file | 3.2, 5.1-5.3 |
| `PROJECT` | Project 초기화/로드와 경로 봉쇄 | 4.2, 6.1 |
| `DATA_REGISTRATION` | Source inspection과 logical dataset 등록 | 4.3, 6.2, 6.3 |
| `UNIVERSE` | Universe dataset 표준 검사 | 6.5 |
| `STRATEGY_CONTRACT` | Strategy manifest와 binding 작성 | 6.3, 7.1 |
| `STRATEGY_RUN` | Decision 실행, point-in-time 경계, user code | 6.4, 7.2, 7.3 |
| `ALPHA` | Signal transform과 budget | 8.2, 8.4 |
| `PORTFOLIO` | Ensemble과 enhanced index construction | 10.1, 10.2 |
| `EXECUTION` | Qlib order/fill/account lifecycle | 11 |
| `RESEARCH_RECORD` | Session, publication, catalog, artifact | 9, 12.3 |
| `REPORTING` | Stored run 분석과 rendering | 12.4 |

Stage 수는 분류 설계의 결과가 아니라 제품 workflow 단계 수다. 한 stage 안에서는 message와 context가
구체적인 내용을 모두 나르므로 stage를 더 쪼갤 필요가 없다.

#### Public error와 internal error

Public error는 agent layer로 나가는 메시지이며 항상 다음을 갖는다.

- `stage`: 위 표의 code
- `message`: 무엇이 관측되었는지. 하위 예외가 있으면 그 내용을 그대로 포함한다
- `expected`: 그 단계의 계약이 요구한 것
- `context`: 판단 근거가 되는 구체적 값. 위반한 row, column, 값, 개수
- `requires_user_confirmation`: 의미를 user에게 물어야 하는지 여부

Internal error는 qlibx 자신의 invariant가 깨진 것이며 stage도 `expected`도 갖지 않는다. Caller가
유발할 수 없고 고칠 수도 없으므로 agent contract에 포함하지 않는다.

#### Registration 단계에서 requirement를 검사한다

Data와 universe는 **등록 시점에** 계약을 검사하고, 맞지 않으면 등록을 거부한다. 잘못 등록된 dataset이
나중에 Strategy 실행 중에 발견되면 원인 추적 비용이 훨씬 커지기 때문이다.

**사례 — `DATA_REGISTRATION`: availability/ticker 중복**

한 `(available_at, ticker)` 쌍에 두 개 이상의 row가 있으면 point-in-time 조회 결과가 결정적이지
않으므로 등록을 거부한다. qlibx는 어느 row가 옳은지 추측하거나 임의로 aggregate하지 않는다.

```json
{"stage": "DATA_REGISTRATION",
 "message": "Found 3 rows sharing an (available_at, ticker) key",
 "expected": "One row per (available_at, ticker); qlibx does not aggregate silently.",
 "context": {"dataset": "fundamentals", "duplicate_count": 3,
             "violations": [{"available_at": "2024-03-01", "ticker": "005930", "rows": 2}]},
 "requires_user_confirmation": true}
```

Agent가 선택할 수 있는 해결은 최소 셋이다. Source에서 중복을 제거한다, registration query에 명시적
dedup 규칙을 넣는다, 또는 key를 다시 정의한다. 어느 것이 옳은지는 data의 의미에 달려 있으므로 agent가
user에게 확인한다.

**사례 — `DATA_REGISTRATION`: available_at 변환 실패**

available_at으로 선택된 column을 datetime으로 변환할 수 없으면 등록을 거부한다. 변환 실패의 원문을
`message`에 그대로 싣는다.

```json
{"stage": "DATA_REGISTRATION",
 "message": "Column '공시일자' cannot convert to datetime: Unknown datetime string format, unable to parse: 20240301.0",
 "expected": "The available_at column must parse to datetime without coercion.",
 "context": {"dataset": "disclosure", "column": "공시일자", "dtype": "float64",
             "samples": [20240301.0, 20240302.0]}}
```

**사례 — `UNIVERSE`: universe 표준 위반**

Universe는 모든 Strategy가 상속하는 requirement이므로 별도 표준을 갖는다. 등록 시점에 검사한다.

- 값은 boolean이어야 한다. 결측을 미포함으로 해석하지 않는다.
- available_at을 가져야 한다. 다른 dataset과 같은 point-in-time 규칙을 따른다.
- `(available_at, ticker)`가 유일해야 한다.
- 선언된 axis의 모든 cell이 채워져 있어야 한다.

```json
{"stage": "UNIVERSE",
 "message": "Universe values are float64 with 12 missing cells",
 "expected": "Universe membership must be boolean and complete; absence is not non-membership.",
 "context": {"dataset": "kospi_universe", "dtype": "float64", "missing_cells": 12,
             "violations": [{"available_at": "2024-03-04", "ticker": "000660"}]}}
```

**사례 — `STRATEGY_RUN`: user code가 user data에서 실패**

Strategy 실행 중 발생한 실패는 core가 분류하지 않는다. 어느 단계에서 났는지만 표시하고 원문을 그대로
전달한다. 분류를 시도하면 정확하지도 않고 원문 정보를 잃는다.

```json
{"stage": "STRATEGY_RUN",
 "message": "Strategy 'reversal.v1' raised TypeError at 2024-03-05: unsupported operand type(s) for -: 'str' and 'float'",
 "expected": "The Strategy callable must run on its bound inputs at every decision time.",
 "context": {"strategy_id": "reversal.v1", "decision_time": "2024-03-05T00:00:00",
             "inputs": {"returns": {"dtype": "object", "null_count": 4}},
             "traceback_tail": "..."}}
```

이 error를 받은 agent는 skill을 읽고 두 경로 중 하나를 user와 함께 선택한다. Core는 어느 쪽도
지시하지 않는다.

#### 고치는 지침은 skill이 소유한다

각 stage에 대응하는 skill은 그 단계에서 자주 발생하는 실패와, 각각에 대해 **가능한 여러 해결 경로**를
담는다. Core package는 skill 내용을 알지 못하며, error에 특정 해결을 지시하는 문장을 쓰지 않는다.

Skill이 담아야 하는 것은 다음과 같다.

- 그 stage의 계약 요약
- 자주 발생하는 실패와 각각의 가능한 해결 경로 목록
- 어떤 선택이 user 확인을 필요로 하는지
- 해결 후 다시 실행할 public command

## 6. Project and data contracts

### 6.1 Package와 project 분리

qlibx package는 reusable code, schema, built-in, documentation과 onboarding resource를 제공한다. Project
data, config, local extension, research record와 generated state는 user repository가 소유한다.

Project는 config root, generated-state root, research root와 extension root를 선택한다. 다음 layout은
지원할 수 있는 example이지만 mandatory하지 않다.

```text
config/qlibx/
data/qlibx/
qlibx-research/
.qlibx/
qlibx-custom/
```

### 6.2 Logical dataset

qlibx는 project-owned file을 config-defined logical dataset으로 읽는 contract를 제공한다. Product는
Parquet dataset과 DuckDB file을 지원한다.

Dataset definition은 다음을 설명한다.

- Dataset ID와 schema version
- Source type과 project-relative location
- 필요한 경우 explicit table 또는 query
- Required source column과 primary key
- Table 또는 `date × ticker` matrix output
- Date, ticker와 value semantics
- Dtype, frequency와 timezone
- Observation time과 availability lag
- Missing, duplicate와 alignment behavior
- Optional universe와 tradability meaning

User-provided dataset에서 required meaning이 없으면 명확히 실패해야 하고 정확한 의미를 User에게 물어야
한다. Regex로 field를 추측하거나 다른 column으로 조용히 fallback해서는 안 된다.

Agent는 `(date, ticker)`의 data uniqueness와 invalid value를 먼저 검사하고, 문제가 있으면 user에게
알리고 해결 방법을 제시해야 한다. Agent는 point-in-time availability와 delivery lag처럼 source
column만 보고 확정할 수 없는 문제도 경고해야 한다.

Logical dataset과 capability input binding은 다른 identity를 가진다. Logical dataset은 registered source,
query/output shape와 point-in-time rule을 설명한다. Capability input binding은 capability ID/version과
requirement role을 logical dataset 및 exact source field에 연결한다. Binding 변경은 config fingerprint와
새 run identity를 만들지만 basic registration artifact와 provenance는 바꾸지 않는다.

### 6.3 Basic registration과 capability input binding

Data discovery와 registration은 source data에 대해 read-only다. qlibx는 user-provided dataset을 Qlib에
그대로 넘기지 않는다. Basic registration은 source identity, axis, availability와 opaque field inventory를
확정하며 strategy, Qlib profile 또는 다른 capability의 semantic role을 확정하지 않는다.

Basic registration은 다음 순서로 진행한다.

1. Source schema, date/ticker key, frequency, coverage, duplicate와 invalid value를 검사한다.
2. Availability, ticker와 key mapping을 user에게 확인한다.
3. 선택된 information field를 semantic rename 없이 opaque value로 보존한다.
4. qlibx 전용 canonical Parquet을 project의 `data/qlibx/` 영역에 만든다.
5. Generated dataset을 logical dataset으로 등록하고 bounded load smoke를 실행한다.
6. Source schema와 registered field inventory를 provenance에 남긴다.

Successful basic registration은 최소 다음 결과를 제공한다.

- Generated 또는 selected config path
- Generated qlibx Parquet path
- Stable logical dataset ID
- Source identity와 schema summary
- Availability/ticker/key mapping과 opaque registered field inventory
- Availability와 point-in-time status
- Validation result와 bounded load-smoke result

원본 data는 이동, 변환 또는 overwrite하지 않는다. Derived Parquet은 같은 source와 mapping으로 다시
생성했을 때 동일한 logical content를 가져야 한다.

Capability input binding은 capability가 선택된 뒤 다음 순서로 진행한다.

1. Installed requirement declaration에서 canonical role, pandas shape, field semantics와 alternative를 읽는다.
2. Basic registration provenance와 logical catalog에서 registered dataset 및 field inventory를 조회한다.
3. Agent가 가능한 exact field mapping과 파생식을 candidate로 작성하되 아직 config를 변경하지 않는다.
4. Candidate mapping, 적용할 가정과 지원하지 못하는 기능을 user에게 보여주고 확인받는다.
5. User-confirmed mapping만 project-owned binding YAML에 기록한다.
6. Resolver가 binding을 logical dataset query 또는 deterministic projection으로 materialize한다.
7. Canonical pandas input의 dtype, axis, availability, missingness와 bounded load를 검증한다.
8. Binding identity, validation, warning과 unresolved limitation을 research record에 남긴다.

Successful capability binding은 capability ID/version, requirement role, registered dataset ID, exact source
field mapping, derivation, validation result와 config fingerprint를 제공한다. Output pandas contract는
Strategy manifest가 제공하며, interview wording이나 확인 상태는 binding schema에 포함하지 않는다.

#### Daily OHLCV capability-binding and Qlib materialization profile

Timestamp가 없는 daily OHLCV의 basic registration이 끝난 뒤 Qlib daily backtest를 선택하면 qlibx는
필요한 input과 registered source field의 mapping을 제안한다. Built-in default convention은 다음과 같다.

- 관측된 date로 daily trading calendar를 만들고 ticker로 instrument 후보를 만든다.
- Strategy는 trade date `t`보다 앞서 available한 data만 본다. 기본 profile은 `t-1`까지 관측하고
  `t`일 종가에 거래한다.
- `Close`를 execution price로 사용하고 별도 mark price가 없으면 같은 가격으로 당일 valuation한다.
- Price change처럼 Qlib이 요구하지만 source에서 직접 제공할 필요가 없는 값은 mapped price에서
  결정적으로 계산한다.
- `Volume`은 volume participation 또는 partial-fill constraint를 선택한 경우에만 execution capacity에
  반영한다. 사용하지 않을 때는 volume이 investability filter로 조용히 적용되지 않는다.
- 유효한 execution price는 기본적인 거래 가능 후보를 만들 수 있지만, 이것만으로 완전한
  investability 또는 tradability를 주장하지 않는다.
- 거래정지, 상·하한가, 관리종목과 membership data가 있으면 명시적으로 mapping한다. 없으면 qlibx가
  해당 상태를 추측하지 않으며, 적용할 수 없는 execution constraint를 registration result에 알린다.
- Index membership 또는 별도 investment-universe dataset이 있으면 point-in-time으로 결합한다.
- Corporate-action-adjusted price와 quantity factor를 확인할 수 없으면 임의로 보정하지 않는다. Source가
  이미 normalized되었다고 가정할지, corporate-action-aware execution을 지원하지 않을지는 materialization
  전에 user에게 알리고 project-local 문서에 남긴다.

이 profile은 원본 OHLCV나 basic registration artifact에 qlibx 전용 semantic column을 추가하라는 schema
요구가 아니다. User-confirmed capability binding으로 Qlib 전용 materialization과 설명 문서를 생성하는
behavior다. 다른 execution timing이나 valuation convention도 같은 binding·검증·문서화 contract를
만족하면 사용할 수 있다.

### 6.4 No-look-ahead data access

여기서 필요한 계약은 no look-ahead다. Look-ahead가 없다는 사실만으로 strategy가 economically causal한
것은 아니므로 두 개념을 같은 의미로 표현하지 않는다.

각 dataset은 decision time에 무엇을 사용할 수 있었는지 판단할 수 있는 time metadata를 제공한다.
StrategyAgent에는 declared availability가 decision time보다 늦지 않은 observation만 전달한다.

Dataset은 독립적인 clock과 lookback rule을 가질 수 있다. 예를들어 quarterly data의 경우 정확한 lookback days를 몰라도 decision time에 available한 이전 3분기 데이터를 사용하도록 설정할 수 있다. 

또 다른 예시로 economic calendar의 경우도 decision time에 알 수 있었던 미래 일정들이 point-in-time 하게 달라지므로 economic calendar의 event date가 아닌 point-in-time 한 timestamp가 있어야 한다. 

Qlib closed-loop backtest가 decision과 feedback sequence를 제공한다. qlibx는 parent StrategyAgent와 모든
nested child strategy에 data를 제공할 때 이 time boundary를 보존한다.

### 6.5 Universe와 tradability

Research universe와 Qlib execution tradability는 같은 개념이 아니다.

- Research universe는 strategy가 signal 또는 target을 만들 수 있는 instrument를 나타낸다.
- Qlib execution state는 price availability와 제공된 suspension, price-limit, volume-limit 등의 data를
  이용하여 실제 order가 체결될 수 있는지를 판단한다.
- Matrix axis에 ticker가 존재한다는 사실만으로 research universe 포함 또는 tradability를 추론하지
  않는다.
- 제공되지 않은 shortability, borrow inventory 또는 exchange restriction을 qlibx가 추측하지 않는다.
- Universe에서 제외된 보유종목은 target에서 제거할 수 있지만 실제 liquidation 여부와 시점은 Qlib
  order/fill 결과로 확인한다.

Source data와 선택한 execution profile이 표현할 수 있는 범위에서 universe entry, exit, blocked
liquidation과 re-entry가 관측 가능해야 한다. Data가 표현하지 못하는 상태를 완전한 market reality처럼
보고해서는 안 된다.

### 6.6 Frozen run config

Run 시작 시 qlibx는 project config와 selected component version을 resolve하여 immutable effective config
ID를 만든다. Shared repository에서 이후 config가 바뀌어도 해당 run은 바뀌지 않는다.

Unknown key, missing dataset, incompatible axis와 incompatible component contract는 StrategyAgent 또는 Qlib
execution 전에 실패한다.

## 7. StrategyAgent

### 7.1 Definition

StrategyAgent는 기본적으로 deterministic decision program이다. Effective decision context, strategy definition,
dependency version, checkpoint state와 declared seed가 같으면 같은 decision result를 반환해야 한다.
(예외 존재. 특수한 경우 전략 내에서 random output을 내는 요소가 존재하거나 본질적으로 stochastic한 LLM agent가 embedded 되어있을 수 있음. 하지만 대부분의 일반적인 경우 StrategyAgent는 기본적으로 deterministic.)

Strategy definition 자체는 run 도중 다시 작성되지 않는다. 다만 bounded observation, realized feedback과
strategy-owned state가 변하면 그 decision logic이 다른 rule, model, allocation 또는 action을 선택할 수
있다.

Fixed function도 valid StrategyAgent다. ML retraining, Bayesian belief update와 nested strategy research는
StrategyAgent 내부에서 사용할 수 있는 optional capability다.

Strategy는 가급적 공통 class contract를 사용한다. Class는 구현 유형을 나타내고, 개별 연구의 정체성은
instance의 strategy name, stable ID, parameter, data requirement와 output declaration으로 표현한다. 같은
signal logic을 parameter variation마다 새로운 class로 복사해서는 안 된다.

PRD는 특정 base class, 반환 class 또는 내부 composition pattern을 강제하지 않는다. 구현은 명확한
책임 분리, 작은 public contract, composition, DRY와 효율적인 data flow를 우선하여 clean하고 efficient한
방식을 선택해야 한다.

Strategy implementation의 data plane은 pandas object와 strategy parameter만 안다. Strategy code는 raw
source column, registration spec, project path, catalog, binding YAML 또는 agent API를 import하거나
해석하지 않는다. Strategy definition은 implementation 밖에서 canonical pandas input role과 field
requirement를 선언하고, runtime adapter가 confirmed capability binding을 resolve한 뒤 pandas object만
strategy에 전달한다.

User-side agent는 Strategy requirement를 Python constant로 package에 등록하지 않고 project-owned
Strategy manifest YAML로 선언한다. 예를 들어 `open_close_rebound`의 conceptual manifest는 다음과 같다.

```yaml
schema_version: 1
contract: qlibx.pandas_strategy
strategy:
  id: open_close_rebound
  version: "1"
  name: Open Close Rebound
  implementation:
    source: strategies/open_close_rebound.py
    callable: decide
  parameters: {rebound_threshold: 0.02}
  lookback: {kind: rows, value: 20}
  inputs:
    market_data:
      meaning: Daily market prices used by the rebound rule.
      pandas: {kind: table, index: [observation_time, ticker]}
      fields:
        open_price: {meaning: Session open price, dtype: float64, unit: price, nullable: false}
        close_price: {meaning: Session close price, dtype: float64, unit: price, nullable: false}
  output: {kind: signal}
```

`qlibx.pandas_strategy` contract는 모든 Strategy에 mandatory point-in-time `universe` input을 자동으로
상속한다. 따라서 개별 manifest가 universe requirement를 반복하지 않는다. Strategy별 input과 field만
manifest에 추가한다. 현재 fixed lookback schema는 positive row count만 허용하며 runtime loop의 매
decision마다 각 registered input을 decision time에서 먼저 자른 뒤 최근 fixed rows만 전달한다.

Strategy implementation은 qlibx base class를 상속할 필요가 없다. Plain callable이나 plain class method면
충분하다. Runtime이 callable signature와 pandas input/output을 검증한다. Parent Strategy가 child
Strategy를 실행할 때도 별도 DI container나 qlibx runner API를 주입하지 않고, 이미 bounded된 pandas
input의 같거나 더 좁은 slice를 child callable에 직접 전달할 수 있다.

### 7.2 Decision context와 result

StrategyAgent는 필요에 따라 다음을 입력받는다.

- Decision time
- Dataset별 독립적으로 bounded된 lookback
- Point-in-time universe와 tradability state
- 이전 desired, submitted, filled와 held position
- Realized return, PnL, cost와 turnover
- Qlib-confirmed feedback history
- Strategy-owned memory
- Optional model 또는 belief-state identity
- Isolated nested-research interface

Dataset input은 strategy가 선언한 canonical role 이름으로 전달된다. 같은 source의 `시가`와 `종가`가
confirmed binding을 통해 각각 `open_price`와 `close_price`로 resolve되면 strategy에는 그 canonical
이름의 bounded pandas object만 보인다. Source field 이름과 binding provenance는 invocation/research
record에는 남지만 strategy implementation의 input contract에는 노출되지 않는다.

StrategyAgent의 primary decision payload는 signal, weight, order 또는 strategy가 선언한 다른 결과일 수
있다. Strategy는 필요에 따라 updated memory, physical intent, hold/stop/retrain decision, diagnostics와
중간 계산 결과를 함께 제공하거나 별도 record capability로 남길 수 있다.

Primary output과 intermediate output을 하나의 result에 포함할지 별도 recording interface로 내보낼지는
구현 단계에서 가장 clean하고 efficient한 방식을 선택한다. 어느 방식을 사용하든 downstream wrapper,
transform, ensemble, optimizer와 execution adapter가 private Strategy object를 해석하지 않고 선언된
contract를 통해 결과를 재사용할 수 있어야 한다.

Parent 또는 wrapper strategy는 child output을 받아 transform, decay, neutralization, budget 조정,
ensemble 또는 order 변환을 수행할 수 있어야 한다. 기본 signal 계산을 wrapper마다 다시 구현해서는
안 된다.

### 7.3 Parent lookback 안의 child strategy

Parent StrategyAgent는 next decision 전에 child strategy를 spawn하여 alternative를 평가할 수 있다.
이는 child strategy 활용의 한 예일 뿐이다. Child는 signal 생성, component 재사용, historical
counterfactual, 후보 비교, 후처리 또는 user-defined composition 등 다른 목적으로도 사용할 수 있다.

핵심 access rule은 다음과 같다.

> Child strategy는 해당 decision에서 parent StrategyAgent가 볼 수 있는 data와 feedback만 볼 수 있다.
> Parent보다 넓은 historical window 또는 더 늦은 observation을 요청할 수 없다.

예를 들어 120-day lookback을 가진 parent는:

```text
parent의 bounded 120-day context
-> child strategy A, B, C 실행
-> selected evaluator로 child result 비교
-> parent의 next action 선택
-> parent action만 actual Qlib account에 제출
```

Nested-research request는 child definition, allowed warmup/evaluation slice, evaluator, seed와 resource limit을
명시한다. Return value는 serializable child result, metric, diagnostics와 failure status다.

Child run은 actual Qlib account, parent state 또는 sibling state를 변경하지 않는다. Parent decision 안에서
수행되는 historical what-if evaluation이다.

### 7.4 ML과 belief update

같은 StrategyAgent decision loop 안에서 strategy는 다음을 수행할 수 있다.

- Rolling 또는 expanding training window에서 model retraining
- 여러 historical rule 또는 model 비교
- Bayesian prior-to-posterior update
- Trailing evidence에 따른 member allocation 조정
- Regime, drawdown, execution failure 또는 capacity feedback 반영

이 operation은 strategy decision logic이 사용하는 input을 갱신한다. Strategy definition을 nondeterministic하게
바꾸는 것이 아니다. 사용하는 strategy는 model version, train/evaluation window, evidence, posterior와
selected action을 optional diagnostics로 남길 수 있다.

Historical evaluation, model fitting, prediction과 belief update는 actual Qlib account를 변경하지 않는다.

### 7.5 Feedback와 resume

Current-bar fill과 account change는 이후 Qlib decision context를 통해서만 strategy에 전달한다. Next
decision은 requested target이 아니라 actual holding을 본다.

Strategy state는 run별로 isolate된다. Fresh run은 checkpoint를 명시적으로 전달하지 않으면 fresh state에서
시작한다. Resume와 uninterrupted execution은 같은 observable decision, order, fill, position, cash와
result identity를 만들어야 한다.

## 8. Signed alpha research

### 8.1 Canonical alpha result

Atomic alpha의 canonical result는 underlying instrument의 ticker-level signed signal 또는 signed active
weight다. Synthetic execution asset은 alpha ranking, normalization 또는 research universe에 포함하지
않는다.

Alpha result는 다음을 포함한다.

- Signal 또는 weight artifact
- Long, short, gross와 net exposure
- Coverage와 missingness
- Turnover와 cost diagnostics
- Information-availability audit
- Evaluation segment와 metric
- Optional intermediate weight snapshot

### 8.2 Built-in signal tool

Agent가 common research operation을 project마다 다르게 다시 작성하지 않도록 qlibx는 deterministic
implementation을 제공한다.

Initial built-in set:

- Cross-sectional rank, demean과 z-score
- Winsorization과 clipping
- Market 또는 cross-sectional demean
- Industry와 sector group demean
- Factor data가 있을 때 beta estimation과 residualization
- Lag와 rolling statistics
- Linear signal decay
- Hump 또는 barrier function
- Top/bottom selection과 per-name cap
- Fixed dollar-neutral과 flexible-budget rescaling/validation
- Matrix alignment, coverage, missingness와 no-look-ahead check

각 operation은 axis, tie behavior, NaN behavior, minimum observation, group-missing behavior, dtype,
parameter semantics와 **required data**를 문서화한다. Operation ID와 version은 result lineage에 포함한다.

이 목록의 대부분은 signal matrix 하나만 있으면 동작하지만 일부는 추가 registered data를 요구한다.
Industry/sector group demean은 point-in-time group label을 요구하고, beta estimation과 residualization은
market 또는 factor return을 요구한다. 이런 operation은 section 5.4의 형식으로 requirement를 선언해야 하며,
요구가 충족되지 않으면 section 5.5의 requirement gap을 보고한다.

Required data가 없는 operation을 신호만으로 실행하거나, 요구된 data를 유사한 다른 dataset으로 대체해서는
안 된다. Operation의 requirement 선언은 `qlibx` 설치본에서 조회할 수 있어야 하며, agent는 이를 근거로
section 4.8의 절차를 시작한다.

### 8.3 Neutralization과 exposure measurement

Mandatory neutrality mode는 없다. Raw signed signal도 valid result다. User는 research objective에 따라
market demean, industry demean, beta residualization 또는 custom transform을 적용할 수 있다.

이 transform을 적용했다는 사실이 exact market-neutral 또는 sector-neutral을 보장하지 않는다. Missing
data, factor-estimation error, selection, cap, rebalance timing과 execution 때문에 residual exposure가 남을
수 있다.

필요한 market, benchmark, industry 또는 factor data가 등록되어 있으면 built-in exposure analysis는
다음을 계산할 수 있어야 한다.

- Long, short, gross와 net exposure
- Market 또는 benchmark beta/exposure
- Industry와 sector exposure
- User-supplied factor exposure
- Intended weight와 realized holding의 exposure 차이

이 목록의 각 항목은 서로 다른 registered data를 요구한다. Long/short/gross/net exposure와 coverage는
weight만으로 계산되지만, market 또는 benchmark exposure는 해당 beta 또는 return을, industry/sector
exposure는 point-in-time group label을, factor exposure는 factor data를, intended-realized gap은 realized
holding을 요구한다.

요청된 항목의 required data가 없으면 exposure analysis는 그 항목을 **조용히 생략하지 않는다**. 계산하지
못한 항목, 그 이유와 필요한 data를 결과에 명시적으로 기록하고, section 5.5의 형식으로 requirement gap을
보고한다. 계산된 항목만 담긴 결과를 완전한 exposure analysis로 표시해서는 안 된다.

예를 들어 OHLCV 가격만 등록된 project에서 market beta exposure를 요청하면, analyzer는 beta를 임의로
추정하거나 해당 필드를 비워 둔 채 성공을 반환하지 않고, market return이 필요하다는 사실과 이를 충족하는
alternative(등록된 index return, 또는 market capitalization과 return으로부터의 cap-weighted 계산)를 보고한다.

Exposure artifact에는 analyzer ID/version, input과 dataset ID, estimation window, method, coverage,
missingness와 계산하지 못한 항목의 requirement 정보를 기록한다. Compatible project-local analyzer가
built-in analyzer를 보완하거나 교체할 수 있다.

### 8.4 Fixed budget과 flexible budget

Default는 research convenience를 위한 fixed dollar-neutral rescale다. 양쪽에 feasible candidate가 있으면:

```text
sum(long weights)  =  1
sum(short weights) = -1
```

Flexible budget은 각 side budget을 반드시 사용해야 할 amount가 아니라 maximum으로 취급한다.

```text
0 <= sum(long weights)   <= 1
-1 <= sum(short weights) <= 0
```

Candidate scarcity, truncation, signal strength 또는 StrategyAgent decision에 따라 budget을 사용하지 않을
수 있다. Candidate가 없는 side는 0일 수 있다.

Generic downstream module은 이 intent를 보존해야 한다. 각 side를 full budget으로 silent rescale하거나,
ensemble 전에 member gross exposure를 복원하거나, residual budget을 unrelated security에 배분해서는 안
된다. Explicit strategy 또는 ensemble rule이 weight를 재배분할 수는 있지만, before/after result와 rule을
관측할 수 있어야 한다.

### 8.5 Weight snapshot

Strategy는 selection, transform, truncation, budget adjustment, ensemble 또는 execution 전후에 signed
weight snapshot을 기록할 수 있다. Snapshot에는 date, strategy ID, snapshot name, sequence, signed
weights, long/short/gross/net exposure, leftover budget과 strategy metadata가 포함된다.

Snapshot logging을 켜거나 꺼도 final strategy result가 달라져서는 안 된다.

## 9. Research workspace and centralized catalog

### 9.1 qlibx-research/를 scratchpad로 사용

Agent는 선택된 research root, 예를 들어 `qlibx-research/`를 temporary script, note, table과 diagnostics를 위한
scratchpad로 사용할 수 있다. Scratch file은 canonical research record가 아니다.

각 session은 isolated workspace를 가진다. 완료 시 agent는 다음을 포함하는 organized research artifact를
남긴다.

- Research question과 hypothesis
- Referenced dataset, strategy와 사용한 implementation identity
- Proposal과 run ID
- Key comparison과 result
- Success, failure, rejection 또는 follow-up decision
- Nearest prior work와 다른 점
- Catalog에 등록된 canonical artifact reference

Possible layout:

```text
research/
  sessions/<session-id>/scratch/
  artifacts/<research-id>/
```

이것은 example이며 mandatory directory structure가 아니다.

### 9.2 Centralized file database

Alpha research record는 하나의 project-local, file-backed catalog에 모아야 한다. 여러 session이 동시에
publish하더라도 user와 agent에게는 하나의 queryable database로 보여야 한다.

Catalog는 다음을 저장하거나 reference한다.

- Dataset snapshot과 effective config
- Proposal과 hypothesis
- Alpha definition과 parameter
- Successful, failed, invalid와 incomplete run
- Model, signal, weight, ensemble, portfolio와 backtest artifact
- Exposure, performance, turnover와 cost result
- Parent/child와 supersede lineage
- Promotion, rejection과 diagnostic decision
- Research session과 agent identity

Storage engine과 atomic-write implementation은 architecture decision이다. 이 PRD는 observable catalog
behavior를 정의한다.

### 9.3 Identity와 reuse

Alpha definition, alpha run, model run, ensemble run, portfolio run과 backtest run은 서로 다른 identity를
가진다.

- Backtest-only change는 compatible alpha result를 재사용할 수 있다.
- Ensemble은 strategy를 다시 실행하지 않고 stored member alpha를 사용할 수 있다.
- Report는 original strategy를 load하지 않고 stored backtest artifact를 사용할 수 있다.
- Dataset 또는 transitive parent가 바뀌면 dependent identity가 달라진다.
- Corrupt 또는 provenance-conflicting content는 verified complete artifact로 반환하지 않는다.

### 9.4 Trial 이전 research context

Agent는 새 trial을 제안하기 전에 다음 bounded context를 조회할 수 있다.

- Registered와 superseded alpha
- Successful, failed와 invalid trial
- Searched parameter range
- Active proposal
- Nearest semantic/empirical neighbor
- Available dataset snapshot과 known time limitation
- Required comparison set과 research gap

이 context를 얻기 위해 모든 historical scratch file을 읽을 필요가 없어야 한다.

### 9.5 Orthogonality

Alpha candidate는 세 level에서 평가한다.

1. Semantic: mechanism, input, clock, horizon, operation, neutralization과 search-space overlap
2. Empirical: signal, holding, return, exposure, turnover, trade와 regime stability
3. Incremental: residual signal quality, cost-aware marginal return/IR, risk, concentration과 capacity

Low PnL correlation만으로 independence를 인정하지 않는다. Parameter, sign, scale 또는 neutralization
variation과 genuinely separate alpha family를 구분해야 한다.

Result에는 reference pool, evaluation segment, missing comparison, metric과 threshold를 기록한다.

### 9.6 Proposal과 decision record

Bounded proposal은 다음을 명시한다.

- Hypothesis와 mechanism
- Logical dataset
- Observation clock과 holding horizon
- Strategy, transform과 parameter range
- Evaluation segment와 comparison set
- Cost와 capacity assumption
- Stopping condition과 search limit

Promotion, rejection, diagnostic retention과 supersede decision은 evidence run, decision criteria, reviewer
identity와 rationale을 reference한다. Failed trial도 이후 agent가 조회할 수 있어야 한다.

### 9.7 Parallel-agent behavior

Same-branch, no-worktree operation이 default다. Product는 다음을 보장한다.

1. 각 agent는 distinct research session과 workspace ID를 받는다.
2. Effective config, dataset snapshot, component version과 seed는 run start에 고정된다.
3. 다른 agent의 이후 edit은 해당 run을 변경하지 않는다.
4. 서로 다른 strategy와 proposal을 concurrent하게 실행할 수 있다.
5. Duplicate content는 반복 저장하지 않고 duplicate로 식별한다.
6. 다른 content가 같은 identity를 claim하면 conflict로 실패한다.
7. Idempotent request의 retry는 duplicate result를 만들지 않는다.
8. Incomplete publication은 complete result로 보이지 않는다.
9. Crashed agent는 다른 session 또는 completed result를 손상시키지 않는다.
10. Stale promotion 또는 update는 명시적으로 실패한다.

User와 agent는 lock 또는 atomic file replacement mechanism을 선택하지 않는다. 그것은 이 behavior를
만족해야 하는 implementation detail이다.

## 10. Ensemble and enhanced index

### 10.1 Stored-alpha ensemble

Ensemble은 verified stored alpha artifact를 input으로 사용하며 요구되지 않는다면 member strategy를 다시 실행하지 않는다.

```text
stored member signed weights
-> member의 actual flexible exposure 보존
-> ticker alignment
-> same-ticker opposite intent netting
-> combined signed active intent
```

다른 ticker의 opposite exposure는 자동 netting하지 않는다. Member gross exposure를 silent하게 복원하지
않는다.

Ensemble result는 다음을 제공한다.

- Member alpha와 run ID
- Member coefficient와 effective weight
- Ticker-level contribution과 netting
- Combined signed signal 또는 weight
- Exposure와 budget diagnostics
- Member similarity와 marginal contribution
- Full parent lineage

Ensemble 자체가 StrategyAgent가 되어 prior evidence로 member allocation을 변경할 수도 있다. 이 경우에도
bounded context, deterministic input/result와 no-account-side-effect requirement를 따른다.

### 10.2 Enhanced index construction

Ensemble은 benchmark-relative active intent를 나타낸다. Enhanced index constructor는 이를 현재 지원하는
stock, ETF와 cash로 구현되는 long-only portfolio로 변환한다.

```text
benchmark constituent exposure
+ signed active intent
-> desired total constituent exposure
-> stock / ETF / cash physical target
```

Input:

- Benchmark member와 weight
- Signed active intent
- Current actual holding과 cash
- Stock/ETF price, lot와 tradability
- Available한 경우 point-in-time ETF/index constituent exposure
- Cost
- Hard/soft constraint

Result:

- Desired active와 total constituent exposure
- Stock, ETF와 cash target
- Look-through exposure
- Constraint residual과 binding constraint
- Solver status와 infeasibility reason
- Expected trade, cost와 tracking diagnostics

Hard infeasibility, soft-constraint relaxation과 solver failure는 서로 다른 result다. Unknown instrument와
incompatible exposure axis를 silent하게 제외하지 않는다.

Qlib의 기본 enhanced-index 기능은 ETF를 하나의 physical instrument로 보유할 수 있지만 ETF 내부
constituent exposure를 자동으로 인식하지 않는다. ETF look-through constraint와 attribution에는 별도의
point-in-time constituent dataset과 qlibx exposure 계산 기능이 필요하다.

### 10.3 Physical instrument와 ETF look-through

Qlib API는 `stock_id`라는 이름을 널리 사용하지만 실제 Position은 instrument ID별 amount, price와 weight를
보유하는 구조다. Qlib Account 자체가 asset-class semantics, ETF constituent 또는 look-through exposure를
관리하지는 않는다.

qlibx는 다음 contract를 제공한다.

- 현재 지원하는 financial instrument는 stock과 ETF다.
- Qlib Account와 Position은 실제로 거래하고 보유한 physical instrument ID와 quantity의 source다.
- ETF는 core에 고정된 특별한 passive sleeve가 아니라 지원되는 instrument type 중 하나다.
- ETF constituent를 몰라도 ETF를 opaque instrument로 거래하고 하나의 자산처럼 research할 수 있다.
- Look-through가 필요할 때만 별도의 point-in-time ETF constituent 또는 index constituent logical
  dataset을 구독한다.
- ETF physical quantity와 physical weight는 Qlib Account에서 가져오고, constituent-level exposure는
  해당 holding과 별도 constituent dataset을 결합하여 계산한다.
- Physical portfolio와 constituent-level look-through exposure는 별도의 result로 유지한다.
- Constituent dataset이 없으면 qlibx는 look-through exposure를 추측하거나 생성하지 않는다.
- Instrument type별 price, lot, cost와 execution behavior는 명시적인 metadata와 contract를 사용한다.

Bond, futures와 다른 instrument는 future roadmap이다. 새로운 instrument를 추가할 때 상품별 valuation,
trading unit, expiry, settlement와 cost behavior를 확장할 수 있어야 하지만 현재 stock/ETF requirement에
미구현 상품의 lifecycle을 섞지 않는다.

### 10.4 Flexible-budget financing

Unused flexible alpha budget을 unrelated active stock bet으로 전환하지 않는다. Enhanced index result는
다음을 구분한다.

- Benchmark 또는 passive-sleeve exposure
- ETF exposure
- Cash residual
- Constraint 때문에 구현하지 못한 active exposure

Fixed-budget counterfactual과 flexible-budget actual portfolio를 비교하고 selection effect, budget timing,
passive residual과 implementation effect를 구분할 수 있어야 한다.

## 11. Qlib execution and signed-alpha compatibility

### 11.1 Qlib을 통한 realized execution

Physical target은 Qlib의 actual execution lifecycle을 통과한다.

- Weight target을 booksize, price와 lot rule에 맞는 quantity로 변환한다.
- Stock과 ETF에 다른 cost를 적용할 수 있다.
- Suspension, price limit, volume participation, cash와 lot constraint를 적용한다.
- Order와 fill은 requested/dealt quantity, clipping stage와 reason을 제공한다.
- Partial fill 이후 next optimizer와 StrategyAgent는 actual holding을 본다.
- Cash와 marked holding은 Qlib account에 reconcile된다.

### 11.2 matched-capitalization이 필요한 이유

Qlib의 official stock `Position`과 `Account` contract는 long-only이며 negative stock quantity를 native하게
지원하지 않는다. 따라서 qlibx는 Qlib을 fork하지 않고 signed alpha를 실행하고 audit하기 위한 명시적
compatibility hack으로 `matched_capitalization`을 제공한다.

이 mode는 Qlib이 native short를 지원한다고 주장하지 않는다. Qlib account에는 non-negative composite
position만 유지하고, matched baseline inventory를 기준으로 signed active quantity를 복원한다.

예를 들어 active position `-20주`가 필요하면 baseline inventory `30주`를 먼저 부여하고 Qlib에서 실제
underlying `20주`를 매도한다. Qlib이 보는 composite position은 `10주`로 non-negative지만 qlibx가
재구성하는 active position은 `10 - 30 = -20주`다. Cover는 실제 Qlib `BUY` order로 실행한다.

### 11.3 Accounting contract

각 ticker에서:

```text
A = realized signed active quantity
B = matched baseline/endowment quantity, B >= 0
C = Qlib composite quantity, C >= 0

C = B + A
A = C - B
```

Initial funding은 active strategy booksize와 short capacity를 위한 baseline funding reserve로 나눈다.
Qlib account는 `C`를 소유한다. Baseline record는 `B`와 matching cash를 추적한다. Independent signed
execution ledger는 없다.

### 11.4 Endowment와 actual SELL

Negative intent를 Qlib에서 실제로 실행할 필요가 생기면:

1. Active pre-trade NAV, configured per-name short cap, safety multiplier, execution price와 lot size로 required
   baseline quantity를 정한다.
2. Missing baseline quantity를 같은 execution-time price로 Qlib composite position과 baseline record에
   endow한다.
3. Matching notional을 baseline reserve cash에서 debit한다.
4. 이 event는 exchange fill이 아닌 zero-cost capitalization이므로 market volume, commission과 tax를
   사용하지 않는다.
5. Matching quantity와 cash change가 동시에 일어나 composite NAV와 active NAV가 변하지 않는다.
6. Qlib에는 negative signed target이 아니라 `C_target = B + A_target`을 제출한다.
7. Economic active short는 Qlib exchange를 통과하는 actual underlying `SELL`이다.
8. Partial fill 또는 blocked trade 이후 signed holding은 `A_realized = C_realized - B`로 복원한다.

Baseline lifecycle은 dynamic universe와 actual fill을 따라야 한다.

- 새로운 short instrument에 필요한 baseline은 그 instrument가 실제로 필요해진 시점에 추가한다.
- Universe에서 제외되어 cover target이 생겨도 BUY가 blocked되었다면 realized short가 남아 있으므로
  필요한 baseline을 유지한다.
- Actual cover fill 이후에만 불필요한 baseline을 matching cash와 함께 NAV-neutral하게 release한다.
- `retained` policy는 re-entry를 위해 baseline을 계속 보유한다.
- `active-short-only` policy는 열린 active short를 표현하는 데 필요한 baseline만 유지하여 reserve 누적을
  줄인다.

Funding reserve가 부족하거나 `C_target < 0`이면 명시적으로 실패한다.

아직 observed되지 않은 ticker는 baseline과 composite position이 모두 0이다. Qlib dealt quantity가
realized execution의 source이며 별도 signed fill ledger를 advance해서는 안 된다.

### 11.5 Observable account와 performance

Result는 다음을 제공한다.

- Intended signed weight와 quantity
- Baseline quantity/cash before and after
- Activation, top-up과 release event
- Qlib requested/dealt quantity와 blocked reason
- Composite와 reconstructed signed closing quantity
- Composite, baseline과 active account reconciliation
- Cost, turnover와 PnL

Composite account에는 baseline endowment가 포함되므로 standard return을 canonical signed-alpha return으로
사용하지 않는다. Active performance는 active booksize를 denominator로 사용하고 baseline price movement를
제거하여 active PnL과 reconcile한다.

### 11.6 Compatibility limitation

Matched-capitalization은 native short가 아니라 Qlib long-only contract 안에서 signed active holding을
재구성하는 compatibility hack이다.

- Borrow, locate, recall, margin과 forced buy-in을 자동으로 모델링하지 않는다.
- Short borrow fee와 securities-lending capacity를 자동으로 재현하지 않는다.
- Baseline inventory를 위한 사전 reserve가 필요하고 reserve가 부족하면 새로운 short를 실행할 수 없다.
- Qlib composite account return은 signed active strategy return과 같지 않으므로 별도 reconciliation이
  필요하다.
- Universe 교체가 잦으면 baseline activation, retention, release와 reserve 사용이 증가한다.
- Corporate action, delisting과 normalized execution/valuation input이 잘못되면 reconstructed active
  quantity와 PnL도 잘못된다.
- Qlib composite position을 non-negative로 유지할 수 없거나 account reconciliation이 맞지 않으면
  실행을 실패시킨다.

## 12. Composable module, artifact and reporting

### 12.1 Extension point

Project-local code를 qlibx workflow에 삽입하거나 built-in behavior와 조합할 수 있는 extension capability는
qlibx의 핵심 기능이다. User가 작성한 Strategy가 qlibx의 data, decision, Qlib execution과 recording
workflow 사이에 들어가 실행되는 것 자체가 대표적인 extension이다. 이 capability는 installed qlibx,
Qlib 또는 site-packages를 수정하지 않고 사용할 수 있어야 한다.

이 PRD는 아직 지원할 extension point의 전체 목록, taxonomy, discovery mechanism 또는 config/programming
interface를 확정하지 않는다. 이 결정은 각 workflow contract와 함께 설계해야 하며 임의의 목록을 public
contract로 고정해서는 안 된다.

대신 실제 product version이 제공하는 모든 extension point는 version-matched documentation에서 정확히
discoverable해야 한다. 각 extension point의 documentation은 최소 다음을 설명한다.

- Extension의 목적과 workflow에서 호출되는 위치
- Extension이 registered data를 요구하는 경우 section 5.4 형식의 requirement 선언
- Required input의 type, schema, axis, unit, data semantics와 time-access boundary
- Required output의 type, schema, semantics와 downstream consumer
- 호출 lifecycle, state와 허용되는 side effect
- Error, validation과 incompatible output behavior
- Built-in과 local implementation의 compatibility 조건
- Composition 가능 여부와 다른 extension 또는 artifact와의 관계
- Agent가 실행하고 검증할 수 있는 minimal example

이 정보는 사람용 설명에만 존재해서는 안 된다. Installed help와 schema에서 조회할 수 있어야 하며,
generated coding-agent skill에도 직접 포함되거나 정확한 version-matched resource로 연결되어야 한다.
Agent는 extension input/output을 source code에서 추측하지 않고 이 public contract만으로 local code를 작성,
연결하고 검증할 수 있어야 한다.

### 12.2 Project-local extension

qlibx는 하나의 extension directory를 강제하지 않는다. `.qlibx/extensions/`, `qlibx-custom/`, 다른
project directory 또는 installed organization package를 사용할 수 있다.

Local extension을 발견하고 선택하고 연결하는 구체적인 방식은 해당 extension point의 public contract가
정한다. 모든 extension에 하나의 ID, registry, base class, directory layout 또는 registration mechanism을
강제하지 않는다.

Product는 실제로 제공하는 extension contract에 맞는 authoring guidance, scaffold가 필요한 경우의
scaffold, validation과 failure behavior를 제공한다. Local code가 required input/output 또는 time-access
boundary를 만족하지 않으면 verified run에 사용하기 전에 명확히 실패해야 한다.

### 12.3 Stored artifact와 record capability

Public workflow boundary는 다른 module의 private Python object 또는 live process memory를 요구하지
않는다. 각 stage는 input과 output을 serialize하고 reload할 수 있어야 한다.

Strategy, transform, optimizer와 execution component는 실행 중 필요한 지점에서 named intermediate
result를 record할 수 있어야 한다. Record된 값은 run-local physical file로 materialize되며 live Strategy
또는 Qlib process 없이 다시 읽을 수 있어야 한다. Standard signal, target, order, fill, position과
account뿐 아니라 strategy-defined intermediate result도 기록할 수 있다.

PRD는 recordable Python type 또는 serializer 목록을 제한하지 않는다. 필요한 결과는 저장된 payload의
의미와 loader가 명확하고, agreed artifact schema를 통해 downstream consumer가 독립적으로 읽을 수
있다는 것이다.

Artifact envelope:

- Artifact type과 schema version
- Stable artifact/run ID
- Producer를 lineage에서 식별하고 재현하는 데 필요한 implementation identity
- Parent와 input artifact ID
- Bounded time range
- Applicable한 axis, index, unit, currency, timezone과 data semantics
- Portable payload 또는 payload reference
- Coverage, warning, diagnostics와 completion status

Initial portable format은 metadata/config에 JSON, table/matrix에 Parquet 또는 Arrow-compatible data를
사용한다.

Downstream module은 input producer가 qlibx built-in인지 local Python file인지 알 필요가 없어야 한다.
User는 raw artifact를 export하고 qlibx 밖에서 처리한 뒤 compatible artifact를 다시 연결할 수 있다.

### 12.4 Composable reporting

Record와 reporting을 연결하는 유일한 contract는 stored artifact schema다. Reporting은 live Strategy,
model, optimizer, Qlib Account 또는 private Python object를 입력으로 요구하지 않는다.

Built-in reporting은 최소 다음을 제공한다.

- Performance와 risk summary
- Signal/weight coverage와 turnover
- Data가 있을 때 market, benchmark와 industry exposure
- Cost, order/fill과 desired-versus-realized reconciliation
- Member, ensemble과 optimizer attribution
- Matched-capitalization composite/baseline/active reconciliation

Reporting은 다음 책임을 분리한다.

1. Analysis module은 stored artifacts를 읽고 performance, exposure, attribution, turnover와 reconciliation
   등 report에 필요한 수치를 계산한다.
2. Composition layer는 여러 analysis section을 선택하고, 합치고, 분리하고, 제거하고, 순서를 바꾼다.
3. Visualization 또는 renderer는 계산된 report data를 table, chart, HTML, notebook 또는 document로
   표현한다.

수치 계산을 visualization code 안에 다시 구현해서는 안 된다. 하나의 analysis result를 여러 renderer가
재사용할 수 있어야 하며 built-in module과 project-local module을 같은 report 안에서 조합할 수 있어야
한다.

Local Python analysis module, report section과 renderer는 같은 stored artifact schema를 사용하여 built-in을
교체하거나 확장할 수 있다. Strategy, model, optimizer 또는 backtest를 다시 실행해서는 안 된다.

Reporting 과정은 새로운 canonical research artifact를 만들거나 중간 report calculation을 research
artifact store에 다시 등록하지 않는다. User가 저장을 요청한 최종 HTML, image 또는 document는 report
output이며 alpha, backtest 또는 ensemble lineage를 구성하는 artifact가 아니다. User와 agent는
reporting을 거치지 않고 raw stored artifacts를 직접 분석할 수도 있다.

## 13. Acceptance criteria

### P0 — Agent onboarding

- Installed qlibx가 version-matched help, schema, example과 agent task instruction을 제공한다.
- Onboarding action이 user content를 덮어쓰지 않고 `AGENTS.md`와 `CLAUDE.md`를 create 또는 append할 수
  있다.
- Repeated onboarding은 managed block을 duplicate하지 않고 update한다.
- Skill generation이 tool-specific 또는 selected output directory에 valid `SKILL.md` package를 만든다.
- Generated instruction과 skill이 private source를 읽지 않고 public qlibx surface를 사용하도록 안내한다.
- Generated skill이 현재 제공되는 extension point의 workflow 위치, required input/output, time boundary,
  validation과 minimal example을 포함하거나 version-matched installed documentation으로 정확히 연결한다.

### P1 — Human과 agent data journey

- Human은 qlibx 설치, agent instruction/skill 추가, `data/` file 준비 후 agent에게 registration을 요청할
  수 있다.
- Agent는 data를 read-only로 discover하고 ambiguous time, ticker 또는 value semantics를 추측하지 않는다.
- Basic registration은 availability/ticker/key와 opaque field inventory만 확정하고 capability-specific
  semantic role을 source field에 부여하지 않는다.
- Agent는 선택한 Qlib backtest가 요구하는 data와 assumption을 확인하고 source-to-Qlib mapping,
  derived field, warning과 unsupported feature를 materialization 전에 user에게 알린다.
- Capability binding은 registered dataset만 참조하고 user confirmation 뒤에만 project YAML을 변경한다.
- Basic registration은 `data/qlibx/`의 validated canonical Parquet, valid project config, logical dataset
  ID와 bounded load smoke를 만든다.
- Daily OHLCV default profile은 `t-1`까지 관측하고 `t`일 종가에 거래·평가하며, 다른 convention은
  명시적으로 등록한다.
- Source data는 변경되지 않는다.

### P2 — StrategyAgent와 no look-ahead

- 같은 bounded input, version, state와 seed는 같은 StrategyAgent result를 만든다.
- Qlib closed-loop decision/feedback ordering을 보존한다.
- Strategy instance는 class identity와 별도로 이름, ID, parameter, data requirement와 output contract를
  가진다.
- Strategy implementation은 canonical named pandas input만 받고 registration, catalog, binding YAML과 raw
  source field를 알지 못한다.
- Strategy별 required column/field가 machine-readable requirement로 선언되고 runtime 전에 confirmed
  binding으로 resolve된다.
- Strategy output은 signal, weight, order 또는 declared payload일 수 있고 intermediate result를 record할
  수 있다.
- Parent/wrapper가 child output을 composition하여 재사용하고 같은 signal logic을 반복 구현하지 않는다.
- Child strategy는 parent의 allowed lookback 밖 또는 parent decision 이후 data에 접근할 수 없다.
- Child evaluation과 ML/Bayesian what-if는 actual Qlib account를 변경하지 않는다.
- Resume와 uninterrupted run은 같은 observable result를 만든다.

### P3 — Signed alpha tool

- Raw signed alpha는 neutrality mode 없이 valid하다.
- Rank, market/industry demean, linear decay와 hump가 deterministic built-in으로 제공된다.
- Exposure analysis는 method, data, window, coverage와 missingness를 제공한다.
- Transform 사용을 exact neutrality의 증명으로 표시하지 않는다.
- Fixed/flexible budget을 지원하고 unused flexible budget을 보존한다.
- Registered data를 요구하는 operation은 required data를 선언하고 installed surface에서 조회할 수 있다.
- Required data가 없는 operation은 계산을 시도하지 않고 requirement gap을 보고한다.
- Exposure analysis는 계산하지 못한 항목을 조용히 생략하지 않고 이유와 함께 기록한다.

### P4 — Research history와 parallel agent

- Agent는 research scratchpad를 사용하면서 organized artifact와 canonical catalog record를 남긴다.
- Successful, failed, invalid와 incomplete trial을 구분한다.
- Proposal 전에 prior alpha, nearest neighbor와 searched range를 조회한다.
- Orthogonality는 semantic, empirical과 incremental result를 제공한다.
- 최소 세 agent가 worktree 없이 한 branch에서 independent session을 실행한다.
- Config edit, crash, duplicate publication과 stale update는 section 9.7 behavior를 따른다.

### P5 — Ensemble과 enhanced index

- Stored alpha member를 strategy rerun 없이 ensemble한다.
- Member weight를 ticker-level로 netting하면서 flexible exposure를 보존한다.
- Signed active intent를 benchmark-relative long-only stock/ETF/cash target으로 변환한다.
- ETF를 constituent data 없이 opaque physical instrument로 실행할 수 있다.
- Point-in-time constituent dataset이 있을 때만 ETF/index look-through exposure를 계산한다.
- Qlib Account의 physical holding과 constituent-level look-through exposure를 별도 result로 유지한다.
- Look-through constraint, cost와 solver status를 관측할 수 있다.
- Flexible residual을 unrelated active bet과 구분한다.

### P6 — Qlib signed execution

- Result가 matched-capitalization을 Qlib long-only limitation을 위한 compatibility hack으로 표시한다.
- Endowment activation은 NAV-neutral하다.
- Active short는 actual underlying Qlib `SELL`로 실행된다.
- Composite position은 non-negative이고 `A = C - B`를 만족한다.
- Partial fill은 Qlib dealt quantity를 통해서만 signed quantity를 변경한다.
- Blocked cover 뒤에는 필요한 baseline을 유지하고 actual cover fill 뒤에만 release한다.
- Insufficient baseline funding과 negative composite target은 명시적으로 실패한다.
- Active performance가 composite baseline denominator로 희석되지 않는다.
- Result가 native borrow, margin, recall과 borrow-fee model이 아님을 명시한다.

### P7 — Local module과 raw artifact

- Agent가 installed documentation과 generated skill만으로 available extension contract를 찾고 required
  input/output을 만족하는 local code를 작성할 수 있다.
- Agent가 installed qlibx를 수정하지 않고 exponential decay를 local Python transform으로 추가한다.
- Local exposure analyzer 또는 reporter가 같은 artifact contract로 built-in을 교체한다.
- Complete stage result를 documented portable format으로 export할 수 있다.
- Strategy가 선택한 intermediate result를 physical stored file로 record한다.
- User가 built-in report 없이 raw Qlib backtest artifact를 사용할 수 있다.
- Stored artifact에서 report를 만들 때 research를 다시 실행하지 않는다.
- Analysis calculation과 visualization을 분리하고 여러 report section과 renderer를 조합할 수 있다.
- Reporting은 새로운 canonical research artifact를 만들지 않는다.

### P8 — Capability requirement와 resolution interview

- Registered data를 요구하는 모든 capability가 section 5.4 형식의 requirement를 선언한다.
- Agent가 capability를 실행하지 않고 requirement와 acceptable derivation alternative를 조회할 수 있다.
- 실행 전 read-only plan과 실행 시점 error가 같은 requirement 선언에서 같은 판정을 만든다.
- Requirement가 충족되지 않으면 capability는 계산을 시도하지 않고 requirement gap을 보고한다.
- Requirement gap은 미충족 requirement, 이유, alternative와 next command를 포함하고,
  capability-specific plan은 registered field inventory 같은 interview 근거를 제공한다.
- OHLCV 가격만 등록된 project에서 beta residualization을 요청하면 market return requirement와 그
  alternative를 보고하고, beta를 추정하거나 해당 항목을 비워 둔 채 성공을 반환하지 않는다.
- Optional requirement 미충족으로 계산하지 못한 결과 항목이 이유와 함께 결과에 기록된다.
- Generated skill이 requirement gap을 받았을 때 수행할 resolution interview 절차를 포함한다.
- Agent가 gap 해소를 위한 registration을 완료한 뒤 같은 요청을 다시 실행하여 성공한다.
- Agent가 user 확인 없이 alternative를 선택하거나 유사한 dataset으로 대체하지 않는다.
- Registered field와 canonical strategy role 사이의 candidate mapping은 user confirmation 전에는
  requirement를 충족하지 않으며 config를 변경하지 않는다.
- `open_close_rebound`가 `open_price`와 `close_price`를 요구하고 registered OHLCV가 `시가`와 `종가`를
  제공하는 경우, agent가 exact mapping을 user에게 확인받아 binding YAML을 작성한 뒤에만 같은 strategy
  요청이 canonical pandas input으로 성공한다.
- Project-local extension도 같은 형식으로 requirement를 선언할 수 있다.

## 14. Working prototype reference

`qlib-integration-codex`는 qlibx implementation을 위한 working prototype과 reference다. qlibx의 product
definition, package layout, migration source 또는 public naming model이 아니다.

이미 동작을 증명한 부분을 구현할 때 해당 code와 Goal test를 참고한다.

- Qlib feedback timing, partial fill, actual holding과 account reconciliation
- Dataset별 lookback과 StrategyAgent memory
- Universe entry/exit, blocked liquidation과 re-entry
- Lot rounding, stock/ETF cost와 checkpoint/resume
- Stored alpha reuse, ensemble, enhanced index construction과 reporting
- Look-through optimization과 explicit solver outcome
- Qlib ML train-only fitting과 purge/embargo behavior
- Matched-capitalization signed execution과 active performance

qlibx requirement의 기준은 이 PRD다. Prototype은 evidence와 reusable reference code이며, prototype의
accidental structure를 유지해야 하는 constraint가 아니다.

## 15. Future roadmap: AI를 사용하는 user-defined Strategy

qlibx는 AI agent runtime이 아니라 human과 AI coding agent가 사용하는 alpha research tool이다. Model
provider, prompt, token/cost, tool call, retry, rate limit과 model failure handling은 qlibx의 product
responsibility가 아니다.

향후 user-defined Strategy는 외부 AI agent 또는 model을 내부 decision logic으로 사용할 수 있다. 이
경우에도 qlibx는 별도의 AI lifecycle을 만들지 않고 기존 Strategy contract만 적용한다.

- AI를 사용하는 Strategy도 parent decision에 허용된 bounded lookback 밖의 data를 볼 수 없다.
- News, filing, transcript와 research note 같은 text data는 다른 logical dataset과 같이 point-in-time
  availability를 가진 subscription으로 제공할 수 있어야 한다.
- Child strategy가 AI를 사용하더라도 parent의 data boundary를 확장할 수 없다.
- Qlib account에는 Strategy가 반환한 declared decision만 제출하며 historical child evaluation은 account를
  변경하지 않는다.
- Strategy가 선택하여 record한 결과는 다른 intermediate result와 같은 stored artifact contract를 따른다.
- Provider-specific execution, prompt 관리와 AI runtime의 재현성은 해당 user-owned Strategy 또는 외부
  runtime의 책임이다.

이 roadmap의 목적은 qlibx 자체에 AI를 내장하는 것이 아니라, lookback boundary, Strategy composition,
recordability와 Qlib execution isolation을 유지하면서 AI를 사용하는 local Strategy도 연결할 수 있게
하는 것이다.
