# Handoff — Actual state 이력 관측과 Strategy state 분리

Author: coding agent (Claude Opus 5), teaching session 3
Date: 2026-08-11
Branch: `exp/2nd-attempt`
Base commit: `29cb4d8` (`docs: record validation evidence for the decision trigger`)
For: a different agent on a different machine

---

## 0. 이 문서를 읽는 방법

이 handoff는 **PRD가 이미 요구하지만 코드가 아직 구현하지 않은 것 셋**을 다룬다. 앞선 handoff와 달리
**product requirement 논쟁은 이미 끝났다.** `8393858`이 세 요구를 PRD에 확정했다.

읽는 순서:

1. `AGENTS.md`, `.agent/project.yaml`
2. **`docs/qlibx-prd.md` §4.3.1, §9.10, §9.11, §17.2** ← 이 작업의 근거
3. `docs/qlibx-architecture.md` §1.1 표 아래의 2026-08-11 문단 (무엇이 target인지)
4. `docs/handoff/2026-08-11-1000-strategy-owned-decision-trigger.md` (직전 작업, 완료됨)

### 이 작업의 근거는 PRD다 — 설계 논쟁을 다시 하지 말 것

`8393858`에서 확정된 것:

| PRD | 요구 | use case |
|---|---|---|
| §4.3.1 | Actual state를 **이력**으로 관측한다. session 시계열과 instrument panel 중 선택해 구독한다 | `UC-ACCOUNT-HISTORY-001` |
| §9.11 | Strategy state는 strategy가 소유하고, **execution 발생에 종속되지 않으며**, run 경계를 넘는다 | `UC-STATE-001` |
| §9.10 + §17.2 | Run 종료 결과는 제공하되 **중단 복구는 current scope가 아니다** | — |

`docs/qlibx-architecture.md`가 `UC-STATE-001`과 `UC-ACCOUNT-HISTORY-001`을 **target(미구현)** 으로 명시하고
있다. 이 handoff가 그 둘을 current로 만드는 작업이다.

---

## 1. 지금 코드가 어긋나 있는 지점 (검증된 사실)

### 1.1 순환 결합 — memory와 account feedback이 서로를 붙잡고 있다

`src/qlibx/flow/daily.py`의 `_on_decision`:

```python
account_feedback = (
    AccountFeedback(..., entries=(), ...)                     # ← 빈 tuple
    if memory_state.version == 0 and memory_state.value is None
    else self._account.feedback(memory_state.feedback_cursor, ...)
                                 └──────────────┘
                                 memory 의 cursor 가 조회 시작점이다
)
```

`src/qlibx/flow/daily.py`의 `_plan_memory`:

```python
if not result.state_accesses:
    self._fail(event, "memory", "MEMORY_PROPOSAL_WITHOUT_ACTUAL_FEEDBACK")
...
if feedback_cursor <= current.feedback_cursor and not initialization:
    self._fail(event, "memory", "MEMORY_FEEDBACK_NOT_ADVANCED")
```

읽으면 이렇다.

```
strategy state 를 쓰려면   →  account feedback 이 전진해야 하고
account feedback 을 보려면 →  strategy state 가 있어야 한다
```

**결과 (직접 확인할 것):**

- `project.invoke()` 직접 호출은 `account_state=None`이므로 `state_accesses`가 빌 수밖에 없고, 따라서
  **strategy state를 전혀 쓸 수 없다.**
- strategy state가 없는 daily strategy는 **account 이력을 한 줄도 못 본다.**

PRD §4.3.1의 마지막 bullet(*"Actual state 이력 접근은 strategy state 보유 여부에 종속되지 않는다"*)과
§9.11의 세 번째 bullet(*"갱신은 execution이나 fill 발생 여부에 종속되지 않는다"*)이 정확히 이 결합을 금지한다.

### 1.2 계약 구멍 — `average_cost`가 선언되지 않고 증거에도 안 남는다

