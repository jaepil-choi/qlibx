# 2026-08-09 13:10 PRD conformance review and fix plan

Reviewer: coding agent (Claude Opus 5)
Scope: `src/qlibx` 전체 (14,993 LOC) — `docs/qlibx-prd.md`의 use case / acceptance criteria 대비 적합성
Reviewed commit: `055bf76` (`chore: ignore agent temporary artifacts`)
Branch: `exp/2nd-attempt`
Baseline: **`11 failed, 198 passed, 34 errors`** — 전부 환경 결함이다. §1 참조
Lint: `ruff check .` → `All checks passed!`
Canonical documents: `docs/qlibx-prd.md`, `docs/qlibx-architecture.md`
직전 리뷰: `docs/code-review/2026-08-07-2100-catalog-performance-profile-and-fix-plan.md`
다음 implementation record 번호: **050** (현재 최고 `049-observation-frame-cache.md`)

> 이 문서는 감사 기록이며 canonical contract가 아니다. PRD와 Architecture가 정본이다.
> §3의 finding 중 `CONFIRMED`는 **실제 실행으로 재현**했고 `PLAUSIBLE`은 코드 경로 추적으로 판단했다.
> 재현 스크립트는 §9 부록에 전문이 있다. 붙여넣으면 바로 돌아간다.
> §5의 수정 계획은 **제안**이며 사용자 승인 전에는 확정이 아니다.
> **§4를 읽기 전에 §5를 구현하지 마라.** §4는 이 코드베이스가 이미 보장하고 있어서
> 깨뜨리면 안 되는 불변식을 정리한 것이다. 특히 F-03과 F-04는 순진하게 고치면 §4.2와 §4.3을 깬다.
> **F-03, F-07, F-10, F-11은 product decision이 필요하다.** §5에서 옵션과 권고를 제시했지만
> 구현 agent가 단독으로 확정하지 마라. PRD §2.6대로 경제적 의미를 바꾸는 선택은 user가 한다.

---

## 0. 후속 agent를 위한 사용법

1. **§1을 먼저 읽어라.** 지금 suite는 red지만 제품 결함이 아니라 **로컬 데이터 부재**다.
   이걸 해결하지 않으면 §3의 finding 중 어느 것도 acceptance로 검증할 수 없다.
2. §2에서 이번 리뷰가 무엇을 봤고 무엇을 안 봤는지 확인한다.
3. §3의 F-01 ~ F-11을 읽는다. 각 항목에 **정확한 파일:라인, 재현 방법, PRD 근거 조항**이 있다.
4. **§4의 설계 제약을 읽는다.**
5. §5의 커밋 순서대로 수정한다. C1 → C2 → ... → C8. 순서에는 이유가 있다(§5.0).
6. §6의 검증을 커밋마다 통과시킨다. 성능 커밋(C5·C6·C7)은
   **before/after 수치를 implementation record에 기록**해야 한다. "빨라졌다"는 서술로는 부족하다.
7. §7의 process 의무를 지킨다. implementation record는 050부터.
8. §8은 **일부러 고치지 않기로 한 것**이다. 다시 파헤치지 마라.

> **가장 놓치기 쉬운 것 하나.** F-01의 결함을 `tests/acceptance/test_research_scenarios.py:243-250`
> (`test_uc_portfolio_001_...`)이 **정답으로 단정하고 있다.** PRD use case 이름을 달고 있다고
> 해서 그 테스트가 PRD를 올바로 인코딩했다는 뜻은 아니다. C2는 소스와 **오라클을 함께** 고친다.
> PRD §16.4가 경고한 "prototype의 accidental 동작을 requirement로 승격"의 실제 사례다.

```powershell
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe -m ruff check .
```

---

## 1. HEAD 상태 — suite는 red지만 제품 결함이 아니다

```
.venv/Scripts/python.exe -m pytest tests -q
-> 11 failed, 198 passed, 34 errors in 37.23s
```

`ruff check .` → `All checks passed!`.

### 1.1 근본 원인: `data/DW/`가 이 체크아웃에 없다

```
tests/acceptance/conftest.py:22  bounded_real_dw_source
tests/acceptance/real_dw_support.py:47
E  AssertionError: repository acceptance requires the real DW daily-price CSV
```

```
DW_DAILY = ROOT / "data" / "DW" / "fng_stock_daily_prices.csv"   # real_dw_support.py:26
-> C:\Users\chlje\DevProjects\qlibx\data\DW\fng_stock_daily_prices.csv  is_file() = False
-> data/DW/ 디렉터리 자체가 존재하지 않음
```

34개 error는 전부 이 session fixture 실패의 파생이다. 11개 failure도 같은 뿌리다:

| 실패 | 이유 |
|---|---|
| `test_data_source_audit.py` 4건 | 원천 CSV 부재 |
| `test_public_constraint_sample.py`, `test_public_daily_sample.py`, `test_sample.py` | 번들 sample 행을 real DW와 대조 불가 |
| `test_scenario_registry.py` 2건, `test_recovery_registry.py`, `test_strategy_capability_catalog.py` | 레지스트리 YAML이 가리키는 `reference_sources` 파일이 없어 `(ROOT / path).is_file()` 실패 |

### 1.2 후속 agent가 가장 먼저 할 일

**`data/DW/`를 복원하기 전에는 어떤 수정도 acceptance로 검증할 수 없다.**
`tests/acceptance/`, `tests/characterization/`, sample reconciliation은 전부 real DW에 묶여 있고,
이번 리뷰의 F-01 · F-02 · F-03 · F-04 · F-05는 정확히 그 경로에 있다.

세 가지 선택지:

1. **원천 데이터를 복원한다** (권장). `data/DW/fng_stock_daily_prices.csv` 등.
   `tests/acceptance/real_dw_support.py`의 `DW_*` 상수 전체가 필요한 파일 목록이다.
2. 데이터가 영구히 없다면, real DW 의존 테스트를 `pytest.skip`으로 명시적으로 게이트하고
   **green baseline을 재정의**한다. 단 §16.4(test philosophy)상 acceptance를 skip으로 덮는 것은
   회귀 탐지력을 잃는 것이므로 user 승인이 필요하다.
3. 축소된 결정론적 fixture로 대체한다. 이 경우 `tests/scenarios/*.yaml`의
   `fixture_kind: deterministic_contract` 표기를 함께 갱신해야 한다.

**어느 쪽이든 이건 이번 fix plan의 C0이고, 나머지 커밋의 선행 조건이다.**

---

## 2. 리뷰 범위와 방법

### 2.1 읽은 것

`src/qlibx` 전체를 PRD 조항 대비로 읽었다. 무게중심은 PRD가 current scope로 못박은 경로다.

| 영역 | 파일 | PRD 근거 |
|---|---|---|
| Closed-loop runtime | `flow/daily.py` (2,168) | §5.2, §11, UC-EXEC-001~003, UC-CLOSED-LOOP-001 |
| Exchange 산술 | `execution/exchange.py`, `execution/sizing.py` | UC-COST-001~004, UC-SCALE-001 |
| Account authority | `account/account.py`, `account/memory.py` | §4.3, §9.10 |
| PIT 강제 | `context/scoped.py`, `data/store.py`, `data/registry.py` | §4.4, §7.2, §7.6, UC-DATA-001 |
| Portfolio / Constraint | `portfolio/construction.py`, `portfolio/constraints.py`, `flow/constraints.py`, `flow/monitoring.py` | §7.11, §10.2~10.4, UC-CONSTRAINT-* |
| Artifact catalog | `evidence/local.py` (1,129), `flow/recovery.py` | §12, GAP-CATALOG-001, GAP-RECOVERY-001 |
| Composition | `flow/composition.py`, `flow/strategy_results.py`, `flow/research.py` | §9.4, §10.1, UC-ENSEMBLE-001, UC-ALPHA-PATH-001 |
| Analysis / Report | `analysis/results.py`, `analysis/sessions.py`, `flow/analysis.py` | §13.1, UC-REPORT-001, UC-MONITOR-001 |
| Extension | `extensions/local_modules.py`, `flow/strategy_extensions.py` | UC-EXTENSION-001/002 |
| Public facade | `project.py`, `simulation.py`, `constraints.py` | §6.8, §11.5 |

### 2.2 잘 구현되어 있다고 확인한 것 (재작업 금지)

아래는 PRD 요구를 **충족**한다. finding이 없는 이유를 남긴다.

- **PIT 강제 (§4.4).** `ObservationStore.query`가 `available_at <= as_of`를 우회 불가능하게 적용하고,
  `_DatasetView._binding`이 미선언 role 접근을 `ViewAccessError`로 막는다. Strategy는 raw store를
  받지 못한다(`ViewGate`). UC-LOOKTHROUGH-002의 "미래 관측 은닉"이 구조적으로 보장된다.
- **actual state authority (§4.3).** `_on_execution`이 candidate Account로 먼저 계산하고,
  recovery point를 발행한 뒤, live Account에 commit하고, `after != candidate_after`면
  `RECOVERY_CANDIDATE_DIVERGED`로 실패한다. requested target이 actual로 새는 경로가 없다.
- **cost policy 해석 (§3.5 UC-COST-001~004).** `KrxExchange._resolve_cost`가
  `len(matches) == 1`일 때만 rule을 반환하고, `KrxExchangeConfig.reject_overlapping_rules`가
  등록 시점에 겹침을 막는다. ETF에 Equity policy가 대입될 경로가 없다(UC-COST-004 충족).
- **Memory CAS와 feedback 전진 (§9.11).** `_plan_memory`가 `MEMORY_CAS_MISMATCH`,
  `MEMORY_FEEDBACK_CURSOR_MISMATCH`, `MEMORY_FEEDBACK_NOT_ADVANCED`를 구분해 실패시킨다.
  미래 fill 선취가 불가능하다.
- **catalog 원자성 (§12.3, GAP-CATALOG-001).** staging → promote → commit 3단계와
  `publication_events` audit, `_recover_locked`의 abandoned 정리가 partial write를
  reusable success로 노출하지 않는다.
- **frozen composition lineage (§9.4).** `collect_strategy_source_lineage`가 v1/v2 member의
  Account/Memory identity와 cursor를 consumer result에 보존하고 충돌 시 실패한다.
- **run_daily가 constraint monitoring을 자동 실행하지 않음 (§11.5).** `_on_monitor`가 만드는 것은
  `monitor_observation`(관측 evidence)이지 constraint finding이 아니다. 계약대로다.
- **timezone 계약 (GAP-TIME-001).** naive 소스는 `source_timezone` 없이 등록 불가,
  offset 소스의 미사용 timezone은 `TIMESTAMP_TIMEZONE_UNUSED`로 거부.

### 2.3 이번 리뷰가 보지 **않은** 것

- `onboarding.py` (700 LOC)와 `.claude` / `.agents` skill 생성 경로(GAP-ONBOARD-001).
  직전 리뷰들이 다뤘고 이번 질문(시나리오/use case 수행 능력)의 중심이 아니다.
- `cli.py`, `config/project.py`.
- 성능 **실측**. 직전 리뷰(2026-08-07 21:00)가 catalog write 경로를 실측했다.
  이번 F-04·F-06·F-08·F-09는 **코드 경로 기반 복잡도 분석**이며, 절대 수치는 §5의 C6-a에서
  실측해야 한다. 이 문서는 초(sec) 단위 주장을 하지 않는다.

---

## 3. Findings

11건. 심각도 순.

| ID | 위치 | 분류 | 판정 | 한 줄 |
|---|---|---|---|---|
| F-01 | `portfolio/construction.py:93` | correctness | CONFIRMED | long-only 변환이 budget을 자동 재정규화해 residual을 소멸시킴 |
| F-02 | `flow/daily.py:758` | correctness | CONFIRMED | `DecisionIntent` ValidationError가 `run()` 밖으로 새어나감 |
| F-03 | `flow/daily.py:674` | correctness | CONFIRMED | memoryless strategy는 ~129 세션에서 강제 중단 |
| F-04 | `flow/recovery.py:49` | efficiency | CONFIRMED | recovery point가 전체 journal을 매 이벤트 직렬화 (Θ(N²)) |
| F-05 | `analysis/results.py:178` | correctness | CONFIRMED | hold-only run 분석 불가 + initial NAV 오기준 |
| F-06 | `flow/daily.py:1763` | efficiency | CONFIRMED | resume이 모든 recovery point를 load |
| F-07 | `data/requirements.py:69` | correctness | CONFIRMED | 선언된 axis/time requirement가 강제되지 않음 |
| F-08 | `data/store.py:40` | efficiency | CONFIRMED | query마다 소스 파일 전체 재해싱 |
| F-09 | `data/store.py:54` | efficiency | CONFIRMED | 필터 전 전체 프레임 불필요 복제 |
| F-10 | `flow/daily.py:926` | correctness | CONFIRMED | `total_market_volume` 미주입으로 impact 경로 도달 불가 |
| F-11 | `execution/instruments.py:11` | correctness | PLAUSIBLE | instrument position-direction 계약 부재 |

---

### F-01 — long-only construction이 budget을 자동 재정규화한다 (CONFIRMED)

**위치** `src/qlibx/portfolio/construction.py:84-98`, 특히 `:93`
**연루** `src/qlibx/flow/portfolio.py:40-46`

```python
selected = tuple(entry for entry in source.weights if entry.weight > 0)   # :84
...
selected_gross = sum(abs(entry.weight) for entry in selected)             # :92
scale = request.requested_budget / selected_gross                          # :93  <-- 문제
```

**증상.** short leg 또는 약한 weight를 제거한 뒤, **남은 종목의 gross로 나눠**
`requested_budget`을 정확히 채우도록 재정규화한다. 결과적으로

- `realized_gross`는 항상 `requested_budget`과 같고,
- `cash_residual = max(0.0, requested_budget - realized_gross)`는 **구조적으로 항상 0**이며,
- 제거된 부분의 budget이 남은 종목에 조용히 재배분된다.

**재현** (실행 확인 완료, §9.1):

```
F-01 targets  : {'A': 0.625, 'B': 0.375}
F-01 gross    : 1.0 residual: 0.0
F-01 diag     : ('negative signed alpha removed for equity long-only target',
                 'construction_scale=2.5')
F-01 short-dropped targets: {'A': 1.0} gross 1.0
```

입력은 flexible alpha `{A:0.25, B:0.15}` (gross 0.40). 출력은 gross 1.0, residual 0.0.
**2.5배 확대**되었고 60% residual은 사라졌다. 유일한 흔적은 diagnostics 문자열
`construction_scale=2.5`뿐이다.

**PRD 위반 조항 (4건).**

- §4.6 — "Tradable instrument만 남기고 target weight를 자동 재정규화"는 silent fallback 금지 목록의 첫 항목.
- §9.3 — "Package가 빈 weight를 자동 재정규화해 두 의미(fixed/flexible)를 바꾸지 않는다."
- UC-ALPHA-BUDGET-001 — "Result는 60% residual을 보존한다. Fixed-budget consumer가 이를 요구하면
  **자동 확대하지 않고** incompatibility를 보고해 user가 normalization 또는 다른 Strategy를 선택하게 한다."
- §15.2 acceptance — "`UC-ALPHA-BUDGET-001`에서 flexible residual을 fixed budget으로 자동 확대하지 않는다."
- §10.4 — "Portfolio result는 requested budget, realized gross/net exposure, cash/residual과
  중요한 clipping reason을 보여준다." → residual이 항상 0이면 이 evidence가 무의미하다.

**부수 원인 — flow 경계에서 budget semantics가 유실된다.**
`flow/portfolio.py:40-46`이 `PortfolioConstructionInput`을 `weights`만으로 만든다.
source `StrategyResult`의 `budget_mode` / `target_gross` / `residual_budget`(§9.2가 보존을
요구하는 값들)이 전달되지 않으므로, `construct_portfolio`는 원래 budget 기준을 알 방법이 없어
subset gross로 나눌 수밖에 없는 구조다. **F-01은 `:93` 한 줄이 아니라 이 경계까지 함께 고쳐야 한다.**

**결정적 주의 — 기존 acceptance 오라클이 이 결함을 계약으로 고정하고 있다.**
`tests/acceptance/test_research_scenarios.py:229-250`
(`test_uc_portfolio_001_constructs_two_portfolios_from_one_real_dw_alpha`)가 다음을 단정한다.

```python
# source alpha: {A000660: -0.5, A005930: +0.5}   (gross 1.0)
assert {...signed...}    == {"A000660": -0.5, "A005930": 0.5}
assert {...long_only...} == {"A005930": 1.0}          # <-- 0.5 가 1.0 으로 확대됨 = F-01
assert signed.result.realized_gross == long_only.result.realized_gross == 1.0
assert long_only.result.realized_net == 1.0
```

즉 **UC-PORTFOLIO-001이라는 PRD use case 이름을 단 테스트가, PRD §4.6·§9.3이 금지한 재정규화를
정답으로 못박고 있다.** 이 테스트를 불변 진실로 취급하지 마라. C2에서
`{"A005930": 0.5}`, `realized_gross == 0.5`, `cash_residual == 0.5`,
`dropped_weights == ({A000660: -0.5},)`로 **오라클을 바로잡아야 한다.**
PRD §16.4가 "Prototype의 accidental 동작을 제품 requirement로 승격하지 않는다"고 한 바로 그 경우다.

`test_uc_alpha_budget_001_preserves_real_dw_flexible_residual`도 §1 때문에 지금 error 상태다.
data/DW 복원 후 읽어라. 통과 중이었다면 residual 보존을 alpha 단계에서만 보고 있고
construction 단계를 보지 않는다는 뜻이므로 오라클을 확장해야 한다.

---

### F-02 — `DecisionIntent` ValidationError가 `run()` 밖으로 새어나간다 (CONFIRMED)

**위치** `src/qlibx/flow/daily.py:753-773` (생성은 `:758`), 전파 경로 `_drain` `:568-576`

```python
if any(weight.weight < 0 for weight in run_result.result.weights):
    self._fail(event, "decision", "SIGNED_TARGET_REQUIRES_CONSTRUCTION")   # :753 음수는 typed
    return
snapshot = self._account.snapshot(evaluation_time=event.ts)
intent = DecisionIntent(                                                   # :758 try/except 없음
    ...
)
```

`DecisionIntent.validate_targets` (`:103-110`)는 `sum(weight) > 1 + 1e-10`이면 `ValueError`를 던지고
pydantic이 이를 `ValidationError`로 감싼다. `_on_decision`에도 `_drain`의
`handler.callback(handler.event)` (`:574`)에도 예외 처리가 없어 `QlibxProject.run_daily()` 밖으로 나간다.

**재현** (실행 확인 완료, §9.2):

```
draft OK, gross 1.2
RAISES: ValidationError
```

`StrategyDraft`는 `target_gross: Field(gt=0)`만 요구하므로 `target_gross=1.2`,
weights `{A:0.7, B:0.5}`가 **정상 draft로 통과**한다. 즉 "잘못된 strategy"가 아니라
**PRD가 허용하는 declaration**이 daily flow에서 crash로 이어진다.

**왜 심각한가.** 예외가 나기 전에 이미 일이 벌어져 있다.

1. `ResearchFlow.invoke_strategy`가 `strategy_result` artifact를 **catalog에 발행 완료**.
2. `_on_decision`이 `self._strategy_results` / `self._published`에 append 완료 (`:706-707`).
3. 그 뒤 `:758`에서 crash → **failure artifact 없음, recovery point 없음, `OperationError` 없음.**

호출자는 `error_code` · `stage_path` · `commit_status` · `idempotency_identity` 없이 raw traceback만 받는다.

**PRD 위반 조항.**

- §2.6 — "Capability가 충족되지 않으면 package는 agent layer가 해석할 수 있도록 observed fact를
  machine-readable하게 보고한다: failure stage, stable error code, ... state 또는 artifact가
  commit되었는지."
- §7.5 — hierarchical operation error contract 전체.
- §6.9 — stage는 `complete` / `incomplete` / `failed` / `unsupported` 중 하나로 끝나야 한다.
  예외 전파는 이 넷 중 어느 것도 아니다.

**동일 계열의 잠재 위험.** `_drain`이 callback 예외를 전혀 번역하지 않으므로,
`_on_execution`의 `view.session(...)` pandas 예외, `_on_mark`의 `float(getattr(row, ...))`
변환 예외 등도 같은 방식으로 새어나간다. **C1은 개별 검사뿐 아니라 `_drain`의
번역 계층까지 넣어야 한다** (§5.1).

---

### F-03 — memoryless strategy가 ~129 세션에서 강제 중단된다 (CONFIRMED)

**위치** `src/qlibx/flow/daily.py:660-686`

```python
memory_state = self._memory.snapshot(self._strategy.strategy_id)           # :660
account_feedback = self._account.feedback(
    memory_state.feedback_cursor,                                          # :663  <-- 문제
    self._profile.feedback_entry_limit,
)
...
if account_feedback.next_cursor != account_state.feedback_cursor:          # :674
    self._fail(event, "decision.feedback", "ACCOUNT_FEEDBACK_WINDOW_EXCEEDED", ...)
```

