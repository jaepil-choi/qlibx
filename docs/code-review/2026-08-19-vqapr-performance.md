# vqapr performance review — 2026-08-19

| | |
|---|---|
| **발견 시각** | 2026-08-19 KST (+09:00) |
| **리뷰 대상** | `run()` hot path — `flow/simulation.py`, `flow/run_state.py`, `data/store.py`, `data/scan.py`, `exchange/conventions.py`, `account/` |
| **브랜치 / HEAD** | `jaepil-develop` @ `a825b62` — *Carry the ensemble to three alphas and measure one* |
| **작업 트리 상태** | dirty (43 entries: `M src/vqapr/{cli,flow,orders,portfolio,valuation,extension}/…`, `?? tests/{agent,cli,extension,valuation}/`) |
| **테스트 기준선** | `uv run pytest -q` → **515 passed in 61.88s** |
| **계측 환경** | Windows 11, Python 3.12 (uv venv), duckdb 1.5.5, SHA256 처리량 **1,942 MB/s** (측정값) |
| **동기** | kwam-enhanced-index의 research replication이 너무 느림 |
| **수정 여부** | **코드 수정 없음.** 이 문서는 진단 + 수정 설계만 담는다. |
| **작업자** | gjc |

> **⚠ Staleness 주의.** 모든 위치는 위 HEAD + 위 작업 트리 기준이다. 착수 전에 각 항목의
> **재현 절차**를 먼저 돌려 아직 살아 있는지 확인할 것. 이미 고쳐졌다면 지우지 말고
> `RESOLVED @ <sha>`로 표시한다.

> **📌 선행 리뷰 연계.** `docs/code-review/2026-08-18-vqapr-review.md`의 **EB-5**(`data/store.py:26`
> digest)와 **EB-6**(`exchange/conventions.py:148` 날짜 루프)는 **아직 살아 있다.** 이 문서의
> P0-2 / P2-6이 같은 항목이며, 여기에는 그때 없던 계측치와 수정 설계가 붙어 있다.

---

## 0. 총평

**"event callback이 loop으로 도니까 느리다"는 진단은 틀렸다.** loop 자체는 문제가 아니다.
비용은 콜백 안에서 **매번 처음부터 다시 하는 일**에 몰려 있고, 두 축으로 갈린다.

**축 A — 이벤트당 물리 I/O.** parquet이 메모리에 올라온 적이 한 번도 없다. `CREATE TABLE`도,
view도, 커넥션 재사용도 코드 전체에 없다 (`lru_cache`/`@cache` grep 결과 **0건**). 매 관측
쿼리가 (1) 새 DuckDB 커넥션을 열고 (2) 소스 parquet **전체 바이트를 SHA256으로 재해싱**하고
(3) `read_parquet` glob + footer를 재파싱하고 (4) 커넥션을 닫아 캐시를 전부 버린다.
게다가 `RowsLookback`은 SQL에 하한이 없어서 **매번 데이터셋 시작점부터 스캔**한다.

**축 B — 런 길이에 대한 제곱 누적.** 매 root 생성마다 **과거 전체를 다시 검증**한다. 누적된
모든 model state를 재해싱하고, 지금까지 기록된 모든 recorder row를 dict로 재복사한다.
런이 길어질수록 세션당 비용이 선형으로 증가하므로 총비용이 제곱이 된다. 1년 백테스트가
멀쩡한데 10년이 10배가 아니라 100배가 되는 패턴이 이것이다.

**왜 515개 테스트가 다 통과하는데 안 보이나.** fixture가 작기 때문이다. 계측해 보면
`tests/fixtures`의 parquet은 **총 39KB**이고, acceptance 전체가 관측 쿼리를 **29건**밖에 안 던진다.
축 A는 소스 크기에 비례하고 축 B는 세션 수의 제곱에 비례하는데, 테스트는 둘 다 거의 0이다.
**이 두 축은 테스트로는 영원히 안 잡힌다** — §6의 회귀 가드가 따로 필요한 이유다.

### 우선순위 요약

기준 시나리오: **2,500 세션**(10년 일간), **3,000-name universe**, 리밸런스당 **500 targets/fills**,
소스 parquet **500 MB**. 추정치는 이 시나리오 기준이며 §1에 재계산 방법이 있다.

| # | 축 | 위치 | 한 줄 | 추정 비용 | 난이도 |
|---|---|---|---|---|---|
| **P0-1** | A | `data/scan.py:405` | `RowsLookback`에 SQL 하한이 없어 매번 데이터셋 처음부터 스캔 | 데이터 크기 비례, **최대** | 중 (⚠정확성) |
| **P0-2** | A | `data/store.py:58` | 조회마다 소스 parquet 전체를 SHA256 재해싱 | **~86 분** | 하 |
| **P0-3** | B | `flow/run_state.py:104` | root 생성마다 누적 recorder row 전체를 재복사 | **~45 분** | 중 |
| **P0-4** | B | `flow/run_state.py:80` | root 생성마다 누적 model state 전체를 재해싱 | **~34 분** | 중 |
| **P1-1** | A | `data/store.py:79` | 쿼리 결과를 Python에서 셀 단위 재검증, 그것도 **두 번** | 반환 행수 비례 | 하 |
| **P1-2** | A | `exchange/conventions.py:137` | 콜백마다 남은 horizon 전체 instant를 스캔, 첫 행만 사용 | 세션 수 제곱 | 중 |
| **P1-3** | A | `data/scan.py:143` | 쿼리마다 새 DuckDB 커넥션 (~10 ms 고정비 + 메타데이터 폐기) | **~4 분** + 재디코딩 | 하 |
| **P2-1** | — | `flow/simulation.py:1293` | 콜백당 strategy state를 4~6회 직렬화/역직렬화 | strategy state 크기 비례 | 중 |
| **P2-2** | — | `flow/simulation.py:1322` | universe 멤버십을 tuple로 검사 (set이 아님) | **~1 분** (170× 손해) | **하 (한 줄)** |
| **P2-3** | — | `data/windows.py:61` | occurrence마다 전체 universe를 재정규화 | ~수십 초 | 하 |
| **P2-4** | — | `flow/simulation.py:1328` | source ref를 콜백당 두 번 계산, 인덱스도 매번 재구축 | ~수십 초 | 하 |
| **P2-5** | — | `account/account.py:78` | due execution마다 `fill_history` tuple 재구성 ×4 | **~40 초** | 중 |
| **P2-6** | — | `exchange/conventions.py:149` | 콜백마다 남은 달력 전체를 순회하고 결과를 버림 | selector 의존 | 하 |
| **P2-7** | — | `orders/planning.py:93` | 매수 clip을 1주씩 감소시키며 루프 | 종목가 의존 | 하 |
| **P3-1** | — | `account/snapshot.py:87` | `AccountState` 생성마다 `mark_history` 전체 재정렬 | ~0.6 초 | 하 |
| **P3-2** | — | `flow/simulation.py:777,783` | mirror 검사가 `AccountState`를 deep compare | ~1 초 | 하 |

### 초기 진단에서 바로잡은 것

착수 전에 반드시 읽을 것. 계측 없이 세운 가설 중 둘이 틀렸다.

