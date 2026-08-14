"""기계 판독 descriptor를 **패키지에서 생성한다.**

구현할 것
    error code 표          `domain/errors.py`에서 생성
    requirement schema     각 소비자가 무엇을 선언해야 하는가
    컴포넌트 계약           네 확장점 각각의 입출력 계약과 통과 조건

왜 생성하나
    skill이 이 표를 들고 있어야 package error를 해석할 수 있다(PRD §2.6). 손으로 적으면
    `domain/errors.py`와 어긋나고, 어긋난 표는 없는 것보다 나쁘다 — agent가 잘못된 해결
    경로를 제시한다.

    패키지에서 뽑아내면 drift가 **구조적으로 불가능하다.**

누가 읽나
    bundled agent skill과 `vqapr check`의 기계 판독 출력. 사람이 읽는 문서가 아니다.
"""