**증상.** window 시작점이 **Strategy Memory의 cursor**다. 그런데
`StrategyMemoryStore.snapshot`(`account/memory.py:21-25`)은 미등록 strategy에 대해
`feedback_cursor=0`인 기본 스냅샷을 돌려준다. **memory를 한 번도 commit하지 않는 strategy는
cursor가 영원히 0**이므로, 검사는 사실상 "account journal 전체가
`feedback_entry_limit` 안에 들어가는가"가 된다.

Account journal은 세션당 약 2개씩 자란다.

- `_on_mark`가 보유 포지션이 있을 때 세션마다 `MarkBatch` 1건 commit (`daily.py:1240`)
- `_on_execution`이 체결이 있을 때 `FillBatch` 1건 commit (`daily.py:1079`)

기본 `feedback_entry_limit = 256`(`daily.py:218`, `simulation.py:30`)이므로
**약 129번째 세션에서 run이 `ACCOUNT_FEEDBACK_WINDOW_EXCEEDED`로 중단**된다.
strategy가 feedback을 **읽지도 않는데** 그렇다.

**재현** (실행 확인 완료, §9.3):

```
F-03 default memory cursor: 0
F-03 journal len: 300 feedback next_cursor: 256 -> window check fails: True
```

**기존 테스트가 같은 메커니즘을 이미 보여준다.**
`tests/acceptance/test_execution_scenarios.py:236`
`test_feedback_window_fails_before_strategy_when_limit_is_too_small`가
`feedback_entry_limit=1`과 memory를 쓰지 않는 `TargetStrategy`로 정확히 이 실패를 단정한다.
즉 **현재 동작은 "의도된 bounded 계약"으로 문서화되어 있지만, 그 경계가 strategy의
feedback 소비 여부와 무관하게 걸린다는 점이 문제다.**

**PRD 위반 조항.**

- §5.7 — "Historical backtest와 portable research catalog"가 current scope인데
  memoryless strategy의 backtest가 6개월을 못 넘긴다.
- §3.5 UC-SCALE-001 — "일별 횡단면 universe에서 ... 시간 축 closed loop를 유지해야 한다."
- §9.10 — resume/checkpoint 계약은 장기 run을 전제한다.

**주의: 이건 단순 버그가 아니라 semantics 결정이다.** §5.3에서 옵션 A/B를 제시했다.
`_plan_memory`의 initialization 판정(`daily.py:1434-1447`)이 `state_access.feedback_cursor == 0`을
요구하므로, window 시작점을 바꾸면 **initialization 조건도 같이 손봐야 한다.** 이 결합을
모르고 고치면 UC-ALPHA-ADAPTIVE-001이 깨진다.

---

### F-04 — recovery point가 전체 journal을 매 이벤트 직렬화한다 (CONFIRMED, Θ(N²))

**위치** `src/qlibx/flow/recovery.py:49` (`account_checkpoint: AccountCheckpoint`),
발행 지점 `src/qlibx/flow/daily.py:1658-1742`

**중첩 구조.**

```
SimulationRecoveryPoint            (flow/recovery.py:35)
 ├─ account_checkpoint: AccountCheckpoint      (account/account.py:110)
 │    └─ journal: tuple[JournalEntry, ...]     (account/account.py:118)
 │         └─ JournalEntry.fills: tuple[Fill, ...]   (account/account.py:70)  <-- 전체 체결 이력
 │         └─ applied_events: tuple[str, ...]                                  <-- 전체 event id
 ├─ event_trace: tuple[str, ...]               (:51)  <-- 지금까지의 모든 이벤트 문자열
 └─ completed_decision_ids: tuple[str, ...]    (:52)
```

**발행 빈도.** `_publish_recovery_point` 호출 지점 6곳 (`daily.py:499, 537, 730, 810, 1067, 1225`)
= 초기 1회 + DECISION마다 + EXECUTION마다 + MARK마다. 세션당 약 3회.

**비용.** 세션 k의 recovery point는 세션 1..k의 **모든 Fill을 다시 JSON으로 직렬화**한다.
UC-SCALE-001 규모(3,000종목 일별 횡단면, 250세션)에서

- 세션당 `FillBatch` 1건 = 최대 3,000개 `Fill` ≈ 600 KB JSON
- 세션 250의 recovery point 1건 ≈ 250 × 600 KB ≈ **150 MB**
- 세션당 3회 × 250세션 = 750건, 총 기록량 ≈ 3 × Σ(0.6 MB × k) ≈ **수십 GB**

게다가 **오래된 recovery point를 정리하는 코드가 없다.** catalog가 무한히 자란다.

**왜 지금까지 안 드러났나.** UC-SCALE-001 커버리지는
`tests/test_exchange_batch.py::test_uc_scale_001_three_thousand_names_keep_stable_batch_order`
**단일 batch parity 하나뿐**이다(`tests/scenarios/current_contracts.yaml:102-107`).
3,000종목 × 다세션 closed loop는 검증되지 않는다.

**PRD 근거.** §3.5 UC-SCALE-001("Supported resource profile에서 ... 경제적 결과가 일치"),
§9.10 / GAP-RECOVERY-001(장기 run의 resume).

**경고.** GAP-RECOVERY-001의 crash matrix(`tests/scenarios/recovery.yaml`,
`tests/acceptance/test_recovery_scenarios.py`)가 **각 crash point에서 resume 결과가
uninterrupted와 동일함**을 요구한다. recovery point 발행 빈도를 줄이는 최적화는 이 오라클을
직접 깬다. §4.3과 §5.6을 반드시 읽어라.

---

### F-05 — 시뮬레이션 분석이 hold-only run을 거부하고 initial NAV를 잘못 잡는다 (CONFIRMED)

**위치** `src/qlibx/analysis/results.py:178` 및 `:187`

```python
if not source.executions:
    raise AnalysisError("ANALYSIS_EXECUTION_INPUT_MISSING", {})   # :178
...
initial_nav = source.executions[0].initial_nav                     # :187
```

**증상 (a) — hold-only run을 분석할 수 없다.**
strategy가 매 세션 `hold`를 반환한 run은 정상 완료되어 checkpoint를 발행하지만
`AnalysisFlow.analyze_simulation`이 `ANALYSIS_EXECUTION_INPUT_MISSING`으로 실패한다.
PRD §9.7은 "새로운 주문을 만들지 않는 `hold`도 정상적인 decision이다"라고 못박는다.

**증상 (b) — `total_return`의 기준 NAV가 "첫 거래 세션"의 NAV다.**
run 시작 NAV가 아니다. 그리고 `executions[0]`은 **caller가 `execution_artifact_ids`에
넣은 순서**에 의존한다(`flow/analysis.py:94-101`이 요청 순서대로 append).
`ExecutionAnalysisInput`에는 시간 정보가 없어 정렬조차 불가능하다.

**재현** (실행 확인 완료, §9.4):

```
F-05a hold-only run -> ANALYSIS_EXECUTION_INPUT_MISSING
F-05b total_return depends on execution order: 0.0 vs 0.04
```

동일한 checkpoint와 동일한 execution 집합인데 **순서만 바꾸면 총수익률이 0% ↔ 4%로 바뀐다.**

**PRD 위반 조항.**

- §9.7 — hold는 정상 decision.
- §13.1 UC-REPORT-001 — "Renderer가 달라도 return, cost, exposure의 underlying value와
  lineage는 같아야 한다." 입력 순서로 값이 바뀌면 결정론이 깨진다.
- §16.2 — "same frozen input의 deterministic replay."

---

### F-06 — resume이 모든 recovery point를 load한다 (CONFIRMED)

**위치** `src/qlibx/flow/daily.py:1747-1772`

```python
envelopes = tuple(
    envelope for envelope in self._artifacts.list_envelopes()      # :1749 전체 카탈로그 역직렬화
    if envelope.logical_identity.startswith(prefix) ...
)
...
for envelope in envelopes:
    loaded = self._artifacts.load_model(envelope.artifact_id, SIMULATION_RECOVERY_POINT_CONTRACT)
    ...
    loaded_points.append(...)                                       # :1763-1771 전부 load
_, point = max(loaded_points, key=lambda item: item[1].sequence)    # :1772 하나만 사용
```

`list_envelopes()`는 필터 인자가 `include_failure` / `artifact_type`뿐이라
(`evidence/local.py:471-496`) **카탈로그 전체 envelope을 역직렬화**한 뒤 파이썬에서 prefix를 거른다.
그 다음 해당 run의 recovery point **전부**를 `load_model`한다 — `max(sequence)` 하나를 구하려고.

**이미 순서 정보가 identity에 있다.** `daily.py:1706`:

```python
logical_identity=f"simulation-recovery:{self._request.run_id}:{sequence:08d}:{suffix}"
```

zero-padded 8자리이므로 사전순 최대 = 수치 최대(sequence < 10^8). payload를 읽을 필요가 없다.

**F-04와 곱해진다.** 각 point가 전체 journal을 담으므로, resume은
**전체 이력의 제곱만큼을 디스크에서 읽고 pydantic 검증**한 뒤 첫 callback을 실행한다.

**부수 효과 (개선).** 현재는 point 하나라도 load 실패하면 resume 전체가 실패한다.
최신 하나만 읽으면 오래된 point의 손상이 resume을 막지 않는다. **이건 semantics 변화이므로
implementation record에 명시할 것.**

---

### F-07 — 선언된 axis/time requirement가 강제되지 않는다 (CONFIRMED)

**위치** `src/qlibx/data/requirements.py:69-78` (resolver), 선언은 `:15-34`

```python
class ComponentRequirement(QlibxModel):
    requirement_id: str
    semantic_role: str
    axis: AxisRequirement = AxisRequirement()        # :31  선언되지만
    time: TimeRequirement = TimeRequirement()        # :32  선언되지만
    compatibility: tuple[CompatibilityRule, ...] = ()
    dataset_id: str | None = None
```

`RequirementResolver.resolve`의 candidate 필터(`:69-78`)는
`semantic_role` · `dataset_id` · `compatibility`만 본다. **`axis`와 `time`은 어디에서도 읽히지 않는다.**

**결과.** Strategy가 `axis=AxisRequirement(kind="scalar")`를 선언해도 instrument-time panel에
조용히 바인딩되고, 계산은 잘못된 axis 위에서 진행된다.
`time.available_at_required=False`도 마찬가지로 존중되지도 거부되지도 않는다.

**PRD 위반 조항.**

- §7.3 — "Strategy, model, optimizer, report 또는 executor는 실제로 호출될 때 자신에게 필요한
  capability를 선언한다. 등록된 dataset이 requirement를 충족하지 못하면 package는 해당 operation을
  state mutation 전에 멈추고 structured error를 전달한다."
