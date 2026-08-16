# Execution session 안에서 evaluation time과 execution time을 분리해야 한다

- **Status:** Open
- **Affects:** `docs/vqapr-prd.md` §3.3, §3.4, §3.6, §6.3, acceptance criteria
- **Architecture:** `docs/vqapr-architecture.md` §2.1, §3, §6.2, §8, §12, §16
- **Implementation impact:** 현재 target architecture를 구현하기 전에 문서 결정을 먼저 수정해야 한다.

## 문제

현재 문서는 frozen `ExecutionTable`의 distinct `trade_at`을 정렬해 executable session과
StrategyModel callback 순서를 만든다고 설명한다. 이 표현은 다음 두 의미를 혼동하게 한다.

1. `trade_at`이 run에서 처리할 session의 날짜와 순서를 제공한다.
2. StrategyModel callback도 `trade_at` 시각에 발생한다.

표준 daily-close 시나리오에서 필요한 동작은 2번이 아니다.

```text
2024-03-05 15:30  전일 종가 observation이 available해짐
2024-03-06 04:00  StrategyModel callback과 decision
2024-03-06 15:30  execution
```

StrategyModel은 `2024-03-06 04:00`에 다음 PIT 경계만 사용해야 한다.

```text
available_at <= 2024-03-06 04:00
```

`2024-03-06 15:30`의 execution price와 tradability는 이 callback에서 보이면 안 된다. 해당 값은
execution 시점에 Flow와 Exchange만 읽어야 한다.

PRD §3.1과 §3.6은 event time, availability time, execution time이 다를 수 있다고 이미 요구한다. 반면
PRD §3.4와 §6.3 및 Architecture의 session-loop 설명은 `ExecutionTable`이 callback까지 구동하는 것으로
읽힐 수 있다. 구현자가 `trade_at`을 현재 clock으로 설정한 뒤 StrategyModel을 호출하면 15:30 정보가
decision input에 포함되는 잘못된 구현이 생긴다.

## 필요한 최소 설계 변경

범용 event scheduler, 여러 event-source framework 또는 별도 calendar provider를 새로 만들지 않는다.
현재의 execution-session loop를 유지하고, 각 session 내부의 두 시각을 명시적으로 분리한다.

```text
ExecutionTable
  -> session 날짜와 순서

StrategyModel callback timing
  -> evaluation_time

FillConvention
  -> execution_time
```

Architecture에는 아래와 동등한 작은 값 또는 순수 계산 경계를 둔다.

```python
class SessionTimeline:
    session_date: date
    evaluation_time: datetime
    execution_time: datetime
```

구체적인 class 이름은 normative하지 않다. 필수 의미는 다음과 같다.

- `ExecutionTable.trade_at`은 session anchor와 순서를 제공한다.
- configured StrategyModel의 callback timing은 해당 session의 `evaluation_time`을 제공한다.
- `FillConvention`은 해당 session의 `execution_time`을 제공한다.
- Flow는 한 session 안에서 evaluation을 execution보다 먼저 처리한다.
- StrategyModel의 bounded View는 `available_at <= evaluation_time`으로 해석한다.
- ExecutionTable은 execution 단계에서만 exact-time 조회한다.
- StrategyModel에는 execution row나 미래 session 목록을 노출하지 않는다.

개념적인 Flow는 다음으로 충분하다.

```python
for session in execution_sessions:
    timeline = make_session_timeline(session, strategy_timing, fill_convention)

    result = invoke_strategy(
        session=session,
        evaluation_time=timeline.evaluation_time,
        view=resolve_view(cutoff=timeline.evaluation_time),
    )

    if isinstance(result, PortfolioIntent):
        execute_at(timeline.execution_time, result)
```

## 시간 선언의 authority

`04:00 Asia/Seoul`은 추측하거나 숨은 package default로 정하면 안 된다. configured StrategyModel의
callback timing에 명시하고 frozen invocation identity와 result evidence에 보존해야 한다. 사용자가 preset을
선택할 수는 있지만, resolve된 timezone-aware 시각은 재현 가능해야 한다.

DatasetRegistration에는 이 callback 시간을 넣지 않는다. DatasetRegistration의 `available_at`은 각 row를
실제로 사용할 수 있게 된 시각만 의미한다. 같은 dataset을 04:00 Strategy와 09:00 Strategy가 재사용할 수
있어야 한다.

