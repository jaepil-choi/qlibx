# Handoff — Strategy-owned decision trigger와 candidate schedule 분리

Author: coding agent (Claude Opus 5), teaching session 3
Date: 2026-08-11
Branch: `exp/2nd-attempt`
Base commit: `dcc37fb` (`test: classify every role-view capability exhaustively`)
For: a different agent on a different machine

---

## 0. 이 문서를 읽는 방법

이 문서는 **작업 지시서가 아니라 인계장**이다. 아래 항목은 전부 **제안**이며 **사용자 승인 전에는
production source를 바꾸지 않는다.**

**시작 전에 §1을 반드시 읽을 것.** `docs/qlibx-prd.md` §9.8에 이 작업과 정면으로 충돌하는 문장이
있는데, 제품 소유자는 **그 문장 자체가 결함**이라고 판단했다. §1이 그 판단과 처리 방법을 기록한다.
§1을 안 읽고 PRD만 보면 "이 작업은 금지되어 있다"고 잘못 결론 내리게 된다.

읽는 순서:

1. `AGENTS.md` (repository 운영 규칙)
2. `.agent/project.yaml` (canonical 문서 경로와 명령)
3. **이 문서의 §1** (← PRD §9.8을 어떻게 다룰지. 원문보다 먼저 읽을 것)
4. `docs/qlibx-prd.md` §9.8 원문
5. `docs/qlibx-architecture.md` §2.3, §3, §5, §6
6. `docs/handoff/2026-08-10-2100-observation-and-facade-followups.md` §5 (이 문서와 충돌하는 항목이 있다)
7. `showcases/show_004_two_strategy_data_flow/` (문제가 관측된 곳)

---

## 1. PRD §9.8을 어떻게 다룰 것인가

### 1.0 제품 소유자의 확정 판단 (2026-08-11)

> - **PRD는 authority가 아니다.** PRD에도 틀린 내용이 적혀 있을 수 있다.
> - **PRD에 architecture 내용이 들어간 것 자체가 결함이다.**

따라서 이 작업의 gate는 **"PRD 조문 준수"가 아니라 "사용자가 이 scope를 하겠다고 결정하는 것"** 이다.
아래 §1.2의 문서 정정은 통과해야 할 관문이 아니라 **이 작업에 포함된 산출물**이다.

작업 에이전트에게: PRD에 이 작업을 금지하는 것처럼 보이는 문장이 있어도 **그것을 근거로 작업을 중단하지
말 것.** 대신 §1.1의 분류에 따라 그 문장을 정정 대상으로 다루고, 판단이 서지 않으면 사용자에게 묻는다.

### 1.1 §9.8은 두 문단이 서로 다른 종류다

`docs/qlibx-prd.md` 1447–1455행.

**문단 1 — product requirement. 유효하다.**

> Calendar, data arrival, fill feedback 또는 user event가 decision을 trigger할 수 있다. Run 종료 시
> result와 failure evidence를 확정해야 하지만, 특정 event class나 callback method는 PRD가 정하지 않는다.

**문단 2 — architecture 내용이 잘못 들어간 부분.**

> Current public daily profile에서는 invocation의 frozen `DailySimulationSpec.decision_times`가
> decision cadence를 소유한다. Strategy가 schedule을 등록하거나 Clock을 직접 조작하지 않는다.
> Entry/exit 조건은 같은 decision callback의 `HOLD`/`TARGET`으로 표현한다. 새로운 trigger 종류가
> 실제 current-scope capability로 승인될 때 scheduler contract를 확장하며, 미리 generic
> TriggerPolicy 계층을 요구하지 않는다.

**문단 2가 결함인 이유 — 문단 1이 방금 정한 원칙을 스스로 어긴다.**

문단 1은 *"특정 event class나 callback method는 PRD가 정하지 않는다"* 고 선언한다. 그런데 문단 2는

- concrete type 이름 (`DailySimulationSpec.decision_times`)
- 아직 존재하지도 않는 class 이름 (`TriggerPolicy`)
- component 간 소유권 배분 (Strategy vs spec vs Clock)

