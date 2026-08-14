"""식별자 — 무엇을 부르는가.

구현할 것
    InstrumentId · DatasetId · RunId · IntentId · OrderBatchId · ExchangeId ·
    ProducerId · TableId. 전부 검증된 str newtype.

왜 newtype인가
    DatasetId를 받는 자리에 InstrumentId를 넘기는 것을 타입이 막는다. 그리고 형식 검증이
    한 곳에만 존재한다.

`references.py`와 다르다
    여기 있는 것은 **이름**이고 저쪽은 **참조**다. 참조는 버전과 schema identity를 들고 다녀
    reuse 판정(architecture §9.6)의 입력이 된다.

여기서 하지 않을 것
    UUID 생성 정책을 정하지 않는다. 그것은 그 값을 만드는 층이 정한다.
"""
