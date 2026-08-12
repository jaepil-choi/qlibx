# 2026-08-10 17:30 Execution-spine conformance review

Reviewer: coding agent (Claude Opus 5)
Scope: Codex 작업 4개 커밋 (`4656e89..f692961`) 대비 **확정된 PRD/architecture 결정**
Reviewed range: `3f0c076`, `32d2c15`, `6eeb4bf`, `f692961`
Baseline: `4656e89` (docs: require the execution path for any claimed portfolio return)
Branch: `exp/2nd-attempt`
Canonical: `docs/qlibx-prd.md`, `docs/qlibx-architecture.md`
Implementation note: `docs/implementations/062-typed-execution-spine-and-preparation.md`

> **판정 요약: roll back 하지 않는다.** 이번 작업은 우리가 확정한 결정 4개 중 3개를 정확히
> 구현했고, 남은 충돌은 **국소적**이다 — 문서 2곳, 필드 2개, 미확정 product question 1개.
> 되돌리면 올바른 구현을 버리게 된다.

---

## 1. 커밋 내역

| 커밋 | 내용 | 규모 |
|---|---|---|
| `3f0c076` | refactor: rebuild core runtime contracts | 68 files |
| `32d2c15` | test: add exact lookback performance gate | 1 file (196줄) |
| `6eeb4bf` | refactor: split view responsibilities | 3 files |
| `f692961` | fix: preserve execution and dataset lineage | 3 files |

구조 변경:

```
src/qlibx/context/            → src/qlibx/view/{__init__,gate,records,views}.py
src/qlibx/{academic,constraints,simulation}.py → src/qlibx/specs/{academic,constraints,daily}.py
src/qlibx/execution/exchange.py → execution/{base,krx,preparation}.py
src/qlibx/data/snapshot.py     (신규 — registration-time normalized Parquet)
tests/performance/lookback_gate.py (신규)
```

---

## 2. 확정 결정 대비 적합성

### ✅ K1 — ExecutionPreparation spine (Q1 결정)

PRD §2.4가 요구하는 `Strategy → ExecutionPreparation → BaseExchange → Account commit`이
`execution/preparation.py`(562줄)에 구현되었다.

```python
class ExecutionPreparation(Generic[IntentT, ContextT, RequestT, EvidenceT]):
    def prepare(...) -> PreparedExecution[RequestT, EvidenceT]
class KrxExecutionPreparation(ExecutionPreparation[...])
class AcademicExecutionPreparation(ExecutionPreparation[...])
```

**Q1에서 확정한 "자리를 만들되 범용 registry는 두지 않는다"를 정확히 지켰다.**
`KrxExecutionPreparation.prepare()`가 construct → adjust → validate → size를 고정 순서로 호출하고,
event당 preparation bundle artifact 하나(`krx_execution_preparation:v1`)만 발행한다.
User-configurable `DecisionStage[]`는 없다 — PRD §2.4 본문과 일치.

### ✅ K2 — BaseExchange (PRD §11.2)

```python
class BaseExchange(ABC, Generic[RequestT, ResultT]):
    exchange_id: str
    def match_batch(self, request: RequestT) -> ResultT
```

`KrxBatchRequest`/`AcademicBatchRequest`가 **서로 다른 타입**이고 ledger semantics를 공유하지 않는다.
PRD가 요구한 *"두 subclass는 request/result type과 ledger semantics를 공유하지 않으며"* 를 지켰다.

### ✅ K3 — Advisory constraint (Q2 결정)

Finding-level `passed` + aggregate `compliant`. Residual breach는 evidence일 뿐 matching을 막지 않고,
benchmark 부재나 evaluator 실패만 Exchange 호출 전에 `OperationError`로 끝난다.
**Q2에서 확정한 🅱️(위반 기록 후 실행)와 정확히 일치.**

### ✅ K4 — Exact lookback (Q4 결정) — 구현 품질이 높다

