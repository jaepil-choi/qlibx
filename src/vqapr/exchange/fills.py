"""체결 결과.

구현할 것
    Fill             requested/dealt quantity, 가격, fee/tax, 적용 listing rule
    FillBatch        Fill의 모음 + execution data lineage, exchange id, intent id,
                     order batch id
    ZeroDealtReason  최소 셋을 구분한다
                        체결 테이블에 행이 없음   그 시점 이 venue에 없다
                        is_tradable = false      상장돼 있으나 거래 불가
                        현금 부족                 앞선 주문이 현금을 소진했다

**zero-dealt와 rejected를 Fill로 가장하지 않는다.**
    다음 decision이 이를 구분해 읽을 수 있어야 한다(`UC-CLOSED-LOOP-001`).

한 FillBatch에 세 경우와 정상 체결이 섞인다
    3,000종목 x 250세션에서 정지와 상폐는 매일 나온다. 그것을 batch 실패로 묶으면 run이 첫 주에
    죽는다. **전제조건은 all-or-nothing이고 체결 결과는 종목별로 다를 수 있다.**

is_tradable=true인데 가격이 없는 경우는 여기 없다
    그것은 zero-dealt가 아니라 **batch 실패**이므로 FillBatch 자체가 만들어지지 않는다. 앞의
    셋은 고칠 것이 없는 시장 사실이고, 이것은 거래할 수 있다고 선언해 놓고 가격을 주지 않은
    것이라 연구자가 고칠 수 있고 고쳐야 한다.

`UC-TRADABILITY-002` `UC-FILL-001`
"""
