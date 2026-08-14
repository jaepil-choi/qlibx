"""models — 두 확장점의 계약.

DataModel과 StrategyModel은 **하나의 계약을 공유**하고 갈리는 것은 하나뿐이다.

    공유   trigger() · requirements() · tables() · memory · payload · recorder · checkpoint
    다름   **execution을 통과하는가**

그 결과로 따라오는 것
    DataModel     값을 만든다. 체결될 것이 없으므로 계좌가 없다. 진입점은 materialize
    StrategyModel 배분을 만든다. 체결되면 return이 생기므로 반드시 execution을 통과한다

**계좌 접근으로 두 역할을 가르면 틀린다.** 어떤 배분이 계좌를 쓰지 않을 수도 있지만, 그것이
그 역할이 계좌를 볼 수 없다는 뜻은 아니다(PRD §2.3).

두 계약을 한 package에 둔 이유
    공유 항목의 해석 코드가 하나여야 한다. TriggerPolicy -> 시점 목록 변환과 state 저장·복원이
    각각 한 군데에만 존재해야, 새 trigger나 payload 규칙을 추가할 때 한쪽만 고치는 사고가
    나지 않는다. 두 package로 나누면 그 공유가 코드에서 사라진다.
"""