`data/contracts.py`:
```python
class RowsLookback(QlibxModel):
    rows: int = Field(gt=0)
class CalendarLookback(QlibxModel):
    years/months/days: int = 0
    timezone: str
    month_end_policy: Literal["clamp"] = "clamp"
```

우리가 정한 세 세부사항이 모두 맞다.

| 확정 항목 | 구현 |
|---|---|
| **q4-a** rows는 instrument별 | `row_number() OVER (PARTITION BY instrument ORDER BY …)` ✅ |
| **q4-b** 월말 clamp | `day = min(local_date.day, calendar.monthrange(year, month)[1])` ✅ |
| **q4-c** timezone 명시 선언 | `CalendarLookback.timezone` 필수 필드, `ZoneInfo` validation ✅ |

그리고 **PRD §7.6.1의 핵심 요구 — "전체 history를 먼저 읽은 뒤 Strategy code에서 자르는 경로를
bounded access로 간주하지 않는다" — 를 실제로 지켰다.** Lookback이 `ComponentRequirement` →
`ResolvedBinding` → DuckDB SQL predicate까지 내려간다. `history()`는 인자로 lookback을 받지 않고
**binding에 선언된 것만** 적용하므로 Strategy가 우회할 수 없다.

`_calendar_lower_bound`의 산술도 정확하다 — 월/연을 먼저 이동해 clamp한 뒤 `days`를 단순 감산한다.
우리가 정한 *"`days`는 단순 가산"* 규칙 그대로다.

### ✅ K5 — `latest_execution_result()` (GAP-EXECUTION-FEEDBACK-001)

`view/views.py:266`에 구현되었고, decision 사이에 execution이 2회 이상이면
`STRATEGY_EXECUTION_SCHEDULE_INVARIANT`로 실패시킨다. Zero-dealt diagnostic이 Fill이나 Account
mutation을 만들지 않는다는 계약도 지켜졌다.

> 참고: implementation note §"Remaining limitations"는 *"The Strategy cannot yet read the exact
> execution result between decisions"* 라고 적었지만 **코드에는 이미 있다.** Note가 이후 커밋보다
> 앞서 작성된 것으로 보인다. Note를 갱신해야 한다.

### ✅ K6 — Exchange injection

`run_daily(..., exchange=...)`, `run_academic(..., exchange=...)` keyword-only. 생략하면 spec에서
built-in venue를 만들고, 주입하면 `exchange_id`와 config fingerprint가 run identity에 들어간다.
Frozen invocation(PRD §7.10)을 지킨다.

### ✅ K7 — §12 package layout 문서 갱신

architecture §12가 `view/`, `specs/`, `execution/ (BaseExchange, preparation)`,
`data/ (normalized Parquet + DuckDB bounded query)`로 갱신되었다.

---

## 3. 충돌 — 수정이 필요한 것

### 🔴 C1 — `AccessRecord`가 instrument마다 항목을 남긴다 (원칙 위반 + UC-SCALE-001 위험)

`view/records.py:64`:

```python
class AccessRecord(QlibxModel):
    ...
    lookback: Lookback | None = None                              # ✅ 필요
    snapshot_fingerprint: str | None = None                       # 🟡 논의된 적 없음
    requested_instruments: tuple[str, ...] = ()                   # 🔴
    per_instrument_actual_count: tuple[tuple[str, int], ...] = () # 🔴
```

**문제 1 — 크기.** `view/views.py:137-150`에서 `instruments is None`이면 frame 전체를 groupby해
**종목 수만큼 항목을 만든다.** UC-SCALE-001은 3,000종목 일별 cross-section이다. 즉 access record
하나에 3,000개 tuple이 들어가고, 이것이 `StrategyResult` JSON artifact에 그대로 직렬화된다.
Decision 하나에 access가 여러 개이고 run은 수백~수천 decision이다.

