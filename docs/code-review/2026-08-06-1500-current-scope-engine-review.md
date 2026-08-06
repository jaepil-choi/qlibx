# 2026-08-06 15:00 Current-scope engine code review

Reviewer: coding agent (Claude Opus 5)
Scope: `src/qlibx` 전체 (약 6,526 LOC)
Reviewed commit: `a05844f` (`feat: add independent constraint monitoring`)
Branch: `exp/2nd-attempt`
Baseline documents: `docs/qlibx-prd.md`, `docs/qlibx-architecture.md`, `docs/implementations/001`~`013`

> 이 문서는 감사 기록이며 canonical contract가 아니다. PRD와 Architecture가 정본이고, 이 문서와
> 충돌하면 정본이 우선한다. 아래 finding은 "확정된 버그 목록"이 아니라 **fact check 대상**이다.
> 각 항목의 재현 절차와 판정 기준을 그대로 실행해 확인한 뒤에 수정 여부를 결정한다.

---

## 0. 후속 agent를 위한 사용법

1. §2의 finding 표에서 하나를 고른다.
2. 해당 §3.x 절의 **재현** 블록을 그대로 실행한다. `CONFIRMED`로 표시된 항목은 이 문서 작성 시점에
   실제 실행으로 관측한 것이고, `REASONED`는 코드 경로 추적만으로 판단한 것이다.
3. **판정 기준**에 적힌 관측값이 재현되면 finding이 유효하다. 재현되지 않으면 이 문서에 반증을 기록하고
   finding을 폐기한다.
4. 수정할 경우 `AGENTS.md`의 implementation record 규칙에 따라 `docs/implementations/NNN-*.md`를 새로
   만든다. 이 review 문서는 수정 기록이 아니므로 여기에 수정 내역을 덧붙이지 않는다.

### 코드 위치 유효성

리뷰 시점 이후 `HEAD`는 `f9f6f74`로 진행했으나, 아래 인용된 파일은 모두 그 이전에 마지막으로 수정되었고
리뷰 시점과 동일하다. 따라서 인용한 `file:line`은 `f9f6f74`에서도 유효하다.

| 파일 | 마지막 변경 commit |
|---|---|
| `src/qlibx/flow/daily.py` | `d97ade9` |
| `src/qlibx/data/requirements.py` | `eec76d8` |
| `src/qlibx/account/account.py` | `ed3f32b` |
| `src/qlibx/execution/exchange.py` | `eec76d8` |
| `src/qlibx/flow/intraday.py` | `765c95b` |

line number가 어긋나면 인용된 코드 조각으로 `grep`해 위치를 다시 확인한다.

### 공통 실행 환경

```bash
uv run pytest -p no:cacheprovider -q
```

재현 테스트는 `tests/acceptance/conftest.py`의 `real_dw_case` fixture(실 DW parquet 추출)를 사용한다.
아래 재현 코드는 모두 `tests/acceptance/` 아래에 임시 파일로 두고 실행한 뒤 **삭제**한다. 이 리뷰를 위해
생성했던 임시 파일은 이미 삭제되어 저장소에 남아 있지 않다.

---

## 1. 총평

Gate 구조(`ViewGate` / `available_at <= clock.now()` 강제), Account의 CAS·batch atomicity·idempotency,
artifact envelope의 typed 검증과 content-hash 재검증은 PRD와 Architecture가 요구하는 형태로 서 있다.
아래 finding은 이 골격 자체를 부정하지 않는다.

실질적으로 시급한 것은 F-01, F-02, F-03 세 건이다.

- **F-01**은 리밸런싱이 2회 이상인 모든 backtest의 수량 계산을 왜곡한다.
- **F-02**와 **F-03**은 PRD가 명시적으로 금지한 silent fallback(§4.6)과 허위 evidence(§2.6, §4.5)에
  해당한다. 계산이 틀리는 문제가 아니라 **제품 계약을 어기는** 문제다.

현재 acceptance suite가 이 셋을 모두 통과시키는 이유는 구조적이다.

- fixture strategy `ActualStateMomentumStrategy`는 포지션이 생기면 항상 `HOLD`하므로,
  **보유 상태에서의 두 번째 리밸런싱이 한 번도 실행되지 않는다** (F-01 미검출).
- `DailyExecutionProfile`은 `dataset_id`를 고정하므로 resolver의 모호성 경로를 타지 않는다 (F-02 미검출).
- fixture strategy가 `account.feedback_cursor > memory.feedback_cursor` 가드를 손으로 넣어 두어
  first-decision memory 경로를 우회한다 (F-04 미검출).

즉 이 셋은 "테스트가 없어서 못 잡은" 것이 아니라 **fixture가 해당 경로를 구조적으로 회피**하고 있다.
수정과 함께 회피하지 않는 fixture를 추가해야 한다.

---

## 2. Finding 요약