`src/qlibx/account/account.py`의 `Position`은 `average_cost`와 `realized_pnl`을 **갖고 있다.** 그러나:

```python
# src/qlibx/view/records.py — strategy 에게 선언된 계약
class AccountState(Protocol):
    positions: tuple[object, ...]          # ← object. 타입이 없다

class StateHolding(QlibxModel):            # ← lineage 에 남는 것
    instrument_id: str
    quantity: float
    mark: float | None = None
    marked_at: datetime | None = None      # ← average_cost 도 realized_pnl 도 없다
```

두 문제가 동시에 있다.

1. 런타임에는 진짜 `AccountSnapshot`이 넘어가므로 `position.average_cost`가 **우연히** 동작한다. 선언은
   비어 있어 타입 검사도 자동완성도 없다.
2. Strategy가 진입 평단을 읽고 손절을 판단해도 **그 사실이 lineage에 남지 않는다.** stop-loss는 진입가가
   판단의 핵심 입력인데 evidence가 불완전해진다.

PRD §2.4는 이미 *"Stop-loss는 actual entry/fill price와 이후 marked price 또는 realized state를 이용할 수
있다"* 를 요구한다. 즉 **이것은 새 기능이 아니라 기존 요구의 미구현이다.**

### 1.3 요구가 사라진 기계장치 — recovery

`§17.2`가 중단 복구를 future로 내렸으므로, 아래 코드는 **현재 어떤 requirement도 뒷받침하지 않는다.**

| 대상 | 규모 |
|---|---|
| `src/qlibx/flow/recovery.py` | 527줄 전체 |
| `daily.py::_restore_recovery_point` | 133줄 |
| `daily.py::_hydrate_run_evidence` | 121줄 |
| `daily.py::_publish_recovery_point`, `_pending_recovery_records`, `_should_schedule` | ~80줄 |
| 4개 callback 안의 clone-리허설-비교 (`from_checkpoint` / `candidate_*` 27회) | ~150줄 |
| `resume=` 파라미터, `simulation_recovery_point` artifact, `RECOVERY_CANDIDATE_DIVERGED` 등 | 산재 |

`daily.py`에서 `resume|recovery` 언급이 **66회**다.

---

## 2. 작업 순서 — 이 순서를 지킬 것

```
W1  Actual state 이력 관측        (추가 위주, 독립)
W2  Recovery 제거                 (대규모 삭제, W3 를 작게 만든다)
W3  Strategy state 를 JSON scratch 로 (W2 이후면 훨씬 작다)
```

**W1이 먼저인 이유:** W1이 끝나면 stop-loss·cooldown·연속손실이 strategy state 없이 표현 가능해진다.
strategy state 수요 자체가 줄어든 상태에서 W3를 설계해야 필요 이상으로 크게 만들지 않는다.

**W2가 W3보다 먼저인 이유:** 현재 memory commit은 clone → 리허설 → recovery point 발행 → 실제 적용 →
비교의 5단계로 감싸여 있다. W2가 그 껍질을 걷어내면 W3는 순수한 계약 변경만 남는다.

---

## W1 — Actual state를 이력으로 관측한다

**근거:** PRD §4.3.1, `UC-ACCOUNT-HISTORY-001` · **우선순위 1**

### 요구되는 것

관측 shape는 **둘**이고, 소비자가 선택한다.

| shape | 단위 | 예시 항목 |
|---|---|---|
| **account series** | session 하나당 한 행 | cash, NAV, 실현손익, 총 exposure |
| **instrument panel** | (session × instrument) | 보유 수량, 진입 평단, 종목별 실현손익, mark |

집계 단위는 **session**이다. Raw event journal을 그대로 노출하는 것이 아니라 session 단위로 집계된
시계열을 준다. 이는 제품 소유자가 명시적으로 선택한 것이다.

### 설계 제약 다섯