**문제 2 — 계산 비용.** `instruments`가 주어진 경로는 종목마다 full-column 비교를 돈다.

```python
int((frame["instrument"].astype(str) == instrument).sum())   # O(instruments × rows)
```

3,000종목 × 60,000행이면 1.8억 회 비교를 **access record 하나 만들려고** 수행한다.

**문제 3 — 계약 초과.** PRD §7.6.1이 요구하는 것은 이것뿐이다.

> "`rows`보다 적은 행만 존재하면 있는 만큼 반환하고 **requested/actual count**를 access evidence에
> 기록한다."

`count`(수)이지 per-instrument 목록이 아니다. 게다가 같은 절이 이렇게 경고한다.

> "Dataset-wide `available_at_min`만으로 instrument별 coverage를 추정하거나, **row가 전혀 없는
> instrument를 declared universe 없이 존재한다고 추측하지 않는다.**"

**문제 4 — 사용자 원칙 위반.** *"자꾸 이것저것 attribute, lineage를 붙이는 것은 금지야.
꼭 필요한 경우에만 남겨야 해."*

**권고 수정:**

```python
lookback: Lookback | None = None
instruments_below_window: int = 0     # rows일 때만 0이 아님
```

`requested_instruments`는 caller가 넘긴 값의 복사이므로 새 정보가 없고, `snapshot_fingerprint`는
`registration_identity`가 이미 담고 있는지 확인 후 중복이면 제거한다.

### 🔴 C2 — architecture가 자기 자신과 모순된다 (pandas vs DuckDB)

`data/store.py`가 이제 **DuckDB `read_parquet` + predicate pushdown**을 쓴다. `data/snapshot.py`가
registration 시점에 normalized Parquet snapshot을 만든다.

그런데 architecture 두 곳이 여전히 옛 사실을 "current"라고 선언한다.

| 위치 | 현재 문구 | 실제 |
|---|---|---|
| §1 alignment 표 (line 33) | "registered CSV/Parquet source를 **pandas로 읽고** … **columnar store는 target이지 current가 아니다**" | DuckDB가 current |
| §7 횡단면 (line 1062-1066) | "current query = **pandas read + in-memory PIT/filter**", "**future target** = partitioned Parquet + DuckDB predicate pushdown" | 이미 future target이 current |

