"""invocation 문맥 — 무엇을 볼 수 있는가.

구현할 것
    ModelContext           window, checkpoint()
    DataModelContext       ModelContext 그대로
    StrategyModelContext   + calendar, account(), account_history(), prior_feedback(),
                             constraint_bounds()
    CalendarView           판단 시점의 **성질**을 묻는다 (이번 달 몇 번째 거래일인가 등)

**DataModelContext에 account가 없다. 이 부재가 판정이다.**
    architecture §2.3의 경계를 문서가 아니라 타입이 지킨다. DataModel이 account를 보면 결과가
    그 run에 묶여 재사용할 수 없게 된다.

    두 context를 한 파일에 둔 이유가 이것이다 — 차이가 **한 화면에** 보여야 한다.

Timeline을 주지 않는다
    이벤트 열 전체를 주면 미래 session이 그대로 보인다. CalendarView는 판단 시점의 성질만
    답하고, 미래를 어디까지 노출할지는 열린 결정이다(architecture §15-1).

constraint_bounds()가 무엇인가
    RunDefinition이 선언한 제약을 이 판단 시점에 투영한 결과다. 제약이 요구한 data는 flow가
    PIT로 풀며, **전략이 벤치마크 비중을 직접 읽지 않아도 cap이 적용된다.** 제약이 선언되지
    않은 run에서는 무한 bound가 온다(`UC-CONSTRAINT-001`).

checkpoint()는 두 번째 상태 경로가 아니다
    state 값을 받거나 돌려주지 않고 현재 Model state의 staging 저장만 요청한다. memory와
    recorder는 창에도 context에도 없다 — Model은 self.memory와 self.recorder를 쓴다.

account_history가 memory와 독립인 것이 핵심
    `UC-ACCOUNT-HISTORY-001`은 strategy state 없이 stop-loss가 가능해야 한다고 요구한다.
"""
