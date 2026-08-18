"""The causal guarantee has to be checkable, not merely stated.

Asserting that the callable receives a tuple of the right length proves almost nothing: a centred
window hands over a tuple of exactly that length too, with the wrong elements in it. So these tests
check the contents and the reachability, not the container.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr.transforms.window import (
    apply_causal,
    window_beta,
    window_maximum,
    window_mean,
    window_skewness,
    window_stdev,
)


def _series(*values: str) -> tuple[Decimal, ...]:
    return tuple(Decimal(value) for value in values)


def test_every_window_is_exactly_the_trailing_slice() -> None:
    """Element-wise, not length-wise. A centred window has the right length and the wrong values."""
    values = _series("1", "2", "3", "4", "5", "6")
    seen: list[tuple[Decimal, ...]] = []

    apply_causal((values,), length=3, fn=lambda windows: (seen.append(windows[0]), Decimal(0))[1])

    assert seen == [values[i - 2 : i + 1] for i in range(2, len(values))]


def test_a_later_observation_cannot_change_an_earlier_step() -> None:
    """The no-future property, stated as an experiment rather than as a promise.

    Mutating any observation strictly after step `i` must leave the output at `i` untouched. A
    centred or forward-looking window fails this immediately.
    """
    base = _series("1", "2", "3", "4", "5", "6")
    original = apply_causal((base,), length=3, fn=window_mean)

    for cut in range(3, len(base)):
        tampered = base[:cut] + tuple(value * 100 for value in base[cut:])
        produced = apply_causal((tampered,), length=3, fn=window_mean)
        assert produced[: cut - 1] == original[: cut - 1], (
            f"changing observations from {cut} onward altered an earlier step"
        )


def test_the_last_step_equals_the_last_observations() -> None:
    """End-anchored: the final window is the final `length` observations and nothing else."""
    values = _series("10", "20", "30", "40")

    produced = apply_causal((values,), length=2, fn=window_mean)

    assert produced[-1] == (values[-1] + values[-2]) / 2
    assert produced == (None, Decimal(15), Decimal(25), Decimal(35))


def test_warm_up_reports_none_rather_than_a_short_window() -> None:
    values = _series("1", "2", "3", "4")

    produced = apply_causal((values,), length=3, fn=window_mean)

    assert produced[:2] == (None, None)
    assert all(value is not None for value in produced[2:])


def test_a_series_shorter_than_the_window_is_all_warm_up() -> None:
    produced = apply_causal((_series("1", "2"),), length=5, fn=window_mean)

    assert produced == (None, None)


def test_misaligned_series_are_refused_before_any_step_runs() -> None:
    """Alignment is the driver's job, so a statistic never has to defend itself against it."""
    calls: list[object] = []

    with pytest.raises(ValueError, match="equally long"):
        apply_causal(
            (_series("1", "2", "3"), _series("1", "2")),
            length=2,
            fn=lambda windows: (calls.append(windows), Decimal(0))[1],
        )

    assert calls == [], "the driver refused after already invoking the callable"


def test_two_series_are_read_in_lockstep() -> None:
    asset = _series("1", "2", "3", "4")
    market = _series("5", "6", "7", "8")
    seen: list[tuple[tuple[Decimal, ...], ...]] = []

    apply_causal((asset, market), length=2, fn=lambda w: (seen.append(w), Decimal(0))[1])

    assert seen == [
        ((asset[i - 1], asset[i]), (market[i - 1], market[i])) for i in range(1, len(asset))
    ]


def test_the_driver_refuses_a_float_or_an_infinite_value() -> None:
    with pytest.raises(TypeError, match="must be a Decimal"):
        apply_causal(([Decimal(1), 2.0],), length=2, fn=window_mean)  # type: ignore[list-item]

    with pytest.raises(ValueError, match="must be finite"):
        apply_causal(((*_series("1"), Decimal("Infinity")),), length=2, fn=window_mean)


def test_the_driver_refuses_a_non_positive_length() -> None:
    for length in (0, -1):
        with pytest.raises(ValueError, match="positive integer"):
            apply_causal((_series("1", "2"),), length=length, fn=window_mean)


def test_statistics_refuse_the_wrong_number_of_series() -> None:
    single = ((Decimal(1), Decimal(2)),)
    paired = ((Decimal(1), Decimal(2)), (Decimal(3), Decimal(4)))

    with pytest.raises(ValueError, match="one series"):
        window_mean(paired)
    with pytest.raises(ValueError, match="two series"):
        window_beta(single)


def test_the_shipped_statistics_compute_what_they_claim() -> None:
    window = ((Decimal(2), Decimal(4), Decimal(6)),)

    assert window_mean(window) == Decimal(4)
    assert window_maximum(window) == Decimal(6)
    assert window_stdev(window) == Decimal(2)


def test_beta_of_a_series_against_itself_is_one() -> None:
    values = (Decimal(1), Decimal(3), Decimal(2), Decimal(5))

    assert window_beta((values, values)) == Decimal(1)


def test_beta_scales_with_the_asset_leg() -> None:
    market = (Decimal(1), Decimal(2), Decimal(4))
    doubled = tuple(value * 2 for value in market)

    assert window_beta((doubled, market)) == Decimal(2)
    assert window_beta((tuple(-value for value in market), market)) == Decimal(-1)


def test_statistics_refuse_where_the_answer_would_be_invented() -> None:
    flat = (Decimal(3), Decimal(3), Decimal(3))

    with pytest.raises(ValueError, match="no spread"):
        window_skewness((flat,))
    with pytest.raises(ValueError, match="no variance"):
        window_beta(((Decimal(1), Decimal(2), Decimal(3)), flat))
    with pytest.raises(ValueError, match="at least two"):
        window_stdev(((Decimal(1),),))


def test_skewness_sees_the_direction_of_the_tail() -> None:
    right = (Decimal(1), Decimal(1), Decimal(1), Decimal(9))
    left = tuple(-value for value in right)

    assert window_skewness((right,)) > 0
    assert window_skewness((left,)) < 0
    assert window_skewness((right,)) == -window_skewness((left,))