§12는 갱신됐는데 §1과 §7은 안 됐다. **alignment 표는 "actual만 적는다"가 그 표의 존재 이유**이므로
(문서 서두: *"이 표에서 current는 실제 public symbol 또는 실행 가능한 회귀 테스트가 있는 상태만
뜻한다"*) 이 불일치는 그냥 오탈자가 아니라 계약 위반이다.

또한 그 행의 **전환 조건**이 명시되어 있었다.

> "대표 workload benchmark에서 cold scan cost가 budget을 넘고 ingestion/fingerprint contract가
> 정의될 때 전환한다"

`tests/performance/lookback_gate.py`(196줄, fresh-process gate)가 추가된 것은 이 조건을 겨냥한
것으로 보이나, **before/after 수치가 implementation note에 기록되지 않았다.** 직전 리뷰
(`2026-08-09-1310`)가 성능 커밋에 대해 *"before/after 수치를 implementation record에 기록해야 한다.
'빨라졌다'는 서술로는 부족하다"* 를 프로세스 의무로 남겼다.

### 🟡 C3 — `set_exchange` / `add_instrument` 거부 — 사용자 결정과 어긋난다

Implementation note:

> "A project-level `set_exchange()` was rejected because hidden mutable composition would make
> replay and resume identity ambiguous."

**사용자는 이 대화에서 반대로 결정했다.** (B-3)

> "이것도 add instrument, set exchange 할 수 있어야 해."

그리고 그 근거를 검토한 결과 frozen invocation과 **충돌하지 않는다**는 결론이 나왔다 — PRD §7.10의
freeze 시점은 *"한 operation이 시작되면"* 이므로, 조립은 mutable하고 `run_daily()`가 스냅샷을 뜨면
된다. Codex가 든 논거는 내가 처음에 제시했다가 **철회한 것과 같은 논거**다.

다만 정상 참작 사유가 있다: **이 결정은 PRD에 기록되지 않았다.** Codex가 알 방법이 없었다.
그리고 현재 injection 방식이 *틀린* 것은 아니다 — frozen이고 fingerprint에 들어간다.

→ **product decision 필요**(§5 Q-A). 둘은 공존 가능하다: builder가 누적하고 `run_*`가 freeze.

### 🟡 C4 — `hypothetical_long_short_return` 잔존 (내 후속 작업)

`analysis/results.py:374`에 그대로 있다. `GAP-RETURN-AUTHORITY-001` 미해결이며 이는 **내가 하기로 한
후속 작업**이지 Codex의 누락이 아니다. 다만 해당 파일이 이번에 수정되었으므로 내 변경 계획을
현재 코드 기준으로 다시 잡아야 한다.

### 🟡 C5 — Implementation note가 코드보다 뒤처져 있다

Note의 "Remaining limitations"가 두 항목을 미구현이라고 적었지만 코드에는 있다.

- *"The Strategy cannot yet read the exact execution result between decisions"* → `latest_execution_result()` 존재
- *"Dataset history is still pandas-backed and not physically bounded by a declared rows/calendar lookback"* → DuckDB + lookback 구현됨

Note가 `3f0c076` 시점에 작성되고 이후 커밋을 반영하지 않은 것으로 보인다.

---

## 4. Q3(디렉토리 이동) 위반 여부 — 실질 피해는 없다

사용자 결정은 *"S0–S2까지, S3–S5는 F1(facade) 완료 후 별도 세션"* 이었고, Codex 자신의 계획서도
*"전체 directory를 먼저 재배치하는 것은 권하지 않습니다"* 라고 적었다. 그런데
`context/ → view/`, top-level DTO → `specs/`, `exchange.py` 분할이 함께 일어났다.

**그러나 실질적으로는 문제가 없다.** 이유:

1. 이동이 **책임 경계 구현과 동시에** 일어났다 — Codex 계획서의 *"책임 경계가 실제 코드로 생긴
   다음 이동해야 한다"* 조건을 오히려 만족한다. `execution/{base,krx,preparation}.py` 분할은
   `BaseExchange`/`ExecutionPreparation`이 생겼기 때문에 가능해진 것이다.
2. 결과 배치가 내가 §3.7에서 제안한 목표 layout과 **거의 동일**하다.
3. 내가 우려한 것은 순서(F1 먼저)였는데, 그 이유는 "public import가 깨진다"였다. PRD
   `GAP-PUBLIC-FACADE-001`이 *"제거되는 root/context module에는 compatibility shim을 두지 않는다"*
   로 이미 정해 두었으므로 정책상 문제도 아니다.

→ **되돌리지 않는다.** 다만 그 shim-없음 정책은 사용자에게 명시적으로 확인받은 적이 없으므로
§5 Q-B로 남긴다.

---

## 5. Product decision이 필요한 항목

**Q-A — builder-style project configuration → ✅ (b)로 확정, 구현 완료.**
사용자가 B-3 결정을 PRD에 기록하고 구현을 고치도록 지시했다. PRD §7.10.1을 신설하고
`GAP-PROJECT-CONFIGURATION-001`을 등록했으며, `QlibxProject.add_instrument`/`set_exchange`/
`daily_spec`을 구현했다.

Codex가 든 거부 논거(*"hidden mutable composition이 replay/resume identity를 모호하게 만든다"*)는
**타당하지만 특정 구현 방식의 문제**였다. 채택한 설계가 그 우려를 제거한다.

| Codex의 우려 | 이 설계 |
|---|---|
| spec에 "나중에 project를 읽는다"는 구멍 | 만들지 않는다. spec은 완전하다 |
| Flow가 project를 계속 참조 | 참조하지 않는다. spec만 소비한다 |
| fingerprint에 환경이 빠짐 | `frozen_config_fingerprint()`가 instruments·exchange를 포함한다 |

누적은 project instance에만 머물고 `daily_spec()`이 값으로 스냅샷한다. `DailySimulationSpec`의
필드는 하나도 optional로 바꾸지 않았다. 세션 간 persistence는 수요가 확인되지 않아 넣지 않았다.

**Q-B — compatibility shim 부재 → ✅ 현행 유지로 확정.**
사용자 확인: qlibx를 설치해 쓰는 외부 프로젝트가 없고 0.1.0도 아직 release되지 않았다. 따라서
`qlibx.context` 등 옛 import 경로가 사라져도 깨질 consumer가 없다. PRD의 "shim을 두지 않는다"
문장을 그대로 둔다. Repo 내부는 이미 전부 새 경로로 통과한다. **Release 이후에는 같은 판단이
성립하지 않으므로 다음 rename부터는 이 질문을 다시 물어야 한다.**

---

## 6. 조치 계획

| # | 대상 | 조치 | 상태 |
|---|---|---|---|
| **F-1** | C1 | `AccessRecord`에서 `requested_instruments`, `per_instrument_actual_count` 제거하고 `instruments_below_window: int`로 대체. `views.py`의 groupby/quadratic 계산 삭제 | ✅ 완료 |
| **F-2** | C2 | architecture §1 alignment 표와 §7의 pandas 서술을 DuckDB/Parquet current로 갱신. §17에 전환 이력 추가 | ✅ 완료 |
| **F-3** | C5 | `062` note의 "Remaining limitations" 갱신 | ✅ 완료 |
| **F-4** | C4 | `GAP-RETURN-AUTHORITY-001` — `hypothetical_long_short_return` 제거 + showcase를 academic 경로 대조로 재작성 | ✅ 완료 (show_002는 §8 참조) |
| **F-5** | Q-A | 사용자 결정 후 진행 | 대기 |
| — | Q3 | 조치 없음 (§4) | — |

### F-1 구현 상세

```python
# view/records.py
lookback: Lookback | None = None
snapshot_fingerprint: str | None = None       # research.py의 dependency edge가 실제 소비 → 유지
instruments_below_window: int = Field(default=0, ge=0)
```

```python
# view/views.py — groupby 한 번, set 차집합. instrument마다 full-column 비교하던 경로를 제거
def _instruments_below_window(frame, *, lookback, instruments) -> int:
    if not isinstance(lookback, RowsLookback):
        return 0
    counts = frame.groupby("instrument", sort=False).size()
    satisfied = {str(name) for name, count in counts.items() if count >= lookback.rows}
    if instruments is None:
        return len(counts) - len(satisfied)
    return len({str(item) for item in instruments} - satisfied)
```

`instruments`가 선언된 경우에만 **행이 하나도 없는 instrument**를 부족으로 센다. 선언이 없으면 frame에
실제로 등장한 instrument만 센다 — PRD §7.6.1의 *"row가 전혀 없는 instrument를 declared universe 없이
존재한다고 추측하지 않는다"* 를 지키기 위해서다.

`snapshot_fingerprint`는 제거하지 않았다. `flow/research.py:298`이 dependency edge의
`compatibility_fingerprint`로 소비하고 있고 스칼라 하나이므로 실사용이 증명된 필드다.

---

## 7. 검증 상태

```
.venv/Scripts/python.exe -m pytest tests -q --deselect tests/test_data_source_audit.py
→ 283 passed, 4 deselected in 144.53s
```

**Codex 작업 범위는 green이다.** 새 execution spine, BaseExchange, lookback, view 분리 전부 회귀 없음.

Deselect한 `tests/test_data_source_audit.py`(4건)는 **local data drift**이며 code defect가 아니다.

| 파일 | 상태 |
|---|---|
| `data/qlibx/k200_membership.parquet` | SHA-256이 `data_sources.yaml` 기록값과 불일치 |
| `data/preprocessed/sector_classification.parquet` | **1,143,059행** vs 기록된 187,615행 |

qlibx 밖에서 재생성된 user-owned source다. 직전 리뷰(`2026-08-09-1310`)도 같은 부류를 환경 결함으로
분류했다. 다만 **이 audit이 red인 동안은 real-DW acceptance의 입력 동일성을 주장할 수 없다** —
`data_sources.yaml`을 현재 파일에 맞춰 갱신하거나 데이터를 되돌려야 한다. 별도 작업이다.

미확인으로 남는 것: `tests/performance/lookback_gate.py`의 실제 수치(§3 C2의 전환 조건 근거).

### F-4 실행 증거

`show_003`을 재작성한 뒤 실제로 실행했다.

```json
"maximum_absolute_period_identity_delta": 1.1726730697603216e-15,
"verified_identity_periods": 22
```

22개 보유기간 전부에서 **AcademicExchange가 도달한 NAV 수익률이 직전 rebalance weight와 실현 가격
수익률이 함의하는 값과 부동소수점 오차 내로 일치**한다. Architecture §2.5가 $\sum w r$ 을 "1기간 검증
항등식"으로 재정의한 것의 실행 증거다.

이전 showcase는 pandas로 계산한 $\sum w r$ 을 qlibx가 계산한 같은 공식과 비교했다 — 두 구현이 같은
식을 쓰는지만 확인했을 뿐 아무것도 증명하지 않았다. 지금은 **회계 경로가 항등식을 만족함**을 증명한다.

---

## 8. F-4 중 발견 — `show_002`는 이미 죽어 있다

`showcases/show_002_academic_factor_research/run.py:461`도 삭제된 metric을 소비한다. 원래 리뷰 범위에는
없었는데, Codex의 `3f0c076`이 이 파일을 수정하면서 드러났다.

조사 결과 이 showcase는 **세 겹으로 이미 폐기 상태**다.

1. **자기 README가 "superseded by `show_003_academic_exchange_factor_execution`"** 이라고 선언한다.
2. **자기 staleness guard에 걸려 실행되지 않는다.**
   ```python
   if academic_exchange_present:
       raise RuntimeError("showcase verdict is stale: AcademicExchange now exists")
   ```
   `hasattr(qlibx, "AcademicExchange")`는 **현재 True**다. 즉 이 runner는 아무것도 만들지 못하고 즉시 실패한다.
3. **어떤 테스트도 참조하지 않는다.**

그리고 내용 자체가 새 규칙의 정확한 반례다.

```python
cost = turnover * HYPOTHETICAL_COST_RATE
net_return = qlibx_return - cost
cumulative_gross *= 1 + qlibx_return     # ← Σwr 을 직접 누적
cumulative_net  *= 1 + net_return
```

Exchange도 Account도 없이 $\sum w r$ 을 복리로 쌓고 손수 만든 비용 모델을 빼서 **"Net academic
return"** 으로 보고한다. Architecture §2.5가 *"이 식을 직접 누적하면 무비용과 매기간 완전 리밸런싱을
암묵적으로 가정하게 되고 turnover는 0으로 보고된다"* 고 쓴 바로 그 패턴이다. Quantile spread도 계산하는데
PRD §4.2 개정으로 1층에서 빠진 항목이다.

**권고: 디렉토리 폐기.** 이유는 (a) 이미 superseded이고 (b) 이미 실행 불가이며 (c) 남겨 두면 새 규칙을
어기는 코드가 repo에 남는다. show_003이 같은 데이터 축으로 더 강한 증거를 만든다.

**→ ✅ 사용자 결정으로 폐기했다.** 4개 파일을 제거했고 dangling reference는 없다.