1. **`AccountState` deep compare는 병목이 아니다** (P3-2). 두 state의 history tuple은 *서로 다른
   객체*지만 *원소는 동일 객체*라서, CPython의 `PyObject_RichCompareBool` identity fast path가
   포인터 비교로 끝낸다. 측정: 200k 원소에 **0.070 ms**. 같은 자리에서 진짜 비싼 것은 비교가 아니라
   `(*hist, *new)` **tuple 재구성**이다 (200k에 **1.27 ms**, 18배). 그래서 P2-5가 남고 P3-2는 내려갔다.
2. **account history 계열의 총비용은 시간 단위가 아니라 분 단위다.** `fill_history` 재구성 ~40초,
   `mark_history` 검증 ~0.6초. 처음에 "O(N²)이니 심각"이라고 묶었지만 상수가 작아서 P0가 아니다.
   **P0는 recorder row 재복사(P0-3)와 model state 재해싱(P0-4)이다** — 상수가 각각 100배 이상 크다.
3. **새로 찾은 것: `RowsLookback`의 SQL 하한 부재 (P0-1).** 초기 리뷰에 없었다. 데이터 크기에
   비례하므로 실제 warehouse에서는 이것이 최대 항목일 가능성이 높다.

---

## 1. 계측 근거 — 재현 절차

모든 수치는 아래로 재현된다. gjc는 **착수 전에 이 셋을 자기 환경에서 한 번 돌려** 기준선을 잡을 것.

### 1.1 프로파일 (vqapr 프레임만)

```bash
uv run python -c "import cProfile,pstats,io,pytest; pr=cProfile.Profile(); pr.enable(); pytest.main(['tests/acceptance/test_enhanced_index.py','-x','-q','--no-header','-p','no:cacheprovider']); pr.disable(); s=io.StringIO(); pstats.Stats(pr,stream=s).sort_stats('cumtime').print_stats('vqapr',25); print(s.getvalue())"
```

HEAD 기준 결과 (발췌):

```
ncalls  tottime  cumtime  function
    29    0.001    1.131  data/windows.py:80(observations)
    29    0.001    1.125  data/store.py:46(query)
    29    1.116    1.116  data/scan.py:379(observation_rows)   ← 38 ms/call, fixture가 수십 행인데도
    31    0.316    0.317  data/scan.py:129(_open)              ← 10 ms/call, 데이터 크기 무관 고정비
    29    0.000    0.022  data/store.py:26(_physical_digest)   ← fixture가 39KB라 안 보임
```

### 1.2 물리 I/O 계측 (digest / connect / query 횟수)

```bash
uv run python -c "
import pytest, time
from vqapr.data import store, scan
stats = {'digest_calls':0,'digest_bytes':0,'connects':0,'obs':0,'digest_time':0.0}
_d = store._physical_digest
def digest(path):
    t=time.perf_counter(); stats['digest_calls']+=1
    files=(path,) if path.is_file() else tuple(sorted(path.glob('**/*.parquet')))
    stats['digest_bytes']+=sum(f.stat().st_size for f in files)
    r=_d(path); stats['digest_time']+=time.perf_counter()-t
    return r
store._physical_digest = digest
_o = scan._open
def op(spec):
    stats['connects']+=1
    return _o(spec)
scan._open = op
_ob = scan.observation_rows
def ob(*a, **k):
    stats['obs']+=1
    return _ob(*a,**k)
scan.observation_rows = ob
pytest.main(['tests/acceptance/test_enhanced_index.py','-x','-q','--no-header','-p','no:cacheprovider'])
print()
for k,v in stats.items(): print(f'{k:16s}', v)
"
```

HEAD 기준 결과:

```
observation queries   : 29
duckdb connects       : 31
digest calls          : 29        ← query 1건당 정확히 1건
bytes re-hashed       : 39,353    ← fixture 전체 크기. 실제로는 (쿼리 수 × 소스 전체 크기)
digest wall time      : 0.025 s
```

**재해싱 바이트 = 쿼리 수 × 소스 전체 크기.** 이 등식이 P0-2의 전부다.

### 1.3 마이크로벤치 (축 B 상수 확인)

```bash
uv run python -c "
import time
from types import MappingProxyType
from vqapr.flow.model_state import prepare_model_state
def bench(label, fn, reps=10):
    t=time.perf_counter()
    for _ in range(reps): fn()
    print(f'{label:46s} {(time.perf_counter()-t)/reps*1000:9.3f} ms')
rows = tuple({'instrument':f'A{i:06d}','weight':'0.001','run_id':'r','producer_id':'p','stage':'s','event_time':None,'sequence':i} for i in range(100_000))
bench('re-wrap 100k recorder rows (run_state:104)', lambda: tuple(MappingProxyType(dict(r)) for r in rows))
bench('tuple concat 100k + 500 (run_state:224)', lambda: rows + rows[:500])
mem = {'window': [float(i) for i in range(500)], 'fitted': {'a':1.0,'b':2.0}}
bench('prepare_model_state x1', lambda: prepare_model_state(mem, b'x'*50_000), reps=200)
"
```

HEAD 기준 결과:

```
re-wrap 100k recorder rows (run_state:104)        42.619 ms   ← P0-3의 상수
tuple concat 100k + 500 (run_state:224)           0.444 ms   ← 96배 싸다. 여기는 문제가 아니다
prepare_model_state x1                            0.163 ms   ← P0-4의 상수
```

### 1.4 추정치 재계산법

축 B 항목은 세션 `k`에서 비용이 `c × k`이므로 총비용 = `c × R × N²/2` (R = 세션당 root 생성 수 ≈ 4).

| 항목 | 단위 상수 `c` | 기준 시나리오 총합 |
|---|---|---|
| P0-3 recorder 재복사 | 0.426 ms / 1k rows → 500 rows/세션 = **0.213 ms/세션²** | `0.213 × 4 × 3.13M ms` ≈ **45 분** |
| P0-4 model state 재해싱 | **0.163 ms/state** | `0.163 × 4 × 3.13M ms` ≈ **34 분** |
| P2-5 fill_history 재구성 | 1.27 ms / 200k → 500 fills/세션 = **0.0032 ms/세션²** | `× 4 × 3.13M ms` ≈ **40 초** |
| P3-1 mark_history 검증 | 0.947 ms / 20k marks | ≈ **0.6 초** |
| P3-2 AccountState `!=` | 0.070 ms / 200k | ≈ **1 초** |

축 A 항목은 데이터 크기에 비례한다: P0-2 = `쿼리수 × 소스크기 ÷ 1,942 MB/s`.
**소스 크기와 세션 수만 바꿔 넣으면 gjc 환경 수치가 나온다.**

---

## 2. P0 — 먼저 고칠 것

### P0-1. `RowsLookback`이 SQL 하한 없이 데이터셋 처음부터 스캔한다 🔴 최우선

**위치** — [`src/vqapr/data/store.py:62-65`](../../src/vqapr/data/store.py),
[`src/vqapr/data/scan.py:405-410`](../../src/vqapr/data/scan.py)

**무엇이 일어나나.** `store.query()`가 lookback을 두 갈래로 나눈다.

