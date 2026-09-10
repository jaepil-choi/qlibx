# 244 — `every`의 거절문이 예시가 아니라 문법을 말한다

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 하나를 닫는 bounded fix (0.14.2 hotfix) |
| **이슈** | `docs/issues/report-2026-09-10-agenda-has-no-year-unit-and-the-refusal-reads-as-a-closed-set` — 닫는다 |
| **설계 근거** | 설계 §3.4(`every`는 count와 unit; `d`·`w`·`M`은 거래일, `m`·`h`는 하루 안의 순간), 기록 `204` |
| **브랜치** | `develop` (0.14.1 stamped 뒤) |
| **앞선 기록** | `204` |

---

## 왜 이 변경이 있는가

enhanced-index testbed(0.11.0 wheel)의 보고. Fama-French 연간 sort는 해마다 6월에 한 번 formation한다.
`every: 1y`를 쓰자 거절문이 *"every must be a count and a unit such as 1d, 1w, 1M, 5m or 1h; got '1y'"*.
그 문장이 문법을 말하는 유일한 자리이므로 보고자는 다섯 예시를 **받아들이는 값의 전부**로 읽었고,
연간 cadence를 선언할 수 없다고 결론지어 스케줄을 모델 안으로 옮겼다(6월이 아니면 `[]`). 그것은
돌아가지만 더 나쁘다 — 선언은 `every: 1M`이라 말하고 `check`는 85회를 펼치고 record는 `sessions: 85`를
적는데, run이 연간임은 component를 열어야 안다. `12M`이 된다는 것은 나중에 다른 질문(분기가 되나)으로
단위를 열거하다가 찾았다.

문법 자체는 문제가 없다: count는 자유(`_EVERY`는 양의 정수 + 단위 한 글자)이고 `12M`은 `select_days`가
매 열두 번째 달의 첫 거래일을 고른다(`firsts[::count]`). 문제는 거절문과, 같은 모양으로 네 값을 나열한
skill 문서다.

## 무엇이 어떻게 바뀌었는가

- `domain/agendas.py::AgendaRule.__post_init__`의 거절문이 **문법**을 말한다: *"every is a count and a unit --
  the count is any positive integer; the unit is d, w or M to select trading days (every Nth trading day, the
  first trading day of every Nth ISO week or Nth calendar month: 2d, 1w, 3M, 12M) or m, h to select instants
  inside each day (5m, 1h); got '1y'"*. 단위가 `y`/`Y`이면 *"; there is no year unit, a yearly cadence is 12M"*
  을 덧붙인다. "count and a unit"이라는 구절은 그대로 두어 이 구절을 match하는 기존 테스트 셋
  (`tests/project/test_run.py`, `tests/test_a_run_is_registered.py`, `tests/exchange`)이 그대로 든다.
- skill 문서 셋이 문법을 말한다: `run-backtest/references/run-declaration.md`(주석 `<count><unit>`; 본문 한
  단락 — count는 자유, 단위 다섯, 연 단위 없음, `3M` 분기·`12M` 연간은 run의 `start`부터 센다),
  `run-backtest/SKILL.md`(`12M` 한 줄), `make-datamodel/references/running-a-datamodel.md`(주석).

**바꾸지 않은 것.** `y` 단위를 받지 않는다. 별칭 하나는 문법에 단위 하나를 더하는 것이고, 보고자가 청한 둘 중
작은 쪽(문장을 고치는 것)이 `2w`·`5d`가 안 보이던 것까지 고친다. `1y`를 받는 것은 hotfix가 아니라 표면 변경이다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/domain/test_an_agenda_rule_expands_over_trading_days.py::test_a_rule_whose_halves_disagree_is_refused_by_name` (파라미터 둘 추가) | `1y` → "a yearly cadence is 12M"; `1Y` → 문법 문장("any positive integer.*d, w or M.*12M") |
| `tests/domain` · `tests/project/test_run.py` · `tests/test_a_run_is_registered.py` · `tests/exchange` | 통과 (0.14.2 노트의 `test_all`에 포함) |
| `ruff check src/` · `pyright` | clean · 0 errors |
