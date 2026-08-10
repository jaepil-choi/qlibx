# Handoff — observation-store performance and facade follow-ups

Author: coding agent (Claude Opus 5), teaching session 2
Date: 2026-08-10
Branch: `exp/2nd-attempt`
Base commit: `a4c833e` (`docs(code-review): record session 2 mental-model conformance findings`)
For: a different agent on a different machine

---

## 0. 이 문서를 읽는 방법

이 문서는 **작업 지시서가 아니라 인계장**이다. 아래 항목은 전부 **제안**이며
**사용자 승인 전에는 production source를 바꾸지 않는다.** 시작하기 전에 §1을 읽고,
착수할 항목을 사용자에게 확인받은 뒤 진행한다.

읽는 순서:

1. `AGENTS.md` (repository 운영 규칙)
2. `.agent/project.yaml` (canonical 문서 경로와 명령)
3. `docs/qlibx-prd.md` (product authority)
4. `docs/module-map.md`, `docs/current-support-map.md` (현재 코드 지도)
5. `docs/code-review/2026-08-10-2030-mental-model-session2-verification.md` (**이 handoff의 근거**)
6. 필요하면 `docs/code-review/2026-08-10-1730-execution-spine-conformance-review.md`

---

## 1. 배경 — 이 목록이 나온 맥락

사용자(제품 소유자)는 코드를 직접 작성하지 않았고, **현재 codebase가 자신의 mental model과
일치하는지 확인하는 teaching session**을 진행 중이다. 세션의 산출물은 두 가지다.

- 사용자의 이해 (대화)
- mental model과 코드가 어긋나는 지점의 기록 (`docs/code-review/`)

따라서 이 handoff의 항목들은 "버그 수정 티켓"이 아니라 **teaching 중 드러난 구조적 관찰**이다.
각 항목은 사용자가 "이건 고치자"고 판단해야 작업이 된다.

세션 2에서 확정된 사실:

- 세션 1 finding(MM-01~MM-10) 10개 중 5개는 해결됐고, 2개는 mental-model correction이며,
  2개는 부분 해결, 1개(cadence 소유권)는 PRD §9.8이 의도적으로 확정한 설계다.
- 신규 finding 5개(N-01~N-05)와 문서 drift 1건이 나왔다. 아래가 그 목록이다.

---

## 2. 해야 할 일

우선순위는 **N-03 > N-04 > N-05 > 문서 drift > N-01 > N-02** 순으로 제안한다.
앞의 셋은 계약을 바꾸지 않는 순수 최적화이고, 뒤의 둘은 product decision이 필요하다.

---

### N-03 — `latest()` / `RowsLookback`이 전체 visible history를 랭킹한다

**종류:** 성능 (계약 변경 없음) · **승인 상태:** 대기 · **권장 우선순위:** 1

**문제**

`src/qlibx/data/store.py`의 `RowsLookback`과 `latest` 경로가
`row_number() OVER (PARTITION BY instrument ORDER BY available_at DESC ...)`를 사용한다.
Window function이 PIT gate를 통과한 **모든 행**에 순위를 매긴 뒤 `__rank <= N`으로 자르므로,
비용이 요청한 N이 아니라 **누적 history 길이**에 비례한다.

**측정된 baseline** (3,000 instrument × 1,500 session = 4.5M행, 27.9MB Parquet, warm,
`frozen()` scope 안, median):

| query | 반환 행 | median |
|---|---|---|
| `session()` 1일 | 3,000 | 16 ~ 38 ms |
| `latest()` | 3,000 | **499 ms** |
| `RowsLookback(rows=20)` | 60,000 | **654 ms** |

**영향**

Constraint를 켠 daily run은 execution event마다 benchmark weight를 `latest()`로 읽는다
(`src/qlibx/flow/daily.py`의 `_on_execution` 안 `view.latest(policy.benchmark_weight_role)`).
1,500 거래일이면 이 한 줄이 약 12분을 추가하고, history가 길어질수록 선형으로 악화된다.

**제안 방향**

- `latest`는 window function 없이 `max(available_at)` group-by join 또는 correlated subquery로
  표현할 수 있다.
- `RowsLookback`은 랭킹 전에 `available_at` 하한 예비필터로 대상을 줄이는 방법을 검토한다.
  단, 하한을 잘못 잡으면 instrument별 ragged panel에서 행이 누락되므로 **정확성 검증이 필수**다.

**완료 판정**

