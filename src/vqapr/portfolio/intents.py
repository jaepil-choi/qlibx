"""PortfolioIntent — 동결된 의도, 그리고 만들 때 검증한다.

구현할 것
    BudgetSemantics   선언된 현금 범위 + direction
    PortfolioTarget   weight **또는** quantity 중 정확히 하나
    PortfolioIntent   intent_id, strategy_id, decision_time, effective_after, targets,
                      cash_target, budget, source_refs, account_version_seen, model_state_ref
    PortfolioIntent.from_weights(...)   **유일한 정당한 생성 경로**

왜 조립과 검증이 한 파일인가
    검증이 여기 있고 생성이 다른 파일에 있으면 둘이 갈라진다. "만드는 길이 하나고 그 길이
    검증한다"가 한 화면에서 보여야 한다.

생성 시 검증 — 계산한 쪽을 믿지 않는다
    sum w + cash_target = 1        예산 항등식
    l <= w <= u                    선언된 상하한
    c_lo <= cash <= c_hi           선언된 현금 범위
    w_j = w0_j (j in frozen)       거래 불가 종목 불변
    tz-aware 시각 · 유일 instrument · 유한 값 · lineage · profile direction 호환
    선언된 constraint 재평가        `constraints/evaluation.py`를 부른다

    왜 optimize가 이미 제약을 넣었는데 또 검사하나 — solver가 수치적으로 살짝 벗어날 수 있고,
    optimize를 쓰지 않고 직접 target을 만드는 StrategyModel도 있고, 전략에 버그가 있을 수 있다.
    **authority가 주입물을 신뢰하면 authority가 아니다.**

    어기면 PortfolioIntent를 만들지 않는다. 그러면 주문도 account mutation도 생기지 않는다.

cash_target은 유도하지 않는다
    `1 - sum w`로 계산되는 값이 아니라 optimize가 결정한 값이다. **의도된 현금 포지션**과
    **배분하지 못한 잔여**는 선언한 현금 범위의 폭으로 구분된다(PRD §5.5).

weight target과 quantity target은 가격 변동에 대한 성질이 다르다
    weight target은 체결 시점 NAV에 적용되므로 갭이 상쇄되고, quantity target은 수량을 고정하므로
    갭 노출이 남는다. 결함이 아니라 그 target의 의미다.

fractional/lot 검증은 하지 않는다
    그건 venue가 안다(`exchange/listings.py`).

`UC-ALPHA-BUDGET-001` `UC-CONSTRAINT-002`
"""
