"""진단 집계.

구현할 것
    zero-dealt 사유별 집계 (행 없음 / 거래 불가 / 현금 부족)
    clipping과 rounding 규모
    DECISION_SKIPPED(warmup) 목록
    ConstraintFinding 집계 — 어느 제약이 몇 번, 얼마나 초과했는가

왜 필요한가
    "어느 종목이 왜 줄었거나 체결되지 않았는지가 결과에서 확인된다"가 PRD §14.3의 요구다.
    개별 진단은 FillBatch와 OrderBatch에 있지만, 250세션 x 3,000종목에서 사람이 읽으려면
    집계가 필요하다.

진단을 성과의 출처로 쓰지 않는다
    집계는 무엇이 일어났는지를 말하고 얼마를 벌었는지는 말하지 않는다.
"""
