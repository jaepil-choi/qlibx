# 246 — A callback frames what it read once, and asks its declaration once per run

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 콜백 캠페인 (`docs/refactoring/2026-09-10-the-one-callback-campaign.md`) |
| **이슈** | 없음 — 0.14.2 시나리오 stepper의 트레이스(`experiments/exp_246_the_scenario_trace_0_14_2/`)를 중복으로 읽은 결과 |
| **설계 근거** | 기록 `240`·`241`(선언 쪽의 "사실 하나", `RunFacts`), `239`(콜백의 memory를 한 번 프레이밍), `125`(의도서의 다섯 필드는 Flow가 찍는다) |
| **브랜치** | `redesign/one-callback` (develop 0.14.2 위) |
| **앞선 기록** | `239`, `242` |

---

## 왜 이 변경이 있는가

0.14.2 트레이스를 이야기가 아니라 중복으로 다시 세자 콜백 하나가 같은 것을 두 번 만들고 있었다.

- `CallbackHandler._actual_source_refs(window)` — 창이 실제로 읽은 source와 그 digest의 튜플 — 이
  콜백마다 **두 번** 불렸다: 의도서에 도장을 찍을 때(`_stamp_intent`)와 증거를 만들 때(`_callback_evidence`).
  같은 창, 같은 accesses, 같은 튜플이다. factor run(10 결정) 20회, stop-loss run(37 결정) 71회
  (`08_run_factor`, `10_run_stoploss`).
- `strategy.inputs()` — 저자의 읽기 선언 — 이 **매 decide마다** 다시 불렸다(`StrategyModelContext(reads=...)`).
  검증·시작에서 다섯 번 묻는 것에 더해 결정마다 한 번: factor run 15회, stop-loss run 42회. 선언은 계약상 한 번
  정해지는 값이고, DataModel 쪽의 `ComputeHandler`는 이미 조립 때 한 번만 묻고 있었다(`compute.py`).

둘 다 기록 `240`이 선언 쪽에 세운 원칙 — 한 사실은 한 번 읽고 나눠 쓴다 — 이 루프 안에는 아직 없던 자리다.

## 무엇이 어떻게 바뀌었는가

- `CallbackHandler.__init__`이 `strategy.inputs()`를 **한 번** 풀어 `self._reads`로 들고, 매 dispatch의
  `StrategyModelContext`에 그것을 준다. `ComputeHandler`와 같은 모양.
- `dispatch`가 `decide` 뒤(창이 읽힌 뒤)에 `source_refs = self._callback_actual_source_refs(occurrence, window)`를
  **한 번** 만들고 `_stamp_intent(..., source_refs)`와 `_callback_evidence(..., source_refs)`에 넘긴다. 두 메서드는
  더 이상 창에서 스스로 도출하지 않는다.
- `_stamp_intent`의 시그니처가 `window` 대신 `source_refs`를 받는다. 봉투·record·의도서의 값은 같다(같은 튜플).

**바꾸지 않은 것.** `_actual_source_refs`의 검사(창이 FrozenRun에 없는 dataset을 읽었나, 한 source에 두 digest가
보였나)는 그대로 그 한 번의 호출 안에서 한다. 검증·시작 단계의 `inputs()` 다섯 번(`load` ×2 · 판정 · freeze ·
run 시작의 `Component.requirements`)은 각각 다른 물음(계약 검사 · 요구 목록 · 기록)이라 두었다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/flow/run/test_session_callbacks.py::test_a_callback_frames_what_it_read_once` (신규) | Hold 두 번의 흐름에서 `_actual_source_refs` 콜백당 1회, `inputs()` run당 1회 |
| `tests/flow/declaration/test_preflight.py::test_a_run_frames_what_each_callback_read_once` (신규) | 실제 run(Rebalance 경로)에서 콜백당 1회 · run당 1회, 결과 ok |
| 트레이스 재측정 (`experiments/exp_246`, 같은 sample door, `--force`) | `_actual_source_refs` factor 20 → 10 · stop-loss 71 → 37; `inputs` 15 → 6 · 42 → 6; 호출 수 27,853 → 25,913 · 68,066 → 63,021 |
| `tests/flow` · `tests/characterization` · `tests/cli/test_check.py` | 통과 (봉투 baseline 바이트 동일) |
| `uv run ruff check src/` · `uv run python -m pyright` | clean · 0 errors |