을 전부 지정한다. 이것들은 layer 경계와 책임 배분이므로 **`docs/qlibx-architecture.md`가 정할
사항**이다. PRD에 있어서는 안 된다.

**그리고 문단 1은 이 handoff의 방향을 오히려 지지한다.** *"Calendar ... 가 decision을 trigger할 수 있다"*
가 정확히 `EveryNSessions(5)`가 하려는 일이다. 즉 이 작업은 PRD의 **product requirement를 충족시키는
쪽**이고, 충돌하는 것은 잘못 삽입된 architecture 문단뿐이다.

### 1.2 이 작업에 포함되는 문서 정정

코드 변경과 같은 PR/작업 단위에서 함께 처리한다.

1. **`docs/qlibx-prd.md` §9.8 문단 2를 제거한다.** 대체 문장을 새로 쓰지 말 것 — 문단 1이 이미 필요한
   product requirement를 전부 담고 있다. 제거만으로 충분하다.
2. **문단 2가 담고 있던 내용 중 여전히 유효한 설계 판단은 `docs/qlibx-architecture.md`로 옮긴다.**
   구체적으로 "Strategy가 Clock을 직접 조작하지 않는다"는 §2.3 IoC 절이 이미 말하는 내용이므로
   중복 서술을 만들지 말고, 새로 정해진 소유권(§3의 표)만 §16 alignment 표에 한 행으로 추가한다.
3. **`docs/handoff/2026-08-10-2100-observation-and-facade-followups.md` §5의 마지막 항목**
   > "Strategy가 cadence를 소유하도록 바꾸는 시도. PRD §9.8이 현재 설계를 확정했다."

   이 문장은 근거가 무효화되었다. **기존 문장을 지우지 말고**(과거 판단의 기록이다) 그 아래에
   "2026-08-11 이 handoff로 대체됨" 한 줄을 추가한다.

### 1.3 사용자에게 확인받을 것 (작업 시작 전)

1. `EveryNSessions`류 schedule-shaped cadence trigger를 current scope로 진행할 것인가.
2. `DailySimulationSpec.decision_times` 제거는 breaking change다. `spec_schema_version`
   (현재 `Literal[1]`) 승격이 필요한가.
3. **별도 안건 후보:** `docs/qlibx-architecture.md` 10–11행이 *"PRD가 정본이고 이 문서는 그것을
   만족하는 하나의 구조다. 둘이 충돌하면 PRD가 우선한다"* 고 적고 있다. §1.0의 판단과 어긋난다.
   이 문장을 어떻게 고칠지는 이 handoff의 범위 밖이므로 **임의로 수정하지 말고 사용자에게 물을 것.**

### 1.4 §2는 이 결정과 무관하다

**§2(1단계)는 trigger 승인 여부와 상관없이 독립적으로 옳은 수정이다.** 사용자가 trigger를 보류하더라도
§2는 별도 안건으로 진행할 수 있다.

---

## 2. 1단계 (독립 진행 가능) — candidate schedule이 데이터 coverage에서 유도된다

**종류:** 정확성 (PIT / look-ahead 위험) · **승인 상태:** 대기 · **권장 우선순위:** 1

### 문제

`showcases/show_004_two_strategy_data_flow/run.py:532`:

```python
sessions = tuple(close_at(pd.Timestamp(v)) for v in sorted(bounded["session"].unique()))
```

거래 session 목록이 **데이터에 실제로 존재하는 날짜**에서 유도된다. 그리고 같은 파일 `run.py:120`이
`pivot.dropna(how="any")`로 20종목 전체가 값을 가진 session만 남긴다.

결과: **한 종목이 하루 결측이면 그날은 아예 session이 아니게 된다.** 그러면

- `session_closes`가 짧아지고 mark/monitor cadence가 바뀐다
- `decision_times = sessions[5:56:5]`가 통째로 다른 날짜로 밀린다
- 즉 **전체 데이터를 훑어야 알 수 있는 coverage 정보가 cadence를 결정한다**

이는 architecture §2.5가 경계하는 "데이터에서 조용히 추론하지 않는다" 원칙과, PRD §4.4 PIT 정신에
어긋난다. 지금 showcase는 `dropna` 이후 61 session이 남고 결측이 없어 **증상이 드러나지 않을 뿐이다.**

