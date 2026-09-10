# 227 — One loop walks both kinds of run

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 루프 캠페인 L3 (`docs/refactoring/2026-09-10-the-one-loop-campaign.md`) |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §3 (시계는 둘) · §4.3 (부품과 도구) · 기록 `214` "무엇을 잃었나" |
| **브랜치** | `redesign/one-loop` |
| **앞선 기록** | `226` (A market-clock instant is a fold) |

---

## 왜 이 변경이 있는가

기록 `214`가 남긴 빚이다: *"루프 클래스를 하나로 만들지 않았다. `StrategyEventLoop`는
`RunStateRepository`+`FlowContext` 위에, `DataModelEventLoop`는 `RunOutput` 위에 서 있고, 둘을 한
클래스로 접으려면 datamodel run도 accepted state 루트를 갖거나 strategy run의 발행이 창고 문을
지나야 한다. 그것은 척추 변경이다."*

척추를 바꾸지 않고 접는 길이 있었다. **루프가 수신자 위에 서지 않으면 된다.** 두 루프가 서로 달랐던
것은 넷뿐이다 — `start`(visible state 적재 / 창고 문 열기), `dispatch`(`decide` / `compute`),
`finish`(root 확정 / `DataModelResult`), 그리고 시장 시계의 유무. 앞의 셋은 **부품**(설계 §4.3, 자기
시계를 선언하는 것)이 소유하는 것이고, 넷째는 도구들이 붙는 시계다. 루프가 알아야 하는 것은 그 둘의
모양뿐이다.

## 무엇이 어떻게 바뀌었는가 — `flow/run/loop.py`

```text
RunLoop[TraceT, ResultT](EventLoop)        루프 하나.  events = 부품의 agenda ∪ 시장 시계의 점
    start(cutoff)   -> part.start
    handle(event)   -> market.at(event)  |  part.dispatch(occurrence)
    finish(traces)  -> part.finish(traces, elapsed=…)

Part[TraceT, ResultT]  (Protocol)          start · dispatch · finish — 부품의 세 문
    StrategyPart      callback.dispatch, root 확정, timing
    DataModelPart     compute.dispatch, 창고 문 열고 DataModelResult

MarketClock                                시장 시계: instants() (horizon, 게으르게) · at(event) (기록 226의 fold)

StrategyEventLoop(RunLoop)                 조립만: 권한 검사, FlowContext, handler 다섯, MarketClock
DataModelEventLoop(RunLoop)                조립만: ComputeHandler, DataModelPart, 시장 시계 없음
```

- `RunLoop`는 `RunStateRepository`도 `RunOutput`도 `Account`도 import하지 않는다. 그것들은 부품과
  도구의 것이다. 두 kind의 차이는 **생성자에서 무엇을 조립했는가**로만 남는다.
- `StrategyEventLoop`·`DataModelEventLoop`의 생성자 시그니처는 그대로다. 일곱 테스트 파일과
  `orchestration.py`가 그것을 쓰고, 권한 검사(`layer`가 run의 것인가, 초기 계좌가 일치하는가,
  component memory가 정확히 로드된 것들의 것인가)는 조립의 일이 맞다.
- `_handle_market` → `MarketClock.at`. AC-8(`tests/boundaries/test_a_market_instant_keeps_the_stage_order.py`)과
  배선표 테스트(`tests/domain/test_the_wiring_table.py`)가 그 소스를 읽는다 — 이름만 바꿨다.
- `timing.total`은 `RunLoop.start`에서 잰 시각으로 `finish`에 `elapsed`로 건네진다. 전에는
  `StrategyEventLoop.run()`의 override였다. 범위는 같다(`start`부터 `finish`까지).

**하지 않은 것.** 표가 루프를 구동하는 dispatcher(기록 `213`·캠페인 문서 §2). datamodel run에 journal을
주는 것(`214`가 그은 척추). `Part`를 `authoring.Part`와 합치는 것 — 저자 계약의 `Part`는 "자기 시계를
선언하는 Component"이고 여기의 `Part`는 "루프가 부르는 부품의 handler"다. 같은 이름이 두 층에 있는
것은 배선표의 부품/도구 구분이 run 층에서 그대로 보이게 하려는 것이며, 둘은 서로 import하지 않는다.

## 성능

바뀌지 않아야 한다: 루프가 더하는 것은 이벤트마다 메서드 호출 하나(하루 403번)이고 종목마다 하는 일은 없다.
exp_221 세 번: 48.1 s · 46.7 s · 34.3 s. 앞의 둘은 build 단계(테이블 생성)조차 평소의 두 배(2.5 s)로
나온 세션이라 머신이 느렸던 때이고(L2 직후 같은 코드 경로가 34.7 s), 셋째는 build 1.4 s의 세션이다.

## 검증

```text
uv run ruff check src/                 All checks passed
uv run pyright                          0 errors
uv run pytest tests/ -q                 1648 passed, 4 skipped
showcase digest                         81/81
```
