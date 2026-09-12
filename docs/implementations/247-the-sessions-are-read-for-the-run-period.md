# 247 — The sessions are read for the run's period, not the table's whole span

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 콜백 캠페인 (`docs/refactoring/2026-09-10-the-one-callback-campaign.md`) |
| **이슈** | 없음 — `experiments/exp_246` 트레이스 |
| **설계 근거** | 기록 `238`(시각 열은 명령당 한 번 읽고 agenda와 horizon이 나눠 쓴다), `docs/issues/archive/069`(agenda는 날짜로 먼저 자른다) |
| **브랜치** | `redesign/one-callback` |
| **앞선 기록** | `238`, `246` |

---

## 왜 이 변경이 있는가

기록 `238`은 집행표의 시각 열을 명령당 **한 번** 읽게 했고, 이슈 069는 그 시각들을 occurrence로 펼치기 **전에**
run의 날짜로 자르게 했다. 남은 것은 그 한 번의 읽기 자체였다: `Workspace.evaluation_times`는 등록 span 전체의
`SELECT DISTINCT available_at`을 읽고 Python이 자른다. 10세션 run이 3년 표의 735 시각을 읽어 10개를 쓴다
(`08_run_factor` #752, `distinct_values` 143 ms — 그 run의 검증 305 ms 중 절반). 10년 · 3,000 종목 표에서는
같은 열이 750만 행이고, 한 해짜리 run이 매번 그것을 다 읽는다.

## 무엇이 어떻게 바뀌었는가

- `scan.distinct_values(spec, field, *, not_before=None, not_after=None)`: 양끝 포함으로 값의 범위를 묶는다.
  경계는 **`TIMESTAMPTZ` 리터럴**로 문장에 들어간다 — 파라미터 바인딩이 아니다. 측정(125만 행, 새 프로세스):
  전체 열 107 ms · 파라미터로 묶기 **590 ms** · 리터럴로 묶기 80 ms(첫 호출); 데워진 뒤 15 · 5 · 6 ms. tz-aware
  datetime을 바인딩하는 첫 문장이 프로세스당 ~450 ms를 낸다. 리터럴은 `astimezone(UTC).isoformat()`이라 숫자 ·
  `T` · `:` · `+`/`-`뿐이고, naive datetime은 `ValueError`로 거절한다(`_instant_literal`).
- `Workspace.evaluation_times(raw_dataset_id, *, between=None)`: memo 키가 `(dataset_id, between)`이 된다. 같은
  범위를 두 번 물으면 한 번 읽는다(기록 238 그대로).
- `preflight._session_bounds(definition)`: run의 `[start, end]`를 **양쪽으로 하루씩** 넓힌 범위. agenda는 venue-local
  날짜가 `[start, end]` 안인 세션을 두고 horizon은 instant가 `(start, end]` 안인 것을 두는데, 하루의 여유는 어느
  시간대에서든 그 날짜가 떨어질 수 있는 instant를 다 덮는다. 두 자르기는 전과 정확히 같은 답을 낸다.
  `derived_agenda`와 `bound_execution_horizon`이 같은 범위로 묻는다 — memo가 맞물린다. start나 end가 없는 run은
  전처럼 표 전체를 읽는다(`None`).

**바꾸지 않은 것.** 잘라진 뒤의 agenda 펼치기(`OperationAgenda.expand`)와 horizon(`ExecutionHorizon.between`).
`Workspace.evaluation_times`를 범위 없이 부르는 호출자는 없지만 시그니처는 남겼다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/data/test_scan.py::test_distinct_values_reads_only_the_bounded_values` (신규) | 묶인 읽기는 범위 안의 값만, 양끝 포함; 범위 없이는 전체 |
| `tests/flow/declaration/test_preflight.py::test_the_sessions_are_read_for_the_run_period_not_the_table` (신규) | judgments + preflight가 `(start − 1일, end + 1일)`로 **한 번** 읽고, agenda의 날짜와 horizon의 instant가 전체 스캔의 답과 같다 |
| `tests/flow/declaration/test_preflight.py` 기존 두 카운트 테스트(기록 238 · 240) | 통과 — 읽기 1회 그대로 |
| `experiments/.../bench_first.py` (프로세스당 첫 호출, 125만 행) | 위 표의 숫자 |
| `uv run ruff check src/` · `uv run python -m pyright` | clean · 0 errors |
