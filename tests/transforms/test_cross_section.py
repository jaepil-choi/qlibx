"""Cross-sectional operations, and the missing-value choices that precede them."""

from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr.transforms.cross_section import demean, quantile_buckets, rank, winsorize, zscore
from vqapr.transforms.missing import drop_missing, require_complete


def _values(**pairs: str) -> dict[str, Decimal]:
    return {name: Decimal(value) for name, value in pairs.items()}


def test_ties_share_a_rank_so_mapping_order_cannot_break_them() -> None:
    """Order of arrival must not decide a research result."""
    forward = rank(_values(A="10", B="20", C="20", D="40"))
    reversed_order = rank(_values(D="40", C="20", B="20", A="10"))

    assert forward == reversed_order
    assert forward["B"] == forward["C"] == Decimal("2.5")
    assert forward["A"] == Decimal(1)
    assert forward["D"] == Decimal(4)


def test_descending_rank_reverses_the_order_without_disturbing_ties() -> None:
    values = _values(A="10", B="20", C="20", D="40")

    descending = rank(values, ascending=False)

    assert descending["D"] == Decimal(1)
    assert descending["A"] == Decimal(4)
    assert descending["B"] == descending["C"]


def test_demean_removes_the_average_exactly() -> None:
    """The identity that makes this the market-neutral move: what is left sums to zero."""
    centred = demean(_values(A="10", B="20", C="20", D="40"))

    assert sum(centred.values()) == 0
    assert centred["A"] == Decimal("-12.5")


def test_demean_of_an_already_centred_cross_section_changes_nothing() -> None:
    centred = demean(_values(A="-1", B="0", C="1"))

    assert centred == _values(A="-1", B="0", C="1")


def test_zscore_centres_and_scales() -> None:
    scored = zscore(_values(A="10", B="20", C="30"))

    assert sum(scored.values()) == 0
    assert scored["A"] == -scored["C"]
    assert scored["B"] == 0


def test_zscore_refuses_a_flat_cross_section_rather_than_returning_zeros() -> None:
    """Zeros would claim every name sits at the average by measurement rather than by accident."""
    with pytest.raises(ValueError, match="no spread"):
        zscore(_values(A="5", B="5", C="5"))


def test_winsorize_clips_to_the_surviving_boundary_and_keeps_every_name() -> None:
    values = _values(A="1", B="10", C="11", D="12", E="100")

    clipped = winsorize(values, proportion=Decimal("0.2"))

    assert set(clipped) == set(values), "an outlier is still a position"
    assert clipped["A"] == Decimal(10)
    assert clipped["E"] == Decimal(12)
    assert clipped["B"] == Decimal(10) and clipped["C"] == Decimal(11)


def test_winsorize_with_no_trim_is_the_identity() -> None:
    values = _values(A="1", B="10", C="100")

    assert winsorize(values, proportion=Decimal(0)) == values


def test_winsorize_refuses_a_proportion_that_would_trim_everything() -> None:
    for proportion in (Decimal("0.5"), Decimal("0.9"), Decimal("-0.1")):
        with pytest.raises(ValueError, match=r"at least 0 and below 0\.5"):
            winsorize(_values(A="1", B="2"), proportion=proportion)


def test_buckets_are_numbered_from_one_and_follow_the_rank() -> None:
    assigned = quantile_buckets(_values(A="1", B="2", C="3", D="4"), buckets=2)

    assert assigned["A"] == assigned["B"] == 1
    assert assigned["C"] == assigned["D"] == 2


def test_tied_names_share_a_bucket_even_across_a_count_boundary() -> None:
    """A double sort stops being reproducible the moment a tie can straddle a boundary."""
    assigned = quantile_buckets(_values(A="10", B="20", C="20", D="40"), buckets=2)

    assert assigned["B"] == assigned["C"]


def test_buckets_refuse_to_leave_one_empty() -> None:
    with pytest.raises(ValueError, match="would be empty"):
        quantile_buckets(_values(A="1", B="2"), buckets=3)


def test_every_operation_refuses_a_float() -> None:
    bad = {"A": 1.0, "B": Decimal(2)}

    for operation in (rank, demean, zscore):
        with pytest.raises(TypeError, match="must be a Decimal"):
            operation(bad)  # type: ignore[arg-type]


def test_every_operation_refuses_an_empty_cross_section() -> None:
    for operation in (rank, demean, zscore):
        with pytest.raises(ValueError, match="non-empty"):
            operation({})


def test_drop_missing_shrinks_the_cross_section_rather_than_padding_it() -> None:
    """Coverage stays visible in the length instead of hiding behind zeros."""
    kept = drop_missing({"A": Decimal(1), "B": None, "C": Decimal(3)})

    assert kept == {"A": Decimal(1), "C": Decimal(3)}
    assert "B" not in kept


def test_there_is_no_way_to_fill_a_gap_with_zero() -> None:
    """Filling zero is an economic claim, so the package does not offer it as a convenience."""
    import vqapr.transforms.missing as module

    assert not hasattr(module, "fill_missing")
    assert set(module.__all__) == {"drop_missing", "require_complete"}


def test_require_complete_names_what_is_absent() -> None:
    with pytest.raises(ValueError, match=r"no value: \['B', 'D'\]"):
        require_complete(
            {"A": Decimal(1), "B": None, "C": Decimal(3)}, instruments=["A", "B", "C", "D"]
        )


def test_require_complete_returns_the_required_names_in_the_order_asked() -> None:
    complete = require_complete(
        {"C": Decimal(3), "A": Decimal(1), "B": Decimal(2)}, instruments=["A", "B", "C"]
    )

    assert list(complete) == ["A", "B", "C"]


def test_require_complete_ignores_extra_names_it_was_not_asked_about() -> None:
    complete = require_complete(
        {"A": Decimal(1), "B": Decimal(2), "EXTRA": None}, instruments=["A", "B"]
    )

    assert complete == {"A": Decimal(1), "B": Decimal(2)}
