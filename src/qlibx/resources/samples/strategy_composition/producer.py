from qlibx import BudgetMode, DecisionAction, EveryNSessions, StrategyDraft, WeightEntry


class CountingPathProducer:
    """Path-dependent sample producer with observable non-rerun evidence."""

    def __init__(self, identity: str, instrument: str) -> None:
        self.strategy_id = f"sample.path-producer-{identity}"
        self.instrument = instrument
        self.call_count = 0

    def requirements(self) -> tuple[object, ...]:
        return ()

    def trigger(self) -> EveryNSessions:
        return EveryNSessions(n=2)

    def run(self, view: object) -> StrategyDraft:
        account = view.account_snapshot()  # type: ignore[attr-defined]
        feedback = view.account_feedback()  # type: ignore[attr-defined]
        memory = view.memory_snapshot()  # type: ignore[attr-defined]
        self.call_count += 1
        return StrategyDraft(
            weights=(WeightEntry(instrument=self.instrument, weight=0.5),),
            budget_mode=BudgetMode.FLEXIBLE,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
            path_dependent=True,
            state_identity=(
                f"{account.account_id}:v{account.version}:cursor{feedback.next_cursor}"
            ),
            feedback_cursor=str(feedback.next_cursor),
            proposed_memory={
                "call_count": self.call_count,
                "feedback_cursor": feedback.next_cursor,
            },
            expected_memory_version=memory.version,
        )
