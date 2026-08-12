# 2026-08-10 20:30 Mental-model conformance review (session 2)

Reviewer: coding agent (Claude Opus 5)
Scope: 사용자 mental model ↔ `docs/qlibx-prd.md` ↔ `src/qlibx` (20,478 LOC) ↔ `showcases/`
Reviewed commit: `2f57d31` (`Ignore tmp files`)
Branch: `exp/2nd-attempt`
직전 리뷰: `docs/code-review/2026-08-10-1000-mental-model-conformance-review.md`,
`docs/code-review/2026-08-10-1730-execution-spine-conformance-review.md`

> 이 문서도 teaching session 중 발견한 gap의 누적 기록이며 canonical contract가 아니다.
> 분류는 session 1과 같다: `CODE`(코드가 PRD 위반), `DOC`(코드는 맞고 문서가 침묵),
> `DEBT`(둘 다 맞지만 mental model에 대응이 없어 이해 비용이 큼).
> §2의 제안은 전부 **제안**이며 사용자 승인 전 구현하지 않는다.

## 0. Session 1 finding의 현재 상태 (HEAD 재확인)

| ID | session 1 내용 | 현재 상태 | 근거 |
|---|---|---|---|
| MM-01 | Strategy가 lookback을 선언 못 함 | **해결** | `ComponentRequirement.lookback`(`data/requirements.py:35`) → `ResolvedBinding.lookback` → `ObservationStore.query` → `AccessRecord.lookback` |
| MM-02 | Rebalance cadence가 caller 소유 | **미해결(의도적)** | `DailySimulationSpec.decision_times`가 cadence 소유. PRD §9.8이 명시적으로 이 설계를 확정함 |
| MM-03 | Constraint adjustment가 closed loop 미연결 | **해결** | `flow/daily.py:1096-1146`이 `KrxConstraintInput`을 `KrxExecutionPreparation.prepare()`에 전달 |
| MM-04 | Public facade 비대칭 | **해결** | `run_ensemble`, `invoke_stored_signal_strategy`, `construct_portfolio`, `analyze_*`, `render_report`가 `QlibxProject`에 존재 |
| MM-05 | daily loop은 long-only 전용 | **mental-model correction 유지** | `flow/daily.py:910` `SIGNED_TARGET_REQUIRES_CONSTRUCTION` |
| MM-06 | 전량 미체결이 strategy에 도달 안 함 | **해결** | `StrategyView.latest_execution_result()`(`view/views.py:273`)가 직전 decision 이후 execution evidence를 노출 |
| MM-07 | 디렉토리가 layer semantics 미반영 | **부분 해결** | `specs/`, `view/` 분리 완료. `operations/`는 여전히 Strategy·Materialization·artifact contract 혼재 |
| MM-08 | `flow/daily.py` 비대 | **부분 해결** | 2,468 → 2,314줄. recovery 조율은 `flow/recovery.py`로 추출됨 |
| MM-09 | `MONITOR` event ≠ `monitor_constraints()` | **mental-model correction 유지** | PRD §11.5 |
| MM-10 | 임의 Exchange 주입 port 없음 | **해결** | `run_daily(..., exchange=)`, `run_academic(..., exchange=)` |

## 1. 이번 세션의 신규 finding

### N-01 `DEBT` — 대표 showcase가 public facade를 우회해 artifact를 직접 publish한다

`showcases/show_003_academic_exchange_factor_execution/run.py:224-271`의 `publish_portfolio()`는
`PortfolioConstructionResult` payload를 손으로 만든 뒤
`project.artifacts.publish_model(...)`을 직접 호출한다. 즉 catalog backend를 직접 쓴다.

문제는 이 showcase가 **사용자 mental model의 alpha research loop 전체**(stored signal →
signed weights → AcademicExchange → factor return)를 보여주는 유일한 end-to-end 증거라는 점이다.
현재 지원되는 두 경로 중 어느 것도 사용하지 않는다.

1. `invoke_stored_signal_strategy()` → `strategy_result:v3` → `construct_portfolio()`
2. stored signal을 `StrategyArtifactRequirement`로 구독하는 project-local Strategy (PRD §13.3의 기본 경로)

