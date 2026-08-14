"""constraints — 선언 하나, 소비자 셋.

PRD §7.1이 제약의 결과를 셋으로 갈랐고 **셋이 같은 선언을 봐야 한다.**

    판단 시점     projection  -> optimize의 bounds
    결과 생성 시  evaluation(intended weights)  -> 독립 검증
    별도 cadence  evaluation(actual holdings)   -> monitoring finding

왜 별도 package인가
    소비자가 셋이고 층이 셋에 걸친다(portfolio 구성 / intent 검증 / monitoring). 변경 이유도
    독립적이다 — 제약 종류가 늘 때 바뀐다.

**이것은 네 번째 확장점이다.**
    constraint metric의 경제적 의미와 bound는 user project가 소유하므로(PRD §12.4) package가
    목록을 닫아둘 근거가 없다. `builtin/`의 둘은 다른 내장과 같은 지위이며 같은 문으로
    들어오고 같은 conformance를 통과한다(`UC-EXTENSION-003`).
"""