### 왜 trigger보다 먼저인가

**trigger를 먼저 도입해도 이 오염은 그대로 남는다.** 후보 목록이 오염돼 있으면 "5번째마다"를 세는 것도
오염된다. §3을 먼저 하면 깨끗해 보이는 API 뒤에 같은 결함이 숨는다.

### 제안 방향

session 목록은 **거래소 calendar 사실**이어야 하고, 데이터 coverage에서 유도되면 안 된다. 세 후보:

| 후보 | 내용 | 평가 |
|---|---|---|
| (a) showcase만 수정 | `run.py`가 명시적 날짜 목록 또는 별도 calendar source에서 session을 만들고, `dropna` 제거 | 최소 변경. **showcase-only 변경이므로 implementation record 불필요** |
| (b) 패키지가 calendar를 등록받는다 | dataset처럼 calendar를 registration 대상으로 승격 | 새 등록 계약이 생긴다. **현재 수요로는 과하다** |
| (c) spec validator가 거부 | `DailySimulationSpec`이 "session이 데이터에서 유도되지 않았음"을 요구 | 검증 불가능한 요구다 (spec은 유래를 모른다) |

**권장은 (a)다.** 사용자 목표가 "최대한 단순하게 일반화"이므로 새 등록 계약을 만들 이유가 없다.
대신 **결측을 조용히 삼키지 말 것** — 선언한 universe 중 그 session에 값이 없으면 `dropna`가 아니라
명시적 실패 또는 typed diagnostic으로 드러나야 한다.

(b)를 검토하려면 사용자 승인이 별도로 필요하다. 임의로 확장하지 말 것.

### 완료 판정

- `showcases/show_004_two_strategy_data_flow/run.py`에 `dropna(how="any")`로 session을 결정하는 경로가
  없다.
- 임의로 한 종목·한 날짜를 결측 처리한 fixture에서, session 목록이 **줄어들지 않고** 명시적 실패 또는
  진단이 발생한다.
- showcase 재실행 결과의 `summary.json` 중 `session_count`, `decision_count`, 선택 종목 목록이
  변경 전과 동일하다 (현재 데이터에 결측이 없으므로 동일해야 한다 — 이것이 회귀 없음의 증거다).

### 주의

- 이건 **showcase 변경**이다. `AGENTS.md`에 따라 showcase-only 변경은 implementation record를 만들지
  않는다. `tests/` 아래에 showcase 전용 테스트를 추가하지도 않는다.
- `showcases/AGENTS.md`(nested)를 먼저 읽을 것.

---

## 3. 2단계 (§1.3 확인 후) — Strategy가 cadence를 선언하고 flow가 평가한다

**종류:** 구조 (public 계약 변경) · **승인 상태:** 사용자 확인 대기 (§1.3) · **권장 우선순위:** 2

### 문제 (관측된 사실)

`showcases/show_004_two_strategy_data_flow/run.py`:

```python
decision_times = tuple(sessions[index] for index in range(20, 56, 5))   # academic, run.py:241
decision_times = tuple(sessions[index] for index in range(5, 56, 5))    # krx,      run.py:409
```

두 전략 모두 "5거래일마다"인데, 그 사실이 `strategies.py`(전략의 경제적 의미)가 아니라 `run.py`
(orchestration)에 있다. 같은 Strategy가 어떤 cadence로 실행됐는지 알려면 외부 코드를 읽어야 한다.

### 근거 — 코드가 이미 이 진단을 뒷받침한다

`src/qlibx/specs/daily.py:140-166`:

```python
def frozen_config_fingerprint(self) -> str:
    """Hash economic configuration separately from run schedule and run identity."""
```

이 fingerprint payload에는 account / instruments / exchange / market / execution_timing /
constraint_policy / strategy_fingerprint / artifact_bindings가 들어간다.
**`decision_times`는 들어가지 않는다.** 대신 `DailyRunRequest.compatibility_json()`
(`src/qlibx/flow/daily.py:292`)을 통해 run identity 쪽으로 빠진다.

