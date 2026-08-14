"""판정 결과.

구현할 것
    ConstraintFinding   constraint_id, measured value, bound, excess, pass/fail, input lineage
    ConstraintReport    finding의 모음 + 평가 시점 + 평가 대상(intended / actual)

왜 input lineage가 필요한가
    "이 cap이 어느 benchmark dataset의 어느 시점 값으로 판정되었는가"를 재구성할 수 있어야
    한다. 그렇지 않으면 같은 판정을 다시 만들 수 없다(PRD §7.1).

왜 평가 대상을 담나
    같은 함수가 intended weights와 actual holdings 둘 다에 쓰이므로, finding만 보고 어느 쪽인지
    알 수 없으면 `UC-CONSTRAINT-ADJUST-001`의 차이를 읽을 수 없다.

required input 부재는 finding이 아니다
    그것은 **결과를 만들기 전의 structured operation error**다(`domain/errors.py`). finding으로
    만들면 "평가했는데 통과 못 했다"와 "평가하지 못했다"가 같은 것이 된다.
"""