| ID | 위치 | 요약 | severity | 상태 |
|---|---|---|---|---|
| F-01 | `flow/daily.py:650` | 주문 수량을 직전 세션 mark 기준 stale NAV로 산출 | high | CONFIRMED |
| F-02 | `data/requirements.py:83` | 동일 semantic role 다중 후보를 실패 없이 알파벳순 선택 | high | CONFIRMED |
| F-03 | `flow/daily.py:1054` | Fill commit 이후 실패도 `commit_status=NONE`으로 기록 | high | CONFIRMED |
| F-04 | `flow/daily.py:926` | 첫 decision의 memory 초기화가 run 전체를 중단시킴 | medium | CONFIRMED |
| F-05 | `account/account.py:126` | mark 시각이 없어 stale mark를 `COMPLETE`로 판정 | medium | REASONED |
| F-06 | `execution/exchange.py:192` | market volume 부재 시 impact를 정액 요율로 fallback | medium | REASONED |
| F-07 | `account/account.py:275` | 포지션 청산 시 `realized_pnl`과 잔여 수량 소실 | low | REASONED |
| F-08 | `flow/intraday.py:305` | `AccountCommitRejected`가 raw 예외로 전파 (I5 위반) | low | REASONED |

---

## 3. Finding 상세

### F-01 — 주문 수량이 직전 세션 mark 기준 stale NAV를 사용한다

**위치**: `src/qlibx/flow/daily.py:650` (`DailyExecutionFlow._on_execution`)

**상태**: CONFIRMED (실행 재현)

**현상**

```python
# src/qlibx/flow/daily.py:649-652
for instrument in required_instruments:
    target_quantity = target_weights.get(instrument, 0) * before.nav / prices[instrument]
    actual_quantity = holdings.get(instrument, 0)
    delta = target_quantity - actual_quantity
```

`prices`는 **이번 세션 종가**(`view.session(execution_price_role, session_date)`)인데,
`before.nav`는 `Account.snapshot()`이 계산한 값으로 **직전 세션 MARK가 남긴 mark**를 사용한다.

원인은 event priority다 (`src/qlibx/flow/daily.py:44-47`).

```python
DECISION_PRIORITY = 0
EXECUTION_PRIORITY = 10
MARK_PRIORITY = 20
MONITOR_PRIORITY = 30
```

`_prepare`는 모든 `session_closes`에 MARK(20)와 MONITOR(30)를 등록하고, EXECUTION은 10이다. 따라서
**같은 세션 종가 timestamp에서 EXECUTION이 항상 MARK보다 먼저 실행**되고, EXECUTION이 보는 mark는
언제나 한 세션 이전 것이다.

**재현**

`tests/acceptance/test_zz_repro.py`로 저장하고 실행한 뒤 삭제한다.

```python
"""TEMPORARY review repro - delete after inspection."""

from qlibx import OutcomeStatus
from qlibx.flow import DailyExecutionFlow, DailyExecutionProfile, DailyRunRequest
from qlibx.kernel import BacktestClock
from qlibx.operations import BudgetMode, DecisionAction, StrategyDraft, WeightEntry
from tests.acceptance.real_dw_support import (
    RealDwProject,
    close_at,
    configured_exchange,
    initial_account,
)


class SwitchingStrategy:
    """1회차는 A000660 전량, 2회차는 A005930 전량으로 리밸런싱한다."""

    strategy_id = "repro.switching"

    def __init__(self) -> None:
        self.calls = 0

    def requirements(self):
        return ()

    def run(self, view):
        self.calls += 1
        target = "A000660" if self.calls == 1 else "A005930"
        return StrategyDraft(
            weights=(WeightEntry(instrument=target, weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
        )


def test_repro_stale_nav(real_dw_case: RealDwProject) -> None:
    sessions = tuple(close_at(2024, 1, day) for day in (2, 3, 4, 5))
    flow = DailyExecutionFlow(
        clock=BacktestClock(sessions[0]),
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
        exchange=configured_exchange(cost_rate=0.0),
        account=initial_account(),
        profile=DailyExecutionProfile(
            market_dataset_id="dw-real-market",
            execution_price_role="execution_price",
            valuation_price_role="valuation_price",
        ),
    )
    outcome = flow.run(
        SwitchingStrategy(),
        DailyRunRequest(
            run_id="repro-stale-nav",
            config_fingerprint="repro-v1",
            decision_times=(sessions[0], sessions[2]),
            session_closes=sessions,
        ),
    )
    assert outcome.status is OutcomeStatus.COMPLETE, outcome.errors
    for execution in outcome.result.executions:
        print("EVENT", execution.event_time)
        print("  before nav", execution.account_before.nav, "cash", execution.account_before.cash)
        print("  holdings", execution.account_before.holdings)
        for fill in execution.fills:
            print("  fill", fill.instrument_id, fill.side, fill.dealt_quantity, fill.price)
    final = outcome.result.final_account
    print("FINAL nav", final.nav, "cash", final.cash, final.holdings())
    for position in final.positions:
        print("  weight", position.instrument_id, position.quantity * position.mark / final.nav)
```

