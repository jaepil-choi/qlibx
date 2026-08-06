from qlibx.operations import BudgetMode, DecisionAction, StrategyDraft, WeightEntry


class SampleSignedConstraintStrategy:
    strategy_id = "sample.public-constraint-signed"

    def requirements(self) -> tuple[object, ...]:
        return ()

    def run(self, view: object) -> StrategyDraft:
        return StrategyDraft(
            weights=(
                WeightEntry(instrument="A005930", weight=0.6),
                WeightEntry(instrument="A000660", weight=-0.4),
            ),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.RESEARCH_ONLY,
            diagnostics=("product-owned signed constraint sample",),
        )