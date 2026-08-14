"""이식 가능한 표 값.

구현할 것
    Scalar   bool · int · float · str · Decimal · date · datetime · None
    Rows     arrow table을 감싼 얇은 값

왜 하나의 타입이어야 하나
    `DataModel.compute()`의 반환, `Recorder.append_batch()`의 입력, publish된 table의 표현이
    **전부 같은 타입**이어야 architecture §9.1의 "기록 테이블은 dataset으로 읽는다"가 성립한다.
    셋이 다른 타입이면 소비자가 출처별로 분기하게 된다.

왜 Scalar를 제한하나
    architecture §9.1이 diagnostic schema를 portable scalar type으로 제한한다. 제한하지 않으면
    다른 process가 읽을 수 없는 값이 artifact에 들어간다.

여기서 하지 않을 것
    pandas 타입을 public 계약에 노출하지 않는다. 내부 구현이 무엇을 쓰든 경계에서는 이 타입이다.
"""
