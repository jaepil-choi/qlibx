"""execution time에 델타를 계산한다.

구현할 것
    plan_orders(intent, account, venue, rules) -> OrderBatch

    account   AccountSnapshot — **체결 시점의** committed position/cash
    venue     ExecutionSnapshot — 체결 테이블을 집합 단위로 한 번 조회한 결과
    rules     ExchangeRulesView — listing 규칙

**Protocol이 아니라 함수다.**
    구현이 하나이고 이 층이 닫혀 있다. venue마다 달라지는 것 — 수량 단위, 체결 순서, 현금
    clipping — 은 전부 `exchange/listings.py`와 Exchange 구현 안에 있고, 여기 남는 것은 델타
    산술 하나다. 구현이 하나인데 Protocol을 두면 **없는 확장점을 있는 것처럼 보이게 한다.**

지켜야 할 것
    - decision time의 stale quantity를 **재사용하지 않는다.** 체결 시점의 committed position/
      cash와 그 시각 체결 테이블 행으로 델타를 계산한다.
    - StrategyModel을 재호출하거나 intent를 재계산하지 않는다.
    - **제약을 평가하지 않는다.** 제약 평가는 경제적 판단이라 판단 시점에 있다. 여기로 미루면
      그 시점에 할 수 있는 일이 기록밖에 없다 — 다시 최적화하는 것은 판단을 되돌리는 것이다.
    - `DataRequirement`도 `ModelWindow`도 거치지 않는다. 체결은 창 조회가 아니다.

왜 이것이 우회 불가능한가
    decide()가 반환할 수 있는 것은 PortfolioIntent 하나이고 전략이 Exchange를 볼 수 없으므로
    변환할 재료가 없다. 이 분리는 architecture §2.2의 결과이지 독립된 설계가 아니다.

`UC-EXEC-001` `UC-COST-003` `UC-SCALE-001`
"""