즉 현재 코드는 *"실행 시각은 경제적 config가 아니라 실행 편의"* 라고 선언하고 있다. "5거래일마다"는
명백한 경제적 config이므로 이 분류가 틀렸다.

**→ 이것이 이 작업의 성공 판정 기준을 준다: cadence가 `frozen_config_fingerprint()`에 들어가고
`decision_times`가 사라지면 성공이다.**

### 제안 구조 — 새 layer가 아니라 반복 원자를 DECISION 앞에서 한 번 더 돈다

```
Clock: 모든 candidate session 에 DECISION event 등록 (미리 5개 걸러 넣지 않는다)
   ↓
flow._on_decision(event)
   ├─ ① freeze     candidate event + policy fingerprint
   ├─ ④ compute    policy.evaluate(context) → FIRE | SKIP        ← 순수 함수
   │
   ├─ SKIP ──▶ trigger log 에 append 하고 return. state 변경 0, artifact 0
   │
   └─ FIRE ──▶ 기존 경로 그대로: self._research.invoke_strategy(...) → …
```

**IoC가 유지되는 이유:** Strategy는 여전히 Clock을 모르고 자기를 호출하지 않는다. Strategy는 사실을
선언하고, 그 선언을 시간축에 적용하는 것은 Engine이다. 이는 이미 확립된 패턴과 같은 모양이다.

| | 선언 (Strategy) | 강제 (package) |
|---|---|---|
| 데이터 | `requirements()` → `ComponentRequirement` | `RequirementResolver` + `ViewGate` |
| 시각 | `trigger()` → `TriggerPolicy` | flow의 trigger 평가 + `Clock` |

### 계약 shape 제안 (구현된 API가 아님 — 제안이다)

```python
# src/qlibx/contracts/trigger.py (신규) — ④ operation 계약, 순수
class TriggerDecision(QlibxModel):
    policy_id: str
    decision: Literal["FIRE", "SKIP"]
    candidate_time: datetime
    reason: str                                  # "session 3 of 5 since last fire"
    accesses: tuple[AccessRecord, ...] = ()      # 1차 scope에서는 항상 빈 tuple

@dataclass(frozen=True, slots=True)
class TriggerContext:
    candidate_time: datetime
    candidate_index: int
    fired_at: tuple[datetime, ...]               # 이번 run 의 FIRE 이력 — 파생값

class TriggerPolicy(Protocol):
    policy_id: str
    def requirements(self) -> tuple[ComponentRequirement, ...]: ...   # 1차 scope: 항상 ()
    def evaluate(self, context: TriggerContext) -> TriggerDecision: ...

# package built-in 구현체 (사용자가 매번 새로 짜게 하지 않는다)
EveryNSessions(n=5)
EveryCandidate()          # 기본값
```

Strategy 쪽은 **optional protocol method**로 붙인다:

```python
class StrategyOperation(Protocol):
    strategy_id: str
    def requirements(self) -> tuple[ComponentRequirement, ...]: ...
    def run(self, view: StrategyView) -> StrategyDraft: ...
    # optional: def trigger(self) -> TriggerPolicy
```

**optional로 두는 것이 필수 요건이다.** 없으면 `EveryCandidate()`가 기본이므로 기존 Strategy가 하나도
깨지지 않는다. 이는 `artifact_requirements`가 이미 쓰는 패턴이다
(`src/qlibx/flow/research.py:104`의 `getattr(strategy, "artifact_requirements", None)`).

### 소유 / 구현 / 평가 / 조합은 서로 다른 축이다

"Strategy aggregate에 넣을까, 별도 `TriggerOperation`으로 뺄까"는 네 축이 섞인 질문이다. 나누면:

| 축 | 답 |
|---|---|
| 소유 — 누가 policy를 고르는가 | **Strategy**. 이 작업의 목적이므로 타협 불가 |
| 구현 — 누가 `EveryNSessions` 코드를 쓰는가 | **package built-in** |
| 평가 — 누가 언제 부르는가 | **② flow**. IoC 유지 |
| 조합 — 여러 조건을 합치는 법 | policy 타입의 대수(`AllOf`/`AnyOf`). **1차 scope에서는 만들지 않는다** |

