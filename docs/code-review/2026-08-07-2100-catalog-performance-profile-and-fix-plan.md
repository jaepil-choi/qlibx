# 2026-08-07 21:00 Catalog performance profile and fix plan

Reviewer: coding agent (Claude Opus 5)
Scope: 실행 성능 프로파일링 (`src/qlibx` 전체, 병목은 `src/qlibx/evidence/local.py`에 집중)
Profiled tree: `22e1e7a` + working tree (220 tests). 문서 작성 시점 HEAD: `3428101` (224 tests)
Branch: `exp/2nd-attempt`
Platform: Windows 11, DuckDB **1.5.5**, CPython 3.12.13, `.venv`
직전 리뷰: `docs/code-review/2026-08-07-1800-strategy-extension-review-and-fix-plan.md`

> 이 문서는 성능 측정 기록이며 canonical contract가 아니다. PRD와 Architecture가 정본이다.
> §3의 finding은 전부 **실측**이다. 추정치에는 명시적으로 "추정"이라고 적었다.
> §5의 수정 계획은 **제안**이며 사용자 승인 전에는 확정이 아니다.
> **§4를 읽기 전에 §5를 구현하지 마라.** §4는 순진한 최적화가 왜 정확성을 깨는지를 실측으로 보여준다.

---

## 0. 후속 agent를 위한 사용법

1. §1로 계측 도구를 복원하고 **자기 머신에서 baseline을 다시 잰다.** 이 문서의 절대 초(sec)는
   측정 머신에 종속적이다. 비율과 호출 횟수가 이식 가능한 값이다.
2. §2에서 시간이 어디로 가는지 확인한다.
3. §3의 finding P-01 ~ P-06을 읽는다.
4. **§4의 설계 제약을 읽는다.** DuckDB 커넥션 공존 규칙과, 이미 존재하는 다중 프로세스·크래시
   복구 테스트가 어떤 해법을 금지하는지 나온다.
5. §5의 커밋 순서대로 수정한다. C0(계측 하네스) → C1 → C2 → C3 → C4 → C5.
6. §6의 검증을 커밋마다 통과시킨다. 성능 커밋은 **before/after 수치를 implementation record에
   기록**해야 한다. "빨라졌다"는 서술만으로는 부족하다.
7. §7의 process 의무를 지킨다. 다음 implementation record 번호는 **045**다.

```powershell
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe -m ruff check .
```

---

## 1. 계측 방법과 재현 절차

측정에 쓴 도구는 세 종류다. 전부 §9 부록에 전문이 있다. **C0에서 이 파일들을
`experiments/catalog-performance/`에 넣어 재현 가능하게 만들 것**(`.agent/project.yaml`의
`workflow.experiment_root: experiments`).

| 도구 | 파일 | 목적 |
|---|---|---|
| pytest 플러그인 | `qxprof.py` | `duckdb.connect` / `execute` / `close` / `os.fsync`를 SQL 문 단위로 집계 |
| pytest 플러그인 | `qxprof2.py` | `ObservationStore.query` 내부(파일 해싱·parquet 읽기·타임스탬프 정규화) 집계 |
| 스케일링 벤치 | `bench_publish.py` | 카탈로그 크기에 따른 publish 1건당 비용 변화 측정 |
| 공존 규칙 probe | `probe_conn.py` | DuckDB 커넥션 동시 개방 가능 여부 (§4) |
| 콜드 커넥션 probe | `probe_cold.py` | 커넥션 open/validate/close 원가 분해 |
| SQL 마이크로벤치 | `probe_sql.py` | 복구 스캔·`event_order` 채번 대안 비교 |

실행 예:

```bash
PYTHONPATH=experiments/catalog-performance .venv/Scripts/python.exe -m pytest tests -q -s -p qxprof
```

```bash
.venv/Scripts/python.exe experiments/catalog-performance/bench_publish.py 800
```

`cProfile`도 보조로 썼지만 **오버헤드가 2배 가까이 붙어**(116s 실행 → 276s 프로파일) 절대값을
신뢰하면 안 된다. 순위 확인용으로만 쓰고, 수치는 위 플러그인 쪽을 인용할 것.

---

## 2. Baseline

**프로파일링 시점 트리** (측정의 근거): `220 passed in 155~163s`, 3회 실행 편차 ±5%.
아래 §2.1~§2.3의 모든 수치는 이 트리에서 나왔다.

**문서 작성 시점 HEAD `3428101` + working tree**: `224 passed in 178.56s`.
테스트가 4개 늘고 `load_envelope` (local.py:262)가 추가되면서 reader 커넥션 경로가 하나 더
생겼다. 병목의 성격은 동일하며 오히려 커졌다. **C0 직후 이 트리에서 §2를 다시 재서
implementation record에 기록할 것.**

`ruff check .` → `Found 1 error` — 단, `.agent/tmp/pytest-.../daily_strategy.py`의 `I001`로
**pytest scratch 파일**이다. 제품 소스가 아니다. 직전 리뷰가 지적한
"`.agent/tmp/`가 `.gitignore`에 없다"의 후속 증상이며, 이 계획의 범위 밖이다.
성능 커밋의 red/green 판정에서 이 한 건은 제외하고 볼 것.

### 2.1 전체 시간의 62%가 DuckDB에서 소비된다

`qxprof` 계측, 스위트 전체 wall 162.7s 기준:

| 구간 | 호출 수 | 총 시간 | 회당 | 비중 |
|---|---|---|---|---|
| `connection.close()` | 1,773 | 34.3s | 19.4ms | 21.1% |
| `connection.execute()` | 22,963 | 29.2s | 1.27ms | 17.9% |
| `duckdb.connect()` (read-write) | 965 | 20.3s | 21.0ms | 12.5% |
| `duckdb.connect()` (read_only) | 833 | 20.2s | 20.2ms | 10.3% |
| `os.fsync()` | 927 | 2.2s | 2.4ms | 1.3% |
| **합계** | | **~100s** | | **~62%** |

커넥션 **개폐만으로 71.4초 = 전체의 44%**다. 커넥션은 총 1,798개 열렸다.

### 2.2 execute 상위 SQL

| SQL | 호출 수 | 총 시간 | 회당 | 출처 |
|---|---|---|---|---|
| `INSERT INTO publication_events VALUES (...)` | 3,350 | 10.4s | 3.10ms | `_append_event` (local.py:520) |
| `SELECT table_name FROM information_schema.tables ...` | 1,772 | 5.5s | 3.12ms | `_table_names` (local.py:768) |
| `COMMIT` | 927 | 3.5s | 3.78ms | `_commit_publication` (local.py:576) |
| `SELECT coalesce(max(event_order), 0) + 1 ...` | 3,350 | 2.2s | 0.65ms | `_append_event` (local.py:520) |
| `SELECT event_json FROM publication_events ORDER BY event_order` | 941 | 0.87s | 0.93ms | `_read_events` (local.py:686) |
| `PRAGMA table_info('artifacts' / 'artifact_edges' / 'publication_events')` | 1,677×3 | 1.8s | ~0.4ms | `_validate_columns` (local.py:777) |
| `SELECT schema_version FROM catalog_metadata` | 1,678 | 0.6s | 0.37ms | `_require_schema_version` (local.py:791) |

### 2.3 카탈로그가 커질수록 publish가 느려진다

`bench_publish.py 800` — 빈 카탈로그에 800건을 순차 publish, 100건 구간 평균:

| 누적 publish | publish 1건당 |
|---|---|
| 100 | 66.2 ms |
| 200 | 95.4 ms |
| 400 | 125.5 ms |
| 600 | 123.8 ms |
| 800 | **194.8 ms** |

선형이 아니다. 총 78초. 원인은 P-03.

### 2.4 병목이 **아닌** 것 (재확인 불필요)

| 후보 | 실측 | 판정 |
|---|---|---|
| import 시간 | 누적 0.52s (pandas 0.27s, pydantic 0.03s). 프로세스 전체 1.1s | 병목 아님 |
| pandas / 데이터 계층 | `ObservationStore.query` 206회 / 1.61s = **0.9%** | 스위트에서는 병목 아님 (단 P-06 참조) |
| cvxpy / 최적화 | 상위 30개 프로파일 항목에 등장하지 않음 | 병목 아님 |
| subprocess sample 테스트 | 6회 / 10.1s (대부분 인터프리터 기동 + pandas import) | 6% — 구조적 비용, 손대지 말 것 |

---

## 3. Findings

### 3.1 P-01 — 연산 1건마다 DuckDB 커넥션을 새로 열고 닫는다 (CONFIRMED, 최대 원인)

`LocalArtifactBackend`의 모든 public 연산이 커넥션을 새로 만들고 끝나면 닫는다.

| 호출부 | 위치 | 종류 |
|---|---|---|
| `publish_model` | local.py:136 | writer |
| `load_model` | local.py:311 | reader |
| `load_envelope` | local.py:273 | reader |
| `list_envelopes` | local.py:380 | reader |
| `audit_publications` | local.py:394 | reader |
| `recover_publications` | local.py:419 | writer |

`_connect_writer` (local.py:709), `_connect_reader` (local.py:718)가 매번 `duckdb.connect()`를
호출한다.

**`close()`가 가장 비싼 이유**는 DuckDB가 close 시점에 WAL을 데이터베이스 파일로 체크포인트하기
때문이다. 카탈로그가 비어 있을 때 19ms, `bench_publish` 처럼 실데이터가 쌓이면 **회당 50.9ms**까지
올라간다(같은 계측, 800 publish 실행에서 close 600회 / 30.6s / 41.0%).

**영향:** 스위트 71.4s(44%). 실사용에서는 publish 1건당 약 70ms의 고정비.

### 3.2 P-02 — 커넥션마다 스키마 전체를 재검증한다 (CONFIRMED, 단 비중은 작다)

`_ensure_writer_schema` (local.py:727) / `_validate_reader_schema` (local.py:753)가 커넥션마다
5개 쿼리를 돈다: `information_schema.tables` 1회 + `PRAGMA table_info` 3회 + `schema_version` 1회.

**중요 — 여기서 크게 벌 수 없다.** `probe_cold.py`로 콜드 커넥션 원가를 분해한 결과:

| 시나리오 | 회당 |
|---|---|
| `connect` + `close`만 | **20.11 ms** |
| 현행: `information_schema` + PRAGMA 3 + version | 23.21 ms |
| `duckdb_tables()` + PRAGMA 3 + version | 27.23 ms |
| `duckdb_tables()`만 | 24.35 ms |

즉 연산당 카탈로그 오버헤드 23ms 중 **20ms가 커넥션 개폐 자체**이고 검증 쿼리는 3ms(13%)다.
그리고 `duckdb_tables()`로 바꾸면 콜드 커넥션에서 **오히려 느리다**(§8의 dead end 참조).

**결론: P-02는 단독으로 고칠 가치가 없다. P-01을 고치면 자동으로 사라진다**(커넥션당 1회 →
스코프당 1회). 검증 쿼리 자체를 튜닝하는 데 시간을 쓰지 말 것.

### 3.3 P-03 — publish마다 이벤트 로그 전체를 재파싱한다 — O(N²) (CONFIRMED)

`publish_model` (local.py:106)
→ `_recover_locked` (local.py:617)
→ `_read_events` (local.py:686)

`_read_events`는 `SELECT event_json FROM publication_events ORDER BY event_order`로
**지금까지 기록된 모든 이벤트 행**을 읽고 전부 `PublicationEvent.model_validate_json()`으로
역직렬화한다. publish 1건은 이벤트를 4행 추가하고 로그는 절대 잘리지 않는다.

`_recover_locked`가 실제로 필요로 하는 것은 **미종결 attempt의 최신 이벤트**뿐이다
(local.py:626-631에서 `CATALOG_COMMITTED` / `RECOVERED_ABANDONED`를 걸러 버린다).
즉 역직렬화한 행의 대부분을 즉시 버린다. 정상 상태에서는 **전부** 버린다.

**실측 (cProfile, `bench_publish` 800건):**

```
ncalls      tottime  filename:lineno(function)
1278400      6.064   {method 'validate_json' of pydantic_core.SchemaValidator}
  799/0      2.424   src/qlibx/evidence/local.py:_read_events
1278400      1.629   pydantic/main.py:742(model_validate_json)
```

