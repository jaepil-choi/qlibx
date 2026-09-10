# 230 — `--jobs` spreads datamodel runs, and a batch that depends on itself is refused

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **닫는 이슈** | `docs/issues/report-2026-09-10-run-jobs-does-not-parallelise-datamodel-runs.md` — `vqapr run --jobs N`이 datamodel run을 병렬로 돌리지 않는다: 프로세스 하나, 한 번에 하나 |
| **브랜치** | `fix/jobs-spreads-datamodel-runs` (develop `05dbc1f5`에서) |
| **앞선 기록** | `201` (run 하나 = 모델 하나, `--jobs`는 run을 펼친다) · `170` (`VqaprError`가 pickle된다) · `073` (worker의 실패는 건너올 수 있는 것이어야 한다) · `216` (`record.exists`, 409) |

---

## 왜 이 변경이 있는가

testbed가 671개 alpha datamodel run을 `--jobs 16`으로 돌렸는데 **분당 1.07 run** — 43 s짜리 run이 한
번에 하나씩이었다. `tasklist`로 세어 보니 워커 프로세스가 없었다. `vqapr run` 여러 개를 쉘에서 동시에
띄우니 run당 3.6 s, 12배. 8시간 대 40분.

원인은 record `201`이 스스로 적어 둔 "한 가지 축소"다. `_run_each_in_workers`는 strategy run만
`in_workers`에 넣고 datamodel run은 부모에서 순차로 돌렸다. datamodel worker는 거절을 **raise**하고
(그 자체는 옳다 — `VqaprError`는 pickle되고, 순차 경로와 같은 예외다), `in_workers`는

```python
return {run_id: future.result() for run_id, future in futures.items()}
```

였으므로 worker 하나가 raise하면 comprehension이 거기서 끝나 나머지 결과를 전부 버렸다. "한 run의
거절은 그 run의 결과이고 나머지는 계속 돈다"를 지키려면 datamodel을 풀에 넣을 수 없었고, 그래서
순차로 돌렸다. `run_registered_datamodel`은 worker로 쓰라고 만들어졌고 테스트도 있었지만, CLI에서는
아무도 부르지 않았다.

보고자가 더 아프게 짚은 것은 시간이 아니라 **읽기**다. `--jobs 16`이 `--jobs 1`과 같은 처리량을
내면서 아무 말도 안 했으므로, "10개가 병렬로 370 s씩"과 "하나씩 37 s씩"을 같은 숫자에서 구분할 수
없었다. help는 "in this many processes"라고 했고, 보고자는 help를 믿었다.

## 무엇이 어떻게 바뀌었는가

**`in_workers`는 run마다 반환값 또는 예외를 모은다** (`flow/orchestration.py`). 반환 타입이
`dict[str, Returned | Exception]`. `future.result()`를 run별로 감싸서 raise된 것은 그 run의 entry가
된다. `BrokenExecutor`만 그대로 올린다 — 풀이 죽은 것은 어느 run의 소식도 아니다.

**record 예외 셋이 pickle된다** (`record/reader.py`, `record/writer.py`). `RunRecordLive`·
`RunRecordExists`·`RunRecordConflict`는 위치 인자 여럿을 받는 생성자라 기본 pickling(`cls(*args)`,
메시지 하나)이 복원에 실패했다 — record `170`이 `VqaprError`에 준 `__reduce__`와 같은 규칙을 셋에
준다. 이게 없으면 `--jobs` 아래에서 **이미 서 있는 record**(sweep을 다시 돌리는 가장 흔한 경우)가
부모에 pickling `TypeError`로 도착한다. strategy 경로도 같은 구멍이 있었다.

**CLI는 두 종류 모두 풀에 넣는다** (`cli/run.py`). `_run_each_in_workers`가 datamodel run을
`run_registered_datamodel`로, strategy run을 `run_registered_strategy`로 `in_workers`에 보낸다.
datamodel이 먼저, strategy가 나중 — 아래 가드를 통과한 배치라도 그 순서가 더 안전하다. run별 entry는
`_worker_entry`가 만든다: worker가 raise한 것은 `_record_refusal`(순차 경로 `_run_one`이 쓰는 것과
같은 문)을 거쳐 `_refusal_envelope`으로, datamodel record는 순차 경로와 같은 `run.complete` 봉투로.

**배치 봉투에 `jobs`** — 실제로 쓴 프로세스 수(`min(jobs, len(targets))`; 순차면 1). 보고자가 청한
"a caller cannot see a pool that is not there"의 답이다.

**서로 의존하는 배치는 통째로 거절한다** — 오너 결정 (2026-09-10). 처음 제안은 "strategy와 datamodel을
한 풀에서, dispatcher 하나로"였고 오너가 막았다: 어떤 datamodel의 결과물에 의존하는 strategy는 같은
병렬에서 돌 수 없다. `require_independent_batch(workspace, run_ids)`가 spawn 전에 판정한다.

- 한 run이 읽는 것 = 그 컴포넌트(모델·Compliance 규칙)의 `requirements()`의 dataset id들 +
  `agenda.days_from` + `execution.dataset`. 로드가 안 되는 컴포넌트는 아무것도 읽지 않는 것으로 —
  그 run은 자기 worker가 이름으로 거절하고, 시작 못 하는 run은 아무것과도 경주하지 않는다.
