# qlibx module map

> Snapshot: 2026-08-11. 이 문서는 현재 `src/qlibx/`를 제품 역할로 번역한다. 파일 위치는 current implementation이고,
> execution spine, exact lookback/Strategy v4, declared account history와 explicit strategy state까지 반영한 snapshot이다.

## 큰 구조

```text
Public API / composition root
  qlibx.__init__ + QlibxProject
        |
Application orchestration
  flow/*
        |
Pure or bounded domain work
  contracts/* + portfolio/* + execution/* + analysis/*
        |
Read authority and state authority
  view/* + data/* + account/* + evidence/* + runtime/*
```

이 구조의 핵심 패턴은 다음과 같다.

- **Dependency Injection**: `QlibxProject`와 Flow가 concrete dependency를 생성자에서 명시적으로 조립한다.
- **Inversion of Control**: Flow가 clock/event 순서를 소유하고 user Strategy callback을 호출한다. Strategy가 runtime을 돌리지 않는다.
- **Functional Core / Imperative Shell**: 계산 component는 typed result를 만들고, Flow가 artifact publication, Account commit과 strategy-state 전달을 수행한다.
- **Aggregate Root**: `Account`가 actual cash, Position과 committed journal의 쓰기 권한을 가진다.
- **Command-Query Separation**: Strategy/Monitor는 immutable View로 읽고, Flow만 commit command를 호출한다.
- **Strategy Pattern**: public run 호출에 주입한 `BaseExchange` concrete implementation으로 execution algorithm을 교체한다. KRX와 Academic의 경제적 의미까지 하나로 합친다는 뜻은 아니다.

## Directory responsibility

| path | 현재 책임 | 큰 흐름에서의 위치 |
|---|---|---|
| `project.py` | public facade, project open/init, operation별 composition root, catalog-session boundary | 사용자가 시작하는 최상위 API |
| `flow/` | use-case orchestration, requirement resolution, event ordering, artifact publication, Account commit, strategy-state/history projection | application layer이자 imperative shell |
| `specs/` | daily, constraint와 academic run의 frozen public input | public configuration contract |
| `view/` | Strategy/Model/Monitor에 허용된 read capability만 주는 records, scoped View와 ViewGate | least-authority query boundary |
| `data/` | dataset registration, requirement binding, timezone/PIT normalization, deterministic versioned query snapshot, source fingerprint와 observation read | observation authority |
| `contracts/` | 사용자가 구현하는 계약: `strategy.py`(StrategyOperation), `model.py`(ResearchModel), `artifacts.py`(artifact I/O)와 built-in calculation | user logic 및 pure calculation boundary |
| `portfolio/` | construction, adjustment, validation의 typed calculation | standalone operation과 KRX execution preparation이 공유하는 pure calculation |
| `execution/` | generic Exchange/preparation lifecycle, KRX/Academic concrete preparation/request/result, Instrument와 sizing/matching | market-specific execution mechanics와 pure request preparation |
| `account/` | Account aggregate와 legacy checkpoint schema | committed actual state authority |
| `account_history.py`, `strategy_state.py` | declared recording/requirement types와 strict JSON state normalization | Strategy input contract |
| `evidence/` | typed artifact envelope와 local JSON/DuckDB backend | durable result/lineage authority |
| `analysis/` | typed analysis session/result와 renderer support | committed artifact를 읽는 downstream read model |
| `extensions/` | project-local module validation, fingerprint, registration/loading | local Strategy/transform extension boundary |
| `runtime/` | aware clock와 시간 불변식 | deterministic runtime primitive |
| `config/` | project configuration schema | composition input |
| `resources/` | installed samples와 bundled agent skill | package consumer evidence/onboarding asset |

> Future production/OMS boundary는 더 이상 빈 package로 표현하지 않는다. 부재는 코드가 아니라
> `docs/qlibx-prd.md` §14와 `docs/oms-future-plans.md`가 기술한다.

### `contracts/` · `extensions/` · `flow/`를 구분하는 법

이름이 비슷해 보이지만 세 층은 서로 다른 질문에 답한다.

| directory | 답하는 질문 |
|---|---|
| `contracts/` | 사용자가 **무엇을** 구현하는가 (Strategy protocol, ResearchModel protocol, artifact I/O) |
| `extensions/` | 사용자가 쓴 파일을 **어떻게** 검증·등록·적재하는가 (fingerprint, registration) |
| `flow/` | 그것들을 **언제 어떤 순서로** 호출하는가 (event ordering, commit, publication) |

## Root-level modules

| module | 의미 |
|---|---|
| `__init__.py` | 의도적으로 노출한 public imports와 CLI `main` |
| `domain.py` | 여러 layer가 공유하는 core typed value/result |
| `models.py` | 공통 Pydantic model base/serialization 규칙 |
| `errors.py` | typed `OperationError`, `OperationOutcome`, status |
| `onboarding.py` | agent instruction/skill installation lifecycle |
| `sample.py` | bundled sample discovery/materialization |
| `cli.py` | CLI argument parsing과 public operation routing |

## `flow/`를 읽는 방법

`flow/`는 “도메인 객체 모음”이 아니라 **use case별 application service**다.

