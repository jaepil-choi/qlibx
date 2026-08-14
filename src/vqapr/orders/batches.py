"""주문과 그 변환 증거.

구현할 것
    OrderRequest   instrument, side, quantity, 출처 intent/target, account version,
                   변환 가격, rounding/clipping/skip 진단
    OrderBatch     OrderRequest의 모음 + batch identity

왜 진단이 주문에 붙어 있나
    "어느 종목이 왜 줄었는지"가 결과에서 확인되어야 한다(PRD §14.3). 남은 현금을 종목 전체에
    나눠 조용히 줄이는 방식으로 처리하지 않는다.

여기에 free-form 기록 경로를 두지 않는다
    체결 쪽 진단은 이미 구조화되어 있다 — 이 파일이 clipping을, `exchange/fills.py`가
    requested/dealt와 zero-dealt 사유를 담는다. 자유 형식을 얹으면 **같은 사실을 표현하는
    방법이 둘**이 되고 읽는 쪽이 어느 것을 봐야 하는지 모른다(architecture §9.1).
"""
