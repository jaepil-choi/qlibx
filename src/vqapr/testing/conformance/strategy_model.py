"""StrategyModel 계약 검사.

검사할 것
    `decide()`가 **PortfolioIntent만** 반환한다
    hold가 완전한 target으로 온다 (None도 별도 enum도 아니다)
    warm-up 선언이 지켜진다 — 그 구간 candidate가 DECISION_SKIPPED로 기록된다
    account를 읽어도 되지만 mutable Account에는 닿지 않는다
    체결 테이블에 도달하는 경로가 없다
    다른 run을 실행하지 않는다
    선언한 requirement 밖의 데이터를 읽지 않는다
    같은 frozen input에서 같은 intent (state를 쓰면 state 복원 후에도 같은 다음 결과)

왜 hold를 검사하나
    "판단 안 함 / 판단해서 유지 / 주문했는데 dealt 0" 세 가지가 구분되어야 하고, 가짜 hold
    (current target 반복 제출로 price-drift rebalance 유발)는 PRD §12.5 금지 항목이다.
"""
