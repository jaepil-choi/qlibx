"""Constraint 계약 검사.

검사할 것
    `requirements()`가 선언한 data로 `project()`가 성립한다
    요구한 data가 없으면 **결과를 만들기 전에 실패한다** (0으로 추정하지 않는다)
    `project()`가 종목별 Bounds를 낸다
    `measure()`가 intended weights와 actual holdings **둘 다**에 적용된다
    finding이 constraint_id · measured · bound · excess · pass/fail · lineage를 갖는다
    같은 선언이 같은 입력에 같은 판정을 낸다

왜 둘 다에 적용되는지를 검사하나
    생산 검증과 monitoring이 같은 함수를 부르는 것이 설계의 핵심이다. 한쪽에서만 동작하는
    구현이 등록되면 `UC-CONSTRAINT-ADJUST-001`의 차이를 읽을 수 없게 된다.
"""