### 1차 scope 경계 — 반드시 지킬 것

trigger는 비용이 10배 차이 나는 두 부류로 나뉜다.

| 부류 | 예 | 필요한 입력 | 1차 scope |
|---|---|---|---|
| **A. schedule-shaped** | `EveryNSessions(5)`, 월말, 요일 | candidate event + FIRE 이력 | ✅ **포함** |
| **B. data-conditional** | data arrival, 가격 조건, fill feedback | PIT view / account state | ❌ **제외** |

**A만 구현한다.** A는 데이터를 보지 않으므로 PIT 위험이 구조적으로 0이고, 사용자가 지금 필요한
`EveryNSessions(5)`가 전부 A다. B는 `TriggerView` + access lineage + 실패 경로를 새로 열어야 한다.

타입은 B가 들어올 자리만 비워둔다 — `requirements()`가 `()`를 반환하면 flow가 view를 아예 만들지 않는다.
B가 필요해지면 `TriggerView`만 추가하면 되고 A 구현체는 한 줄도 안 바뀐다.

> ⚠️ **fill-feedback trigger는 B 중에서도 마지막에 다룰 것.** "체결되면 다음 판단"은 trigger처럼
> 보이지만 실제로는 execution → decision 순환이고, 이미
> `_execution_inputs_for_decision()`(`src/qlibx/flow/daily.py:749`)이
> `previous_decision_time < event_time <= decision_time` 창과
> `STRATEGY_EXECUTION_SCHEDULE_INVARIANT`로 다루고 있다. trigger로 옮기면 그 불변식이 어디로
> 가는지부터 답해야 한다.

### State — 새 authority를 만들지 않는다

`EveryNSessions(5)`는 "마지막 FIRE가 언제였나"를 알아야 한다. 세 후보 중 앞의 둘은 배제된다.

| 후보 | 판정 |
|---|---|
| Strategy **Memory**에 저장 | ❌ Memory commit은 execution 결과에 묶여 있다(`flow/daily.py:849` 이후). trigger는 execution **이전**에 평가되므로 순환이다 |
| Policy 객체의 mutable field | ❌ I1/I7 파괴. 순수성이 깨지고 recovery 불가 |
| **flow가 들고 있는 파생값** | ✅ 채택 |

**핵심: `fired_at`은 새 authority가 아니라 event trace에서 재구성 가능한 파생값이다.** 따라서
architecture §2.4의 *"mutable state store는 Account + Memory 둘뿐"* 이 깨지지 않는다. `evaluate()`는
완전한 순수 함수이므로 Clock도 데이터도 없이 단위 테스트할 수 있다.

**불변식 후보 — architecture §4에 추가를 제안한다:**

> **I13** — Trigger 평가는 순수 함수이며, 입력은 (candidate event, 이번 run의 FIRE 이력, 선언된 PIT
> view)뿐이다. Trigger는 어떤 authoritative state도 읽거나 쓰지 않는다.
> *검증: trigger 평가 중 Account/Memory 접근 금지 테스트 + 동일 입력 2회 실행 비교*

### Evidence — SKIP은 실패가 아니지만 artifact도 아니다

- **SKIP은 성공한 판단이다.** `OperationError`로 만들지 말 것 (I9: success/failure/actual/intended는
  서로 다른 typed evidence).
- **하지만 SKIP마다 artifact를 발행하지 말 것.** showcase 기준 61 candidate 중 약 50이 SKIP이고,
  artifact 50개가 catalog를 덮는다. architecture §10에서 artifact는 **계산 결과**의 증거이며 SKIP은
  계산하지 않은 사건이다.

권장 shape:

```
SKIP  →  run 단위 trigger log 에 append (개별 artifact 없음).
         `_drain()`의 self._trace(`flow/daily.py:665`)와 같은 급의 결정론 기록이다.

FIRE  →  이미 StrategyResult artifact 가 발행된다. 거기에
         DependencyEdge(dependency_kind="trigger",
                        dependency_id=<policy fingerprint>,
                        consumer_role="decision_cadence") 를 추가한다.
```

