# 2026-08-10 10:00 Mental-model conformance review (session 1)

Reviewer: coding agent (Claude Opus 5)
Scope: user-stated mental model ↔ `docs/qlibx-prd.md` ↔ `docs/qlibx-architecture.md` ↔ `src/qlibx` (18,568 LOC)
Reviewed commit: `98bdfba` (`feat: add hypothetical academic exchange`)
Branch: `exp/2nd-attempt`
Canonical documents: `docs/qlibx-prd.md`, `docs/qlibx-architecture.md`
직전 리뷰: `docs/code-review/2026-08-09-1310-prd-conformance-review-and-fix-plan.md`

> 이 문서는 **teaching session 중 발견한 gap의 누적 기록**이다. Canonical contract가 아니다.
> 앞선 리뷰들이 "PRD 대비 코드가 맞는가"를 봤다면, 이 문서는 **"제품 소유자의 mental model 대비
> 코드/문서가 맞는가"** 를 본다. 즉 이 문서의 finding 중 일부는 **코드 결함이 아니라 PRD/문서 결함**
> 이거나, **cognitive debt**(코드는 맞지만 소유자가 예측할 수 없는 형태)다. 세 종류를 구분해 표기한다.
>
> - `CODE` — 코드가 PRD/architecture를 어긴다
> - `DOC` — 코드는 맞지만 PRD/architecture가 그 사실을 명시하지 않는다
> - `DEBT` — 코드도 문서도 맞지만 구조가 mental model에 대응하지 않아 이해 비용이 크다
>
> Fix plan은 §3에만 있고 전부 **제안**이다. 사용자 승인 전 구현하지 않는다.

## 0. Current-HEAD fact check (2026-08-10)

이 절은 중단된 첫 검토 뒤 98bdfba HEAD와 PRD를 다시 읽고 수행한 정정이며, 아래 finding의
분류나 표현과 충돌하면 **이 절이 우선한다**.

- 현재 검증은 미실행 상태가 아니다. Dataset registration, public daily flow, public
  constraints/monitoring, installed Strategy composition의 focused test **39개가 통과**했다.
- MM-01은 실제 API와 architecture의 lookback-shaped 조회 계약 사이의 DOC/DEBT다.
  PRD가 특정 window field를 강제하지 않으므로 곧바로 PRD 위반으로 승격하지 않는다.
- MM-02의 표현을 축소한다. Entry/exit 판단은 같은 decision callback에서 HOLD/TARGET으로
  구현할 수 있다. 현재 없는 것은 Strategy가 선언하는 별도 entry/exit event channel과 cadence다.
- MM-03, MM-04, MM-06은 현재 code path에서 다시 확인했다. 특히 zero-dealt Fill은
  ExecutionEvidence에는 남지만 Account journal/feedback에는 들어가지 않는다.
- MM-05는 DOC 결함이 아니다. PRD §15.3, §15.5, §17은 production real short와
  partial-fill lifecycle이 current support가 아니라고 명시한다. 이는 mental-model correction이다.
- MM-09도 DOC 결함이 아니다. PRD §11.5는 monitor_constraints()가 standalone이며
  un_daily()가 자동 실행하지 않는다고 명시한다. 역시 mental-model correction이다.
- MM-10의 정확한 범위는 architecture 서술과 current composition의 차이다. Current public
  surface는 임의 Exchange port를 주입하지 않고 un_daily(KrxExchangeConfig)와
  un_academic(AcademicRunSpec)을 별도 flow로 선택한다.
- MM-07의 directory rename은 낮은 비용이 아니다. Import, sample, tests, docs와 installed
  compatibility가 얽혀 있으므로 먼저 semantic module map과 public facade를 정리하고 별도
  refactor decision으로 다뤄야 한다.

Focused validation은 기본 uv cache의 access-denied 뒤, ignored task-scoped ASCII
UV_CACHE_DIR와 pytest basetemp를 사용해 실행했다. Cache 삭제나 product code 변경은 없었다.

---

## 1. 이번 세션이 본 것 / 보지 않은 것

