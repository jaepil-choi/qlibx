# qlibx actual implementation — 2026-08-11 09:00

> 목적: `src/qlibx/`를 읽어 **실제로 무엇이 어떻게 구성되어 있는지**를 기술하고, `docs/qlibx-architecture.md`가
> 그것과 어긋나는 지점을 열거한다. 이 문서는 **관찰 기록**이며 normative contract가 아니다.
> Product authority는 `docs/qlibx-prd.md`, 설계 authority는 `docs/qlibx-architecture.md`로 유지한다.

- 기준 commit: `3f90f5c` (refactor: name the research Model and give modules semantic directories)
- 기준 branch: `exp/2nd-attempt`
- 판정 기준: **실제 public symbol 또는 실행 경로가 source에 있는 것만 "actual"로 적는다.** 추정하지 않고,
  확인하지 못한 것은 "미확인"으로 남긴다.
- 이 문서는 코드를 바꾸지 않았고, architecture doc도 바꾸지 않았다.

---

## Part 0. 한 줄 요약

Architecture doc의 **서술적 골격**(6 layer, 반복 원자, PIT/authority 경계, 불변식 I1–I12)은 코드와 잘 맞는다.
어긋난 것은 두 종류뿐이다.

1. **상태 표기 지연** — §1 alignment 표, §7, §8, §14, §16, §17에 남은 `GAP-*` 마커가 최근 6개 커밋보다
   뒤처져 있다. 7개 GAP이 코드에서는 이미 닫혔다.
2. **코드 블록 시그니처 불일치** — §5·§6·§7·§9·§16의 "### 계약" 블록이 실제 시그니처와 다르다. 특히
   §6 `Executor` protocol은 그 안에서 언급하는 타입 대부분이 코드에 존재하지 않는다.

---

# Part 1. 실제 구조

## 1.1 진입점 — `QlibxProject` 하나

`src/qlibx/project.py`의 `QlibxProject`가 **유일한 public composition root**다. 모든 use case가 여기서 시작하고,
Flow·`ViewGate`·backend·policy를 method마다 생성자 주입으로 조립한다. 장수명 `Engine` 객체는 없다.

| 사용자의 질문 | public method | 내부 Flow |
|---|---|---|
| 데이터를 등록한다 | `register_dataset()`, `reindex_datasets()` | `data/registry.py` |
| Strategy를 직접 돌린다 | `invoke()` | `ResearchFlow` |
| 중간 label/signal을 저장한다 | `materialize()` | `ModelFlow` |
| KRX daily backtest를 돌린다 | `run_daily(..., exchange=...)` | `DailyExecutionFlow` |
| 같은 결정을 다른 체결규약으로 비교한다 | `execute_frozen_daily()` | `DailyExecutionFlow.execute_frozen` |
| Academic long-short를 평가한다 | `run_academic(..., exchange=...)` | `AcademicExecutionFlow` |
| Ensemble / stored signal을 합성한다 | `run_ensemble()`, `invoke_stored_signal_strategy()` | `CompositionFlow` |
| weight를 physical target으로 바꾼다 | `construct_portfolio()` | `PortfolioConstructionFlow` |
| constraint를 계산/관찰한다 | `adjust_constraints()`, `validate_constraints()`, `monitor_constraints()` | `ConstraintFlow`, `MonitoringFlow` |
| 결과를 분석/보고한다 | `analyze_simulation()`, `analyze_monitoring()`, `analyze_signal()`, `render_report()` | `AnalysisFlow` |
| project-local Strategy를 붙인다 | `validate_strategy_extension()`, `invoke_registered_strategy()`, `run_daily_registered_strategy()` | `StrategyExtensionFlow` |
| agent skill을 설치한다 | `onboard()` | `onboarding.py` |