- `tests/test_exact_lookback.py`가 그대로 통과한다 (반환 semantics 불변).
- `AccessRecord`의 `row_count`, `instruments_below_window`, `snapshot_fingerprint`가 이전과 동일.
- 위 3개 쿼리의 median을 개선 전후로 기록한다 (§3 재현 절차 사용).
- ragged panel(일부 instrument의 행 수가 N 미만)에서 결과가 동일함을 확인한다.

---

### N-04 — 쿼리마다 DuckDB connection을 새로 만들고 닫는다

**종류:** 성능 (계약 변경 없음) · **승인 상태:** 대기 · **권장 우선순위:** 2

**문제**

`src/qlibx/data/store.py`의 `query()`가 호출마다
`duckdb.connect(":memory:")` → `execute` → `close()`를 수행한다.

**측정:** connect+close만 **9.2 ms**. 가장 흔한 `session()` 쿼리(16.3 ms)의 약 **56%**다.

**제안 방향**

`ObservationStore`는 이미 `frozen()` context로 invocation 수명을 갖는다
(`QlibxProject._with_catalog_session`이 모든 public 호출을 감싼다). 그 scope 안에서
connection을 재사용해도 격리 semantics는 바뀌지 않는다.

**주의**

- `frozen()`은 재진입 가능하다(`_frozen_depth`). connection 수명을 outermost scope에 맞춘다.
- Scope 밖 단독 쿼리 경로도 여전히 동작해야 한다.
- 스레드 안전성을 새로 주장하지 않는다. 현재도 그런 계약은 없다.

**완료 판정**

- `tests/test_observation_store_cache.py`, `tests/test_exact_lookback.py`,
  `tests/test_data_registration.py`, `tests/test_session_timezone.py` 통과.
- `session()` median 개선을 수치로 기록한다.

---

### N-05 — Query snapshot을 정렬 없이 기록해 row-group pruning이 source 순서에 의존한다

**종류:** 성능 (fingerprint 변경 있음) · **승인 상태:** 대기 · **권장 우선순위:** 3

**문제**

`src/qlibx/data/snapshot.py`의 `build_query_snapshot()`이 normalized frame을 `to_parquet`으로
그대로 쓴다. 정렬하지 않으므로 `available_at`의 row-group min/max 통계가 원본 파일의 물리적
덤프 순서를 그대로 물려받고, `available_at <= cutoff` predicate pushdown 효율이 **우연에
좌우된다.**

**측정** (같은 4.5M행, 물리 순서만 다름):

| snapshot 물리 순서 | 크기 | `session()` median |
|---|---|---|
| 시간순 `(date, instrument)` | 27.9 MB | **37.7 ms** |
| 종목순 `(instrument, date)` | 29.4 MB | **60.2 ms** |

종목별 블록 덤프는 vendor CSV에서 매우 흔하다.

**제안 방향**

Snapshot 기록 시 `available_at`(또는 registered logical key) 순으로 정렬한다.

**주의 — 이 항목만 side effect가 있다**

Snapshot은 content-addressed다. 정렬하면 **fingerprint가 바뀐다.** 즉:

- 기존 registration은 `DATASET_QUERY_SNAPSHOT_DRIFT` 또는 재색인 필요 상태가 된다.
- 이미 `reindex_datasets()` 경로가 있으므로 그것을 사용한다. 새 migration 도구를 만들지 않는다.
- `registration_schema_version` 승격이 필요한지 판단하고 사용자에게 확인받는다.

**완료 판정**

- `tests/test_data_registration.py`, `tests/test_exact_lookback.py` 통과.
- 정렬 전후 `session()` median 기록.
- 기존 registration의 전환 경로가 명시적 실패 → `reindex_datasets()` → 성공으로 닫히는지 확인.

---

### 문서 drift — `docs/implementations/049-observation-frame-cache.md`

**종류:** 문서만 · **승인 상태:** 대기 (저위험) · **권장 우선순위:** 4

049는 `ObservationStore`가 `(registration_identity, source path, fingerprint, field)` 키의
in-memory normalized frame cache를 갖는다고 기술한다. **현재 source에는 그 cache가 없다.**
GAP-LOOKBACK-001의 normalized Parquet snapshot으로 대체되면서 제거됐고 049는 갱신되지 않았다.

현재 `ObservationStore`가 실제로 갖는 것은 `_frozen_verified`, 즉 **fingerprint 검증
memoization**뿐이다 (frame cache가 아니다).

`docs/code-review/2026-08-10-1730-execution-spine-conformance-review.md`의 C5와 같은 종류이므로,
다른 implementation record에도 같은 drift가 있는지 함께 확인할 것을 권한다.

**주의:** implementation record는 과거 사실의 기록이다. 지우거나 다시 쓰지 말고,
**superseded 표시와 대체 record 참조를 추가**하는 방식을 사용자와 합의한 뒤 적용한다.

---

### N-01 — 대표 showcase가 public facade를 우회해 artifact를 직접 publish한다

**종류:** 구조/증거 · **승인 상태:** 대기 (product decision 포함) · **권장 우선순위:** 5

**문제**

`showcases/show_003_academic_exchange_factor_execution/run.py`의 `publish_portfolio()`가
`PortfolioConstructionResult` payload를 손으로 조립한 뒤 `project.artifacts.publish_model(...)`을
직접 호출한다.

이 showcase는 **사용자 mental model의 alpha research loop 전체**(stored signal → signed weights
→ AcademicExchange → factor return)를 보여주는 유일한 end-to-end 증거인데, 지원되는 두 경로 중
어느 것도 사용하지 않는다.

1. `invoke_stored_signal_strategy()` → `strategy_result:v3` → `construct_portfolio()`
2. stored signal을 `StrategyArtifactRequirement`로 구독하는 project-local Strategy (PRD §13.3)

**우회 원인 (추정, 검증 필요)**

- `StoredSignalWeighting`(`src/qlibx/flow/composition.py`)에 built-in weighting이
  `long_short_extremes`, `long_only_max` 둘뿐이고 user-supplied rule을 받지 않는다.
  Showcase가 필요로 한 cross-sectional demeaned unit-gross weighting이 없다.
- `construct_portfolio()`는 `load_strategy_result()`만 받으므로(`src/qlibx/flow/portfolio.py`)
  stored signal artifact를 직접 소비할 수 없다.

**결정이 필요한 것 (사용자에게 질문할 것)**

- showcase를 local Strategy extension 경로로 다시 쓸 것인가, 아니면
- stored signal → weights에 user-supplied weighting을 허용하는 최소 표면을 추가할 것인가.

**하지 말 것:** 범용 weighting registry나 plugin 시스템을 만들지 않는다.
`docs/code-review/2026-08-10-0947-remediation-boundary-addendum.md`가 그 방향을 명시적으로 배제했다.

---

### N-02 — 점진적 execution 환경 누적이 KRX daily 전용이다

**종류:** 문서 또는 API 대칭성 · **승인 상태:** 대기 (product decision) · **권장 우선순위:** 6

**문제**

`QlibxProject.add_instrument()` / `set_exchange()`는 PRD §7.10.1의 인터뷰형 누적 요구를
구현하지만,

- `set_exchange`의 타입이 `KrxExchangeConfig`로 고정이고,
- 누적분을 소비하는 것은 `daily_spec()` 하나뿐이며,
- Academic run은 여전히 `AcademicRunSpec(listings=..., profile=..., session_closes=...)`을
  한 번에 채워야 한다.

PRD 위반은 아니다(§7.10.1이 profile을 한정하지 않음). 다만 두 venue의 onboarding 대화 형태가
달라진다.

**결정이 필요한 것 (사용자에게 질문할 것)**

(a) 누적 표면이 daily physical profile 전용임을 PRD/문서에 명시한다, 또는
(b) `academic_spec()` 대칭 표면을 추가한다.

**직전 세션의 권고는 (a)다.** Academic listing은 instrument identity가 아니라 가격 semantics
선언이므로 같은 누적 버킷에 넣으면 의미가 섞인다. 이 판단을 사용자에게 확인받는다.

---

## 3. 측정 재현 절차

`tests/performance/lookback_gate.py`가 저장소에 이미 있다. 2M행 / 50 instrument /
`RowsLookback(rows=60)` 기준으로 pandas baseline과 비교한다.

```bash
python tests/performance/lookback_gate.py setup <work_dir>
python tests/performance/lookback_gate.py compare <work_dir>
```

`a4c833e` 시점 측정값 (Windows, 로컬 SSD):

```
baseline_median = 51.521094 s     (pandas: hash + read_csv + filter + sort + groupby.tail)
bounded_median  =  0.288837 s     (qlibx: normalized Parquet + DuckDB)
ratio           =  0.005606       (gate 기준: 0.5 이하)
```