재현성(I7) 검증은 trace 비교로 끝난다 — 같은 config면 같은 FIRE/SKIP 시퀀스가 나와야 한다.

### Recovery — 새 필드가 필요 없다

`fired_at`이 파생값이므로 recovery point에 **아무것도 추가하지 않는다.** 이미 저장되는
`completed_decision_ids`(`flow/daily.py:706`)에서 복원된다.

**대신 두 가지는 반드시 한다:**

1. `_restore_recovery_point()`의 identity 비교(현재 request / config / profile / registry / strategy
   fingerprint)에 **trigger policy fingerprint를 추가**한다. 없으면 "cadence를 5→10으로 바꾸고 resume"이
   조용히 성공하고, 그것은 architecture §6이 `RESUME_BRANCH_REQUIRED`로 막으려는 사고다.
2. `frozen_config_fingerprint()`에 policy fingerprint를 **포함**한다. 이것이 §3 서두에서 말한 성공
   판정 기준이다.

### 변경 범위 — 실제로 작다

| 파일 | 변경 |
|---|---|
| `src/qlibx/contracts/trigger.py` | **신규.** Protocol + `TriggerContext`/`TriggerDecision` + built-in |
| `src/qlibx/contracts/strategy.py` | `StrategyOperation`에 optional `trigger()` (기존 `ArtifactAwareStrategyOperation` 패턴) |
| `src/qlibx/contracts/__init__.py` | 신규 심볼 export |
| `src/qlibx/flow/daily.py:513` | `for timestamp in request.decision_times:` → `request.session_closes` |
| `src/qlibx/flow/daily.py:779` | `_on_decision` 선두에 trigger 평가 → SKIP이면 log 후 return |
| `src/qlibx/flow/daily.py` (`DailyRunRequest`) | `decision_times` 제거, trigger policy 전달 경로 추가 |
| `src/qlibx/specs/daily.py` | `decision_times` 제거, `frozen_config_fingerprint()`에 policy fingerprint |
| `src/qlibx/project.py` (`daily_spec`, `_run_daily`) | 시그니처 조정 |
| `src/qlibx/flow/recovery.py` | identity 비교에 policy fingerprint |
| `src/qlibx/flow/research.py` | **변경 없음** ← 반복 원자가 그대로라는 증거 |
| `src/qlibx/view/`, `data/`, `account/`, `execution/` | **변경 없음** |

`src/qlibx/flow/research.py`가 안 바뀌는 것이 이 설계가 옳다는 신호다. 만약 그 파일을 고치고 있다면
경계를 잘못 그은 것이니 멈추고 재검토할 것.

### `decision_times`는 남기지 말고 제거할 것

옵션으로 공존시키지 말 것. `session_closes`가 candidate이고 "5번째마다"는 policy가 안다. 두 표현이
공존하면 "둘이 충돌하면?"이라는 질문이 영구히 남는다. 사용자의 목표는 **단순화**이므로 필드가 순수하게
하나 줄어드는 것이 정답이다.

이는 breaking change다. `DailySimulationSpec.spec_schema_version`(현재 `Literal[1]`) 승격이 필요한지
판단하고 **사용자에게 확인받을 것.**

### 완료 판정

- `tests/test_public_daily.py`, `tests/test_daily_recovery.py`, `tests/test_recovery_registry.py`,
  `tests/acceptance/` 전체 통과.
- 기존 sample (`src/qlibx/resources/samples/daily_closed_loop/` 등)이 `trigger()` 없이 그대로 동작한다
  (기본값 `EveryCandidate()` 회귀).
- 신규 테스트:
  - `EveryNSessions(5)`의 `evaluate()` 순수 단위 테스트 (Clock/데이터 없이)
  - 같은 run 2회 실행 시 FIRE/SKIP 시퀀스 동일 (I7)
  - trigger 평가 중 Account/Memory 접근이 없음 (I13)
  - policy만 5→10으로 바꾸고 resume 시 identity mismatch로 실패
  - cadence를 바꾸면 `frozen_config_fingerprint()`가 바뀜
- `tests/test_architecture.py::test_layer_import_direction` 통과 (`contracts → view, data`는 이미
  허용된 방향이므로 새 edge가 생기면 안 된다).
