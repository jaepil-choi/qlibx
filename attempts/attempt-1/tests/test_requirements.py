from __future__ import annotations

from qlibx.requirements import (
    CapabilityRequirement,
    CapabilityRequirements,
    DerivationAlternative,
    Finding,
    RequirementEvidence,
    evaluate_requirements,
    gather_evidence,
    plan_capability,
    supplied_roles_probe,
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
    payload = resolution.to_dict()
    assert "user_questions" not in payload
    assert payload["capability"] == {"id": "test.capability", "version": "1"}
    assert payload["retryable"] is True
    assert {item["status"] for item in payload["requirements"]} == {"unsatisfied"}


def test_gather_evidence_labels_each_answer_with_the_question_it_answered() -> None:
    """A probe reports only satisfaction; the protocol owns requirement/alternative identity."""
    asked: list[tuple[str, str]] = []

    def probe(requirement: CapabilityRequirement, alternative: DerivationAlternative) -> Finding:
        asked.append((requirement.requirement_id, alternative.alternative_id))
        return Finding(True, "supplied", source="test")

    evidence = gather_evidence(_declaration(), probe)

    # Every declared alternative is asked, not merely every requirement -- an evaluator that
    # only saw the first alternative would silently drop the fallback path.
    assert asked == [
        ("market_return", "index_return"),
        ("market_return", "capitalization_weighted"),
        ("groups", "explicit_groups"),
    ]
    assert [(item.requirement_id, item.alternative_id) for item in evidence] == asked


def test_a_probe_may_decline_an_alternative_without_inventing_a_reason() -> None:
    """Returning None means 'not asked', which must not become a fabricated refusal."""

    def probe(
        _requirement: CapabilityRequirement, alternative: DerivationAlternative
    ) -> Finding | None:
        if alternative.alternative_id != "index_return":
            return None
        return Finding(False, "The index-return dataset is not registered.")

    resolution = evaluate_requirements(_declaration(), gather_evidence(_declaration(), probe))
    market = resolution.results[0]

    assert [item.alternative_id for item in market.alternatives] == [
        "index_return",
        "capitalization_weighted",
    ]
    assert market.alternatives[0].reason == "The index-return dataset is not registered."
    assert market.alternatives[1].reason == "No evidence was provided for this alternative."


def test_supplied_roles_probe_selects_the_alternative_whose_inputs_are_all_present() -> None:
    """The shared rule for caller-supplied inputs: an alternative needs every role it names."""
    plan = plan_capability(
        _declaration(),
        supplied_roles_probe(("market_capitalization", "instrument_return")),
        parameters={"note": "only the derived path is supplied"},
    )
    market = plan.resolution.results[0]

    assert plan.ready is True
    assert market.selected_alternative == "capitalization_weighted"
    assert market.alternatives[0].details["missing_roles"] == ["index_return"]
    assert market.alternatives[1].details["missing_roles"] == []
    assert market.alternatives[0].details["supplied_roles"] == [
        "instrument_return",
        "market_capitalization",
    ]
    # The optional requirement stays unrequested even though its role is absent.
    assert plan.resolution.results[1].status == "not_requested"
    assert plan.parameters == {"note": "only the derived path is supplied"}
    assert plan.read_only is True


def test_plan_capability_carries_requested_optional_through_to_the_resolution() -> None:
    plan = plan_capability(
        _declaration(),
        supplied_roles_probe(("index_return",)),
        requested_optional=("groups",),
    )

    assert plan.ready is False
    assert plan.resolution.missing_requirements == ("groups",)
    assert plan.resolution.results[0].selected_alternative == "index_return"
