"""무엇을 거래하는가.

구현할 것
    InstrumentBase        instrument_id, currency — 공통 필드는 여기 한 번만
    StockInstrument       kind: Literal["stock"]
    EtfInstrument         kind: Literal["etf"]
    Instrument            kind를 discriminator로 하는 union

왜 kind가 있나
    직렬화 경계를 건너기 위한 꼬리표다. JSON에는 클래스가 없어서 두 종류의 필드가 같으면
    읽을 때 어느 것인지 복원할 수 없다. PRD §2.5가 raw dict가 아닌 typed object 복원을 요구한다.

왜 Literal인가
    꼬리표가 클래스와 어긋날 수 없게. str이면 StockInstrument(kind="etf")가 통과한다.

왜 지금 비어 있나
    우선주 구분 같은 것은 실제로 필요할 때 넣는다. **클래스는 미리, 필드는 나중에** —
    나중에 나누면 모든 생성 지점을 고쳐야 하고, 필드 추가는 기본값을 주면 국소적이다.

여기 없는 것과 그 이유
    exchange_id      같은 종목이 venue마다 다른 수량 단위를 가질 수 있어야 한다. 넣으면
                     "같은 종목"이라는 사실이 깨진다(architecture §6.2)
    거래 가능 여부    시점에 따라 변한다. 정적 선언에 넣으면 어제의 판단이 오늘의 정지
                     상태를 보게 된다(architecture §2.8)
"""
