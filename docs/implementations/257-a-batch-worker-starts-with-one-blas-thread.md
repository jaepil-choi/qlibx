# 257 — A `--jobs` worker starts with one BLAS thread unless the user set a count

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로). 메모리 보고의 넷 중 넷째 |
| **이슈** | `docs/issues/report-2026-09-11-a-strategy-runs-memory-grows-with-its-orders-far-past-the-documented-per-worker-size.md` |
| **설계 근거** | 오너 판정 2026-09-11 — 선택지 셋(워커만 / 모든 프로세스 / 문서만) 중 "`--jobs` 워커만" |
| **브랜치** | `develop` |
| **앞선 기록** | `230`(두 종류의 run 모두 풀로), `236`(배치의 cube) |

---

## 왜 이 변경이 있는가

보고에서 한 번도 거래하지 않는 Hold run도 private 1.08 GB였고 working set은 0.37 GB였다. 측정해 보니 그 바닥의 대부분은
numpy의 OpenBLAS다: 로드될 때 쓸 수 있는 코어마다 작업 버퍼를 commit한다. 이 32코어 머신에서 `vqapr.cli.main`까지
import한 프로세스의 private이 **0.838 GB**, 그중 실제로 만진 것은 수십 MB였다. Windows에서 commit은 쓰지 않아도
머신의 한도에 잡힌다. `--jobs` 워커는 각자 프로세스라 각자 commit하고, 워커 N개 × BLAS 스레드 32개는 코어를 두고
다투기만 한다 — 워커들이 이미 코어를 쓰고 있다.

## 무엇이 어떻게 바뀌었는가

`flow/orchestration.py`에 `BLAS_THREAD_VARIABLES`(`OPENBLAS_NUM_THREADS`·`OMP_NUM_THREADS`·`MKL_NUM_THREADS`)와
`one_blas_thread_for_workers()`. `in_workers`가 풀을 이 컨텍스트 안에서 연다: 사용자가 정하지 **않은** 변수만 `"1"`로
두고, spawn된 워커는 시작할 때 그 환경을 복사하며, 풀이 닫히면 부모 프로세스의 환경을 원래대로 돌린다(파이썬
호출자의 프로세스를 바꾸지 않는다). skill: run-backtest의 크기 문단과 `watching-and-failures.md`의 spill 문장.

## 바꾸지 않은 것

단일 run(풀을 쓰지 않는다)의 스레드 수, 사용자가 정한 값, BLAS를 쓰는 사용자 코드의 결과(스레드 수는 속도만 바꾼다).

## 검증

| 검사 | 결과 |
|---|---|
| `tests/flow/test_batch_workers_run_one_blas_thread.py` (신규) | 안에서는 셋 다 `"1"`, 나오면 원래대로(없었으면 없음); 사용자가 둔 `OPENBLAS_NUM_THREADS=8`은 그대로 |
| 같은 명령의 `--jobs` 경로들(`test_a_run_reports_every_strategy.py`·`test_a_datamodel_is_a_run.py`·`test_a_datamodel_run_through_the_cli.py`, `-m ""`) | 24 passed — 풀이 이 컨텍스트 안에서 그대로 돈다 |
| import 바닥(`scratchpad/mem/import_floor.py`, 32코어) | `vqapr.cli.main`까지: 기본 private **0.838 GB** / `OPENBLAS_NUM_THREADS=1`(과 형제들) **0.062 GB** — 워커당 ~0.78 GB |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |
