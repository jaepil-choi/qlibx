from zoneinfo import ZoneInfo

from qlibx.data import ComponentRequirement
from qlibx.operations import BudgetMode, DecisionAction, StrategyDraft, WeightEntry

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
        memory = view.memory_snapshot()  # type: ignore[attr-defined]
        session = view.as_of.astimezone(KST).date()  # type: ignore[attr-defined]
        frame = view.session("decision_return", session)  # type: ignore[attr-defined]
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
        proposed_memory = {
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
            feedback_cursor=str(feedback.next_cursor),
            proposed_memory=proposed_memory,
            expected_memory_version=memory.version,
        )