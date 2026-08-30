"""A failure raised inside the strategy callback carries all six advertised fields.

The skill states the guarantee without qualification -- *every entry carries `code`, `source`,
`requirement`, `observed`, `fix` and `explain`* -- and tells the reader to read `fix` first,
because it is the sentence that fixes this occurrence.

A raise inside `decide()` delivered four of the six. `fix`, `explain` and `source` were absent
entirely, and `requirement` degraded to "the guarded boundary must complete without raising", which
is a statement about this package's plumbing rather than about anything the author did. Recorded as
`docs/issues/016`, which is the cross-cutting half of three separate entries in the journey log.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vqapr.evidence.artifacts import (
    SimulationFailure,
    SimulationFailureFamily,
    SimulationStage,
)

_SIX = ("code", "source", "requirement", "observed", "fix", "explain")


def _failure(stage: SimulationStage, cause: Exception) -> dict:
    """One boundary failure, serialized the way an agent reads it."""
    moment = datetime(2024, 3, 6, 4, 0, tzinfo=UTC)
    return SimulationFailure(
        family=SimulationFailureFamily.INTENT,
        stage=stage,
        clock=moment,
        failed_requirement=None,
        observed=str(cause),
        cause=cause,
        retry_precondition=None,
        correlation_id="c",
        frozen_run_identity="r",
        cutoff=moment,
        root_version=1,
        model_version=1,
        model_state_ref=None,
        account_version=1,
        pending_id=None,
    ).as_dict()


@pytest.mark.parametrize(
    "message",
    [
        # The journey's two, verbatim.
        "invested must be greater than zero and no greater than one",
        "decide() emitted undeclared diagnostic tables: ['ff3.formation']",
    ],
)
def test_a_callback_valueerror_carries_all_six_fields(message: str) -> None:
    """Both failures the journey hit, and both used to arrive with three fields missing."""
    body = _failure(SimulationStage.CALLBACK_INTENT, ValueError(message))
    entry = body["failures"][0]

    missing = [field for field in _SIX if field not in entry or not entry[field]]
    assert not missing, f"the envelope dropped {missing}"

    assert entry["observed"] == message, "the author's own message must survive intact"


def test_the_requirement_is_about_the_author_not_the_plumbing() -> None:
    """`requirement` must describe what was required of the code that raised.

    A reader handed a `ValueError` from their own `decide()` learns nothing from being told that
    this package's guarded boundary was supposed to not raise.
    """
    body = _failure(SimulationStage.CALLBACK_INTENT, ValueError("boom"))
    requirement = body["failures"][0]["requirement"]

    assert "guarded boundary" not in requirement, (
        "the refusal still describes the framework's plumbing rather than the author's callback"
    )
    assert "callback" in requirement


def test_fix_names_where_to_look_and_that_re_registration_is_in_place() -> None:
    """`fix` is the field the skill says to read first, and it was absent.

    It cannot know the specific cause of an arbitrary exception, so it must at least say where the
    fault is and what the repair loop costs -- which is nothing: registration replaces in place, so
    no new component id is needed (`docs/issues/009`).
    """
    body = _failure(SimulationStage.CALLBACK_INTENT, ValueError("boom"))
    fix = body["failures"][0]["fix"]

    assert "ValueError" in fix, "fix does not name what was raised"
    assert "callback" in fix
    assert "replaces in place" in fix, "fix implies the author needs a new registration"


def test_explain_resolves_to_a_real_recovery_topic() -> None:
    """`explain` must name a topic the skill actually has a section for.

    `tests/characterization/test_explain_topics.py` pins topics and `### Recovering from:` sections
    to each other in both directions, so a topic invented here would fail that test rather than
    silently pointing a reader at a section that does not exist.
    """
    from vqapr.domain.errors import ExplainTopic

    intent = _failure(SimulationStage.CALLBACK_INTENT, ValueError("boom"))
    publication = _failure(SimulationStage.CALLBACK_PUBLICATION, RuntimeError("boom"))

    assert intent["failures"][0]["explain"] == str(ExplainTopic.COMPONENT_CONTRACT)
    assert publication["failures"][0]["explain"] == str(ExplainTopic.PUBLICATION)


def test_a_framework_refusal_is_still_passed_through_unchanged() -> None:
    """A `VqaprError` already carries all six, and must not be rewritten by this path.

    The synthesis above exists only for exceptions that carry no envelope of their own. Re-coding a
    refusal that already has one would rename a defect the reader may already handle.
    """
    from vqapr.domain.errors import (
        ExplainTopic,
        Failure,
        FailureFamily,
        FailureSource,
        VqaprError,
    )

    original = VqaprError(
        stage="declaration.parse",
        family=FailureFamily.INTENT,
        failures=[
            Failure.bounded(
                "declaration.keys_missing",
                "a declaration must name its component",
                observed="missing component",
                fix="add `component:`",
                explain=ExplainTopic.DECLARATION_SHAPE,
                source=FailureSource(file="spec.yaml"),
            )
        ],
    )

    entry = _failure(SimulationStage.CALLBACK_INTENT, original)["failures"][0]

    assert entry["code"] == "declaration.keys_missing"
    assert entry["fix"] == "add `component:`"
    assert entry["explain"] == str(ExplainTopic.DECLARATION_SHAPE)
