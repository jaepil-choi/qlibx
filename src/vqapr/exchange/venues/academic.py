"""Academic venue — 구조적으로 현금 부족이 불가능하다.

구현할 것
    Exchange 계약의 구현
        direction  signed
        quantity   listing별 fractional 허용
        cost       fee/tax/slippage/impact/borrow = 0
        fill       전량
        realism    "hypothetical"

체결 알고리즘
    1. is_tradable 필터
    2. q = w x NAV / P
    3. 끝

    fractional이라 내림이 없고 비용이 0이므로 sum(q_i P_i) = NAV sum(w_i) <= NAV가 정확히
    맞아떨어진다. 잔여도 부족도 없다. **정렬도 누적합도 없다** — 3,000종목이 나눗셈 한 번이다.

미모델링
    borrow · locate · margin · collateral. hypothetical_short의 음수 position은 research 관측을
    위한 committed hypothetical state이며 차입 비용을 모델링하지 않는다(PRD §8.1).

왜 이것이 필요한가
    같은 alpha를 두 profile로 실행해 비교할 수 있어야 하고(`UC-PORTFOLIO-001`), 버킷 조합 팩터와
    signed 직접 실행 팩터가 zero-friction에서 **정확히 일치**해야 검산이 성립한다(§11.1).

`UC-ACADEMIC-001` `UC-PROFILE-001`
"""
