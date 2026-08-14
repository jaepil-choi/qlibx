"""선언 + PIT 관측 -> 종목별 bounds.

구현할 것
    ConstraintSet과 그 시점의 window를 받아 종목별 Bounds를 만든다.
    여러 제약이 같은 종목에 걸리면 가장 좁은 구간으로 교집합을 만든다.

**누락 시 0으로 추정하지 않는다.**
    benchmark constituent weight가 없으면 constraint evaluation을 실패시킨다. 종목이 비구성
    종목임이 **확인되면** w_index=0이지만, 확인되지 않은 것과 0인 것은 다르다(PRD §7).

    실패는 `optimize`가 호출되기 **전에** 일어나므로 portfolio 결과도 주문도 account mutation도
    생기지 않는다(`UC-CONSTRAINT-002`).

제약이 선언되지 않은 run에서는
    무한 bound를 돌려준다. 그래야 constraint 없는 research가 아무것도 등록하지 않고 돈다
    (`UC-CONSTRAINT-001`).

용어 주의
    여기서 "투영"은 **선언 -> 종목별 bound 벡터**를 뜻한다. architecture §11.7의 "순차 투영"은
    참조 구현이 쓰는 자르고-재분배 반복 기법의 이름이고 우리가 쓰지 않는 방법이다. 같은 단어가
    다른 것을 가리키므로 섞어 읽지 않는다.
"""
