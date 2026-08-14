"""거래비용 — 종목이 아니라 종류에 건다.

구현할 것
    CostRule   rule_id, kind(InstrumentKind), side, effective_from, effective_to,
               rate, minimum_cost
    매칭       (kind, side, event_time을 포함하는 기간)으로 선택

왜 종목 id가 아니라 kind인가
    종목마다 요율을 적으면 세율이 바뀔 때 3,000줄을 고쳐야 하고, 시기별 요율이 종목마다
    시계열이 되어 감당할 수 없다. 3,000종목을 거래해도 주식 규칙 하나와 ETF 규칙 하나면 된다.

    "삼성전자는 주식이다"는 venue를 바꿔도 안 변하고(`domain/instruments.py`), "주식 매도세는
    15bp다"는 KRX의 규칙이다(여기).

**모호함을 두 겹으로 막는다.**
    선언 시   같은 (kind, side)에 적용 기간이 겹치면 config 생성 실패
    해석 시   매칭된 규칙이 **정확히 하나**여야 한다. 0개도 2개도 실패

    0개 실패가 `UC-COST-004`(비슷한 종류의 정책으로 대체하지 않는다)이고, 2개 이상 실패가
    모호한 정책으로 조용히 계산하지 않는 것이다.

`UC-COST-001` `UC-COST-002` `UC-COST-004`
"""
