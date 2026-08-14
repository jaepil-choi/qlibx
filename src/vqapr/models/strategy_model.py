"""StrategyModel — 자본을 어떻게 나눌지 판단한다.

구현할 것
    Warmup                sessions: int = 0
    StrategyModel(Model)
        warmup() -> Warmup
        decide(context: StrategyModelContext) -> PortfolioIntent

무엇이 이 역할을 정의하나
    **반드시 execution을 통과한다.** 배분은 체결될 수 있고 체결되면 return이 생기므로, 배분을
    만들고 실행을 건너뛰는 경로는 없다(PRD §2.2).

    zero-friction academic profile을 선택해도 마찬가지다 — 비용이 0일 뿐 체결·계좌 반영·
    feedback은 그대로 일어난다. 그래서 turnover-aware한 전략이 자기 계좌를 볼 수 있다.

반환 타입이 하나뿐이다
    hold도 PortfolioIntent다. 별도 action enum이나 None을 두지 않는다 — "판단 안 함 / 판단해서
    유지 / 주문했는데 dealt 0" 세 가지가 구분되어야 하기 때문이다(PRD §6.7).

왜 Warmup을 명시 선언하나
    "lookback을 못 채우면 알아서 건너뛴다"로 하면 run 중간의 진짜 결측(상장폐지, 데이터 누락)
    까지 조용히 skip된다. **warm-up 구간의 결측은 예상된 것, 그 이후의 결측은 실패** — 이
    구분이 선언으로만 가능하다. run start 기준이며 데이터 시작 시점을 기준으로 삼지 않는다.

    lookback과 같은 수가 아니다. 분기 재무를 RowsLookback(4)로 읽는 전략의 warm-up은 4 session이
    아니라 약 252 session이다.

중첩 run이 없다
    decide() 안에서 다른 run을 실행하지 않는다. 파라미터 후보 비교는 각각을 run으로 돌리고
    결과를 읽어 고르는 체인으로 표현한다(PRD §5.4).

`UC-SIGNAL-001` `UC-ALPHA-PATH-001` `UC-EXTENSION-002`
"""
