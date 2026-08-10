# 2026-08-10 14:30 Ideal remediation analysis (session 2)

Reviewer: coding agent (Claude Opus 5)
Input: `docs/code-review/2026-08-10-1000-mental-model-conformance-review.md` (MM-01 ~ MM-10, §0 fact check 반영)
Reviewed commit: `98bdfba` (`feat: add hypothetical academic exchange`)
Branch: `exp/2nd-attempt`
Canonical documents: `docs/qlibx-prd.md`, `docs/qlibx-architecture.md`

> **이 문서의 목적.** session 1은 "무엇이 어긋났는가"를 기록했다. 이 문서는 그 각각에 대해
> **"이상적으로는 어떻게 고쳐야 하는가"** 를 분석한다. 구현 계획서가 아니라 **설계 판단 근거**다.
>
> **상태 (2026-08-10 갱신): §7의 Q1–Q4가 모두 승인되었다.** 확정 내용은 바로 아래
> **★ 확정된 결정** 절에 있다. §4의 순서에 따라 구현에 착수할 수 있으며, 각 단계는 그 절이
> 정한 범위를 넘지 않는다. §7의 소문자 세부 항목(q4-a/b/c, q1-a)은 기본값이 정해져 있으므로
> 착수를 막지 않는다.
>
> session 1 §3의 제안 표는 이 문서로 **대체된다.** 특히 **P3(MM-06)은 폐기**한다 — §3.6에
> 더 나은 설계가 있다.

---

## ★ 확정된 결정 (2026-08-10, 사용자 승인)

§7의 네 질문이 모두 답을 받았다. **아래가 정본이며, 본문의 이전 서술과 충돌하면 이 절이 우선한다.**

| | 질문 | 결정 | 본문 |
|---|---|---|---|
| **Q1** | Constraint를 loop 안에 넣을 것인가 | ✅ **🅲 파이프라인 자리를 만든다.** 단계 0개로 시작해 현행과 동일 동작을 유지하고, 실제 stage 구현은 필요 시점에 채운다 | §3.3 |
| **Q2** | Validation breach 처리 | ✅ **🅱️ 위반을 기록하고 그대로 실행한다.** profile switch는 두지 않는다 | §3.3, §7 |
| **Q3** | 디렉토리 이동 범위 | ✅ **🅰️ 지금은 지도(S0–S2)까지.** 실제 이동(S3–S5)은 F1(facade) 완료 후 별도 세션 | §3.7 |
| **Q4** | Lookback semantics | ✅ **`rows`와 `calendar` 두 종류.** 제안했던 `sessions`(거래일)는 **폐기** | §3.1 |

### Q4는 제안이 정정된 것이다 — 이유를 기록한다

이 문서 초판은 `sessions`(거래일 N개) + `duration`(timedelta)을 제안했다. **사용자가 이를 정정했다:**

> "3개월 전이라고 하면 모두 calendar를 생각하지 trading day로 생각하는 사람 없음."

확정된 두 축은 다음과 같다.

1. **`rows`** — 데이터 그대로 몇 행을 볼 것인지. **date semantics 없음.**
2. **`calendar`** — 현재 date에서 달력 기준으로 이동한 date부터. **거래일 아님.**

**이 결정이 초판 제안보다 나은 점이 하나 더 있다.** `sessions`는 거래일을 세기 위해
`observation_time_field` 등록을 **전제 조건으로 요구**했다. `rows`(available_at 정렬 상위 N행)와
`calendar`(available_at 비교)는 **둘 다 그 필드를 요구하지 않는다.** 즉 lookback이 dataset
registration에 새로운 필수 조건을 만들지 않는다 — PRD §7.2 minimal registration 원칙에 더 맞다.

Architecture §7(`architecture.md:1015`)의 원문도 *"lookback은 **rows**와 duration semantics를
구분하며"* 였다. `rows`는 원래 설계에 있던 축이고, 초판이 이를 `sessions`로 잘못 좁혔다.

---

## 0. "ideal"의 판정 기준

무엇이 이상적인지는 취향이 아니라 이 프로젝트가 이미 선언한 것으로부터 나온다. 아래 네 기준을
순서대로 적용한다. **앞 기준이 뒤 기준을 이긴다.**

| # | 기준 | 근거 | 위반 시 |
|---|---|---|---|
| **K1** | PRD 정합 | PRD가 정본이다 (`architecture.md:11`) | 그 fix는 후보에서 탈락한다 |
| **K2** | 불변식 보존 | I1–I11 (`architecture.md:444-457`) | 재현성·권한 경계가 깨진다 |
| **K3** | Mental-model 대응 | 사용자가 제기한 문제 자체 | cognitive debt가 남는다 |
| **K4** | 가역성과 비용 | YAGNI, 되돌릴 수 있는가 | 잘못된 추상화가 고착된다 |

**K1이 K3을 이기는 사례가 실제로 하나 있다.** §3.3(MM-03)을 보라 — 사용자의 mental model이
PRD §2.4와 어긋나는 지점이 있고, 그 경우 PRD를 따른다.

**K4가 K3을 이기는 사례도 있다.** §3.10(MM-10) — "Exchange를 고를 수 있어야 한다"는 직관은
자연스럽지만, 구현이 하나뿐인 축에 Protocol을 뽑는 것은 speculative generality다.

---

## 1. 문제의 재분류 — 고치는 *방식*이 세 종류다

session 1은 `CODE / DOC / DEBT`로 분류했다. 수정 관점에서는 다른 축이 더 유용하다.

| 계열 | 정의 | 해당 finding | 고치는 방법 |
|---|---|---|---|
| **A. 진실 정렬** | 코드가 옳고 문서/설명이 과장 또는 침묵 | MM-02(부분), MM-05, MM-09, MM-10 | 문서를 코드에 맞춘다. **코드를 건드리지 않는다** |
| **B. 계약 결손** | 선언된 계약이 코드에 없다 | MM-01, MM-03, MM-06 | 계약을 구현하거나, 선언을 철회한다 |
| **C. 구조 부채** | 계약은 맞지만 배치가 이해를 방해 | MM-04, MM-07, MM-08 | 옮긴다. semantics는 안 바뀐다 |

**이 분류가 중요한 이유:** 계열 A는 위험이 0이고 오늘 끝낼 수 있다. 계열 C는 위험이 중간이고
순서가 중요하다. 계열 B만이 진짜 설계 판단을 요구한다. **A → C → B 순으로 접근하는 것이
이상적이다** — B를 먼저 하면 구조가 흔들리는 위에 계약을 얹게 된다.

---

## 2. 가장 높은 레버리지는 코드 변경이 아니다

사용자가 말한 문제는 기능 부족이 아니라 **cognitive technical debt**다:

> "내가 세부적인 모든 것을 알지는 못하더라도, 현재의 src/ 하의 모듈 구조가 어떻게 되어있고
> 어떤 것이 어떤 역할을 하고 그게 큰 구조에서 어떻게 흘러간다 이런건 알 수 있어야 해."

