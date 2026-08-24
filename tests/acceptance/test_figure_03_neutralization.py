"""Figure 3, reproduced against a contract computed outside this repository's own arithmetic.

The figure makes two claims and this file asserts both, because a previous revision of the plan
silently dropped the second and the review lanes caught it:

1. neutralising the signal drops its annualised return substantially, and
2. it drives the market beta toward zero.

Neither claim survives an identity transform, and each is checked so that it would go red if the
transform became one. The mutation gate at the end is what proves the assertions are live rather
than merely arithmetically true.

**The target is recomputed, not quoted.** The published bm-scaled figures were computed over
2018-01-02 to 2026-07-28, and that input no longer exists — the reference build cache was
regenerated over a shorter window, and no panel anywhere spans the published range. Retargeting to
the window that exists was the user's decision, taken over weakening the criterion, and the fixture
manifest records what it departed from. What survives is that the target is still produced by the
report's own recipe from the report's own panels; what is lost is the ability to quote the published
numbers, and this file says so rather than implying otherwise.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vqapr.public import neutralize

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "report_figure_03"

# The generator owns the two recipe functions that carry reconciliations. Importing them rather
# than re-typing them means those guards run on every invocation of this test, and removes the
# possibility of two copies drifting apart -- which is exactly what happened once, when the guards
# were restored in one place and not the other.
#
# The annualisation helpers below are still written out here. That duplication is safe in a way the
# guard duplication was not: the contract is minted with the generator's version, so any drift in
# them surfaces immediately as a failed reproduction, whereas a dropped guard was silent precisely
# because both copies produced identical numbers.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from extract_report_figure_03_fixture import (  # noqa: E402
    market_demean_preserving_gross as _market_demean_preserving_gross,
)
from extract_report_figure_03_fixture import rolling_beta as _rolling_beta  # noqa: E402

RETURN_CEILING = 1e-3
"""Annualised-return agreement, in return units. The claimed gap is roughly 1875 bp, so this sits
about two hundred times inside it: wide enough for float accumulation order, far too narrow for a
broken transform to slip through."""

RATIO_CEILING = 2e-3
"""Information-ratio agreement, dimensionless. The claimed gap is about 0.196, so this keeps the
same headroom the return ceiling has rather than being a second number chosen by feel."""

BETA_WINDOW = 60
TRADING_DAYS = 252.0


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))["figure_03_contract"]


@pytest.fixture(scope="module")
def panels() -> dict[str, pd.DataFrame]:
    return {
        name: pd.read_parquet(FIXTURE / f"{name}.parquet")
        for name in ("baseline_weight", "universe_mask", "benchmark_weight", "realized_return")
    }


def _annual_mean(series: pd.Series) -> float:
    return float(series.mean() * TRADING_DAYS)


def _information_ratio(series: pd.Series) -> float:
    volatility = float(series.std(ddof=1) * np.sqrt(TRADING_DAYS))
    return _annual_mean(series) / volatility if volatility > 0.0 else float("nan")


def _diagnostic(panels: dict[str, pd.DataFrame], *, demeaned: pd.DataFrame | None = None) -> dict:
    baseline = panels["baseline_weight"]
    universe = panels["universe_mask"].astype(bool)
    realized = panels["realized_return"]
    if demeaned is None:
        demeaned = _market_demean_preserving_gross(baseline, universe | baseline.ne(0.0))

    baseline_return = (baseline * realized).sum(axis=1)
    demeaned_return = (demeaned * realized).sum(axis=1)
    benchmark_return = (panels["benchmark_weight"] * realized).sum(axis=1)
    return {
        "baseline_annualized_return": _annual_mean(baseline_return),
        "baseline_sharpe": _information_ratio(baseline_return),
        "market_demeaned_annualized_return": _annual_mean(demeaned_return),
        "market_demeaned_sharpe": _information_ratio(demeaned_return),
        "baseline_mean_absolute_beta": float(
            _rolling_beta(baseline_return, benchmark_return, window=BETA_WINDOW).abs().mean()
        ),
        "market_demeaned_mean_absolute_beta": float(
            _rolling_beta(demeaned_return, benchmark_return, window=BETA_WINDOW).abs().mean()
        ),
        "baseline_mean_beta": float(
            _rolling_beta(baseline_return, benchmark_return, window=BETA_WINDOW).mean()
        ),
        "market_demeaned_mean_beta": float(
            _rolling_beta(demeaned_return, benchmark_return, window=BETA_WINDOW).mean()
        ),
    }


def test_the_sign_of_the_beta_is_pinned(contract: dict, panels: dict) -> None:
    """An absolute mean cannot see a sign flip, so the signed mean is asserted too.

    Every other beta assertion in this file consumes the series through `.abs().mean()`, which is
    sign-invariant: a systematically negated implementation reproduces all of them exactly and
    stays invisible. The contract records the signed mean as well, and this pins it.
    """
    observed = _diagnostic(panels)

    for quantity in ("baseline_mean_beta", "market_demeaned_mean_beta"):
        assert abs(observed[quantity] - contract[quantity]) < RATIO_CEILING

    assert contract["baseline_mean_beta"] > 0, (
        "a long book measured against its own benchmark carries positive beta; a negative value "
        "here would mean the sign convention had inverted"
    )


def test_vqapr_neutralisation_matches_a_market_demean(panels: dict) -> None:
    """Neutralizing against a column of ones equals direct mean subtraction."""
    baseline = panels["baseline_weight"]
    universe = panels["universe_mask"].astype(bool) | baseline.ne(0.0)

    compared = 0
    for position in range(0, len(baseline), 400):
        date = baseline.index[position]
        members = [name for name in baseline.columns if bool(universe.loc[date, name])]
        if len(members) < 3:
            continue
        row = {name: Decimal(str(baseline.loc[date, name])) for name in members}

        centre = sum(row.values(), Decimal(0)) / len(row)
        centred = {name: value - centre for name, value in row.items()}
        residual = neutralize(row, exposures={"market": dict.fromkeys(members, Decimal(1))})

        for name in members:
            assert abs(centred[name] - residual[name]) < Decimal("1E-11"), (
                f"demean and neutralize disagree at {date} on {name}"
            )
        compared += 1

    assert compared >= 3


def test_the_return_claim_reproduces(contract: dict, panels: dict) -> None:
    observed = _diagnostic(panels)

    assert (
        abs(observed["baseline_annualized_return"] - contract["baseline_annualized_return"])
        < RETURN_CEILING
    )
    assert (
        abs(
            observed["market_demeaned_annualized_return"]
            - contract["market_demeaned_annualized_return"]
        )
        < RETURN_CEILING
    )


def test_the_information_ratio_claim_reproduces(contract: dict, panels: dict) -> None:
    observed = _diagnostic(panels)

    assert abs(observed["baseline_sharpe"] - contract["baseline_sharpe"]) < RATIO_CEILING
    assert (
        abs(observed["market_demeaned_sharpe"] - contract["market_demeaned_sharpe"]) < RATIO_CEILING
    )


def test_neutralisation_drops_the_return_substantially(contract: dict) -> None:
    """The first half of the figure's claim, as a relation rather than as two numbers."""
    gap = contract["baseline_annualized_return"] - contract["market_demeaned_annualized_return"]

    assert gap > 0.01, "the drop must be large enough to be a finding rather than noise"
    assert gap / RETURN_CEILING > 100, "the ceiling must sit far inside the claimed gap"