우회 이유는 추정 가능하다. `StoredSignalWeighting`(`flow/composition.py:36`)에는
`long_short_extremes`와 `long_only_max` 두 개의 built-in만 있고 user-supplied weighting rule을
받지 않는다. Showcase가 원한 cross-sectional demeaned unit-gross weighting은 여기 없다.
`construct_portfolio()`도 `load_strategy_result()`만 받으므로(`flow/portfolio.py:53`)
stored signal artifact를 직접 소비할 수 없다.

영향:

- PRD §1.2("정상 사용에 package private surface를 열어야 하면 public surface의 결함")의
  경계선에 있다. `artifacts`는 public property지만 payload schema를 손으로 조립하는 것은
  producer-independent artifact 계약을 사용자가 대신 지키는 것이다.
- 이 경로에는 facade-level regression test가 없다. Showcase가 통과해도
  "signal → weights"의 지원 경로가 동작한다는 증거가 되지 않는다.

제안(승인 필요): showcase를 local Strategy extension 경로로 다시 쓰거나,
weighting을 사용자 코드가 제공할 수 있게 하는 최소 표면을 정한다. 새 registry는 만들지 않는다.

### N-02 `DOC`/`DEBT` — 점진적 execution 환경 누적이 KRX daily 전용이다

`QlibxProject.add_instrument()`/`set_exchange()`(`project.py:138-206`)는 PRD §7.10.1의
인터뷰형 누적 요구를 구현한다. 그러나

- `set_exchange`의 타입이 `KrxExchangeConfig`로 고정되어 있다.
- 누적분을 소비하는 것은 `daily_spec()` 하나뿐이다.
- Academic run은 여전히 `AcademicRunSpec(listings=..., profile=..., session_closes=...)`을
  한 번에 채워야 하며 `add_instrument`로 쌓은 instrument를 재사용하지 않는다.

PRD §7.10.1은 "instrument와 exchange 같은 execution environment"라고만 쓰고 profile을
한정하지 않는다. 따라서 현재 구현은 PRD 위반은 아니지만, "instrument와 exchange를 하나씩
확인한다"는 onboarding 대화가 academic venue에서는 성립하지 않는다.

영향: 사용자가 "AcademicExchange로 long-short 평가"를 요청하면 agent는 다시 한 번에 채우는
spec 생성자로 돌아가야 한다. 두 venue의 onboarding 대화 형태가 달라진다.

제안(승인 필요): (a) PRD/문서에 누적 표면이 daily physical profile 전용임을 명시하거나,
(b) `academic_spec()` 대칭 표면을 추가한다. 둘 중 하나를 product decision으로 확정한다.
현 시점 권고는 (a)다. Academic listing은 instrument identity가 아니라 가격 semantics 선언이므로
같은 누적 버킷에 넣으면 의미가 섞인다.

### N-03 `DEBT` — `latest()`와 `RowsLookback`이 요청 window가 아니라 전체 visible history를 랭킹한다

[data/store.py:155-175](../../src/qlibx/data/store.py)의 `RowsLookback`과 `latest` 경로는
`row_number() OVER (PARTITION BY instrument ORDER BY available_at DESC ...)`를 사용한다.
Window function은 PIT gate를 통과한 **모든 행**에 순위를 매긴 뒤 `__rank <= N`으로 자른다.
따라서 쿼리 비용이 요청한 N이 아니라 **누적 history 길이**에 비례한다.

실측(3,000 instrument × 1,500 session = 4.5M행, 27.9MB Parquet, warm, frozen scope 안):

| query | 반환 행 | median |
|---|---|---|
| `session()` 1일 | 3,000 | **16.3 ms** |
| `latest()` | 3,000 | **498.7 ms** |
| `RowsLookback(rows=20)` | 60,000 | **653.7 ms** |

`session()` 대비 30~40배다. `latest()`는 instrument당 1행만 필요한데도 그렇다.

영향: constraint를 켠 daily run은 execution event마다 benchmark weight를 `latest()`로 읽는다
([flow/daily.py:1085](../../src/qlibx/flow/daily.py)). 1,500 거래일이면 이 한 줄만 **약 12분**을
추가한다. History가 길어질수록 선형으로 나빠진다.

