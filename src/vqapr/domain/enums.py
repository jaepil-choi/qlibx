"""닫힌 어휘.

구현할 것
    Side          BUY · SELL
    InstrumentKind stock · etf

왜 한 파일에 모으나
    각각 파일 하나씩 두면 파일이 아니라 이름 붙이기가 된다. nautilus도 `model/enums.py`
    하나에 모았다.

왜 지금 둘뿐인가
    늘어날 것을 미리 만들지 않는다. Side는 `exchange/listings.py`의 permitted_sides,
    `exchange/costs.py`의 선택자, `orders/batches.py`가 쓰고, InstrumentKind는 discriminator이자
    CostRule의 선택자다 — 셋 이상이 쓰므로 여기 있다.

여기 두지 않을 것
    AccountMode. 소비자가 사실상 Account 하나라 `account/account.py` 안에 있다.
    방향별 거래 가능 여부. 매수만 불가능한 상태는 현재 범위 밖이다(PRD §13.2).
"""