publish 800건에 **`model_validate_json` 128만 회**. 누적 8.5초. §2.3의 초선형 증가가 이것이다.

**SQL 수준 실측 (`probe_sql.py`, 20,000행 이벤트 로그):**

| 쿼리 | 시간 | 반환 행 |
|---|---|---|
| `SELECT event_json FROM pe ORDER BY event_order` (현행) | 14.74 ms | 20,000 |
| 미종결 attempt만 필터 | **2.61 ms** | **0** |

SQL만 4.6배 빠르고, 파이썬 쪽 역직렬화 비용은 20,000행 → 0행으로 사라진다.

`_append_event` (local.py:520)의 `SELECT coalesce(max(event_order), 0) + 1`도 publish당 4회
도는 전체 집계지만, DuckDB zone map 덕에 20,000행에서 0.374ms로 싸다. **여기는 건드릴 필요 없다**
(§8 참조).

### 3.4 P-04 — publish당 이벤트 INSERT 4건이 각각 자동 커밋된다 (CONFIRMED, 그러나 설계 의도)

`_append_event`가 트랜잭션 밖에서 실행되므로 DuckDB가 INSERT마다 커밋 + WAL 기록을 한다.
스위트에서 3,350회 / **10.4초(6.4%)**, 회당 3.10ms.

**이건 버그가 아니라 write-ahead journal이다.** `publish_model` (local.py:165-171)의 순서를 보라:

```
STAGED           → _write_staged_payload   (파일 생성 + fsync)
PAYLOAD_STAGED   → _promote_staged_payload (os.replace)
PAYLOAD_PROMOTED → _commit_publication     (여기서만 BEGIN/COMMIT)
CATALOG_COMMITTED
```

각 이벤트는 **다음 파일시스템 작업 이전에 내구적으로 기록되어야** 크래시 복구가 성립한다.
`tests/test_catalog_recovery.py:91-107`의 `_CrashAfterStageBackend` /
`_CrashAfterPromoteBackend` / `_CrashAfterCommitBackend`가 `os._exit()`로 정확히 그 지점에서
프로세스를 죽이고, `_recover_locked`가 남은 흔적을 정리하는지 검증한다.

**따라서 "4개를 한 트랜잭션으로 묶는다"는 금지다.** 정확성을 깨고 위 테스트를 실패시킨다.
줄일 수 있는 여지는 "단계 수를 4에서 줄일 수 있는가"라는 **설계 질문**이며, 그건 복구 계약
변경이므로 별도 승인이 필요하다. 이번 계획에서는 **손대지 않는다**(§5의 범위 밖).

### 3.5 P-05 — `QlibxProject.artifacts`가 접근할 때마다 백엔드를 새로 만든다 (CONFIRMED)

```python
# src/qlibx/project.py:112-117
@property
def artifacts(self) -> LocalArtifactBackend:
    return LocalArtifactBackend(
        self._root / self._config.catalog_path,
        self._root / self._config.artifact_dir,
    )
```

`extension_flow`(:85), `strategy_extension_flow`(:100), `load_artifact`(:126), `invoke`(:161),
`invoke_registered_strategy`(:175), `adjust_constraints`(:185), `validate_constraints`(:193),
`monitor_constraints`(:212), `_run_daily`(:279) — 전부 이 property를 읽는다.

그 자체로는 싸지만(객체 생성뿐), **인스턴스 단위 커넥션 캐시를 무효화한다.** P-01을 고칠 때
캐시를 `self`에 두면 아무 효과가 없다. C1의 선행 조건이다.

### 3.6 P-06 — `ObservationStore.query`에 캐시가 전혀 없다 (CONFIRMED, 잠재 위험)

`src/qlibx/data/store.py:21` `query()`는 호출마다:

1. `file_hash(source)` (store.py:37 → registry.py:26) — 소스 파일 **전체**를 SHA-256으로 재해싱
2. `pd.read_parquet` / `pd.read_csv` (store.py:56, :62) — 파일 **전체**를 다시 읽음
3. `normalize_timestamps` — 타임스탬프 컬럼 전체 정규화
4. 그 다음에야 `as_of` / `session_date` / `observation_at`으로 **필터링**

즉 "한 시점의 한 종목 값"을 얻는 데 매번 전체 파일을 읽는다. 호출부는
`src/qlibx/context/scoped.py:212` 하나이고, 그 위로 `history()` / `at()` / `latest()` /
`window()` 가 얹혀 있다.

**스위트에서는 병목이 아니다** — 픽스처가 작아 206회 / 1.61초(0.9%). 하지만 실제 백테스트에서는
`거래일 수 × semantic role 수`만큼 전체 파일 읽기 + 전체 해싱이 반복된다. 데이터가 커지면
P-01을 제치고 1순위가 된다.

**우선순위는 낮게 두되(C5), 사용자가 "실행이 느리다"고 한 대상이 테스트가 아니라 실제
백테스트라면 C5를 C1보다 먼저 해야 한다.** 착수 전 확인할 것.

---

## 4. 설계 제약 — 구현 전 반드시 읽을 것

P-01의 순진한 해법("커넥션을 프로세스 수명 동안 캐시한다")은 **정확성을 깬다.** 실측으로 확인했다.

### 4.1 DuckDB 1.5.5 커넥션 공존 규칙 (`probe_conn.py` 실측)

| # | 상황 | 결과 |
|---|---|---|
| 1 | 같은 프로세스에서 read-write 커넥션 2개 | **OK** (DuckDB가 인스턴스를 공유) |
| 2 | read-write가 열린 상태에서 같은 프로세스가 `read_only=True` | **실패** — `ConnectionException: Can't open a connection to same database file with a different configuration than existing connections` |
| 3 | `writer.cursor()` | **OK** |
| 4 | read-write가 열린 상태에서 **다른 프로세스**가 `read_only=True` | **실패** |
| 5 | read-write가 열린 상태에서 **다른 프로세스**가 read-write | **실패** |
| 6 | 닫은 뒤 다른 프로세스가 read-write | **OK** |