제안(승인 필요): correlated subquery 또는 `available_at` 하한 예비필터로 랭킹 대상을 먼저 줄인다.
`latest`는 window function 없이 `max(available_at)` group-by join으로 표현할 수 있다.
계약(반환 semantics)은 바뀌지 않으므로 순수 최적화다.

### N-04 `DEBT` — 쿼리마다 DuckDB connection을 새로 만들고 닫는다

[data/store.py:183-187](../../src/qlibx/data/store.py)은 `query()` 호출마다
`duckdb.connect(":memory:")` → `execute` → `close()`를 수행한다. 실측 connect+close만
**9.2 ms**이며, 이는 가장 흔한 `session()` 쿼리(16.3 ms)의 **약 56%**다.

`ObservationStore`는 이미 `frozen()` scope로 invocation 수명을 갖고 있으므로 그 안에서
connection을 재사용해도 격리 semantics가 바뀌지 않는다.

### N-05 `DEBT` — Query snapshot을 정렬 없이 기록해 row-group pruning이 source 순서에 의존한다

[data/snapshot.py:98](../../src/qlibx/data/snapshot.py)은 normalized frame을 `to_parquet`으로
그대로 쓴다. 정렬하지 않으므로 `available_at`의 row-group min/max 통계가 source의 물리적 순서를
그대로 물려받는다. `available_at <= cutoff` predicate pushdown의 효율이 **등록한 파일이 어떤
순서로 덤프됐는지**에 좌우된다.

실측(같은 4.5M행, 물리적 순서만 다름):

| snapshot 물리 순서 | 크기 | `session()` median |
|---|---|---|
| 시간순 `(date, instrument)` | 27.9 MB | **37.7 ms** |
| 종목순 `(instrument, date)` | 29.4 MB | **60.2 ms** |

1.6배 차이다. 종목별 블록 덤프는 vendor CSV에서 매우 흔한 형태이므로 우연에 맡길 값이 아니다.

제안(승인 필요): snapshot 기록 시 `available_at`(또는 registered logical key) 순으로 정렬한다.
Snapshot은 content-addressed이므로 정렬은 fingerprint를 바꾸며 기존 registration은 explicit
`reindex_datasets()` 경로를 이미 갖고 있다.

### 성능 관련 확인된 사실 (finding 아님, 기록용)

- 현재 구조는 naive pandas 경로보다 훨씬 빠르다. `tests/performance/lookback_gate.py`
  (2M행, 50 instrument, rows=60) 실측: pandas baseline median **51.52 s** vs
  qlibx bounded median **0.289 s** → **178배**. Gate 기준(50% 이하) 대비 0.56%.
- 원본 CSV를 매 쿼리마다 다시 읽지 않는다. Registration이 normalized Parquet snapshot을
  만들고 쿼리는 그것만 친다. 실측 129 MB CSV → 1.5 MB Parquet.
- `frozen()` scope가 SHA-256 검증을 invocation당 1회로 memoize한다. 실측 129MB source
  hash 93.2 ms가 매 쿼리 → 1회로 줄어든다. Scope 밖 cold 쿼리는 281.9 ms, 안에서는 156.2 ms.

### 문서 drift

`docs/implementations/049-observation-frame-cache.md`는 `ObservationStore`가
`(registration_identity, source path, fingerprint, field)` 키의 in-memory normalized frame
cache를 갖는다고 기술한다. **현재 source에는 그 cache가 없다.** GAP-LOOKBACK-001의
normalized Parquet snapshot으로 대체되면서 제거됐고 049는 갱신되지 않았다.
`2026-08-10-1730` 리뷰의 C5(implementation note 지연)와 같은 종류다.

## 2. 이번 세션이 보지 않은 것

`evidence/local.py`(1,157줄), `flow/strategy_extensions.py`(929줄), `onboarding.py`(700줄),
`flow/academic.py`/`execution/academic.py` 내부 산술, `analysis/*` 계산, 테스트 실행.
따라서 이 문서에 회계 정확성·성능 finding은 없다.
