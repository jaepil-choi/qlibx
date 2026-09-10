# 238 — A command reads each fact of its sources once

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 없음 — 0.13.0 시나리오 stepper의 트레이스(`experiments/exp_238_the_scenario_trace_0_13_0/`)가 보인 중복 읽기를 닫는 bounded fix |
| **이슈** | 없음. 0.12.0 stepper가 남긴 보고 `docs/issues/report-2026-09-10-check-derives-a-three-year-agenda-twice.md`가 이 자리의 절반이다 |
| **설계 근거** | 기록 `234`: 물리 파일의 사실은 등록 때 한 번 재고, 이후의 읽기는 identity를 대조한다. 기록 `069`: agenda는 명령당 한 번 유도한다. 이 기록은 그 "한 번"을 **명령의 스냅샷(`Workspace` 객체)** 단위로 만든다 |
| **브랜치** | `develop` (0.13.1 stamped 뒤) |
| **앞선 기록** | `069`(agenda 한 번), `162`(horizon을 콜백마다 다시 스캔하지 않는다), `234`(문 하나), `236`(배치의 cube) |

---

## 왜 이 변경이 있는가

0.13.0 stepper를 만들며 `sys.setprofile`로 뜬 트레이스를 다시 읽었다(`exp_238/README.md`). 명령 하나가 같은
사실을 여러 번 읽고 있었다. `vqapr run sample-factor-run`(10세션) 한 프로세스에서:

| 사실 | 읽은 자리 | 횟수 |
|---|---|---|
| 집행표의 distinct 시각 전부 (`evaluation_times`) | judgments의 `derived_agenda`(#752) · preflight의 `derived_agenda`(#4018) | 2 |
| 집행표의 `(start, end]` 안 시각 (`candidate_instants`) | 집행 순서 판정의 `build_horizon`(#3708) · preflight `_validate_execution_targets`(#7269) · run의 `execution_horizon`(#8272) | 3 |
| 바뀐 파일의 sha256 (`check`, 03 트레이스) | 판정이 거절할 때(#45880) · preflight가 다시 물을 때(#90143) | 2 |
| 배치의 run이 무엇을 읽는가 (`_reads`, 15 트레이스) | `require_independent_batch`(#1070 · #1159) · `_bake_for_batch`(#1246 · #1336) — run마다 컴포넌트를 import해 `requirements()`를 묻는다 | run당 2 |

프로파일러 없이 재면(같은 sample 프로젝트, in-process) 집행표의 distinct 스캔 하나가 25~30 ms다. 다섯 번이면
`check sample-run` 182 ms의 절반이 넘고, 3년 run이든 10세션 run이든 같은 값이다 — 집행표의 크기에만 비례한다.
바뀐 파일의 두 번째 해시는 작은 표에선 3 ms지만 400 MB 원천에선 초 단위이고, 그 명령은 어차피 거절될 명령이다.

첫 번째와 두 번째 행은 한 컬럼의 두 질문이다. `candidate_instants`는 `trade_at > start AND trade_at <= end`의
distinct이고, `evaluation_times`는 같은 컬럼의 distinct 전부다. 앞의 것은 뒤의 것을 자르면 나온다.

## 무엇이 어떻게 바뀌었는가

1. **`Workspace.evaluation_times`가 dataset id마다 한 번 읽는다** (`project/store.py`). `Workspace` 객체는 명령
   하나의 스냅샷이고 digest memo(`_source_digests`)가 이미 그 규칙으로 산다(기록 `234`); 같은 슬롯에
   `_evaluation_times`를 둔다. judgments와 preflight가 같은 workspace 객체를 받으므로(`docs/issues/archive/070`)
   두 번째 `derived_agenda`는 스캔 없이 같은 튜플을 받는다.

2. **horizon은 이미 읽은 시각에서 자른다**. `ExecutionHorizon.between(instants, start_time, end_time)`
   (`exchange/conventions.py`)이 `candidate_instants`가 답하던 것과 같은 조각을 값에서 만들고,
   `preflight.bound_execution_horizon(workspace, definition)`이 그것을 `evaluation_times`로부터 만든다. 집행 순서
   판정(`judgments._judge_execution_ordering`)과 `_validate_execution_targets`(이제 horizon을 인자로 받는다)가
   그것을 쓴다. `FillRule.build_horizon`은 그대로다 — run 자체의 `CallbackHandler.execution_horizon`은 얼린 run만
   들고 workspace가 없으며, run당 한 번이 기록 `162`의 계약이다. 그 세 번째 스캔은 남는다(아래 "바꾸지 않은 것").

3. **실패한 대조도 한 번만 해시한다**. `Workspace.require_verified`가 digest를 `source_digest`(memo)를 통해 얻어
   `validation.require_verified`에 넘긴다. 이전엔 통과한 digest만 memo에 들어가 거절된 파일은 preflight가 다시
   해시했다. `dataset.unverified`(저장된 digest 없음)는 바이트를 읽기 전에 거절되므로 그 앞에서 그대로 낸다.

4. **배치는 run이 읽는 것을 한 번 묻는다**. `orchestration.batch_reads(workspace, run_ids)`가 답을 만들고
   `require_independent_batch`와 `batch_cubes`가 `reads=`로 받는다(없으면 스스로 묻는다 — 기존 호출자와 테스트는
   그대로). `cli/run.py`가 한 번 묻고 둘에 넘긴다. `_datasets_read`는 `reads[run_id]`의 키가 되어 사라졌다.

**바꾸지 않은 것.** run 시작 뒤의 `execution_horizon` 스캔(run당 1회, 25 ms). FrozenRun에 horizon을 실으면
record 모양이 바뀌므로 이 기록의 범위 밖이다. 컴포넌트 load 4회(판정 · freeze · 초기 memory 검증의 "두 번째
fresh 인스턴스"(`docs/issues/archive/076`) · run) — 각각 자기 이유가 있고 7 ms씩이다. 콜백마다 `normalize_memory`
5회 — 별도 기록. `placement`의 첫 호출 800 ms — vqapr 밖(numpy 첫 사용)의 cold cost.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/test_workspace.py::test_a_workspace_reads_a_datasets_instants_and_hashes_its_file_once_per_command` (신규) | 한 workspace 객체에서 `distinct_values` 1회 · `physical_digest` 1회; 바이트가 바뀐 파일은 두 번 물어도 해시 1회에 `dataset.source_changed` 2회 |
| `tests/flow/declaration/test_preflight.py::test_the_execution_horizon_is_cut_from_the_sessions_already_read_not_scanned_again` (신규) | `between`이 자른 horizon == `build_horizon`이 스캔한 것; judgments + preflight 한 workspace에서 `candidate_instants` 0회, `evaluation_times` 4회 요청에 스캔 1회 |
| `…test_preflight.py::test_the_agenda_is_cut_on_dates_before_it_is_built_and_derived_once_per_command` (수정) | 메서드 호출 수 대신 **스캔** 수를 센다(horizon도 같은 메서드를 묻게 됐으므로): check 1회 · preflight 1회 |
| `tests/cli/test_a_datamodel_run_through_the_cli.py::test_the_batch_driver_asks_each_run_what_it_reads_once` (신규) | `batch_reads` 한 번 뒤 두 문에 넘기면 `_reads`는 run당 1회; 넘기지 않으면 각 문이 스스로 묻는다 |
| `tests/test_workspace.py` · `tests/flow/declaration/test_preflight.py` · `tests/cli/test_check.py` · `tests/cli/test_a_datamodel_run_through_the_cli.py` | 70 passed |
| `uv run python -m pytest tests/ -q` (fast) | 1,704 passed, 29 deselected (140 s) |
| `uv run ruff check src/` · `uv run python -m pyright` | clean · 0 errors |
| 시간 (in-process, best of 3, HEAD의 `src`를 `git archive`로 꺼내 같은 sample 프로젝트에서 A/B) | `check sample-run` 181.8 → 97.4 ms · `check sample-factor-run` 153.0 → 71.1 ms · `run sample-factor-run --force` 969 → 875 ms · `run sample-stoploss-run --force` 1,434 → 1,369 ms |
| `uv run python -m pytest tests/ -q -m ""` (test_all) · `scripts/showcase_record_digest.py --check` | VALIDATION_ALL |