- 배치 안의 다른 run이 `writes`하는 것을 읽으면 `run.batch_dependent` (400, stage `check`).
  fix: `vqapr run <producer> first, then this batch without it`.
- 둘이 같은 `writes`를 선언하면 `run.batch_writes_collide` (400).

왜 순서 정하기가 아니라 거절인가. 이 hazard가 실재하는 순간은 **재실행**이다: 등록 시점에는 reader의
dataset이 있어야 등록되므로(`declaration.run_fed_by_sibling`, 판정 `dataset.unregistered`), reader가
writer와 한 배치에 들어올 수 있는 것은 writer가 이미 한 번 돌아 dataset이 있을 때뿐이고, 그때
`--force`로 writer를 다시 돌리면 reader는 옛 dataset을 읽거나 쓰는 중인 파일을 읽는다. 그래프 순서로
돌려 주는 것은 스케줄러의 일이고(record `201`이 "later"라고 적어 둔 것), 지금 필요한 것은 그 hazard가
조용히 지나가지 않게 하는 문이다.

**`_refusal_envelope`의 잠복 결함 하나.** 존재하지 않는 `as_envelope` 메서드를 찾다가 항상
`{"ok": false, "error": "<str>"}`만 냈다 — 배치 안 거절은 bounded body 없이 문자열이었다. 이제
`cli/envelope.failure(refused, stage=Stage.RUN)`, 단일 run의 거절과 같은 렌더링.

**help와 skill.** `vqapr run --help`와 `--jobs`의 help가 두 종류 모두 펼친다는 것, `jobs`, 의존
배치의 거절을 말한다. `run-backtest/SKILL.md` §5는 없는 `--strategy` 플래그를 아직 적고 있었고
"runs strategies in N processes"라 했다 — 고쳤고 `_shipped.json`을 재기록했다(record `229`와 같은
절차; 이 파일은 `.gitattributes`가 LF를 강제하므로 `write_text` 대신 바이트로 썼다).

### 바뀌지 않은 것

- 순차 경로(`--jobs 1`)는 입력 순서대로 돈다. 의존 판정은 풀에만 있다 — 사용자가 친 순서가 곧
  그래프 순서일 수 있다.
- strategy worker의 실패 entry 모양(`ok:false` + `strategies` 블록, `stage` 없음)은 그대로다. 순차
  경로의 `run.strategy_failed`와 다른 것은 이전부터였고, 이 기록의 범위 밖이다.
- 워커의 롤 개수(`min(jobs, len)`)와 spawn 컨텍스트.

## 검증

```text
uv run ruff check src/                         All checks passed
uv run python -m pyright                        0 errors
tests/flow tests/cli tests/record tests/domain tests/boundaries -m ""   607 passed (slow 포함, 240 s)
tests/agent tests/characterization              114 + 213 passed (skill LF 복원·_shipped.json 재기록 뒤)
refusal-code baseline                           +2 (run.batch_dependent, run.batch_writes_collide), 잃은 것 0
uv run python -m pytest tests/ -q               1671 passed, 29 deselected (282 s)
```

새 테스트 넷이 고정하는 것:

- `test_a_worker_refusal_is_that_runs_entry_and_the_other_run_completes` — worker의 raise가 그 run의
  `VqaprError`(같은 code, stage `run`)이고 옆 run의 record는 남는다.
- `test_a_batch_in_which_one_run_reads_what_another_writes_is_refused_whole` — writer를 돌린 뒤 reader를
  등록하고 둘을 한 배치로: `run.batch_dependent`, spawn 전, reader의 dataset 없음. 독립 배치는 통과.
- `test_jobs_spreads_datamodel_runs_and_refuses_a_batch_that_depends_on_itself` (CLI) — `in_workers`를
  spy로 감싸 두 datamodel id가 **한 호출**로 풀에 들어가는 것; `jobs: 2`; 같은 배치 재실행 시 run마다
  `record.exists` 409(문자열이 아닌 bounded body); writer+reader 배치는 `check` 단계 400에 `runs` 없음;
  그래프 순서로 따로 돌리면 통과.
- `uv run pytest ... -p no:cacheprovider`: `uv run pytest`가 이 셸에서 "uv trampoline failed to
  canonicalize script path"로 죽어 `uv run python -m pytest`로 돌렸다. 환경 문제이지 트리 문제가 아니다.

## 남은 것

- **버전.** develop은 0.11.0으로 stamp된 채고, 이 변경은 0.11.0 wheel 뒤에 온다. 다음 릴리스 번호와
  release note는 오너가 정한다. `_shipped.json`은 0.11.0 아래에 재기록됐다(record `229`의 선례).
- **이슈 번호.** 보고서는 번호 없이 닫았다 — 같은 날 오너가 `095`–`097`을 썼고, 번호는 오너가 붙인다.
- **두 번째 보고**(`agenda.every`의 `y` 단위)는 손대지 않았다.
- strategy worker의 실패 entry를 순차 경로의 `run.strategy_failed` 모양에 맞추는 것.
- 그래프 순서로 배치를 **스케줄**하는 것 — record `201`의 "later". 거절은 그 전까지의 문이다.
