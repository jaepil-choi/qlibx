# 251 — The strategy scaffold takes a calendar window

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로) |
| **이슈** | `docs/issues/report-2026-09-11-new-help-points-a-strategy-at-calendar-lookback-which-new-strategy-refuses.md` |
| **설계 근거** | `docs/issues/archive/033`(창과 guard가 따로 놀면 조용히 틀린다), 기록 `114`(창 규칙은 `extension/lookback.py`), `233`(행렬 위의 scaffold) |
| **브랜치** | `develop` |
| **앞선 기록** | `114`, `233` |

---

## 왜 이 변경이 있는가

12개월 모멘텀을 scaffold하던 에이전트 셋이 셋 다 `vqapr new strategy mom --dataset p --calendar-lookback 400`을
먼저 쳤고 거절됐다. `vqapr new --help`의 `--lookback` 설명이 "N일 창은 `--calendar-lookback`"이라고 하고,
make-strategy skill의 `reading-inputs.md`도 "`--calendar-lookback DAYS`로 scaffold"라고 한다. 거절은
strategy 템플릿의 guard(`closes.shape[0] < LOOKBACK`)가 행 수를 세기 때문이었다(`033`) — 그러나 그건
템플릿의 사정이지 전략이 calendar 창을 못 읽는 게 아니다. 거절문 스스로 "DatasetInput만 고치면 된다"고 했다.

## 무엇이 어떻게 바뀌었는가

- `extension/scaffold.py`: strategy 템플릿에 창 flavour 둘(`_STRATEGY_FLAVOURS`). `rows`는 지금까지 낸 텍스트
  그대로. `calendar`는 `LOOKBACK_DAYS`·`TIMEZONE`·`va.CalendarLookback(days=..., timezone=...)`와 그 창이
  뜻하는 guard — 이름마다 관측값 둘 이상, 수익률은 창 안의 첫 관측값에서 최신 관측값까지(datamodel
  calendar flavour와 같은 규칙). 행 수를 일 수와 비교하는 줄은 없다.
- `extension/lookback.py`: `--calendar-lookback`을 strategy에도 허용. `--instants-lookback`을 strategy에 주면
  InputError로 거절한다 — 전에는 템플릿의 맨 `ValueError`가 봉투에 `unhandled`로 도착했다.
- `cli/new.py`: `--calendar-lookback` 도움말이 "a datamodel or strategy".

## 바꾸지 않은 것

기본(`--lookback`, 행 6개) strategy scaffold의 텍스트, datamodel scaffold 셋, 두 창을 동시에 주면 거절하는 규칙.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/extension/test_the_scaffold_offers_both_lookbacks.py` | 옛 "strategy는 거절" 테스트를 뒤집음: `--calendar-lookback 400`이 `LOOKBACK_DAYS = 400`·`CalendarLookback`·두-관측 guard를 내고 compile된다; rows 텍스트 그대로; `--instants-lookback` strategy는 InputError, 파일 없음 |
| `tests/extension/test_scaffold_runs_on_real_dtypes.py::test_the_calendar_strategy_scaffold_decides_against_a_float64_column` (신규) | 등록·load 후 float64 parquet 위에서 `decide`가 `Rebalance`를 낸다 (A 100→105, B 50→53) |
| `tests/extension tests/cli/test_commands.py …` | 345 passed, 1 skipped |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |
