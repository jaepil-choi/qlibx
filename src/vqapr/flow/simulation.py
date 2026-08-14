"""이벤트를 배달한다.

구현할 것
    SimulationFlow
        on_decision(e)     -> Model 호출, intent 발행, Model state 스냅샷
        on_execution(e)    -> plan_orders, Exchange.execute
        on_fill_commit(e)  -> Account.commit
        on_valuation(e)    -> Valuation.mark, Account.mark
        on_monitoring(e)   -> constraints/evaluation.measure_all(actual holdings)
        on_finalize(e)     -> RunResult

**경제 규칙을 소유하지 않는다.**
    각 callback은 해당 package를 부를 뿐이다. monitoring의 판정 로직이 여기 있으면
    "flow는 경제 규칙을 소유하지 않는다"가 거짓이 된다.

Model state 스냅샷은 fill 발생과 무관하다
    체결이 없는 세션에도 스냅샷이 남는다(`UC-STATE-001`).

warm-up 구간의 candidate
    DECISION_SKIPPED(warmup)으로 **기록하고** 넘어간다. skip은 실패가 아니라 기록된 정상
    결과다. 그 이후의 결측은 실패다.

Timeline은 의미를 모른다
    정렬된 이벤트를 낼 뿐이고 StrategyModel도 Exchange도 모른다.
"""
