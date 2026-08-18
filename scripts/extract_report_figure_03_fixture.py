"""Extract the figure-3 neutralisation panels into a committed, self-pinned fixture.

Why this exists
---------------
`tests/fixtures/report_figure_03/` holds the input to the one acceptance test that compares vqapr's
neutralisation against an outside result. `data/` is gitignored and the reference project is a
separate repository, so a clean checkout can only run that test against a committed excerpt.

Why the target is recomputed rather than quoted
-----------------------------------------------
The published bm-scaled report states its figure-3 numbers over 2018-01-02 to 2026-07-28, 2102
observations. **That input no longer exists.** The build cache in the reference project was
regenerated over a shorter window: every panel now spans 2020-01-03 to 2026-05-22, and no panel
anywhere in that repository covers the published range. Each of the three source hashes the
bm-scaled manifest records also fails against what is on disk, and against the older manifest's
hashes, so the cache is a third state rather than a recoverable earlier one.

The choice was the user's, and it was to **retarget to the available window** rather than to weaken
the criterion. So this generator applies the report's own recipe — unchanged, transcribed from
`build_report_assets.py` — to the panels that do exist, and pins the result. What is preserved is
that the target is still computed by somebody else's method from somebody else's data. What is lost
is the ability to quote the published figures, and this file records both facts rather than
implying the numbers came from the report.

Provenance
----------
Because the target is recomputed, the upstream manifest carries **no authority** over it, and the
panels are pinned by their own hashes. The manifest's hash is recorded anyway, so a later reader can
see which report build this was retargeted away from.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REFERENCE = Path("C:/Users/chlje/DevProjects/kwam-enhanced-index")
CACHE = REFERENCE / "outputs/cache/run_alpha_ensembles/price_alpha"
MANIFEST = REFERENCE / "docs/report/enhanced-index-2/report-assets-bm-scaled/manifest.json"
PRICES = Path("data/preprocessed/adjusted_prices.parquet")
FIXTURE = Path("tests/fixtures/report_figure_03")

SOURCES = {
    "desired_weight": CACHE / "members/open_close_rebound/desired_weight.parquet",
    "universe_mask": CACHE / "shared/universe_mask.parquet",
    "benchmark_weight": CACHE / "shared/benchmark_weight.parquet",
}
BETA_WINDOW = 60
TRADING_DAYS = 252.0


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def market_demean_preserving_gross(baseline: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    """The report's own operation, transcribed unchanged.

    Demean across the cross-section, then rescale each date so the gross book is the size it was
    before. Names outside the universe are missing rather than zero, so they do not enter the mean.
    """
    if not baseline.index.equals(universe.index) or not baseline.columns.equals(universe.columns):
        raise ValueError("baseline weight and neutralisation universe axes must match")
    masked = baseline.where(universe)
    demeaned = masked.sub(masked.mean(axis=1), axis=0).fillna(0.0)
    baseline_gross = baseline.abs().sum(axis=1)
    demeaned_gross = demeaned.abs().sum(axis=1)
    scale = baseline_gross.div(demeaned_gross.replace(0.0, np.nan)).fillna(0.0)
    matched = demeaned.mul(scale, axis=0).astype("float64")

    # The upstream operation carries two reconciliations, and dropping them would leave nothing
    # checking the gross-preservation step: the acceptance test deliberately divides it out to
    # compare the demean itself.
    erased = baseline_gross.gt(0.0) & matched.abs().sum(axis=1).eq(0.0)
    if erased.any():
        dates = [str(value)[:10] for value in matched.index[erased][:3]]
        raise ValueError(f"the market demean erased non-zero weight on {dates}")
    gross_error = matched.abs().sum(axis=1).sub(baseline_gross).abs().max()
    if float(gross_error) > 1e-10:
        raise ValueError(f"gross reconciliation failed by {float(gross_error)}")
    return matched


def rolling_beta(values: pd.Series, benchmark: pd.Series, *, window: int) -> pd.Series:
    """The report's own rolling beta, transcribed unchanged."""
    aligned = pd.concat([values.rename("values"), benchmark.rename("benchmark")], axis=1).fillna(
        0.0
    )
    variance = aligned["benchmark"].rolling(window, min_periods=window).var()
    covariance = aligned["values"].rolling(window, min_periods=window).cov(aligned["benchmark"])
    return covariance.div(variance.where(variance.abs().gt(1e-18)))


def _annual_mean(series: pd.Series) -> float:
    return float(series.mean() * TRADING_DAYS)


def _annual_vol(series: pd.Series) -> float:
    return float(series.std(ddof=1) * np.sqrt(TRADING_DAYS))


def _information_ratio(series: pd.Series) -> float:
    volatility = _annual_vol(series)
    return _annual_mean(series) / volatility if volatility > 0.0 else float("nan")


def _load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    missing = [str(path) for path in SOURCES.values() if not path.is_file()]
    if missing:
        raise SystemExit(f"source panels are missing: {missing}")
    baseline = pd.read_parquet(SOURCES["desired_weight"]).fillna(0.0).astype("float64")
    universe = (
        pd.read_parquet(SOURCES["universe_mask"])
        .reindex(index=baseline.index, columns=baseline.columns)
        .fillna(False)
        .astype(bool)
    )
    benchmark = (
        pd.read_parquet(SOURCES["benchmark_weight"])
        .reindex(index=baseline.index, columns=baseline.columns)
        .fillna(0.0)
        .astype("float64")
    )
    if not PRICES.is_file():
        raise SystemExit(f"return source is missing: {PRICES}")
    prices = pd.read_parquet(PRICES, columns=["date", "ticker", "return"])
    realized = (
        prices.pivot(index="date", columns="ticker", values="return")
        .reindex(index=baseline.index, columns=baseline.columns)
        .fillna(0.0)
        .astype("float64")
    )
    return baseline, universe, benchmark, realized


