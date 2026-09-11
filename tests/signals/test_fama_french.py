from decimal import Decimal

import pytest

from vqapr.signals.transform import fama_french_assign, fama_french_cut_points


def _values(**pairs: str) -> dict[str, Decimal]:
    return {instrument: Decimal(value) for instrument, value in pairs.items()}


def test_cut_points_use_only_the_reference_market() -> None:
    values = _values(K1="10", K2="20", K3="30", K4="40", Q1="1", Q2="2", Q3="3")

    thresholds = fama_french_cut_points(
        values,
        reference={"K1", "K2", "K3", "K4"},
        fractions=(Decimal("0.5"),),
    )

    assert thresholds == (Decimal("25"),)


def test_reference_thresholds_assign_the_whole_universe_with_unequal_counts() -> None:
    values = _values(K1="10", K2="20", K3="30", K4="40", Q1="1", Q2="2", Q3="3")
    thresholds = fama_french_cut_points(
        values,
        reference={"K1", "K2", "K3", "K4"},
        fractions=(Decimal("0.5"),),
    )

    assigned = fama_french_assign(values, thresholds=thresholds, labels=("S", "B"))

    assert assigned == {
        "K1": "S",
        "K2": "S",
        "K3": "B",
        "K4": "B",
        "Q1": "S",
        "Q2": "S",
        "Q3": "S",
    }


def test_linear_interpolation_matches_the_validated_replication() -> None:
    thresholds = fama_french_cut_points(
        _values(A="0", B="10", C="20", D="30"),
        reference={"A", "B", "C", "D"},
        fractions=(Decimal("0.3"), Decimal("0.7")),
    )

    assert thresholds == (Decimal("9.0"), Decimal("21.0"))


def test_nearest_interpolation_is_explicit_and_changes_membership() -> None:
    values = _values(A="0", B="10", C="20", D="30", X="9.5")
    linear = fama_french_cut_points(
        values,
        reference={"A", "B", "C", "D"},
        fractions=(Decimal("0.3"),),
    )
    nearest = fama_french_cut_points(
        values,
        reference={"A", "B", "C", "D"},
        fractions=(Decimal("0.3"),),
        interpolation="nearest",
    )

    assert linear == (Decimal("9.0"),)
    assert nearest == (Decimal("10"),)
    assert fama_french_assign(values, thresholds=linear, labels=("L", "H"))["X"] == "H"
    assert fama_french_assign(values, thresholds=nearest, labels=("L", "H"))["X"] == "L"


def test_a_value_equal_to_a_threshold_stays_in_the_lower_bucket() -> None:
    assigned = fama_french_assign(
        _values(A="10", B="20", C="30"),
        thresholds=(Decimal("20"),),
        labels=("L", "H"),
    )

    assert assigned == {"A": "L", "B": "L", "C": "H"}


def test_repeated_thresholds_can_leave_a_bucket_empty() -> None:
    assigned = fama_french_assign(
        _values(A="10", B="20"),
        thresholds=(Decimal("10"), Decimal("10")),
        labels=("L", "M", "H"),
    )

    assert assigned == {"A": "L", "B": "H"}


@pytest.mark.parametrize(
    ("fractions", "message"),
    [
        ((), "non-empty"),
        ((Decimal(0),), "strictly between"),
        ((Decimal("0.7"), Decimal("0.3")), "strictly increasing"),
    ],
)
def test_cut_points_refuse_invalid_fractions(
    fractions: tuple[Decimal, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        fama_french_cut_points(
            _values(A="1", B="2"),
            reference={"A", "B"},
            fractions=fractions,
        )


def test_cut_points_refuse_an_empty_reference_sample() -> None:
    with pytest.raises(ValueError, match="reference sample is empty"):
        fama_french_cut_points(
            _values(A="1", B="2"),
            reference={"OUTSIDE"},
            fractions=(Decimal("0.5"),),
        )


def test_assign_refuses_a_label_count_that_cannot_name_every_bucket() -> None:
    with pytest.raises(ValueError, match="one more"):
        fama_french_assign(
            _values(A="1"),
            thresholds=(Decimal("0.5"),),
            labels=("only-one",),
        )
