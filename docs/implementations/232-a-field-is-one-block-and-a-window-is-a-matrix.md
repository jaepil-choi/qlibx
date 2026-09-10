# 232 — A field is one block, and a window is a matrix

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | one-door 캠페인 P1 (`.agent/plans/active/one-door-campaign.md`) |
| **이슈** | `docs/issues/096` — panel 읽기가 종목 순회 Python 루프다 (P2 `233`이 닫는다) |
| **설계 근거** | `docs/design/the-panel-the-surface-and-the-run.md` §2.3 · §2.5 · 기록 `137` · 오너 지적 2026-09-10 "5일 close lookback 받은 2d panel을 가지고 axis=0 으로 …" |
| **브랜치** | `redesign/one-door` |
| **앞선 기록** | `231` (The walk is the loop's own) |

---

## 왜 이 변경이 있는가

`Panel`은 종목마다 Arrow 배열 하나를 들었다(`columns[field][instrument]`). 2D 접근자가 없으니
`PanelWindow`의 모든 접근자 — `values[name]` · `counts()` · `current()` · `latest()` — 가 종목을
Python으로 순회했고, 그중 `counts()`는 프레임워크 자신이 **매 읽기마다** 부른다(access 기록). sample
전략과 scaffold가 종목 for loop을 도는 것은 그 API를 그대로 따른 것이다. 3,000종목 측정
(`experiments/exp_231_the_panel_read_cost/bench.py`, 기록 전): sample decide 8.8 ms, `counts()` 3.1 ms,
`current()` 3.6 ms — 콜백마다 12 ms의 Python 루프, 분봉이면 하루 4.7 s. 판을 만드는 쪽도 같았다:
`observation_rows`가 duckdb에서 열로 받은 것을 dict 행으로 다시 만들고 `Panel.from_rows`가 그 행을
Python으로 피벗했다(10 × 735행에 425 ms, 트레이스 `06 #9480`).

## 무엇이 어떻게 바뀌었는가

```text
data/scan.py        _observation_query(...)  -> _ObservationQuery     문장 하나 (창 술어는 여기만)
                    observation_rows(...)    -> dict 행                 rows(alias) 읽기 (그대로)
                    observation_table(...)   -> pa.Table               panel 읽기: 같은 문장, 열로

data/panel.py       Panel.columns[field]     필드마다 Arrow 배열 하나, name-major (index = j*T + t)
                    Panel.from_table(table)  열에서 피벗: 행마다 정수 하나(j*T + t)를 한 번에 계산, fancy-index 대입
                    Panel.column(field, name) 그 이름의 이력 = slice (buffer 공유)
                    Panel.block(field)       (T × N) float64, NaN — 숫자 필드만, 필드당 한 번 만들어 둔다
                    Panel.validity(field)    (T × N) bool — 모든 타입
                    PanelWindow.matrix()     block[start:stop] — 뷰
                    counts / current / latest   validity 위의 벡터 연산 + Arrow take 한 번
                    values[name] / series    그대로 (한 열만 변환, 061)

data/store.py       panel_window: observation_table → Panel.from_table
pyproject           numpy 선언 (pyarrow가 이미 요구하던 것을 이름으로)
```

- 정수 필드는 float 경로로 피벗한 뒤 원래 타입으로 cast한다 — `values[name]`이 여전히 int를 준다.
  문자열·시각 필드는 object 경로(값 목록 한 번 변환)로 같은 배치에 들어가고 `matrix()`는 이름을 대며
  거절한다.
- `current()`·`latest()`는 validity에서 (이름, 시각) 쌍을 고르고 필드 배열에 `take` 한 번으로 셀을
  꺼낸다. 이름당 `as_py()`가 없다.
- `PanelWindow.values`·`series`·`_cells`·`_values` 캐시는 그대로다. 기존 테스트(`tests/data/test_panel.py`)는
  `window.panel.columns["close"]["A"]`를 `window.panel.column("close", "A")`로 바꾼 것 하나뿐이다.

## 성능 (`exp_231`, 3,000 × 6, best of 3)

| | 기록 전 | 기록 후 |
|---|---:|---:|
| 판 만들기 (한 run에 한 번) | 10.7 ms (행 피벗) | 1.2 ms |
| sample decide, 종목 루프 + Decimal | 8.8 ms | 12.3 ms (같은 코드 — 이 기록은 API를 바꾸지 않았다) |
| 같은 결정을 `matrix()` 위에서 | — | 1.5 ms |
| `counts()` (매 읽기) | 3.1 ms | 0.2 ms |
| `current()` | 3.6 ms | 0.3 ms |
| `latest()` | — | 0.8 ms |

sample 자체가 `matrix()`로 옮겨 가는 것은 기록 `233`이다.

**하지 않은 것.** `values`를 없애는 것 — 이름 하나의 시계열을 묻는 모델이 있다. Arrow 대신 numpy로
저장하는 것 — 문자열·시각 필드가 있고, Arrow 슬라이스가 버퍼를 공유한다. 판의 identity·캐시 규칙은
그대로다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/data` (panel · scan · windows) | 111 passed (`test_panel.py`의 buffer 공유 검사는 `panel.column()`으로, one-scan 검사는 `observation_table`을 센다) |
| P1이 닿는 영역 (`tests/flow tests/boundaries tests/models tests/acceptance tests/qa tests/data`) | 517 passed |
| 가드 `test_a_panel_read_makes_no_python_step_per_name` | 3,000종목 창 하나: `counts`·`current`·`latest`·`matrix`에 `Panel.column` 호출 0, `values[name]`에 1 |
| digest | 83/83 (계산되는 수는 그대로) |
| pyright (src) | 0 |
