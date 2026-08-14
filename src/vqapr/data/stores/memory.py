"""in-memory ObservationStore.

구현할 것
    ObservationStore protocol의 구현. Rows를 메모리에 들고 해석된 질의에 답한다.

왜 필요한가
    `transforms/` `portfolio/` `constraints/`는 순수 함수라 store가 없어도 검증되지만,
    창 조회와 lookback 경계를 검증하려면 store가 필요하다. duckdb를 띄우지 않고 돌 수 있어야
    테스트가 빠르고, `testing/datasets.py`의 픽스처가 이것 위에 선다.

    lookback pushdown 같은 것도 여기서 정확히 같은 의미로 동작해야 한다 — 느리게 구현하되
    **의미를 줄이지 않는다.** 줄이면 테스트가 통과하는데 실제로는 실패하는 조합이 생긴다.
"""