MM-05, MM-09는 **PRD가 이미 정확히 명시**하고 있는데도 사용자가 놓쳤다. PRD가 1,853줄이고
architecture가 2,919줄이기 때문이다. 여기에 문장을 더 추가하는 것은 해결이 아니다.

**따라서 이 remediation의 첫 산출물은 코드가 아니라 문서 하나여야 한다.**

### R0 — `docs/current-support-map.md` (신규, 1페이지)

"지금 실제로 무엇이 되는가"만 답하는 표. PRD/architecture를 요약하지 않고 **참조만** 한다.

```
| 하고 싶은 것              | public entry point        | 지원 | 제약                          | 근거 |
| long-only daily backtest  | project.run_daily()       | ✅   | gross ≤ 1, weight ≥ 0         | PRD §11.2 |
| long-short backtest       | project.run_academic()    | ✅   | zero-friction, hypothetical만 | PRD §4.2 |
| 비용 있는 long-short      | —                         | ❌   | out of scope                  | PRD §17 |
| constraint를 적용한 백테스트 | —                      | ❌   | adjust는 loop 밖 별도 오퍼레이션 | §3.3 |
| ensemble                  | qlibx.flow.CompositionFlow| 🟡   | facade 없음                    | §3.4 |
| 실시간 constraint 감시     | —                         | ❌   | monitor는 사후 checkpoint 평가 | PRD §11.5 |
| Strategy가 cadence 선언    | —                         | ❌   | caller가 decision_times 제공   | §3.2 |
| lookback 선언              | —                         | ❌   | history() 전량 후 사용자 절단   | §3.1 |
```

비용: 반나절. 위험: 0. **이것 하나가 MM-02·MM-05·MM-09·MM-10의 사용자 측 문제를 전부 해소한다.**
남는 것은 문서 자체의 정정(§3.2, §3.10)과 진짜 설계 결정(§3.1, §3.3, §3.6)뿐이다.

---

## 3. Finding별 ideal fix 분석

각 절의 형식: **본질 → 이상적 종착점 → 선택지 → 권고와 근거 → 불변식 영향 → 검증**

---

### 3.1 MM-01 — Lookback (계열 B)

#### 본질

Architecture §7 "조회 창구 계약"(`architecture.md:1000-1016`)은 **명시적으로** 이렇게 선언한다:

```python
class PanelView(Protocol):
    def panel(self, binding: ResolvedBinding, lookback: Lookback) -> DataFrame: ...
```
> `lookback`은 rows와 duration semantics를 구분하며 질의에 그대로 반영되어 조회량을 한정한다.
> 초안의 "bounded load 사전 선언"은 불필요해진다 — **조회 자체가 한정적이다.**

Current code에는 `Lookback` 타입도, `panel()`도, window 파라미터도 없다.
**설계 문서가 약속한 계약이 통째로 미구현이다.** PRD는 이 shape를 강제하지 않으므로 PRD 위반은
아니지만, architecture는 이것을 "actual"이 아니라 "계약"으로 서술했다.

#### 이상적 종착점

architecture §7의 명제 — *"역할 경계는 view 구성이 결정한다"* — 를 **시간축에도** 적용한다.
현재 역할 경계는 두 축에만 걸려 있다:

```
어떤 dataset/role?  → ResolvedBinding이 결정. 미선언 role은 ViewAccessError.
언제까지?           → clock.now가 결정. 우회 불가.
언제부터?           → ❌ 경계 없음. 전량 노출.
```

이상적으로는 세 번째 축도 `ResolvedBinding`에 실려야 한다. 그러면 Strategy는 **선언한 window
밖을 물리적으로 읽을 수 없다** — 미선언 role을 읽을 수 없는 것과 같은 방식으로.

#### 선택지

| | 설계 | 얻는 것 | 잃는 것 |
|---|---|---|---|
| **A** | query-time only: `view.history(role, lookback=…)` | 성능. 5줄 | 경계가 아니라 편의 기능. Strategy가 안 쓰면 그만 |
| **B** | declaration-time only: `ComponentRequirement.window` + resolver가 coverage 검증 | 계산 전 실패 (PRD §7.3) | 조회는 여전히 전량 |
| **C** | 선언 + 강제: window를 `ResolvedBinding`에 싣고 `_read`가 적용 | 진짜 경계. 성능. 사전 검증. evidence | `AccessRecord` 스키마 변경 |

#### 권고: **C** — 확정 (Q4)