1. **선언해야 보인다.** 데이터 관측과 같은 원칙이다. 기존 `ComponentRequirement`의 lookback 선언 패턴을
   재사용하는 것이 자연스럽다 — 새 개념을 만들지 말 것.
2. **무엇을 기록할지는 user가 고른다.** 기록은 소급될 수 없으므로 **run 시작 시점(frozen spec)에 선언**
   되어야 한다. 선언되지 않은 항목을 strategy가 요구하면 **계산 전에 실패**한다(추정 금지).
3. **strategy state 보유와 무관하다.** §1.1의 순환을 끊는 것이 이 작업의 핵심이다.
4. **PIT gate를 새로 만들지 말 것.** PRD §4.4가 *"이 보장은 actual state가 과거 committed outcome만 담기
   때문에 성립하며, 별도의 cutoff 장치를 요구하지 않는다"* 로 명시했다. 제품 소유자의 판단이다.
5. **`average_cost` / `realized_pnl`을 계약에 넣을 것.** `AccountState.positions`를 제대로 타입 지정하고,
   access record에 소비된 항목이 남아야 한다(§1.2).

### 완료 판정

- strategy state를 **전혀 쓰지 않는** strategy가 진입 평단과 최근 세션 실현손익 이력을 읽어 stop-loss를
  판정하는 테스트가 통과한다 (`UC-ACCOUNT-HISTORY-001`).
- 같은 strategy가 account series와 instrument panel을 각각 구독하는 두 경로가 모두 동작한다.
- 기록하도록 선언하지 않은 항목을 요구하면 **state mutation 이전에** typed 실패가 난다.
- Strategy가 소비한 actual-state 항목과 범위가 result의 dependency로 남는다.
- 기존 `tests/test_public_daily.py`, `tests/test_strategy_lineage.py`가 통과한다.
- **implementation record 생성** (`docs/implementations/067-*.md`).

---

## W2 — Recovery 제거

**근거:** PRD §17.2 (중단 복구는 current scope가 아님) · **우선순위 2**

### ⚠️ 지울 것과 남길 것을 반드시 구분할 것

PRD에서 "checkpoint"는 **두 가지 다른 뜻**으로 쓰인다. 섞어서 지우면 evidence 계약이 무너진다.

| | 뜻 | 처리 |
|---|---|---|
| **최종 상태 증거** | run 종료 결과, academic checkpoint, `SimulationCheckpoint` | ✅ **남긴다.** PRD §9.10이 *"Run은 종료 시 최종 actual state와 최종 strategy state를 결과로 제공해야 한다"* 를 요구한다 |
| **중단 복구 지점** | `simulation_recovery_point`, `resume=`, clone-리허설-비교 | ❌ 삭제 |

**남길 것 (명시):**
- `SimulationCheckpoint` / `AcademicCheckpoint` — 최종 evidence
- `Account.checkpoint()` / `from_checkpoint()` — child 격리(`execute_frozen_daily`)와 seeding에 쓰인다
- `tests/test_catalog_recovery.py` — **artifact 발행 무결성**(부분 결과를 성공으로 노출하지 않음)이며
  crash 복구가 아니다. `GAP-CATALOG-001`은 여전히 current다
- `Account.commit()`의 `expected_version` CAS — batch atomicity(I11)는 별개 요구다

**삭제 대상:**
- `src/qlibx/flow/recovery.py` 전체
- `daily.py`의 `_publish_recovery_point`, `_restore_recovery_point`, `_hydrate_run_evidence`,
  `_pending_recovery_records`, `_should_schedule`, `_resume_position`
- 4개 callback의 clone → 리허설 → 비교 (`candidate_account`, `candidate_memory`,
  `RECOVERY_CANDIDATE_DIVERGED`)
- `run_daily(..., resume=)`, `run_academic(..., resume=)` 파라미터
- `RESUME` event, `RESUME_BRANCH_REQUIRED`, `RECOVERY_TRIGGER_HISTORY_INVALID`
- `tests/test_daily_recovery.py`, `tests/test_recovery_registry.py`,
  `tests/acceptance/test_recovery_scenarios.py`

