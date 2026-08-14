"""package가 출하하는 venue.

    academic   signed · fractional · 비용 0 · realism "hypothetical"
    krx        long-only · 정수 step · effective-dated 비용 · realism "simulation"

**공통 base class를 만들지 않는다.**
    두 profile이 공유하는 것은 OrderBatch/FillBatch **envelope뿐**이고 알고리즘은 나눈다
    (architecture §2.7). base를 만들면 `UC-COST-004`의 "ETF에 Equity policy를 적용하지 않는다"가
    조건 분기 하나 차이로 무너진다.

이름이 realism을 주장하지 않는다
    **구현된 rule과 명시한 limitation만** 주장한다.

**이 둘은 특권을 갖지 않는다.** project-local Exchange와 같은 계약, 같은 conformance, 같은
등록 경로를 쓰며 preflight에서 구분되지 않는다(`UC-EXTENSION-003`).
"""