A는 경계가 아니다 — Strategy가 인자를 안 넘기면 무력화된다. K3(mental model: "특정 lookback으로
subscribe")도 만족 못 한다. B는 절반이다.

#### 확정된 타입 shape

```python
class RowsLookback(QlibxModel):
    """instrument별 최근 N행. date semantics 없음."""
    kind: Literal["rows"] = "rows"
    rows: int = Field(gt=0)

class CalendarLookback(QlibxModel):
    """as_of의 달력 date에서 역산한 시작 date부터. 거래일이 아니다."""
    kind: Literal["calendar"] = "calendar"
    years: int = Field(default=0, ge=0)
    months: int = Field(default=0, ge=0)
    days: int = Field(default=0, ge=0)
    calendar_timezone: str = Field(min_length=1)
    month_end_policy: Literal["clamp_to_month_end"]

Lookback = Annotated[RowsLookback | CalendarLookback, Field(discriminator="kind")]

class ComponentRequirement(QlibxModel):
    ...
    lookback: Lookback | None = None   # optional → 기존 전략 전부 호환

class ResolvedBinding(QlibxModel):
    ...
    lookback: Lookback | None = None   # resolver가 그대로 전달
```

상한(`available_at <= as_of`)은 clock이 계속 소유한다. Lookback은 **하한만** 추가한다.
경계는 양쪽 모두 inclusive다: `window_start <= available_at <= as_of`.

#### `rows` semantics

`available_at` 내림차순 상위 N행을 **instrument별로** 취한다.

- 종목마다 기간이 다를 수 있다 (**ragged panel**). 이는 결함이 아니라 의도다 — 신규상장,
  거래정지, 데이터 결측을 별도 처리 없이 흡수한다.
- N행에 못 미치는 종목은 **있는 만큼만** 반환하고 **실패시키지 않는다.** IPO 직후 종목이
  20행이 없는 것은 정상이다.
- 대신 `AccessRecord`에 부족 사실을 기록한다 — PRD §4.6("조용히 skip 금지")은 실패를 요구하는
  것이 아니라 **관측 가능성**을 요구한다.

```python
class AccessRecord(QlibxModel):
    ...
    lookback_kind: str | None = None
    lookback_window_start: datetime | None = None     # calendar일 때만
    lookback_rows_requested: int | None = None        # rows일 때만
    instruments_below_window: int = 0                 # rows일 때 N행 미만 종목 수
    instruments_below_window_examples: tuple[str, ...] = ()   # bounded, 최대 20개
```

#### `calendar` semantics

```
window_start_date = calendar_shift(as_of.astimezone(tz).date(), -(years, months, days))
window_start      = window_start_date의 00:00:00 in tz  →  UTC로 변환
```

`timedelta`가 아니라 **달력 산술**이다. `days`는 순수 일수 가산이지만 `months`/`years`는
월/연 단위 이동이다. 따라서 명시적 규칙이 필요하다.

| 입력 | 결과 | 규칙 |
|---|---|---|
| 2024-03-31 − 1개월 | 2024-02-29 | 2월 31일이 없으므로 **월말로 clamp** |
| 2023-03-31 − 1개월 | 2023-02-28 | 평년 clamp |
| 2024-02-29 − 1년 | 2023-02-28 | 윤일 clamp |
| 2024-03-31 − 30일 | 2024-03-01 | `days`는 단순 가산 |

`month_end_policy`를 **명시 필수 필드**로 둔 이유가 이것이다. 지금은 값이 하나뿐이지만,
규칙을 코드 안에 숨기면 PRD §4.7("config는 의미를 선언한다")을 어긴다. 나중에 다른 관행이
필요하면 `Literal`에 값을 추가한다.

`calendar_timezone`도 명시 필수다. `as_of`는 UTC인데 "3개월 전"의 기준 date는 KST일 수도
US/Eastern일 수도 있다. **추측하지 않는다.** dataset의 `source_timezone`이나 profile의
`session_timezone`을 자동 상속하지 않는 이유는, 셋이 서로 다를 수 있고 어느 것이 경제적으로
옳은지는 사용자만 알기 때문이다(PRD §5.3).

새 dependency는 도입하지 않는다. `dateutil.relativedelta` 없이 `calendar.monthrange`로
12줄이면 충분하다.

#### 두 종류의 사전 검증 가능성이 다르다 — 중요

| | 계산 전 검증 | 근거 |
|---|---|---|
| **`calendar`** | ✅ 가능 | `RegistrationEvidence.available_at_min`(`data/contracts.py:84`)이 이미 있다. resolver가 `available_at_min <= first_evaluation_time - window`를 **소스 스캔 없이** 확인한다 |
| **`rows`** | ❌ 불가 | registration evidence는 종목별 행 수를 담지 않는다. 조회 시점에야 알 수 있다 |

이 비대칭을 설계에 그대로 반영한다.

```
calendar 부족  →  resolve 단계에서 OperationError. run() 호출 안 함.       (PRD §7.3)
rows 부족      →  실패 아님. 있는 만큼 반환 + AccessRecord에 기록.          (PRD §4.6)
```

`rows`를 억지로 사전 검증하려고 registration에 종목별 행 수를 저장하면, minimal registration
계약(PRD §7.2)이 무거워지고 소스가 바뀔 때마다 stale해진다. **하지 않는다.**

#### 불변식 영향

- **I2 강화** — 시간축 하한이 질의에 박히므로 우회 경로가 하나 더 막힌다.
- **I8 강화 (calendar 한정)** — requirement resolution이 커버리지를 판정한다.
- **I5, I7 무영향.**

#### 위험과 선결 조건

`AccessRecord`에 필드가 추가되면 `strategy_result` payload shape가 바뀐다. **선결 확인 필요:**
catalog가 payload를 schema hash로 검증하는가? 검증한다면 `strategy_result:v3`가 필요하고,
v2 reader를 남겨야 한다(`StrategyResultV1`이 이미 그 선례다 — `operations/strategy.py:99`).

`observation_time_field` 등록은 **어느 lookback에도 필요 없다.** `rows`는 `available_at` 정렬,
`calendar`는 `available_at` 비교만 쓴다. 초판의 `sessions` 제안이 만들던 전제 조건이 사라졌다.

#### 검증

1. **`rows`** — 3종목 중 하나만 5행, 나머지는 50행. `rows=20` 선언 시 5행 종목은 5행 그대로
   반환되고 `instruments_below_window == 1`이 기록된다. 실패하지 않는다
2. **`calendar` clamp** — `as_of=2024-03-31`, `months=1` → `window_start_date == 2024-02-29`
3. **`calendar` 커버리지 부족** — `available_at_min`이 window_start보다 늦으면
   `run()` 호출 없이 `OperationError`
4. **timezone** — 같은 `as_of`(UTC)에 `calendar_timezone`을 KST/UTC로 바꾸면 window_start가
   달라지는 것이 관측된다
5. **동등성** — lookback 유/무로 같은 전략 실행 시 계산 결과 동일, `AccessRecord.row_count` 감소
6. **성능** — 3,000종목 warm query before/after 기록

---

### 3.2 MM-02 — Strategy-owned cadence (계열 A + B)

#### 본질 (session 1 §0 정정 반영)

Entry/exit 조건 자체는 같은 `DECISION` callback에서 `HOLD`/`TARGET`으로 표현할 수 있다.
없는 것은 **Strategy가 자기 cadence를 선언하는 계약**이다.

PRD를 읽으면 판단이 갈린다:

- **§9.8**: *"Calendar, data arrival, fill feedback 또는 user event가 decision을 trigger할 수
  있다. … **특정 event class나 callback method는 PRD가 정하지 않는다**"* → caller 소유도 허용
- **§9.6**: *"독립 clock은 별도 Clock object를 의무화한다는 뜻이 아니라, **monitoring cadence와
  frozen evaluation time이 Strategy decision cadence에 종속되지 않는다**는 뜻"* → cadence의
  소유자를 규정하지 않음

**PRD는 이 축에 대해 침묵한다.** 따라서 K1은 어느 쪽도 배제하지 않고 K3·K4가 결정한다.

#### 선택지

| | 설계 | 평가 |
|---|---|---|
| **A** | 현행 유지 + 문서 정정 | K4 최고. K3 미해소 |
| **B** | `StrategyOperation`에 optional `schedule()` 추가. 반환값으로 `decision_times` 생성 | K3 해소. Strategy가 캘린더를 알아야 함 |
| **C** | Strategy가 `EventSpec`을 Clock에 등록 (Flow 경유) | 완전한 IoC. 비용·위험 큼 |

#### 권고: **A (지금) + B (조건부 미래)**

**지금 A인 이유는 두 가지다.**

첫째, **B는 캘린더 문제를 전략으로 밀어낸다.** "매월 20일"은 거래일 캘린더 없이 계산할 수 없다.
현재 캘린더는 `session_closes` tuple로 caller가 제공한다. `schedule()`이 캘린더를 받으려면
`schedule(calendar) -> tuple[datetime, ...]` 형태가 되는데, 이는 사실상 caller가 하던 일을
Strategy로 옮긴 것에 불과하고 **frozen invocation 지문(K2/I7)이 Strategy 코드에 의존**하게 된다.
`DailyRunRequest.compatibility_json()`이 schedule을 포함하는 현재 구조가 오히려 재현성에 유리하다.

둘째, **C는 지금 `MATERIALIZE` 같은 미구현 event를 전제**한다. Event channel이 4개로 고정된
상태에서 등록 API만 여는 것은 빈 확장점이다.

**전환 조건 (미래에 B를 도입할 시점):** 같은 Strategy를 3개 이상의 cadence로 돌리는 실제
workload가 생기고, 거래일 캘린더가 dataset으로 등록되어 `ComponentRequirement`로 resolve될 때.
그때는 `schedule(view) -> tuple[datetime, ...]`가 자연스러워진다 — view를 통하므로 PIT과
lineage가 유지되기 때문이다.

#### 지금 할 일

architecture §3 표 아래에 한 문단: *"Decision cadence는 Strategy가 아니라 invocation이 소유한다.
`DailySimulationSpec.decision_times`가 정본이며 frozen fingerprint에 포함된다. Entry/exit 조건은
같은 DECISION callback에서 `DecisionAction.HOLD`/`TARGET`으로 표현한다."*

---

### 3.3 MM-03 — Constraint가 loop 밖에 있다 (계열 B) ★ 가장 중요

#### 본질 — 그리고 사용자 mental model의 정정

사용자는 이렇게 말했다:

> "constraint optimizer는 **strategy 내부에서** weight를 냈을 때 그것을 constraint에 맞도록
> 조정해주는 거야"

**PRD §2.4는 이를 명시적으로 반대 위치에 둔다:**

> "Constraint adjustment와 pre-execution validation은 **이 downstream execution path에 속한다.**
> Constraint monitoring은 actual account를 읽는 independent observer이며…"

즉 adjustment는 **Strategy 안이 아니라 Strategy 뒤, execution 앞**이다. K1이 K3을 이기는 지점이다.
Strategy 안에서 clip하면 (a) original signed intent가 소실되고, (b) PRD §2.1의
*"실제 운용 portfolio가 long-only여도 original signed alpha를 덮어쓰지 않는다"* 를 위반한다.

#### 진짜 문제는 hook 하나가 아니다

PRD가 규정하는 decision→execution 사이의 정본 체인은 다음과 같다 (§3.2 result categories):

```
signed alpha weights
  → [portfolio construction]        → Executable physical target
  → [constraint adjustment]         → Constraint-adjustment result (residual 보존)
  → [pre-execution validation]      → Pre-execution validation finding
  → [order conversion]              → Requested orders + conversion evidence
  → execution
```

Current `DailyExecutionFlow`는 이 다섯 단계를 **둘로 접었다**:

```
weights → DecisionIntent → size_session_orders → match_batch
          (flow/daily.py:861)   (:1000)            (:1032)
```

`PortfolioConstructionFlow`, `ConstraintFlow.adjust`, `ConstraintFlow.validate`는 **전부 존재하고
전부 artifact 기반으로 동작**한다. 다만 loop 안에서 호출되지 않는다.

**따라서 MM-03의 이상적 fix는 "constraint hook 추가"가 아니라 "접힌 체인을 펴는 것"이다.**

#### 선택지

| | 설계 | K1 | K3 | K4 |
|---|---|---|---|---|
| **A** | 문서 축소. architecture §3의 `optional construct/adjust/convert/validate` 서술을 삭제 | ✅ | ❌ | ✅✅ |
| **B** | Strategy가 `qlibx.portfolio.adjust_single_name_caps`를 직접 호출 | ❌ PRD §2.1/§2.4 위반 | 🟡 | ✅ |
| **C** | `DailyExecutionProfile`에 optional `decision_pipeline` 추가. `_on_decision`이 construct→adjust→validate를 순서대로 실행하고 각 단계를 artifact로 발행 | ✅ | ✅ | ❌ |
| **D** | 2단계: 먼저 pipeline **계약**을 `DecisionIntent` 생산 지점에 정의하고, 구현은 pass-through 한 개로 시작 | ✅ | ✅ | 🟡 |

#### 권고: **D → C** — 확정 (Q1)

B는 탈락이다 (K1). A는 정직하지만 제품 능력을 영구히 포기한다 — PRD §10.3, §11.3이 요구하는
capability다.

**D의 핵심 아이디어:** 지금 필요한 것은 constraint 구현이 아니라 **자리**다.

```python
class DecisionStage(Protocol):
    stage_id: str
    def requirements(self) -> tuple[ComponentRequirement, ...]: ...
    def apply(self, candidate: DecisionCandidate, view: DecisionStageView) -> DecisionCandidate: ...
```

`_on_decision`이 Strategy weight로 `DecisionCandidate`를 만들고, profile이 선언한 stage 목록을
순서대로 통과시킨 뒤 마지막 candidate로 `DecisionIntent`를 만든다. Stage가 0개면 **현재 동작과
바이트 단위로 동일**하다.

이 구조가 이상적인 이유:

1. **PRD §3.2의 result category가 stage 출력에 1:1 대응**한다 — 각 stage가 자기 artifact를 낸다.
2. `requirements()`를 갖고 있으므로 **benchmark weight 같은 PIT 데이터를 stage가 스스로 요구**할
   수 있다. UC-CONSTRAINT-002("no-short + PIT benchmark weight")가 loop 안에서 성립한다.
3. **기존 pure 함수를 그대로 재사용**한다 — `adjust_single_name_caps`,
   `validate_single_name_caps`, `construct_portfolio`는 전부 순수 함수이고 이미 존재한다.
   Stage는 얇은 어댑터다.
4. Stage가 0개인 경로가 현행과 동일하므로 **회귀 위험이 격리**된다.

#### 반드시 함께 설계해야 하는 것

- **Recovery.** Stage가 artifact를 발행하면 `_publish_recovery_point`의 `pending_publications`에
  들어가야 한다(`flow/recovery.py:22`의 `RecoveryPublication.artifact_type`은 현재 3종 Literal —
  확장 필요). **이것이 §3.8(MM-08) recovery 추출을 먼저 해야 하는 이유다.**
- **실패 semantics — 확정 (Q2).** Validation이 breach를 찾아도 **decision을 실패시키지 않는다.**
  Finding을 typed artifact로 발행하고 execution은 그대로 진행한다. Profile switch는 두지 않는다.

  근거는 두 가지다. 첫째, PRD §4.6은 *"actual breach를 계산 failure로 숨기지도 않는다"* 고 하며
  breach를 **failure가 아닌 별도 result type**으로 규정한다. 둘째, breach에는 주문으로 생긴 것과
  가격 drift로 생긴 것 두 종류가 있는데 **adjust는 주문만 조정할 수 있다.** HOLD인 날 급등으로
  cap을 넘는 것은 조정 대상이 아니며, 이때 run을 중단시키면 장기 백테스트가 성립하지 않는다.

  따라서 stage의 반환 계약은 다음과 같다.

  ```
  adjust    → 조정된 candidate + before/after + unresolved residual   (실패 아님)
  validate  → finding (measured / bound / excess / eligibility)        (실패 아님)
  둘 다     → 계산 자체가 불가능할 때만 OperationError                 (예: benchmark 데이터 없음)
  ```

  `run_daily()`의 최종 `OperationOutcome`은 breach가 있어도 `COMPLETE`이며, finding artifact가
  증거로 남는다. **Breach 유무를 outcome status로 판단하면 안 된다** — finding을 읽어야 한다.
  나중에 profile switch가 필요해지면 그때 추가한다(되돌리기 쉬운 결정).
- **Fingerprint.** stage 구성이 `DailyExecutionProfile.compatibility_json()`에 들어가야 I7이 유지된다.

#### 지금 하지 말아야 할 것

`_on_decision`에 constraint 호출을 직접 인라인하는 것. 2,468줄 파일에 200줄을 더하고
recovery/fingerprint/실패 semantics를 임시방편으로 처리하게 된다.

---

### 3.4 MM-04 — Facade 비대칭 (계열 C) ★ 비용 대비 효과 최고

#### 본질 — 이건 ergonomics가 아니라 correctness다

session 1은 이것을 "일관성 결함"으로 적었다. 재조사 결과 **더 심각하다.**

`QlibxProject`의 모든 public operation은 `_with_catalog_session()`(`project.py:503`)을 통과한다:

```python
with self.artifacts.session(), self._store.frozen():
    return callback()
except CatalogSessionConflictError as exc:
    return self._catalog_scope_failure(...)   # → typed OperationOutcome
```

이것이 세 가지를 한다:

1. **DuckDB 단일 연결 세션** — operation 전체가 하나의 catalog 연결을 공유
2. **`store.frozen()`** — 물리 소스 SHA-256을 invocation당 한 번만 검증
   (`data/store.py:60`; 없으면 **매 query마다 파일 전체 해싱**)
3. **`CatalogSessionConflictError` → typed `OperationOutcome` 번역**

`CompositionFlow` / `PortfolioConstructionFlow` / `AnalysisFlow`를 직접 쓰면 **셋 다 없다.**
확인: `grep "session()\|frozen()" src/qlibx/resources/samples/*/run.py` → **결과 없음.**
번들 sample들이 이 경로를 그대로 시연하고 있다.

3번은 **PRD §2.6 위반**이다 — catalog 충돌 시 machine-readable failure 대신 raw exception이 나간다.

#### 이상적 종착점

`QlibxProject`가 **유일한 public composition root**다. `qlibx.flow`는 내부 구현이 된다.
Architecture §12가 이미 이렇게 규정한다: *"project → operation별로 필요한 concrete flow/backend
(public composition root)"*.

```python
# 추가할 facade
def run_ensemble(self, definition, invocation) -> OperationOutcome
def invoke_stored_signal_strategy(self, *, artifact_id, strategy_id, weighting, invocation) -> OperationOutcome
def construct_portfolio(self, request) -> OperationOutcome
def analyze_simulation(self, request) -> OperationOutcome
def analyze_monitoring(self, request) -> OperationOutcome
def analyze_signal(self, request) -> OperationOutcome
def render_report(self, request) -> OperationOutcome
```

전부 기존 flow를 `_with_catalog_session`으로 감싸는 5–8줄짜리다. **새 로직 0줄.**

#### 권고: **즉시 실행. 순서상 첫 코드 변경.**

이유:

- K1 ✅ (PRD §1.2 public surface, §2.6 machine-readable failure)
- K2 무영향
- K3 ✅ — 사용자가 "무엇을 할 수 있나"를 `dir(QlibxProject)` 하나로 알 수 있게 된다
- K4 ✅ — 순수 추가. 기존 경로 전부 유지
- **그리고 §3.7(MM-07)의 선결 조건이다** — public surface가 `qlibx.*` 하나로 좁혀져야
  내부 디렉토리 이동이 breaking change가 아니게 된다

함께 할 것: sample들을 facade 경유로 고치고, `qlibx/__init__.py`에 `EnsembleDefinition`,
`PortfolioConstructionRequest` 등 **request 타입만** 재수출한다 (Flow 클래스는 재수출하지 않는다).

---

### 3.5 MM-05 / MM-09 — mental-model correction (계열 A)

#### 본질

둘 다 PRD가 이미 정확히 명시한다 (MM-05: §4.2/§15.3/§17, MM-09: §11.5).
**코드 결함도 문서 결함도 아니다.** 사용자가 2,900줄 문서에서 놓친 것이다.

#### 권고: **PRD를 고치지 않는다. R0(§2)로 흡수한다.**

PRD에 "이건 안 됩니다"를 더 쓰면 문서가 길어져 같은 문제가 재발한다. 이상적 처리는
**정본은 그대로 두고, 정본을 가리키는 1페이지 색인을 만드는 것**이다.

추가로 architecture §2.4 layer 표 옆에 한 줄: *"`MONITOR` event(daily flow 내부)와
`monitor_constraints()`(standalone operation)는 다른 것이다"* — 같은 단어가 두 뜻이라
혼동이 구조적이기 때문이다.

---

### 3.6 MM-06 — 전량 미체결이 feedback에 없다 (계열 B) ★ session 1 제안 폐기

#### 본질

`flow/daily.py:1050`이 `dealt_quantity == 0`인 Fill을 `FillBatch`에서 제외한다. 결과적으로
"주문했는데 한 주도 못 샀다"가 다음 decision에 보이지 않는다. PRD §2.4의
*"Blocked order와 transaction cost가 다음 decision에 영향을 줄 수 있다"* 가 blocked 쪽에서 성립하지 않는다.

#### session 1의 P3은 틀렸다

P3은 *"`FillBatch`에 zero-dealt를 함께 commit하거나 `JournalEntry`에 `blocked` 필드 추가"* 였다.
**둘 다 나쁘다:**

- zero-dealt Fill을 commit하면 **체결되지 않은 것을 Fill이라 부르게 된다.** PRD §4.6이
  금지하는 "다른 것을 같은 타입으로 숨기기"다.
- `JournalEntry`에 `blocked`를 넣으면 **Account journal이 account change가 아닌 것을 담는다.**
  I4("Account는 actual state의 authority")와 I9("actual과 intended는 다른 typed evidence")를
  둘 다 흐린다. 게다가 `AccountCheckpoint` 스키마가 바뀌어 recovery 호환성이 깨진다.

#### 이상적 종착점 — 이미 있는 패턴을 복제한다

`StrategyView`에는 **똑같은 문제를 이미 해결한 선례**가 있다. `latest_session_performance()`다:

```python
# flow/daily.py:784 — Flow가 직전 published artifact를 view에 주입
session_performance=self._session_performance[-1] if self._session_performance else None
```
```python
# context/scoped.py:424 — view가 노출하고 access를 기록
def latest_session_performance(self) -> SessionPerformanceRecordState:
    if self._session_performance is None:
        raise ViewAccessError("this view has no completed session performance")
    self._performance_accessed.append(SessionPerformanceAccessRecord(...))
```

`ExecutionEvidence`는 **이미 발행되고 있고, 이미 `diagnostics: tuple[FillDiagnosticEvidence, ...]`를
담고 있다**(`flow/daily.py:1122`, reasons 포함). Flow는 그것을 `self._executions`에 들고 있다.

**따라서 이상적 fix:**

```python
# context/scoped.py
class ExecutionResultAccessRecord(QlibxModel):
    artifact_id: str
    event_id: str
    decision_id: str
    event_time: datetime

class StrategyView(_AccountStateView):
    def latest_execution_result(self) -> ExecutionResultState: ...
    def execution_result_accessed(self) -> tuple[ExecutionResultAccessRecord, ...]: ...
```

```python
# flow/daily.py::_on_decision
latest_execution=self._executions[-1] if self._executions else None
```

`strategy_accesses_are_path_dependent()`(`operations/strategy.py:159`)에 새 access를 포함시킨다.

#### 왜 이것이 이상적인가

| 기준 | 평가 |
|---|---|
| **K1** | ✅ Account는 actual state만, ExecutionEvidence는 execution outcome — PRD §3.2 category 분리 유지 |
| **K2** | ✅ I4/I9 **강화**. Account 스키마·checkpoint 무변경 |
| **K3** | ✅ 부분체결·전량미체결·비용·사유가 **한 객체**로 보인다. 사용자 mental model보다 오히려 풍부 |
| **K4** | ✅ 기존 패턴 복제. Account/recovery 미접촉 |

`AccessRecord` 한 종류와 `StrategyResult` 필드 하나가 늘어나므로 §3.1과 **같은 스키마 버전 이슈를
공유한다** → 두 변경을 **한 번의 `strategy_result:v3`로 묶는 것이 이상적이다.**

#### 검증

1. 현금 부족으로 BUY가 전량 clip → 다음 decision의 `latest_execution_result().diagnostics`에
   reason과 `requested/dealt`가 보임
2. 그 Strategy의 `path_dependent`가 자동으로 True (선언 안 해도 관측으로 잡힘)
3. execution이 한 번도 없었던 첫 decision → `ViewAccessError`

---

### 3.7 MM-07 — 디렉토리 semantics (계열 C)

#### 본질 (session 1 §0 정정 반영)

rename은 **낮은 비용이 아니다.** import, samples, tests, docs, installed compatibility가 얽힌다.

#### 이상적 종착점

```
src/qlibx/
  __init__.py     ← 유일한 public import surface
  project.py      ← composition root
  cli.py
  specs/          ← frozen invocation DTO      (academic.py, constraints.py, simulation.py)
  kernel/         ← clock, event, queue
  view/           ← ③ (현 context/)
  data/           ← registration, resolution, store
  operations/     ← ④ 순수 계산   (strategy, materialization, portfolio, execution, analysis)
  account/        ← ⑤
  evidence/       ← ⑥
  flow/           ← ②
  extensions/
  resources/
  domain.py  models.py  errors.py
```

**핵심은 이름이 아니라 규칙이다:** *"디렉토리 = layer, 파일 = 개념, 같은 개념이 여러 layer에
나타나면 파일 이름을 같게 두고 패키지로 구분한다."* 이 규칙 하에서는
`specs/constraints.py` / `operations/portfolio/constraints.py` / `flow/constraints.py`가
**혼란이 아니라 정보**가 된다 — import 줄이 layer를 알려준다.

#### 순서가 전부다

| 단계 | 내용 | 위험 | 선결 |
|---|---|---|---|
| **S0** | `docs/module-map.md` — 현재 파일 → layer/역할 매핑표 | 0 | 없음 |
| **S1** | `qlibx/__init__.py`를 완전한 public surface로. samples/tests를 `qlibx.*`로 전환 | 낮음 | **§3.4 (MM-04)** |
| **S2** | 문서 정정: architecture §12가 `execution/`에 executor가 있다고 한 부분 — 실제는 `flow/daily.py:356` | 0 | 없음 |
| **S3** | top-level DTO 3개 → `specs/`. 구 경로에 re-export shim | 낮음 | S1 |
| **S4** | `context/` → `view/`. 구 경로 shim 1버전 | 중간 | S1, S3 |
| **S5** | `portfolio/`, `execution/`, `analysis/` → `operations/` 하위 | 중간 | S4 |

**S1이 전체의 열쇠다.** public surface가 `qlibx.*`로 좁혀지면 S3–S5는 **내부 이동**이 되어
breaking change가 아니게 된다. S1 없이 S4를 하면 사용자 코드가 깨진다.

#### 권고 — 확정 (Q3)

**S0–S2를 먼저 하고, S3–S5는 F1(facade) 완료 후 별도 세션으로 분리한다.** S0만으로도 사용자의
cognitive debt는 상당 부분 갚인다 — 이름이 나빠도 지도가 있으면 길을 잃지 않는다.

이번 범위는 **S0, S1, S2까지**다. S1은 F1의 일부로 함께 수행한다(§3.4 참조).

부수 항목:
- `kernel/clock.py` → 패키지 유지 (architecture §5가 Event/Queue를 kernel에 둔다)
- `production/` (docstring 1줄 빈 패키지) → 삭제. 부재는 코드가 아니라 문서로 표현한다
- `context/scoped.py` 536줄 → `view/records.py`(AccessRecord 8종) + `view/views.py` + `view/gate.py`

---

### 3.8 MM-08 — `flow/daily.py` 2,468줄 (계열 C)

#### 본질

Architecture alignment 표가 이미 부채로 인정하고 전환 조건을 걸었다:
*"둘 이상의 phase가 독립 테스트·재사용 경계를 갖거나 변경 충돌이 반복될 때."*

#### 전환 조건은 충족되었는가 — 정확히 따져보자

session 1은 *"`AcademicExecutionFlow`도 checkpoint/resume을 구현하므로 두 번째 소비자"* 라고
적었다. 재조사 결과 **정확하지 않다.** Academic은 `AcademicCheckpoint`라는 **별도 타입**을 쓰고
(`flow/academic.py:65`), `SimulationRecoveryPoint`(v2, delta 기반)와 구조가 다르다.

공유되는 것은 **타입이 아니라 프로토콜**이다:

```
1. candidate state 계산 (아직 commit 안 함)
2. durable checkpoint 발행         ← "authority boundary. Advance only after it is durable" (academic.py:306)
3. authority commit
4. candidate와 실제 결과 비교      ← RECOVERY_CANDIDATE_DIVERGED (daily.py:1212, 1237)
```

Daily는 이 4단계를 **세 번**(account, memory, execution artifact) 수행하고, academic은 **한 번**
수행한다. **같은 프로토콜의 두 번째 구현이 이미 존재한다** — 조건 충족이다. 다만 추출 대상은
"recovery 코드"가 아니라 **이 4단계 프로토콜**이다.

#### 이상적 종착점 — 기계적 분리가 아니라 상태를 가진 협력자 추출

Architecture가 경고한다: *"기계적 파일 분리는 control flow를 숨긴다."* 따라서 helper 모음이 아니라
**자기 상태를 가진 객체**를 뽑는다.

`DailyExecutionFlow`가 들고 있는 recovery 전용 상태 6개:

```python
self._recovery_sequence
self._previous_recovery_artifact_id
self._recovery_journal_cursor
self._recovery_trace_cursor
self._recovery_completed_cursor
self._resume_position
```

**이것이 응집된 객체 하나다.** Extract Class의 교과서적 신호 — 필드 묶음과 그것만 만지는
메서드 묶음(`_publish_recovery_point`, `_restore_recovery_point`, `_pending_recovery`,
`_recovery_publication`, `_memory_recovery_publication`)이 같이 있다.

```python
class DurableRunJournal:
    """Own recovery sequence, cursors, and the publish-before-commit boundary."""
    def publish(self, *, event, account_checkpoint, ..., pending_publications) -> str | None
    def restore(self, *, run_id, fingerprints, strategy_id) -> RestoredPosition | None
    def commit_barrier(self, candidate, actual) -> None   # RECOVERY_CANDIDATE_DIVERGED
```

`DailyExecutionFlow`와 `AcademicExecutionFlow`가 생성자로 주입받는다.

#### 추출 순서

| 순위 | 대상 | 줄수 | 근거 |
|---|---|---|---|
| 1 | `DurableRunJournal` (recovery 6상태 + 5메서드) | ~600 | 두 번째 소비자 존재. **§3.3의 선결 조건** |
| 2 | `_hydrate_run_evidence` | ~130 | run 종료 시점 전용. event handler와 무관 |
| 3 | memory 2-phase commit (`_plan_memory`, `_apply_memory_plan`, `_memory_*`) | ~170 | Memory authority 전용 |
| — | event handler 4종 | ~900 | **뽑지 않는다.** 이것이 state machine 본체다 |

1·2·3을 뽑으면 ~1,570줄이 남는다. 여전히 크지만 **남은 것이 전부 event 처리**라서 읽을 수 있다.

#### 권고

**1번만 먼저 한다.** 이유: (a) §3.3(constraint pipeline)이 `RecoveryPublication` 확장을 요구하므로
그 전에 소유자가 명확해야 하고, (b) 두 번째 소비자가 실제로 있으며, (c) 2·3번은 급하지 않다.

**위험:** recovery/resume은 `test_recovery_registry.py`, `test_catalog_recovery.py`가 커버한다.
추출 전에 **커버리지를 먼저 측정**하고, 부족하면 characterization test를 먼저 쓴다.
회귀가 조용히 일어나는 종류의 코드다 (crash가 아니라 resume 시 잘못된 상태 복원).

---

### 3.9 (MM-09는 §3.5에 포함)

---

### 3.10 MM-10 — Exchange Strategy Pattern (계열 A)

#### 본질

Architecture §12(`architecture.md:1925`)가 *"Executor, Exchange와 valuation policy에는
**Strategy Pattern**을 적용한다"* 고 쓰지만, Exchange Protocol은 없고 `KrxExchange`가
concrete annotation으로 박혀 있다.

#### 이상적 종착점 — 두 축을 분리해서 판단해야 한다

**Exchange 축:** 실제 구현은 `KrxExchange` 하나다. `AcademicExchange`는 `match_batch`조차
공유하지 않고 별도 flow로 분기한다. 미국주식/암호화폐 같은 두 번째 실제 venue가 없다.
→ **Protocol을 뽑지 않는다 (K4).** speculative generality다.

**Executor 축:** `NextSessionCloseExecutor`와 `NextSessionOpenExecutor` — **구현이 이미 둘**이고,
`plan(decision) -> datetime | None`으로 **실제로 교체 사용**되며,
`daily.py:471`에 `NextSessionCloseExecutor | NextSessionOpenExecutor`라는 **union annotation이
이미 존재**한다. union이 자라는 것은 Protocol이 필요하다는 신호다.
→ **Protocol을 뽑는다.** 5줄이고, 세 번째 convention(VWAP 등)의 자리를 명확히 한다.

```python
class SessionExecutor(Protocol):
    convention_id: str
    def plan(self, decision: DecisionIntent) -> datetime | None: ...
```

#### 권고

1. **architecture §12 문장을 정정한다.** 현실: *"Executor는 structural Protocol로 교체 가능하다.
   Exchange는 현재 `run_daily`(KRX)와 `run_academic`(hypothetical)이 별도 flow로 분기하며,
   임의 Exchange를 주입하는 port는 두지 않는다. 두 번째 실제 venue가 생길 때 재검토한다."*
2. `SessionExecutor` Protocol 추가 — union annotation 대체
3. R0(§2) 표에 "venue 추가 = 새 flow + 새 facade method"를 명시

---

## 4. 의존 순서 — 왜 이 순서여야 하는가

```
R0  current-support-map.md ─────────────┐
S0  module-map.md ──────────────────────┤  (문서. 위험 0. 병렬 가능)
S2  문서 정정 §3.2/§3.5/§3.7/§3.10 ─────┘
                  │
                  v
F1  MM-04 facade 완성  +  S1 public surface 좁히기
    · 7개 method를 _with_catalog_session으로 감쌈 (신규 로직 0줄)
    · samples/tests를 qlibx.* 경유로 전환
    · catalog session 미적용 결함(PRD §2.6) 동시 해결
                  │
                  ├──> S3/S4/S5 실제 디렉토리 이동  ← Q3에 따라 이번 범위 밖. 별도 세션
                  │
                  v
F2  MM-08 DurableRunJournal 추출 ───────── F4의 선결 조건
                  │
                  v
F3  MM-01 lookback(rows·calendar) + MM-06 execution feedback
    · 둘 다 AccessRecord/StrategyResult를 건드림 → strategy_result:v3 한 번에
                  │
                  v
F4-1 DecisionStage 계약 + stage 0개 ────── 동작은 현행과 100% 동일해야 함
F4-2 construct stage                    ┐
F4-3 adjust / validate stage            ┘  필요 시점에 채움
```

**세 가지 순서 제약이 실재한다:**

1. **F1 → S1 → S4.** public surface를 좁히기 전에 facade가 완전해야 하고, 그전엔 디렉토리를
   못 옮긴다. 옮기면 사용자 import가 깨진다.
2. **F2 → F4.** `DecisionStage`가 artifact를 발행하면 `RecoveryPublication`이 확장되어야 하는데,
   그 소유권이 `DailyExecutionFlow` 안에 흩어져 있으면 확장이 2,468줄 파일 안에서 일어난다.
3. **MM-01과 MM-06을 묶는다.** 둘 다 `AccessRecord`/`StrategyResult` 스키마를 건드린다.
   따로 하면 `v3`, `v4`가 되고 reader를 둘 더 유지해야 한다.

---

## 5. 고친 뒤의 그림

```
QlibxProject  ← 유일한 public composition root, 모든 operation이 catalog session 안에서
  │
  ├ register_dataset / materialize
  ├ invoke / run_ensemble / construct_portfolio          ← F1으로 추가
  ├ run_daily / run_academic / execute_frozen_daily
  ├ adjust_constraints / validate_constraints / monitor_constraints
  └ analyze_* / render_report                            ← F1으로 추가

DailyExecutionFlow
  ├ DurableRunJournal        ← F2. academic과 공유
  ├ DECISION
  │    Strategy.run(view)  →  DecisionCandidate
  │       │
  │       └ DecisionStage[]   ← F4. 0개면 현행과 동일. 순서 고정
  │            construct → adjust → validate
  │            각 stage가 requirements()로 PIT 데이터를 요구하고 artifact를 발행
  │            breach는 finding으로 기록만. decision을 실패시키지 않음 (Q2)
  │       │
  │       v  DecisionIntent
  ├ EXECUTION  sizing → match → Account.commit
  ├ MARK
  └ MONITOR

StrategyView (역할 경계)
  dataset       : 선언한 role만, 선언한 lookback(rows|calendar) 안에서만   ← F3
  account       : committed snapshot
  feedback      : journal (fills / marks)
  performance   : 직전 session performance
  execution     : 직전 execution result + diagnostics        ← F3. 미체결이 여기로
  memory        : committed memory
  artifact      : 선언한 consumer_role만
```

---

## 6. 고치지 않기로 하는 것 (명시적 non-goal)

| 항목 | 이유 |
|---|---|
| Exchange Protocol/ABC | 실제 구현 1개. speculative generality (§3.10) |
| 거래일(trading-day) 기반 lookback | Q4에서 폐기. "3개월 전"은 달력 기준이 관행이며, 거래일 계수는 `observation_time_field` 등록을 강요한다 (§3.1) |
| breach 시 decision 실패 / profile switch | Q2에서 결정. drift breach는 adjust로 고칠 수 없어 장기 백테스트가 성립하지 않는다 (§3.3) |
| `rows` lookback의 사전 커버리지 검증 | registration에 종목별 행 수를 저장해야 하는데 minimal registration(PRD §7.2)을 무겁게 하고 stale해진다 (§3.1) |
| S3–S5 디렉토리 실제 이동 | Q3에서 이번 범위 밖으로 확정. F1 완료 후 별도 세션 (§3.7) |
| Strategy-owned cadence | PRD 침묵 + 캘린더 의존성 + 재현성 손해 (§3.2) |
| Strategy 내부 constraint clipping | PRD §2.1/§2.4 위반 (§3.3 옵션 B) |
| `JournalEntry`/`FillBatch` 스키마 변경 | I4/I9 흐림 + checkpoint 호환성 (§3.6) |
| event handler 4종 파일 분리 | control flow 은닉 (§3.8) |
| PRD에 "안 되는 것" 문단 추가 | 이미 있음. 길이가 문제의 원인 (§3.5) |
| 비용 있는 long-short 지원 | PRD §17 out of scope |
| `MATERIALIZE` scheduler / Model registry | architecture가 target으로 명시. 수요 미검증 |

---

## 7. 사용자 결정 — 전부 해결됨

PRD §2.6대로 **경제적 의미나 제품 범위를 바꾸는 선택은 agent가 하지 않는다.**
Q1–Q4는 2026-08-10에 모두 답을 받았다. 결정 내용은 문서 상단 **★ 확정된 결정** 절에 있고,
근거와 설계 귀결은 §3.1(Q4), §3.3(Q1·Q2), §3.7(Q3)에 반영했다.

| | 결정 | 반영 위치 |
|---|---|---|
| Q1 | 🅲 파이프라인 자리를 만든다 (D → C) | §3.3 |
| Q2 | 🅱️ 위반 기록 후 실행. profile switch 없음 | §3.3 |
| Q3 | 🅰️ S0–S2까지. S3–S5는 F1 이후 별도 세션 | §3.7 |
| Q4 | `rows` + `calendar`. `sessions` 폐기 | §3.1 |

### 남은 세부 확인 사항

아래는 제품 범위를 바꾸지 않는 **구현 세부**다. 위 결정을 뒤집지 않으며, 기본값을 그대로
받아들여도 무방하다. 구현 착수 시 한 번만 확인하면 된다.

**q4-a — `rows`의 계수 단위.** "N행"을 **instrument별**로 세는 것으로 해석했다(§3.1).
전역 상위 N행은 3,000종목 횡단면에서 의미가 없기 때문이다. 다른 의도였다면 알려달라.

**q4-b — `calendar`의 월말 규칙.** `2024-03-31 − 1개월 = 2024-02-29`(월말 clamp)를 기본으로
잡았다. 한국 금융 실무에서 다른 관행을 쓰신다면 `month_end_policy`에 값을 추가한다.

**q4-c — `calendar_timezone`의 출처.** dataset의 `source_timezone`이나 profile의
`session_timezone`을 자동 상속하지 않고 **requirement에 명시 선언**하게 했다. 셋이 다를 수
있고 어느 것이 옳은지는 사용자만 알기 때문이다(PRD §5.3). 자동 상속을 원하면 알려달라 —
다만 PRD §4.7("config는 의미를 선언하지만 의미를 대신하지 않는다")과 충돌한다.

**q1-a — stage 실행 순서의 고정 여부.** `construct → adjust → validate`를 고정할 것인가,
profile이 임의 순서를 선언할 수 있게 할 것인가? 기본값은 **고정**이다 — PRD §3.2의 result
category 순서가 이미 이 순서를 함의하고, 임의 순서는 검증 불가능한 조합을 만든다.

---

## 8. 다음 세션에서 확인해야 할 사실

아래는 이 문서의 권고가 의존하지만 **아직 검증하지 않은** 사실이다.

1. **Catalog가 payload를 schema hash로 검증하는가** — F3의 `strategy_result:v3` 필요 여부를 결정한다
   (`evidence/local.py`, 1,157줄 미독)
2. **recovery/resume의 현재 테스트 커버리지** — F2 추출 전 characterization test 필요 여부
3. **`AcademicExecutionFlow`의 checkpoint 프로토콜 상세** — `DurableRunJournal`이 실제로 두 소비자를
   만족하는 shape인지
4. **`ConstraintFlow.adjust`가 요구하는 view/binding** — `DecisionStage.requirements()`로 표현
   가능한지 (`flow/constraints.py:229-263`)
5. **테스트 스위트 전체 실행** — session 1 §0은 focused 39개 통과를 확인했다. 전체는 미확인
