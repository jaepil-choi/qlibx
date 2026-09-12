# 249 — A run in a `--jobs` batch writes the run record a single run writes

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로) |
| **이슈** | `docs/issues/report-2026-09-11-a-jobs-batch-writes-no-run-record-so-show-run-refuses-runs-it-reported-completed.md` |
| **설계 근거** | 기록 `139`(`run.json` = run의 모든 member가 공유하는 설정), `228`(`_run_member`가 strategy와 datamodel의 공통 몸체) |
| **브랜치** | `develop` |
| **앞선 기록** | `139`, `228`, `230`(datamodel run도 풀로) |

---

## 왜 이 변경이 있는가

`vqapr run a b --jobs 2`가 두 run 다 `status: completed`라고 보고하고, `list runs`가 둘 다 나열하는데,
`show run a`는 "this store holds no run"이라며 거절했다(`known: (none)`). `vqapr.public.strategy_report`는
`FileNotFoundError`. 디스크에는 `runs/<id>/strategies/`만 있고 `run.json`이 없었다. FF3 testbed 두 곳에서
여섯 포트폴리오 run 전부가 그랬다.

원인은 문이 둘이었던 것이다. `run.json`은 `orchestration.run`과 `_run_datamodels`가 member를 부르기 **전에**
썼는데, `--jobs` 워커(`run_registered_strategy` · `run_registered_datamodel`)는 그 둘을 건너 member 함수
(`_run_strategy` · `_run_datamodel`)를 직접 부른다. 한 run만 `--jobs`로 주면 풀을 쓰지 않으므로(`_run_one`)
보고의 대조군 셋째 줄이 멀쩡했다.

## 무엇이 어떻게 바뀌었는가

- `freeze_run_record`를 `_run_member` 안으로 옮겼다 — store가 있을 때, member의 writer가 디렉터리를 잡기
  직전. `_run_member`는 in-process 경로와 워커 경로가 모두 지나는 유일한 자리다.
- `run`과 `_run_datamodels`의 호출은 지웠다. 문이 하나이므로 다시 갈라질 수 없다.

**순서의 변화 하나.** 전에는 `run.json`이 component load·drift 검사 **앞**에 쓰였고, 이제는 그 **뒤**다. load에
실패한 run은 이제 `run.json`도 남기지 않는다 — 기록 `228`이 member 디렉터리에 둔 규칙("a component that
drifted claims no record directory")과 같다. run이 중간에 죽었을 때 무엇을 시도했는지 말한다는 `run.json`의
약속은 그대로다(member 몸체보다 앞).

## 바꾸지 않은 것

- `run.json`의 내용과 스키마. 같은 설정은 같은 바이트이고, 다른 설정은 `RunRecordConflict`(`__reduce__`로
  워커 경계를 넘는다)로 거절되며 워커에서 올라온 것은 `cli/run.py::_record_refusal`이 순차 경로와 같게 그린다.
- 이미 배치로 돌아 `run.json`이 없는 run은 스스로 고쳐지지 않는다. `vqapr run <id> --force`로 다시 돌리면 생긴다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/flow/test_a_run_reports_every_strategy.py::test_a_batch_worker_writes_the_run_record_a_single_run_writes` (신규) | 워커를 이 프로세스에서 부른다 — 풀의 경로에서 pickling만 뺀 것. `run.json`의 `strategies`·`writes`가 선다. 수정 전에는 `read_run_record`가 `FileNotFoundError` (코드 경로상 `freeze_run_record` 호출이 워커에 없었다) |
| 같은 파일 slow 테스트(`--jobs 3`, 세 run) · `tests/flow/run/test_a_datamodel_is_a_run.py`의 `--jobs 2` datamodel 테스트 | 배치의 모든 run에 `run.json` 단언 추가 — 통과 |
| `tests/flow/test_a_run_reports_every_strategy.py tests/flow/run/test_a_datamodel_is_a_run.py tests/record tests/cli/test_a_datamodel_run_through_the_cli.py -m ""` | 64 passed |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |
