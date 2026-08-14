"""w_i(t) >= 0.

구현할 것
    Constraint 계약의 구현. requirements()는 비어 있다 — 외부 데이터가 필요 없다.
    project()는 모든 종목에 lower=0을 건다.
    measure()는 음수 비중을 excess로 보고한다.

`AccountMode.LONG_ONLY`와 무엇이 다른가
    AccountMode는 **상태 전이의 유효성**이고 이것은 **판단 시점의 mandate**다. 전자는 음수
    position을 가진 Fill의 commit을 거부하고, 후자는 음수 비중을 의도하지 않게 만든다.
    둘 다 있는 것이 이중 방어다(architecture §7.2).
"""