```bash
uv run pytest tests/acceptance/test_zz_repro.py -q -s -p no:cacheprovider
```

**관측된 출력** (판정 기준)

```text
EVENT 2024-01-03 06:30:00+00:00
  before nav 10000000.0 cash 10000000.0
  holdings ()
  fill A000660 BUY 73.0 136800.0
EVENT 2024-01-05 06:30:00+00:00
  before nav 9970800.0 cash 13600.0
  holdings (StateHolding(instrument_id='A000660', quantity=73.0, mark=136400.0),)
  fill A000660 SELL 73.0 137500.0
  fill A005930 BUY 130.0 76600.0
FINAL nav 10051100.0 cash 93100.0 {'A005930': 130}
  weight A005930 0.990737332232293
```

핵심은 두 번째 EXECUTION이다.

- `before.nav = 9,970,800`은 `13,600 + 73 x 136,400`으로, **2024-01-04 종가 mark**를 쓴다.
- 그러나 같은 event에서 A000660 매도는 **2024-01-05 종가 137,500**에 체결되어 실제로 10,037,500을 회수한다.
- 목표 수량 = `1.0 x 9,970,800 / 76,600 = 130.16` -> 130주 -> 9,958,000 집행.
- 결과: 목표 100%인데 실현 비중 **99.07%**, 의도하지 않은 현금 **93,100원** 잔류.

참고로 사용된 실 DW 종가는 다음과 같다. A005930은 01-04와 01-05 종가가 우연히 같으므로(76,600),
**재현할 때 보유 종목을 A000660으로 잡아야 staleness가 드러난다.**

| date | A000660 | A005930 |
|---|---|---|
| 2024-01-02 | 142,400 | 79,600 |
| 2024-01-03 | 136,800 | 77,000 |
| 2024-01-04 | 136,400 | 76,600 |
| 2024-01-05 | 137,500 | 76,600 |

**영향**

- 오차는 리밸런싱마다 누적된다. 가격이 오르는 국면에서는 지속적으로 under-invest한다.
- 반대 방향(가격 하락)에서는 stale NAV가 자본을 과대평가해 Exchange가 `CASH_LIMIT`으로 clip한다.
  즉 **sizing 결함이 시장 유동성 diagnostic으로 잘못 기록된다.** PRD §4.6이 금지하는 종류의 오분류다.
- Architecture §2.2 "실제로 무엇을 갖고 있는가 — Account"와 §5의 동시각 priority 근거
  ("`MARK`(10)가 `MONITOR`(20)보다 먼저여야 monitoring이 갱신된 account를 읽는다")를 EXECUTION에
  적용하면 같은 논리가 성립하지 않는다. 현재 구현은 EXECUTION < MARK 순서다.

**수정 방향 (택일 필요 — 제품 결정)**

1. 주문 변환에서 execution view가 읽은 당일 가격으로 NAV를 재계산한다 (`cash + Σ qty x execution_price`).
   Account state는 건드리지 않고 계산에만 쓰므로 authority 경계를 침범하지 않는다.
2. 또는 EXECUTION 이전에 당일 mark를 commit하는 별도 event(priority < 10)를 두어, EXECUTION이 항상
   당일 valuation을 본 뒤 실행하게 한다.
3. 또는 현행 동작이 의도된 것이라면 `DailyExecutionProfile.limitations`에 "직전 세션 valuation 기준으로
   수량을 산출한다"를 명시하고, 그에 맞는 acceptance fixture를 추가한다.

어느 쪽이든 **보유 상태에서 종목을 교체하는 2회 리밸런싱 fixture**를 acceptance에 추가해야 한다.

---

### F-02 — 동일 semantic role 다중 후보를 실패 없이 알파벳순으로 선택한다

**위치**: `src/qlibx/data/requirements.py:83` (`RequirementResolver.resolve`)

**상태**: CONFIRMED (실행 재현)

**현상**

```python
# src/qlibx/data/requirements.py:68-83
candidates = [
    dataset
    for dataset in registry.datasets
    if requirement.semantic_role in dataset.bindings
    and (requirement.dataset_id is None or dataset.dataset_id == requirement.dataset_id)
    and all(...)
]
if not candidates:
    errors.append(self._missing_error(...))
    continue
selected = sorted(candidates, key=lambda item: item.dataset_id)[0]
```

후보가 0개면 `REQUIREMENT_NOT_RESOLVED`로 실패하지만, **후보가 2개 이상일 때는 아무 진단 없이
`dataset_id` 사전순 첫 번째를 선택**한다.

**재현**