## 문서 수정 범위

### PRD

- §3.3: callback opportunity의 시각과 StrategyModel 내부 decision cadence를 구분한다.
- §3.4: `trade_at`이 callback 시각을 뜻하지 않고 session anchor와 순서만 제공한다고 명시한다.
- §3.6: 한 session의 evaluation과 execution이 서로 다른 timezone-aware instant임을 명시한다.
- §6.3: `trade_at` 정렬이 session 순서를 정하지만 callback cutoff는 Strategy timing에서 온다고 수정한다.
- 결론, use-case 설명, acceptance criteria에서 “execution table이 callback을 만든다”는 모호한 문구를
  같은 의미로 정렬한다.

### Architecture

- §1 실행 그림에서 ExecutionTable이 StrategyModel callback을 직접 구동하는 것으로 보이는 화살표를 수정한다.
- §2.1 IoC에서 Flow가 session 진행을 소유하되 evaluation time과 execution time을 순서대로 배달한다고 명시한다.
- §3에 session별 timeline 생성과 시간 불변식을 추가한다.
- §6.2에서 ExecutionTable의 책임을 session anchor와 exact execution-state 조회로 제한한다.
- §8 Flow 의사코드와 state machine에서 `SESSION_CALLBACK`의 evaluation time을 명시한다.
- §12 preflight와 §16 acceptance checklist를 아래 조건으로 수정한다.

## Preflight 불변식

현재 daily-session scope에서는 최소한 다음을 검사한다.

```text
evaluation_time < execution_time
previous.execution_time <= next.evaluation_time
```

두 번째 조건이 깨지면 현재의 session-by-session Flow로 시간순 처리를 보장할 수 없으므로 run 시작 전에
실패해야 한다. 더 일반적인 event scheduler를 도입해 우회하지 않는다.

## Acceptance criteria

- [ ] `trade_at=2024-03-06 15:30 Asia/Seoul`인 session에서 Strategy callback은 configured timing에 따라
      `2024-03-06 04:00 Asia/Seoul`에 평가된다.
- [ ] observation row의 timestamp가 정확히 04:00에 존재하지 않아도 callback이 발생한다.
- [ ] callback의 모든 observation read는 `available_at <= 04:00`을 강제한다.
- [ ] `available_at=04:00:00`인 row는 보이고 `available_at=04:00:00.000001`인 row는 보이지 않는다.
- [ ] 15:30 execution price와 tradability는 StrategyModelContext에서 접근할 수 없다.
- [ ] `NoDecision`과 `PortfolioIntent`의 기존 state-commit 의미는 변하지 않는다.
- [ ] 유효한 `PortfolioIntent`만 같은 session의 15:30 execution spine으로 들어간다.
- [ ] 같은 frozen execution input, callback timing, StrategyModel config/state와 registered data가 같은
      callback, state transition과 execution trace를 만든다.
- [ ] preflight가 시간 역행 또는 naive/inconsistent timezone을 account mutation 전에 거부한다.

## 비목표

이 이슈는 다음 capability를 추가하지 않는다.

- execution session이 없는 날짜의 Strategy callback
- 한 session 안의 복수 Strategy callback
- data arrival 자체가 Strategy를 깨우는 callback
- 여러 venue의 독립 event stream 병합
- live wall-clock timer
- 별도 `SessionCalendar` artifact나 calendar provider
- DatasetRegistration의 예상 배치 시각 또는 freshness SLA

위 capability가 필요해질 때만 별도 schedule/event-source 설계를 승인한다. 현재 요구사항은
“각 frozen execution session에서 04:00에 판단하고 15:30에 체결”이며, session별 time 분리만으로 충족한다.

## 구현 중단 조건

PRD와 Architecture가 위 의미로 정렬되기 전에는 다음 구현을 확정하지 않는다.

- `trade_at`을 현재 clock으로 설정한 뒤 StrategyModel을 호출하는 session loop
- execution row를 StrategyModel의 evaluation input으로 전달하는 context
- callback time을 숨은 default로 정하는 runtime
- 이 문제를 해결한다는 이유로 범용 scheduler나 calendar subsystem을 추가하는 변경
