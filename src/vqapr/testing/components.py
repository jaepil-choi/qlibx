"""toy 컴포넌트 — 네 확장점 각각의 최소 구현.

구현할 것
    toy DataModel        state 없는 것과 state 쓰는 것 둘
    toy StrategyModel    hold만 하는 것, 균등가중, warm-up이 있는 것
    toy Exchange         conformance를 통과하는 최소 venue
    toy Constraint       고정 상한 하나

`extension/templates/`와 무엇이 다른가
    템플릿은 **사용자가 채우는 미완성**이고 이것은 **테스트가 쓰는 완성품**이다. 템플릿은
    처음에 실패해야 하고 이것은 통과해야 한다.

왜 필요한가
    flow와 conformance를 검증하려면 계약을 만족하는 최소 구현이 있어야 한다. 실제 전략을 쓰면
    테스트가 전략의 경제 로직에 의존하게 된다.
"""
