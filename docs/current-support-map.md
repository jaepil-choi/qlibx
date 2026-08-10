# Current support map

> Snapshot: 2026-08-10. 이 문서는 구현이 현재 제공하는 것과 PRD가 요구하지만 아직 제공하지 않는 것을 구분한다.
> Product authority는 `docs/qlibx-prd.md`이고, 상세 설계 설명은 `docs/qlibx-architecture.md`다.

## 상태 판정 기준

- **Current**: public symbol과 실행 가능한 flow/test evidence가 현재 source에 있다.
- **Partial**: 계산 또는 concrete component는 있지만 PRD의 end-to-end public path가 닫히지 않았다.
- **Gap**: 확정된 product requirement이나 현재 구현에 대응 경계가 없다.
- **Future**: PRD가 current support 밖으로 명시한 capability다.

## Capability map

| capability | status | 현재 진입점과 실제 동작 | 남은 경계 |
|---|---|---|---|
| Dataset registration/PIT resolution | Current | registration v2가 content-addressed normalized Parquet snapshot을 만들고, `RowsLookback`/`CalendarLookback`을 DuckDB predicate/projection pushdown으로 읽으며 explicit `reindex_datasets()`가 v1을 전환한다 | 기존 registration은 query 전에 명시적 reindex 필요 |
| Direct Strategy research | Current | `QlibxProject.invoke()`가 `ResearchFlow`를 조립하고 Strategy draft를 lineage가 붙은 result artifact로 승격한다 | 없음 |
| Direct Model materialization | Current | `QlibxProject.materialize()`와 `MaterializationFlow`가 optional typed intermediate artifact를 발행한다 | recurring scheduler/model registry는 current requirement가 아님 |
| Project-local Strategy extension | Current | validation, immutable registration, registered execution 경로가 있다 | arbitrary plugin registry는 current requirement가 아님 |
| Daily KRX closed loop | Current | `QlibxProject.run_daily(..., exchange=...)`가 explicit schedule, `KrxExecutionPreparation`, typed `BaseExchange` 호출, actual-fill Account/Memory commit, exact next-callback execution feedback과 recovery를 조립한다 | 없음 |
| Frozen daily child execution | Current | `execute_frozen_daily()`가 parent strategy result를 재계산하지 않고 isolated child Account에서 close/open convention을 비교한다 | 없음 |
| Academic hypothetical execution | Current | `QlibxProject.run_academic(..., exchange=...)`, `AcademicExecutionPreparation`과 `AcademicExchange(BaseExchange)`가 production Account와 분리된 signed/fractional hypothetical state를 계산한다 | KRX와 request/result 또는 ledger semantics 통합은 요구하지 않음 |
| Constraint adjustment/validation | Current | standalone `adjust_constraints()`/`validate_constraints()`와 daily `KrxExecutionPreparation`이 같은 adjustment/validation 계산을 사용하며 finding은 `passed`, aggregate는 `compliant`다 | best-effort residual breach는 evidence에 남고 Exchange 호출을 막지 않음 |
| Actual-account monitoring | Current | `monitor_constraints()`가 committed checkpoint를 별도 cadence에서 읽고 finding을 발행한다 | daily callback 자동 연결은 current requirement가 아님 |
| Ensemble/stored-signal composition | Current | `run_ensemble()`와 `invoke_stored_signal_strategy()`가 catalog session 안에서 v3 lineage-preserving composition을 실행한다 | 없음 |
| Portfolio construction | Current | `construct_portfolio()`가 internal portfolio Flow를 catalog session 안에서 실행한다 | 없음 |
| Analysis/report | Current | `analyze_simulation()`, `analyze_monitoring()`, `analyze_signal()`과 `render_report()`가 public facade에 있다 | 없음 |
| Exact lookback | Current | `ComponentRequirement.lookback`이 resolver/view까지 보존되고 rows/calendar query와 per-instrument actual count/snapshot SHA-256이 access evidence에 기록된다 | sessions lookback은 이번 범위 밖 |
| Unified execution preparation | Current | generic lifecycle 아래 `KrxExecutionPreparation`과 `AcademicExecutionPreparation`이 각각 하나의 immutable preparation bundle과 typed request를 만든다 | concrete 경제적 의미는 의도적으로 분리됨 |
| Common Exchange boundary | Current | `BaseExchange[RequestT, ResultT]` 아래 KRX/Academic concrete class가 독립 request/result를 사용하고 run-level keyword DI로 선택된다 | arbitrary plugin registry나 mutable project Exchange state는 없음 |
| Latest execution feedback | Current | `StrategyView.latest_execution_result()`가 직전 decision 이후의 유일한 exact v2 execution evidence만 노출하고 실제 접근을 `strategy_result:v3` lineage에 기록한다 | 복수 execution이면 schedule invariant로 실패 |
| Intraday/partial fill/OMS/real short | Future | current package는 이를 지원한다고 주장하지 않는다 | 별도 product decision과 lifecycle authority가 필요함 |

## 현재 closed-loop를 읽는 순서

```text
QlibxProject.run_daily()
  -> DailyExecutionFlow
  -> StrategyView -> StrategyOperation.run() -> StrategyDraft
  -> Flow promotion -> StrategyResult / DecisionIntent
  -> next-close or next-open Executor
  -> KrxExecutionPreparation -> injected BaseExchange.match_batch(request)
  -> Flow-owned Account/Memory commit
  -> execution, mark, checkpoint and lineage evidence
```

이것이 **현재 코드**이며 다음 feedback까지 연결된 closed loop다.

```text
Strategy
  -> ExecutionPreparation
  -> selected BaseExchange
  -> Flow-owned Account commit
  -> StrategyView.latest_execution_result()
```

Academic flow는 위 daily flow에 조건문으로 합치지 않는다. 같은 `BaseExchange` lifecycle을 따르더라도
`AcademicRequest/AcademicResult`와 hypothetical state transition을 독립적으로 유지한다.

## 승인된 구현 순서

1. **완료:** Generic `BaseExchange`와 typed request를 추가하고 두 concrete Exchange의 numerical behavior를 보존한다.
2. **완료:** Constraint-free `ExecutionPreparation` pass-through와 advisory constraint, execution evidence v2를 연결한다.
3. **완료:** Registration-time normalized Parquet snapshot, explicit reindex와 exact rows/calendar query를 구현한다.
4. **완료:** Latest execution access와 dataset lookback access를 함께 `strategy_result:v3`으로 전환하고 v1/v2 reader를 제거한다.
5. **완료:** Composition, portfolio, analysis/report를 `QlibxProject` facade로 감싼다.
6. **완료:** Public specs를 `specs/`, scoped views를 `view/`로 이동하고 old root/context import shim은 두지 않는다.

각 단계는 별도 vertical slice다. 범용 scheduler/journal/plugin registry는 도입하지 않는다.
