# 한 cube 캠페인 — run의 horizon만큼, 한 벌만, 배치는 한 번만

enhanced-index testbed가 0.11.0 wheel로 671개 alpha datamodel run을 동시에 돌리다 스왑으로 죽었고, 원인을
재어 보고했다(`docs/issues/098`): run 하나의 peak 메모리가 lookback(160일)이나 기간이 아니라 **종목 수에
선형**이다 — 309 종목 0.32 GB, 기간 7배엔 12%. 오너가 물은 것은 "근본적으로 메모리를 줄이되 속도를
희생하지 않는 길", 예로 든 것은 date × ticker × feature 3d cube였다.

브랜치 `redesign/one-cube`, develop `2c976d11`에서 시작. 마일스톤마다 기록 하나. 계획 원본은 `.agent/plans/`
(로컬)이고 이 문서는 그 결산이다. 측정은 전부 `experiments/exp_236_the_panel_memory/`.

## 0. 진단과 소유자 결정 (2026-09-10)

원인은 두 겹이었다.

1. **0.11.0의 `Panel.from_rows`** 가 `observation_rows`의 Python dict 행 877k개를 들고 pivot했다 — 그것이
   0.32 GB. record `232`(0.12.0)가 보고 도착 전에 이미 Arrow 스캔 + numpy pivot으로 바꿨다. 같은 모양의 합성
   원천(4,975 종목 · 2,955 세션 · 8.0M 행)으로 0.11.0 트리를 재면 309 종목 0.35 GB 대 5 종목 0.14 GB, 보고의
   기울기 그대로.
2. **panel이 등록 span 전체를 스캔**했고(run 기간과 무관), 숫자 필드를 **두 벌**(Arrow + numpy 블록) 들었고,
   배치의 worker마다 같은 parquet을 **다시 스캔**해 자기 사본을 만들었다.

오너 결정:

- 3d cube는 record 232 이후 필드마다 이미 (instants × instruments) 행렬이다. 남은 것은 **span·사본·스캔**이다.
- 근본 해법은 dataset의 숫자 필드마다 cube 하나를 **모든 종목 × 등록 span**으로 한 번 굽고, 모든 worker가
  memory-map으로 공유하는 것. 프로세스 4개가 0.40 GB 배열 파일을 읽을 때 `np.load`는 시스템 메모리 1.58 GB,
  `mmap`은 0.48 GB, 프로세스당 private 0 — 잰 뒤 채택.
- **파일이 쌓이면 안 된다.** `--jobs` 배치가 시작할 때 굽고 끝날 때 지운다. 단일 run은 스캔 경로 그대로.
- float32 아님(유효숫자), 스레드 아님(콜백이 Python이라 GIL).

## 1. 마일스톤과 기록

| 마일스톤 | 기록 | 무엇이 바뀌었나 | 게이트 |
|---|---|---|---|
| M0 | — | `exp_236`: 합성 원천 생성기, panel 빌드 peak 측정(0.11.0 트리 / develop / horizon), 프로세스 4개의 copy 대 mmap | fast 1685 · pyright 0 |
| M1 | `235` | `Panel`: 숫자 필드는 instant-major float64 블록 한 벌(`blocks`), `kinds`로 INTEGER는 int, 문자열은 Arrow; `bounds`와 거절하는 `window`; `placement`/`dense_block`. store: `horizon=(start, end)` + `requirements` → 스캔은 `[start에서 가장 이른 lookback 하한, end]`; `_run_member`가 넘김 | fast 1691 · pyright 0 · ruff clean |
| M2 | `236` | `data/cube.py`: `bake`(모든 종목, 필드마다 .npy + present + instants + cube.json) · `open_cube` · `panel_from_cube`(전체면 view, 부분집합이면 gather); `observation_table(instruments=None)`; store `cubes=`; `orchestration.batch_cubes`(sweep · lock · heartbeat · bake · rmtree); worker 인자 `cubes: str`; `cli/run.py`가 두 풀을 감쌈 | fast 1700 · pyright 0 · ruff clean |
| M3 | — | 이슈 098 번호·닫음, ledger, 릴리스 노트 초안(`docs/releases/0.13.0.md`, 번호는 오너가), skill 두 줄(`make-datamodel` reading-inputs, `run-backtest` §5); `_shipped.json`은 stamp 때 | `test_all` 1729 · digest 83/83 · pyright 0 · ruff clean |

