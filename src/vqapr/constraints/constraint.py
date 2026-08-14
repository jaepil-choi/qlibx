"""Constraint 계약 — 사용자가 구현하는 것.

구현할 것
    Constraint (Protocol)
        constraint_id
        requirements() -> tuple[DataRequirement, ...]   자기가 필요한 PIT data를 스스로 선언
        project(window, instruments) -> Bounds          선언 -> 종목별 상하한
        measure(weights_or_holdings, window) -> ConstraintFinding
    ConstraintSet   위의 모음. RunDefinition이 하나 갖는다
    Bounds          종목별 lower/upper

왜 숫자 벡터가 아니라 정체를 가진 선언인가
    PRD §7.1이 요구하는 것은 "constraint별 measured value, bound, excess, pass/fail, input
    lineage"다. **upper[i] = 0.10을 보고 그것이 어느 제약에서 나왔는지 복원할 수 없다.**
    벡터는 선언의 투영 결과여야 한다.

왜 제약이 스스로 requirement를 선언하나
    single-name cap의 w_index(t)가 time-varying PIT data라 그렇게 될 수밖에 없다. 그리고 그
    data가 없으면 **0으로 추정하지 않고 평가를 실패시킨다**(PRD §7).

왜 RunDefinition이 소유하나
    monitoring은 별도 cadence라 전략이 소유하면 자기 사본을 따로 갖게 되고, 둘이 갈라지면
    `UC-EXEC-003`의 finding이 구성 때 지키려던 것과 대응하지 않는다. 그리고 §7.1이 "생산 검증이
    독립적으로 판정한다"를 요구하는데, 검증자가 전략이 준 bound를 쓰면 독립이 아니다.
"""