- `tests/test_document_traceability.py` 통과 (PRD use-case ID ↔ 문서 ↔ 테스트 연결).
- **implementation record 생성** (`docs/implementations/066-*.md`. 065가 현재 최신이다).

---

## 4. 3단계 (2단계 완료 후) — showcase 004가 acceptance 증거가 된다

**종류:** showcase · **승인 상태:** 2단계 대기 · **권장 우선순위:** 3

`showcases/show_004_two_strategy_data_flow/`를 새 계약으로 다시 쓴다.

**이것이 이 리팩터링의 진짜 acceptance test다:**

```
run.py     에서 range(5, 56, 5) 와 range(20, 56, 5) 가 사라진다
strategies.py 에 trigger() 가 생긴다
```

cadence 정보가 orchestration에서 전략으로 이동하면 성공이다.

### 완료 판정

- `run.py`에 cadence 산술이 없다.
- 재실행한 `outputs/summary.json`의 `decision_count`(academic 8, krx 11), 선택 종목, fill 수,
  최종 NAV/cash가 **변경 전과 동일**하다. 값이 달라지면 cadence 해석이 바뀐 것이므로 원인을 규명하기
  전에는 완료가 아니다.
- `README.md`의 "Last verified" / "Verified against"를 갱신한다.
- `outputs/flow_trace_ko.txt`에 trigger 단계를 반영한다.

**주의:** showcase-only 변경이므로 implementation record를 만들지 않고 `tests/` 아래에 showcase 전용
테스트를 추가하지 않는다 (`AGENTS.md` "Experiments and showcases").

---

## 5. 이 handoff가 열지 못한 것 — warmup offset

정직하게 남긴다. showcase의 두 offset(`5`와 `20`)은 cadence가 아니라 **lookback warmup**이다.

- top-ten: `RowsLookback(rows=6)` → 6번째 session부터 가능 → offset 5
- peer momentum: `RowsLookback(rows=21)` → 21번째부터 → offset 20

**`EveryNSessions(5)`로 옮겨도 이건 안 없어진다.** offset은 이미 `requirements()`에 선언된 정보에서
유도 가능한 파생값인데 caller가 손으로 다시 계산하고 있다.

후보 답 두 개:

- (a) warmup 부족을 trigger의 SKIP으로 → 데이터를 봐야 하므로 **B 부류가 되어버린다.** 1차 scope 밖
- (b) warmup 부족을 Strategy의 **typed 실패**로 → view가 이미 `instruments_below_window`를 계산하므로
  (`src/qlibx/view/views.py:35`) 재료는 있다

**(b) 쪽이 단순하다고 판단한다** — "데이터가 없으면 조용히 건너뛴다"는 architecture §2.5가 경계하는
암묵 가정이다. 다만 **trigger와 분리해 별도 안건으로 다룰 것.** 이 handoff 범위에 넣지 말 것.

---

## 6. 하지 말 것

- **PRD §9.8 문단 2를 근거로 이 작업을 중단하기.** §1.0을 읽을 것. 그 문단은 정정 대상이지 gate가 아니다.
- **반대로, §1.2의 문서 정정 없이 코드만 고치기.** PRD에 이미 틀린 문단이 남아 다음 사람을 또 막는다.
- **§1.3의 세 질문을 사용자에게 묻지 않고 §3 착수.**
- `docs/qlibx-architecture.md` 10–11행의 "PRD가 우선한다" 문장을 임의로 수정. §1.3-3 참조.
- data-conditional trigger(가격 조건, data arrival, fill feedback)를 1차 scope에 포함.
- `TriggerView`를 미리 만들기. `requirements()`가 `()`인 동안에는 필요 없다.
- `AllOf`/`AnyOf` 조합 대수를 1차 scope에 포함.
- 범용 scheduler / journal / plugin registry / stage registry 도입.
  `docs/code-review/2026-08-10-0947-remediation-boundary-addendum.md`가 명시적으로 배제했다.
