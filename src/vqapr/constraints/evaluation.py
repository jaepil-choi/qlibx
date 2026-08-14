"""weights 또는 holdings -> 제약별 finding.

구현할 것
    measure_all(constraints, weights_or_holdings, window) -> ConstraintReport

**생산 검증과 monitoring이 같은 이 함수를 부른다.**

    measure_all(constraints, intended_weights, window)   `portfolio/intents.py`의 생성 시 검증
    measure_all(constraints, actual_holdings,  window)   monitoring

    다르면 "판단 시점엔 통과했는데 monitoring은 위반이라 한다"가 제약 해석 차이인지 진짜
    위반인지 구분되지 않는다. 같은 함수면 차이의 원인이 **입력뿐**이고,
    `UC-CONSTRAINT-ADJUST-001`이 말하는 정수 변환 오차가 정확히 그 차이로 드러난다.

선언된 제약만 판정한다
    `optimize`에 넘어간 bounds에는 전략의 구성 선택도 섞여 있다(ETF를 e에 고정하는 등).
    그것을 compliance로 판정하면 "전략이 자기 규칙을 어겼다"가 mandate 위반과 **같은 등급**이
    되고, 전략 코드를 고칠 때마다 과거 compliance 판정의 의미가 달라진다(architecture §5.7).

여기서 하지 않을 것
    blocking, severity, override policy는 future work다(PRD §7.1). finding을 만들 뿐 실행을
    되돌리거나 중단하지 않는다. monitoring finding은 계좌를 소급 변경하지 않는다.
"""