```python
"""TEMPORARY review repro - delete after inspection."""

import shutil

import duckdb

from qlibx import OutcomeStatus
from qlibx.data import (
    AvailableAtField,
    ComponentRequirement,
    DatasetRegistration,
    RequirementResolver,
    SourceFormat,
)
from tests.acceptance.real_dw_support import RealDwProject


def test_repro_ambiguous_role(real_dw_case: RealDwProject) -> None:
    duplicate = real_dw_case.root / "aaa-shadow-market.parquet"
    shutil.copyfile(real_dw_case.source, duplicate)
    # execution_price를 의도적으로 1로 덮어쓴 두 번째 물리 파일
    shifted = real_dw_case.root / "aaa-shadow.parquet"
    duckdb.connect().sql(
        f"SELECT * REPLACE (execution_price * 0 + 1 AS execution_price) "
        f"FROM read_parquet('{duplicate.as_posix()}')"
    ).write_parquet(str(shifted))
    outcome = real_dw_case.project.register_dataset(
        DatasetRegistration(
            dataset_id="aaa-shadow-market",
            source=shifted.name,
            source_format=SourceFormat.PARQUET,
            instrument_field="ticker",
            observation_time_field="date",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("date", "available_at", "ticker"),
            semantic_bindings={"execution_price": "execution_price"},
            semantic_category="krx_daily_market",
            source_provenance="repro shadow dataset",
        )
    )
    assert outcome.status is OutcomeStatus.COMPLETE, outcome.errors
    resolution = RequirementResolver().resolve(
        operation="repro",
        idempotency_identity="repro",
        requirements=(
            ComponentRequirement(
                requirement_id="repro.execution_price",
                semantic_role="execution_price",
            ),
        ),
        registry=real_dw_case.project.registry_snapshot(),
    )
    print("FAILED?", resolution.failed)
    print("BINDINGS", [(b.dataset_id, b.field) for b in resolution.bindings])
```

**관측된 출력** (판정 기준)

```text
FAILED? False
BINDINGS [('aaa-shadow-market', 'execution_price')]
```

**영향 — 어느 호출 경로가 실제로 위험한가**

`dataset_id`를 고정하는 경로는 안전하다.

- `DailyExecutionFlow._on_execution` / `_on_mark`: `dataset_id=self._profile.market_dataset_id` 고정. **안전.**

`dataset_id`를 고정하지 **않는** 경로가 위험하다.

- `src/qlibx/flow/constraints.py:201-205` (`ConstraintFlow._resolve`) — `benchmark_weight_role`만 지정.
- `src/qlibx/flow/monitoring.py:117-121` (`MonitoringFlow._resolve`) — 동일.

즉 benchmark weight를 제공하는 dataset이 둘 이상 등록되면(개정판 등록, 다른 지수, 테스트 fixture 잔존)
**constraint adjustment / validation / monitoring이 조용히 다른 benchmark로 갈아탄다.** 게다가
lineage evidence(`DependencyEdge`)는 잘못 선택된 dataset을 정확히 가리키므로, 증거만 보면 정상으로 보인다.

**정본 근거**

- PRD §4.6 "명시적 실패가 silent fallback보다 우선한다"
- PRD §4.7 "비슷한 field name, class path 또는 default 값이 경제적 의미를 확정하지 않는다"
- PRD §2.6 "빠진 data를 비슷한 field로 대체하지 않으며, 경제적 의미를 추측하지 않는다"

**수정 방향**

`len(candidates) > 1`이면 `REQUIREMENT_AMBIGUOUS`(신규 error code)로 실패시키고, context에 후보
`dataset_id` 목록과 각 `registration_identity`를 담는다. retry precondition은 "requirement에
`dataset_id`를 명시하거나 중복 binding을 제거하라"가 된다. `ConstraintDeclaration`과
`ConstraintMonitoringRequest`에 benchmark dataset을 고정할 수 있는 필드를 추가할지도 함께 결정해야 한다.

---

### F-03 — Fill commit 이후의 실패도 `commit_status=NONE`으로 기록한다

**위치**: `src/qlibx/flow/daily.py:1054` (`DailyExecutionFlow._fail`)

**상태**: CONFIRMED (실행 재현)

**현상**

```python
# src/qlibx/flow/daily.py:1044-1058
error = OperationError(
    operation="daily_flow.run",
    stage_path=f"daily_flow.{stage}",
    error_code=code,
    context={...},
    commit_status=CommitStatus.NONE,      # <- 무조건 NONE
    ...
)
```

`_fail`은 commit 이전 단계에서도 호출되지만, `_on_execution`이 **`Account.commit(FillBatch)`를 성공시킨
뒤** 이어지는 경로에서도 호출된다.

- `_on_execution` -> `_commit_memory` -> `_fail(event, "memory", ...)` (daily.py:763-770, 894-936)
- `_on_execution` -> `_publish_model` 실패 -> `self._errors` 확장 (daily.py:761-762, 1027-1029)

**재현**