def test_neutralisation_drives_the_beta_toward_zero(contract: dict, panels: dict) -> None:
    """The second half — the one a previous plan revision dropped.

    Asserted as a strict inequality against the baseline and as proximity to zero, because a book
    that still carried half the market's beta would satisfy the inequality while failing the claim.
    """
    observed = _diagnostic(panels)

    assert observed["market_demeaned_mean_absolute_beta"] < observed["baseline_mean_absolute_beta"]
    assert observed["market_demeaned_mean_absolute_beta"] < 0.25
    assert (
        abs(observed["baseline_mean_absolute_beta"] - contract["baseline_mean_absolute_beta"])
        < RATIO_CEILING
    )
    assert (
        abs(
            observed["market_demeaned_mean_absolute_beta"]
            - contract["market_demeaned_mean_absolute_beta"]
        )
        < RATIO_CEILING
    )


@pytest.mark.parametrize(
    "quantity",
    [
        "baseline_annualized_return",
        "market_demeaned_annualized_return",
        "baseline_sharpe",
        "market_demeaned_sharpe",
    ],
)
def test_perturbing_an_input_turns_each_asserted_quantity_red(
    contract: dict, panels: dict, quantity: str
) -> None:
    """Perturb an **input** and require the reproduction to fail.

    Adding an offset to the computed output and then asserting the offset is large enough is an
    arithmetic identity that holds whenever the reproduction test already passes. The perturbation
    therefore goes into the return panel, and the assertion is that the recomputed value moves
    outside its ceiling.

    The perturbation changes the cross-sectional *shape* rather than the scale. A uniform rescale
    would move both annualised returns and leave both information ratios exactly where they were,
    since numerator and denominator scale together — writing this test the naive way surfaced that
    immediately, which is the point of perturbing an input rather than an output.
    """
    ceiling = RETURN_CEILING if "return" in quantity else RATIO_CEILING

    shifted = panels["realized_return"].copy()
    # Sorted rather than parquet order, so which names are perturbed does not depend on how the
    # panel happened to be written.
    #
    # Fifty basis points, sized by measurement rather than by feel. The demeaned book sums to
    # roughly zero by construction, so a shift applied to half the cross-section largely cancels
    # against itself: at 10 bp the demeaned return moved only 1.6 ceilings while the baseline moved
    # 54. At 50 bp the smallest of the four headrooms is 7.8 ceilings, which is why the assertion
    # below can demand three and still be describing a real margin.
    half = sorted(shifted.columns)[::2]
    shifted[half] = shifted[half] + 0.005

    tampered = dict(panels)
    tampered["realized_return"] = shifted

    observed = _diagnostic(tampered)

    assert abs(observed[quantity] - contract[quantity]) >= ceiling * 3, (
        f"a 50 bp additive shift on half the cross-section did not move {quantity} "
        "clear of its ceiling"
    )