**KRX 형태 벤치마크는 저장소에 없다.** N-03/N-05를 작업한다면 아래 형태로 재생성한다.
저장소에 추가하려면 `tests/performance/`에 두고, 게이트로 승격할지는 사용자에게 확인한다.

```python
# 3,000 instrument x 1,500 session = 4.5M rows
# DuckDB로 Parquet을 직접 생성한 뒤 RegisteredDataset을 손으로 구성해
# ObservationStore.query()를 frozen() scope 안에서 반복 측정한다.
#
#   COPY (
#     SELECT 'A'||lpad(CAST(i AS VARCHAR),6,'0') AS instrument,
#            TIMESTAMPTZ '2018-01-01 06:30:00+00' + d*INTERVAL 1 day AS available_at,
#            TIMESTAMPTZ '2018-01-01 00:00:00+00' + d*INTERVAL 1 day AS observation_time,
#            50000.0 + (i*7+d*13)%50000 AS value,
#            TIMESTAMPTZ '2018-01-01 06:30:00+00' + d*INTERVAL 1 day AS __key_000,
#            'A'||lpad(CAST(i AS VARCHAR),6,'0') AS __key_001
#     FROM range(1500) days(d) CROSS JOIN range(3000) inst(i)
#     ORDER BY d, i                       -- N-05는 ORDER BY i, d 와 비교한다
#   ) TO 'krx.parquet' (FORMAT PARQUET)
#
# 측정 대상 3개:
#   store.query(ds, field="value", as_of=T, session_date=T.date(), session_timezone="UTC")
#   store.query(ds, field="value", as_of=T, latest=True)
#   store.query(ds, field="value", as_of=T, lookback=RowsLookback(rows=20))
```

측정 시 반드시 `with store.frozen():` 안에서 수행하고, 첫 호출은 warm-up으로 버린다.
그렇지 않으면 SHA-256 검증 비용(129MB 기준 93 ms)이 섞인다.

---

## 4. 환경 메모

- 이 저장소의 홈 경로에 비-ASCII 문자가 있다. 이전 세션에서 기본 uv cache가
  access-denied를 낸 기록이 있다. 그때는 ignored task-scoped ASCII `UV_CACHE_DIR`와
  pytest `--basetemp`를 사용해 해결했다. **cache를 삭제하지 않는다.**
- 이번 세션은 `.venv/Scripts/python.exe`를 직접 호출해 문제없이 실행했다. 그 경로를 먼저 시도한다.
- 실행/검증 명령의 정본은 `.agent/project.yaml`이다.

---

## 5. 하지 말 것

- 사용자 승인 없이 production source 변경, commit, push.
- 범용 scheduler / journal / plugin registry / stage registry 도입.
  `2026-08-10-0947-remediation-boundary-addendum.md`가 명시적으로 배제했다.
- `flow/daily.py`를 파일 크기만을 이유로 분할. `docs/module-map.md`가 그 판단 근거를 적어두었다.
- implementation record를 삭제하거나 소급 재작성.
- Strategy가 cadence를 소유하도록 바꾸는 시도. PRD §9.8이 현재 설계를 확정했다.
  변경하려면 PRD 개정이 선행되어야 한다.

---

## 6. 진행 중인 teaching thread

이 handoff와 별개로, 사용자와의 teaching session이 진행 중이다. 다음 세션에서 이어질 후보:

1. **ExecutionPreparation + constraint 내부** (사용자에게 이미 권한 다음 주제)
   — construct → adjust → validate → size 고정 순서, benchmark PIT 요구.
   N-03의 `latest()` 500 ms가 정확히 이 경로에서 쓰인다.
2. `ViewGate`가 read capability를 잘라내는 코드 실체
3. crash & resume (`flow/recovery.py`)의 recovery point 복원 범위
4. alpha research 경로 (`materialize()` → stored signal → weights → `run_academic()`)

이미 다룬 것: PRD 전체 지도, 사용자 mental model 검증, `run_daily()` 12-event 전체 trace
(`src/qlibx/resources/samples/daily_closed_loop/` 실측), IoC 개념, observation store 성능.

teaching 중 새 gap을 발견하면 `docs/code-review/`에 날짜-시각 파일로 누적한다.
분류 기호는 `CODE`(코드가 PRD 위반) / `DOC`(코드는 맞고 문서가 침묵) /
`DEBT`(둘 다 맞지만 mental model에 대응이 없어 이해 비용이 큼)를 사용한다.
