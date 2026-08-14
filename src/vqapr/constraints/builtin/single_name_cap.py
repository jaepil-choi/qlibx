"""w_i(t) <= max(floor, w_index_i(t)).

구현할 것
    Constraint 계약의 구현.
    requirements()  benchmark constituent weight를 **time-varying PIT data**로 요구한다
    project()       종목별 upper = max(floor, w_index(t)). 기본 floor는 10%
    measure()       초과분을 excess로 보고한다

핵심 성질
    weight가 3%인 종목의 cap은 10%, 15%인 종목의 cap은 15%다(`UC-CONSTRAINT-002`).

**누락되면 0으로 추정하지 않는다.**
    종목이 benchmark 비구성종목임이 확인되면 w_index=0이지만, 구성 여부나 weight data가
    누락되면 constraint evaluation을 실패시킨다. 0으로 추정하면 cap이 10%로 조용히 완화된다.

이 제약이 자기 데이터를 요구하기 때문에
    전략이 벤치마크 비중을 직접 읽지 않아도 cap이 적용된다. 그리고 데이터가 없으면 `optimize`
    호출 전에 실패하므로 주문도 mutation도 생기지 않는다.
"""
