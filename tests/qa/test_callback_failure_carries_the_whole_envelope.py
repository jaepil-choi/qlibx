"""A failure raised inside the strategy callback carries every advertised field.

The skill states the guarantee without qualification -- *every entry carries `code`, `status`,
`source`, `requirement`, `observed`, `fix` and `cause`* -- and tells the reader to read `fix`
first, because it is the sentence that fixes this occurrence.

A raise inside `decide()` delivered four of the six fields of the day. `fix`, `explain` and
`source` were absent entirely, and `requirement` degraded to "the guarded boundary must complete
without raising", which is a statement about this package's plumbing rather than about anything
the author did. Recorded as `docs/issues/archive/016`, which is the cross-cutting half of three separate
entries in the journey log. Record `171` replaced `explain` with `status` and put the exception
itself on the entry as `cause`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vqapr.flow.engine.artifacts import SimulationFailure, SimulationStage

_FIELDS = ("code", "status", "source", "requirement", "observed", "fix", "cause")


def _raised(error: Exception) -> Exception:
    """The exception with a traceback on it, the way a callback's raise arrives."""
    try:
        raise error
    except Exception as raised:
        return raised


def _failure(stage: SimulationStage, cause: Exception) -> dict:
    """One boundary failure, serialized the way an agent reads it."""
    moment = datetime(2024, 3, 6, 4, 0, tzinfo=UTC)
    return SimulationFailure(
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
def test_a_callback_valueerror_carries_every_field(message: str) -> None:
    """Both failures the journey hit, and both used to arrive with three fields missing."""
    body = _failure(SimulationStage.CALLBACK_INTENT, _raised(ValueError(message)))
    entry = body["failures"][0]

    missing = [field for field in _FIELDS if field not in entry or not entry[field]]
    assert not missing, f"the envelope dropped {missing}"

    assert entry["observed"] == message, "the author's own message must survive intact"
    assert entry["code"] == "strategy.callback.intent"
    assert entry["cause"]["type"] == "ValueError"
    assert entry["cause"]["message"] == message
    assert message in entry["cause"]["traceback"], "the exception rides whole"
    assert entry["cause"]["where"]


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
    no new component id is needed (`docs/issues/archive/009`).
    """
    body = _failure(SimulationStage.CALLBACK_INTENT, ValueError("boom"))
    fix = body["failures"][0]["fix"]

    assert "ValueError" in fix, "fix does not name what was raised"
    assert "callback" in fix
    assert "replaces in place" in fix, "fix implies the author needs a new registration"


def test_status_says_whose_frame_raised() -> None:
    """`status` is the key to the skill's recovery sections, and it is read off the traceback.

    An exception raised from a file outside the package -- this test's, or an author's strategy
    -- is the user's code crashing (502); one raised from inside the package is the framework's
    (500). Both are 5xx: the submission was fine, and what ran failed.
    """
    intent = _failure(SimulationStage.CALLBACK_INTENT, _raised(ValueError("boom")))
    publication = _failure(SimulationStage.CALLBACK_PUBLICATION, _raised(RuntimeError("boom")))

    assert intent["failures"][0]["status"] == 502
    assert intent["failures"][0]["cause"]["origin"] == "user"
    assert publication["failures"][0]["status"] == 502
    assert "explain" not in intent["failures"][0]
    assert "family" not in intent


def test_a_framework_refusal_is_still_passed_through_unchanged() -> None:
    """A `VqaprError` already carries every field, and must not be rewritten by this path.

    The synthesis above exists only for exceptions that carry no envelope of their own. Re-coding a
    refusal that already has one would rename a defect the reader may already handle.
    """
    from vqapr.domain.errors import Failure, FailureSource, Stage, Status, VqaprError

    original = VqaprError(
        stage=Stage.REGISTER,
        failures=[
            Failure.bounded(
                "declaration.keys_missing",
                "a declaration must name its component",
                status=Status.INVALID,
                observed="missing component",
                fix="add `component:`",
                source=FailureSource(file="spec.yaml"),
            )
        ],
    )

    entry = _failure(SimulationStage.CALLBACK_INTENT, original)["failures"][0]

    assert entry["code"] == "declaration.keys_missing"
    assert entry["fix"] == "add `component:`"
    assert entry["status"] == 400
