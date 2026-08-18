"""The committed fixture must be able to falsify its own provenance.

Recording a hash proves nothing on its own; a clean checkout has to be able to notice that what is
committed is no longer what the manifest describes. That is the whole reason these panels are in
the repository rather than read from a gitignored cache.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parent / "report_figure_03"
PANELS = (
    "baseline_weight.parquet",
    "benchmark_weight.parquet",
    "realized_return.parquet",
    "universe_mask.parquet",
)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))


def test_every_committed_panel_is_present() -> None:
    for name in PANELS:
        assert (FIXTURE / name).is_file(), f"{name} is missing from the committed fixture"


def test_every_committed_panel_matches_its_recorded_hash(manifest: dict) -> None:
    """The standing check. A regenerated or truncated panel turns this red on a clean checkout."""
    recorded = manifest["committed_sha256"]

    assert set(recorded) == set(PANELS)
    for name in PANELS:
        digest = hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest()
        assert digest == recorded[name], f"{name} is not the file the manifest describes"


def test_the_recorded_sizes_are_the_real_ones(manifest: dict) -> None:
    for name, size in manifest["committed_bytes"].items():
        assert (FIXTURE / name).stat().st_size == size


def test_the_retarget_is_declared_rather_than_implied(manifest: dict) -> None:
    """The numbers are not the published ones, and the fixture has to say so in its own file.

    A reader who finds these panels must not be able to mistake them for the report's figures. The
    manifest therefore carries the published range and contract it departed from, the reason, and
    an explicit statement that nothing upstream authenticates the recomputed target.
    """
    retarget = manifest["retarget"]

    assert retarget["published_range"]["observations"] == 2102
    assert retarget["published_contract"]["baseline_annualized_return"] == 0.14042999799281802
    assert "no longer exists" in retarget["reason"]
    assert retarget["authority"].startswith("None upstream")
    assert "transcribed unchanged" in retarget["method"]


def test_the_committed_span_is_the_one_the_contract_was_computed_over(manifest: dict) -> None:
    span = manifest["span"]

    assert span["observations"] == 1562
    assert span["start"] == "2020-01-03" and span["end"] == "2026-05-22"
    assert span["observations"] != manifest["retarget"]["published_range"]["observations"], (
        "the retarget exists precisely because these differ"
    )


def test_the_contract_carries_both_halves_of_the_figure_three_claim(manifest: dict) -> None:
    """Return and beta. A previous revision of the plan silently dropped the beta half."""
    contract = manifest["figure_03_contract"]

    for key in (
        "baseline_annualized_return",
        "market_demeaned_annualized_return",
        "baseline_sharpe",
        "market_demeaned_sharpe",
        "baseline_mean_absolute_beta",
        "market_demeaned_mean_absolute_beta",
    ):
        assert key in contract, f"the contract is missing {key}"

    assert contract["beta_window"] == 60


def test_the_figure_three_claim_actually_holds_on_this_window(manifest: dict) -> None:
    """The retarget is only worth having if the claim it targets survives the new window.

    Figure 3 asserts two things: neutralisation drops the return substantially, and it drives the
    market beta toward zero. Both must be true of the recorded contract, or the fixture is aimed at
    a window where there is nothing to demonstrate.
    """
    contract = manifest["figure_03_contract"]

    baseline = contract["baseline_annualized_return"]
    demeaned = contract["market_demeaned_annualized_return"]
    assert demeaned < baseline, "neutralisation must reduce the return"
    assert (baseline - demeaned) > 0.01, "the drop must be large enough to measure"

    assert contract["market_demeaned_mean_absolute_beta"] < contract["baseline_mean_absolute_beta"]
    # Near zero, not merely lower: a demeaned book still carrying half the market's beta would
    # satisfy a strict inequality while failing the claim the figure actually makes.
    assert contract["market_demeaned_mean_absolute_beta"] < 0.25