- §7.7 — "Unknown은 자동으로 tradable 또는 non-member로 바꾸지 않고 해당 operation의 policy에 따라
  fail, exclude 또는 warn한다."
- §4.6 — "Unknown field, instrument 또는 exposure axis를 임의로 제외."

**중요 — 이건 public artifact schema다.**
`ComponentRequirement`는 `src/qlibx/extensions/strategy.py:87`의
`dataset_requirements: tuple[ComponentRequirement, ...]`를 통해 **strategy extension registration
artifact에 직렬화되어 저장된다.** 필드를 제거하면 §16.3(schema change) 절차가 필요하다.
`src/qlibx/analysis/results.py:95`의 `SignalAnalysisRequest.return_requirement`도 같은 타입이다
(이쪽은 request이지 published payload는 아니다).

**확인 완료 — 기본값 외의 값이 이 저장소 어디에서도 쓰이지 않는다.**

```
grep -rn "AxisRequirement|TimeRequirement|available_at_required|axis=" src/ tests/
-> src/qlibx/data/registry.py:132  (무관한 pandas `.any(axis=1)`)  ... 그 외 히트 없음
```

`kind="scalar"` / `kind="any"` / `available_at_required=False`를 생성하는 코드가 하나도 없다.
따라서 §5.8의 옵션 (c)(Literal로 좁히기)는 **기존 직렬화 값과 100% 호환**되며 마이그레이션이 필요 없다.

---

### F-08 — query마다 소스 파일 전체를 재해싱한다 (CONFIRMED)

**위치** `src/qlibx/data/store.py:39-53`

```python
source = Path(dataset.source).resolve()
if not source.is_file() or file_hash(source) != dataset.physical_fingerprint:   # :40  매 호출
    raise DataSnapshotError(...)
cache_key = (...)
cached = self._frame_cache.get(cache_key)                                        # :50  해시 후에 캐시 조회
```

`file_hash`(`data/registry.py:26-31`)는 1 MB 청크로 **파일 전체를 읽어 SHA-256**을 계산한다.
프레임 캐시(record 049)는 읽기·정규화를 1회로 줄였지만 **해시는 매 query마다 돈다.**

**호출 빈도** (daily flow, 세션당):
`_on_execution`의 execution price session query 1회 (+volume 1회),
`_on_mark`의 valuation price session query 1회, 그리고 Strategy의 모든 `history`/`latest`/`session` 호출.

250세션 × 최소 3회 = **750회 이상**. 3,000종목 × 250세션 CSV(≈50 MB)면 약 **37 GB 해싱**.
그 사이 `_load_normalized_frame`은 정확히 1회 돈다.

**의도된 동작이긴 하다.** `tests/test_observation_store_cache.py:52`
`test_warm_cache_hashes_every_query_but_reads_and_normalizes_once`가 이름 그대로 단정한다.
그러나 비용이 run 길이와 데이터 크기에 대해 **무제한**이며, PRD §7.10(frozen invocation)은
invocation 단위 검증으로 같은 무결성을 더 싸게 얻을 근거를 제공한다(§5.7 참조).

---

### F-09 — 필터 전에 전체 프레임을 복제한다 (CONFIRMED)

**위치** `src/qlibx/data/store.py:54`, 연관 `src/qlibx/context/scoped.py:238`

```python
visible = cached.copy()                                    # store.py:54  전체 복사
visible = visible.loc[visible["available_at"] <= cutoff]   # store.py:55  이미 새 객체 반환
...
return frame.rename(columns={"value": semantic_role}).copy()   # scoped.py:238  또 복사
```

query 한 번에 **full-size 복제가 3회** 발생한다. 750,000행 프레임에서 3,000행을 고르는
session query가 먼저 750,000행을 통째로 복사한다.
`.loc[boolean]`이 이미 새 DataFrame을 반환하므로 `:54`의 `.copy()`는 순수 낭비다.

250세션 run의 750여 query에 걸쳐 수억 행을 할당·폐기한다.

---

### F-10 — `total_market_volume`이 주입되지 않아 impact 경로가 도달 불가다 (CONFIRMED)

**위치** `src/qlibx/flow/daily.py:925-932`

```python
quotes=tuple(
    MarketQuote(
        instrument_id=instrument,
        price=prices[instrument],
        available_volume=volumes.get(instrument),
        #  total_market_volume 을 절대 채우지 않는다
    )
    for instrument in required_instruments
),
```

`KrxExchange.match_batch`(`execution/exchange.py:168-180`)는 `impact_rate > 0`이면
`total_market_volume`이 없을 때 모든 주문을 `EXECUTION_MARKET_VOLUME_MISSING`으로 거부한다.
그런데 daily flow에는 **total market volume에 해당하는 role이나 requirement 자체가 없다.**
retry 안내("provide positive total_market_volume or use an impact-free profile")를
이 flow를 통해서는 만족시킬 방법이 없다.

동시에 `DailyExecutionProfile.volume_role`(`daily.py:216`)은
`QlibxProject._run_daily`(`project.py:337-342`)에서 **한 번도 설정되지 않으므로**
participation-rate 경로(`daily.py:842-887`, `exchange.py:193-197`)도 public API에서 도달 불가다.

`DailySimulationSpec`(`simulation.py:62-65`)이 `participation_rate`와 `impact_rate != 0`을
공개적으로 거부하므로 **결함이 노출되지 않고 가려져 있을 뿐**이다.

**판단.** PRD §5.7과 §11.2는 partial fill / intraday liquidity를 future work로 두므로
**현재 scope에서는 "지원 안 함"이 정답**이다. 문제는 지원하지 않는 기능의 코드 경로가
반쯤 남아 있어 §4.6의 "unsupported behavior의 명시적 실패"가 아니라
"설정하면 아무 이유 없이 전부 실패"가 된다는 점이다.

**기존 테스트 상황 (확인 완료).**

- `tests/acceptance/test_execution_scenarios.py:323-355`
  `test_daily_profile_rejects_impact_without_total_market_volume`가
  **현재 동작을 계약으로 단정한다**: `impact_rate=0.001` → `OutcomeStatus.FAILED`,
  `EXECUTION_MARKET_VOLUME_MISSING`, `commit_status is NONE`, account version 0 유지.
  즉 "impact를 켜면 mutation 없이 실패한다"가 이미 의도된 계약이다.
  → §5.8 옵션 (b)를 택하면 이 테스트는 **유지**하되, `volume_role` 제거로 인한 시그니처 변화만 반영.
    옵션 (a)를 택하면 이 테스트를 "role을 선언하지 않았을 때만 실패"로 좁혀야 한다.
- `tests/test_exchange_batch.py:244, 268-269`가 `price_impact_rate` 산술을 직접 검증한다
  (`impact_rate=0.1`, `(99/1000)**2` 등). **따라서 `KrxExchange`의 impact/participation 산술은
  어떤 옵션에서도 삭제하면 안 된다.** 제거 대상은 daily flow 쪽 배선뿐이다.

---

### F-11 — instrument position-direction 계약이 없다 (PLAUSIBLE)

**위치** `src/qlibx/execution/instruments.py:11-45`

`StockInstrument` / `EtfInstrument` 어느 쪽에도 position direction 필드가 없다.

**계약 요구.**

- PRD §7.12 — "Instrument type, venue와 execution profile은 가능한 position direction, ... 을 결정한다.
  `long_only`, `hypothetical_short`, borrow-aware short와 derivative exposure를 같은 capability로 취급하지 않는다."
- PRD §5.6 — 금지: "Position-direction contract 없이 negative Position을 executable short라고 주장."
- PRD §5.7 — current scope 목록에 "**`hypothetical_short` instrument를 사용하는 signed research (§7.12)**"가 있다.
- `docs/qlibx-architecture.md:2790` — "instrument가 선언하는 값이며,
  `long_only` / `hypothetical_short` / `real_short` 세 값을 갖는다."
- `docs/qlibx-architecture.md:2472` — "unknown은 `long_only`로 처리한다."
  (**이 문장 자체가 §4.6의 silent fallback 금지와 충돌한다. 구현 전에 architecture 쪽을 정리해야 한다.**)

**현재 코드 동작.**
`_on_decision:753`이 음수 weight를 `SIGNED_TARGET_REQUIRES_CONSTRUCTION`으로 거부하고,
`match_batch`의 SELL 경로(`exchange.py:199-208`)가 보유수량으로 무조건 clip한다(`HOLDING_LIMIT`).
결과적으로 short intent를 **표현할 수단도, profile 차원에서 거부할 수단도 없다.**
"여기서는 허용되지 않음"과 "팔 물건이 없었음"이 같은 diagnostic으로 뭉개진다.

**PLAUSIBLE로 둔 이유.** 실행으로 재현한 결함이 아니라 **계약 부재**다.
수정 방향이 "기능 구현"이냐 "PRD readiness gap 표에 정직하게 추가"냐는 product decision이다(§5.8).

---

## 4. 설계 제약 — 고치기 전에 반드시 읽을 것

순진한 수정이 깨뜨리는 기존 보장들이다.

### 4.1 Account journal은 evidence이자 idempotency 근거다

`AccountCheckpoint`의 불변식(`account/account.py:209-223`):

```python
if checkpoint.version != len(checkpoint.journal): raise ...
if set(checkpoint.applied_events) != {e.event_id for e in checkpoint.journal}: raise ...
if checkpoint.as_of != checkpoint.journal[-1].as_of: raise ...
```

**F-04에서 journal을 잘라내면 이 셋이 전부 깨진다.**
`version == len(journal)`을 `version == journal_base_cursor + len(journal)`로 바꾸고,
`applied_events`를 journal 파생이 아닌 독립 필드로 승격해야 한다.
`Account.feedback(after, limit)`(`:273-282`)도 base cursor를 반영해야 한다.

### 4.2 Memory cursor는 "확정 소비된 feedback"의 authority다

`_plan_memory`(`daily.py:1401-1498`)는 세 가지를 동시에 요구한다.

1. `feedback_access.after_cursor == current.feedback_cursor` — 건너뛴 feedback 없음
2. `feedback_access.next_cursor <= state_access.feedback_cursor` — 미래 fill 선취 없음
3. `feedback_cursor > current.feedback_cursor` (initialization 제외) — 전진 강제

그리고 initialization 판정(`:1441-1447`)은 `state_access.feedback_cursor == 0`을 요구한다.
**F-03에서 window 시작점을 바꾸면 이 initialization 조건이 성립하지 않는 시점이 생긴다.**
UC-ALPHA-ADAPTIVE-001과 `test_first_decision_can_initialize_memory_without_feedback`,
`test_memory_update_after_initialization_still_requires_new_feedback`이 오라클이다.

