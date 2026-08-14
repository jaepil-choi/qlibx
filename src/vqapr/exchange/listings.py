"""venue별 수량 규칙.

구현할 것
    ListingRule        instrument_id, quantity_step, minimum_quantity,
                       fractional_allowed, permitted_sides
    ExchangeRulesView  그 시점 조회 결과

왜 Account가 아니라 여기인가
    같은 종목이 academic venue에서는 step=0.000001, KRX에서는 1일 수 있다. **fractional은
    상장의 성질이고 음수 cash는 계좌의 성질이다**(architecture §2.8). Account에 두면 profile을
    늘릴 때마다 Account를 고쳐야 한다.

dataset registration과 listing은 다른 일이다
    가격 데이터가 등록되어 있다는 사실이 그 종목을 그 venue에서 거래할 수 있다는 뜻이 아니다.
    거꾸로도 마찬가지다.

preflight가 검사한다
    intent가 다룰 수 있는 **모든 instrument**에 대해 listing이 존재하는지 시작 전에 확인한다.
    하나라도 없으면 run이 시작되지 않는다(architecture §12).

거래 가능 여부를 여기 넣지 않는다
    permitted_sides가 방향을 표현하고, 그 시점의 거래 가능 여부는 체결 테이블에 있다. 같은
    사실을 두 곳에 두지 않는다.
"""