### 파급

- `showcases/show_003_academic_exchange_factor_execution/run.py`가 `run_academic(spec, resume=True)`를
  쓴다. showcase 갱신 필요.
- `docs/qlibx-architecture.md` §6의 "Default local daily recovery protocol" 절 삭제, §1.1 alignment 표의
  daily orchestration 행 갱신.
- `docs/qlibx-prd.md` §15.5 `GAP-RECOVERY-001`은 이미 `future (§17.2)`로 바뀌어 있다. 추가 변경 불필요.

### 완료 판정

- `daily.py`가 2,424줄에서 크게 줄어든다 (대략 1,300~1,500줄 예상. **숫자를 실측해 기록할 것**).
- `grep -c "resume\|recovery" src/qlibx/flow/daily.py`가 0에 가깝다.
- 전체 스위트 통과. `tests/test_catalog_recovery.py`는 **그대로 통과해야 한다** (삭제 대상 아님).
- Showcase 003/004 재실행 결과가 이전과 **수치까지 동일**하다.
- **implementation record 생성** (`docs/implementations/068-*.md`).

---

## W3 — Strategy state를 JSON scratch로

**근거:** PRD §9.11, `UC-STATE-001` · **우선순위 3**

### 확정된 계약 (제품 소유자 결정)

```
값의 형태     JSON 직렬화 가능한 값만. 직렬화 불가능하면 즉시 typed 실패
수명          run 경계를 넘는다. day N 의 종료 state 를 day N+1 의 시작 state 로 쓴다
읽기          지난 호출(또는 seed)이 남긴 값. 처음이면 None
쓰기 시점     Strategy 가 반환한 직후. flow/execution 경계 결합 없음
seed          run 의 명시적 입력. 이전 run 의 state 를 자동 선택하지 않는다
package 의 역할  저장하고 돌려준다. 내용을 해석하지 않는다
```

**seed는 `DailyAccountSeed.initial_cash`와 같은 급이다.** 둘 다 "이 run이 시작하는 상태"다. 이 대칭을
유지하면 production loop가 명시적이 된다.

```
day N    run  →  최종 strategy state (JSON)
day N+1  spec 의 시작 state 로 그 JSON 을 명시적으로 지정
```

### CAS와 version이 왜 필요 없는가 — 구조적 논거 둘

이건 "덜 엄격해도 괜찮다"가 아니라 **방어 대상이 존재할 수 없다**는 뜻이다.

1. **writer가 하나뿐이다.** `BacktestClock`이 event를 순차 drain한다(단일 프로세스·단일 스레드). 동시
   쓰기 경로가 없다.
2. **scratch는 look-ahead를 만들 수 없다.** t1에 쓴 내용은 t1에 볼 수 있었던 것의 부분집합이고(view가
   이미 강제), t2 > t1에 읽는다. 구성상 미래를 담을 수 없다. 따라서 PIT 기계장치가 필요 없다.

### 삭제 대상

| 지금 | 앞으로 |
|---|---|
| `MEMORY_PROPOSAL_WITHOUT_PRIOR_STATE` | 삭제 |
| `MEMORY_CAS_MISMATCH` | 삭제 |
| `MEMORY_PROPOSAL_WITHOUT_ACTUAL_FEEDBACK` | 삭제 |
| `MEMORY_FEEDBACK_CURSOR_MISMATCH` | 삭제 |
| `MEMORY_FEEDBACK_NOT_ADVANCED` | 삭제 |
| — | **`MEMORY_NOT_JSON`** 신규 |

함께 사라지는 것: `expected_memory_version`, `MemoryCommitEvidence`, `_plan_memory`(95줄),
`_apply_memory_plan`(54줄), `_memory_dependencies`, `StrategyMemoryStore`의 CAS/cursor 로직.