## 2. 숫자

worker 하나(바닥 0.13 GB), 7년 run, 160일 CalendarLookback, 필드 1개:

| | 309 종목 private | 4,975 종목 private | 4,975 종목 peak |
|---|---|---|---|
| 0.11.0 (dict 행) | 0.21 GB (peak 0.35) | — | — |
| record 232 (Arrow + 블록) | 0.04 GB (peak 0.18) | — | — |
| record 235 (horizon, 한 벌, 스캔) | 0.074 GB | 0.372 GB | 0.76 GB |
| record 236 (cube를 map) | **0.007 GB** | **0.013 GB** | **0.17 GB** |

bake는 필드당 1.6 s, 디스크 132 MB, 배치당 한 번. 671-run sweep의 스캔 671번이 bake 한 번이 된다. 창 순회
시간은 변하지 않았다(`matrix()`는 view).

## 3. 결정 로그

- **cube는 dataset 단위, run은 선택.** 디렉터리 = dataset, 파일 = 숫자 필드. run의 dataset · fields ·
  instruments · lookback은 각각 디렉터리 · 파일 · 인덱스 배열 · `bisect` 둘이 된다. strategy와 datamodel은
  같은 store를 지나므로 구분이 없다.
- **instant-major.** 전 종목을 선언한 run(firm characteristics)이 순수 view가 되는 레이아웃. 부분집합은
  어차피 gather라 name-major가 더 나을 것이 없다.
- **`present.npy`.** 값 null과 행 없음을 NaN 하나로 접으면 cube에서 만든 panel의 instant 축이 스캔 panel의
  축과 어긋난다(선언 종목 모두 값이 null인 세션). 행의 존재를 따로 들어 두 경로가 셀 단위로 같게 했고,
  테스트가 네 경우를 대조한다.
- **파일 기반, `shared_memory` 아님.** 핸들 수명 관리가 없고, 페이지 캐시가 압박 때 버리고 다시 읽으며,
  단일 run과 배치가 한 경로다. 배치 수명은 오너 결정.
- **cube는 지름길이지 문이 아니다.** store는 자기가 잰 digest와 같고 필드를 다 들 때만 쓴다. bake 실패,
  미검증 등록, 문자열 필드, `rows` grain은 그냥 없고 worker는 배치 밖에서처럼 스캔·거절한다.
- **RowsLookback의 하한은 원천 instant grid 산술**이다(설계 §2.4의 ruling). grid는 종목으로 거르지 않은
  superset이라 panel보다 넓을 수는 있어도 좁을 수는 없다.
- **`Panel.bounds` 밖은 거절.** 창이 조용히 짧아지는 것은 아무도 볼 수 없는 look-behind 구멍이다.
- 릴리스 번호는 오너가 찍는다. 문서 모양은 바뀌지 않았고(등록·record 그대로), 새 keyword 인자만 늘었다.

## 4. 발견

- panel identity는 `panel.py`/`store.py` 밖에서 아무도 소비하지 않고 record에도 쓰이지 않는다 — span을
  bounds로 바꿔도 record 모양은 그대로다.
- panel 읽기는 전부 occurrence의 evaluation time과 compliance의 market instant, 즉 `[start, end]` 안에서만
  일어나고 finalization은 panel을 읽지 않는다.
- duckdb `threads`(1 대 32)는 스캔 peak를 움직이지 않는다.
- RSS는 공유 페이지를 프로세스마다 다시 센다. 효과는 private bytes나 시스템 가용 메모리로 봐야 보인다.
- 이 호스트에서 `uv run pytest`는 "uv trampoline failed to canonicalize script path"로 죽는다;
  `uv run python -m pytest`는 된다.