```python
"""TEMPORARY review repro - delete after inspection."""

from qlibx.flow import DailyExecutionFlow, DailyExecutionProfile, DailyRunRequest
from qlibx.kernel import BacktestClock
from qlibx.operations import BudgetMode, DecisionAction, StrategyDraft, WeightEntry
from tests.acceptance.real_dw_support import (
    RealDwProject,
    close_at,
    configured_exchange,
    initial_account,
)


class FirstDecisionMemoryStrategy:
    strategy_id = "repro.first-memory"

    def requirements(self):
        return ()

    def run(self, view):
        memory = view.memory_snapshot()
        view.account_snapshot()
        return StrategyDraft(
            weights=(WeightEntry(instrument="A005930", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
            proposed_memory={"initialised": True},
            expected_memory_version=memory.version,
        )


def test_repro_commit_status(real_dw_case: RealDwProject) -> None:
    sessions = tuple(close_at(2024, 1, day) for day in (2, 3))
    flow = DailyExecutionFlow(
        clock=BacktestClock(sessions[0]),
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
        exchange=configured_exchange(),
        account=initial_account(),
        profile=DailyExecutionProfile(
            market_dataset_id="dw-real-market",
            execution_price_role="execution_price",
            valuation_price_role="valuation_price",
        ),
    )
    outcome = flow.run(
        FirstDecisionMemoryStrategy(),
        DailyRunRequest(
            run_id="repro-commit-status",
            config_fingerprint="repro-v1",
            decision_times=(sessions[0],),
            session_closes=sessions,
        ),
    )
    print("STATUS", outcome.status)
    for error in outcome.errors:
        print("  ", error.stage_path, error.error_code, error.commit_status, error.context)
```

**관측된 출력** (판정 기준)

```text
STATUS failed
   daily_flow.memory MEMORY_FEEDBACK_NOT_ADVANCED {'event_name': 'EXECUTION',
   'event_time': '2024-01-03T06:30:00+00:00', 'account_version': 1,
   'consumed_feedback_cursor': 0, 'memory_feedback_cursor': 0}
```

`context.account_version == 1`은 **FillBatch가 이미 Account에 commit되었다는 뜻**이다. 그런데 같은
error의 `commit_status`는 `NONE`이다.

**정본 근거**

- PRD §2.6 "Operation이 state를 commit했는지와 deterministic retry에 필요한 precondition 또는
  idempotency identity"를 machine-readable하게 보고해야 한다.
- PRD §4.5 / Architecture I9 "Success, failure, retry, actual state와 intended state는 서로 다른
  typed evidence다."

**영향**

`commit_status=NONE`을 신뢰한 agent 또는 운영자는 "이번 run은 아무것도 바꾸지 않았다"고 판단해
execution 이전 checkpoint에서 재실행한다. Account의 `event_id` idempotency가 중복 적용 자체는 막지만
(`DUPLICATE_EVENT`), **evidence가 사실과 다르다**는 계약 위반은 남는다.

**수정 방향**

`DailyExecutionFlow`가 이번 event에서 authoritative commit이 발생했는지를 추적하고, `_fail`에
`commit_status`를 인자로 넘긴다. commit 이후 실패에는 `CommitStatus.COMMITTED`와 함께 commit된
`event_id` / `account_version`을 retry precondition에 담는다. `_publish_model` 실패 경로도 동일하게
처리해야 한다.

---

### F-04 — 첫 decision에서 memory를 초기화하면 run 전체가 중단된다

**위치**: `src/qlibx/flow/daily.py:926` (`DailyExecutionFlow._commit_memory`)

**상태**: CONFIRMED (F-03 재현 코드와 동일한 실행에서 관측)

**현상**

```python
# src/qlibx/flow/daily.py:925-936
feedback_cursor = result.state_accesses[-1].feedback_cursor
if feedback_cursor <= current.feedback_cursor:
    self._fail(event, "memory", "MEMORY_FEEDBACK_NOT_ADVANCED", ...)
    return
```

신규 `Account`의 journal은 비어 있으므로 첫 decision 시점의 `feedback_cursor`는 0이고, 신규
`StrategyMemoryStore`의 `feedback_cursor`도 0이다 (`account/memory.py:20-24`). 따라서
`0 <= 0`이 성립해 실패한다.

**판정 기준**: F-03 재현 출력의 `MEMORY_FEEDBACK_NOT_ADVANCED (consumed_feedback_cursor=0,
memory_feedback_cursor=0)`. `_fail`은 `self._errors`에 넣고 `_drain`이 즉시 종료하므로
**run 전체가 FAILED**로 끝난다.

**논점 (제품 결정 필요)**

이 가드의 의도는 PRD §9.4 / `UC-ALPHA-ADAPTIVE-001`의 "no future feedback" — 아직 확인되지 않은
feedback으로 belief를 진행시키지 못하게 하는 것이다. 그 자체는 타당하다.

문제는 두 가지다.