**남기는 것:** `path_dependent` 불리언. "이 result는 data만으로 재현되지 않는다"는 소비자 신호는 여전히
진짜다(PRD §9.11 네 번째 bullet). 다만 그건 lineage 서브시스템이 아니라 **필드 하나**다.

### 정직하게 남는 대가 하나 — 반드시 문서화할 것

Strategy가 DECISION 직후에 state를 쓰면, **EXECUTION이 실패해도 state는 이미 전진해 있다.** Strategy는
"손절했다"고 기억하는데 실제로는 체결이 실패해 여전히 보유 중일 수 있다.

**이것은 버그가 아니라 의도된 계약이다.** Strategy state는 *판단의 기록*이고 actual state는 *사실의
기록*이며, 둘은 어긋날 수 있다(production에서는 늘 그렇다). Package의 일은 둘을 강제로 동기화하는 것이
아니라 **둘 다 정직하게 보여주는 것**이다. Strategy는 다음 호출에서 state와 actual state를 모두 갖고
있으므로 스스로 대조할 수 있다.

이 문장을 implementation record에 남길 것. Flow가 다시 동기화를 떠맡으면 삭제한 여섯 개의 실패 코드로
되돌아간다.

### 완료 판정

- 체결이 0인 세션에서도 state가 이어진다 (`UC-STATE-001`).
- `project.invoke()` 직접 호출에서 state를 쓸 수 있다 (**현재는 구조적으로 불가능**).
- Run 결과에서 최종 state를 얻고, 그것을 다음 run의 시작 state로 지정해 이어 실행할 수 있다.
- 이전 run의 state를 자동 선택하지 않는다.
- JSON 직렬화 불가능한 값은 typed 실패.
- **implementation record 생성** (`docs/implementations/069-*.md`).

---

## 3. 사용자에게 확인받을 것 (착수 전)

세 가지가 미해결이다. **추측하지 말고 물을 것.**

1. **strategy state의 schema 불일치를 어떻게 다루는가?**
   전략 코드가 바뀌면 state 구조가 바뀔 수 있다. 옛 state를 새 전략에 먹이면 조용히 오작동한다.
   `strategy_fingerprint`는 파일 해시라 주석 한 줄 수정에도 바뀌므로 엄격 비교는 production state를
   자주 끊는다.
   **직전 세션의 권고:** 전략이 state에 스스로 버전 키를 넣게 하고(`{"schema": 2, ...}`), package는
   fingerprint를 **기록만** 한다. package가 전략의 state 구조를 알지 않는다는 원칙과 일치한다.

2. **state 칸이 하나인가, 이름 있는 여러 칸인가?**
   **권고: 하나.** 칸을 나누면 package가 그 구조를 알아야 하고, 그러면 계약이 다시 자란다. 전략이
   dict를 스스로 관리하면 된다.

3. **actual state가 기본으로 무엇을 기록해야 하는가?**
   W1의 "user가 고른다"는 선언 경로를 만들지만, 기본값이 필요하다. cash/NAV/보유수량/평단/실현손익
   정도가 후보다. 기록 항목이 늘면 run 비용도 늘어난다.

---

## 4. 하지 말 것

- **W1 이전에 W3 착수.** strategy state 수요가 부풀려진 상태에서 설계하게 된다.
- **`Account`에 PIT cutoff gate 신설.** PRD §4.4가 명시적으로 불필요하다고 적었다.
- **`tests/test_catalog_recovery.py` 삭제.** artifact 무결성이며 crash 복구가 아니다. `GAP-CATALOG-001`은
  current다.
- **`SimulationCheckpoint` / `AcademicCheckpoint` 삭제.** 최종 evidence이며 PRD §9.10이 요구한다.
- **strategy state에 CAS·version·cursor 재도입.** §W3의 구조적 논거 둘을 먼저 반박할 것.
- **strategy state 갱신을 execution 결과에 다시 결합.** PRD §9.11이 금지한다.
- **raw event journal을 strategy에 그대로 노출.** 제품 소유자가 session 집계를 선택했다.
- **generic scheduler / journal / plugin registry 도입.**
  `docs/code-review/2026-08-10-0947-remediation-boundary-addendum.md`가 배제했다.
