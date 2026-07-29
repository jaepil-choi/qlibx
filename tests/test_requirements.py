from __future__ import annotations

from qlibx.requirements import (
    CapabilityRequirement,
    CapabilityRequirements,
    DerivationAlternative,
    RequirementEvidence,
    evaluate_requirements,
)


def _declaration() -> CapabilityRequirements:
    return CapabilityRequirements(
        capability_id="test.capability",
        capability_version="1",
        summary="Exercise the public requirement evaluator.",
        requirements=(
            CapabilityRequirement(
                requirement_id="market_return",
                role="market_return",
                meaning="Point-in-time market return.",
                axis="time",
                unit="return",
                currency="not_applicable",
                purpose="Measure market exposure.",
                satisfaction_rule="One declared alternative must be available.",
                availability="Available no later than the decision time.",
                mandatory=True,
                unavailable_effect="Market exposure cannot be calculated.",
                alternatives=(
                    DerivationAlternative(
                        alternative_id="index_return",
                        description="Use a registered index-return dataset.",
                        required_inputs=("index_return",),
                        derivation="direct",
                    ),
                    DerivationAlternative(
                        alternative_id="capitalization_weighted",
                        description="Derive a capitalization-weighted market return.",
                        required_inputs=("market_capitalization", "instrument_return"),
                        derivation="capitalization-weighted aggregation",
                    ),
                ),
                user_questions=("Which market-return alternative should be registered?",),
                next_commands=("qlibx data inspect --root <project> --path <source>",),
            ),
            CapabilityRequirement(
                requirement_id="groups",
                role="group_label",
                meaning="Point-in-time group label.",
                axis="date_by_ticker",
                unit="category",
                currency="not_applicable",
                purpose="Optional group exposure.",
                satisfaction_rule="An explicit group-label matrix is available.",
                availability="Available no later than the decision time.",
                mandatory=False,
                unavailable_effect="Group exposure is unavailable.",
                alternatives=(
                    DerivationAlternative(
                        alternative_id="explicit_groups",
                        description="Use explicit point-in-time group labels.",
                        required_inputs=("group_label",),
                        derivation="direct",
                    ),
                ),
                user_questions=("Which registered dataset contains the group labels?",),
                next_commands=("qlibx data catalog --root <project>",),
            ),
        ),
    )


def test_evaluator_supports_alternatives_and_unrequested_optional_requirements() -> None:
    resolution = evaluate_requirements(
        _declaration(),
        (
            RequirementEvidence(
                requirement_id="market_return",
                alternative_id="capitalization_weighted",
                satisfied=True,
                reason="Both registered inputs are available.",
                source="project_catalog",
                details={"datasets": ["market_cap", "instrument_return"]},
            ),
        ),
    )

    assert resolution.ready is True
    assert resolution.satisfied_requirements == ("market_return",)
    assert resolution.missing_requirements == ()
    assert resolution.results[0].selected_alternative == "capitalization_weighted"
    assert resolution.results[1].status == "not_requested"


def test_evaluator_reports_one_typed_gap_for_plan_and_error_serialization() -> None:
    resolution = evaluate_requirements(
        _declaration(),
        (
            RequirementEvidence(
                requirement_id="market_return",
                alternative_id="index_return",
                satisfied=False,
                reason="The selected dataset is not registered.",
            ),
        ),
        requested_optional=("groups",),
    )

    assert resolution.ready is False
    assert resolution.missing_requirements == ("groups", "market_return")
    assert "Which market-return alternative" in " ".join(resolution.user_questions)
    payload = resolution.to_dict()
    assert payload["capability"] == {"id": "test.capability", "version": "1"}
    assert payload["retryable"] is True
    assert {item["status"] for item in payload["requirements"]} == {"unsatisfied"}
