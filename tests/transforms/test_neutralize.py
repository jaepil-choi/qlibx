"""Neutralisation, checked by the property that kills a no-op.

The falsifier here is weighted orthogonality: the residual is orthogonal to every exposure column
under the weights. An identity transform fails it on the first column, so this is a real check
rather than a restatement of the arithmetic that produced the number.

Orthogonality is asserted on exact rationals before any quantisation, so the primary proof carries
no tolerance to tune.
"""

from __future__ import annotations

import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import duckdb
import pytest

from vqapr.transforms.neutralize import NeutralizationRefusal, neutralize

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "real_k200"


def _values(**pairs: str) -> dict[str, Decimal]:
    return {name: Decimal(value) for name, value in pairs.items()}


def _ones(names) -> dict[str, Decimal]:
    return dict.fromkeys(names, Decimal(1))


def _dot(left: dict[str, Decimal], right: dict[str, Decimal]) -> Fraction:
    return sum((Fraction(left[name]) * Fraction(right[name]) for name in left), Fraction(0))


def test_the_residual_is_exactly_orthogonal_to_a_single_exposure() -> None:
    """Exact, on the rational value, before any quantisation."""
    signal = _values(A="10", B="20", C="30", D="45")

    residual = neutralize(signal, exposures={"market": _ones(signal)})

    assert _dot(residual, _ones(signal)) == 0


def test_the_residual_is_orthogonal_to_every_column_at_once() -> None:
    signal = _values(A="10", B="20", C="30", D="45")
    beta = _values(A="1", B="2", C="3", D="4")

    residual = neutralize(signal, exposures={"market": _ones(signal), "beta": beta})

    assert _dot(residual, _ones(signal)) == 0
    assert _dot(residual, beta) == 0


def test_an_identity_transform_would_fail_the_orthogonality_check() -> None:
    """The falsifier has to kill a no-op, so state the no-op and show it dies."""
    signal = _values(A="10", B="20", C="30", D="45")

    identity = dict(signal)

    assert _dot(identity, _ones(signal)) != 0, "an unneutralised signal is not orthogonal"
    assert _dot(neutralize(signal, exposures={"market": _ones(signal)}), _ones(signal)) == 0


def test_neutralisation_strictly_reduces_weighted_variance() -> None:
    """The second falsifier: a no-op leaves the variance equal rather than smaller."""
    signal = _values(A="10", B="20", C="30", D="45")
    market = _ones(signal)

    residual = neutralize(signal, exposures={"market": market})

    before = sum((Fraction(v) ** 2 for v in signal.values()), Fraction(0))
    after = sum((Fraction(v) ** 2 for v in residual.values()), Fraction(0))
    assert after < before


def test_a_market_column_alone_reproduces_the_demean() -> None:
    """A column of ones is the simplest exposure, and its residual is the centred signal."""
    signal = _values(A="10", B="20", C="30", D="45")

    residual = neutralize(signal, exposures={"market": _ones(signal)})

    centre = sum(signal.values()) / len(signal)
    assert residual == {
        name: (value - centre).quantize(Decimal("1E-12")) for name, value in signal.items()
    }


def test_weights_change_the_answer_and_the_orthogonality_follows_them() -> None:
    signal = _values(A="10", B="20", C="30", D="45")
    market = _ones(signal)
    weights = _values(A="1", B="1", C="1", D="7")

    unweighted = neutralize(signal, exposures={"market": market})
    weighted = neutralize(signal, exposures={"market": market}, weights=weights)

    assert weighted != unweighted
    assert sum((Fraction(weights[n]) * Fraction(weighted[n]) for n in signal), Fraction(0)) == 0


def test_a_dependent_exposure_is_refused_by_name() -> None:
    """Exact zero pivot, not a small one: the refusal can name the column instead of guessing."""
    signal = _values(A="10", B="20", C="30", D="45")
    market = _ones(signal)

    with pytest.raises(NeutralizationRefusal, match=r"'b' is linearly dependent"):
        neutralize(signal, exposures={"a": market, "b": market})


def test_a_missing_loading_is_not_a_zero_loading() -> None:
    signal = _values(A="10", B="20", C="30", D="45")

    with pytest.raises(NeutralizationRefusal, match="no loading"):
        neutralize(signal, exposures={"market": _values(A="1", B="1", C="1")})


def test_too_few_instruments_for_the_exposures_is_refused() -> None:
    signal = _values(A="10", B="20")

    with pytest.raises(NeutralizationRefusal, match="zero by construction"):
        neutralize(
            signal,
            exposures={"a": _values(A="1", B="1"), "b": _values(A="1", B="2")},
        )


def test_negative_or_empty_weights_are_refused() -> None:
    signal = _values(A="10", B="20", C="30", D="45")
    market = _ones(signal)

    with pytest.raises(NeutralizationRefusal, match="not be negative"):
        neutralize(
            signal, exposures={"market": market}, weights=_values(A="-1", B="1", C="1", D="1")
        )

    with pytest.raises(NeutralizationRefusal, match="not all be zero"):
        neutralize(
            signal, exposures={"market": market}, weights=_values(A="0", B="0", C="0", D="0")
        )


def test_a_real_thin_industry_makes_the_matrix_singular_and_it_is_named() -> None:
    """The rank-deficiency case, on real classifications rather than an invented matrix.

    A single-name industry gives a dummy column that is linearly dependent once a market column is
    present: the market column already carries that instrument's only loading. The refusal must
    name the industry rather than reporting an unusable number.
    """
    manifest = json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))
    thin = manifest["single_name_industries"][0]

    connection = duckdb.connect()
    try:
        rows = connection.execute(
            f"""
            SELECT ticker, industry_code
            FROM read_parquet('{(FIXTURE / "cross_section.parquet").as_posix()}')
            WHERE date = DATE '{thin["date"]}'
            ORDER BY ticker
            """
        ).fetchall()
    finally:
        connection.close()

    members = {str(row[0]): int(row[1]) for row in rows}
    lonely = thin["industry_code"]
    assert sum(1 for code in members.values() if code == lonely) == 1

    # Keep the lonely name and enough others that the refusal is about dependence rather than
    # about having fewer instruments than exposures.
    others = [name for name, code in members.items() if code != lonely][:8]
    only = next(name for name, code in members.items() if code == lonely)
    chosen = [only, *others]

    signal = {name: Decimal(index + 1) for index, name in enumerate(chosen)}
    market = _ones(signal)
    lonely_dummy = {name: Decimal(1 if members[name] == lonely else 0) for name in chosen}
    other_dummy = {name: Decimal(1 if members[name] != lonely else 0) for name in chosen}

    with pytest.raises(NeutralizationRefusal, match="linearly dependent"):
        neutralize(
            signal,
            exposures={"market": market, "thin": lonely_dummy, "rest": other_dummy},
        )


def test_neutralisation_never_grows_a_constraint_shape() -> None:
    """A transform takes values and returns values. A constraint is a different thing entirely."""
    import vqapr.transforms.neutralize as module

    for forbidden in ("constraint_id", "requirements", "project", "measure", "ConstraintFinding"):
        assert not hasattr(module, forbidden)
    assert set(module.__all__) == {"NeutralizationRefusal", "neutralize"}