읽음: `project.py`, `kernel/clock.py`, `context/scoped.py`, `operations/strategy.py`,
`operations/materialization.py`, `data/contracts.py`, `data/requirements.py`, `data/registry.py`(부분),
`execution/{exchange,sizing,instruments}.py`, `account/{account,memory}.py`, `flow/daily.py`(주 경로),
`flow/__init__.py`, `flow/{composition,materialization,monitoring,research}.py`(시그니처),
`portfolio/{construction,constraints}.py`(시그니처), `resources/samples/*`(부분).

보지 않음: `evidence/local.py`(1,157줄), `flow/strategy_extensions.py`(929줄), `onboarding.py`(700줄),
`flow/academic.py`/`execution/academic.py` 내부 산술, `analysis/*`, 테스트 스위트 실행.
따라서 아래 finding에 성능·회계 정확성 항목은 없다.

---

## 2. Findings

### MM-01 `DEBT` — Strategy가 lookback window를 선언할 수 없다

`ComponentRequirement`(`src/qlibx/data/requirements.py:28`)의 필드는
`requirement_id / semantic_role / axis / time / compatibility / dataset_id`뿐이다. **window, horizon,
min_history 같은 축이 없다.** `_DatasetView`(`src/qlibx/context/scoped.py:158`)가 제공하는 창구는
`history()`(as_of 이전 전량), `session(date)`, `at(datetime)`, `latest()` 넷이다.

결과:

1. "20일 momentum" 전략은 `history()`로 **전체 과거를 받아 자기 코드에서 잘라야** 한다.
   PIT 안전성은 깨지지 않지만(cutoff는 `as_of`가 강제) **읽기 권한이 필요 이상으로 넓다.**
   `context/scoped.py`의 설계 명제(§2.3 "역할 경계")가 시간축에는 적용되지 않는다.
2. Requirement resolution 단계에서 **데이터 충분성을 사전 검증할 수 없다.** 시작일 근처에서
   lookback이 모자라면 계산 단계에서야 드러난다. PRD §7.3 progressive requirement discovery의
   취지는 "계산 전에 실패"인데 이 축만 빠져 있다.
3. `AccessRecord`가 `row_count`와 `max_available_at`만 남기므로 **evidence에도 실제 사용한
   window가 남지 않는다.**

Architecture §7 "조회 창구 계약"은 오히려 `panel(binding, lookback)`과 bounded lookback을 설명한다. 따라서 이는 PRD가 class shape를 강제해서가 아니라 **architecture의 actual-alignment 서술과 current code가 어긋난 `DOC/DEBT`**다.

### MM-02 `DEBT` — Rebalance cadence가 Strategy 소유가 아니라 caller 소유다

`DailySimulationSpec.decision_times`(`src/qlibx/simulation.py`)를 **호출자가 tuple로 직접 넣는다.**
`StrategyOperation` Protocol(`src/qlibx/operations/strategy.py:227`)은 `strategy_id`,
`requirements()`, `run(view)` 셋뿐이고 **cadence를 선언하는 자리가 없다.**

따라서 "매월 20일 리밸런싱하는 전략"은 전략이 아니라 **run script가 결정**한다. 같은 전략을
다른 cadence로 돌려도 `strategy_id`가 같고, `DailyRunRequest.compatibility_json()`에는
schedule이 들어가므로 artifact identity는 갈라지지만 **전략 자체는 자기 cadence를 모른다.**

Current daily event 종류는 `DECISION / EXECUTION / MARK / MONITOR` 넷이다
(`flow/daily.py:506,613,617,628`). Entry/exit 조건 자체는 같은 `DECISION` callback 안에서 평가하고
`HOLD` 또는 `TARGET`을 반환해 표현할 수 있다. 현재 표현할 수 없는 것은 **서로 다른 entry/exit
event channel이나 Strategy-owned cadence registration**이다. Architecture §3 표는
`MATERIALIZE / SETTLEMENT / FUNDING / EXPIRY`를 future로 열어 두지만, Strategy가 자기 trigger를
등록하는 public contract는 두지 않는다.

