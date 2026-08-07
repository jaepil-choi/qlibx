from zoneinfo import ZoneInfo

from qlibx.data import ComponentRequirement
from qlibx.operations import BudgetMode, DecisionAction, StrategyDraft, WeightEntry

KST = ZoneInfo("Asia/Seoul")


class SampleReversalStrategy:
    strategy_id = "sample.real-dw-direct"

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return (
            ComponentRequirement(
                requirement_id="sample.direct.decision_return",
                semantic_role="decision_return",
                dataset_id="sample-real-dw-market",
            ),
        )

    def run(self, view: object) -> StrategyDraft:
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
        return StrategyDraft(
            weights=(WeightEntry(instrument=str(winner.instrument), weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.RESEARCH_ONLY,
            diagnostics=("product-owned sample direct Strategy",),
        )
