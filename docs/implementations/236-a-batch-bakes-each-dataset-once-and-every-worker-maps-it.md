# 236 — A `--jobs` batch bakes each dataset once, and every worker maps it

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | one-cube 캠페인 M2 (`.agent/plans/active/one-cube-campaign.md`) |
| **이슈** | `docs/issues/098` — 닫는다 (앞 절반은 record `235`) |
| **설계 근거** | 오너 결정 2026-09-10: "date x ticker x feature cube를 한 번 만들어 공유하되, 파일이 쌓이면 안 된다 — 병렬로 돌릴 때 생성했다가 끝나면서 지운다"; 측정 `experiments/exp_236_the_panel_memory/share_across_processes.py` |
| **브랜치** | `redesign/one-cube` |
| **앞선 기록** | `235` (a panel is the run's horizon, held once), `230` (`--jobs` spreads datamodel runs), `137` (the panel; "spill across processes and a `prepare` verb" 자리) |

---

## 왜 이 변경이 있는가

record `235`가 run 하나의 panel을 run의 horizon으로 줄이고 한 벌만 들게 한 뒤에도, 배치는 여전히 같은
일을 worker 수만큼 반복했다. 671개 alpha run이 같은 430 MB parquet을 671번 스캔해 각자의 panel을
만들었고, worker 12개가 각자의 사본을 들었다. 데이터는 작다(309 종목 7년 한 필드가 7 MB). 비싼 것은
**사본과 스캔**이다.

프로세스가 같은 바이트를 공유하는 길은 OS의 memory-map이다. 파일을 `read`로 읽으면 프로세스마다 사본이
생기고, `mmap`으로 열면 OS 페이지 캐시가 한 번 들고 각 프로세스는 창문만 낸다. 잰 것: 프로세스 4개가
0.40 GB 배열 파일을 `np.load`로 읽으면 시스템 메모리 1.58 GB(파일 × 4), 프로세스당 private +0.40 GB;
`mmap_mode="r"`로 열면 0.48 GB(파일 × 1), private +0.00; 4,975 중 309 종목만 만지면 0.12 GB. 파일은
압축된 parquet이 아니라 **배열 그대로**여야 페이지가 곧 행렬이다.

오너의 결정 둘. cube는 dataset의 숫자 필드마다 하나, 모든 종목 × 등록 span으로 — run은 그 위의 선택이다.
그리고 cube는 배치의 수명만 산다: `--jobs` 드라이버가 시작할 때 굽고 끝날 때 지운다. 단일 run은 지금처럼
스캔한다.

## 무엇이 어떻게 바뀌었는가

```text
data/cube.py (new)        bake(root, registration=, source=, source_digest=, fields=, session=) -> Cube | None
                              모든 종목(scan.distinct_values) x 등록 span을 한 번 스캔(observation_table(instruments=None)),
                              숫자 필드마다 (instants x names) float64 .npy 하나 — Panel.from_table과 같은 배치(panel.placement) —
                              + present.npy(행이 있었던 자리) + instants.npy + instruments.json + cube.json(digest, kinds)
                              한 번에 한 필드씩 저장하고 버린다; 숫자 아닌 필드·미검증 등록·rows grain은 None
                          open_cube(root, dataset_id) -> Cube | None       np.load(mmap_mode="r")
                          panel_from_cube(cube, fields=, instruments=, bounds=, ...) -> Panel
                              instant 축 = bounds 안의 cube instant 중 선언 종목 하나라도 행이 있는 것 (= from_table의 축)
                              선언 종목이 cube 종목 전부이고 그 구간이 빈틈없으면 블록은 memmap의 **view** (복사 0, 공유)
                              부분집합이면 그 열들의 gather 한 번 (run이 선언한 크기); cube에 없는 이름은 NaN 열
data/scan.py              _observation_query / observation_table: instruments=None = 원천의 모든 종목 (calendar bound만)
data/panel.py             placement(table, names, keyed) · dense_block(...) — from_table과 bake가 같은 함수로 놓는다
data/store.py             DuckDbObservationStore(..., cubes=Path | None); dataset에 cube가 있고 digest가 같고 필드를 다 들면
                          panel_from_cube, 아니면 스캔 (cube는 지름길이지 문이 아니다)
flow/orchestration.py     batch_cubes(workspace, run_ids) — contextmanager:
                              .vqapr/cubes/ 아래 lock이 600 s 넘게 안 갱신된 형제 디렉터리 sweep
                              .vqapr/cubes/<pid>-<token>/ 생성, batch.lock, 30 s heartbeat 스레드
                              배치의 run들이 읽는 panel-grain dataset마다 (필드 합집합으로) bake — 실패는 건너뜀
                              yield 디렉터리; finally: heartbeat 정지, rmtree
                          _reads(workspace, definition) -> {dataset_id: {field_id}}; _datasets_read는 그 key
                          run_registered_datamodel / run_registered_strategy (..., cubes: str = "") — spawn 경계는 문자열
                          _run_datamodel / _run_strategy / _run_member (..., cubes=) -> store
cli/run.py                _run_each_in_workers: with batch_cubes(workspace, targets) as cubes: 두 in_workers 호출 모두 안에서
```

- **cube는 dataset 단위, run은 선택.** 디렉터리 하나가 dataset 하나, 파일 하나가 숫자 필드 하나. run의 네
  선언(dataset · fields · instruments · lookback)은 각각 "어느 디렉터리 · 어느 파일 · 종목 축의 인덱스 배열 ·
  instant 축의 `bisect` 둘"이 된다. strategy와 datamodel은 같은 `read(alias, field)`로 같은 store를 지나므로
  차이가 없고, datamodel이 **쓴** dataset도 등록되면 다음 배치에서 자기 cube를 얻는다.
- **panel은 스캔이 만들었을 것과 셀 단위로 같다.** `present.npy`가 "행이 있었다"를 값과 따로 들어서, cube에서
  만든 panel의 instant 축이 `from_table`의 축(선언 종목의 행이 있는 instant)과 일치한다. 값 null과 행 없음을 둘 다
  NaN으로 접는 것은 record 235의 panel과 같다. 테스트가 네 경우(전체 · 빠진 instant가 있는 부분집합 · 원천에 없는
  이름 · 하나)를 스캔 panel과 대조한다.
- **공유가 큰 곳에서 view다.** 전 종목을 선언한 run(firm characteristics datamodel이 그렇다)은 블록이 memmap의
  view라 프로세스가 사적으로 드는 것이 0에 가깝다. 부분집합은 run이 선언한 크기의 gather 한 번이다.
- **digest가 문이다.** cube.json은 구운 바이트의 digest(`workspace.source_digest`)를 들고, store는 자기가 잰
  digest와 같을 때만 쓴다. 다른 바이트의 cube, 필드가 모자란 cube는 스캔으로 지나간다.
- **쌓이지 않는다.** 디렉터리는 배치가 돌아오면 사라진다 — 정상·거절·예외. 강제 종료가 남긴 것은 lock이 stale
  (600 s)해진 뒤 다음 배치가 치운다. heartbeat가 살아 있는 배치의 lock을 30 s마다 갱신하므로 긴 run들의 배치가
  죽은 것으로 오인되지 않는다. Windows는 map된 파일을 지울 수 없지만 worker는 풀이 닫힐 때 이미 끝나 있다.
- **구울 수 없는 것은 없는 것이다.** 미검증 등록, 문자열 필드, `rows` grain, 스캔이 안 되는 원천 — bake는
  건너뛰고 worker는 배치 밖에서처럼 스캔하고 이름으로 거절한다.

**하지 않은 것.** cube는 배치 밖에서 살지 않는다(`prepare` verb 없음). `multiprocessing.shared_memory`는
배치마다 다시 굽고 마지막 핸들이 닫히면 사라지며 페이지 캐시처럼 가볍게 버려지지 않아 택하지 않았다. 문자열
필드는 cube에 없다. 실행표·roster 읽기는 자기 경로다.

## 성능

`experiments/exp_236_the_panel_memory/measure_cube.py`. 합성 원천 4,975 종목 × 2,955 세션 8.0M 행, `close`
한 필드, 7년 run, 160일 CalendarLookback. worker는 새 프로세스(바닥 0.13 GB).

| | bake |
|---|---|
| 전 종목 × 모든 instant, 필드 1개 | 1.6 s, 디스크 132 MB — 배치당 한 번 |

| worker | 종목 | panel build | 창 2,676개 순회 | private +GB | peak GB |
|---|---|---|---|---|---|
| 스캔 (record 235) | 309 | 0.58 s | 0.36 s | 0.074 | 0.17 |
| cube | 309 | 0.29 s | 0.34 s | **0.007** | 0.17 |
| 스캔 (record 235) | 4,975 | 1.30 s | 4.04 s | 0.372 | **0.76** |
| cube | 4,975 | 0.30 s | 3.94 s | **0.013** | **0.17** |

671-run sweep이면 스캔 671번(각 0.6–1.3 s)이 bake 한 번(1.6 s)이 된다. 전 종목 run의 worker peak는 0.76 →
0.17 GB, 즉 15.7 GB 머신에서 worker 12개가 데이터로 드는 것이 4.5 GB에서 0.16 GB(+ 페이지 캐시 132 MB 한 번)가
된다. 창 순회 시간은 같다 — `matrix()`는 여전히 view다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/data/test_cube.py` (신규 8) | bake의 파일·축·NaN·present·digest; 문자열 필드/미검증 등록은 None; cube panel = 스캔 panel (4 경우, view/gather 판별); store가 cube를 쓰면 스캔 0; 다른 digest·모자란 필드는 스캔 |
| `tests/cli/test_a_datamodel_run_through_the_cli.py` | `--jobs 2` 뒤 `.vqapr/cubes` 비어 있음; 신규: `batch_cubes`가 굽고(모든 종목) worker가 스캔 0으로 돌고 디렉터리가 사라짐 — 정상·예외; stale sweep은 죽은 것만 |
| fast suite | 1700 passed, 29 deselected (1691 → +9) |
| ruff (src) · pyright | clean · 0 |