이는 PRD §0.1("새로운 cadence나 lifecycle event를 추가해도 관련 없는 behavior를 다시 작성하지
않는다")의 문자적 요구는 만족한다 — Flow가 등록 지점을 소유하기 때문이다. 하지만 PRD §9.6
"Independent clocks"와 §9.8 "Trigger and finalization"이 약속하는 사용자 경험과는 거리가 있다.

### MM-03 `CODE`/`DOC` — Constraint adjustment가 closed loop에 연결되어 있지 않다

`QlibxProject.adjust_constraints()` / `validate_constraints()`(`src/qlibx/project.py:242,255`)는
독립 오퍼레이션이다. **`DailyExecutionFlow._on_decision`은 이 둘 중 무엇도 호출하지 않는다**
(`flow/daily.py:728-931` 전체에 `Constraint` 참조 없음). `_on_decision`은 Strategy weight를 받아
바로 `DecisionIntent`를 만들고 `_on_execution`이 `size_session_orders`로 주문화한다.

Architecture §3 `DECISION` 행은 "selected Strategy; **optional construct/adjust/convert/validate**"라고
적어 놓았다. 실제로는 daily runtime에서 이 optional 단계를 **끼울 수 있는 자리가 없다** —
`DailyExecutionFlow`는 constraint policy를 인자로 받지 않는다.

즉 사용자가 constraint를 적용한 백테스트를 돌리려면 (a) 전략 코드 안에서 직접 clip 하거나
(b) `run_daily` 밖에서 수동으로 adjust → 그 결과를 다시 artifact로 물려 별도 실행해야 한다.
`resources/samples/constraint_workflow/run.py`가 실제로 (b)를 한다.

PRD §10.3, §11.3과 architecture §3의 서술이 이 한계를 드러내지 않으므로 **문서가 과장**이다.

### MM-04 `DEBT` — Public facade가 비대칭이다

`QlibxProject`에 있는 것: `register_dataset`, `invoke`, `materialize`,
`invoke_registered_strategy`, `adjust_constraints`, `validate_constraints`, `monitor_constraints`,
`run_academic`, `run_daily`, `run_daily_registered_strategy`, `execute_frozen_daily`,
`validate_extension`, `onboard`, `load_artifact`, `materialize_sample`.

`QlibxProject`에 **없는** 것: ensemble 실행, portfolio construction, analysis/report.
이들은 `from qlibx.flow import CompositionFlow, PortfolioConstructionFlow, AnalysisFlow`로
**flow layer를 직접 import**해야 하고, `LocalArtifactBackend`·`RegistrySnapshot`·`ObservationStore`를
사용자가 손으로 조립해야 한다(`resources/samples/basic/run.py:89,110,122` 참조).

`qlibx/__init__.py`의 `__all__`에도 이 셋이 없다. PRD §1.2는 "정상적 사용을 위해 agent가
package source나 private module을 열어야 하면 public product surface의 결함"이라고 규정한다.
`qlibx.flow`가 private은 아니지만, **다른 오퍼레이션은 전부 facade로 감싸 놓고 이 셋만
layer를 노출**하는 것은 일관성 결함이다. 그리고 PRD §2.1의 흐름도에서 ensemble과 portfolio
construction은 **중심 use case**다.

### MM-05 `MENTAL-MODEL CORRECTION` — Daily closed loop은 long-only 전용이다

`flow/daily.py:845`가 음수 weight를 보면 `SIGNED_TARGET_REQUIRES_CONSTRUCTION`으로 실패시키고,
`flow/daily.py:850`이 gross > 1을 `DAILY_TARGET_BUDGET_UNSUPPORTED`로 실패시킨다.
`SizingTarget.weight`도 `Field(ge=0)`(`execution/sizing.py:21`)이다.

즉 **signed long-short 백테스트는 `run_academic()` 경로에서만 가능**하고, 그 경로는
zero-friction·fractional·hypothetical이다. "비용 있는 long-short 백테스트"는 현재 지원되지 않는다.

이는 PRD의 research intent와 executable real short 분리, §15.3 acceptance와 §17 out-of-scope에
정합한다. 따라서 제품 결함은 아니다. 다만 상위 흐름도만 읽으면 signed weight가 daily KRX path로
직접 들어간다고 오해하기 쉬우므로 teaching에서는 `run_academic()`과 `run_daily()`를 처음부터
서로 다른 current profile로 설명해야 한다.

### MM-06 `CODE` — 전량 미체결이 strategy feedback에 도달하지 않는다

`flow/daily.py:1050`:

```python
committed_fills = tuple(fill for fill in match.result.fills if fill.dealt_quantity > 1e-12)
```

`dealt_quantity == 0`인 Fill은 `FillBatch`에서 제외된다. `JournalEntry`
(`account/account.py:63`)에 담기는 것은 `fills`/`marks`/`realized_pnl`뿐이고
**`FillDiagnostic`은 journal에 들어가지 않는다.** `StrategyView.account_feedback()`가 반환하는
것은 journal entry들이므로, 다음 decision의 Strategy는 **"주문을 냈는데 한 주도 못 샀다"는
사실을 볼 수 없다.**

부분 체결은 보인다 — `Fill.requested_quantity`와 `dealt_quantity`가 둘 다 journal에 남는다
(`domain.py:24-25`). 사각지대는 **dealt == 0** 케이스 하나다. 이 정보는 `ExecutionEvidence`
artifact에는 남지만(`flow/daily.py:1122`), Strategy가 그것을 읽으려면 `artifact_bindings`로
직접 물려야 하고 그건 **직전 세션의 execution artifact ID를 미리 알아야** 가능하다.

PRD §4.6("Untradable target을 reason 없이 skip" 금지)은 evidence 차원에서는 지켜진다.
그러나 PRD §2.4("Blocked order와 transaction cost가 다음 decision에 영향을 줄 수 있다")는
**현재 코드에서 blocked order에 대해 성립하지 않는다.**

### MM-07 `DEBT` — 디렉토리/파일 이름이 layer semantics를 반영하지 않는다

Architecture §2.4는 여섯 layer를 `kernel / flow / view / operation / state / evidence`로 정의한다.
실제 디렉토리는 다음과 같다.

| architecture layer | 실제 위치 | 문제 |
|---|---|---|
| ① kernel | `kernel/clock.py` (83줄, 단일 파일) | 패키지일 이유가 없다 |
| ② flow | `flow/` (14 모듈, 5,200줄) | `flow/daily.py` 하나가 2,468줄 |
| ③ **view** | **`context/`** | **2026-08-03 개정에서 context 모델을 폐기하고 view 모델을 채택했는데 디렉토리 이름만 옛 모델로 남았다** |
| ④ operation | `operations/` + `portfolio/` + `execution/` + `analysis/` | 한 layer가 네 패키지에 흩어짐 |
| ⑤ state | `account/` | 이름이 layer가 아니라 aggregate |
| ⑥ evidence | `evidence/` | 일치 |

같은 이름이 세 layer에 반복된다.

```
constraints:  constraints.py (spec DTO) | portfolio/constraints.py (pure) | flow/constraints.py (flow)
academic:     academic.py (DTO)         | execution/academic.py (exchange) | flow/academic.py (flow)
materialization: operations/materialization.py | flow/materialization.py
```

읽는 사람이 `import` 줄만 보고 어느 층인지 알 수 없다. 그리고 top-level에
`academic.py / constraints.py / domain.py / models.py / simulation.py / sample.py / onboarding.py /
cli.py / errors.py / project.py`가 평평하게 섞여 있다 — 이 중 `academic.py`, `constraints.py`,
`simulation.py`는 **spec/DTO**이고 `project.py`는 **composition root**이며 `onboarding.py`는
**flow**다. 세 종류가 같은 깊이에 있다.

추가로:

- `execution/`에 Executor가 없다. `NextSessionCloseExecutor`/`NextSessionOpenExecutor`는
  `flow/daily.py:356,370`에 있다. Architecture §12는 `execution/`에 "instruments, **executor**,
  exchange, cost, quantity, validation"이라고 적었다 → `DOC` 불일치.
- `production/`은 docstring 한 줄짜리 빈 패키지다.
- `context/scoped.py` 536줄 안에 view 4종 + access record 8종 + Protocol 7종이 함께 있다.

### MM-08 `DEBT` — `flow/daily.py` 2,468줄 (기인정 부채)

Architecture의 alignment 표(`docs/qlibx-architecture.md:38`)가 이미 기술부채로 인정하고
"둘 이상의 phase가 독립 테스트·재사용 경계를 가질 때 state machine을 추출한다"를 전환 조건으로
걸어 두었다. 이 파일 하나에 event handler 4종 + recovery/resume 프로토콜 + memory 2-phase commit +
evidence hydration이 함께 있다. Recovery 관련 메서드만 8개(`_publish_recovery_point`,
`_restore_recovery_point`, `_pending_recovery`, `_recovery_publication`,
`_memory_recovery_publication`, ...)로 약 600줄이다. **재사용 경계는 이미 생겼다** —
`AcademicExecutionFlow`도 checkpoint/resume을 별도로 구현한다(`flow/academic.py`).

### MM-09 `MENTAL-MODEL CORRECTION` — `MONITOR` event와 `monitor_constraints()`는 다른 것이다

`DailyExecutionFlow._on_monitor`(`flow/daily.py:1380`)는 session performance와 account observation
evidence만 만들고 **constraint를 평가하지 않는다.** Constraint monitoring은
`QlibxProject.monitor_constraints(spec)`이며 **호출자가 명시적으로 불러야** 하고, 입력으로
`checkpoint_artifact_id`와 `evaluation_time`을 받는다 — 즉 **run이 끝난 뒤 사후 평가**다.

Architecture §3 각주와 PRD §11.5가 이 사실을 정확히 적어 두었으므로 코드-문서 불일치는
아니다. 다만 "감시자가 loop 밖에서 계좌를 계속 지켜본다"는 통상적 mental model과 달리,
current support는 caller가 committed checkpoint와 frozen evaluation time을 지정해 호출하는
**standalone post-check operation**이며 자동·실시간 scheduler가 아니다.

### MM-10 `DOC`/`DEBT` — Current public flow에는 임의 Exchange 주입 port가 없다

Architecture §12는 "Executor, Exchange와 valuation policy에는 **Strategy Pattern**을 적용한다"고
적었다(`docs/qlibx-architecture.md:1925`). 실제 코드에는 **Exchange Protocol/ABC가 없다.**

```
flow/daily.py:441        exchange: KrxExchange          # concrete class annotation
project.py:393,439       exchange = KrxExchange(spec.exchange)   # hardcoded
simulation.py:45,82,106,171   exchange: KrxExchangeConfig         # concrete config type
```

`AcademicExchange`(`execution/academic.py:279`)는 `KrxExchange`와 **공통 base도 공통 method
signature도 없다.** `KrxExchange.match_batch(event_id, event_time, orders, quotes, cash, holdings)`
와 academic 경로는 별도 flow(`AcademicExecutionFlow`)로 완전히 분기한다.

즉 "사용자가 KrxExchange / AcademicExchange 중 무엇을 쓸지 고른다"는 것은 **exchange 객체를
고르는 것이 아니라 `run_daily()` / `run_academic()` 중 어느 public method를 부르는지**다.
제3의 venue(예: 미국주식, 암호화폐)를 추가하려면 새 Exchange class가 아니라 **새 Flow와 새
facade method**가 필요하다.

교체 가능한 축은 `KrxExchangeConfig.rules`(effective-dated `CostRule` 목록)와
`DailyExecutionProfile.execution_timing`(`next_session_close` / `next_session_open`) 둘뿐이다.
후자는 `NextSessionCloseExecutor` / `NextSessionOpenExecutor` 선택으로 이어지는데
(`project.py:481`, `flow/daily.py:590-603`) — 이 둘은 `plan(decision) -> datetime | None` 이라는
**같은 구조적 shape를 갖지만 명시적 Protocol이 선언돼 있지 않다**(structural typing에 의존).

Architecture alignment 표(`docs/qlibx-architecture.md:36`)는 `FillConvention` class 추출을
"현재는 이르다"고 판단했다. 그 판단 자체는 타당하다(YAGNI). 문제는 §12가 이미 적용된 것처럼
**Strategy Pattern을 서술**한다는 점이다.

---

## 3. 제안 (승인 전 구현 금지)

> **SUPERSEDED (2026-08-10 14:30).** 이 표는
> `docs/code-review/2026-08-10-1430-ideal-remediation-analysis.md`로 대체되었다.
> 특히 **P3(MM-06)은 폐기**한다 — `FillBatch`/`JournalEntry` 스키마 변경은 I4/I9를 흐리고
> checkpoint 호환성을 깬다. 대체 설계는 후속 문서 §3.6(`StrategyView.latest_execution_result()`)에 있다.
> 아래 표는 이력 보존용으로만 남긴다.

우선순위는 **사용자가 제기한 문제(cognitive debt) 해소** 기준이다. 성능이나 기능 추가가 아니다.

| # | 대상 | 제안 | 비용 | 위험 |
|---|---|---|---|---|
| P1 | MM-07 | 먼저 semantic module map과 facade 경계를 문서화한다. Package rename/restructure는 public imports, samples, tests, docs와 installed compatibility를 함께 다루는 별도 refactor decision으로 둔다 | 낮음 / 높음 | 문서화는 낮음. 실제 rename은 넓은 회귀·migration 위험 |
| P2 | MM-04 | `QlibxProject.run_ensemble()`, `.construct_portfolio()`, `.analyze()` 추가. 기존 flow를 그대로 감싼다 | 낮음 | 없음 |
| P3 | MM-06 | `FillBatch`에 zero-dealt diagnostic을 함께 commit하거나, `JournalEntry`에 `blocked: tuple[FillDiagnostic, ...]` 추가 | 중간 | Account 스키마 변경 → checkpoint 호환성 |
| P4 | MM-03 | (product decision) `DailyExecutionProfile`에 optional constraint policy를 받아 `_on_decision`에서 adjust→validate를 끼우거나, **문서를 현실에 맞게 축소**한다 | 높음 / 낮음 | 전자는 evidence lineage 확장 필요 |
| P5 | MM-01 | `ComponentRequirement`에 optional `window`(sessions or timedelta) 추가, `_DatasetView._read`에서 하한 필터 + `AccessRecord`에 기록 | 중간 | 기존 전략 전부 호환(optional) |
| P6 | MM-08 | `flow/daily.py`에서 recovery 프로토콜(~600줄)을 `flow/recovery.py`로 이관 — 이미 `AcademicExecutionFlow`가 두 번째 소비자다 | 중간 | 회귀 위험, 테스트 커버리지 확인 필요 |
| P7 | MM-02 / MM-10 | Strategy-owned cadence/event channel의 현재 부재와 architecture §12의 "Strategy Pattern 적용" 서술을 current composition(structural timing selection + separate daily/academic flows)에 맞게 정정. MM-05/MM-09는 PRD가 이미 명시하므로 추가 정정 불필요 | 낮음 | 없음 |

**P4는 product decision이다.** PRD §2.6대로 구현 agent가 단독 확정하지 않는다.

---

## 4. 다음 세션에서 볼 것

- `evidence/local.py` — catalog/artifact 발행 경로, append-only 보장, session locking
- `flow/strategy_extensions.py` — project-local Strategy 등록·검증(UC-EXTENSION-002)
- `flow/academic.py` + `execution/academic.py` — signed fractional 산술과 checkpoint
- `onboarding.py` — agent skill 배포 lifecycle
- 테스트 스위트 실제 실행 (직전 리뷰가 환경 결함으로 red였다)
