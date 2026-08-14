"""append-only 전이 로그.

구현할 것
    commit과 mark가 만든 상태 전이의 추가 전용 기록. 각 항목이 before/after version을 갖는다.

`history.py`와 무엇이 다른가
    journal   원시 전이. 무엇이 언제 일어났는가
    history   소비자가 구독하는 projection. 무엇을 읽을 수 있는가

    두 파일인 이유는 audience가 다르기 때문이다. journal은 감사와 복원의 근거이고 history는
    StrategyModel과 monitoring이 읽는 표면이다.

**노출하지 않는다.**
    architecture §7.3 — raw journal은 노출하지 않고 immutable projection만 준다. 노출하면
    소비자가 원시 전이에 의존하게 되고 내부 표현을 바꿀 수 없다.
"""
