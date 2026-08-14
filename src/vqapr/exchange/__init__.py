"""exchange — 확장점. venue가 그 시점에 아는 것.

venue가 아는 것은 넷이고 **변화 속도만 다르다.**

    안 변함   ListingRule    수량 단위, 허용 방향
    기간별    CostRule       요율
    매 시점   체결 테이블     거래 가능 여부, 가격
    선언      FillConvention 언제 어느 값으로 체결하는가

무엇이 여기 속하는지 판정하는 규칙(architecture §2.8)
    venue를 바꾸면 달라지는가?  -> Exchange
    계좌를 바꾸면 달라지는가?   -> Account
    둘 다 아니고 회계 항등식인가? -> 공통 불변식

**거래정지는 venue가 판단한다.** 같은 종목이 KRX에서 정지여도 academic venue에서는 거래
가능일 수 있다. 시점에 따라 변한다는 이유만으로 데이터 쪽에 두면 venue를 바꿀 때 따라오지 않는다.
"""
