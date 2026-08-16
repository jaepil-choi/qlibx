# 008 — evaluation과 execution 시간 계약 분리

## 배경

기존 runtime은 `ExecutionTable.trade_at`에서 daily `SessionStream`을 만들고 Strategy callback과 execution을
하나의 session으로 결합했다. 이 구조에서는 execution row 빈도가 callback 빈도를 결정하고 Strategy가
`decision_time`·`effective_after`를 제출하며 `offset_sessions`로 target을 고르는 authority 혼선이 있었다.

이 변경은 PRD `UC-TIME-002`, Architecture timing contract와
`docs/issues/001-separate-session-evaluation-and-execution-time.md`의 runtime acceptance를 구현한다.

## 결과

- Strategy, valuation, monitoring이 각각 immutable finite `OperationAgenda`를 참조한다.
- observation과 execution rows는 passive input이며 runtime occurrence를 만들지 않는다.
- preflight가 owner configuration, agenda identities/slices, shared `ConstraintSet`, execution input과 initial
  declarations를 inclusive run horizon에 freeze한다.
- Strategy는 current occurrence와 PIT-bounded capabilities만 받고 timestamp 없는 economic intent 또는
  `NoDecision`을 반환한다.
- Flow가 current occurrence evaluation time을 decision time으로 stamp한다.
- final `FillConvention`이 venue-local same-day/next-eligible semantics로 strictly-later exact target을 고른다.
- 한 Strategy/Account의 latest pending intent 하나만 유지한다. 새 intent는 complete validation 뒤 교체되고
  실패한 replacement와 `NoDecision`은 기존 pending authority를 보존한다.
- callback state, private Model payload, decision evidence, recorder rows와 pending pointer는 immutable
  `AcceptedRunState` root의 한 optimistic pointer swap으로 publish된다.
- prior due execution은 같은 instant의 callback보다 먼저 exact snapshot → execution-time NAV → order planning →
  Academic Exchange → Account commit → required valuation → feedback chain을 완료한다.
- weight targets는 prior mark가 아니라 current-position/complete-target union의 selected-time values로 계산한
  pre-trade NAV를 사용한다. quantity targets는 declared quantity를 유지한다.
- 하나의 frozen `ConstraintSet`이 Strategy projection, independent validation과 monitoring에 공유된다.
- successful inclusive-end finalization에는 pending intent가 없다.
- legacy `SessionStream`, `SessionEvent`, `LocalEvaluationTime`, `callback_time`, `on_session`, `offset_sessions`,
  `execution_session_times`와 Strategy timing fields를 제거했다. compatibility alias나 workspace migration은 없다.

## 설계와 구현

### Agenda와 preflight

`runtime/agendas.py`는 explicit local-time resolution proof, stable occurrence identity, canonical UTC ordering과
inclusive slicing을 제공한다. Workspace는 agendas와 closed owner configs를 detached declarations로 저장한다.
Valuation과 monitoring은 새 extension kind가 아니라 closed `ValuationConfig`와 `MonitoringPolicy`이며, extension
kind는 DataModel, StrategyModel, Exchange, Constraint 네 개를 유지한다.

### Atomic callback state

`RunStateRepository`의 current immutable root만 Model state, decision trace, recorder manifests/rows와 latest
pending을 노출한다. prepared candidates는 loadable/countable하지 않다. 모든 fallible validation과 serialization
뒤 한 root swap만 수행하므로 target/provenance/state/recorder failure가 partial authority를 남기지 않는다.

### Exact execution과 Account

Execution input은 selected target instant의 exact snapshot만 제공한다. duplicate present key는 실패하고,
selected snapshot에서 target-only instrument가 없으면 typed `ABSENT` zero-dealt다. current held value가 없으면
execution-time NAV를 계산할 수 없으므로 planning과 Account mutation 전에 실패한다.

Academic execution은 deterministic sell-before-buy planning, declared listing/side rules, zero cost와 full fill만
지원한다. Account는 expected version, cash, mode, positions와 fill journal의 immutable candidate를 먼저 검증한
뒤 Account-owned authority에 commit한다. 이 시점에 pending을 소비하고 `ACCOUNT_COMMITTED`를 hook-free publish한
다음, frozen `ValuationConfig` mark/NAV를 `MARKED`, execution feedback을 `FEEDBACK_PUBLISHED`로 각각 publish한다.
Account commit 전 실패는 mutation=false로 이전 Account/pending을 유지한다. required valuation 또는 feedback이
commit 뒤 실패하면 `FAILED_AFTER_COMMIT`, mutation=true, exact Account/root/Model version과 consumed pending을
보존하며 rollback이나 same-intent retry로 가장하지 않는다.

### 품질 게이트 보완

첫 strict Cleaner/Architecture/QA cohort가 split Account/root authority, private payload 비가시성, target-only
absence 차단, monitoring mark cache, 불완전한 constraint/intent provenance, DST selector proof, public run spine와
proxy acceptance tests를 blocker로 판정했다. 보완 구현은 다음을 추가했다.

