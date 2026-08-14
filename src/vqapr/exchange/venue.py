"""Exchange 계약 — 사용자가 구현하는 것.

구현할 것
    Exchange (Protocol)
        exchange_id
        calendar                              SessionCalendar
        fill                                  FillConvention
        rules(at, instruments)                -> ExchangeRulesView
        snapshot(at, instruments)             -> ExecutionSnapshot
        execute(event, orders, account, venue) -> FillBatch
    ExecutionSnapshot   그 시각 체결 테이블 조회 결과
    ExchangeRulesView   그 시점의 listing 규칙 조회 결과

왜 Protocol인가
    구현이 둘 이상이고(academic, krx) **사용자가 자기 venue를 작성할 수 있다**
    (`UC-EXTENSION-003`). `orders/planning.py`가 함수인 것과 갈리는 지점이 이것이다.

Store를 모른다
    자기 체결 테이블을 점 조회할 뿐이다. `DataRequirement`도 `ModelWindow`도 쓰지 않는다.

listing의 소유자는 Exchange다
    어떤 instrument가 그 venue에 상장되어 있고 어떤 수량 규칙을 갖는지는 **Exchange의 frozen
    config**가 소유한다. RunDefinition에 별도 listing 필드를 두지 않는다 — 두면 "거래 가능한데
    lot을 모른다"는 상태가 생긴다.

profile은 주입한다
    Academic Flow와 KRX Flow를 따로 만들지 않는다. 두 profile은 **같은 lifecycle에 다른
    정책**이며, Flow를 나누면 그 사실이 거짓이 된다(architecture §2.5).
"""
