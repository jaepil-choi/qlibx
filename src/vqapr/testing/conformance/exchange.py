"""Exchange 계약 검사.

검사할 것
    불변식 `is_tradable = true  =>  선언된 가격이 유한하고 양수`
    세 zero-dealt 사유를 구분한다 (행 없음 / 거래 불가 / 현금 부족)
    batch-atomic 전제조건 — 체결 테이블 조회·listing·CostRule 매칭이 하나라도 안 되면 전체 실패
    체결 결과는 종목별로 다를 수 있다 — 정지 종목 하나에 rebalance 전체가 죽지 않는다
    선언한 가격 컬럼이 없을 때 **다른 컬럼으로 대체하지 않는다**
    매칭되는 CostRule이 0개거나 2개 이상이면 실패한다
    zero-dealt와 rejected를 Fill로 가장하지 않는다
    관측이 없는 시점의 행을 직전 값으로 **합성하지 않는다**

정렬과 누적 규칙은 검사하지 않는다
    그것은 계약이 아니라 KRX profile의 알고리즘이다(architecture §6.2). profile 간에 공유하는
    것은 OrderBatch/FillBatch envelope뿐이다.
"""
