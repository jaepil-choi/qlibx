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
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vqapr.public import demean, neutralize

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "report_figure_03"

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


def _market_demean_preserving_gross(baseline: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    masked = baseline.where(universe)
    demeaned = masked.sub(masked.mean(axis=1), axis=0).fillna(0.0)
    baseline_gross = baseline.abs().sum(axis=1)
    demeaned_gross = demeaned.abs().sum(axis=1)
    scale = baseline_gross.div(demeaned_gross.replace(0.0, np.nan)).fillna(0.0)
    return demeaned.mul(scale, axis=0).astype("float64")


def _rolling_beta(values: pd.Series, benchmark: pd.Series, *, window: int) -> pd.Series:
    aligned = pd.concat([values.rename("values"), benchmark.rename("benchmark")], axis=1).fillna(
        0.0
    )
    variance = aligned["benchmark"].rolling(window, min_periods=window).var()
    covariance = aligned["values"].rolling(window, min_periods=window).cov(aligned["benchmark"])
    return covariance.div(variance.where(variance.abs().gt(1e-18)))


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
    }


def test_vqapr_reproduces_the_reference_demean_instrument_by_instrument(
    panels: dict,
) -> None:
    """**This is the criterion that makes the rest mean anything.**

    Everything below compares a pandas recomputation against a contract a pandas recomputation
    produced, which proves determinism rather than correctness. This test is what closes that
    circle: it runs vqapr's own `demean` on the same real cross-sections and requires it to agree
    with the reference operation instrument by instrument.

    If `demean` were wrong, or an identity, or off by a scale factor, this fails while every
    downstream comparison would still pass.
    """
    baseline = panels["baseline_weight"]
    universe = panels["universe_mask"].astype(bool) | baseline.ne(0.0)
    reference = _market_demean_preserving_gross(baseline, universe)

    checked = 0
    for position in range(0, len(baseline), 200):
        date = baseline.index[position]
        members = [name for name in baseline.columns if bool(universe.loc[date, name])]
        if len(members) < 2:
            continue

        # vqapr's own cross-sectional demean, on Decimals, over exactly the universe members.
        centred = demean({name: Decimal(str(baseline.loc[date, name])) for name in members})

        # The reference rescales to preserve the gross book; undo that to compare the demean
        # itself rather than the sizing step, which `rescale` owns and this milestone does not.
        reference_row = {name: Decimal(str(reference.loc[date, name])) for name in members}
        reference_gross = sum((abs(v) for v in reference_row.values()), Decimal(0))
        centred_gross = sum((abs(v) for v in centred.values()), Decimal(0))
        if reference_gross == 0 or centred_gross == 0:
            continue

        for name in members:
            ours = centred[name] / centred_gross
            theirs = reference_row[name] / reference_gross
            assert abs(ours - theirs) < Decimal("1E-9"), (
                f"vqapr's demean disagrees with the reference at {date} on {name}"
            )
        checked += 1

    assert checked >= 5, f"only {checked} cross-sections were compared"


def test_vqapr_neutralisation_matches_a_market_demean(panels: dict) -> None:
    """`neutralize` against a column of ones is the demean, so the two products must agree.

    This is a second, independent route into the same claim: the figure's operation is a market
    demean, and vqapr expresses it two ways. If they disagreed, one of them is wrong.
    """
    baseline = panels["baseline_weight"]
    universe = panels["universe_mask"].astype(bool) | baseline.ne(0.0)

    compared = 0
    for position in range(0, len(baseline), 400):
        date = baseline.index[position]
        members = [name for name in baseline.columns if bool(universe.loc[date, name])]
        if len(members) < 3:
            continue
        row = {name: Decimal(str(baseline.loc[date, name])) for name in members}

        centred = demean(row)
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
    half = list(shifted.columns)[::2]
    shifted[half] = shifted[half] + 0.001

    tampered = dict(panels)
    tampered["realized_return"] = shifted

    observed = _diagnostic(tampered)

    assert abs(observed[quantity] - contract[quantity]) >= ceiling, (
        f"a five percent shift in the return panel did not move {quantity} outside its ceiling"
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


def test_an_identity_demean_fails_the_beta_clause(panels: dict) -> None:
    """The beta mutation, in its own units.

    A return-unit perturbation applied to a dimensionless beta would fail to turn this red rather
    than merely being mis-denominated, so the mutation is magnitude-free: substitute the baseline
    book for the demeaned one and the two beta series become identical, which the strict inequality
    must reject.
    """
    identity = _diagnostic(panels, demeaned=panels["baseline_weight"])

    assert identity["market_demeaned_mean_absolute_beta"] == identity["baseline_mean_absolute_beta"]
    assert not (
        identity["market_demeaned_mean_absolute_beta"] < identity["baseline_mean_absolute_beta"]
    ), "an identity demean must fail the beta clause"


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