```python
# data/store.py:62-65
if isinstance(requirement.lookback, RowsLookback):
    rows = requirement.lookback.rows          # ← lower_bound는 None으로 남는다
elif isinstance(requirement.lookback, CalendarLookback):
    lower_bound = requirement.lookback.lower_bound(evaluation_time)
```

`scan.observation_rows`는 `lower_bound`가 있을 때만 하한 술어를 붙인다.

```python
# data/scan.py:405-410
predicates = [f"{available} <= ?", f"{instrument} IN ({placeholders})"]
if lower_bound is not None:
    predicates.append(f"{available} >= ?")   # ← RowsLookback은 여기 안 온다
```

그래서 `RowsLookback(5)` 쿼리의 실제 SQL은 이렇게 된다:

```sql
WITH gated AS (
  SELECT *, count(close) OVER (PARTITION BY instrument ORDER BY available_at DESC
           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS __vqapr_rank_0
  FROM read_parquet('warehouse/**/*.parquet')
  WHERE available_at <= ?  AND instrument IN (?, ?, … ×3000)   -- 하한 없음
)
SELECT … FROM gated WHERE (close IS NOT NULL AND __vqapr_rank_0 <= 5) ORDER BY …
```

**rank는 SQL로 내려갔지만 스캔 범위는 안 내려갔다.** window function이 데이터셋 시작점부터
evaluation_time까지 전 구간을 partition·정렬해야 한다. 반환 행수는 `5 × 3000 = 15k`로 작은데
**읽고 정렬하는 행수는 전체 이력 × universe**이고, 런이 진행될수록 커진다.

docstring이 `"""Execute one physical PIT observation query with its lookback pushed into SQL."""`
라고 말하는데, **`RowsLookback`에 대해서는 절반만 참이다.**

**왜 최우선인가.** 이 비용은 세션 수가 아니라 **warehouse 크기 × 세션 수**에 비례한다.
hive 파티션이 걸려 있어도 하한이 없으면 partition pruning이 전혀 안 걸린다. 실제 KRX warehouse
에서는 이것이 P0-2보다 클 가능성이 높다.

**고치는 법.**

하한을 넣되 **rows semantic을 깨지 않는 방식**이어야 한다. 단계적으로:

1. **먼저 측정.** 하한만 붙였을 때 DuckDB가 실제로 pruning을 하는지 `EXPLAIN ANALYZE`로 확인한다.
   pruning이 안 걸리면(파티션 레이아웃 문제) 이 항목의 이득이 없으므로 여기서 멈추고 P0-2로 간다.

   ```bash
   uv run python -c "
   import duckdb
   con = duckdb.connect()
   print(con.execute('''EXPLAIN ANALYZE SELECT count(*) FROM read_parquet('<warehouse>/**/*.parquet', hive_partitioning=1) WHERE available_at <= TIMESTAMPTZ '2020-01-01+09' ''').fetchall()[0][1])
   "
   ```

2. **낙관적 하한 + 명시적 fallback.** `DataRequirement`에 optional한 `scan_hint`(보수적 calendar
   하한)를 선언으로 받고, 쿼리를 두 단계로 나눈다.
   - 1단계: 하한을 걸고 조회한다.
   - 2단계: 요청한 instrument 중 **`rows`개를 못 채운 것**이 있으면, **그 종목들만** 하한 없이
     재조회한다.

   정상 종목은 1단계에서 끝나고(pruning 이득 전부), 정지·상폐 종목만 2단계 비용을 낸다.

3. **결과 동일성 증명.** 하한 있는 경로와 없는 경로의 결과가 **byte-identical**임을 검증하는
   테스트를 먼저 쓴다 (§6 G-1).

> **⚠ 정확성 위험 — 반드시 읽을 것.**
> 순진하게 하한만 걸면 **정지/상폐 종목의 mark가 조용히 사라진다.**
> `public._marks_for_occurrence`는 "cutoff 이전 가장 최근 관측"으로 보유 종목을 평가하고,
> 그 관측이 몇 달 전일 수 있다는 것이 **의도된 동작**이다
> (`docs/implementations/019-a-mark-says-when-it-was-observed.md`,
> `tests/valuation/test_stale_marks.py` 참조). 하한 아래로 밀려나면
> `ValuationService.mark`가 `missing selected mark for …`로 런을 죽이거나 — 더 나쁘게 —
> 평가가 달라진다. **2단계 fallback 없이 1단계만 넣지 말 것.**

**검증** — `uv run pytest tests/valuation/ tests/data/ tests/acceptance/ -q` + §6 G-1.

---

### P0-2. 조회마다 소스 parquet 전체를 SHA256으로 재해싱한다 🔴

**위치** — [`src/vqapr/data/store.py:26-36`](../../src/vqapr/data/store.py) (`_physical_digest`),
호출부 [`:58`](../../src/vqapr/data/store.py)
*(= 2026-08-18 리뷰 EB-5, 미해결)*

**무엇이 일어나나.** `DuckDbObservationStore.query()`가 매 호출마다 소스 parquet 전체 바이트를
Python `open()` + 1MB 청크로 읽어 SHA256을 계산한다. 캐시가 없다.

```python
# data/store.py:58
source_digest = _physical_digest(source.path)   # ← 매 query. frozen run 동안 불변인 값
```

**비용.** 계측 등식은 `재해싱 바이트 = 쿼리 수 × 소스 전체 크기`. 기준 시나리오
(세션당 ~8 쿼리 × 2,500 세션 × 500 MB ÷ 1,942 MB/s) = **~86 분**, 오직 해싱에만.

> OS page cache가 있으니 매번 디스크 platter까지 내려가진 않는다. 하지만 page cache가 막아주지
> **못하는** 것이 셋이다 — 바이트 전체 순회, SHA256(순수 CPU), 그리고 duckdb의 parquet
> 압축해제·디코딩. warehouse가 RAM보다 크면 그때는 진짜 디스크 I/O다.

**고치는 법.** `DuckDbObservationStore` 인스턴스 수명 = 1 run이다
(`public.run()` [`:396`](../../src/vqapr/public.py)에서 한 번 생성). 인스턴스 캐시면 충분하다.

```python
class DuckDbObservationStore:
    __slots__ = ("__catalog", "__digests")

    def __init__(self, catalog: DatasetCatalog) -> None:
        self.__catalog = catalog
        self.__digests: dict[Path, str] = {}

    def _digest(self, path: Path) -> str:
        cached = self.__digests.get(path)
        if cached is None:
            cached = self.__digests[path] = _physical_digest(path)
        return cached
```

**이것은 단순 최적화가 아니라 기존 불변식과 정합한다.**
`SimulationFlow._actual_source_refs` ([`simulation.py:1349`](../../src/vqapr/flow/simulation.py))가
이미 이렇게 강제하고 있다:

```python
raise RuntimeError("one callback observed multiple byte digests for one source")
```

즉 **한 run은 소스당 digest 하나만 봐야 한다는 것이 이미 계약이다.** 매번 재계산하는 것은 그
계약을 확인하는 방법이었을 뿐이고, run당 1회 계산은 계약을 더 강하게 만든다(위반이 불가능해짐).

