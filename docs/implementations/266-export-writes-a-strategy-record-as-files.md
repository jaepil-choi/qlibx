# 266 — `vqapr export`가 strategy record 하나를 파일로 쓴다

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 한 읽기 (`redesign/one-reading`), M3 — 계획 `.agent/plans/active/one-reading-campaign.md` |
| **이슈** | `docs/issues/report-2026-09-11-feature-request-an-export-command-that-writes-a-strategy-record-as-csv.md` |
| **설계 근거** | 오너 판정 2026-09-11 — 만들되 좁게: 조인 없음, `--format parquet` 없음 |
| **브랜치** | `redesign/one-reading` |
| **앞선 기록** | `264`(record의 숫자가 숫자), `265`(주소 하나), analyze-result의 "값은 패키지, 그림은 skill"(PRD §9.4) |

---

## 왜 이 변경이 있는가

incremental testbed의 B 에이전트 셋은 결과를 사용자와 비교 스크립트가 읽을 평범한 파일(일별 NAV, 진입·청산 로그)로
넘겨야 했고, 각자 exporter를 짰다(87 · 136 · 118+176줄). 셋 다 도중에 넘어졌다: `json.dumps`의 튜플 키,
`Decimal += str`, `str < int`, 그리고 B-3은 325,047행의 `vqapr.account` 전체에서 날짜별 마지막 행을 골라 NAV가 NaN이
됐다(NAV는 `_ACCOUNT` 1,721행에만 있다). 다시 짠 로직 — `_ACCOUNT` 행만, 평가 시점마다 하나, 텍스트를 숫자로 — 은
이미 패키지 안, report 속에 있었다(`measure.valuations`·`opening`).

`--help`는 B-3(haiku)을 포함해 모든 에이전트가 읽은 유일한 표면이라, 명령으로 둔다. skill의 "보고용 CLI는 없다"는
그림을 CLI가 그리지 않는다는 뜻이었고, 값을 파일로 넘기는 것은 그림이 아니다.

## 무엇이 어떻게 바뀌었는가

`vqapr export <run-id>/<strategy-id>@<fp8> --out <dir> [--store-root] [--force]` (`cli/export.py`, `cli/main.py`에 등록,
stage는 `new`처럼 `write`):

| 파일 | 내용 | 어디서 |
|---|---|---|
| `nav.csv` | `event_time, date, account_version, cash, nav` — 평가마다 한 행, opening 점 포함 | `report/record.py::valuation_grid` |
| `holdings.csv` | `event_time, date, instrument, quantity, price, value` | 같은 grid의 `positions` |
| `fills.csv` · `weights.csv` · `monitoring.csv` | 패키지 표를 기록된 대로(`monitoring`은 규칙이 있을 때만) | `read_table` |
| `tables/<t>.csv` | 전략이 만든 표마다 — 하위 디렉터리라 저자의 표 이름이 패키지 파일과 부딪힐 수 없다 | `read_table` |
| `report.json` | `strategy_report(...).as_record()` | report |

- `report/record.py::valuation_grid`(신규)와 `strategy_report`가 한 함수 `_opening_grid`를 쓴다. 그래서 `nav.csv`는
  `performance.nav`와 **같은 계열**이다 — 비슷하게 계산한 두 계열이 아니다.
- 숫자는 `format(Decimal, "f")` — 지수 없는 정확한 십진 텍스트, float를 거치지 않는다. 시각은 기록된 zone의 ISO 8601,
  `date`는 그 시각의 현지 날짜.
- 주소는 `show strategy`와 같은 문(`show.resolve_strategy`): bare id는 하나일 때, 여러 record면 이름을 대며 거절.
- `--out`에 이전 export의 파일이 있으면 그 경로들과 `--force`를 말하며 거절한다. 거절은 쓰기 전에 한다.
- report를 만들 수 없는 record(평가 없음)는 `report.json`을 빼고 `omitted`에 이유를 싣는다.
- skill: analyze-result `SKILL.md` — "파일로 넘길 때는 `vqapr export`, exporter를 짜지 말 것".

## 바꾸지 않은 것 · 하지 않은 것

- 전략 표와 체결가의 조인: 과제마다 다른 질문이라 `fills.csv`를 읽는 사용자 코드의 일이다.
- `--format parquet`: store가 이미 parquet이다(`reading-a-record.md`의 경로).
- `vqapr.account` 원본 표는 쓰지 않는다 — 그 행은 grid이고 `nav.csv`·`holdings.csv`가 그것이다.
- 행 순서는 기록된 순서(run의 `sequence`).

## 트레이드오프

`vqapr.account`를 두 번 읽는다(grid 한 번, report 한 번). report가 grid를 내놓게 바꾸면 한 번이지만 `StrategyReport`의
모양이 바뀐다. 명령 하나의 비용이고 run 경로가 아니라서 그대로 두었다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/cli/test_export_writes_a_record_as_files.py` (신규, 둘) | CLI fixture run(세 세션)에서: 파일 다섯; `nav.csv`의 `nav`·`event_time`이 `strategy_report(...).performance.nav`와 점마다 같고 `date`는 현지 날짜; `fills.csv`의 숫자 여섯이 `read_strategy_table`과 같은 `Decimal`, 지수·따옴표 없음; `weights.csv` 숫자; `report.json` = `as_record()`. 두 번째 export는 `nav.csv`와 `--force`를 말하며 거절, `--force`로 통과; `r1`(주소 아님)은 형식을 말하며 거절되고 아무것도 쓰지 않는다 |
| `tests/cli/test_agent_surface.py` | `export`의 요약·설명·cp949 `--help` 통과 |
| `tests/report` (`-m ""`) | 통과(`_opening_grid`로 옮긴 뒤에도 report가 같다) |
| `uv run ruff check`, `uv run python -m pyright` (export · main · report/record) | 통과, 0 errors |
| `uv run python -m pytest tests/ -q` | 1747 통과, 6 skip, 29 deselected (139.3 s) |
