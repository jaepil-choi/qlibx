# 235 — A panel is the run's horizon, and a numeric field is held once

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | one-cube 캠페인 M1 (`.agent/plans/active/one-cube-campaign.md`) |
| **이슈** | `docs/issues/098` — 절반을 닫는다 (나머지 절반은 record `236`) |
| **설계 근거** | 오너 결정 2026-09-10 "근본적으로 메모리를 줄이되 속도를 희생하지 않는다"; 측정 `experiments/exp_236_the_panel_memory/` |
| **브랜치** | `redesign/one-cube` (develop `2c976d11`에서) |
| **앞선 기록** | `232` (a field is one block), `137` (the panel), `228` (`_run_member`) |

---

## 왜 이 변경이 있는가

testbed가 671개 alpha datamodel run을 동시에 돌리다 스왑으로 죽었고, 원인을 재어 보고했다: run 하나의
peak 메모리가 lookback(160일)이나 run 기간이 아니라 **종목 수에 선형**이다 — 309 종목이면 0.32 GB, 기간을
7배로 늘려도 12%만 는다. 보고자는 (a) 창이 아니라 원천 전체 이력을 읽는 것, (b) 값이 Python 객체로 오는 것
둘을 후보로 들었다. 둘 다 맞고, 두 겹이다.

**1겹, 0.11.0.** `store.panel_window`가 `scan.observation_rows`의 **dict 행**을 받아 `Panel.from_rows`로
Python 루프 pivot을 했다. 309 종목 × 2,839 세션 = 877k개 dict가 동시에 살아 있고, 그것이 0.32 GB다.
record `232`가 `observation_table` + numpy pivot으로 바꿔 0.12.0에서 사라졌다. 보고자의 wheel에는 없던
커밋이다. 같은 모양의 합성 원천(4,975 종목, 2,955 세션, 8.0M 행)으로 0.11.0 트리를 재면 309 종목 0.35 GB
대 5 종목 0.14 GB — 보고의 기울기가 그대로 재현된다.

**2겹, develop.** panel이 run과 무관하게 **등록된 span 전체**를 스캔했다(record 137의 "한 번 스캔, 이후는
슬라이스"). 그래서 1년 run과 7년 run의 panel이 같고, 보고자가 청한 "기간을 줄여 메모리를 사는 손잡이"가
없었다. 그리고 숫자 필드 하나를 **두 벌** 들었다: name-major Arrow 배열과, 그것을 transpose해 복사한
numpy 블록(`_blocks`), 그 옆에 validity 마스크. 309 종목 한 필드에 7 MB × 2.

## 무엇이 어떻게 바뀌었는가

```text
data/panel.py     Panel.blocks[field]   숫자 필드: (instants x names) float64 한 벌, NaN = 값 없음
                  Panel.kinds[field]    선언된 Arrow 타입 — INTEGER 필드의 셀은 int로 돌아간다
                  Panel.columns[field]  숫자 아닌 필드만: name-major Arrow, 그대로
                  Panel.bounds          이 panel이 스캔된 (lower, upper); None = 등록 span 전체
                  Panel.window()        bounds 밖의 cutoff, bounds 아래의 calendar bound를 RuntimeError로 거절
                  Panel.cells_at()      (instant, name) 쌍의 셀을 gather 한 번으로 — current/latest가 쓴다
                  from_table()          블록을 instant-major로 바로 쓴다: dense[rows, cols] = values
data/store.py     DuckDbObservationStore(catalog, session=, horizon=(start, end), requirements=)
                  _scan_bounds()        horizon이 있으면 [그 dataset에 선언된 lookback들이 start에서 닿는 가장 이른 instant, end]
                                        (calendar는 lower_bound(start), rows는 instant grid 산술 — 설계 §2.4)
                                        없으면 등록 span (테스트 store, in-process 호출자)
                  panel_identity(...)   등록 span 대신 스캔 bounds가 들어간다
flow/orchestration.py  _run_member가 frozen.start/end와 frozen.requirements를 store에 넘긴다 (_horizon)
```

- **한 dataset에 lookback이 여럿이어도 panel은 하나다.** bounds는 run이 그 dataset에 선언한 모든
  requirement의 최소 하한이라, 두 alias가 같은 identity를 얻고 스캔은 한 번이다(테스트가 센다).
- **잘리지 않고 거절한다.** bounds 밖을 묻는 창은 rows가 없어서 조용히 짧아질 것이므로 `RuntimeError`다.
  확인한 바로 panel 읽기는 전부 occurrence의 evaluation time과 compliance의 market instant, 즉
  `[start, end]` 안에서만 일어나고 finalization은 panel을 읽지 않는다.
- **`values[name]`·`series`의 계약은 그대로다.** 값 없음은 `None`, INTEGER는 `int`, DOUBLE은 `float`.
  블록은 float64 하나지만 셀이 문을 나갈 때 `kinds`로 되돌린다. `matrix()`는 블록 행의 view — 복사 0.
- **RowsLookback의 bound는 원천 instant grid 산술이다.** grid는 종목으로 거르지 않은 superset이라 panel의
  instant보다 넓을 수는 있어도 좁을 수는 없다. 선언 종목 전부가 어떤 세션에 행이 없는 희소한 표에서는
  `start`의 첫 창이 grid 기준 n개 instant 안의 panel instant만 갖는데, 그것이 record 137 표의 ruling("the
  table's last n rows, bounded by arithmetic on the source's instant grid")이다.

**하지 않은 것.** 숫자 아닌 필드(문자열·날짜)는 NaN이 없어 Arrow 경로에 그대로 남는다. `grain: rows`는
공유 instant 축이 없어 panel이 없다. 프로세스끼리 panel을 공유하는 것은 record `236`이다.

## 성능

`experiments/exp_236_the_panel_memory/measure_panel.py`, 309 종목, 160일 CalendarLookback, 필드 1개,
peak working set(프로세스 바닥 0.13 GB 포함):

| | panel이 드는 것 | peak |
|---|---|---|
| 0.11.0 트리, 등록 span | dict 행 877k + name별 Arrow | 0.35 GB |
| record 232 (develop), 등록 span | Arrow 7.4 MB + numpy 7.4 MB + validity | 0.18 GB |
| 이 record, horizon 없음 (등록 span) | 블록 7.3 MB | 0.19 GB |
| 이 record, 7년 run horizon | 블록 5.0 MB | 0.17 GB |
| 이 record, 1년 run horizon | 블록 0.9 MB | 0.13 GB |

panel 빌드 0.5–0.8 s, 2,676개 일별 창 순회 뒤 메모리 증가 0. `matrix()` view, `counts/current/latest`의
벡터화(`tests/flow/test_hot_path_costs.py`)는 그대로다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/data/test_a_panel_is_the_runs_horizon.py` (신규 6) | horizon 스캔 bounds·한 스캔, horizon 없으면 등록 span, bounds 밖 거절, 한 벌 + view, INTEGER는 int, VARCHAR는 Arrow + `matrix()` 거절 |
| `tests/data/test_panel.py` | `test_a_window_shares_the_panels_buffers` → `test_a_window_is_a_view_of_the_panels_block` |
| fast suite | 1691 passed, 29 deselected (1685 → +6) |
| ruff (src) · pyright | clean · 0 |