### 4.3 recovery point는 "commit 직전"에 발행되어야 한다

`_on_execution`(`daily.py:1067-1102`)의 순서가 계약이다.

```
candidate 계산 → recovery point 발행(post-state 포함) → live commit → 결과 대조
```

크래시가 어디서 나든 resume이 동일 결과를 내는 이유가 이 순서다.
`_should_schedule`(`:1630-1634`)이 `(ts, priority) > resume_position`으로 **이미 지나간 이벤트를
재실행하지 않고**, `pending_publications`가 누락된 artifact만 idempotent하게 발행한다.

**F-04를 "발행 빈도를 줄여서" 고치면 이 보장이 깨진다.**
`tests/scenarios/recovery.yaml`의 crash matrix가 각 지점을 개별 검증한다.
**허용되는 최적화는 "얼마나 자주 쓰는가"가 아니라 "한 번에 얼마나 쓰는가"뿐이다.**

### 4.4 catalog publication은 logical_identity로 idempotent하다

`publish_model`(`evidence/local.py:224-247`)은 같은 `logical_identity` + 같은 content_hash면
기존 envelope을 반환하고, 내용이 다르면 `ARTIFACT_IDENTITY_CONFLICT`로 실패한다.
resume 시 재발행이 안전한 근거다. **payload 구조를 바꾸면 content_hash가 바뀌므로,
resume 중인 기존 run은 identity conflict를 맞는다.** schema 변경 커밋은
"진행 중 run은 재개 불가, 새 run 필요"를 implementation record에 명시해야 한다.

### 4.5 artifact schema 변경은 dual-contract 패턴을 따른다

`load_model`(`evidence/local.py:440-452`)은 `artifact_schema_version` 불일치를
`ARTIFACT_CONTRACT_UNSUPPORTED`로 명시 실패시킨다(§16.3 충족).
기존 artifact를 계속 읽어야 하면 `STRATEGY_RESULT_CONTRACTS`
(`flow/strategy_results.py:31-34`)가 이미 쓰는 **버전별 contract 튜플 + envelope 기반 dispatch**를
그대로 따라라. `load_strategy_result`(`:39-77`)가 참고 구현이다.

### 4.6 `ObservationStore`의 해시는 PIT 무결성 계약의 일부다

F-08을 mtime/size 비교로 완화하는 것은 **가장 유혹적이면서 가장 위험한 수정**이다.
같은 mtime·size로 내용이 바뀌는 경우가 드물지만 존재하고, 그 순간
`registration_identity`가 가리키는 것과 다른 데이터로 backtest가 돈다.
§5.7의 권고안(frozen invocation scope)은 이 위험을 지지 않는 대안이다.

### 4.7 `DailyExecutionFlow`는 single-use다

`_prepare`(`daily.py:521-522`)가 재사용을 `RuntimeError`로 막는다. 상태 필드를 추가할 때
`__init__`과 `_restore_recovery_point`(`:1842-1853`) **양쪽**을 갱신해야 한다.

---

## 5. 수정 계획 (제안)

### 5.0 커밋 순서와 이유

| 커밋 | finding | 왜 이 순서인가 |
|---|---|---|
| **C0** | §1 | data/DW 복원. **모든 검증의 선행 조건.** |
| **C1** | F-02 | 독립적·저위험. 이후 커밋의 안전망(예외 → typed error)을 먼저 깐다. |
| **C2** | F-01 | 정확성 최우선. artifact schema v2 필요. |
| **C3** | F-05 | C2와 같은 "budget/NAV evidence" 계열. checkpoint schema 변경. |
| **C4** | F-03 | semantics 결정 필요. **user 승인 후.** |
| **C5** | F-06 | 저위험 perf. C6의 계측을 쉽게 만든다. |
| **C6** | F-04 | 최대 작업. 계측(C6-a) → 수정(C6-b) 2단계. |
| **C7** | F-08, F-09 | 독립적 perf. 언제 해도 되지만 C6 계측 노이즈를 줄이려면 뒤에. |
| **C8** | F-07, F-10, F-11 | contract 정리. 일부는 문서 수정으로 닫을 수 있다. **user 승인 후.** |

C2·C3은 artifact schema를 올린다 → §4.4·§4.5를 먼저 읽어라.

---

### 5.1 C1 — daily flow의 예외를 typed failure로 번역 (F-02)

**파일** `src/qlibx/flow/daily.py`

1. **`_on_decision`에 명시 검사 추가** (`:753` 음수 검사 바로 뒤, `:757` snapshot 앞):

   ```python
   target_gross = sum(weight.weight for weight in run_result.result.weights)
   if target_gross > 1 + 1e-10:
       self._fail(
           event, "decision", "DAILY_TARGET_BUDGET_UNSUPPORTED",
           context={
               "target_gross": target_gross,
               "supported_maximum": 1.0,
               "budget_mode": run_result.result.budget_mode.value,
               "declared_target_gross": run_result.result.target_gross,
           },
       )
       return
   ```

   - error code는 새 stable ID다. 기존 `SIGNED_TARGET_REQUIRES_CONSTRUCTION`과 나란히 둔다.
   - retry precondition은 `_fail`의 기본 문구 대신
     "declare a target gross within the long-only capital of this profile, or use portfolio
     construction to scale the alpha" 같은 구체적 문구를 주는 것이 §2.6에 맞다.
     → `_fail`에 optional `retry_preconditions` 인자를 추가해도 좋다.

2. **`DecisionIntent(...)` 생성을 방어적으로 감싼다**:

   ```python
   try:
       intent = DecisionIntent(...)
   except ValidationError as exc:
       self._fail(event, "decision", "DECISION_INTENT_INVALID",
                  context={"message": str(exc)[:500]})
       return
   ```

3. **`_drain`의 callback 호출을 번역 계층으로 감싼다** (`:574`) — **이게 핵심이다**:

   ```python
   try:
       handler.callback(handler.event)
   except Exception as exc:                       # noqa: BLE001 - boundary translation
       self._fail(
           handler.event,
           f"callback.{handler.event.name.lower()}",
           "DAILY_FLOW_CALLBACK_FAILED",
           context={"exception": type(exc).__name__, "message": str(exc)[:500]},
       )
       break
   ```

   `_fail`이 `_event_commits(event)`로 해당 이벤트의 authority commit을 자동 수집하므로
   `commit_status`가 정확히 채워진다(§2.6의 "state 또는 artifact가 commit되었는지").
   `ResearchFlow.invoke_strategy`가 이미 같은 패턴을 쓴다(`flow/research.py:183-197`) — 참고하라.

**테스트** `tests/acceptance/test_execution_scenarios.py`에 추가:

- `target_gross=1.2`인 long-only strategy → `OutcomeStatus.FAILED`,
  `error_code == "DAILY_TARGET_BUDGET_UNSUPPORTED"`, `stage_path == "daily_flow.decision"`,
  `commit_status == CommitStatus.NONE`, failure artifact가 catalog에 존재.
- `_on_mark` 안에서 인위적 예외를 발생시키는 monkeypatch → `DAILY_FLOW_CALLBACK_FAILED`.

**리스크** 낮음. `_drain`의 `except Exception`이 기존 `_fail` 경로를 이중 처리하지 않는지 확인
(`_fail`은 예외를 던지지 않고 `self._errors`에 append하므로 안전).

---

### 5.2 C2 — construction의 자동 재정규화 제거 (F-01)

**파일** `src/qlibx/portfolio/construction.py`, `src/qlibx/flow/portfolio.py`

**1) budget semantics를 flow 경계에서 전달한다.**
`PortfolioConstructionInput`에 source alpha의 budget 정보를 추가:

```python
class PortfolioConstructionInput(QlibxModel):
    source_strategy_id: str
    weights: tuple[PortfolioWeight, ...]
    source_budget_mode: BudgetMode            # 신규
    source_target_gross: float = Field(gt=0)  # 신규
```

`flow/portfolio.py:40-46`에서 `strategy.budget_mode` / `strategy.target_gross`를 채운다.

**2) 스케일 기준을 subset gross → source target_gross로 바꾼다** (`:92-93`):

```python
# 이전: scale = request.requested_budget / selected_gross     <- 재정규화
scale = request.requested_budget / source.source_target_gross  # 원래 budget 기준
```

이렇게 하면 drop된 short/약한 weight만큼 **realized_gross가 requested_budget보다 작게 남고**,
`cash_residual`이 실제 값을 갖는다. §9.3의 flexible semantics가 보존된다.

**3) fixed budget 요구는 명시 실패시킨다** (UC-ALPHA-BUDGET-001의 "incompatibility를 보고"):

```python
if request.budget_mode is BudgetMode.FIXED and not math.isclose(
    realized_gross, request.requested_budget, abs_tol=1e-10
):
    raise PortfolioConstructionError(
        "CONSTRUCTION_FIXED_BUDGET_INCOMPATIBLE",
        {"realized_gross": realized_gross,
         "requested_budget": request.requested_budget,
         "dropped_gross": dropped_gross},
    )
```

`PortfolioConstructionRequest`에 `budget_mode: BudgetMode` 추가.

**4) 명시적 재정규화는 opt-in으로만.**
`PortfolioConstructionRequest`에 `renormalize_to_budget: bool = False`.
`True`일 때만 기존 동작을 하되, `diagnostics`가 아니라 **구조적 evidence**를 남긴다.

**5) drop evidence를 구조화한다.** `PortfolioConstructionResult`에 추가:

```python
dropped_weights: tuple[PortfolioWeight, ...] = ()
dropped_gross: float = 0.0
renormalized: bool = False
renormalization_scale: float | None = None
```

§10.4의 "중요한 clipping reason"을 문자열이 아닌 조회 가능한 값으로.

**6) schema를 v2로 올린다.**
`portfolio_construction_result` v1 → v2. §4.5의 dual-contract 패턴을 따라
`PORTFOLIO_RESULT_CONTRACT_V1`을 남기고 `PORTFOLIO_RESULT_CONTRACT`(v2)를 추가.
**`flow/constraints.py:61-64`의 `ConstraintFlow.adjust`가 이 contract로 load하므로 반드시 함께 갱신한다.**

**테스트**

- 신규 `tests/test_portfolio_construction.py`:
  flexible `{A:0.25,B:0.15}` + `target_gross=1.0` + `requested_budget=1.0`
  → `target_weights == {A:0.25, B:0.15}`, `realized_gross == 0.4`, `cash_residual == 0.6`.