def test_an_unperturbed_run_stays_inside_every_ceiling(contract: dict, panels: dict) -> None:
    """The control for the mutation above: without the perturbation, all four agree."""
    observed = _diagnostic(panels)

    for quantity in (
        "baseline_annualized_return",
        "market_demeaned_annualized_return",
        "baseline_sharpe",
        "market_demeaned_sharpe",
    ):
        ceiling = RETURN_CEILING if "return" in quantity else RATIO_CEILING
        assert abs(observed[quantity] - contract[quantity]) < ceiling


def test_an_identity_demean_fails_the_beta_clause(contract: dict, panels: dict) -> None:
    """Run the *published* beta clause against an identity demean and require it to fail.

    An earlier version of this test asserted that the two beta series were equal under an identity
    substitution. That is `a == a`: the substitution makes the demeaned return the same expression
    as the baseline return, so the assertion held for any beta implementation at all, including a
    constant stub. It certified nothing.

    What is asserted now is the clause the milestone actually claims — the demeaned book's mean
    absolute beta is strictly below the baseline's and close to zero — evaluated against the
    identity diagnostic, with the requirement that it **does not hold**.
    """
    identity = _diagnostic(panels, demeaned=panels["baseline_weight"])

    # Note what this one does and does not prove. Under the identity substitution the demeaned
    # return is the same expression as the baseline return, so this inequality is `not (a < a)` and
    # holds for any beta implementation at all. It is kept because it still catches a `_diagnostic`
    # that ignored its own `demeaned=` override, and for nothing else. The assertion below is the
    # one that makes the clause falsifiable.
    strictly_lower = (
        identity["market_demeaned_mean_absolute_beta"] < identity["baseline_mean_absolute_beta"]
    )
    matches_contract = (
        abs(
            identity["market_demeaned_mean_absolute_beta"]
            - contract["market_demeaned_mean_absolute_beta"]
        )
        < RATIO_CEILING
    )

    assert not strictly_lower, "an identity demean must fail the strict beta inequality"
    assert not matches_contract, "an identity demean must not reproduce the demeaned beta"


@pytest.mark.parametrize(
    "quantity",
    [
        "baseline_mean_absolute_beta",
        "market_demeaned_mean_absolute_beta",
        "baseline_mean_beta",
        "market_demeaned_mean_beta",
    ],
)
def test_perturbing_the_benchmark_turns_each_beta_red(
    contract: dict, panels: dict, quantity: str
) -> None:
    """Beta needs its own input perturbation, and the benchmark is the one that moves it.

    Perturbing the return panel moves the returns and the betas together, so it cannot show that
    the beta numbers are live independently. The benchmark weight enters only through the benchmark
    return series, which is the denominator and the covariance partner of both betas and touches
    neither annualised return — so this isolates exactly the half of the claim the identity case
    alone could never certify.
    """
    # Sorted, not parquet order, for the same reason the return gate is: which names move must not
    # depend on how the panel happened to be written. Measured headroom under this permutation is
    # 18.8 ceilings on the baseline beta and 5.1 on the demeaned one, so demanding three is a real
    # margin rather than a hopeful one.
    shifted = panels["benchmark_weight"].copy()
    reversed_columns = sorted(shifted.columns)[::-1]
    shifted[sorted(shifted.columns)] = shifted[reversed_columns].to_numpy()

    tampered = dict(panels)
    tampered["benchmark_weight"] = shifted

    observed = _diagnostic(tampered)
    unperturbed = _diagnostic(panels)

    assert abs(observed[quantity] - contract[quantity]) >= RATIO_CEILING * 3, (
        f"reversing the benchmark weights did not move {quantity} clear of its ceiling"
    )
    assert abs(unperturbed[quantity] - contract[quantity]) < RATIO_CEILING, (
        f"the unperturbed run must still reproduce {quantity}"
    )


def test_an_identity_demean_fails_the_return_clause(contract: dict, panels: dict) -> None:
    identity = _diagnostic(panels, demeaned=panels["baseline_weight"])

    assert (
        abs(
            identity["market_demeaned_annualized_return"]
            - contract["market_demeaned_annualized_return"]
        )
        > RETURN_CEILING
    )


def test_the_target_declares_that_it_is_recomputed() -> None:
    """A reader must not be able to mistake these for the published figures."""
    manifest = json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))

    assert manifest["retarget"]["published_range"]["observations"] == 2102
    assert manifest["span"]["observations"] == 1562
    assert manifest["retarget"]["authority"].startswith("None upstream")
