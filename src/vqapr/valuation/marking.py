"""보유 종목을 평가한다.

구현할 것
    requirements(snapshot) -> tuple[DataRequirement, ...]   **보유 종목 전체**의 mark field
    mark(...) -> MarkBatch

**하나라도 mark가 없으면 NAV를 추정하지 않고 MarkBatch commit 전에 실패한다.**
    직전 값으로 합성하거나 그 종목을 빼고 계산하지 않는다. 참조 구현이 결측 행을 버킷에서
    제외하고 나머지로 가중평균하는 것은 **암묵적 재정규화**이며 PRD §10.2 금지 목록의 첫
    항목이다(architecture §11.2).

    재현하려면 user가 정책을 명시해야 한다 — 정지일에 직전가로 mark할지, 형성 시점에 제외할지.
    이것은 결함이 아니라 의도된 차이다.

거래 불가와 평가 불가는 다르다
    평가   Valuation이 등록된 관측에서 읽는다        관측은 있다
    체결   Exchange가 체결 테이블에서 읽는다          거래는 불가능하다

    정지 종목은 관측은 있고 거래는 불가능하므로 두 경로가 다른 답을 주는 것이 정상이다.

VALUATION_* 실패의 특별함
    **Fill이 이미 commit된 뒤일 수 있는 유일한 실패**다. 그래서 정확한 account version을
    기록해야 한다(architecture §8.3).
"""