**#2의 함의:** writer 커넥션을 열어둔 채로는 `_connect_reader`의 `read_only=True`가 **실패한다**.
writer를 캐시하려면 reader도 같은 설정(read-write)을 쓰거나 `cursor()`로 파생시켜야 한다.
`read_only=True`는 "reader는 스키마를 생성하지 않는다"는 방어선이므로, 없앨 경우 그 보장을
`_validate_reader_schema`가 계속 책임진다는 점을 record에 남길 것.

**#4·#5의 함의:** read-write 커넥션을 프로세스 수명 동안 열어두면 **다른 프로세스가 카탈로그를
아예 열지 못한다.**

### 4.2 다중 프로세스 접근은 테스트된 계약이다

`src/qlibx/evidence/local.py:448`의 `_writer_lock`이 `msvcrt.locking` / `fcntl.flock`으로
**프로세스 간** 잠금을 잡는 이유가 있다:

- `tests/test_catalog_recovery.py:129` `test_same_candidate_concurrent_writers_are_idempotent`
- `tests/test_catalog_recovery.py:140` `test_different_candidate_concurrent_writers_conflict`

둘 다 `multiprocessing` spawn으로 **두 프로세스가 동시에 publish**한다. `_hold_lock`(:122)은
한 프로세스가 락을 쥔 동안의 동작을 검증한다. `tests/conftest.py`의 `run_python_subprocess`를
쓰는 sample 테스트들도 자식 프로세스에서 같은 카탈로그를 연다.

**따라서 커넥션 캐시는 반드시 명시적으로 경계가 있는 스코프여야 한다.** 스코프 밖에서는 현행
동작(연산당 개폐)을 유지해야 위 테스트가 통과한다. 스코프가 열려 있는 동안 다른 프로세스가
차단된다는 사실은 **문서화되고 승인되어야 하는 의미 변경**이다.

### 4.3 크래시 복구 계약

§3.4 참조. 이벤트 append는 파일시스템 작업보다 먼저 내구화되어야 한다. 트랜잭션으로 묶지 말 것.

---

## 5. 수정 계획 (제안)

| # | Record | Subject | Findings | 선행 | 기대 효과 |
|---|---|---|---|---|---|
| C0 | — | `test: add catalog performance harness` | — | — | 재현 가능성 |
| C1 | 045 | `perf: bound abandoned publication recovery scans` | P-03 | C0 | 초선형 → 선형 |
| C2 | 046 | `refactor: reuse one project artifact backend` | P-05 | C0 | C3의 선행 |
| C3 | 047 | `perf: reuse one catalog connection per scope` | P-01, P-02 | C1, C2 | 최대 |
| C4 | — | `docs: record catalog session semantics` | — | C3 | 계약 문서화 |
| C5 | 048 | `perf: cache registered observation frames` | P-06 | — | 실사용 백테스트 |

**순서 근거.** C1이 먼저인 이유는 **독립적이고 위험이 낮으며 C3의 이득을 측정 가능하게** 만들기
때문이다(C3를 먼저 하면 O(N²)가 남아 개선폭이 희석된다). C2는 순수 리팩터이자 C3의 선행 조건이다.
C3가 가장 크고 가장 위험하므로 마지막에, 안정된 baseline 위에서 한다. C5는 나머지와 독립이며
§3.6의 확인 결과에 따라 순서를 앞당길 수 있다.

### C0 — `test: add catalog performance harness`

§9 부록의 5개 스크립트를 `experiments/catalog-performance/`에 만든다. README에 실행 명령과
"절대 초는 머신 종속, 호출 횟수와 비율이 이식 가능한 값"이라는 주의를 적는다.

record 불필요(실험 전용, `AGENTS.md`).

`.gitignore`는 `experiments/outputs/`와 `experiments/exp_*/outputs/`만 무시한다 —
`experiments/catalog-performance/`는 **커밋 대상이다.** 의도된 것이며, 이후 성능 회귀를
같은 도구로 재현할 수 있어야 한다.

### C1 — `perf: bound abandoned publication recovery scans` (P-03)

**목표:** `_recover_locked`가 전체 이벤트 로그가 아니라 **미종결 attempt의 이벤트만** 읽게 한다.

**수정 파일:** `src/qlibx/evidence/local.py`

1. `_read_events` (local.py:686)는 **현행 유지**한다. `audit_publications` (local.py:390)이
   전체 로그를 필요로 하는 정당한 소비자다.
2. `_recover_locked` (local.py:617)가 쓸 **새 private 메서드**를 추가한다:

```python
_TERMINAL_PHASES = (
    PublicationPhase.CATALOG_COMMITTED.value,
    PublicationPhase.RECOVERED_ABANDONED.value,
)

@staticmethod
def _read_unterminated_events(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[PublicationEvent, ...]:
    rows = connection.execute(
        "SELECT event_json FROM publication_events "
        "WHERE attempt_id NOT IN ("
        "  SELECT attempt_id FROM publication_events WHERE phase IN (?, ?)"
        ") ORDER BY event_order",
        list(_TERMINAL_PHASES),
    ).fetchall()
    ...  # 역직렬화와 CatalogSchemaError 변환은 _read_events와 동일
```

3. `_recover_locked`의 `for event in self._read_events(connection)` (local.py:623)를
   `_read_unterminated_events`로 바꾼다. 그 아래 `if event.phase in terminal: continue`
   (local.py:630-631)는 **남겨 둔다** — SQL 필터와 이중 방어이며 비용이 없다.

**주의 1 — phase 값의 진실은 enum이다.** SQL에 문자열 리터럴을 하드코딩하지 말고
`PublicationPhase.CATALOG_COMMITTED.value`에서 가져와 파라미터로 넘겨라. 위 스케치대로 할 것.
실제 값은 `src/qlibx/evidence/contracts.py:21-26`에서 **밑줄** 표기다:
`staged` / `payload_staged` / `payload_promoted` / `catalog_committed` / `recovered_abandoned`.
하이픈으로 잘못 적으면 필터가 아무것도 걸러내지 못하고 **조용히 현행 동작으로 되돌아간다** —
성능이 안 변하면 여기를 먼저 의심하라.

**주의 2 — 역직렬화 실패 처리를 잃지 마라.** `_read_events`의 `except Exception → CatalogSchemaError`
(local.py:696-699)는 스키마 감지 경로다. 새 메서드도 같은 변환을 해야 하고, 공통 헬퍼로 뽑는 편이
낫다.

