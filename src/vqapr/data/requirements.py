"""소비자가 무엇을 필요로 하는지 선언한다.

구현할 것
    DataRequirement       consumer_id, dataset_id, fields, lookback, 선택적 coverage
    CoverageRequirement   그 구간에 최소 몇 개의 관측이 있어야 하는가

누가 선언하나
    DataModel은 계산 입력을, StrategyModel은 signal/benchmark/constituent field를,
    Valuation은 보유 종목 mark field를, Constraint는 자기 bound에 필요한 데이터를 선언한다.

**Exchange는 여기에 없다.**
    체결에 필요한 가격과 거래 가능 여부는 DataRequirement가 아니라 체결 테이블 **점 조회**로
    얻는다. 창도 lookback도 거치지 않는다(`exchange/execution_table.py`).

ArtifactRequirement를 만들지 않는다
    계산 결과도 dataset이다. DataModel이 다른 DataModel의 결과를 읽는 것은 그냥 데이터를 읽는
    것이다. 별도 경로를 두면 PIT 처리를 두 곳에 구현하게 되고, 둘이 어긋나는 순간
    **파생 데이터에서만** look-ahead가 생긴다. 그 버그는 원본 데이터 테스트로 잡히지 않는다.

`UC-DATA-002` `UC-PIT-001`
"""
