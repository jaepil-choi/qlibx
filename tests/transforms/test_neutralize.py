"""Neutralisation, checked by the property that kills a no-op.

The falsifier here is weighted orthogonality: the residual is orthogonal to every exposure column
under the weights. An identity transform fails it on the first column, so this is a real check
rather than a restatement of the arithmetic that produced the number.

Orthogonality is asserted by rebuilding rationals from the returned values, which carry twelve-place
quantisation, so the comparison is against that quantum rather than a bare zero. The solve itself is
exact; what rounds is the boundary crossing on the way out.
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


def _orthogonal(
    residual: dict[str, Decimal],
    column: dict[str, Decimal],
    *,
    weights: dict[str, Decimal] | None = None,
) -> bool:
    """Orthogonal to within the quantum the returned values carry.

    The solve is exact and the residual is exactly orthogonal before it is returned, but the
    returned Decimals are rounded to twelve places, so what a caller can observe is agreement at
    that scale. The budget is the term count times the quantum times the column's largest loading,
    because each term carries at most one quantum of rounding.

    This is still a real falsifier: an identity transform misses by orders of magnitude, not by a
    rounding step.
    """
    if weights is None:
        loading = dict(column)
    else:
        loading = {name: column[name] * weights[name] for name in residual}
    largest = max((abs(Fraction(value)) for value in loading.values()), default=Fraction(1))
    return abs(_dot(residual, loading)) <= Fraction(len(residual)) * Fraction(1, 10**12) * largest


def test_the_residual_is_orthogonal_to_a_single_exposure() -> None:
    """Agreement at the returned quantum, which is what a caller can actually observe."""
    signal = _values(A="10", B="20", C="30", D="45")

    residual = neutralize(signal, exposures={"market": _ones(signal)})

    assert _orthogonal(residual, _ones(signal))


def test_the_residual_is_orthogonal_to_every_column_at_once() -> None:
    signal = _values(A="10", B="20", C="30", D="45")
    beta = _values(A="1", B="2", C="3", D="4")

    residual = neutralize(signal, exposures={"market": _ones(signal), "beta": beta})

    assert _orthogonal(residual, _ones(signal))
    assert _orthogonal(residual, beta)


def test_an_identity_transform_would_fail_the_orthogonality_check() -> None:
    """The falsifier has to kill a no-op, so state the no-op and show it dies."""
    signal = _values(A="10", B="20", C="30", D="45")

    identity = dict(signal)

    assert _dot(identity, _ones(signal)) != 0, "an unneutralised signal is not orthogonal"
    assert _orthogonal(neutralize(signal, exposures={"market": _ones(signal)}), _ones(signal))


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
    assert _orthogonal(weighted, _ones(signal), weights=weights)


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


def test_a_dependent_exposure_set_from_real_classifications_is_refused_by_name() -> None:
    """Rank deficiency on real classifications rather than an invented matrix — and only that.

    An earlier version of this test claimed the single-name industry was what made the matrix
    singular. It is not, and the test could not have told the difference: the exposure set it built
    was a market column plus a complete partition into two dummies, and a complete partition sums
    to the market column for **any** widths, so it would have passed identically with a fifty-name
    industry. The claim was unfalsifiable and the mechanism was wrong.

    What is actually true is asserted below in both directions: a complete dummy set alongside a
    market column is exactly dependent and is refused by name, while the same single-name industry
    on its own is accepted, because `{market, thin}` has determinant `n - 1` rather than zero.

    `neutralize` performs no within-group centring, which is the operation that would make a
    one-member group vanish, so nothing in the shipped code makes thinness special.
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

    others = [name for name, code in members.items() if code != lonely][:8]
    single = next(name for name, code in members.items() if code == lonely)
    chosen = [single, *others]

    signal = {name: Decimal(index + 1) for index, name in enumerate(chosen)}
    market = _ones(signal)
    lonely_dummy = {name: Decimal(1 if members[name] == lonely else 0) for name in chosen}
    other_dummy = {name: Decimal(1 if members[name] != lonely else 0) for name in chosen}

    # A market column plus a complete set of industry dummies is the classic dummy trap: the
    # dummies sum to the market column exactly, so the set is dependent and must be refused.
    with pytest.raises(NeutralizationRefusal, match="linearly dependent"):
        neutralize(
            signal,
            exposures={"market": market, "thin": lonely_dummy, "rest": other_dummy},
        )

    # And now the part that keeps the claim honest. Thinness is **not** what causes the refusal.
    # Dropping the complement leaves {market, thin}, whose normal matrix has determinant
    # len(chosen) - 1, so a genuine single-name industry is accepted rather than refused.
    accepted = neutralize(signal, exposures={"market": market, "thin": lonely_dummy})
    assert _orthogonal(accepted, market)
    assert _orthogonal(accepted, lonely_dummy)


def test_neutralisation_never_grows_a_constraint_shape() -> None:
    """A transform takes values and returns values. A constraint is a different thing entirely."""
    import vqapr.transforms.neutralize as module

    for forbidden in ("constraint_id", "requirements", "project", "measure", "ConstraintFinding"):
        assert not hasattr(module, forbidden)
    assert set(module.__all__) == {"NeutralizationRefusal", "neutralize"}