**주의 3 — 의미가 바뀌지 않는지 확인하라.** 현행은 `latest[event.attempt_id] = event`로 attempt별
최신 이벤트를 남긴다(local.py:622-623). 종결된 attempt를 SQL에서 제외해도 이 사전의 내용은
동일해야 한다. 종결 이벤트가 있는 attempt는 어차피 `continue`로 건너뛰기 때문이다.

**중복 헬퍼 주의:** `_read_events`와 새 메서드가 역직렬화 로직을 복제하지 않도록
`_deserialize_events(rows)` 하나로 모을 것.

### C2 — `refactor: reuse one project artifact backend` (P-05)

**수정 파일:** `src/qlibx/project.py`

`artifacts` property(:112-117)를 메모이즈한다. `_root`와 `_config`는 `__init__` 이후 불변이므로
안전하다.

```python
def __init__(self, root: Path, config: ProjectConfig) -> None:
    self._root = root.resolve()
    self._config = config
    self._artifacts: LocalArtifactBackend | None = None

@property
def artifacts(self) -> LocalArtifactBackend:
    if self._artifacts is None:
        self._artifacts = LocalArtifactBackend(
            self._root / self._config.catalog_path,
            self._root / self._config.artifact_dir,
        )
    return self._artifacts
```

**확인할 것:** `LocalArtifactBackend`가 상태를 갖지 않는지(`__init__` local.py:92-104는 경로 4개만
저장 — 안전). `QlibxProject.init`/`open` (project.py:345, :359)이 인스턴스를 재사용하는지.
`tests/test_catalog_recovery.py`가 `LocalArtifactBackend`를 **상속**해 크래시를 주입하므로
(`_CrashAfterStageBackend` 등) 프로젝트 밖에서 직접 생성하는 경로는 그대로 살아 있어야 한다.

이 커밋만으로는 성능이 거의 안 변한다. **C3의 선행 조건**이라는 점을 record에 명시할 것.

### C3 — `perf: reuse one catalog connection per scope` (P-01, P-02)

가장 큰 이득이자 가장 큰 위험. §4를 다시 읽고 시작할 것.

**목표:** 하나의 논리적 작업 단위(daily run 전체, extension 검증 전체) 안에서 카탈로그 커넥션을
1개만 열고, 스코프가 끝나면 닫는다. 스코프 밖에서는 현행 동작을 유지한다.

