# 274 — run 하나의 일생은 출발 전 · 고리 · 조립이다: `flow/`는 `run/`

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 개념 트리 (`redesign/concept-tree`), M7 — 계획 `.agent/plans/active/concept-tree-campaign.md` |
| **설계 근거** | `docs/vqapr-architecture.md` §10 · §13 · §17, 오너 결정 (2026-09-11: 새로 지은 이름 `run/preflight/verdict.py` · `run/assemble.py` · `run/batch.py` · `run/recording.py` 승인) |
| **브랜치** | `redesign/concept-tree` |
| **앞선 기록** | `273`(workspace) |

---

## 왜 이 변경이 있는가

`flow/`에는 높이가 셋 있었다. 그런데 이름은 그 셋을 말하지 않았고, 옮겨 온 역사를 말했다.

- `flow/declaration/`: 선언을 판정하고 얼리는 출발 전 단계. 그런데 선언 문서는 이제 `workspace/`에 있다.
- `flow/run/`: 고리와 그 단계들. `flow` 안의 `run`이 루프만 가리켰으니, "run"이 run 하나의 일생 전체인지 루프
  하나인지 이름으로는 알 수 없었다.
- `flow/engine/`: 단계들이 같이 쓰는 바닥(사건 · 증거 · 받아들여진 상태).
- 뿌리의 `orchestration.py`(1,300줄): run 하나를 조립하는 일과 `--jobs` 기계(worker · BLAS · cube)를 한 파일에
  담았다.
- `engine/artifacts.py`: 단계가 남기는 증거 값과 run이 실패하는 방식을 한 파일에 담았다.
- 단계 파일 `callback.py` · `valuation.py`의 이름은 기제를 말했다. 그 단계가 부르는 컴포넌트의 메서드를 말하지 않았다.

## 무엇이 어떻게 바뀌었는가

| 새 자리 | 무엇이 들어왔나 |
|---|---|
| `run/preflight/facts.py` | `RunFacts`와 그 유도(일정 · 묶인 체결표 · horizon), 풀리지 않는 체결 목표 (`preflight.py`에서) |
| `run/preflight/checks.py` | `judgments.py` + `declaration/roster.py` (`vqapr check`가 모아 보이는 판정들) |
| `run/preflight/freeze.py` | `preflight.py`의 나머지: 얼리는 절차와 그것이 내는 거절 (`preflight_run`) |
| `run/preflight/frozen.py` | `declaration/frozen.py` (얼린 값) |
| `run/preflight/verdict.py` | `declaration/verify.py` (판정 + 얼리기의 한 문, `verify_run`) |
| `run/engine/loop.py` · `events.py` | `flow/run/loop.py` · `flow/engine/loop.py` |
| `run/engine/context.py` · `run_state.py` · `calls.py` · `output.py` | 같은 이름으로 |
| `run/engine/evidence.py` · `failure.py` | `engine/artifacts.py`를 둘로: 증거 값 여덟, 그리고 `SimulationFailure`와 그 종류 |
| `run/engine/stages/` | `callback` → `decide`, `compute`, `accrual` → `accrue`, `execution` → `execute`, `valuation` → `value`, `compliance` → `observe` |
| `run/assemble.py` · `batch.py` | `orchestration.py`를 둘로: run 하나의 조립과 발행, 그리고 `--jobs` |
| `run/recording.py` · `roster.py` | `flow/freeze.py` · `flow/roster.py` |

- **층 표.** `run.preflight` 60 < `run.engine` 65 < `run` 70. 옛 표에서는 `engine`이 `declaration`보다 낮았다.
  이제는 출발 전이 고리보다 낮다. 고리는 얼린 값을 import하고, 출발 전은 고리의 어떤 것도 import하지 않는다.
  최종 번호는 M10에서 정한다.
- **함수 이름은 그대로다.** `verify_run` → `preflight`, `preflight_run` → `freeze`는 목표 설계의 이름이다. 하지만
  `vqapr.public.preflight_run`이 저자에게 보이므로, 어휘를 바꾸는 릴리스(M11)로 미뤘다.
- **characterization 기준선.** 거절이 난 자리를 적은 `where`를 새 경로로 옮겼다. `bound_execution_table`과
  `unresolved_target_failures`는 `facts.py`, `_refuse_taken_output`은 `freeze.py`, 판정은 `checks.py`에 있다.
- **테스트 미러.** `tests/flow/declaration` → `tests/run/preflight`, `tests/flow/run` → `tests/run/engine`,
  `tests/flow` → `tests/run`. 깊이가 같아서 `__file__` 기준 경로는 그대로다. 옮긴 모듈의 이름을 문자열로 적은
  테스트도 새 경로로 바꿨다(몇 번째 frame의 모듈 이름을 세는 테스트, 소스를 읽는 테스트, monkeypatch 대상).

## 목표 문서와 다르게 둔 것 (발견)

- **`events.py`는 `loop.py`와 따로 둔다.** 실행 문맥(`context.py`)이 `MarketEvent`를 들고 다니고, `loop.py`가
  문맥을 import한다. 한 모듈에 두면 순환이 생긴다. 목표 대응표의 `loop(+events)`는 record `271`의 compliance 값과 같은
  종류의 잠복 순환이었다.
- **`frozen.py`는 `freeze.py`와 따로 둔다.** 엔진이 import하는 것은 값뿐이다. 절차와 합치면 1,100줄이 넘고, 값을
  읽는 엔진이 컴포넌트 적재와 workspace까지 끌어온다.
- **풀리지 않는 체결 목표는 `facts.py`에 둔다.** check와 freeze가 같은 답을 묻는다. 둘이 같이 쓰는 답은 아래
  모듈에 두어야 `freeze → checks` 간선이 생기지 않는다.
- **`ROSTER_ABSENT`가 두 모듈에 똑같이 정의되어 있었다**(`"roster.absent"`). 한 모듈로 합치면서 하나만 남겼다.

## 검증

| 검사 | 결과 |
|---|---|
| `uv run python -m pytest tests/ -q -m ""` (test_all) | 1795 통과 · 1 실패 · 5 skip (217 s). 실패는 테스트 자신의 모듈 별칭이었다(`monkeypatch.setattr(orchestration, ...)`, 옮긴 뒤 `run_batch`). 고친 뒤 그 파일을 다시 돌려 6개 모두 통과 |
| `scripts/showcase_record_digest.py --check <campaign-digest.json>` | 81개 모두 일치 (캠페인 기준선) |
| `uv run ruff check src/` | 통과 |
| `uv run pyright` | 0 errors, 0 warnings |