- short drop: `{A:0.5, B:-0.5}` → `{A:0.5}`, residual 0.5, `dropped_weights == ({B:-0.5},)`.
- fixed budget 요구 시 `CONSTRUCTION_FIXED_BUDGET_INCOMPATIBLE`.
- `renormalize_to_budget=True`면 옛 동작 + `renormalized=True`, `renormalization_scale=2.5`.
- **`tests/acceptance/test_research_scenarios.py:243-250` 오라클 교정 (필수).**
  `{"A005930": 1.0}` → `{"A005930": 0.5}`,
  `long_only.result.realized_gross == 1.0` → `== 0.5`,
  `long_only.result.realized_net == 1.0` → `== 0.5`,
  `cash_residual == 0.5` 와 `dropped_weights` 단정을 추가.
  `signed`(HYPOTHETICAL_SIGNED) 쪽은 gross가 이미 1.0이므로 **변하지 않아야 한다** — 회귀 감시점.
- `test_uc_alpha_budget_001_preserves_real_dw_flexible_residual` 오라클을
  **construction 단계까지 확장**한다(§3 F-01의 결정적 주의 참조).

**블라스트 반경 (확인 완료).** `realized_gross` / `cash_residual` 소비처는 아래가 전부다.

| 위치 | 영향 |
|---|---|
| `tests/acceptance/test_research_scenarios.py:245-250` | **교정 필요** (위 참조) |
| `src/qlibx/portfolio/constraints.py:92, 223` | `ConstraintAdjustmentResult`의 **별도** `cash_residual`. `source.requested_budget - adjusted_gross`로 계산하므로 C2 이후 실제 값이 생긴다. adjustment 테스트의 기대값 재확인 필요 |
| `src/qlibx/resources/samples/constraint_workflow/run.py:133` | 샘플이 값을 출력만 함. 결정론 오라클(`test_public_constraint_sample.py`)의 기대 출력 갱신 필요 |
| `tests/test_portfolio_constraints.py:40-42`, `tests/test_public_constraints.py:96-98` | fixture가 `realized_gross`/`cash_residual`을 직접 지정. 스키마 v2 필드 추가에 맞춰 갱신 |

**리스크** 중간. `PortfolioConstructionResult`를 v2로 올리므로 §4.4대로
"기존 v1 artifact를 참조하던 진행 중 constraint workflow는 재실행 필요"를 record에 남긴다.

---

### 5.3 C3 — 시뮬레이션 분석의 기준 상태를 명시화 (F-05)

**파일** `src/qlibx/analysis/results.py`, `src/qlibx/flow/analysis.py`, `src/qlibx/flow/daily.py`

**1) checkpoint에 run 시작 상태를 기록한다.**
`SimulationCheckpoint`(`daily.py:186-199`)에 `initial_account: StateAccessRecord` 추가,
`checkpoint_schema_version: Literal[3] = 3`.
값은 flow 시작 시점(`_prepare` 직후)의 `_state(self._account.snapshot())`.
`_restore_recovery_point`에서도 복원되도록 `SimulationRecoveryPoint`에 함께 실어야 한다
— **C6와 충돌하므로 C6 설계 시 이 필드를 고려할 것.**

`SIMULATION_CHECKPOINT_CONTRACT`(`flow/analysis.py:54-58`)를 v3로 올리되 v2 reader를 남긴다(§4.5).
**`project.py:237-244`의 `monitor_constraints`가 이 contract를 쓰므로 함께 갱신한다.**

**2) `analyze_simulation`이 checkpoint의 initial NAV를 쓴다.**

```python
class SimulationAnalysisInput(QlibxModel):
    checkpoint_state: StateAccessRecord
    initial_state: StateAccessRecord          # 신규
    journal_event_count: int
    executions: tuple[ExecutionAnalysisInput, ...]
    failure_count: int
```

`initial_nav = source.initial_state.nav`. `executions[0]` 참조를 제거한다.

**3) 빈 executions를 정상 처리한다.**

```python
# 제거: if not source.executions: raise AnalysisError("ANALYSIS_EXECUTION_INPUT_MISSING", {})
```

`total_cost = 0`, `fill_count = 0`으로 계산이 진행되게 한다.
**누락 감지는 다른 조건으로 옮긴다**: checkpoint journal에 `FillBatch` entry가 있는데
`executions`가 비어 있으면 그때 `ANALYSIS_EXECUTION_INPUT_MISSING`.
→ `SimulationAnalysisInput`에 `journal_fill_event_count: int`를 추가하고
`flow/analysis.py`가 `account_checkpoint.journal`에서 세어 넘긴다.

**4) 순서 의존성을 제거한다.**
`ExecutionAnalysisInput`에 `event_time: datetime`을 추가하고
`analyze_simulation`이 `sorted(source.executions, key=lambda i: (i.event_time, i.event_id))`로 정규화.
`flow/analysis.py:120-129`에서 `item.event_time` / `item.event_id`를 채운다.

**테스트**

- hold-only run(체결 0건) → `OutcomeStatus.COMPLETE`, `total_return`이 initial→final NAV로 계산.
- 동일 execution 집합을 순서만 바꿔 두 번 분석 → `values_fingerprint` 동일.
- journal에 fill이 있는데 `execution_artifact_ids`가 비면 `ANALYSIS_EXECUTION_INPUT_MISSING`.
- v2 checkpoint artifact를 v3 contract로 읽으면 `ARTIFACT_CONTRACT_UNSUPPORTED`,
  v2 reader로는 성공(§16.3).

---

### 5.4 C4 — feedback window를 memory 존재 여부와 분리 (F-03) — **product decision 필요**

**파일** `src/qlibx/flow/daily.py`

세 옵션. **user 승인 없이 확정하지 마라.**

#### 옵션 A (권고) — memory authority가 아직 없으면 빈 window를 준다

```python
memory_state = self._memory.snapshot(self._strategy.strategy_id)
memory_established = memory_state.version > 0 or memory_state.commit_id is not None
window_start = (
    memory_state.feedback_cursor if memory_established
    else account_state.feedback_cursor          # 소급 소비하지 않음
)
account_feedback = self._account.feedback(window_start, self._profile.feedback_entry_limit)
```

의미: "아직 어떤 feedback도 확정 소비한 적 없는 strategy는 과거 feedback을 소급 소비하지 않는다."
미래 fill 선취가 아니므로 §4.4 / §9.11에 위배되지 않는다.

**반드시 함께 고쳐야 하는 것 (§4.2).** `_plan_memory`(`:1434-1447`)의 initialization 판정:

```python
# 이전
initialization_feedback = (
    not result.feedback_accesses
    or (result.feedback_accesses[-1].after_cursor == 0
        and result.feedback_accesses[-1].next_cursor == 0)
)
initialization = (
    current.version == 0 and current.value is None
    and current.feedback_cursor == 0
    and state_access.feedback_cursor == 0       # <-- 이 조건이 문제
    and initialization_feedback
)

# 이후: "빈 window"를 0-0이 아니라 after == next 로 판정
initialization_feedback = (
    not result.feedback_accesses
    or result.feedback_accesses[-1].after_cursor
       == result.feedback_accesses[-1].next_cursor
)
initialization = (
    current.version == 0 and current.value is None
    and current.feedback_cursor == 0
    and initialization_feedback
)
```

그리고 `feedback_cursor = 0` 대신 `feedback_cursor = window_start`(= account cursor)로 두어야
이후 `MEMORY_FEEDBACK_NOT_ADVANCED`가 정상 동작한다.

**남는 제약(의도적).** memory를 쓰지만 **가끔만** commit하는 strategy는 여전히 limit에 걸린다.
이건 bounded memory 계약(§2.4 "bounded memory")으로 정당하다. 다만
`ACCOUNT_FEEDBACK_WINDOW_EXCEEDED`의 retry precondition을 현재의 generic 문구
(`"correct the selected profile input and retry from a checkpoint"`)에서
`"commit Strategy memory every decision, or raise market.feedback_entry_limit above the
observed account journal growth"`로 구체화하라(§2.6).

#### 옵션 B — window를 strategy 선언으로 게이트한다

`StrategyOperation`에 optional `consumes_account_feedback() -> bool`을 추가하고,
선언하지 않은 strategy에는 window 검사를 아예 적용하지 않는다.
장점: 의도가 명시적. 단점: public extension contract 변경(§13.3), 기존 local strategy 전부 영향.

#### 옵션 C — 아무것도 안 하고 문서화한다

기본 `feedback_entry_limit`를 크게 올리고(예: 100,000) 한계를 PRD §15.5 gap 표에 적는다.
가장 싸지만 근본 원인은 남는다. **권고하지 않는다** — 무한히 자라는 값을 상수로 막는 것뿐이다.

**테스트 (옵션 A 기준)**

- memoryless strategy로 **journal이 limit을 넘는 길이의 run**을 돌려 `COMPLETE` 확인.
  real DW 데이터로 길게 돌리기 어렵다면 `feedback_entry_limit=2` + 5세션으로 축소 재현.
- `tests/acceptance/test_execution_scenarios.py:236`
  `test_feedback_window_fails_before_strategy_when_limit_is_too_small`는
  **memory를 쓰는 strategy로 바꿔** 원래 의도(bounded window)를 계속 검증하도록 수정.
  memoryless로는 더 이상 실패하지 않는 것이 새 계약이다.
- `test_first_decision_can_initialize_memory_without_feedback`,
  `test_memory_update_after_initialization_still_requires_new_feedback`,
  `test_uc_alpha_adaptive_001_memory_commits_only_after_feedback` — 전부 회귀 확인 필수.

---

### 5.5 C5 — resume이 최신 recovery point 하나만 읽게 한다 (F-06)

**파일** `src/qlibx/flow/daily.py`, `src/qlibx/evidence/local.py`

1. `list_envelopes`에 `logical_identity_prefix: str | None = None`을 추가하고
   SQL `WHERE logical_identity LIKE ? || '%'`로 내린다(`evidence/local.py:479-493`).
   파이썬 필터보다 역직렬화 대상 자체가 줄어든다.
2. `_restore_recovery_point`(`:1747-1772`)를 다음으로 교체:

   ```python
   envelopes = self._artifacts.list_envelopes(
       artifact_type="simulation_recovery_point",
       logical_identity_prefix=prefix,
   )
   if not envelopes:
       self._fail(resume_event, "resume", "RECOVERY_POINT_NOT_FOUND", ...)
       return
   selected = max(envelopes, key=lambda item: item.logical_identity)  # zero-padded sequence
   loaded = self._artifacts.load_model(selected.artifact_id, SIMULATION_RECOVERY_POINT_CONTRACT)
   if loaded.status is not OutcomeStatus.COMPLETE:
       self._errors.extend(loaded.errors)
       return
   point = loaded.result.payload
   ```

3. **정합성 확인**: `sequence`가 `10**8`을 넘으면 zero-padding이 깨진다.
   `_publish_recovery_point`에 `if sequence >= 10**8: self._fail(...)` 가드를 넣거나
   포맷을 넓혀라. 지금은 조용히 잘못된 point를 고를 수 있다.

**semantics 변화 (record에 명시).** 이전에는 point 하나라도 load 실패 시 resume 전체가 실패했다.
이후에는 최신 point만 검증하므로 **오래된 손상 point가 resume을 막지 않는다.**
GAP-RECOVERY-001의 "손상 checkpoint의 typed failure" 오라클이 *최신* point 손상을 보는지
*임의* point 손상을 보는지 확인하고, 필요하면 테스트를 최신 point 손상으로 조정하라.

**측정.** before/after로 `load_model` 호출 횟수를 기록한다(단순 카운터 monkeypatch로 충분).

---

### 5.6 C6 — recovery point 크기를 상수로 만든다 (F-04)

**§4.1과 §4.3을 먼저 읽어라. 두 단계로 나눈다.**

#### C6-a — 계측 먼저 (수정 없음)

`experiments/recovery-performance/`에 하네스를 만든다
(`.agent/project.yaml`의 `workflow.experiment_root: experiments`).

- 세션 수 N을 늘려가며 (1) recovery point payload 바이트 수,
  (2) run 전체의 recovery 기록량, (3) `model_dump_json` 누적 시간을 잰다.
- **Θ(N²)를 실측으로 확인한 뒤에** C6-b를 한다. 이 문서의 "150 MB / 수십 GB"는
  구조 기반 산정이지 실측이 아니다.
- 직전 리뷰의 `experiments/catalog-performance/qxprof.py` 패턴을 재사용하라.

#### C6-b — journal tail + trace 분리

1. **`AccountCheckpoint`에 base cursor를 도입한다** (`account/account.py:110-121`):

   ```python
   journal_base_cursor: int = 0
   journal: tuple[JournalEntry, ...]        # base_cursor 이후의 tail만
   ```

   `from_checkpoint`의 세 불변식을 §4.1대로 갱신:
   `version == journal_base_cursor + len(journal)`,
   `applied_events`는 journal 파생이 아니라 독립 검증(tail에 없는 event id를 허용),
   `as_of == journal[-1].as_of` (journal이 비면 별도 처리).
   `Account.feedback(after, limit)`도 `after < journal_base_cursor`이면
   `FEEDBACK_WINDOW_TRUNCATED` 계열의 명시 실패를 내야 한다 — **조용히 빈 결과를 주면 §4.6 위반이다.**

2. **tail 길이 정책.** 필요한 최소는 "모든 strategy memory cursor 중 최소값 이후"다.
   `SimulationRecoveryPoint`가 `memory_snapshots`를 갖고 있으므로
   `min(cursor for snapshot in memory_snapshots)`(없으면 account cursor)를 base로 잡을 수 있다.
   여기에 `feedback_entry_limit` 만큼의 여유를 더한다.
   **C4 옵션 A와 상호작용한다 — C4를 먼저 끝내고 base 계산에 반영하라.**

3. **`event_trace` / `completed_decision_ids`를 chain으로 분리한다.**
   `SimulationRecoveryPoint`에 `previous_recovery_artifact_id: str | None`을 추가하고
   trace는 직전 point 이후의 delta만 싣는다. `_restore_recovery_point`는
   chain을 따라가며 재구성한다(resume 1회 비용은 O(N)이지만 **쓰기가 O(1)**이 된다).
   `SimulationCheckpoint.event_trace`의 완전성은 유지되어야 한다.

4. **schema를 v2로 올린다.** `simulation_recovery_point` v1 → v2.
   §4.4대로 "진행 중이던 v1 run은 재개 불가"를 record에 명시.

**테스트**

- `tests/scenarios/recovery.yaml`의 crash matrix **전부** 통과 (타협 불가).
- `tests/test_account_kernel.py`에 base cursor 불변식 테스트 추가:
  tail-only checkpoint round-trip, base 이전 cursor 요청 시 명시 실패.
- C6-a 하네스로 recovery point 크기가 **세션 수에 대해 상수에 수렴**함을 보인다.
  before/after 수치를 record에 기록.

**리스크 높음.** 이 커밋은 단독 PR로 분리하고, C1~C5가 green인 상태에서 시작하라.

---

### 5.7 C7 — observation query 핫패스 (F-08, F-09)

**파일** `src/qlibx/data/store.py`, `src/qlibx/context/scoped.py`, `src/qlibx/project.py`

#### F-09 (먼저, 사소함)

```python
# store.py:54-55
visible = cached.loc[cached["available_at"] <= cutoff]   # .copy() 제거
```

`scoped.py:238`의 `.rename(...).copy()`는 **유지하라.** caller mutation 방어이고,
pandas 버전/copy-on-write 설정에 따라 `rename`의 복사 여부가 달라진다.
제거하려면 pandas 버전을 고정하고 별도 근거가 필요하다.

#### F-08 (frozen invocation scope) — **§4.6을 읽고 시작하라**

mtime/size 완화는 **하지 마라.** 대신 PRD §7.10을 근거로 한 명시적 스코프:

```python
class ObservationStore:
    @contextmanager
    def frozen(self) -> Iterator[None]:
        """One frozen invocation verifies each physical source exactly once."""
        token = self._verified is None
        if token:
            self._verified = set()
        try:
            yield
        finally:
            if token:
                self._verified = None
```

`query`에서:

```python
if self._verified is None or cache_key not in self._verified:
    if not source.is_file() or file_hash(source) != dataset.physical_fingerprint:
        raise DataSnapshotError(...)
    if self._verified is not None:
        self._verified.add(cache_key)
```

`frozen()` 밖에서는 **현재와 완전히 동일하게** 매번 검증한다(회귀 없음).
`QlibxProject._with_catalog_session`(`project.py:360-369`)에서 store를 함께 감싸면
run/invocation 하나가 곧 frozen scope가 된다.
단 `_with_catalog_session`은 store 인스턴스를 모르므로,
`ObservationStore`를 project 레벨에서 소유하도록 배선을 정리해야 한다
(현재 `ResearchFlow` / `DailyExecutionFlow` / `ConstraintFlow`가 각자 `ObservationStore()`를 만든다
— 이 자체도 프레임 캐시를 공유하지 못하는 낭비다).

**테스트**

- `tests/test_observation_store_cache.py::test_warm_cache_hashes_every_query_but_reads_and_normalizes_once`
  는 **frozen scope 밖 동작**으로 그대로 유지한다.
- 신규: `frozen()` 안에서 N회 query → `file_hash` 호출 1회.
- 신규: `frozen()` 안에서 소스 파일이 바뀌어도 감지하지 않는 것이 **의도된 계약**임을 명시하는
  테스트와 docstring. §7.10 인용.
- 신규: `frozen()` 밖에서는 소스 변경이 즉시 `DataSnapshotError`.

---

### 5.8 C8 — contract 정리 (F-07, F-10, F-11) — **product decision 필요**

#### F-07 — axis/time requirement

- **옵션 (a) 강제한다.** `RegisteredDataset`에 axis 선언이 필요하다 → registration schema 변경,
  기존 등록 전부 영향. 큰 작업.
- **옵션 (b) 제거한다.** `ComponentRequirement`에서 `axis` / `time`을 뺀다.
  **단 이 모델은 strategy extension registration artifact에 직렬화된다
  (`extensions/strategy.py:87`) → §16.3 schema 절차 필요.**
- **옵션 (c) 좁힌다 (권고).** 지원하는 값만 남긴다:

  ```python
  class AxisRequirement(QlibxModel):
      kind: Literal["instrument"] = "instrument"      # scalar/any 제거
  class TimeRequirement(QlibxModel):
      available_at_required: Literal[True] = True     # False 제거
  ```

  계약이 거짓말을 하지 않으면서 필드는 남아 확장 여지가 있고, 기존 직렬화 값
  (`{"kind":"instrument"}`, `{"available_at_required":true}`)과 **호환된다.**
  §3 F-07에서 확인했듯 저장소 어디에서도 기본값 외의 값을 만들지 않으므로
  **마이그레이션도 schema bump도 필요 없다.** 가장 저비용이면서 §4.6을 만족시킨다.
  `scalar` / `any` 축을 실제로 지원하게 되는 날 옵션 (a)로 승격하면 된다.

#### F-10 — impact / participation 경로

- **옵션 (a) 완성한다.** `DailyExecutionProfile`에 `total_market_volume_role`을 추가하고
  `_on_execution`이 resolve해 `MarketQuote.total_market_volume`을 채운다.
  `DailySimulationSpec`의 금지를 완화. **PRD §11.2가 intraday liquidity를 future work로 두므로
  scope 확대에 해당한다 — user 승인 필요.**
- **옵션 (b) 정리한다 (권고).** 현재 scope대로 지원하지 않음을 코드에도 반영:
  `DailyExecutionProfile.volume_role`과 `_on_execution:842-887`의 volume binding 분기를 제거.
  `KrxExchange`의 impact/participation 산술은 **남긴다** —
  `tests/test_exchange_batch.py`가 쓰고 있는지 먼저 확인하고, 쓰고 있다면 characterization으로
  유지하되 daily flow에서 도달할 수 없음을 docstring에 명시.
  `tests/acceptance/test_execution_scenarios.py::test_daily_profile_rejects_impact_without_total_market_volume`
  가 현재 어떤 계약을 단정하는지 **data/DW 복원 후 반드시 읽어라.**

#### F-11 — position direction

- **옵션 (a) 계약을 만든다.** `StockInstrument` / `EtfInstrument`에
  `position_direction: Literal["long_only", "hypothetical_short"] = "long_only"` 추가,
  `CompiledInstrument`까지 전달, `match_batch` preflight에서 허용되지 않은 방향의 주문을
  `EXECUTION_DIRECTION_UNSUPPORTED`로 거부. 실제 short 실행은 **별도 product decision**.
  `docs/qlibx-architecture.md:2472`의 "unknown은 `long_only`로 처리한다"는 §4.6과 충돌하므로
  **architecture 문서를 함께 고쳐야 한다** (기본값을 명시적 선언으로).
- **옵션 (b) 정직하게 gap으로 옮긴다 (저비용).** PRD §5.7의 current scope 목록에서
  `hypothetical_short` 항목을 빼고 §15.5 readiness gap 표에 `GAP-DIRECTION-001`로 추가한다.
  closure outcome: "instrument가 direction을 선언하고, 허용되지 않은 방향의 주문이
  compute 전에 typed failure가 된다."

---

## 6. 커밋별 검증

모든 커밋 공통:

```powershell
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe -m ruff check .
```