1. **첫 decision은 정의상 선행 feedback이 없다.** memory를 최초로 초기화하는 것과 미확인 feedback으로
   belief를 진행시키는 것은 다른 행위인데 같은 규칙으로 막힌다.
2. **실패 단위가 run 전체다.** proposal 하나를 거부하는 것이 아니라 backtest가 중단된다.

fixture strategy(`tests/acceptance/real_dw_support.py:182`)는
`has_new_feedback = account.feedback_cursor > memory.feedback_cursor`를 손으로 넣어 이 경로를 회피한다.
그러나 이 요구사항은 Strategy contract(`operations/strategy.py`의 `StrategyDraft`)에도, PRD에도,
bundled skill에도 문서화되어 있지 않다.

**수정 방향 (택일)**

1. `current.version == 0 and current.feedback_cursor == 0`인 최초 commit을 허용하고, 이후부터
   strict 전진을 요구한다.
2. 현행 규칙을 유지하되 `StrategyDraft.validate_budget`에서 미리 거부하거나, run을 중단하지 않는
   proposal-rejected diagnostic으로 강등한다.
3. 현행 동작이 의도라면 PRD/skill/`StrategyDraft` docstring에 "첫 decision에서는 memory를 제안할 수
   없다"를 명시하고, 위반 fixture를 characterization test로 고정한다.

---

### F-05 — mark 시각이 없어 stale mark를 `COMPLETE` valuation으로 판정한다

**위치**: `src/qlibx/account/account.py:126` (`Account.snapshot`)

**상태**: REASONED (코드 경로 추적)

**현상**

```python
# src/qlibx/account/account.py:124-143
def snapshot(self) -> AccountSnapshot:
    positions = tuple(sorted(self._positions.values(), key=lambda item: item.instrument_id))
    complete = all(position.mark is not None for position in positions)
    ...
    valuation_status=(ValuationStatus.COMPLETE if complete else ValuationStatus.INCOMPLETE),
```

`Position`(`account.py:14-20`)에도 `AccountSnapshot`에도 `StateAccessRecord`(`context/scoped.py:37-44`)
에도 **mark가 언제 찍혔는지에 대한 정보가 없다.** `mark is not None`이면 무조건 COMPLETE다.

**영향**

`monitor_actual_single_name_caps`(`portfolio/constraints.py:306-314`)는 이 값만으로 게이트한다.

```python
if account_state.valuation_status != "COMPLETE":
    raise ConstraintEvaluationError("ACCOUNT_VALUATION_INCOMPLETE", ...)
```

그 뒤 `measured = holding.quantity * holding.mark / account_state.nav`를 계산한다. 즉
**며칠 전 가격으로 계산된 비중을 근거로 cap 준수를 선언한 `constraint_monitoring_result`가 발행될 수
있다.** monitoring finding은 소급 수정되지 않는 evidence이므로(PRD §4.3) 잘못된 준수 판정이 그대로
남는다.

또한 F-01의 근본 원인이기도 하다. EXECUTION이 stale mark를 "정상 valuation"으로 받아들이는 이유가
여기에 있다.

**정본 근거**

- Architecture §2.6 "필요한 가격이나 lifecycle input이 없으면 이전 값을 정상값처럼 사용하지 않고
  `INCOMPLETE` 또는 `STALE` diagnostic을 남긴다."
- PRD §4.4 "Actual account snapshot의 `as_of`도 evaluation time보다 늦을 수 없다." — 검사할 `as_of`
  자체가 snapshot에 없다.

**fact check 포인트**

`ValuationStatus`에 `STALE`이 이미 정의되어 있는지 확인한다. 현재는 `COMPLETE`/`INCOMPLETE` 둘뿐이다
(`account.py:9-11`). Architecture가 언급하는 `STALE`이 미구현 상태인지, 의도적으로 future로 미뤄둔
것인지 `docs/implementations`에서 근거를 찾아 판단한다.

**수정 방향**

`Position.mark`를 `(price, marked_at)`으로 확장하거나 `Account`가 마지막 MarkBatch의 event time을
보관하고, `snapshot(as_of=...)`가 mark 시각과 비교해 `STALE`을 반환한다. `StateAccessRecord`에도
`as_of`와 mark 시각을 실어 monitoring이 PIT 검사를 할 수 있게 한다.

---

### F-06 — market volume 부재 시 impact를 정액 요율로 fallback한다

**위치**: `src/qlibx/execution/exchange.py:192` (`KrxExchange.match_batch`)

**상태**: REASONED (코드 경로 추적)

**현상**

```python
# src/qlibx/execution/exchange.py:186-197
market_value = (
    quote.total_market_volume * quote.price
    if quote.total_market_volume is not None
    else 0
)
proposed_value = quantity * quote.price
impact = (
    self._config.impact_rate * (proposed_value / market_value) ** 2
    if market_value > 0
    else self._config.impact_rate          # <- 전액 정액 적용
)
effective_rate = rule.rate + impact
```