**실행 환경 누적 API가 존재한다.** `add_instrument()`, `set_exchange()`가 project instance에 상태를 쌓고,
`daily_spec()`이 그 스냅샷을 frozen spec으로 굳힌다([project.py:138-207](../src/qlibx/project.py#L138)).
Flow는 project를 참조하지 않으므로 run 시작 이후의 누적 변경이 진행 중인 run을 바꾸지 못한다.

여러 catalog 연산이 필요한 public method는 `_with_catalog_session()`으로 `LocalArtifactBackend.session()`
bounded exclusive session을 열고 그 안에서 Flow를 돌린다([project.py:737](../src/qlibx/project.py#L737)).
Sample 코드는 더 이상 `qlibx.flow`를 import하지 않는다 — 전부 facade 경유다.

## 1.2 모듈 layer와 **실제** 의존 방향

`tests/test_architecture.py::LAYER_DEPENDENCIES`가 강제하는 것이 실제 계약이다.

```text
runtime   → (없음)
data      → domain, models, errors
account   → domain, models, errors
evidence  → domain, models, errors
config    → models, errors

view      → runtime, data, + domain/models/errors
contracts → view, data, + domain/models/errors
portfolio → view, data, + domain/models/errors
analysis  → view, data, + domain/models/errors
extensions→ view, data, contracts, + domain/models/errors
execution → view, data, portfolio, evidence, + domain/models/errors
specs     → execution, portfolio, contracts, runtime, models, errors

flow      → runtime, data, view, specs, contracts, extensions,
            portfolio, execution, account, evidence, analysis, + domain/models/errors
project   → (facade; 필요한 concrete flow/backend를 조립)
```

주목할 점 두 가지.

- `execution`이 `portfolio`와 `evidence`를 import한다. 순수 계산 layer가 아니라 **preparation이 constraint
  계산과 evidence 타입을 함께 쓰는 경계**다.
- `specs`가 `execution`을 import한다. Public frozen spec이 concrete instrument/exchange 타입을 담기 때문이다.

Directory 역할:

| path | 역할 |
|---|---|
| `project.py` | public facade + operation별 composition root + catalog session 경계 |
| `runtime/` | `Clock` protocol, `BacktestClock`, `Event`, `Handler` (파일은 `clock.py` 하나) |
| `data/` | dataset registration, requirement/binding, timezone·PIT 정규화, query snapshot 발행, DuckDB 조회 |
| `view/` | `ViewGate` + 4개 role view + access record |
| `contracts/` | 사용자가 구현하는 것: `StrategyOperation`, `ResearchModel`, artifact I/O, built-in 구현 |
| `extensions/` | project-local `.py` 모듈 검증·fingerprint·등록·적재 |
| `portfolio/` | construction / adjustment / validation 순수 계산 |
| `execution/` | `BaseExchange`, `ExecutionPreparation`, KRX/Academic concrete, instrument, sizing |
| `account/` | `Account` aggregate + `StrategyMemoryStore` |
| `evidence/` | artifact envelope + local JSON payload / DuckDB catalog |
| `analysis/` | typed analysis/report 계산 |
| `specs/` | `daily.py`, `constraints.py`, `academic.py` frozen public spec |
| `flow/` | use case별 application service (아래) |
| `config/`, `onboarding.py`, `sample.py`, `cli.py`, `domain.py`, `models.py`, `errors.py` | 지원 모듈 |

`flow/` 전체 목록(14개): `research.py`, `model.py`, `daily.py`, `academic.py`, `composition.py`,
`portfolio.py`, `constraints.py`, `monitoring.py`, `analysis.py`, `extensions.py`,
`strategy_extensions.py`, `artifact_inputs.py`, `strategy_results.py`, `recovery.py`, `failures.py`.

## 1.3 Read path — registration에서 Strategy까지

이것이 최근 커밋들이 가장 크게 바꾼 부분이고, architecture doc이 가장 덜 반영한 부분이다.

```text
user CSV/Parquet
  → register_dataset()            registration schema v2
  → query snapshot 발행           content-addressed Parquet, layout_version 고정
  → ObservationStore.query()      DuckDB read_parquet + predicate pushdown
  → _DatasetView._read()          AccessRecord 기록
  → StrategyView / ModelView / ExecutionView / MonitorView
```

**registration v2 + layout version이 실제 gate다.** `ObservationStore.query()`는 조회 전에 세 가지를 강제한다
([store.py:88-120](../src/qlibx/data/store.py#L88)).

1. `registration_schema_version != 2` 또는 snapshot 부재 → `DATASET_QUERY_SNAPSHOT_REQUIRED`
   (`project.reindex_datasets()` 필요)
2. `snapshot.layout_version != CURRENT_QUERY_SNAPSHOT_LAYOUT_VERSION` → `DATASET_QUERY_SNAPSHOT_LAYOUT_REQUIRED`
3. 원본 SHA-256(`dataset.physical_fingerprint`)과 snapshot SHA-256(`snapshot.fingerprint`)을 **매 query마다**
   재검증 → `DATASET_SOURCE_DRIFT` / `DATASET_QUERY_SNAPSHOT_DRIFT`

**Lookback이 선택이 아니라 필수다.** point query(`session` / `at` / `latest`)가 아닌 historical read에
declared lookback이 없으면 `DATASET_LOOKBACK_REQUIRED`로 실패한다([store.py:81](../src/qlibx/data/store.py#L81)).
"전체를 읽고 Strategy에서 자른다"는 경로가 **구조적으로 막혀 있다.** Architecture doc은 이 강제를 기술하지 않는다.

SQL 형태:

| 질의 모드 | 술어/연산 |
|---|---|
| 공통 | `available_at <= ?` (clock cutoff, UTC 변환) |
| instrument 한정 | `instrument IN (...)`, 빈 집합이면 `FALSE` |
| `session(date, tz)` | 선언된 tz로 local day 경계를 UTC로 변환해 `observation_time >= ? AND < ?` |
| `at(observation_at)` | `observation_time = ?` |
| `CalendarLookback` | `available_at >= ?` (years/months/days 달력 산술, month-end clamp) |
| `RowsLookback` | `arg_min(payload, sort_key, N) GROUP BY instrument` → instrument별 최근 N행 |
| `latest` | `arg_min(payload, sort_key)` |

`session`/`at` query는 `observation_time_field` registration을 요구하고, 없으면
`DATASET_OBSERVATION_TIME_REQUIRED`로 실패한다. `ObservationStore.frozen()` context manager가 한 invocation
동안 DuckDB in-memory connection을 재사용한다([store.py:40](../src/qlibx/data/store.py#L40)).

**Role view 4종**([view/views.py](../src/qlibx/view/views.py)). 상속으로 권한을 쌓는다.

```text
_DatasetView              as_of, history, session, at, latest, accessed
 ├─ ModelView             (추가 없음)
 ├─ ExecutionView         (추가 없음)
 └─ _AccountStateView     + account_snapshot, state_accessed
     ├─ MonitorView       (추가 없음)
     └─ StrategyView      + latest_execution_result, execution_accessed
                          + artifact, artifact_accessed
                          + account_feedback, feedback_accessed
                          + latest_session_performance, performance_accessed
                          + memory_snapshot, memory_accessed
```

`tests/test_architecture.py::test_role_views_expose_only_their_authorized_capabilities`가 이 권한 분리를
회귀로 강제한다. 다만 그 테스트의 `strategy_only_capabilities` 집합에 `latest_execution_result` /
`execution_accessed`가 빠져 있어, 이 둘은 현재 회귀로 보호되지 않는다.

**`ViewGate` 실제 method는 `strategy_view` / `model_view` / `execution_view` / `monitor_view` 넷이다.**
`scoped_view`는 없다. 실사용 분포:

| view | 사용처 |
|---|---|
| `strategy_view` | `research.py`, `strategy_extensions.py` |
| `model_view` | `model.py`, `analysis.py`, `constraints.py`, `extensions.py` |
| `execution_view` | `daily.py` (execution / mark callback) |
| `monitor_view` | `monitoring.py` |

즉 `ModelView`는 materialization 전용이 아니라 **dataset-only operation 전반의 범용 view**로 쓰인다.

## 1.4 Write path — daily closed loop

`flow/daily.py`(약 2,300줄)가 event ordering, commit, recovery를 한곳에 갖고 있다. 의도된 기술 부채다.

**Event와 우선순위**([daily.py:91-94](../src/qlibx/flow/daily.py#L91)):

```text
DECISION   priority 0
EXECUTION  priority 10
MARK       priority 20
MONITOR    priority 30
RESUME     recovery 재개용 (architecture doc의 event 표에 없음)
```

동시각에서는 priority 오름차순이므로 `MARK`가 `MONITOR`보다 먼저 처리되어, session performance가 갱신된
committed mark를 읽는다.

**실제 callback 순서:**

```text
_on_decision   StrategyView 생성 → StrategyOperation.run() → StrategyDraft
               → Flow가 관측된 access lineage로 StrategyResult(v3) 승격
               → DecisionIntent 확정 → executor.plan()으로 다음 EXECUTION 시각 산출
               → Clock에 EXECUTION event 등록 (fill 생성 안 함)

_on_execution  ExecutionView 생성 (available_at <= event.ts)
               → KrxExecutionPreparation.prepare(intent, context)
                  → construct / adjust / advisory validate / convert 를 고정 순서로 호출
                  → PreparedExecution(request, evidence) 또는 pre-Exchange 실패
               → 주입된 BaseExchange.match_batch(request) → OperationOutcome[MatchBatchResult]
               → Flow가 Account.commit(FillBatch, expected_version=...)

_on_mark       ExecutionView → valuation → Account.commit(MarkBatch, expected_version=...)

_on_monitor    session performance / account observation evidence만 발행.
               constraint를 평가하지 않고 Account를 건드리지 않음. (doc 주장과 일치)
```

**Executor의 실제 책임은 doc보다 훨씬 좁다.** `NextSessionCloseExecutor` /`NextSessionOpenExecutor`는
[daily.py:367](../src/qlibx/flow/daily.py#L367), [daily.py:381](../src/qlibx/flow/daily.py#L381)에 있고
메서드가 `plan(decision) -> datetime | None` **하나뿐**이다. "다음 eligible session 시각 하나를 고르는 것"이
전부이며, 체결은 Flow가 한다. `execute()`도 `limitations()`도 없다.

**가격 축은 executor와 독립이다.** schedule은 `DailySimulationSpec.execution_timing`
(`"next_session_close"` | `"next_session_open"`)이 정하고, 가격은
`DailyExecutionProfile.execution_price_role`(default `"execution_price"`)이라는 semantic role로
`ExecutionView`에서 resolve한다. 별도 `FillConvention` class는 없다 — role field가 그 축을 대신한다.

**Cadence authority는 `DailySimulationSpec.decision_times`**(frozen, unique·sorted 강제)다. Strategy가
Clock을 조작하거나 schedule을 등록하지 않는다.

**Recovery.** state를 바꾸는 callback마다 clone된 Account/Memory에서 candidate를 검증하고
`simulation_recovery_point`를 durable publication한 뒤 live에 같은 change를 적용한다. 재시작은 최고 sequence를
load하고 identity를 비교한다(`flow/recovery.py` + `daily.py:1869-2055`).

## 1.5 Execution 경계 — 실제 타입

```python
# execution/base.py
class BaseExchange(ABC, Generic[RequestT, ResultT]):
    @property @abstractmethod
    def exchange_id(self) -> str: ...
    @property @abstractmethod
    def config_fingerprint(self) -> str: ...
    @abstractmethod
    def match_batch(self, request: RequestT) -> OperationOutcome[ResultT]: ...

class KrxExchange(BaseExchange[KrxBatchRequest, MatchBatchResult]): ...
class AcademicExchange(BaseExchange[AcademicBatchRequest, AcademicMatchResult]): ...
```

```python
# execution/preparation.py
@dataclass(frozen=True, slots=True)
class PreparedExecution(Generic[RequestT, EvidenceT]):
    request: RequestT
    evidence: EvidenceT

class ExecutionPreparation(ABC, Generic[IntentT, ContextT, RequestT, EvidenceT]):
    @abstractmethod
    def prepare(self, intent: IntentT, context: ContextT) \
        -> OperationOutcome[PreparedExecution[RequestT, EvidenceT]]: ...

class KrxExecutionPreparation(ExecutionPreparation[...]): ...
class AcademicExecutionPreparation(ExecutionPreparation[...]): ...
```

- 반환은 raw result가 아니라 **`OperationOutcome[...]`**이다. 실패가 타입에 실려 있다(I5).
- `config_fingerprint`가 abstract property로 강제된다 — Exchange 경제 설정 identity가 evidence에 고정된다.
- Exchange 선택은 **run 호출별 keyword 주입**이다(`run_daily(..., exchange=...)`). plugin registry 없음.
- 거래비용 public entrypoint는 없다. `KrxExchange._resolve_cost` / `_cost`가 private이고,
  candidate clipping과 final Fill이 같은 private 계산기를 공유한다([krx.py:348-372](../src/qlibx/execution/krx.py#L348)).
- KRX 전용 타입: `Order`, `MarketQuote`, `KrxBatchRequest`, `FillDiagnostic`, `MatchBatchResult`
  ([execution/krx.py](../src/qlibx/execution/krx.py)). generic `Order`/`ExecutionResult`는 존재하지 않는다.
- `KrxExchange.add_instrument()` / `compile()`이 build 단계에서 stable index array를 만든다.

## 1.6 State authority — Account와 Memory

```python
# account/account.py
AccountChange = FillBatch | MarkBatch          # 두 개뿐

class Account:
    def snapshot(self, *, evaluation_time: datetime | None = None) -> AccountSnapshot: ...
    def feedback(self, after: int, limit: int) -> AccountFeedback: ...
    def checkpoint(self) -> AccountCheckpoint: ...
    @classmethod
    def from_checkpoint(cls, checkpoint) -> "Account": ...
    def commit(self, change: AccountChange, *, expected_version: int) -> AccountCommit: ...
```

- `LifecycleBatch` / `ReconciledBatch`는 **타입 자체가 없다.** future characterization이 코드에 선반영되어
  있지 않다.
- feedback cursor는 `FeedbackCursor` 타입이 아니라 **`int`**다.
- `snapshot()`의 인자 이름은 `as_of`가 아니라 keyword-only `evaluation_time`이다.

```python
# account/memory.py
class StrategyMemoryStore:
    def snapshot(self, strategy_id: str) -> MemorySnapshot: ...
    def checkpoint(self) -> tuple[MemorySnapshot, ...]: ...
    def commit(self, *, strategy_id, value, feedback_cursor,
               expected_version: int, commit_id: str | None = None) -> MemorySnapshot: ...
```

- CAS 축이 **memory-ID가 아니라 `expected_version`**이다. `commit_id`는 idempotency 재적용 판정에만 쓰인다.
- feedback cursor의 역행을 거부한다.
- process-local in-memory store이며 checkpoint를 통해서만 durability를 얻는다.

## 1.7 사용자가 구현하는 계약

```python
# contracts/strategy.py
class StrategyOperation(Protocol):
    def requirements(self) -> tuple[ComponentRequirement, ...]: ...   # invocation 인자 없음
    def run(self, view: StrategyView) -> StrategyDraft: ...

class ArtifactAwareStrategyOperation(StrategyOperation, Protocol):
    def artifact_requirements(self) -> tuple[StrategyArtifactRequirement, ...]: ...

# contracts/model.py
class ResearchModel(Protocol[PayloadModel]):
    def requirements(self) -> tuple[ComponentRequirement, ...]: ...
    def run(self, view: ModelView) -> PayloadModel: ...
```

- Strategy는 `StrategyDraft`(weights + optional proposed memory)를 반환하고, **Flow가 관측된 access를 붙여
  `StrategyResult`로 승격**한다. Strategy는 lineage를 스스로 쓰지 않는다.
- **canonical artifact는 `strategy_result:v3`**다([contracts/strategy.py:130](../src/qlibx/contracts/strategy.py#L130)).
  v3가 아닌 artifact는 `flow/strategy_results.py`가 거부한다. v1/v2 reader는 제거됐다.
- built-in `ForwardReturnLabelModel`이 `ResearchModel`의 유일한 동봉 구현이다.
- 공용 `Operation` base protocol은 존재하지 않는다 — Strategy와 Model이 각자 독립 protocol이다.

## 1.8 Requirement와 binding

```python
# data/requirements.py
class ComponentRequirement(QlibxModel):
    requirement_id: str
    semantic_role: str
    axis: AxisRequirement = AxisRequirement()
    time: TimeRequirement = TimeRequirement()
    compatibility: tuple[CompatibilityRule, ...] = ()
    dataset_id: str | None = None
    lookback: Lookback | None = None

class ResolvedBinding(QlibxModel):        # pydantic. dataclass 아님
    requirement_id: str
    semantic_role: str
    dataset_id: str
    field: str
    registration_identity: str
    lookback: Lookback | None = None

# data/contracts.py
class RowsLookback(QlibxModel):
    kind: Literal["rows"] = "rows"
    rows: int                              # `count` 아님
class CalendarLookback(QlibxModel):
    kind: Literal["calendar"] = "calendar"
    years / months / days: int = 0
    timezone: str                          # 필수. default 없음
    month_end_policy: Literal["clamp"] = "clamp"
```

Access evidence는 `AccessRecord`([view/records.py:64](../src/qlibx/view/records.py#L64))가 담는다:
`dataset_id`, `registration_identity`, `semantic_role`, `selected_field`, `as_of`, `row_count`,
`max_available_at`, `max_observation_time`, `lookback`, `snapshot_fingerprint`, `instruments_below_window`.
**per-instrument actual count는 없다**(횡단면 크기에 비례해 커지는 문제로 제거됨).

## 1.9 Evidence

`LocalArtifactBackend`가 typed `QlibxModel` payload를 canonical JSON으로 저장하고 DuckDB를 catalog/index로만
쓴다. `session()`이 bounded exclusive writer session을 열고, 충돌은 `CATALOG_SESSION_CONFLICT` /
`CatalogSessionConflictError`로 표면화된다. Parquet payload backend는 없다.

`errors.py`의 `OperationError` / `OperationOutcome` / `OutcomeStatus`가 모든 layer의 실패 표현이다.

## 1.10 존재하지 않는 것 (doc이 언급하지만 코드에 없음)

`Operation` base protocol · `Executor` protocol · `ExecutionSpec` · `ExecutionEvent` · `ExecutionResult` ·
`ExecutionLimitation` · `PanelView` · `AccountView` · `FillConvention` / `ClosePriceFill` / `OpenPriceFill` ·
`LifecycleBatch` · `ReconciledBatch` · `StrategyMemorySnapshot` · `FeedbackCursor` 타입 ·
`Reconciler` / `PreparedDecision` / `OMSResult` · public `calculate_transaction_cost()` ·
`Clock.set_timer()` · `ViewGate.scoped_view()` · `engine` 객체 · generic `Order` (KRX 전용만 존재) ·
`ScopedView` 타입 · `production/` package · `kernel/` package.

이 중 다수는 doc이 `target pseudocode`로 **명시 표기한** 것이며(§8 `Operation`, §6 `FillConvention`,
§10 `ArtifactPublisher`) 불일치가 아니다. 표기 없이 현행 계약처럼 적힌 것만 Part 2에 올린다.

---

# Part 2. `docs/qlibx-architecture.md`와의 불일치

> **상태: 전부 반영 완료 (2026-08-11).** 아래 A–F 항목은 같은 날 architecture doc을 코드에 맞추는 방향으로
> 수정했다. 수정 요약은 architecture doc §17 "2026-08-11 — 코드 대조 sync" 항목에 있다. 이 Part는 그 sync가
> 무엇을 근거로 이루어졌는지 남기는 **감사 기록**으로 보존한다. G는 코드 쪽 후속 작업이므로 미해결이다.

## A. 이미 닫힌 GAP인데 doc이 열려 있다고 기술

`docs/current-support-map.md`는 "승인된 구현 순서 1–6 **완료**"로 갱신됐으나 architecture doc은 그 전 상태다.

| # | doc 위치 | doc 주장 | 실제 |
|---|---|---|---|
| A1 | §7 L1051 | `GAP-LOOKBACK-001` 미해결. "current `DatasetView.history()`는 아직 전체 PIT history를 반환한다" | `history()`가 `binding.lookback`을 store까지 관통시키고, lookback 없는 historical read는 `DATASET_LOOKBACK_REQUIRED`로 **실패한다** |
| A2 | §8 L1168 | `analyze_signal`이 `hypothetical_long_short_return`을 발행 중, `GAP-RETURN-AUTHORITY-001` | 해당 심볼 부재. signal metric은 `information_coefficient` 하나 |
| A3 | §8 L1171-1175 | "**Target** `ExecutionPreparation`", `GAP-EXECUTION-PREPARATION-001` | `execution/preparation.py`에 구현 + KRX/Academic concrete, public export |
| A4 | §17 L2681, §14 row 10 | "Current concrete classes에는 아직 common base가 없다", `GAP-EXCHANGE-BASE-001` | `BaseExchange[RequestT, ResultT]` 존재, 두 concrete 모두 상속 |
| A5 | §12 L1995 | `GAP-PROJECT-CONFIGURATION-001` — 누적 API 부재 | `add_instrument()`, `set_exchange()`, `daily_spec()` 존재 |
| A6 | §1 L31, §12 L1997-1999 | `GAP-PUBLIC-FACADE-001` — composition/portfolio/analysis facade 없음, sample이 `qlibx.flow` 직접 조립 | 전부 facade에 존재. sample에 `qlibx.flow` import 0건 |
| A7 | §13.11 L2295 | `GAP-EXECUTION-FEEDBACK-001` | `StrategyView.latest_execution_result()` 존재 |

→ **§14 readiness map 10행 "Simplified execution boundary (target gaps)"는 전 항목이 닫혔다.**

## B. Artifact 버전 drift

| # | doc 위치 | doc 주장 | 실제 |
|---|---|---|---|
| B1 | §16 L2609-2615 | "Current library mechanism은 `strategy_result:v2`", v3는 "approved breaking migration", "Daily recovery와 Portfolio는 v1/v2를 dispatch" | v3가 canonical. non-v3는 거부. v1/v2 reader 제거됨 |
| B2 | §14 row 6 | "v2 source-state lineage" | 동일 |

## C. 계약 shape 불일치 — `target` 표기 없이 현행 계약처럼 적힌 코드 블록

| # | doc 위치 | doc | 실제 |
|---|---|---|---|
| C1 | §5 L503 `Clock` | `set_timer(name, schedule, callback, priority)` 있음, `now()` 없음 | `set_timer` 부재. `now()` 존재 |
| C2 | §6 L704 `Executor` | `plan(decision, decision_ts) -> list[ExecutionSpec]`, `execute(...)`, `limitations()` | protocol 자체 부재. 실제 executor는 `plan(decision) -> datetime \| None` 하나. `ExecutionSpec`/`ExecutionEvent`/`ExecutionResult`/`ExecutionLimitation` 전부 부재 |
| C3 | §6 L676-699 다이어그램 | Executor sub-flow가 `exchange.match_batch`를 호출 | `DailyExecutionFlow`가 `KrxExecutionPreparation` → `BaseExchange`를 직접 호출 |
| C4 | §7 L1028-1037 | `PanelView.panel(binding)/universe(binding)`, `AccountView.snapshot()/feedback(after, limit)` | 부재. 실제는 `history/session/at/latest/accessed` + `account_snapshot()/account_feedback()` |
| C5 | §7 L1011-1020 | `RowsLookback.count`; `CalendarLookback.timezone` default `"Asia/Seoul"`; 둘 다 `@dataclass` | `rows`; `timezone` 필수; 둘 다 `QlibxModel`; 문서화 안 된 `month_end_policy` 존재 |
| C6 | §7 L912 vs L1022 | `ComponentRequirement`를 **doc 안에서 두 번, 서로 다르게** 정의. 후자(`role`, `fields`, `lookback`)는 어느 쪽과도 불일치 | 실제 필드 7개(1.8절) |
| C7 | §8 L1156, §12 | `BaseExchange.match_batch(request) -> ResultT`; `exchange_id: str` class attr | `-> OperationOutcome[ResultT]`; abstract property; 미문서화 `config_fingerprint` 강제 |
| C8 | §8 L1154 | `prepare(intent, account, execution_view, constraint_policy) -> (ExchangeRequest, PreparationEvidence)` | `prepare(intent, context) -> OperationOutcome[PreparedExecution[...]]` |
| C9 | §9 L1499 | `snapshot(as_of)`; `feedback(after: FeedbackCursor, limit)` | `snapshot(*, evaluation_time=None)`; `after: int` |
| C10 | §9 L1496 | `AccountChange = FillBatch \| MarkBatch \| LifecycleBatch \| ReconciledBatch` | `FillBatch \| MarkBatch`. 뒤 둘은 타입 자체가 없음 |
| C11 | §16 L2465 | `StrategyMemoryStore.commit(proposed_memory, expected_memory_id=...) -> StrategyMemorySnapshot` | `commit(*, strategy_id, value, feedback_cursor, expected_version, commit_id=None) -> MemorySnapshot`. **CAS 축이 version** |
| C12 | §8 L1443, §13.3 L2084 | public `calculate_transaction_cost(...)` (2회 언급) | 부재. private `_resolve_cost`/`_cost` |
| C13 | §8 L1358-1360 | `engine.add_exchange()` / `engine.add_instrument()` | `engine` 부재. `QlibxProject.set_exchange()/add_instrument()` + `KrxExchange.add_instrument()/compile()` |
| C14 | §6 L573 | `gate.scoped_view(invocation, resolved)` | `strategy_view`/`model_view`/`execution_view`/`monitor_view` |
| C15 | §11 L1805 | `ResolvedBinding`을 dataclass 열에 배치; `ScopedView`를 타입으로 열거 | `ResolvedBinding`은 pydantic; `ScopedView` 타입 부재 |
| C16 | §7 L987 | `ModelView`는 "direct materialization에 resolve된" view | analysis/constraint/extension flow도 `model_view`를 쓴다. 사실상 dataset-only 범용 view |

## D. rename commit(`3f90f5c`) 미반영

| # | doc 위치 | 내용 |
|---|---|---|
| D1 | §2.4 L253, §5 제목 L481, §12 L1920 | 여전히 "kernel". 모듈은 `runtime/` |
| D2 | §12 L1900 | `runtime/ clock, event, queue` — 실제는 `clock.py` 하나, `Event`/`Handler`가 그 안. queue 모듈 없음 |
| D3 | §12 L1901-1902 | flow 목록에 `academic.py`, `composition.py`, `artifact_inputs.py`, `strategy_results.py` 누락 |
| D4 | §12 L1919-1929 | 의존 방향이 `LAYER_DEPENDENCIES`와 불일치: `specs`/`config`/`extensions` 층 누락, `execution → portfolio/evidence` 누락, `specs → execution` 누락, `future production` 층은 소멸 |

## E. 코드에 있는데 doc이 침묵

| # | 내용 |
|---|---|
| E1 | **registration schema v2 / `reindex_datasets()` / query snapshot `layout_version`** — doc 전체에 등장하지 않는다. §1 alignment가 "snapshot invalidation 계약을 유지해야 한다"고 적어놓고 그 계약을 기술하지 않았다 (commit `2f75053`) |
| E2 | **lookback 없는 historical read의 hard failure**(`DATASET_LOOKBACK_REQUIRED`) — doc이 주장하는 것보다 강한 강제인데 미기술 |
| E3 | **`ObservationStore.frozen()` connection 재사용 / bounded top-N 질의** (commit `58bf82a`) |
| E4 | **`RESUME` event** — §3 event 표에 없음 |
| E5 | **`DecisionIntent`가 `flow/daily.py:102`에 있다** — doc은 executor-neutral cross-layer 계약처럼 다루지만 daily flow 지역 타입. `domain.py`에는 `Side`/`BudgetMode`/`Fill` 셋뿐 |
| E6 | **`config_fingerprint` abstract property** — Exchange 설정 identity 강제가 미기술 |

## F. 문서 간 모순 (architecture doc이 맞는 쪽)

| # | 내용 |
|---|---|
| F1 | `current-support-map.md` "Exact lookback" 행이 "per-instrument actual count가 access evidence에 기록된다"고 하나, architecture §17 L2651과 실제 `AccessRecord`는 그것이 제거됐음을 보인다. **support map이 stale** |
| F2 | `module-map.md` L83이 아직 `materialization.py`를 가리킨다 (같은 문서 L149는 `flow/model.py`로 맞음) |

## G. 회귀로 보호되지 않는 지점 (참고)

| # | 내용 |
|---|---|
| G1 | `test_role_views_expose_only_their_authorized_capabilities`의 `strategy_only_capabilities`에 `latest_execution_result` / `execution_accessed`가 빠져 있다. 두 capability가 다른 role view로 새어도 이 테스트는 통과한다 |

---

## Part 3. 반영 결과

2026-08-11에 A–F를 architecture doc에 반영했다. 각 항목은 doc의 normative 서술을 **코드에 맞추는** 방향이며,
반대 방향(코드를 doc에 맞춤)이 필요한 항목은 이번 대조에서 발견되지 않았다.

| 그룹 | 반영 위치 |
|---|---|
| A (닫힌 GAP 7개) | §1 alignment 표, §7, §8, §12, §13.11, §14 row 10, §17 2026-08-10 Exchange 항목 |
| B (artifact 버전) | §14 row 6, §16 "Current Strategy-composition readiness" |
| C (계약 shape 16개) | §5 Clock, §6 Executor/flow pseudocode, §7 조회 창구·requirement, §8 Exchange/preparation/cost, §9 Account, §11 타입 배치표, §16 G1 |
| D (rename) | §2.4 layer 표, §5 제목, §12 layout과 의존 방향 |
| E (누락 계약) | §3 event 표(`RESUME`, priority), §7 snapshot/reindex/lookback 강제, §8 `config_fingerprint`, §6 `DecisionIntent` 위치 |
| F (cross-doc) | `current-support-map.md` Exact lookback 행, `module-map.md` flow 표 |

### 남은 것 — 코드 쪽 후속 (미실행)

**G1.** `tests/test_architecture.py::test_role_views_expose_only_their_authorized_capabilities`의
`strategy_only_capabilities` 집합에 `latest_execution_result` / `execution_accessed`를 추가해야 한다. 지금은
이 두 capability가 `ModelView`/`ExecutionView`/`MonitorView`로 새어도 테스트가 통과한다. 문서가 아니라
회귀 커버리지의 문제이므로 이번 sync 범위에 넣지 않았다.
