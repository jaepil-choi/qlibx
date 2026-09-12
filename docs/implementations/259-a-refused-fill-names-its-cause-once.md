# 259 — A decision with no fill is refused once, with the repair its cause needs

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로) |
| **이슈** | `docs/issues/report-2026-09-11-a-decide-after-close-run-is-refused-on-every-friday-and-the-second-refusal-points-at-the-run-end.md` |
| **설계 근거** | 한 문(`verify_run`, records `240`–`241`): 같은 질문을 두 곳이 따로 답하면 답이 갈린다 |
| **브랜치** | `develop` |
| **앞선 기록** | `237`(`099`: 체결과 결정 사이의 `end`), `238`(horizon을 명령당 한 번), `240`(`verify_run`) |

---

## 왜 이 변경이 있는가

incremental testbed의 sonnet run이 장 마감 뒤(15:31)에 결정하고 다음 15:30에 체결하는 전략을 기존 momentum run의 fill
블록(`at: "15:30", within: "1d"`)으로 선언했다. `check`가 403개 occurrence를 두 번 거절했다:

- `execution.not_after_decision` (ordering 판정) — "결정을 앞당기거나, run end를 늘리거나, `at`/`after`/`within`을 풀라".
- `execution.target_outside_horizon` (preflight의 freeze) — 같은 403개, "run end를 2024-12-31 뒤로 넓히라".

403개 중 402개는 금요일과 휴장 전날이었다. `within`은 벽시계 시간이라 금요일 15:31의 다음 15:30은 71시간 뒤 월요일이고,
`1d` 안에 없다. run 한가운데의 occurrence이니 어떤 end도 고칠 수 없다 — 두 번째 거절의 처방은 402개에 대해 틀렸다. 남은
하나는 데이터의 마지막 세션이었고, 그것을 고치는 end(마지막 체결과 마지막 결정 사이, record `237`)는 어느 거절도 대지
않았다. 에이전트는 `within: 10d`를 찍고 한 바퀴 더 돈 뒤 스스로 `end: 2024-12-30T15:30:01+09:00`을 찾았다.

쉽게 말하면 창구 둘이 같은 서류를 따로 반려했고, 둘째 창구는 반려 사유를 잘못 적었다. 서류가 모자란 이유는 두
가지(기다릴 수 있는 시간이 짧다 / 끝나는 날이 너무 늦다)였는데, 두 창구 모두 그 둘을 구분하지 않았다.

## 무엇이 어떻게 바뀌었는가

**원인을 한 곳에서 가른다.** `flow/declaration/preflight.py`에 `unresolved_targets()`와 `UnresolvedTargets`:
`select_target`이 묶지 못한 occurrence만 `within`을 뺀 규칙으로 한 번 더 묻는다.

- `waiting` — 규칙이 인정하는 instant가 있지만 `within`보다 멀다. 창의 문제이고, end로는 고쳐지지 않는다.
- `past_end` — run의 end 전에 인정되는 instant가 아예 없다. end(또는 테이블의 끝)의 문제.
- `last_fill` — 풀린 occurrence가 체결되는 가장 늦은 instant(`waiting`은 창을 넓혔을 때 받을 instant로 센다).

**처방도 한 곳에서 쓴다.** `unresolved_target_failures()`가 원인마다 failure 하나를 만들고 각자 자기 occurrence만 싣는다.

- `waiting`: observed가 가장 긴 대기(`2d 23h 59m`, 어느 occurrence가 언제에서 언제까지)를 대고, fix가 "`within`은
  세션이 아니라 벽시계 시간이다 — 주말·휴일이 `1d`를 넘는다"고 말한 뒤 이 run에서 통하는 가장 작은 창(`within: "3d"`,
  문법 단위로 올림)을 댄다. "run end를 늘려도 이것들은 안 풀린다"도 말한다.
- `past_end`: `last_fill + 1s`가 첫 `past_end` 결정보다 앞이면 그 end를 댄다(`end: "2024-12-30T15:30:01+09:00"`,
  record `237`의 end); 아니면 예전 처방(end를 늘리거나, 결정을 앞당기거나, `at`/`after`를 풀라).

두 문(ordering 판정, freeze)이 이 둘을 부르고, code는 각자 그대로다(`execution.not_after_decision` /
`execution.target_outside_horizon`). freeze의 예시는 판정과 같은 모양(occurrence id)이 됐다.

**`check`는 한 번만 말한다.** `cli/check.py`의 preflight 단계가, 판정이 이미 나열한 occurrence 목록과 같은 failure를
freeze의 code로 다시 싣지 않는다. freeze 자체는 판정 없이 freeze하는 호출자(`preflight_run`)를 위해 그대로 증명한다.
`run`은 원래 판정의 거절만 올리므로 바뀌지 않았다.

`within`이 벽시계 시간이라는 말은 `vqapr new run` 템플릿 주석, `project/run.py`·`exchange/conventions.py`의 docstring,
run-backtest skill의 `references/run-declaration.md`(새 절 "When a decision fills")에 들어갔다 — 보고가 지적한 대로
그 전엔 어디에도 없었다.

## 바꾸지 않은 것

`within`의 뜻(벽시계 시간). 세션 수로 세는 창은 다른 기능이고 보고도 요구하지 않았다. 두 code, 거절의 status(412),
`run`의 봉투. 통과하는 run의 비용: 두 번째 질문은 실패한 occurrence에만 한다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/cli/test_a_refused_fill_names_its_cause_once.py` (신규, 셋; 샘플 프로젝트에 15:31 결정·15:30 `within: 1d`·표 끝 뒤의 end) | 각 occurrence가 한 번만; 금요일이 창으로 불리고 `2024-12-20T15:31 → 2024-12-23T15:30`과 `within: "3d"`; 마지막 세션에 `end: "2024-12-30T15:30:01+09:00"` |
| `tests/flow/declaration/test_preflight.py` | freeze의 예시가 occurrence id로, "extend the run end"가 requirement가 아니라 fix에 — 두 줄 갱신 |
| `tests/characterization/check_and_run_envelopes.baseline.json` | 재생성(`VQAPR_REGENERATE_CHECK_BASELINE=1`), 12줄: `check bad-run`·`run bad-run`의 ordering failure가 `past_end`로 분류돼 `observed`에 run end와 첫 결정이, `fix`에 end 처방이 붙었고(그 run은 15:30 결정·15:30 체결이라 `last_fill + 1s`가 결정보다 앞서지 않아 예전 처방), `cause.where`가 공유 builder(`preflight.py (unresolved_target_failures)`)를 가리킨다. 그 시나리오엔 freeze의 되풀이가 없었다 — 의도한 변화만 |
| 영향 받는 테스트(신규, `tests/flow/declaration`, `test_check.py`, `qa/test_check_collects.py`, `test_run_makes_the_judgments_check_makes.py`, `tests/characterization`, `tests/cli/test_new*.py`, `-m ""`) | 재생성 뒤 전부 통과 |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |
| `test_all` (`uv run python -m pytest tests/ -q -m ""`) | 1772 passed, 1 skipped, 268.1 s |