`market_value == 0`이면 이차 impact 모델 대신 `impact_rate` **전액이 정액 요율로** 더해진다.

**핵심**: `DailyExecutionFlow._on_execution`(`daily.py:662-669`)은 `MarketQuote`를
`instrument_id`, `price`, `available_volume`만으로 만들고 **`total_market_volume`을 절대 넘기지 않는다.**
따라서 current-support daily 경로에서는 `market_value`가 항상 0이고, `else` 분기가 항상 실행된다.

**판정 기준**

`impact_rate=0.001`로 `KrxExchangeConfig`를 구성하고 daily flow를 실행한 뒤,
`ExecutionEvidence.fills[0].total_cost`가 `trade_value * (rule.rate + 0.001)`과 일치하는지 확인한다.
일치하면 finding이 유효하다. (기본값 `impact_rate=0`이므로 현재 acceptance는 이 경로를 드러내지 않는다.)

**영향**

- 이차 impact 모델을 의도한 사용자가 **모든 주문에 10bp 정액 추가 수수료**를 받는다.
- `_max_buy_quantity`(`exchange.py:296-316`)가 이 요율로 매수 가능 수량을 clip하므로 체결 수량도 바뀐다.
- `Fill.total_cost`에 합산되고 `Fill.cost_rule_id`는 실제 fee/tax rule을 가리키므로,
  **해당 policy가 규정하지 않은 비용이 그 policy 소산으로 기록된다.**

**정본 근거**

- PRD §4.6 silent fallback 금지.
- PRD `UC-CASHFLOW-001` "Fill fee와 tax만 transaction cost로 집계한다."
- PRD `UC-COST-001` "Fill은 total cost와 적용 policy identity를 보존해야 한다."

**수정 방향**

`impact_rate > 0`인데 `total_market_volume`이 없으면 `EXECUTION_MARKET_VOLUME_MISSING`으로 실패시킨다
(`INSTRUMENT_UNSUPPORTED` / `EXECUTION_QUOTE_MISSING`와 같은 preflight 단계). 함께, impact를
`Fill.total_cost`에 섞지 말고 별도 필드로 분리할지 검토한다 — 현재 구조로는 cost 감사가 불가능하다.

---

### F-07 — 포지션 청산 시 `realized_pnl`과 잔여 수량이 소실된다

**위치**: `src/qlibx/account/account.py:275` (`Account._apply_fills`)

**상태**: REASONED (코드 경로 추적)

**현상**

```python
# src/qlibx/account/account.py:269-282
quantity = current.quantity - fill.dealt_quantity
realized = (
    current.realized_pnl
    + (fill.price - current.average_cost) * fill.dealt_quantity
    - fill.total_cost
)
if quantity <= 1e-12:
    positions.pop(fill.instrument_id)     # <- realized를 버린다
else:
    positions[fill.instrument_id] = replace(current, quantity=quantity, realized_pnl=realized)
```

전량 매도 시 바로 위에서 계산한 `realized`가 그대로 버려진다. 같은 종목을 나중에 다시 매수하면
`realized_pnl`은 0에서 다시 시작한다(`account.py:259`). 또한 `0 < quantity <= 1e-12`인 잔여 수량이
cash 조정이나 journal 기록 없이 삭제된다.

**현재 영향 범위**

`realized_pnl`은 저장소 전체에서 `account/account.py` 외에는 읽히지 않는다.

```bash
grep -rn "realized_pnl" --include=*.py src tests
```

어떤 evidence model에도 노출되지 않으므로 **현재는 잠재 결함**이다. 다만 PRD §0.2가 vn.py에서
차용 대상으로 명시한 "trading/holding PnL 분해"가 바로 이 필드에 의존하므로, 성과 분석을 붙이는
순간 모든 청산된 round trip의 실현손익이 누락된다.

**수정 방향**

청산 시에도 `Position(quantity=0)`을 유지하거나, Account에 종목별 누적 realized PnL을 별도 보관한다.
전자는 Architecture §2.6의 "Position map은 실제 보유 상품만 담는 sparse map" 원칙과 충돌하므로
후자가 적절해 보인다. dust 수량은 삭제 대신 명시적 diagnostic으로 남긴다.

---

### F-08 — `AccountCommitRejected`가 raw 예외로 전파된다 (intraday)

**위치**: `src/qlibx/flow/intraday.py:305`, `src/qlibx/flow/intraday.py:405`

**상태**: REASONED (코드 경로 추적)

**현상**

```python
# src/qlibx/flow/intraday.py:304-312
if committed_fills:
    after = self._account.commit(
        FillBatch(...),
        expected_version=before.version,
    ).snapshot
```

`try/except AccountCommitRejected`가 없다. 같은 상황을 daily flow는 감싸서 typed error로 변환한다
(`daily.py:689-696`). `_finish`(`intraday.py:405`)의 MarkBatch commit도 동일하다.

**영향**

