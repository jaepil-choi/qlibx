"""제약 하 배분 — 자르지 않고 한 번에 푼다.

**이 파일은 순수 leaf다.** `weighting.py`와 같은 import 금지가 그대로 적용된다(`UC-BUILTIN-001`).

구현할 것
    optimize(*, desired, current, lower, upper, frozen,
             cash_range, cost, turnover_penalty, L=None)
        -> (Weights, cash, Diagnostics)

    목적    ||L w - desired||^2  +  sum_i cost_i |w_i - w0_i|  +  lambda ||w - w0||_1
    제약    sum w + c = 1,  l <= w <= u,  c_lo <= c <= c_hi,  w_j = w0_j (j in frozen)

왜 자르지 않고 푸는가
    자르면 남은 비중을 재분배해야 하고, 재분배하면 다른 종목이 다시 상한에 걸려 반복이 생긴다.
    수렴 보장이 없고, 무엇보다 **잘릴 것을 미리 알았다면 다른 종목을 다르게 잡았을** 기회가
    사라진다(architecture §11.3, §11.7).

현금은 결정 변수다
    유도값이 아니라 예산 항등식을 만족하는 해의 일부다. 그래서 **"상한에 걸려 잘린 비중을
    어디로 보내나"라는 질문이 성립하지 않는다** — 현금이 흡수한다.

L은 목적함수에만 들어가고 제약에는 들어가지 않는다
    제약은 physical w에만 건다. 계좌에 남는 것이 physical이고 monitoring이 판정할 대상도
    그것이다. 노출은 계산값이라 매핑이 바뀌면 과거 판정까지 달라진다.
    **패키지는 L을 만들지 않는다** — StrategyModel이 만들어 넘긴다(PRD §8.2).

거래 불가 종목은 제외가 아니라 frozen이다
    조용히 빼면 PRD §10.2 위반이다. `w_j = w0_j` 제약으로 표현한다.

lower/upper가 어디서 오는지는 이 함수가 모른다
    선언된 제약의 투영일 수도, 전략의 구성 선택일 수도 있다. 합치는 것은 호출자의 일이고
    검증은 선언된 것만 판정한다(architecture §5.7).

리스크 항은 선택이며 기본은 없다
    공분산을 요구하는 순간 계약이 무거워진다.

`UC-CONSTRAINT-002` `UC-CONSTRAINT-ADJUST-001` `UC-ALPHA-BUDGET-001`
"""
