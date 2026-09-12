# 231 — The walk is the loop's own, and the assemblies are functions

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | one-door 캠페인 L (`.agent/plans/active/one-door-campaign.md`) |
| **이슈** | `docs/issues/097` — 추상 루프에 서브클래스가 하나뿐 |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §3 · 기록 `227` · 오너 판정 2026-09-10 "OOP를 위한 OOP는 overengineering이야" |
| **브랜치** | `redesign/one-door` |
| **앞선 기록** | `230` (--jobs spreads datamodel runs) · `227` (One loop walks both kinds of run) |

---

## 왜 이 변경이 있는가

오너가 0.11.0 척추 트레이스를 읽다가 물었다: *"flow/run/loop 랑 flow/engine/loop 는 또 무슨
차이야?"* 답은 "하나는 추상 걷기, 다른 하나는 그 유일한 구현"이었고, 그 답이 곧 결함이다.
`flow/engine/loop.py`의 `EventLoop`는 루프가 둘일 때(기록 `182`) 걷기를 나눠 쓰려고 만든 추상층인데,
기록 `227`이 두 루프를 `RunLoop` 하나로 접은 뒤로 서브클래스가 `RunLoop` 하나뿐이었다. 그 옆의
`StrategyEventLoop`·`DataModelEventLoop`는 `__init__`만 있는 클래스 — 타입으로 쓴 factory였다.
읽는 사람은 루프 하나를 이해하려고 클래스 셋과 파일 둘을 만난다.

## 무엇이 어떻게 바뀌었는가

```text
flow/engine/loop.py     Event · OccurrenceEvent · MarketEvent와 정렬 규칙만 (같은 시각이면 시장이 먼저)
                        EventLoop 삭제

flow/run/loop.py        RunLoop[TraceT, ResultT]        루프 하나. run()이 걷기다:
                            run()      start → sorted(events) → handle 하나씩 → finish
                            part       부품 (테스트가 fault를 넣을 때 여기로)
                        strategy_loop(...) -> RunLoop   조립: 권한 검사 · FlowContext · handler 다섯 · MarketClock
                        datamodel_loop(...) -> RunLoop  조립: ComputeHandler · DataModelPart · 시장 시계 없음
                        StrategyPart.callback           공개 이름 (전엔 StrategyEventLoop._callback)
```

- `RunLoop.run`은 `EventLoop.run`을 글자 그대로 옮긴 것이다: `on_progress`는 이벤트마다 `handle`
  **앞에서** 불린다(`tests/record/test_run_records.py`가 그 소스를 읽는다).
- 조립 함수 둘의 시그니처는 옛 생성자와 같다. `orchestration.py`의 두 호출과 테스트 13파일은 이름만
  바꿨다. 정렬 규칙(`MarketEvent.sort_key`의 `-1`)은 이벤트의 사실이라 `engine/loop.py`에 남는다.
- `StrategyEventLoop._callback`을 읽던 테스트(`tests/acceptance/test_time_002.py`)는
  `flow.part.callback`으로 읽는다. 비공개 속성을 뒤에서 잡는 대신 부품이 자기 handler를 공개한다.

**하지 않은 것.** `engine/loop.py`를 `run/`으로 옮기는 것 — `engine/`은 층 60(artifacts · run_state)이고
이벤트는 그 층의 것이 맞다. `Part` Protocol을 없애는 것 — 부품이 둘(`StrategyPart` · `DataModelPart`)이라
Protocol이 하는 일이 있다.

## 검증

- `tests/flow tests/record tests/boundaries tests/domain tests/acceptance/test_time_002.py`: 아래 표.
- `grep -rn "class .*EventLoop" src/` — 없음. `tests/boundaries/test_the_layers_hold.py` `OPEN = {}` 그대로.
- pyright 0, ruff: 바뀐 파일에서 HEAD 대비 새 finding 0.
- 계산되는 수는 바뀌지 않았다: showcase digest 83/83.

| 검사 | 결과 |
|---|---|
| L이 닿는 테스트 (`tests/flow tests/record tests/boundaries tests/domain tests/acceptance/test_time_002.py`) | 378 passed (한 테스트는 `flow._context.account`를 잡고 있었다 → `Account.append`를 seam으로) |
| fast suite (`tests -q`) | 1671 passed, 29 deselected |
| digest | 83/83 |
| pyright (src) | 0 errors |