**측정된 상한:** writer 커넥션 재사용 프로토타입으로 `bench_publish 800`이
**78초 → 30.3초 (2.6배)**, 800번째 publish 기준 **194.8ms → 49.6ms (3.9배)**였다.
(프로토타입은 writer만 다뤘고 reader 경로는 §4.1 #2 때문에 그대로는 동작하지 않는다.)

**설계 — `LocalArtifactBackend`에 명시적 세션 스코프를 추가한다:**

```python
@contextmanager
def session(self) -> Iterator[None]:
    """Hold one catalog connection open for the duration of a unit of work.

    While a session is open this process holds the DuckDB file exclusively;
    other processes cannot open the catalog. Outside a session every
    operation opens and closes its own connection, as before.
    """
```

구현 요점:

1. 세션 진입 시 `duckdb.connect(str(self._catalog_path))` (read-write) 1개를 열고
   `_ensure_writer_schema`를 **1회만** 돌린다.
2. `_connect_writer` / `_connect_reader`는 활성 세션이 있으면 그 커넥션(또는 `.cursor()`)을
   반환하고, **없으면 현행대로 새로 연다.**
3. 반환된 객체의 `close()`가 세션 커넥션을 실제로 닫으면 안 된다. 호출부의
   `finally: connection.close()`는 **6곳**(local.py:178, :280, :322, :387, :401, :423)이다
   (:714, :723은 `_connect_writer` / `_connect_reader` 내부의 실패 처리이므로 별개).
   6곳을 전부 바꾸느니, **세션 중에는 `close()`가 no-op인 얇은 프록시**를 반환하는 편이
   변경 표면이 작다.
   프록시를 쓴다면 `duckdb.DuckDBPyConnection` 타입 힌트와의 관계를 어떻게 정리할지 결정하고
   record에 남길 것(`typing.Protocol` 도입 또는 `cursor()` 반환).
4. **`read_only=True`를 세션 안에서는 쓸 수 없다**(§4.1 #2). 세션 커넥션에서 `.cursor()`를
   파생시켜 reader에 준다. `_validate_reader_schema`의 검증 책임은 유지한다.
5. 재진입(nested `session()`)은 refcount로 처리하거나 명시적으로 금지하라. 둘 중 하나를
   고르고 record에 근거를 남길 것.
6. 스레드 안전성: `_THREAD_LOCKS` (local.py:61)가 이미 있다. 세션 상태를 인스턴스에 두면
   스레드 간 공유가 문제가 된다. **단일 스레드 사용을 전제로 하고 그 전제를 docstring에
   명시**하는 편이 현 사용 실태에 맞다.

**세션을 여는 위치 (호출부 변경):**

| 파일 | 위치 | 스코프 |
|---|---|---|
| `src/qlibx/project.py:256` | `_run_daily` — `flow.run(...)` 전체를 감싼다 | daily run 1회 |
| `src/qlibx/project.py:95` | `strategy_extension_flow` 사용 지점 | 검증 1회 |
| `src/qlibx/project.py:180-212` | `adjust_constraints` / `validate_constraints` / `monitor_constraints` | 각 1회 |

**절대 하지 말 것:** 모듈 전역에 커넥션을 캐시하고 영구히 열어두는 것. §4.1 #4·#5로
`tests/test_catalog_recovery.py`의 다중 프로세스 테스트가 깨진다.

**증분 검증 전략 (권장):** 먼저 세션 인프라만 넣고 **아무 호출부도 세션을 열지 않은 상태**로
전체 스위트를 통과시켜라(무변경이어야 한다). 그 다음 `_run_daily` 한 곳만 감싸고 다시 돌려라.
문제가 생기면 원인이 인프라인지 호출부인지 즉시 구분된다.

### C4 — `docs: record catalog session semantics`

C3가 도입한 "세션 중 다른 프로세스는 카탈로그를 열 수 없다"는 의미를 문서화한다.

- `docs/qlibx-architecture.md`의 evidence/catalog 절
- `src/qlibx/resources/skills/qlibx/references/error-recovery.md` — 세션 중 다른 프로세스의
  실패가 어떤 error code로 관측되는지 확인하고, 새 code가 생기면 추가

docs-only이므로 record 불필요.

### C5 — `perf: cache registered observation frames` (P-06)

**수정 파일:** `src/qlibx/data/store.py`

`ObservationStore`에 인스턴스 단위 캐시를 둔다. 키는 `(resolved source path, st_mtime_ns, st_size)`.

캐시할 것은 **필터링 이전의 정규화된 프레임** — 즉 store.py:94-101에서 만드는 `visible` DataFrame
(단, `available_at <= cutoff` 필터 이전 상태). 그 뒤 `as_of` / `session_date` / `observation_at`
필터는 캐시된 프레임 위에서 수행한다.

**필드별 캐시 키가 필요하다.** `selected_columns`(store.py:45-54)가 `field`에 따라 달라지므로
캐시 키에 `field`도 포함해야 한다. 또는 필요한 컬럼을 전부 읽어 한 번만 캐시하는 편이 단순하다 —
어느 쪽을 택했는지 record에 근거를 남길 것.

**`file_hash` 재계산 (store.py:37)** 은 `(mtime_ns, size)`가 그대로일 때만 건너뛴다. 이건
**보안 검사가 아니라 무결성 검사**이므로 캐시가 정당하다. 다만 "같은 mtime/size로 내용이 바뀐
파일은 탐지하지 못한다"는 약화를 record의 trade-off 절에 반드시 적을 것. 세션 경계에서 캐시를
버리는 옵션도 검토하라.

**`DataSnapshotError` 경로를 잃지 마라.** 캐시 적중 시에도 소스가 사라졌거나 지문이 달라졌으면
동일한 예외가 나야 한다. `tests/test_data_source_audit.py`가 이를 검증한다.

---

## 6. 검증

### 6.1 커밋마다 (전부 필수)

```powershell
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe -m ruff check .
```

C1·C2·C5는 **기존 테스트 무변경 통과가 acceptance criterion**이다. 동작이 바뀌면 안 된다.

### 6.2 C1 — 초선형성이 사라졌는지

```bash
.venv/Scripts/python.exe experiments/catalog-performance/bench_publish.py 800
```

**성공 기준:** 800건 구간의 publish 1건당 비용이 100건 구간 대비 **1.5배 이내**
(현행 66.2 → 194.8ms = 2.9배). 표 전체를 record의 `## Validation`에 붙일 것.

추가로 회귀 테스트를 넣어라: 카탈로그에 N건을 publish한 뒤 `_read_unterminated_events`가
**0행**을 반환하는지 assert. 정상 상태에서 복구 스캔이 비어 있다는 것이 이 커밋의 불변식이다.

### 6.3 C3 — 커넥션 수가 줄었는지

```bash
PYTHONPATH=experiments/catalog-performance .venv/Scripts/python.exe -m pytest tests -q -s -p qxprof
```

**성공 기준:** `connect(write)` + `connect(read_only)` 합계가 **1,798 → 유의미하게 감소**하고
스위트 wall이 줄어든다. 감소하지 않으면 세션이 실제로 걸리지 않은 것이다.

**정확성 기준 (더 중요):**

```powershell
.venv/Scripts/python.exe -m pytest tests/test_catalog_recovery.py -q
```

다중 프로세스 테스트 2건과 크래시 매트릭스가 전부 통과해야 한다. 여기가 깨지면 커밋을
되돌려라 — 속도를 위해 복구 정확성을 거래하지 않는다.

### 6.4 C5 — 파일 재읽기가 줄었는지

```bash
PYTHONPATH=experiments/catalog-performance .venv/Scripts/python.exe -m pytest tests -q -s -p qxprof2
```

**성공 기준:** `pd.read_parquet` / `pd.read_csv` / `file_hash` 호출 수가 감소하고
`ObservationStore.query` 호출 수는 **동일**해야 한다(호출을 줄인 게 아니라 캐시가 먹은 것).

---

## 7. Process 의무

- **Implementation record:** 현재 최고 번호 **044**. 다음은 **045**. 형식 `NNN-kebab-case-slug.md`,
  구조는 `## Intent` / `## Observable outcome` / `## Responsibilities and flow` /
  `## Alternatives and trade-offs` / `## Validation` / `## Remaining limitations`.
  **성능 커밋의 `## Validation`에는 before/after 수치를 verbatim으로 넣을 것.**
  C0·C4는 실험·문서 전용이므로 record를 만들지 않는다(`AGENTS.md`).
- **Commit:** Conventional Commits, subject line만. body·trailer 없음.
- **ExecPlan:** 이 작업은 evidence / data / flow / project를 넘나들고 §4의 미승인 의미 변경을
  포함하므로 ExecPlan 대상이다. `.agent/plans/active/`에 만들고 완료 후 `completed/`로 옮긴다.
- **승인이 필요한 지점:** C3의 "세션 중 다른 프로세스 차단"은 관측 가능한 계약 변경이다.
  구현 전에 사용자 확인을 받을 것.

---

## 8. 측정으로 배제된 접근 (반복하지 말 것)

| 아이디어 | 실측 결과 | 판정 |
|---|---|---|
| `information_schema.tables` → `duckdb_tables()` | 콜드 커넥션에서 23.2ms → **27.2ms (악화)**. 웜 커넥션에서만 0.556 → 0.164ms로 빨라 보임 | **하지 마라.** 실제 패턴은 콜드다 |
| `max(event_order)` → `CREATE SEQUENCE` + `nextval()` | 20,000행 `max()` 0.374ms vs `nextval()` **1.380ms (악화)**. DuckDB zone map이 이미 빠르다 | **하지 마라** |
| 이벤트 INSERT 4건을 한 트랜잭션으로 묶기 | 10.4초를 벌지만 크래시 복구 계약을 깬다 (§3.4, §4.3) | **금지** |
| 커넥션을 모듈 전역에 영구 캐시 | `tests/test_catalog_recovery.py`의 다중 프로세스 테스트가 깨진다 (§4.1 #4·#5) | **금지** |
| import 최적화 / lazy import | 누적 0.52초. 스위트의 0.3% | 무의미 |
| pandas·cvxpy 튜닝 | 프로파일 상위에 없음 | 무의미 |
| `pytest-xdist` 병렬화 | 측정 안 함. 다만 카탈로그가 파일 락으로 직렬화되므로 이득이 제한적일 것으로 **추정** | 근본 해결 아님 |

---

## 9. 부록 — 계측 스크립트 전문

C0에서 `experiments/catalog-performance/` 아래에 그대로 만든다.

### 9.1 `qxprof.py`

```python
"""pytest plugin: measure duckdb connect/execute/close and fsync costs."""

import atexit
import collections
import os
import time

import duckdb

STATS = collections.defaultdict(lambda: [0, 0.0])

_real_connect = duckdb.connect
_real_fsync = os.fsync


class _Wrapped:
    def __init__(self, inner):
        self._inner = inner

    def execute(self, *a, **k):
        start = time.perf_counter()
        try:
            return self._inner.execute(*a, **k)
        finally:
            elapsed = time.perf_counter() - start
            entry = STATS["execute"]
            entry[0] += 1
            entry[1] += elapsed
            sql = " ".join(str(a[0]).split())[:58] if a else "?"
            sub = STATS["  sql| " + sql]
            sub[0] += 1
            sub[1] += elapsed

    def close(self):
        start = time.perf_counter()
        try:
            return self._inner.close()
        finally:
            entry = STATS["close"]
            entry[0] += 1
            entry[1] += time.perf_counter() - start

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _connect(*a, **k):
    start = time.perf_counter()
    try:
        return _Wrapped(_real_connect(*a, **k))
    finally:
        key = "connect(read_only)" if k.get("read_only") else "connect(write)"
        entry = STATS[key]
        entry[0] += 1
        entry[1] += time.perf_counter() - start


def _fsync(fd):
    start = time.perf_counter()
    try:
        return _real_fsync(fd)
    finally:
        entry = STATS["os.fsync"]
        entry[0] += 1
        entry[1] += time.perf_counter() - start


duckdb.connect = _connect
os.fsync = _fsync

_T0 = time.perf_counter()


@atexit.register
def _report():
    total = time.perf_counter() - _T0
    lines = ["", "=" * 62, f"instrumented wall: {total:.2f}s", "=" * 62]
    for key, (count, seconds) in sorted(STATS.items(), key=lambda kv: -kv[1][1]):
        lines.append(
            f"{key:22s} n={count:6d}  total={seconds:7.2f}s"
            f"  avg={seconds / max(count, 1) * 1000:7.2f}ms  {seconds / total * 100:5.1f}%"
        )
    print("\n".join(lines))
```

### 9.2 `bench_publish.py`

```python
"""Measure how per-publish cost scales with catalog size."""

import sys
import tempfile
import time
from pathlib import Path

from qlibx.evidence.local import LocalArtifactBackend
from qlibx.models import QlibxModel


class Payload(QlibxModel):
    index: int
    filler: str


def main() -> None:
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    bucket = max(total // 8, 1)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        catalog = LocalArtifactBackend(
            catalog_path=root / "catalog.duckdb",
            artifact_dir=root / "artifacts",
        )
        window_start = time.perf_counter()
        print(f"{'published':>10} {'ms/publish':>12}")
        for index in range(total):
            outcome = catalog.publish_model(
                logical_identity=f"identity-{index}",
                artifact_type="bench",
                artifact_schema_version=1,
                producer_id="bench",
                payload=Payload(index=index, filler="x" * 256),
            )
            assert outcome.status.value == "complete", outcome
            if (index + 1) % bucket == 0:
                elapsed = time.perf_counter() - window_start
                print(f"{index + 1:>10} {elapsed / bucket * 1000:>12.1f}")
                window_start = time.perf_counter()


if __name__ == "__main__":
    main()
```

### 9.3 `probe_conn.py` — §4.1 재현

```python
"""Probe DuckDB connection coexistence rules that constrain any caching design."""

import subprocess
import sys
import tempfile
from pathlib import Path

import duckdb

print("duckdb", duckdb.__version__)
tmp = Path(tempfile.mkdtemp())
db = tmp / "c.duckdb"

w = duckdb.connect(str(db))
w.execute("CREATE TABLE t (a INTEGER)")
w.execute("INSERT INTO t VALUES (1)")

try:
    w2 = duckdb.connect(str(db))
    print("1. same-process 2nd read-write : OK")
    w2.close()
except Exception as exc:
    print("1. same-process 2nd read-write : FAIL", type(exc).__name__)

try:
    r = duckdb.connect(str(db), read_only=True)
    print("2. same-process read_only      : OK")
    r.close()
except Exception as exc:
    print("2. same-process read_only      : FAIL", type(exc).__name__, str(exc)[:160])

try:
    c = w.cursor()
    print("3. writer.cursor()             : OK", c.execute("SELECT count(*) FROM t").fetchone())
    c.close()
except Exception as exc:
    print("3. writer.cursor()             : FAIL", type(exc).__name__)

probe = "import duckdb,sys; duckdb.connect(sys.argv[1], read_only=True).execute('SELECT 1')"
done = subprocess.run([sys.executable, "-c", probe, str(db)], capture_output=True, text=True,
                      errors="replace")
print("4. other-process read_only     :", "OK" if done.returncode == 0 else "FAIL")

probe_w = "import duckdb,sys; duckdb.connect(sys.argv[1]).execute('SELECT 1')"
done = subprocess.run([sys.executable, "-c", probe_w, str(db)], capture_output=True, text=True,
                      errors="replace")
print("5. other-process read-write    :", "OK" if done.returncode == 0 else "FAIL")

w.close()
done = subprocess.run([sys.executable, "-c", probe_w, str(db)], capture_output=True, text=True,
                      errors="replace")
print("6. other-process rw after close:", "OK" if done.returncode == 0 else "FAIL")
```

### 9.4 `probe_cold.py` — §3.2 재현

```python
"""Cost of the per-connection schema check on a COLD connection (the real pattern)."""

import shutil
import tempfile
import time
from pathlib import Path

import duckdb

tmp = Path(tempfile.mkdtemp())
seed = tmp / "seed.duckdb"
con = duckdb.connect(str(seed))
con.execute("CREATE TABLE artifacts (a INTEGER, b VARCHAR)")
con.execute("CREATE TABLE artifact_edges (a INTEGER)")
con.execute("CREATE TABLE publication_events (a INTEGER)")
con.execute("CREATE TABLE catalog_metadata (schema_version INTEGER)")
con.execute("INSERT INTO catalog_metadata VALUES (1)")
con.close()

INFO = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
DUCK = "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main'"
PRAGMAS = [f"PRAGMA table_info('{t}')"
           for t in ("artifacts", "artifact_edges", "publication_events")]
VERSION = "SELECT schema_version FROM catalog_metadata"

SCENARIOS = {
    "connect + close only": [],
    "current: information_schema + 3 PRAGMA + version": [INFO, *PRAGMAS, VERSION],
    "duckdb_tables() + 3 PRAGMA + version": [DUCK, *PRAGMAS, VERSION],
    "duckdb_tables() only": [DUCK],
}

N = 60
for label, statements in SCENARIOS.items():
    work = tmp / "work.duckdb"
    total = 0.0
    for _ in range(N):
        shutil.copyfile(seed, work)
        start = time.perf_counter()
        c = duckdb.connect(str(work))
        for sql in statements:
            c.execute(sql).fetchall()
        c.close()
        total += time.perf_counter() - start
        work.unlink()
    print(f"{label:48s} {total / N * 1000:7.2f} ms per open/validate/close")
```

### 9.5 `qxprof2.py` — P-06 계측

```python
"""pytest plugin: measure ObservationStore.query internals."""

import atexit
import collections
import time

import pandas as pd

from qlibx.data import registry, store

STATS = collections.defaultdict(lambda: [0, 0.0])


def _wrap(owner, name, label):
    original = getattr(owner, name)

    def wrapper(*a, **k):
        start = time.perf_counter()
        try:
            return original(*a, **k)
        finally:
            entry = STATS[label]
            entry[0] += 1
            entry[1] += time.perf_counter() - start

    setattr(owner, name, wrapper)


_wrap(store.ObservationStore, "query", "ObservationStore.query (total)")
_wrap(registry, "file_hash", "  file_hash (rehash source)")
_wrap(store, "file_hash", "  file_hash via store")
_wrap(pd, "read_parquet", "  pd.read_parquet")
_wrap(pd, "read_csv", "  pd.read_csv")

_T0 = time.perf_counter()


@atexit.register
def _report():
    total = time.perf_counter() - _T0
    lines = ["", "=" * 66, f"instrumented wall: {total:.2f}s", "=" * 66]
    for key, (count, seconds) in sorted(STATS.items(), key=lambda kv: -kv[1][1]):
        lines.append(
            f"{key:32s} n={count:6d} total={seconds:7.2f}s"
            f" avg={seconds / max(count, 1) * 1000:7.2f}ms {seconds / total * 100:5.1f}%"
        )
    print("\n".join(lines))
```

### 9.6 `probe_sql.py` — §3.3·§8 재현

```python
"""Micro-benchmark the queries that run on every publish."""

import tempfile
import time
from pathlib import Path

import duckdb

tmp = Path(tempfile.mkdtemp())
con = duckdb.connect(str(tmp / "c.duckdb"))

# event_order: full max() scan vs sequence
con.execute("CREATE TABLE ev (event_order BIGINT, payload VARCHAR)")
con.executemany("INSERT INTO ev VALUES (?, ?)", [(i, "x" * 200) for i in range(20000)])
con.execute("CREATE SEQUENCE ev_seq START 20001")
for label, sql in {
    "max(event_order) over 20k rows": "SELECT coalesce(max(event_order), 0) + 1 FROM ev",
    "nextval(sequence)": "SELECT nextval('ev_seq')",
}.items():
    con.execute(sql).fetchall()  # warm
    start = time.perf_counter()
    for _ in range(200):
        con.execute(sql).fetchall()
    print(f"{label:38s} {(time.perf_counter() - start) / 200 * 1000:6.3f} ms")

# recovery scan: full log vs unterminated attempts only
# NOTE: phase values below must match PublicationPhase in evidence/contracts.py
con.execute(
    "CREATE TABLE pe (event_order BIGINT, attempt_id VARCHAR, phase VARCHAR, event_json VARCHAR)"
)
con.executemany(
    "INSERT INTO pe VALUES (?, ?, ?, ?)",
    [(i, f"a{i // 4}", "catalog_committed" if i % 4 == 3 else "staged", "{}" * 60)
     for i in range(20000)],
)
for label, sql in {
    "SELECT event_json (full log, current)": "SELECT event_json FROM pe ORDER BY event_order",
    "unterminated attempts only": (
        "SELECT event_json FROM pe WHERE attempt_id NOT IN ("
        "  SELECT attempt_id FROM pe WHERE phase IN ('catalog_committed', 'recovered_abandoned')"
        ") ORDER BY event_order"
    ),
}.items():
    rows = con.execute(sql).fetchall()
    start = time.perf_counter()
    for _ in range(50):
        con.execute(sql).fetchall()
    print(f"{label:38s} {(time.perf_counter() - start) / 50 * 1000:6.3f} ms  rows={len(rows)}")
```

---

## 10. 범위 밖 미해결 항목

- **P-04 (이벤트 단계 4개)** — 10.4초(6.4%)가 걸려 있지만 크래시 복구 계약이라 이번 계획에서
  제외했다. 단계 수를 줄이는 것은 복구 설계 변경이며 별도 승인이 필요하다.
- **`_commit_publication`의 `COMMIT` 3.78ms × 927회** — DuckDB의 내구성 비용이다.
  P-01을 고친 뒤 다시 측정해 남은 비중을 확인할 것.
- **`pytest-xdist` 병렬화** — 측정하지 않았다. 카탈로그가 프로세스 락으로 직렬화되므로 이득이
  제한적일 것으로 추정하지만, C1·C3 이후 실측할 가치는 있다.
- 이 문서의 finding 번호는 `P-xx`다. 직전 리뷰의 `R-xx`, 그 이전의 `F-xx`와 겹치지 않도록
  인용 시 출처를 명시할 것.