`STALE_VERSION`, `NEGATIVE_CASH`, `SELL_EXCEEDS_POSITION`, `INSTRUMENT_NOT_REGISTERED` 중 어느 것이든
`RuntimeError`가 `IntradayExecutionFlow.execute` 밖으로 그대로 나간다. 호출자는 invariant **I5**가
요구하는 `OperationOutcome(FAILED, errors=...)` 대신 예외를 받고, failure artifact도 발행되지 않는다.

**우선순위 판단**

`docs/implementations/012`에 따라 intraday는 **current support가 아니라 future characterization**이고
`qlibx.flow.__all__`에서도 제외되어 있다. 다만 012가 이 모듈을 남겨둔 이유가 "preflight 실패와
per-event Account CAS 동작을 증명하는 architecture 증거"이므로, 그 증거가 I5를 지키지 않는다는 점은
모순이다.

---

## 4. 검토했으나 finding으로 올리지 않은 것

후속 agent가 같은 지점을 재발견하고 중복 조사하지 않도록 기록한다.

| 지점 | 판단 |
|---|---|
| `exchange.py:232` — `dealt_quantity=0`인 Fill 생성 | `daily.py:676`과 `intraday.py:302`가 commit 전에 필터링한다. Account의 `SELL_EXCEEDS_POSITION` 오폭은 발생하지 않는다. |
| `Account.commit` 원자성 | `_apply_fills`/`_apply_marks`가 복사본에 적용하고 검증 후에만 `self`에 반영한다. 부분 실패가 state를 바꾸지 않는다. I11 충족. |
| `BacktestClock.advance_to_next` 동시각 순서 | heap 키가 `(ts, priority, sequence)`이므로 pop 순서가 곧 priority 순서다. 결정론적. |
| `store.py:59-65` — `available_at` 중복 계산 | 59행 결과를 61행이 덮어쓴다. 동작은 동일하며 순수 중복 코드다. cleanup 대상이지 버그가 아니다. |
| `StrategyView.latest()` — `keep="last"` | `store.query`가 `(available_at, observation_time, instrument)` 오름차순으로 정렬해 반환하므로 "가장 최근에 available해진 관측"이 선택된다. PIT 의미상 타당. |
| `evidence/local.py:93-100` — payload 파일 orphan | catalog commit 실패 시 payload 파일이 남는다. artifact_id가 content-derived이므로 재발행이 안전하고 catalog에 보이지 않는다. 영향 미미. |
| `evidence/local.py:174-182` — `publish_failure` identity 충돌 | 같은 `error_id`에 다른 context면 `ARTIFACT_IDENTITY_CONFLICT`로 failure artifact 발행이 실패한다. error 자체는 반환되므로 손실은 evidence 한 건. low. |
| `ConstraintFlow` / `MonitoringFlow`의 `BacktestClock(request.evaluation_time)` | cutoff가 호출자 선언값이다. PRD가 invocation-time cutoff를 허용하므로 설계상 정상. |
| `composition.py:346` — `operation.run(object())` 2회 호출 | `EnsembleStrategyOperation.run`이 instance state를 쓰지만 결정론적이라 결과는 동일하다. 설계 냄새이지 버그는 아니다. |
| `daily.py:873` — `account_version_after_callback` | `before`와 같은 시점에 찍어 항상 동일하다. 무변경을 실제로 증명하지 못하는 증거이나 오류는 아니다. |

---

## 5. 검토 범위와 한계

**검토함**: `src/qlibx` 전체 소스, `tests/acceptance/test_execution_scenarios.py`,
`tests/acceptance/real_dw_support.py`, `tests/acceptance/conftest.py`,
`docs/implementations/010`~`013`, PRD §0~§5, Architecture §1~§6.

**검토하지 못함 (후속 리뷰 필요)**:

- PRD §6 이후 (user/agent workflow, §7.12 instrument extension, §9.4 path dependency 상세) —
  문서 길이 제한으로 앞부분만 읽었다. `docs/qlibx-prd.md`는 1,783행이고 §5까지만 대조했다.
- Architecture §7 이후 (§7.6 no-look-ahead 상세, §13 cost/exchange, §16 설계 감사 기록) —
  `docs/qlibx-architecture.md`는 2,605행이고 §6까지만 대조했다. **특히 §13.2/§13.3의 cost rule
  정의는 F-06 판단에 직접 관련되므로 후속 확인이 필요하다.**
- `src/qlibx/cli.py`, `onboarding.py`, `project.py`, `config/project.py`, `resources/skills/` —
  runtime correctness 관점에서 우선순위가 낮아 제외했다.
- `docs/implementations/001`~`009` — 요약만 참조했고 대조하지 않았다.
- 성능/`UC-SCALE-001`(3,000종목) 특성 — 전혀 검증하지 않았다.

**리뷰 중 저장소에 가한 변경**: 없다. 재현용 임시 테스트 파일은 모두 삭제했다.
