"""The point-in-time boundary is asserted, not assumed.

`derived_available_at` used to search its accesses for an instant later than `evaluation_time` and
stamp with that instead. The branch was unreachable, because every observation query binds
`WHERE available_at <= evaluation_time` (`scan.py:579,620`).

Deleting unreachable code is normally right. Here it would have removed the only thing watching for
a specific failure that nothing else in the stack can see: **look-ahead improves correlations.** A
run that reads tomorrow's price produces better numbers, not worse ones, so the count gate passes,
`compare_factors.py` passes, and every downstream figure looks like an improvement. A silent
improvement is the hardest kind of wrong to notice.

So the branch became an assertion, and this is the mutation test that proves the assertion is live:
the guarded condition is constructed directly, and the failure must be raised rather than absorbed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vqapr.flow.datamodel import LookAheadDetected, derived_available_at

AT = datetime(2024, 3, 5, 6, 30, tzinfo=UTC)


class _Access:
    """The two fields the stamp reads. A real `AccessRecord` needs a whole run to build."""

    def __init__(self, max_available_at: datetime | None, dataset_id: str = "prices") -> None:
        self.max_available_at = max_available_at
        self.dataset_id = dataset_id


def test_a_derived_row_is_knowable_at_the_instant_that_derived_it() -> None:
    """The ordinary answer, and the only one the PIT bound permits."""
    accesses = (_Access(AT - timedelta(hours=1)), _Access(AT), _Access(None))

    assert derived_available_at(AT, accesses) == AT


def test_no_accesses_still_stamps_the_evaluation_instant() -> None:
    """A derived value that consumed nothing is knowable when it was computed."""
    assert derived_available_at(AT, ()) == AT


def test_a_row_newer_than_the_read_that_returned_it_is_refused(
) -> None:
    """The mutation test. This is what a loosened PIT bound would produce.

    Constructed directly rather than by editing `scan.py`, because the assertion must fire on the
    CONDITION, whatever produced it -- a future query path that forgets the bound is exactly as
    dangerous as an edit to the existing one, and this test must catch both.
    """
    leaked = _Access(AT + timedelta(seconds=1), dataset_id="prices")

    with pytest.raises(LookAheadDetected) as caught:
        derived_available_at(AT, (leaked,))

    message = str(caught.value)
    assert "prices" in message, "the refusal must name the dataset that leaked"
    assert "available_at <= evaluation_time" in message, (
        "the refusal must name the bound that was supposed to prevent this"
    )
    assert "improves correlations" in message, (
        "the refusal must say why no other gate would have caught it"
    )


def test_the_boundary_instant_itself_is_not_a_leak() -> None:
    """`available_at == evaluation_time` is knowable, and the bound is `<=` not `<`.

    Off by one here would refuse every row published exactly at the instant that reads it, which on
    a daily close is most of them.
    """
    assert derived_available_at(AT, (_Access(AT),)) == AT


def test_a_naive_evaluation_time_is_refused_before_anything_is_compared() -> None:
    """Comparing a naive instant to an aware one raises something less useful further in."""
    with pytest.raises(ValueError, match="evaluation_time"):
        derived_available_at(datetime(2024, 3, 5, 6, 30), ())
