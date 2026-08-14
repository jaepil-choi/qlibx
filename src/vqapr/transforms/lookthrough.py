"""구성종목 데이터 -> 노출 매핑 L.

구현할 것
    보유 종목과 구성종목 데이터로부터 physical -> exposure 매핑 L을 만드는 순수 함수.
    coverage, normalization, cash residual 처리 방식은 **인자로 선언받는다.**

**패키지가 자동으로 켜지 않는다.**
    ETF registration, 보유 수량, constituent dataset이 존재한다는 이유만으로 look-through가
    켜지지 않는다. ETF ticker를 근거로 dataset을 자동 발견하지도, 누락된 구성종목을 추정하지도
    않는다(PRD §8.2).

    이 함수가 built-in으로 있어도 **부르는 것은 StrategyModel이다.** 그래야 mapping, coverage,
    stale/revision 처리, cash residual의 경제적 의미가 그 Model의 것으로 남는다.

L은 목적함수에만 들어간다
    제약은 physical w에만 건다. 노출은 계산값이라 매핑이 바뀌면 과거 판정까지 달라진다
    (architecture §5.3, §11.5).

`UC-LOOKTHROUGH-001` `UC-LOOKTHROUGH-002` `UC-LOOKTHROUGH-003`
"""