**더 나은 최종 형태 (별도 작업으로 분리 권장).** digest를 preflight/freeze 시점에 계산해
`FrozenRun`에 담으면 `run()`은 해싱을 아예 안 한다. frozen run identity의 일부로서도 더 옳다.
다만 `FrozenRun` 스키마 변경이라 P0-2와 섞지 말 것.

**곁다리.** `_physical_digest`의 수동 1MB 루프는 `hashlib.file_digest()`(Python 3.11+)로 바꾸면
버퍼 복사가 줄어든다. 캐시를 넣으면 호출이 run당 1회라 이득은 미미하니 같이 하되 우선순위는 없다.

**검증** — `uv run pytest tests/data/ tests/flow/ -q`,
그리고 §1.2 계측을 다시 돌려 `digest calls`가 **소스 수와 같아야** 한다(29 → 1~2).

---

### P0-3. root 생성마다 누적 recorder row 전체를 재복사한다 🔴

**위치** — [`src/vqapr/flow/run_state.py:98-108`](../../src/vqapr/flow/run_state.py)
(`AcceptedRunState.__post_init__`), 누적부 [`:224`](../../src/vqapr/flow/run_state.py)

**무엇이 일어나나.** `AcceptedRunState.__post_init__`이 지금까지 기록된 **모든** row를 새 dict로
싸서 다시 만든다.

```python
# flow/run_state.py:101-107
object.__setattr__(
    self, "recorder_rows",
    MappingProxyType({
        name: tuple(MappingProxyType(dict(row)) for row in rows)   # ← 누적 전체
        for name, rows in self.recorder_rows.items()
    }),
)
```

root는 세션당 ~4회 생성된다 (callback publish → account commit → marked → feedback).

**중요한 구분.** **디스크 write는 일어나지 않는다.** `InvocationRecorder._rows`는 순수 메모리
`dict[str, list[Row]]`이고, `run()` 루프 안에 파일 write가 없다
(`flow`/`evidence`/`data` 전체에서 write는 [`materialize.py:489`](../../src/vqapr/flow/materialize.py)
한 곳뿐이며 그건 `publish_run_record`/`publish_run_allocation` — `run()` 종료 후 별도 호출).
**"메모리에 모았다가 마지막에 dump"라는 기대는 맞다.** 문제는 dump 시점이 아니라,
메모리 안에서 **append가 아니라 매번 전체 재구축**을 한다는 것이다.

**비용.** 100k row 재복사에 **42.6 ms** (§1.3). 기준 시나리오에서 누적 1.25M row까지 자라며
총 **~45 분**. 참고로 [`:224`](../../src/vqapr/flow/run_state.py)의 tuple concat은 100k에 0.44 ms로
**96배 싸다** — 여기는 손대지 않아도 된다.

**고치는 법.** 유일한 소비자가 런 끝에 있다는 사실을 이용한다.

- 소비자: [`materialize.py:745`](../../src/vqapr/flow/materialize.py)
  (`getattr(result.final_state, "recorder_rows")`) — **런 종료 후 1회**
- 그 외: 테스트가 `recorder_rows["diagnostics"][0]["sequence"]` 식으로 인덱싱

따라서 **chunk 누적**이 안전하다. 내부 표현을 "테이블별 청크 리스트"로 바꾸고, 평탄화는 읽는
시점에 한 번만 한다.

```python
# 내부: chunk append — O(1)
_recorder_chunks: Mapping[str, tuple[Rows, ...]]

@property
def recorder_rows(self) -> Mapping[str, tuple[Mapping[str, object], ...]]:
    """평탄화는 읽을 때 1회. 기존 소비자 계약은 그대로."""
    return MappingProxyType({
        name: tuple(chain.from_iterable(chunks))
        for name, chunks in self._recorder_chunks.items()
    })
```

**핵심 논거.** row는 `InvocationRecorder.append_batch`에서 이미 `normalize_rows`를 통과했고
(`recorder.py:63`), `staged_rows()`가 한 번 더 통과시킨다(`recorder.py:82`). **이미 두 번 검증된
detached 값**을 root마다 또 감쌀 이유가 없다. 재래핑이 지키려던 불변식(외부에서 못 바꿈)은
청크가 detached tuple이면 그대로 유지된다.

**⚠ 주의.** `recorder_rows`가 `__post_init__`에서 사라지면 `AcceptedRunState`를 **직접 생성하는
테스트**가 깨진다 (`tests/flow/test_publish_run_record.py:25`가 `recorder_rows` 필드를 직접
선언한다). property 경로를 남겨 계약을 유지할 것.

**곁다리.** `recorder_manifests`도 [`:225`](../../src/vqapr/flow/run_state.py)에서 콜백마다 tuple
concat으로 누적한다. 상수가 작아 급하진 않지만 같은 chunk 처리를 하면 깔끔하다.

**검증** — `uv run pytest tests/flow/ tests/acceptance/ -q` + §6 G-2.

---

### P0-4. root 생성마다 누적 model state 전체를 재해싱한다 🔴

**위치** — [`src/vqapr/flow/run_state.py:76-81`](../../src/vqapr/flow/run_state.py)

**무엇이 일어나나.**

```python
# flow/run_state.py:76-81
for ref, memory in self._model_states.items():        # ← 누적 전체
    payload = self._payloads[ref]
    if not isinstance(payload, bytes):
        _invalid_payload(ref)
    if prepare_model_state(memory, payload).ref != ref:   # json.dumps + sha256
        raise ValueError("ModelStateRef must identify its exact memory and payload")
```

`prepare_callback`이 `states = dict(root._model_states); states[candidate.ref] = …`로 누적하므로
콜백 `k`에서 `k`개를 전부 재직렬화·재해싱한다. root는 세션당 ~4회.

**비용.** `prepare_model_state` 1회 **0.163 ms** (§1.3, 500-float memory + 50KB payload).
기준 시나리오 총 **~34 분**. strategy가 rolling window나 fitted model을 memory에 들고 있으면 이
상수가 그대로 커진다.

**고치는 법.** **새로 추가된 ref만 검증한다.** 나머지는 이전 root에서 이미 증명됐다.

`ModelStateRef`는 오직 `prepare_model_state`에서만 만들어진다
([`model_state.py:38`](../../src/vqapr/flow/model_state.py)) — 즉 **ref의 존재 자체가 이미 증명이다.**
두 방향 중 택일:

- **(a) 검증된 집합을 명시적으로 나른다** — `AcceptedRunState`에 private `_verified: frozenset[ModelStateRef]`
  를 두고, `__post_init__`은 `set(self._model_states) - self._verified`만 검사한다.
  외부에서 직접 생성한 root는 `_verified=frozenset()`이 기본이므로 **기존 전수 검증이 그대로 유지**된다.
  기존 테스트를 안 깨는 쪽.
- **(b) 검증된 타입을 나른다** — `prepare_callback`이 `PreparedModelState`를 그대로 넘기고,
  root는 `PreparedModelState`에 대해서만 재해싱을 생략한다. 더 깨끗하지만 시그니처 변경 범위가 넓다.

**(a)를 권장.** 변경이 `run_state.py` 한 파일에 갇히고, "외부 생성 root는 전수 검증"이라는
안전한 기본값이 유지된다.

