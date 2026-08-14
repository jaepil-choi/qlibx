"""suite를 돌리고 기계 판독 결과를 낸다.

구현할 것
    run(ref, instance) -> ConformanceReport
        ComponentKind에 맞는 suite를 고른다
        각 검사의 통과/실패와 **왜 실패했는지**를 구조화해 반환한다

왜 기계 판독인가
    agent가 first-class user이고(PRD §1.4), `vqapr check`의 출력이 agent가 읽는 표면이다.
    사람이 읽는 형태는 pytest가 이미 준다.

실패 형식
    `domain/errors.py`의 구조를 따른다 — 어떤 요구가 충족되지 않았는지, 무엇을 고쳐야 하는지.
    **해결 방법을 결정하지는 않는다.** 그것은 agent의 일이다.
"""
