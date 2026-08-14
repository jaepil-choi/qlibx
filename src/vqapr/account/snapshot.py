"""AccountSnapshot — package 밖으로 나가는 유일한 것.

구현할 것
    AccountSnapshot   cash, position, cost, version, as_of. **불변.**

왜 별도 파일인가
    소비자가 넷이다 — StrategyModel context, `orders/planning.py`, Exchange 구현,
    `valuation/marking.py`. 그리고 이것만이 package 경계를 넘어간다.

왜 읽기 전용인가
    architecture §2.3 — 쓰기를 모으고 읽기를 좁힌다. nautilus의 Cache는 읽기를 모으고 쓰기를
    분산하는 반대 방향인데, `intended != requested != dealt != committed` 네 단계를 구분해야
    하는 쪽이 더 좁은 authority를 갖는다.

as_of가 evaluation time보다 늦을 수 없다
    actual state가 과거 committed outcome만 담기 때문에 자연히 성립하며 별도 cutoff 장치를
    요구하지 않는다(PRD §3.2).
"""