**같이 볼 것 — 메모리 누수 성격의 설계 질문 (결정은 gjc/사용자 몫).**
`_model_states` / `_payloads`는 콜백마다 자라고 **한 번도 줄지 않는다.** 그런데 실제로 읽히는 것은
`current_model_state_ref` 하나뿐이다 (`_visible_callback_state`,
[`simulation.py:1150`](../../src/vqapr/flow/simulation.py)). 2,500 콜백 × payload 50KB = **125 MB**가
목적 없이 상주할 수 있다. canon이 전체 이력 보존을 요구하는지 확인하고, 아니라면 보존 정책
(마지막 N개, 또는 evidence로 스트리밍)을 별도 작업으로 제안할 것. **이 리뷰에서 결정하지 않는다.**

**검증** — `uv run pytest tests/flow/ -q` + §6 G-3.

---

## 3. P1 — 그 다음

### P1-1. 쿼리 결과를 Python에서 셀 단위로 재검증하고, 그것도 두 번 한다

**위치** — [`src/vqapr/data/store.py:79-90`](../../src/vqapr/data/store.py),
[`src/vqapr/data/windows.py:40-41`](../../src/vqapr/data/windows.py) (`ObservationBatch.__init__`)

**무엇이 일어나나.** 세 겹이다.

```python
# data/store.py:79
normalized = normalize_rows(raw_rows)          # ① 셀 단위 isinstance 체인 + 키 whitespace 스캔
actual = {inst: {f: 0 for f in requirement.fields} for inst in instruments}
for row in normalized:                          # ② O(rows × fields) Python 루프
    for field in requirement.fields:
        if row[field] is not None:
            actual[instrument][field] += 1
…
return ObservationBatch(normalized, access)     # ③ __init__이 normalize_rows를 또 부른다
```

`ObservationBatch.__init__`은 `object.__setattr__(self, "rows", normalize_rows(rows))` —
**이미 정규화된 것을 다시 정규화한다.**

**비용.** `normalize_rows` 측정치 **3.16 µs/row** (200k × 5필드 = 632 ms). 반환 행수에 비례하고
**두 번** 낸다. 5일 lookback × 3,000종목 = 15k행이면 쿼리당 ~95 ms, 250일 lookback이면
쿼리당 **~4.7 초**.

**고치는 법.** 셋 다 독립적으로 고칠 수 있다.

1. **이중 정규화 제거** (가장 쉽고 안전). `ObservationBatch`가 이미 정규화된 `Rows`를 신뢰하는
   생성 경로를 갖게 한다 — 예: `ObservationBatch._trusted(rows, access)` classmethod. 공개 생성자는
   그대로 두어 외부 입력은 계속 검증한다. **즉시 2배.**
2. **카운팅을 SQL로.** `actual_rows`의 유일한 소비자는
   [`materialize.py:352`](../../src/vqapr/flow/materialize.py)의 lineage evidence다. instrument·field별
   non-null 카운트는 같은 스캔 안에서 집계로 뽑을 수 있다 (`count(col) … GROUP BY instrument`,
   또는 메인 쿼리에 window aggregate 하나 추가). Python 이중 루프가 통째로 사라진다.
3. **`normalize_rows` 자체를 fast path로.** DuckDB가 이미 타입을 보장한 컬럼에 대해 셀 단위
   `isinstance` 체인을 도는 것이 근본 낭비다. `scan.observation_rows`가 `cursor.description`으로
   컬럼 타입을 알고 있으므로, **컬럼 단위로 한 번 검증하고 행 단위 검증을 생략**하는 경로가 가능하다.
   `normalize_scalar`가 실제로 잡아야 하는 것은 non-finite float / naive datetime 둘뿐이다.

**⚠ 주의.** `normalize_rows`는 방어가 아니라 **경계 계약**이다 (naive datetime을 여기서 잡는 것이
PIT 정확성의 일부다). 1·2는 계약을 안 건드리지만 **3은 계약을 건드린다.** 3을 할 거면
"어느 컬럼이 이미 타입 보장되는가"를 명시적으로 증명하는 테스트를 먼저 쓸 것.

**검증** — `uv run pytest tests/data/ tests/flow/test_materialize.py -q`.
`tests/data/test_windows.py:62`와 `tests/flow/test_materialize.py:129`가 `actual_rows` 값을 직접
단언하므로 2를 하면 여기가 회귀 가드가 된다.

---

### P1-2. 콜백마다 남은 horizon 전체의 execution instant를 스캔한다

**위치** — [`src/vqapr/exchange/conventions.py:137-142`](../../src/vqapr/exchange/conventions.py)

**무엇이 일어나나.** `FillConvention.select_target`이 accepted intent마다:

```python
candidates = scan.candidate_instants(
    table.source, trade_at_field=table.trade_at_field,
    decision_time=decision_time, end_time=end_time,      # ← end_time = run 종료
)
…
for candidate in candidates:
    …
    return ExactExecutionTarget(…)      # ← 사실상 첫 적격 원소에서 끝난다
```

`candidate_instants`는 `SELECT DISTINCT trade_at … ORDER BY trade_at`을 `LIMIT` 없이 돌리고
전 구간을 Python tuple로 materialize한다. 1일차에 ~2,500개, 2일차에 ~2,499개…

**비용.** 총 ~3.1M 행 materialize + **2,500회 full DISTINCT 스캔**(각각 P1-3의 cold connection 위에서).

**고치는 법.** **execution table은 frozen run 동안 불변이므로 instant 집합도 불변이다.**
run당 1회 스캔해서 정렬된 tuple로 갖고 있다가, 콜백마다 `bisect_right(instants, decision_time)`으로
시작 위치만 잡는다. O(N) 스캔 × N회 → O(N) 스캔 1회 + O(log N) × N회.