- initial memory/payload와 callback memory/payload를 동일한 visible ModelStateRef에 결합했다.
- Strategy와 Constraint는 owner별 least-privilege `ModelWindow`를 사용한다. Constraint projection/intended
  validation과 independent monitoring actual evaluation은 같은 loaded `Constraint` tuple과 bounds path를
  사용하며 due execution에서는 monitoring을 수행하지 않는다.
- intent의 Strategy/Account/Model/source-byte actual-read provenance와 Budget/cash economics를 publish 전에
  검증한다.
- required due valuation은 independent valuation agenda occurrence를 요구하지 않고 exact target cutoff에서
  frozen `ValuationConfig` binding으로 수행한다.
- `SimulationFailure`가 stage, mutation flag, cutoff, root/Account version과 pending identity를 보존한다.
- `vqapr.public.run`이 caller가 명시적으로 preflight한 동일 `FrozenRun`만 소비하고 fingerprinted owners, initial
  authority와 bounded PIT providers를 load한다. universe와 owner-partitioned Strategy/Constraint requirements도
  freeze identity에 포함되고 Exchange listing과 대조되며 implicit re-preflight나 post-freeze argument는 없다.
- callback state, PIT/data, intent/target/constraint와 root publication failure는 각각 closed owner family/stage와
  failed requirement를 보존한다. due snapshot/order/Exchange/Account/valuation/feedback도 같은 taxonomy를 쓴다.
- show_001이 generated public-only Strategy/Exchange/Constraint와 동일 `FrozenRun`으로 dense/canonical physical
  input을 각각 실행하고 unmodified callback·due·Account·feedback·finalization full trace를 비교한다.

### Cutover

새 foundations는 additive work units로 먼저 도입했고, active `FillConvention`/workspace schema, Strategy callback,
Flow와 모든 source/test/showcase callsites는 한 cutover commit에서 교체했다. old workspace documents는
`offset_sessions is no longer supported`로 fail fast한다.

## Trade-offs

- finite resolved agendas만 지원해 recurrence/calendar inference와 live scheduler complexity를 배제했다.
- single pending pointer는 replacement semantics를 단순하고 atomic하게 하지만 queue/cancellation/recovery를
  지원하지 않는다.
- callback transaction은 in-memory immutable root로 atomicity를 보장한다. interrupted-run recovery는 별도
  capability다.
- exact selected-time valuation은 gap correctness를 보장하지만 held instrument value가 하나라도 없으면 fail
  closed한다.
- Academic profile만 완결했다. KRX partial implementation, costs, partial fills, margin/leverage, TWAP/VWAP는 없다.
- DuckDB가 Python timezone-aware parameters를 처리할 때 요구하는 `pytz`를 runtime dependency로 명시했다.

## 직접 영향을 받은 surface

- `vqapr.public`의 agenda/config/register/preflight/run 및 component-author declarations
- workspace YAML agenda/config/fill schema
- Strategy callback과 Flow runtime
- execution input registration과 exact snapshot reads
- Account/order/Exchange/valuation/constraint/evidence owners
- `showcases/show_001_execution_input_registration`
- runtime, flow, exchange, account, workspace, public-boundary와 acceptance tests

## 검증

2026-08-16, branch `gjc/implement-operation-agendas`에서 관찰한 결과:

```text
uv sync
Resolved 36 packages
Installed pytz==2026.3.post1 and editable vqapr==0.1.0

uv run pytest -q
211 passed in 8.16s

uv run ruff check src tests showcases/show_001_execution_input_registration
All checks passed!

uv run ruff format --check src tests showcases/show_001_execution_input_registration
162 files already formatted

uv run python -c "import vqapr; import vqapr.public"
exit 0

uv build
Successfully built dist/vqapr-0.1.0.tar.gz
Successfully built dist/vqapr-0.1.0-py3-none-any.whl

git diff --check
exit 0
```

Showcase를 clean generation으로 두 번 실행하고 11개 output artifact의 SHA-256 manifest를 비교했다.

```text
uv run python showcases/show_001_execution_input_registration/run.py
showcase-determinism: passed (11 artifacts)
```

최종 tracked source/tests/showcase 검색에서 다음 obsolete active symbols는 0건이었다.

```text
SessionEvent
SessionStream
LocalEvaluationTime
callback_time
on_session
execution_session_times
session_stream
target_selection
```

`effective_after`와 `offset_sessions` 문자열은 forbidden input rejection과 explicit legacy-schema error tests에만
남아 있다.

## 남은 한계

- runtime recovery, pending carryover, cancellation/expiry와 OMS는 구현하지 않았다.
- partial fills, child orders, TWAP/VWAP/pacing과 minutely execution algorithm은 구현하지 않았다.
- venue calendar/holiday inference, recurrence expansion, live timer와 data-arrival callbacks는 구현하지 않았다.
- physical parquet bytes의 in-place mutation immunity는 보장하지 않는다. FrozenRun은 declarations/configuration과
  actual-read lineage를 보존한다.
