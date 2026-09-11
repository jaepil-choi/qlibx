"""Adversarial attack on claim 6: `derived_available_at` refuses look-ahead, boundary is `<=`.

Three instants around `evaluation_time`, at one-microsecond resolution:
- exactly at the boundary: must NOT refuse (`<=`, not `<`)
- one microsecond before: must NOT refuse
- one microsecond after: MUST refuse, and the refusal must name the dataset

`derived_available_at` is deliberately probed directly with a hand-built `AccessRecord` rather
than through a full simulation, so the boundary is tested at exactly the resolution Python's
`datetime` supports and not diluted by whatever coarser cadence a fixture agenda happens to use.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vqapr.data.lookback import RowsLookback
from vqapr.data.store import AccessRecord
from vqapr.run.engine.output import LookAheadDetected, derived_available_at

_EVAL = datetime(2024, 1, 1, 15, 30, tzinfo=UTC)


def _access(dataset_id: str, max_available_at: datetime | None) -> AccessRecord:
    return AccessRecord(
        consumer_id="c",
        dataset_id=dataset_id,  # type: ignore[arg-type]
        source_id="s",
        source_digest="d",
        fields=("close",),
        lookback=RowsLookback(1),
        evaluation_time=_EVAL,
        instruments=("A",),
        lower_bound=None,
        actual_rows={},
        max_available_at=max_available_at,
    )


def test_exactly_at_the_boundary_is_permitted() -> None:
    """The boundary is `<=`, not `<`: an access carrying exactly `evaluation_time` must pass."""
    result = derived_available_at(_EVAL, [_access("prices", _EVAL)])
    assert result == _EVAL


def test_one_microsecond_before_is_permitted() -> None:
    result = derived_available_at(_EVAL, [_access("prices", _EVAL - timedelta(microseconds=1))])
    assert result == _EVAL


def test_one_microsecond_after_is_refused_and_names_the_dataset() -> None:
    """The one direction that must fail, at the tightest margin the type supports."""
    with pytest.raises(LookAheadDetected) as excinfo:
        derived_available_at(_EVAL, [_access("prices", _EVAL + timedelta(microseconds=1))])

    message = str(excinfo.value)
    assert "prices" in message, "the refusal must name the dataset that leaked"
    assert _EVAL.isoformat() in message


def test_a_mix_of_compliant_and_leaking_accesses_still_refuses() -> None:
    """A batch of several accesses where only the LAST one leaks must still be caught.

    If the check only inspected the first access in the sequence, or stopped after the first
    passing one, a leak buried later in the list would be missed.
    """
    accesses = [
        _access("prices", _EVAL - timedelta(days=1)),
        _access("volumes", _EVAL),
        _access("factors", _EVAL + timedelta(microseconds=1)),
    ]
    with pytest.raises(LookAheadDetected) as excinfo:
        derived_available_at(_EVAL, accesses)
    assert "factors" in str(excinfo.value)


def test_an_access_with_no_recorded_availability_does_not_trip_the_check() -> None:
    """`max_available_at=None` means nothing was actually read; must not be treated as a leak."""
    result = derived_available_at(_EVAL, [_access("prices", None)])
    assert result == _EVAL


def test_evaluation_time_itself_must_be_timezone_aware() -> None:
    """A naive `evaluation_time` cannot be compared against a tz-aware access boundary safely."""
    naive = datetime(2024, 1, 1, 15, 30)
    with pytest.raises(ValueError, match="evaluation_time"):
        derived_available_at(naive, [_access("prices", _EVAL)])
