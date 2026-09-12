from decimal import Decimal

import pytest

from vqapr.signals.transform import rank


def _values(**pairs: str) -> dict[str, Decimal]:
    return {instrument: Decimal(value) for instrument, value in pairs.items()}


def test_rank_starts_at_one_and_averages_tied_positions() -> None:
    ranked = rank(_values(A="10", B="20", C="20", D="40"))

    assert ranked == {
        "A": Decimal(1),
        "B": Decimal("2.5"),
        "C": Decimal("2.5"),
        "D": Decimal(4),
    }


def test_descending_rank_reverses_the_order_without_splitting_ties() -> None:
    ranked = rank(_values(A="10", B="20", C="20", D="40"), ascending=False)

    assert ranked == {
        "A": Decimal(4),
        "B": Decimal("2.5"),
        "C": Decimal("2.5"),
        "D": Decimal(1),
    }


def test_rank_is_mapping_order_independent() -> None:
    expected = rank(_values(A="10", B="20", C="20", D="40"))
    reversed_input = dict(reversed(tuple(_values(A="10", B="20", C="20", D="40").items())))

    assert rank(reversed_input) == expected


def test_rank_refuses_a_float() -> None:
    with pytest.raises(TypeError, match="must be a Decimal"):
        rank({"A": 1.0})  # type: ignore[dict-item]


def test_rank_refuses_an_empty_cross_section() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        rank({})