def _contract(
    baseline: pd.DataFrame,
    universe: pd.DataFrame,
    benchmark_weight: pd.DataFrame,
    realized: pd.DataFrame,
) -> dict[str, object]:
    demeaned = market_demean_preserving_gross(baseline, universe | baseline.ne(0.0))
    baseline_return = (baseline * realized).sum(axis=1)
    demeaned_return = (demeaned * realized).sum(axis=1)
    benchmark_return = (benchmark_weight * realized).sum(axis=1)
    baseline_beta = rolling_beta(baseline_return, benchmark_return, window=BETA_WINDOW)
    demeaned_beta = rolling_beta(demeaned_return, benchmark_return, window=BETA_WINDOW)
    return {
        "alpha": "open_close_rebound",
        "before": "baseline_without_neutralization",
        "after": "market_demean_with_daily_gross_preserved",
        "baseline_annualized_return": _annual_mean(baseline_return),
        "baseline_sharpe": _information_ratio(baseline_return),
        "market_demeaned_annualized_return": _annual_mean(demeaned_return),
        "market_demeaned_sharpe": _information_ratio(demeaned_return),
        "baseline_mean_absolute_beta": float(baseline_beta.abs().mean()),
        "market_demeaned_mean_absolute_beta": float(demeaned_beta.abs().mean()),
        # Signed as well as absolute. An absolute mean is sign-invariant, so a systematically
        # sign-flipped beta would reproduce every absolute figure exactly and stay invisible.
        "baseline_mean_beta": float(baseline_beta.mean()),
        "market_demeaned_mean_beta": float(demeaned_beta.mean()),
        "beta_window": BETA_WINDOW,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="recompute and compare against the committed fixture without writing",
    )
    arguments = parser.parse_args()

    baseline, universe, benchmark_weight, realized = _load()
    contract = _contract(baseline, universe, benchmark_weight, realized)
    span = {
        "start": str(baseline.index.min())[:10],
        "end": str(baseline.index.max())[:10],
        "observations": len(baseline),
        "instruments": int(baseline.shape[1]),
    }

    if arguments.check:
        recorded = json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))
        drift = {
            key: (recorded["figure_03_contract"][key], value)
            for key, value in contract.items()
            if recorded["figure_03_contract"].get(key) != value
        }
        if drift or recorded["span"] != span:
            print(f"fixture drifted: {json.dumps(drift, default=str)}", file=sys.stderr)
            return 1
        print("fixture matches the sources it was extracted from")
        return 0

    FIXTURE.mkdir(parents=True, exist_ok=True)
    written = {
        "baseline_weight.parquet": baseline,
        "universe_mask.parquet": universe,
        "benchmark_weight.parquet": benchmark_weight,
        "realized_return.parquet": realized,
    }
    for name, frame in written.items():
        frame.to_parquet(FIXTURE / name, index=True)

    manifest = {
        "purpose": (
            "Input to the figure-3 neutralisation acceptance test. The target is recomputed for "
            "the window that exists, not quoted from the published report."
        ),
        "retarget": {
            "published_range": {
                "start": "2018-01-02",
                "end": "2026-07-28",
                "observations": 2102,
            },
            "published_contract": {
                "baseline_annualized_return": 0.14042999799281802,
                "baseline_sharpe": 0.547398798563331,
                "market_demeaned_annualized_return": 0.06501825970332753,
                "market_demeaned_sharpe": 0.4033130871259885,
            },
            "reason": (
                "The build cache that produced the published figures no longer exists. Every "
                "panel in the reference project now spans a shorter window, all three recorded "
                "source hashes fail against what is on disk, and they fail against the older "
                "manifest's hashes too, so the cache is a third state rather than a recoverable "
                "earlier one. Retargeting to the available window was the user's decision, taken "
                "over weakening the criterion."
            ),
            "authority": (
                "None upstream. Because the target is recomputed, the report manifest does not "
                "authenticate it and the panels are pinned by their own hashes. Any later "
                "criterion whose value depends on these panels must establish its own authority."
            ),
            "method": (
                "The report's own recipe, transcribed unchanged from build_report_assets.py: "
                "market_demean_preserving_gross, rolling_beta over 60 sessions, annual mean at "
                "252 sessions, information ratio as annual mean over annual volatility."
            ),
            "upstream_manifest_sha256": _digest(MANIFEST) if MANIFEST.is_file() else None,
        },
        "span": span,
        "figure_03_contract": contract,
        "sources_sha256": {name: _digest(path) for name, path in SOURCES.items()},
        "return_source": {
            "path": str(PRICES),
            "sha256": _digest(PRICES),
            "note": (
                "vqapr's own preprocessed prices, the same file the reference project derives "
                "its adjusted return from."
            ),
        },
        "committed_sha256": {name: _digest(FIXTURE / name) for name in sorted(written)},
        "committed_bytes": {name: (FIXTURE / name).stat().st_size for name in sorted(written)},
    }
    (FIXTURE / "fixture.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    total = sum(manifest["committed_bytes"].values())
    print(f"wrote {len(written)} panels to {FIXTURE} ({total / 1e6:.1f} MB)")
    print(f"span: {span['start']}..{span['end']}  {span['observations']} obs")
    for key in (
        "baseline_annualized_return",
        "market_demeaned_annualized_return",
        "baseline_mean_absolute_beta",
        "market_demeaned_mean_absolute_beta",
    ):
        print(f"  {key} = {contract[key]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
