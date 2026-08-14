"""evidence — 영수증. **닫힌 층.**

Evidence는 authority가 아니다. 그러나 **다른 run이 소비하는 입력**이므로 층이다.

    data access -> Model + trigger -> PortfolioIntent -> OrderBatch -> Exchange rules + inputs
    -> FillBatch -> Account version before/after -> MarkBatch -> feedback / limitations

nautilus는 이것이 `cache/`와 `persistence/`에 흩어져 있고 qlib은 `workflow/recorder`에 있다.
둘 다 기록이 **부산물**이기 때문이다. 우리에게는 StrategyModel 체인(A -> B -> C)이 성립하려면
기록이 층이어야 한다(architecture §9).

같은 이유로 `workflow/` 층이 **없다** — 실험 관리를 패키지가 소유하지 않는다. run은 값이고
catalog는 evidence다.
"""
