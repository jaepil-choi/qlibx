from qlibx import (
    DecisionAction,
    StrategyArtifactRequirement,
    StrategyDraft,
    StrategyExtensionSpec,
    StrategyResult,
)

STRATEGY_SPEC = StrategyExtensionSpec(strategy_id="sample.frozen-ensemble-consumer")


class FrozenEnsembleConsumer:
    strategy_id = STRATEGY_SPEC.strategy_id

    def requirements(self) -> tuple[object, ...]:
        return ()

    def artifact_requirements(self) -> tuple[StrategyArtifactRequirement, ...]:
        return (
            StrategyArtifactRequirement(
                requirement_id="sample.frozen-ensemble",
                consumer_role="frozen_ensemble",
                artifact_type="strategy_result",
                artifact_schema_version=3,
            ),
        )

    def run(self, view: object) -> StrategyDraft:
        source = view.artifact(  # type: ignore[attr-defined]
            "frozen_ensemble",
            StrategyResult,
        )
        return StrategyDraft(
            weights=source.weights,
            budget_mode=source.budget_mode,
            target_gross=source.target_gross,
            decision_action=DecisionAction.TARGET,
        )


def create_strategy() -> FrozenEnsembleConsumer:
    return FrozenEnsembleConsumer()