캐시 소유자는 `ExecutionInputRegistration`이 아니라 **run 수명 객체**여야 한다
(registration은 값 선언이고, [`sources.py`](../../src/vqapr/data/sources.py) docstring이 "선언은 파일을
열지 않는다"를 명시한다). `SimulationFlow`가 run 시작 시 한 번 채우거나, P1-3의 scan session에
얹는 것이 자연스럽다.

**추가로**, 어떤 경우에도 `candidate_instants`에 `LIMIT`을 걸 수 있다 — `ORDER BY`가 이미
"첫 적격 instant"를 보장하므로 전체를 가져올 이유가 없다. 캐시를 안 하더라도 이 한 줄은 유효하다.

**⚠ 주의.** `SAME_DAY` selector는 `end_time`을 decision day 끝으로 좁힐 수 있어 더 쉽다. 하지만
다른 selector는 `_local_target` 해석 결과로 후보를 걸러내므로 **"첫 행"이 아니라 "첫 적격 행"**이다.
`LIMIT 1`로 줄이면 안 되고, 캐시 + bisect가 정답이다.

**검증** — `uv run pytest tests/exchange/ tests/flow/test_simulation_timing.py -q`.

---

### P1-3. 쿼리마다 새 DuckDB 커넥션을 열고 닫는다

**위치** — [`src/vqapr/data/scan.py:129-146`](../../src/vqapr/data/scan.py) (`_open`),
호출부 7곳 (`:150 :177 :209 :257 :293 :347 :445`)

**무엇이 일어나나.** 모든 scan 함수가 `con = _open(spec)` … `finally: con.close()` 패턴이다.
`duckdb.connect()`는 in-memory DB를 만들지만 **비어 있는** in-memory DB다. 매번:

- 커넥션 셋업 (**측정 10 ms**, 데이터 크기 무관)
- `read_parquet('dir/**/*.parquet')` glob 재확장
- parquet footer / row-group 통계 재파싱
- close → DuckDB의 parquet 메타데이터 캐시 **전부 폐기**

DuckDB 1.5는 커넥션 수명 동안 parquet 메타데이터를 캐시한다. **매번 닫는 것이 그 캐시를 무의미하게
만든다.**

**비용.** 기준 시나리오에서 커넥션 셋업만 **~4 분**. parquet 재디코딩은 별도이고 데이터 크기에
비례하므로 훨씬 클 수 있다 (P0-1과 겹친다).

**고치는 법 — 두 단계.**

**단계 1 (권장, 저위험): 커넥션을 run 수명으로.**
`scan.py`의 모듈 docstring이 *"물리 층을 여는 유일한 곳"*이라고 선언하고 있으므로,
**커넥션 소유권을 `scan.py` 안에 둔다.** duckdb 커넥션을 `store.py`로 유출시키지 말 것.

```python
# data/scan.py — 경계는 그대로, 수명만 바꾼다
class ScanSession:
    """한 run 동안 살아 있는 물리 층 핸들. 소유권은 scan.py 안에 남는다."""
    def __init__(self) -> None:
        self._con: duckdb.DuckDBPyConnection | None = None
    def connection(self, spec: SourceSpec) -> duckdb.DuckDBPyConnection: ...
    def close(self) -> None: ...

def observation_rows(spec, *, session: ScanSession | None = None, …): ...
```

`session=None`이면 현행대로 열고 닫는다 → **기존 호출부·테스트가 안 깨진다.**
`public.run()`이 session 하나를 만들어 `DuckDbObservationStore`에 넘긴다.

**단계 2 (선택, 사용자 원래 기대): in-memory 테이블로 materialize.**

```sql
CREATE TABLE obs AS SELECT * FROM read_parquet('…');
```

- **이득**: parquet 디코딩이 run당 1회. P0-1의 반복 스캔 비용도 크게 줄어든다.
- **대가**: warehouse가 RAM에 들어가야 한다. 안 들어가면 DuckDB가 spill하며 오히려 느려진다.
- **PIT 정확성**: 영향 없음. `available_at <= ?` 술어는 SQL에 그대로 남는다.
- **권고**: **기본값으로 하지 말 것.** replication 용도의 opt-in 플래그로 두고,
  소스 크기 대비 가용 RAM을 확인한 뒤 켠다.

**⚠ 주의.** `_open`은 커넥션 생성 외에 **경로 존재 검사**(`spec.path.exists()` → typed
`source.scan.path_missing` 실패)와 `SET preserve_insertion_order=false`를 한다.
세션으로 옮길 때 **둘 다 유지**할 것. 특히 존재 검사는 typed failure 계약이라 놓치면
에러 메시지가 duckdb 내부 예외로 바뀐다.

**검증** — `uv run pytest tests/data/ tests/exchange/ -q` + §1.2 계측에서
`duckdb connects`가 31 → 한 자릿수로.

---

## 4. P2 / P3 — 싸고 확실한 것들

각 항목이 독립적이라 아무 순서로나 집어도 된다. **P2-2는 한 줄이고 170배 이득이라 지금 하는 게 낫다.**

### P2-1. 콜백당 strategy state를 4~6회 직렬화/역직렬화한다

**위치** — [`simulation.py:1281-1302`](../../src/vqapr/flow/simulation.py) (`_candidate_callback_state`,
`_validate_candidate_payload`)

`_candidate_callback_state`가 `normalize_memory` → `save_payload` → `prepare_model_state`
(json.dumps + sha256)를 하고, 곧바로 `_validate_candidate_payload`가 **같은 payload를 다시 load →
다시 save → byte 비교**하고 `normalize_memory`를 두 번 더 부른다. 여기에 `prepare_callback`의
`prepare_model_state`와 `AcceptedRunState.__post_init__`(P0-4)이 더 붙는다.

**고치는 법.** round-trip 증명(load/save가 바이트를 안 바꾼다)은 **strategy 계약 검증**이지
매 콜백의 사실이 아니다. 옵션:
- run 시작 시 1회만 증명하고 이후 생략 — 가장 큰 이득, 계약 해석 변경이므로 **사용자 확인 필요**
- 최소한 `normalize_memory` 중복 호출은 제거 (이미 detached copy를 받은 자리에서 또 부른다)

**⚠ 이 항목은 canon 해석이 걸린다.** "매 콜백마다 상태 재현 가능성을 증명한다"가 의도된 계약이면
비용을 받아들이는 것이 맞다. gjc가 임의로 끄지 말고 확인할 것.

---

### P2-2. universe 멤버십을 tuple로 검사한다 ⭐ 한 줄, 170배

**위치** — [`simulation.py:1319-1323`](../../src/vqapr/flow/simulation.py)

```python
outside_universe = tuple(
    target.instrument_id
    for target in intent.targets
    if target.instrument_id not in self._frozen_run.instruments   # ← tuple[str, ...] 선형 스캔
)
```

**측정** — 3,000 targets × 3,000-name tuple = **24.07 ms/콜백**. frozenset = **0.14 ms**. **170배.**
(측정은 동일 문자열 객체라 identity fast path가 걸린 최선의 경우다. 실제로는 strategy가 만든
문자열과 frozen run의 문자열이 다른 객체이므로 **더 느리다.**)

**고치는 법.** `FrozenRun`에 `instruments`와 함께 `_instrument_set: frozenset[str]`을
`__post_init__`에서 한 번 만든다. 이미 [`run.py:298`](../../src/vqapr/flow/run.py)에서
`len(set(self.instruments)) != len(self.instruments)`로 set을 만들고 **버리고 있다** — 그걸 보관하면 된다.

**검증** — `uv run pytest tests/flow/ -q`.

---

### P2-3. occurrence마다 전체 universe를 재정규화한다

**위치** — [`data/windows.py:61-63`](../../src/vqapr/data/windows.py),
생성부 [`public.py:420,426`](../../src/vqapr/public.py)

`ModelWindow.__init__`이 `tuple(str(instrument_id(v)) for v in instruments)`를 돌린다.
`instrument_id`는 문자열 전체에 `any(c.isspace() …)`를 스캔한다. 그리고 uniqueness를 위해
`set(selected)`를 또 만든다. `public.run()`이 occurrence마다 strategy window + constraint window
**두 개**를 같은 `frozen.instruments`로 만든다.

**고치는 법.** `FrozenRun.instruments`는 freeze 시점에 이미 전부 검증된다
([`run.py:294-299`](../../src/vqapr/flow/run.py)). `ModelWindow`에 검증을 건너뛰는 내부 생성 경로
(`ModelWindow._for_frozen_universe(...)`)를 두고 `public.run()`이 그것을 쓴다. 공개 생성자는
그대로 검증한다. P2-2의 `_instrument_set`을 재사용하면 uniqueness 체크도 공짜다.

---

### P2-4. source ref를 콜백당 두 번 계산한다

**위치** — [`simulation.py:1328`](../../src/vqapr/flow/simulation.py) (`_validate_intent_authority`),
[`:1270`](../../src/vqapr/flow/simulation.py) (`_callback_actual_source_refs` → `_callback_evidence`)

`_actual_source_refs(window)`가 같은 window로 두 번 불린다. 매번 `datasets`/`sources` dict를
FrozenRun에서 새로 만들고 모든 id를 `str()`로 바꾼다. 게다가
[`windows.py:78`](../../src/vqapr/data/windows.py)의 `accesses` property가 호출마다 리스트를
tuple로 복사한다 (콜백당 여러 번 읽힌다).

**고치는 법.**
- `datasets`/`sources` 인덱스를 `SimulationFlow.__init__`에서 1회 구축 (run 불변)
- 두 번째 호출 제거 — 같은 window, 사이에 관측 없음이므로 **결과가 증명 가능하게 동일**하다.
  첫 결과를 지역 변수로 넘긴다.

---

### P2-5. due execution마다 `fill_history` tuple을 재구성한다

**위치** — [`account/account.py:78-84`](../../src/vqapr/account/account.py)
(`PreparedAccountTransition.__post_init__`), [`:192`](../../src/vqapr/account/account.py) (`prepare_mark`),
[`:205`](../../src/vqapr/account/account.py) (`commit_fill`),
[`run_state.py:280`](../../src/vqapr/flow/run_state.py) (`prepare_account_commit`)

`(*source.fill_history, *journal_entries)`가 due execution당 **4번** 만들어진다.
`PreparedAccountTransition.__post_init__`은 그 중 하나를 **검증 목적으로만** 만들어 비교하고 버린다.

**측정** — 200k 원소 tuple 재구성 **1.27 ms**. 기준 시나리오 총 **~40 초**.

**고치는 법.** 검증 재구성(`:78`)을 tail 검사로 바꾼다:

```python
source_len = len(self.fill.source.fill_history)
if (len(self.next_state.fill_history) != source_len + len(self.fill.journal_entries)
        or self.next_state.fill_history[:source_len] is not self.fill.source.fill_history[:...]  # 주의: 슬라이스도 복사다
        or self.next_state.fill_history[source_len:] != self.fill.journal_entries):
    raise ValueError(…)
```

**슬라이스도 O(N) 복사**라는 점에 주의. 진짜로 O(1)로 만들려면 `next_state`가 어떤 source에서
파생됐는지를 들고 다녀야 한다(`AccountState`에 private `_parent` 참조). 그건 설계 변경이므로
**길이 + tail 비교만으로도 4회 → 3회 + O(tail)**이 되어 충분하다.

**같이 볼 것.** `fill_history`가 수백만 원소까지 자라는 것 자체가 메모리 문제다.
P0-4의 `_model_states` 보존 질문과 같은 성격 — canon 확인 후 별도 작업.

---

### P2-6. 콜백마다 남은 달력 전체를 순회하고 결과를 버린다

**위치** — [`exchange/conventions.py:145-150`](../../src/vqapr/exchange/conventions.py)
*(= 2026-08-18 리뷰 EB-6, 미해결)*

```python
last_date = decision_date if self.selector is FillSelector.SAME_DAY else final_date
day = first_date
while day <= last_date:
    self._local_target(day)      # ← 결과를 버린다. 순수 검증 루프
    day += timedelta(days=1)
```

`SAME_DAY`면 1회지만, 그 외 selector에서는 **run 종료일까지** 매 콜백마다 돈다.
10년이면 첫 콜백 ~3,650회 → 총 ~660만 회의 버려지는 timezone 해석.

**고치는 법.** 이 검사는 **horizon 전체에 대한 run 불변 사실**이다. `select_target` 안이 아니라
run 시작 시 1회(또는 preflight)로 옮긴다. `FillConvention`이 값 객체라 상태를 못 들면,
`SimulationFlow.__init__`이나 preflight에서 1회 호출하는 형태가 맞다.

---

### P2-7. 매수 clip을 1주씩 감소시키며 루프한다

**위치** — [`orders/planning.py:91-99`](../../src/vqapr/orders/planning.py)

```python
affordable = rules.quantize(instrument_id, available / price)
while affordable > 0:
    notional = affordable * price
    required = notional + rules.charge(Side.BUY, notional).total
    if required <= available:
        break
    affordable = rules.quantize(instrument_id, affordable - rules.listing(instrument_id).quantity_step)
```

KRX는 `quantity_step = 1주`다. 저가주일수록 주수가 커져 반복이 늘어난다 — 500원 종목에
1,000만원이면 ~66회, 100원 종목이면 ~330회. 매 회 `listing()` + `quantize()` + `charge()`의
Decimal 연산.

**고치는 법.** 닫힌 식으로 한 번에 푼다. 비례 수수료율 `r`에 대해
`affordable = quantize(available / (price × (1 + r)))`로 잡고, **최대 1회만** 감소 보정한다
(반올림 경계). 고정 수수료가 섞이면 식에 포함시킨다.

**⚠ 주의.** `CostRule`이 비례율만이 아닐 수 있다
([`exchange/costs.py`](../../src/vqapr/exchange/costs.py) 확인). 비선형 rule이면 닫힌 식이
성립하지 않으므로, 그 경우엔 **1주씩이 아니라 이분 탐색**으로 바꾼다 (O(n) → O(log n)).
어느 쪽이든 기존 결과와 **정확히 같은 주수**가 나와야 한다 — 여기서 1주가 달라지면 이후 모든
weight가 달라진다.

**검증** — `uv run pytest tests/orders/ tests/exchange/test_krx.py -q`. 반드시 결과 동일성 확인.

---

### P3-1. `AccountState` 생성마다 `mark_history` 전체를 재정렬한다

**위치** — [`account/snapshot.py:85-88`](../../src/vqapr/account/snapshot.py)

```python
versions = tuple(mark.account_version for mark in self.mark_history)
if versions != tuple(sorted(set(versions))):     # set + sorted + tuple, 매번 신규 할당
```

**측정** — 20k marks에 **0.947 ms**. 기준 시나리오 총 **~0.6 초**. 급하지 않다.

**고치는 법.** 단조성은 단일 패스로 확인할 수 있다 — `all(a < b for a, b in pairwise(versions))`.
할당 3개가 사라지고 결과는 동일하다. 진짜 O(1)로 만들려면 신뢰된 predecessor 경로가 필요하지만
(P0-4 (a)와 같은 패턴) **이 항목은 비용이 작아 그럴 가치가 없다.**

---

### P3-2. mirror 검사가 `AccountState`를 deep compare한다

**위치** — [`simulation.py:777,783`](../../src/vqapr/flow/simulation.py)

```python
if root.account != self._account.state:
    raise RuntimeError("Account commit root does not mirror Account authority")
```

**측정** — 200k 원소에 **0.070 ms**. 기준 시나리오 총 **~1 초**. **거의 문제가 아니다.**

**⚠ `is not`로 바꾸지 말 것.** 초기 진단에서 그렇게 제안했는데 **틀렸다.**
`RunStateRepository.prepare_account_commit`과 `Account.commit_fill`이 **각각 독립적으로**
`AccountState`를 만든다. 두 객체가 서로 다르다는 사실 자체가 이 검사의 존재 이유다 —
identity로 바꾸면 mirror 검증이 무력화된다.

**정말 줄이고 싶다면** — 두 경로가 하나의 `AccountState`를 공유하도록 설계를 바꾸는 것이 옳고,
그러면 `is`가 유효해진다. 하지만 이득이 ~1초라 **지금 할 일이 아니다.** 기록만 남긴다.

---

## 5. 작업 순서 제안

측정 → 수정 → 재측정을 항목마다 반복한다. 한 번에 여러 개 고치면 어느 것이 효과였는지 모른다.

| 순서 | 항목 | 이유 |
|---|---|---|
| 0 | §1.1~1.3 기준선 확보 | 이것 없이는 개선을 증명할 수 없다 |
| 1 | **P2-2** (universe frozenset) | 한 줄, 위험 0, 170배. 워밍업 |
| 2 | **P0-2** (digest 캐시) | 단일 파일, 기존 불변식과 정합, 최대 확실 이득 |
| 3 | **P1-3 단계 1** (커넥션 수명) | P0-1 측정의 전제 조건 |
| 4 | **P0-1** (SQL 하한) | ⚠ 정확성 위험 최대. §6 G-1을 **먼저** 쓴다 |
| 5 | **P0-3** (recorder chunk) | 제곱 항 최대 |
| 6 | **P0-4** (model state 증분 검증) | 제곱 항 2위 |
| 7 | **P1-1** (이중 정규화 제거) | 즉시 2배, 저위험 |
| 8 | **P1-2** (instant 캐시 + bisect) | |
| 9 | P2-3 / P2-4 / P2-6 | 묶어서 처리 가능 |
| 10 | P2-5 / P2-7 | ⚠ P2-7은 결과 동일성 필수 |
| — | P2-1 / P3-1 / P3-2 | 사용자 확인 필요하거나 이득이 작음. 마지막 |

**실제 규모 프로파일을 언제 돌리나.** 순서 3까지 끝난 뒤 kwam-enhanced-index의 replication을
**2년치로 잘라** (universe 크기는 실제 유지) 한 번 돌리는 것을 권한다. acceptance fixture는
축 A(39KB)도 축 B(29 쿼리)도 0에 가까워서 **개선을 측정할 수 없다.** 2년치면 축 B의 제곱 항이
보이기 시작하고 실행 시간은 관리 가능하다.

---

## 6. 회귀 가드 — 테스트로는 안 잡히는 것을 잡는 법

**이 문서의 어떤 항목도 현재 515개 테스트로는 검출되지 않는다.** 수정과 함께 아래를 추가할 것.
성능 임계값 단언은 CI에서 불안정하니, **횟수**와 **결과 동일성**을 단언한다.

**G-1 — PIT 결과 동일성 (P0-1 필수 선행).**
같은 requirement를 하한 있는 경로와 없는 경로로 조회해 **byte-identical**임을 단언한다.
정지·상폐 종목(마지막 관측이 lookback 창 바깥)을 반드시 포함한다.
`tests/valuation/test_stale_marks.py`의 fixture를 재사용할 것.

**G-2 — 물리 I/O 횟수 단언.**
`_physical_digest`와 `scan._open`을 counting spy로 감싸고 (§1.2 스크립트 그대로),
acceptance 런에서 **digest 호출 ≤ 소스 수**, **connect 호출 ≤ 상수**를 단언한다.
캐시가 조용히 사라지는 회귀를 잡는다.

**G-3 — 검증 호출 횟수가 세션 수에 선형.**
`prepare_model_state`를 spy로 감싸고, N 콜백 런에서 호출 수가 `O(N)`임을 단언한다
(현재는 `O(N²)`). 상한을 `4N + C` 같은 형태로 잡으면 제곱 회귀가 즉시 걸린다.

**G-4 — 결과 불변 스냅샷.**
성능 작업 **착수 전에** 대표 replication 하나의 결과(publish된 allocation parquet 또는
`recorder_rows` 다이제스트)를 스냅샷으로 고정한다. **모든 항목의 합격 조건은
"이 스냅샷이 안 바뀐다"**이다. P0-1과 P2-7은 특히 이것 없이는 안전하지 않다.

---

## 7. 건드리지 말아야 할 것

성능 작업 중에 없애고 싶어지지만 **정확성 계약인 것들.** 지우기 전에 반드시 확인할 것.

| 위치 | 무엇 | 왜 남겨야 하나 |
|---|---|---|
| `data/scan.py` 모듈 docstring | "물리 층을 여는 유일한 곳" | duckdb 커넥션을 `store.py`나 `flow`로 유출시키면 이 경계가 깨진다. P1-3은 **`scan.py` 안에서** 해결할 것 |
| `domain/rows.py:normalize_scalar` | naive datetime 거부 | PIT 정확성의 일부. P1-1의 3번을 할 때 이 검사만은 반드시 살릴 것 |
| `simulation.py:1349` | "one callback observed multiple byte digests" | P0-2 캐시가 이 계약을 **강화**한다. 이 검사는 남긴다 |
| `simulation.py:777,783` | mirror 검사 | 두 AccountState가 독립 생성이라는 것이 검사의 요점. `is`로 바꾸면 무력화 (§P3-2) |
| `store.py` PIT 술어 `available_at <= ?` | look-ahead 방지 | in-memory materialize(P1-3 단계 2)를 해도 이 술어는 SQL에 그대로 남아야 한다 |
| `public._marks_for_occurrence` 의 stale mark 허용 | 정지/상폐 종목 평가 | P0-1이 가장 쉽게 깨뜨리는 지점. `docs/implementations/019-*.md` 참조 |
| `orders/planning.py` clip 결과 주수 | 이후 모든 weight의 입력 | P2-7에서 1주라도 달라지면 백테스트 전체가 달라진다 |

---

## 8. 남은 질문 (gjc가 사용자와 확인할 것)

1. **model state / fill_history 보존 정책.** `_model_states`, `_payloads`, `fill_history`가 런 내내
   무한히 자라고 줄지 않는다. 읽히는 것은 `current_model_state_ref` 하나뿐이다. canon이 전체 이력의
   메모리 상주를 요구하는가, 아니면 보존 정책(마지막 N개 / evidence로 스트리밍)이 가능한가?
   → P0-4, P2-5의 근본 해결이 여기에 달려 있다.
2. **콜백당 payload round-trip 증명(P2-1)이 계약인가 방어인가?** run 1회 증명으로 충분한가?
3. **in-memory materialize(P1-3 단계 2)를 replication 경로의 기본으로 둘 것인가?**
   warehouse 크기 대비 가용 RAM 확인 필요.
4. **`DataRequirement`에 scan hint를 추가하는 것이 공개 표면 변경으로 허용되는가?** (P0-1)
   허용 안 되면 하한을 내부 추정으로만 해야 하고, 그러면 fallback 경로가 필수가 된다.