| flow | 수행하는 use case |
|---|---|
| `research.py` | direct Strategy invocation과 result promotion |
| `model.py` | optional Model/intermediate artifact materialization |
| `daily.py` | explicit daily events, decision/execution/mark/monitor ordering, KRX Account commit, account-history recording과 strategy-state 전달 |
| `academic.py` | separate hypothetical signed execution와 final checkpoint |
| `composition.py` | stored StrategyResult/Signal을 소비하는 Ensemble/stored-signal Strategy |
| `portfolio.py` | stored weight를 physical construction result로 변환 |
| `constraints.py` | standalone adjustment와 validation |
| `monitoring.py` | committed Account checkpoint의 independent constraint observation |
| `analysis.py` | signal/simulation/monitoring artifact 분석과 report render |
| `strategy_extensions.py`, `extensions.py` | local module 검증/등록/실행 |
| `artifact_inputs.py`, `strategy_results.py` | producer-independent artifact contract와 result promotion helper |
| `account_history.py`, `failures.py` | Flow-owned actual-history recording과 shared typed failure helper |

`daily.py`가 큰 이유는 event ordering, Account commit, state propagation과 evidence가 한곳에 있기 때문이다. 파일 크기만으로 쪼개면 control
flow가 더 숨을 수 있다. 먼저 `ExecutionPreparation`이라는 실제 responsibility seam을 추출한 뒤 추가 분리를 판단한다.

## 현재 semantic layout

```text
src/qlibx/
  # 사용자가 선언하는 것
  config/           # project configuration schema
  specs/            # daily, constraints, academic public frozen specs
  data/             # dataset registration + versioned query snapshot + PIT store

  # 사용자가 작성하는 것
  contracts/
    strategy.py      # StrategyOperation, StrategyDraft, StrategyResult
    model.py         # ResearchModel, ForwardReturnLabelModel
    artifacts.py     # Strategy/Model artifact I/O contracts
  extensions/       # project-local module validation, fingerprint, registration

  # 실행 기계
  runtime/          # aware clock, Event
  view/             # records, scoped views, ViewGate
  execution/
    base.py          # BaseExchange[RequestT, ResultT]
    preparation.py   # generic lifecycle + concrete KRX/Academic preparation
    krx.py           # KrxExchange physical semantics
    academic.py      # AcademicExchange hypothetical semantics
  account/          # Account aggregate + legacy checkpoint schema
  account_history.py
  strategy_state.py # declared actual history + explicit JSON state contracts
  portfolio/        # construction/constraint pure functions
  flow/             # internal orchestration

  # 결과
  evidence/         # artifact envelope + local catalog backend
  analysis/         # analysis/report contracts
```

기존 `simulation.py`, `constraints.py`, `academic.py`, `context/`, `operations/`, `kernel/`, `production/`은
제거했고 compatibility shim도 두지 않았다. 지원되는 consumer import는 `from qlibx import ...`이며
내부 source와 bundled resource를 같은 변경에서 전환한다.

`materialize`는 **동사**로 유지한다(`QlibxProject.materialize()`, PRD의 "materialized research data").
그 행위를 수행하는 **행위자**만 Model 어휘를 쓴다(`ResearchModel`, `ForwardReturnLabelModel`, `ModelView`).
`SampleMaterializer`는 sample 파일 materialization이라는 별개 개념이므로 이 어휘에 포함되지 않는다.

이 위치는 새 범용 `engine/`, `stages/`, `plugins/`, `journal/` hierarchy를 만들지 않는다. Interrupted-run recovery는
current scope에 두지 않는다. Exact rows/calendar lookback은 execution이 아니라 `data/contracts.py`, `data/requirements.py`,
`data/store.py`, `view/views.py`를 관통하는 data-access contract다. Latest execution result는 execution evidence를
재사용해 `StrategyView`의 최소 query와 access lineage로 구현한다.

## 사용자가 보는 semantic route

| 사용자의 질문 | 먼저 볼 public API | 내부 route |
|---|---|---|
| 데이터를 등록하고 Strategy를 실행하려면? | `QlibxProject.register_dataset()`, `invoke()` | `data/` -> `view/` -> `flow/research.py` -> `contracts/` -> `evidence/` |
| 중간 signal/label을 저장하려면? | `materialize()` | `flow/model.py` -> `contracts/model.py` -> `evidence/` |
| KRX daily backtest를 돌리려면? | `run_daily()` | `specs/daily.py` -> `flow/daily.py` -> `execution/` -> `account/` -> `evidence/` |
| Academic long-short를 평가하려면? | `run_academic()` | `specs/academic.py` -> `flow/academic.py` -> `execution/academic.py` |
| constraint를 계산/관찰하려면? | `adjust_constraints()`, `validate_constraints()`, `monitor_constraints()` | `specs/constraints.py` -> constraint/monitoring Flow -> `portfolio/constraints.py` |
| local Strategy를 plug-in하려면? | `validate_strategy_extension()`, `invoke_registered_strategy()` | `extensions/` -> `flow/strategy_extensions.py` -> research/daily Flow |
| Ensemble, portfolio, analysis를 쓰려면? | `run_ensemble()`, `construct_portfolio()`, `analyze_*()`, `render_report()` | `QlibxProject` catalog session -> internal Flow -> evidence |