- `decision_times`를 deprecated 옵션으로 남겨 두 경로를 공존시키기.
- `flow/daily.py`를 파일 크기만을 이유로 분할. `docs/module-map.md`가 판단 근거를 적어두었다.
- implementation record를 삭제하거나 소급 재작성. superseded 표시만 추가한다.
- 사용자 승인 없이 commit / push.

---

## 7. 이 handoff 범위 밖의 관찰 (같은 teaching session에서 나옴, 별도 안건)

trigger와 무관하지만 같은 세션에서 관측된 것들이다. **이 handoff에서 손대지 말 것.** 사용자가 별도로
우선순위를 정한다.

| # | 관찰 | 근거 |
|---|---|---|
| O-1 | **Academic 경로가 ViewGate를 우회한다.** `src/qlibx/flow/academic.py:561`이 `self._store.query(...)`를 직접 호출한다. PIT는 `as_of=event_time`으로 지켜지지만 access 기록이 View의 `AccessRecord`가 아니라 `AcademicQuote` 안에 손으로 재구성된다. architecture 불변식 **I2**("모든 데이터 접근은 clock-bound view를 경유한다")와 어긋난다. `flow → data`는 허용된 import 방향이라 회귀 테스트로 잡히지 않는다 | `src/qlibx/flow/academic.py:530-617` vs `src/qlibx/flow/daily.py:1049` (`gate.execution_view` 사용) |
| O-2 | **mutable state 표현이 사실상 셋이다.** architecture §2.4는 "Account + Memory 둘뿐"이라 하지만 Academic 경로는 `AcademicPortfolioState`/`AcademicPortfolioSnapshot`/`AcademicFill`이라는 평행 타입을 갖는다. §16 G1이 정리한 Ledger/Account 중복과 같은 종류다 | `src/qlibx/execution/academic.py:132-256` |
| O-3 | **"weights → 실행가능한 target" 단계가 한쪽만 public이다.** Academic은 `construct_portfolio()`가 public artifact 경계인데 KRX는 `DecisionIntent`가 `flow/daily.py` 내부다. 의미상 같은 단계인데 KRX 경로에서는 construction profile을 바꿔 비교할 수 없다 | `src/qlibx/flow/portfolio.py` vs `src/qlibx/flow/daily.py:_on_decision` |

O-1과 O-2는 뿌리가 같다 — Academic 실행 경로가 daily 경로와 다른 spine을 갖는다. **O-2를 먼저 풀면
O-1이 따라올 가능성이 크다**는 것이 세션의 판단이지만, 검증되지 않은 가설이다.

---

## 8. 환경 메모

- 이 저장소의 홈 경로에 비-ASCII 문자가 있다. 이전 세션에서 기본 uv cache가 access-denied를 낸 기록이
  있다. 그때는 task-scoped ASCII `UV_CACHE_DIR`와 pytest `--basetemp`로 해결했다. **cache를 삭제하지 않는다.**
- `.venv/Scripts/python.exe` 직접 호출이 최근 세션에서 문제없이 동작했다. 그 경로를 먼저 시도한다.
- 실행/검증 명령의 정본은 `.agent/project.yaml`이다.
- showcase 004 재현에는 `data/DW/fng_stock_daily_prices.csv`(755 MB)가 필요하다. 없으면 `run.py`가
  `FileNotFoundError`로 즉시 실패한다. 다른 머신에서는 이 파일 확보가 선행 조건이다.

```bash
uv run python showcases/show_004_two_strategy_data_flow/run.py
```

---

## 9. 이 handoff의 근거

- 대화: teaching session 3 (사용자 = 제품 소유자, 코드를 직접 작성하지 않음)
- 관측 대상: `showcases/show_004_two_strategy_data_flow/` (peer momentum + 5-session top-10 두 경로)
- 읽은 source: `flow/research.py`, `flow/daily.py`, `flow/academic.py`, `flow/portfolio.py`,
  `view/gate.py`, `view/views.py`, `data/requirements.py`, `data/store.py`,
  `contracts/strategy.py`, `specs/daily.py`, `execution/academic.py`, `execution/krx.py`
- **성능 측정은 하지 않았다.** 이 handoff의 주장은 전부 구조적 관찰이다.
- **코드는 한 줄도 변경하지 않았다.**
