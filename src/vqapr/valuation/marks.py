"""평가 결과.

구현할 것
    Mark        instrument, price, 그 값의 출처(어느 dataset의 어느 field)
    MarkBatch   Mark의 모음 + 평가 시점

왜 별도 파일인가
    `account.mark()`가 이 타입을 받는다. 소비자가 account와 analysis 둘 이상이라 생산자 층에
    두되 파일을 나눈다 — 타입이 바뀌는 이유와 평가 로직이 바뀌는 이유가 다르다.

출처를 담는 이유
    어느 field로 평가했는지가 lineage에 남아야 한다. 같은 close를 StrategyModel과 Valuation이
    각자 요구했다는 사실이 보존되어야 한다(PRD §4.1).
"""
