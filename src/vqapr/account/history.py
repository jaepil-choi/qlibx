"""이력 — 기록은 고정, 구독은 선언.

구현할 것
    기록되는 고정 집합
        account series     cash, nav, realized_pnl, gross/net exposure
        instrument panel   quantity, avg_entry_price, realized_pnl, last_mark_price
    AccountHistoryQuery / HistoryRequirement   읽을 항목과 범위를 좁혀 요구한다
    AccountHistory                             immutable projection

왜 설정하지 않는가
    위 값들은 commit을 수행하려면 어차피 구해야 한다. 기록은 한 줄 append일 뿐이고 3,000종목
    x 250세션도 무겁지 않다. 설정 가능하게 만들면 **얻는 것 없이 run identity에 필드만 하나
    는다**(architecture §7.3).

왜 고정 집합인가
    집합이 고정이어야 "집합 밖 항목 요구 -> 계산 전 실패"가 성립한다. 추정 금지를 지키는 데
    필요한 건 선언이 아니라 **경계**다.

왜 memory와 분리되어 있나
    `UC-ACCOUNT-HISTORY-001`은 strategy state 없이 stop-loss와 cooldown이 표현 가능해야 한다고
    요구한다. history를 memory 위에 얹으면 research-only StrategyModel이 그 규칙을 쓸 수 없다.

raw journal은 노출하지 않는다
    immutable projection만 준다.
"""
