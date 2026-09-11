# 253 — An agenda can fire on the last trading day of a week or month (`on: last`)

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로; 오너가 "`on: last` 추가"를 골랐다) |
| **이슈** | `docs/issues/report-2026-09-11-an-agenda-cannot-fire-on-the-last-trading-day-of-a-month.md` |
| **설계 근거** | design §3.3-3.4(날짜는 데이터에서, 순간은 규칙에서), 기록 `204`(`every`/`at`), `238`(세션 한 번 읽기), `247`(run 기간 ± 1일만 읽기) |
| **브랜치** | `develop` |
| **앞선 기록** | `204`, `238`, `244`, `247` |

---

## 왜 이 변경이 있는가

A/B testbed의 B 조건 에이전트 셋(opus·sonnet·fable)에게 같은 문장 — "매월 마지막 거래일에 모멘텀 상위 30종목을
동일비중으로 보유" — 을 줬더니 셋이 세 가지로 선언했다: 월말 세션 84개를 전략 코드에 하드코딩(`1d`), 다음 달
첫 세션 시가, 다음 달 첫 세션 종가. 체결 시점이 월말 종가 → 익일 시가 → 익일 종가로 움직였고, 최종 지수가
81.8 / 61.6 / 84.4로 벌어졌다 — framework 없는 A 조건(69.3–79.0)보다 넓게. `every`는 주·월의 **첫** 거래일만
말할 수 있었고, 월말은 철자가 없었다.

## 무엇이 어떻게 바뀌었는가

- `domain/agendas.py::AgendaRule`에 `on`(`first` 기본 | `last`). `last`는 `w`·`M`에만 — `d`·`m`·`h`는 속할
  주·월이 없어 이름으로 거절한다. `select_days`가 그룹의 마지막 날을 고르되, **끝났다고 보이는 그룹만**: 뒤에
  다른 그룹의 날이 따르거나, 그 날이 그룹의 마지막 달력일인 경우. 표가 월 중간에서 멈추면 그 달은 발화하지
  않는다 — 마지막이 아닐 수 있는 날에 발화하는 것보다 낫다. `describe()`는 "every 1M on the last trading day at …".
- `OperationAgenda.expand(..., through=)`: 고른 날 중 `through` 이하만 남긴다.
- `project/run.py::RunAgenda.on`. **저장은 `last`일 때만** — `first`는 이전의 모든 run이 뜻한 것이라, 말하지 않은
  run과 `on: first`라고 쓴 run은 같은 선언이고 기존 run의 identity가 그대로다.
- `flow/declaration/preflight.py`: `on: last` run은 세션을 `end` 뒤로 `LAST_DAY_LOOKAHEAD`(45일)까지 읽는다 —
  `end`가 든 달이 끝났는지는 다음 세션이 말하고, 그것은 한 달과 연휴 너머에 있을 수 있다. agenda는 `end` 뒤의
  세션을 **판정에만** 쓰고(`through=end의 날짜`), horizon은 같은 읽기에서 `(start, end]`로 자르므로 `end` 뒤의 무엇도
  run에 들어가지 않는다. 읽기는 여전히 명령당 한 번(`238`).
- 문서: `vqapr new run` 템플릿의 주석 한 줄, run-backtest skill과 `run-declaration.md`, introduce-vqapr의
  "No month-end cadence" 항목 삭제, factor-portfolios의 June-end 항목(측정된 옛 방식의 수치는 그대로 두고
  `on: last` 변형은 **측정되지 않았다**고 적음).

**look-ahead가 아닌 이유.** 거래일은 이미 모든 agenda가 run 전에 실행 표에서 전개한다(`1d`도 그렇다). `last`가
미래에서 묻는 것은 "다음 세션이 다음 달인가"라는 달력 사실이지 가격이 아니다.

## 바꾸지 않은 것

`first`의 동작(시작이 월 중간이면 그 날이 첫 발화), `every`의 문법, 개수 세기(`3M`은 run의 `start`부터).

## 검증

| 검사 | 결과 |
|---|---|
| `tests/domain/test_an_agenda_rule_expands_over_trading_days.py` (신규 셋 + 거절 둘 + describe) | 1월 말 31일(2월 세션이 뒤따름), 주별 금요일들과 2월 2일, 31일 휴장이면 30일; 1월 31일에서 멈춘 표는 1월을 끝냄, 26일에서 멈춘 표는 발화 없음; `through` 컷; `1d`+`last`·`on: middle` 거절 |
| `tests/project/test_run.py::test_on_last_is_stored_only_when_it_is_last` (신규) | `last`만 저장, `on: first`와 생략이 같은 저장형 |
| `tests/flow/declaration/test_preflight.py::test_an_on_last_agenda_reads_past_end_to_know_its_last_month_is_over` (신규) | 실제 workspace: 4월 세션이 3월 29일을 월말로 확정, `end`가 28일이면 발화 없음, agenda+horizon이 세션을 한 번 읽음 |
| `tests/domain tests/project tests/flow/declaration tests/cli tests/qa tests/characterization tests/acceptance` | 645 passed + 위 신규 테스트 수정 후 통과 |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |
