from zoneinfo import ZoneInfo

from qlibx.contracts import (
    BudgetMode,
    DecisionAction,
    EveryNSessions,
    StrategyDraft,
    StrategyStateUpdate,
    WeightEntry,
)
from qlibx.data import ComponentRequirement

KST = ZoneInfo("Asia/Seoul")


class SampleDailyFeedbackStrategy:
    strategy_id = "sample.daily-feedback"

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return (
            ComponentRequirement(
                requirement_id="sample.daily.decision_return",
                semantic_role="decision_return",
                dataset_id="sample-daily-market",
            ),
        )

    def run(self, view: object) -> StrategyDraft:
        account = view.account_snapshot()  # type: ignore[attr-defined]
        feedback = view.account_feedback()  # type: ignore[attr-defined]
        view.strategy_state()  # type: ignore[attr-defined]
        session = view.as_of.astimezone(KST).date()  # type: ignore[attr-defined]
        frame = view.session(  # type: ignore[attr-defined]
            "decision_return",
            session,
            session_timezone="Asia/Seoul",
        )
        winner = frame.sort_values(
            ["decision_return", "instrument"],
            ascending=[False, True],
            kind="mergesort",
        ).iloc[0]
        previous_performance = (
            view.latest_session_performance()  # type: ignore[attr-defined]
            if account.positions
            else None
        )
        transaction_cost = sum(
            fill.total_cost
            for entry in feedback.entries
            for fill in entry.fills
        )
        proposed_state = {
            "selected": str(winner.instrument),
            "consumed_feedback_cursor": feedback.next_cursor,
            "feedback_transaction_cost": transaction_cost,
            "previous_portfolio_return": (
                None
                if previous_performance is None
                else previous_performance.portfolio_return
            ),
        }
        return StrategyDraft(
            weights=(WeightEntry(instrument=str(winner.instrument), weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
            diagnostics=("product-owned daily feedback sample",),
            path_dependent=True,
            state_identity=(
                f"{account.account_id}:v{account.version}:cursor{feedback.next_cursor}"
            ),
            proposed_state=StrategyStateUpdate(value=proposed_state),
        )

    def trigger(self) -> EveryNSessions:
        return EveryNSessions(n=2)