| 커밋 | 추가 검증 |
|---|---|
| C0 | baseline이 green임을 기록. 이 문서 §1의 실패 목록이 0이 되어야 한다 |
| C1 | 신규 typed failure 3종 + `_drain` 번역 테스트 |
| C2 | flexible residual 보존, fixed incompatibility, dual-contract 로드, `UC-PORTFOLIO-001` 회귀 |
| C3 | hold-only 분석, 순서 무관 fingerprint, v2/v3 checkpoint 로드 |
| C4 | memoryless 장기 run green + memory 계열 acceptance 3건 회귀 |
| C5 | `load_model` 호출 횟수 before/after, sequence overflow 가드 |
| C6 | **crash matrix 전건**, recovery point 크기 상수 수렴 그래프, before/after 수치 |
| C7 | frozen scope 안/밖 해시 횟수, 소스 변경 감지 테스트 |
| C8 | 선택한 옵션의 계약 테스트 + PRD/architecture 문서 동기화 |

**성능 커밋(C5·C6·C7)은 수치 없이 완료 처리하지 마라.**

---

## 7. Process 의무

- implementation record: `docs/implementations/NNN-kebab-case-slug.md`, **050부터 순차**.
  번호 재사용·재부여 금지. 각 record에 why / outcome / how / trade-off / exact validation.
- 문서 전용·하네스 전용 커밋에는 record를 만들지 않는다(C0, C6-a는 record 불필요할 수 있음 —
  단 C6-a가 `experiments/`에 코드를 남기면 그건 experiment이므로 record 대상 아님).
- schema를 바꾸는 커밋(C2·C3·C6)은 record에
  **"기존 artifact가 어떻게 읽히는가" / "진행 중 run이 재개 가능한가"**를 명시.
- commit message는 짧게. 상세 근거는 record에.
- **stage / commit / push는 user가 명시적으로 승인할 때만.**
- PRD나 architecture를 고쳐야 하는 결론(F-10 옵션 b, F-11 옵션 b, F-07 옵션 c)은
  **canonical document 수정이므로 별도 승인**이 필요하다.

---

## 8. 일부러 고치지 않기로 한 것

다시 파헤치지 마라. 판단 근거를 남긴다.

| 대상 | 위치 | 판단 |
|---|---|---|
| `_cost`가 `value <= 1e-5`일 때 `minimum_cost`를 무시 | `exchange.py:325-328` | Qlib 차용 산술의 일부. UC-COST-* 오라클이 이 경계를 고정하고 있음 |
| SELL 전량 청산 시 lot rounding 생략 | `exchange.py:204-208` | 의도적(단주 청산 허용). 위험 구간은 상대오차 1e-9 미만으로 실무상 도달 불가 |
| `POSITION_DUST_UNSUPPORTED`가 batch 전체를 거부 | `account.py:392-396` | 1e-12 미만 잔량에서만 발생. 명시적 실패가 §4.6에 부합 |
| `_v2_source_lineage`의 bare `assert` | `strategy_results.py:232` | `StrategyResult` validator가 선행 보장. `-O` 실행은 이 프로젝트 대상 아님 |
| `_append_event`의 `max(event_order)` 스캔 | `evidence/local.py:666-668` | 직전 리뷰(2026-08-07)가 다룬 영역. 중복 작업 회피 |
| `adjust_single_name_caps`의 `no_short` 분기가 사실상 dead | `constraints.py:166` | `no_short: Literal[True]`이고 long-only construction이 선행하므로 도달 불가. 방어 코드로 유지 |
| `registry`의 logical key 중복 검사가 정규화 전 값 기준 | `registry.py:143` | 동일 instant의 다른 표기라는 극단 케이스. UC-DATA-001 요구는 충족 |
| `onboarding.py` 전반 | — | 이번 리뷰 범위 밖(§2.3) |

---

## 9. 부록 — 재현 스크립트

전부 `.venv/Scripts/python.exe`로 실행하며 외부 데이터가 필요 없다.
**data/DW 없이도 F-01·F-02·F-03·F-05는 재현된다.**

### 9.1 F-01

```bash
.venv/Scripts/python.exe -c "
from qlibx.portfolio.construction import *
from datetime import datetime, timezone
r = construct_portfolio(
  PortfolioConstructionRequest(invocation_id='i', source_artifact_id='a',
    evaluation_time=datetime.now(timezone.utc), config_fingerprint='c',
    profile=ConstructionProfile.EQUITY_LONG_ONLY, requested_budget=1.0),
  PortfolioConstructionInput(source_strategy_id='s', weights=(
    PortfolioWeight(instrument='A',weight=0.25),
    PortfolioWeight(instrument='B',weight=0.15))))
print('targets  :', {w.instrument: round(w.weight,6) for w in r.target_weights})
print('gross    :', r.realized_gross, 'residual:', r.cash_residual)
print('diag     :', r.diagnostics)
"
```

기대 출력 (수정 전):
```
targets  : {'A': 0.625, 'B': 0.375}
gross    : 1.0 residual: 0.0
diag     : ('negative signed alpha removed for equity long-only target', 'construction_scale=2.5')
```

### 9.2 F-02

```bash
.venv/Scripts/python.exe -c "
from qlibx.flow.daily import DecisionIntent, DecisionTarget
from qlibx.operations import StrategyDraft, WeightEntry, BudgetMode
from datetime import datetime, timezone
d = StrategyDraft(weights=(WeightEntry(instrument='A',weight=0.7),
                           WeightEntry(instrument='B',weight=0.5)),
                  budget_mode=BudgetMode.FIXED, target_gross=1.2)
print('draft OK, gross', sum(abs(w.weight) for w in d.weights))
try:
    DecisionIntent(decision_id='d', strategy_id='s', strategy_artifact_id='a',
        decision_time=datetime.now(timezone.utc), account_id='acc',
        account_version=0, feedback_cursor=0,
        targets=(DecisionTarget(instrument_id='A', weight=0.7),
                 DecisionTarget(instrument_id='B', weight=0.5)))
except Exception as e:
    print('RAISES:', type(e).__name__)
"
```

기대 출력 (수정 전): `draft OK, gross 1.2` / `RAISES: ValidationError`

### 9.3 F-03

```bash
.venv/Scripts/python.exe -c "
from qlibx.account import StrategyMemoryStore, Account, MarkBatch
from datetime import datetime, timezone, timedelta
m = StrategyMemoryStore()
print('default memory cursor:', m.snapshot('never-commits').feedback_cursor)
a = Account(account_id='acc', base_currency='KRW', initial_cash=1000.0,
            instrument_ids=frozenset({'A'}))
base = datetime(2024,1,2,6,0,tzinfo=timezone.utc)
for i in range(300):
    a.commit(MarkBatch(account_id='acc', event_id=f'e{i}',
                       as_of=base+timedelta(days=i), marks=()), expected_version=i)
snap, fb = a.snapshot(), a.feedback(0, 256)
print('journal len:', snap.feedback_cursor, 'next_cursor:', fb.next_cursor,
      '-> window check fails:', fb.next_cursor != snap.feedback_cursor)
"
```

기대 출력 (수정 전): `default memory cursor: 0` / `journal len: 300 next_cursor: 256 -> window check fails: True`

### 9.4 F-05

```bash
.venv/Scripts/python.exe -c "
from qlibx.analysis.results import (SimulationAnalysisRequest, SimulationAnalysisInput,
    ExecutionAnalysisInput, analyze_simulation, AnalysisError)
from qlibx.context import StateAccessRecord
from datetime import datetime, timezone
req = SimulationAnalysisRequest(invocation_id='i', checkpoint_artifact_id='cp',
    execution_artifact_ids=(), evaluation_time=datetime.now(timezone.utc),
    config_fingerprint='c')
state = StateAccessRecord(account_id='acc', version=3, feedback_cursor=3,
    cash=10_400_000.0, nav=10_400_000.0, valuation_status='COMPLETE', holdings=())
try:
    analyze_simulation(req, SimulationAnalysisInput(checkpoint_state=state,
        journal_event_count=3, executions=(), failure_count=0))
except AnalysisError as e:
    print('hold-only run ->', e.code)
ex = lambda nav: ExecutionAnalysisInput(account_id='acc', initial_nav=nav,
    total_cost=0.0, fill_count=1, limitations=())
g = lambda r: next(m.value for m in r.metrics if m.name=='total_return')
r1 = analyze_simulation(req, SimulationAnalysisInput(checkpoint_state=state,
    journal_event_count=3, executions=(ex(10_400_000.0), ex(10_000_000.0)), failure_count=0))
r2 = analyze_simulation(req, SimulationAnalysisInput(checkpoint_state=state,
    journal_event_count=3, executions=(ex(10_000_000.0), ex(10_400_000.0)), failure_count=0))
print('total_return depends on execution order:', round(g(r1),6), 'vs', round(g(r2),6))
"
```

기대 출력 (수정 전):
```
hold-only run -> ANALYSIS_EXECUTION_INPUT_MISSING
total_return depends on execution order: 0.0 vs 0.04
```

### 9.5 §1 환경 결함 확인

```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'tests/acceptance')
from real_dw_support import DW_DAILY
print(DW_DAILY, DW_DAILY.is_file(), 'parent exists:', DW_DAILY.parent.exists())
"
```

기대 출력 (복원 전): `...\data\DW\fng_stock_daily_prices.csv False parent exists: False`

---

## 10. PRD 조항 ↔ finding 역인덱스

| PRD 조항 | finding |
|---|---|
| §2.6 deterministic package behavior / structured failure | F-02 |
| §4.4 PIT와 data meaning | (F-08 수정 시 유지해야 할 제약) |
| §4.6 명시적 실패 > silent fallback | F-01, F-07, F-10, F-11 |
| §5.7 현재 지원 범위 | F-03, F-11 |
| §7.3 progressive requirement discovery | F-07 |
| §7.5 hierarchical operation error contract | F-02 |
| §7.7 universe와 tradability | F-07 |
| §7.10 frozen invocation | (F-08 수정의 근거) |
| §7.12 instrument semantics | F-11 |
| §9.3 fixed와 flexible budget | F-01 |
| §9.7 hold is an explicit decision | F-05 |
| §9.10 checkpoint와 resume | F-03, F-04, F-06 |
| §10.4 budget and residual evidence | F-01 |
| §11.2 execution profile defines realism | F-10 |
| §13.1 UC-REPORT-001 | F-05 |
| §16.2 deterministic replay | F-05 |
| §16.3 schema and artifact change | (C2·C3·C6의 절차 제약) |
| UC-ALPHA-BUDGET-001 | F-01 |
| UC-SCALE-001 | F-03, F-04, F-08 |
| GAP-RECOVERY-001 | F-04, F-06 |
