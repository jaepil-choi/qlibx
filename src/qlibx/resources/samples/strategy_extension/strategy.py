"""Installed-project example of a typed artifact-consuming Strategy extension."""

from qlibx import (
    ArtifactSemanticConstraint,
    BudgetMode,
    StoredSignalResult,
    StrategyArtifactRequirement,
    StrategyDraft,
    StrategyExtensionSpec,
    StrategyView,
    WeightEntry,
)

STRATEGY_SPEC = StrategyExtensionSpec(strategy_id="sample.local-ranked-signal")


class SampleRankedSignalStrategy:
    strategy_id = STRATEGY_SPEC.strategy_id

    def requirements(self) -> tuple[object, ...]:
        return ()

    def artifact_requirements(self) -> tuple[StrategyArtifactRequirement, ...]:
        return (
            StrategyArtifactRequirement(
                requirement_id="sample.local-ranked-signal.input",
                consumer_role="ranked_signal",
                artifact_type="stored_signal_result",
                artifact_schema_version=1,
                semantic_constraints=(
                    ArtifactSemanticConstraint(
                        field="signal_semantics",
                        expected="sample_rank_signal",
                    ),
                ),
            ),
        )

    def run(self, view: StrategyView) -> StrategyDraft:
        signal = view.artifact("ranked_signal", StoredSignalResult)
        selected = max(signal.entries, key=lambda entry: (entry.value, entry.instrument))
        return StrategyDraft(
            weights=(WeightEntry(instrument=selected.instrument, weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            diagnostics=(f"selected_from:{signal.signal_semantics}",),
        )


def create_strategy() -> SampleRankedSignalStrategy:
    return SampleRankedSignalStrategy()