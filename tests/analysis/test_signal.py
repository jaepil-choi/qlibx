"""Signal statistics, anchored on identities the data itself fixes.

The anchors here are exact and derived from the values rather than from a number this milestone
also wrote. A signal correlated with itself must be one; negating the signal must flip the sign; a
perfect-foresight signal built from the outcome must score strongly positive rather than negative.
A sign error cannot survive any of them, which is what makes them anchors rather than restatements.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from vqapr.analysis.signal import (
    decay,
    hit_rate,
    information_coefficient,
    rank_information_coefficient,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "real_k200"


def _values(**pairs: str) -> dict[str, Decimal]:
    return {name: Decimal(value) for name, value in pairs.items()}


@pytest.fixture(scope="module")
def realized() -> dict[str, Decimal]:
    """Real returns from the committed vendor slice, so the anchors run on market data."""
    manifest = json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))
    date = manifest["classification_dates"][-1]
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            f"""
            SELECT ticker, return
            FROM read_parquet('{(FIXTURE / "returns.parquet").as_posix()}')
            WHERE date = DATE '{date}' AND return IS NOT NULL
            ORDER BY ticker LIMIT 40
            """
        ).fetchall()
    finally:
        connection.close()
    return {str(row[0]): Decimal(str(row[1])) for row in rows}


def test_a_signal_correlated_with_itself_is_exactly_one(realized: dict) -> None:
    assert information_coefficient(realized, realized) == 1
    assert rank_information_coefficient(realized, realized) == 1


def test_negating_the_signal_flips_the_sign_exactly(realized: dict) -> None:
    """A sign error anywhere in the computation dies here."""
    negated = {name: -value for name, value in realized.items()}

    assert information_coefficient(negated, realized) == -information_coefficient(
        realized, realized
    )
    assert information_coefficient(negated, realized) == -1


def test_a_perfect_foresight_signal_scores_strongly_positive(realized: dict) -> None:
    """Built from the outcome itself, so a negative score would mean the sign is inverted."""
    foresight = dict(realized)

    assert information_coefficient(foresight, realized) > Decimal("0.99")
    assert rank_information_coefficient(foresight, realized) > Decimal("0.99")
    assert hit_rate(foresight, realized) == 1


def test_a_reversed_signal_scores_strongly_negative(realized: dict) -> None:
    reversed_signal = {name: -value for name, value in realized.items()}

    assert information_coefficient(reversed_signal, realized) < Decimal("-0.99")
    assert hit_rate(reversed_signal, realized) == 0


def test_the_rank_form_ignores_the_size_of_one_extreme_name() -> None:
    """Which is the whole reason the rank form exists."""
    signal = _values(A="1", B="2", C="3", D="4")
    outcome = _values(A="1", B="2", C="3", D="1000")

    assert rank_information_coefficient(signal, outcome) == 1
    assert information_coefficient(signal, outcome) < 1


def test_only_instruments_present_on_both_sides_are_used() -> None:
    """A name with a signal and no outcome contributes nothing; a zero would be an invention."""
    signal = _values(A="1", B="2", C="3", ORPHAN="99")
    outcome = _values(A="1", B="2", C="3")

    assert information_coefficient(signal, outcome) == 1


def test_hit_rate_excludes_names_with_no_direction() -> None:
    signal = _values(A="1", B="-1", C="0")
    outcome = _values(A="1", B="-1", C="1")

    assert hit_rate(signal, outcome) == 1, "a zero signal expresses no direction"


def test_hit_rate_counts_disagreement() -> None:
    signal = _values(A="1", B="1", C="-1", D="-1")
    outcome = _values(A="1", B="-1", C="-1", D="1")

    assert hit_rate(signal, outcome) == Decimal("0.5")


def test_decay_reports_one_value_per_horizon_in_order(realized: dict) -> None:
    negated = {name: -value for name, value in realized.items()}

    produced = decay(realized, [realized, negated])

    assert len(produced) == 2
    assert produced[0] == 1 and produced[1] == -1


def test_a_flat_side_is_refused_rather_than_reported_as_zero() -> None:
    flat = _values(A="1", B="1", C="1")
    varied = _values(A="1", B="2", C="3")

    for signal, outcome in ((flat, varied), (varied, flat)):
        with pytest.raises(ValueError, match="no spread"):
            information_coefficient(signal, outcome)


def test_too_few_shared_instruments_is_refused() -> None:
    with pytest.raises(ValueError, match="at least two instruments"):
        information_coefficient(_values(A="1"), _values(A="1"))


def test_floats_are_refused() -> None:
    with pytest.raises(TypeError, match="must be a Decimal"):
        information_coefficient({"A": 1.0, "B": Decimal(2)}, _values(A="1", B="2"))
