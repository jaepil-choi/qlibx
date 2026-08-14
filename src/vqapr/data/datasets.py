"""의미 — logical dataset 등록.

구현할 것
    DatasetRegistration
        dataset_id, source, 선택적 query
        instrument_field      어느 field가 instrument인가 (이름을 강제하지 않는다)
        available_at          AvailabilityBinding (`availability.py`)
        key_fields            logical row key
        fields                프레임워크 이름 -> 물리 위치 매핑

의미 층에 요구하는 것은 여섯 개가 전부다
    fiscal_period, session_date, revision, horizon_end는 **일반 column**이다. 이를 필요로 하는
    consumer가 명시적으로 요구하며, 아직 선택하지 않은 workflow 때문에 최초 등록을 막지 않는다.

개명은 되고 role은 안 된다
    허용   "당일시가(원)" -> open        누가 읽을지 말하지 않는다. 안정적인 손잡이일 뿐
    금지   "당일종가(원)" -> execution_price   **누가 읽을지를 등록이 미리 정한다**

    같은 close를 StrategyModel · Exchange · Valuation이 각자 요구해야 누가 무엇을 읽었는지
    lineage에 남는다(PRD §4.1).

종목 축이 없는 시계열도 같은 계약을 쓴다
    지수 레벨, 금리, 환율은 상수 컬럼 하나를 두어 합성 instrument(`_KOSPI`, `_CD91`)로 등록한다.
    예외를 두면 ModelWindow가 두 모양을 갖게 되고 소비자가 분기해야 한다.

등록이 보장하지 않는 것
    등록 query가 만들어내는 값이 point-in-time으로 안전한지는 **판정하지 않는다.** 사용자가
    자기 ETL에서 미리 계산해 오면 똑같으므로 한쪽만 막는 것은 막은 것이 아니고, 반쪽 보장은
    무보장보다 나쁘다. 그 경계는 등록 이전의 agent 인터뷰가 담당한다(PRD §11.1).

`UC-DATA-001` `UC-DATA-003`
"""