- implementation record 삭제·소급 재작성. superseded note만 추가한다.
- 사용자 승인 없이 commit / push.

---

## 5. 검증과 환경

**기준선 (base commit `29cb4d8`에서 실측):**

```
uv run pytest -q --ignore=tests/acceptance --ignore=tests/performance
→ 259 passed, 2 failed in ~50s
```

실패 2건은 **기존 환경 문제이며 이 작업과 무관하다.**
`tests/test_data_source_audit.py`가 로컬 `data/preprocessed/sector_classification.parquet`를
`tests/scenarios/data_sources.yaml`의 감사 계약과 대조하는데, 데이터 파일이 재생성되어 행 수가
187,615 → 1,143,059로 바뀌었다. 소스 모듈을 전혀 읽지 않는 테스트다. **고치려 하지 말 것.**
(구현기록 066도 같은 결론을 독립적으로 기록했다.)

**필수 회귀:**
- `tests/test_document_traceability.py` — PRD의 모든 `UC-*`가 architecture에 있어야 한다. 새 UC를
  추가하면 architecture §1.1 표에 6열을 채운 행을 **같은 커밋에서** 추가할 것.
- `tests/test_architecture.py::test_layer_import_direction` — 새 import edge를 만들지 말 것.

**환경 메모:**
- 홈 경로에 비-ASCII 문자가 있다. 기본 uv cache가 access-denied를 낸 기록이 있다. task-scoped ASCII
  `UV_CACHE_DIR`와 pytest `--basetemp`로 해결했다. **cache를 삭제하지 않는다.**
- Showcase 004 재현에는 `data/DW/fng_stock_daily_prices.csv`(755MB)가 필요하다. 없으면 즉시 실패한다.

---

## 6. 범위 밖 (별도 안건)

이 handoff에서 손대지 말 것. 사용자가 따로 우선순위를 정한다.

| # | 관찰 |
|---|---|
| O-1 | **Academic 경로가 ViewGate를 우회한다.** `src/qlibx/flow/academic.py`가 `self._store.query(...)`를 직접 호출한다. PIT는 지켜지지만 access 기록이 View의 `AccessRecord`가 아니라 `AcademicQuote`에 손으로 재구성된다. architecture I2와 어긋나지만 `flow → data`는 허용된 import 방향이라 회귀로 잡히지 않는다 |
| O-2 | **mutable state 표현이 셋이다.** architecture §2.4는 "Account + Memory 둘뿐"이라 하지만 Academic 경로가 `AcademicPortfolioState` 평행 타입을 갖는다. O-1과 뿌리가 같다 |
| O-3 | **"weights → 실행가능한 target" 단계가 한쪽만 public이다.** Academic은 `construct_portfolio()`가 public 경계인데 KRX는 `DecisionIntent`가 flow 내부다 |
| O-4 | **Flow가 계산을 한다.** `_on_execution`이 DataFrame→dict 가공, 유한성/양수성 필터, constraint input 조립을 직접 한다(~50줄). architecture §2.4가 경고한 신호이며 `ExecutionPreparation`이 갈 자리다 |
| O-5 | **warmup offset이 파생값인데 손으로 계산된다.** `RowsLookback(6)` → 6번째 session부터 가능이라는 사실이 `requirements()`에 이미 있는데 caller가 다시 센다. 구현기록 066도 같은 지적을 남겼다 |
| O-6 | **architecture doc 10–11행**이 *"둘이 충돌하면 PRD가 우선한다"* 고 적고 있다. 제품 소유자의 "PRD는 authority가 아니다" 판단과 어긋난다. **product-governance 결정이므로 임의로 고치지 말 것** |
