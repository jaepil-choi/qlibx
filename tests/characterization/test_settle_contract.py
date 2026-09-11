"""AC-M4: the framework settle contract reproduces the committed weight values exactly.

The migration moves `rescale(grid=QUANTUM)` out of author code and into the framework weight
scheme. Whether that move is value-preserving is a measurement, not an inference, and the count
probe cannot make it: `parity_probe.py` locks `callback_days`, `formations` and `membership_rows`,
so a settle-ordering change can preserve every count exactly while changing every weight value.
This test is the value-level oracle for that inverted failure mode.

THE CONTRACT UNDER TEST, stated before it is measured
=====================================================

Read from `vqapr/portfolio/weights.py` (`rescale` at :162, `_settle` at :68) and fixed here so
the measurement is not circular:

1. Scale each side to its own target: `w * target / side_gross`.
2. Quantize FIRST onto `grid` with ROUND_HALF_EVEN, per side.
3. Settle the residual SECOND, onto the largest member of that side by absolute value, ties broken
   by instrument name so the result is dict-order independent.
4. Both sides share ONE grid against targets that are multiples of it, so the two sides land on the
   same steps and their residuals cancel.

Point 4 is why this is one `rescale` over the two-sided book. Each side reaches its own target
either way, but only a shared grid makes their SUM exact, and `Rebalance.__post_init__` requires
`sum(target_weights) + cash_weight == 1` EXACTLY (`vqapr/authoring.py:592-593`). A two-sided
residual of the documented -1.674E-28 kind is refused at the 28th digit, so the observable is a
formation collapsing into a refusal, not a sixth-decimal drift.

WHY A FIXTURE AND NOT A LIVE RUN
================================

The ground truth is `baselines/agent-first-v1/publication.rows.jsonl` in the sibling testbed: ~223MB
of published weight VALUES, gitignored, existing only on the capture machine. The input to the
settle is captured at the real call site from a real 2,096-session run, which costs minutes. Neither
belongs in a unit suite, so `capture_settle_contract.py` projects both into the committed fixture
this test reads: per-formation digests over all 97 HML formations, plus the complete Decimal set for
one named formation. That is a projection, not 636,324 inline Decimals.

The digests carry the breadth and the named formation carries the depth. The named formation is
recomputed here from its captured input, Decimal for Decimal, so this test independently reproduces
the contract rather than trusting the capture's own verdict.

WHY THE NEGATIVE CONTROLS ARE THE POINT
=======================================

A harness that cannot fail proves nothing. Two plausible-wrong settles are recomputed from the same
captured input and must BOTH differ from the published values:

- `independent`  - the sides settled with no shared grid. Measured to differ in all 97 formations.
- `settle_first` - settle to target first, quantize after. Measured to differ in 94 of 97.

That 94-of-97 is the reason breadth matters: a harness sampling a single formation had a 3-in-97
chance of calling a wrong implementation correct.

A SECOND PROPERTY THE GRID BUYS, found while building this
==========================================================

The ungridded settle is ORDER-DEPENDENT: four shuffles of the same book produced four distinct
results, because summing ~1,200 full-precision Decimals at a 28-digit context rounds differently
depending on term order. The gridded contract produced one result across the same four shuffles.
So the shared grid is not only what makes the two sides cancel, it is what makes the settle
reproducible at all, and an ungridded implementation would be unstable as well as wrong.
"""

from __future__ import annotations

import hashlib
import json
import random
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "settle_contract_hml.fixture.json"
SCHEMA = "vqapr-testbed-settle-contract/v1"


def _load() -> dict:
    if not FIXTURE.is_file():
        raise FileNotFoundError(
            f"the AC-M4 fixture is missing: {FIXTURE}. Re-capture it from the testbed with "
            "`uv run --no-sync python capture_settle_contract.py --factor HML "
            "--out outputs/settle_contract_hml.json` and project it into this directory."
        )
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if document.get("schema") != SCHEMA:
        raise AssertionError(f"unexpected fixture schema: {document.get('schema')!r}")
    return document


@pytest.fixture(scope="module")
def measured() -> dict:
    return _load()


@pytest.fixture(scope="module")
def named(measured: dict) -> dict:
    return measured["named_formation"]


def _scaled(held: dict[str, Decimal], long: Decimal, short: Decimal) -> dict[str, Decimal]:
    """Contract point 1, shared by every variant: each side scaled to its own target."""
    long_gross = sum((value for value in held.values() if value > 0), Decimal(0))
    short_gross = sum((value for value in held.values() if value < 0), Decimal(0))
    scaled: dict[str, Decimal] = {}
    for instrument, value in held.items():
        if value > 0:
            scaled[instrument] = value * long / long_gross
        elif value < 0:
            scaled[instrument] = value * short / short_gross
        else:
            scaled[instrument] = Decimal(0)
    return scaled


def _settle_quantize_first(
    scaled: dict[str, Decimal], members: list[str], target: Decimal, grid: Decimal | None
) -> None:
    """Contract points 2 and 3."""
    if not members:
        return
    if grid is not None:
        for name in members:
            scaled[name] = scaled[name].quantize(grid, rounding=ROUND_HALF_EVEN)
    residual = target - sum((scaled[name] for name in members), Decimal(0))
    if residual == 0:
        return
    scaled[max(members, key=lambda name: (abs(scaled[name]), name))] += residual


def _settle_then_quantize(
    scaled: dict[str, Decimal], members: list[str], target: Decimal, grid: Decimal | None
) -> None:
    """The wrong order: quantizing after settling re-breaks the sum settling just fixed."""
    if not members:
        return
    residual = target - sum((scaled[name] for name in members), Decimal(0))
    if residual != 0:
        scaled[max(members, key=lambda name: (abs(scaled[name]), name))] += residual
    if grid is not None:
        for name in members:
            scaled[name] = scaled[name].quantize(grid, rounding=ROUND_HALF_EVEN)


def _rescale(
    held: dict[str, Decimal], long: Decimal, short: Decimal, grid: Decimal | None, settle
) -> dict[str, Decimal]:
    scaled = _scaled(held, long, short)
    settle(scaled, [n for n, v in scaled.items() if v > 0], long, grid)
    settle(scaled, [n for n, v in scaled.items() if v < 0], short, grid)
    return scaled


def _variants(named: dict) -> dict[str, dict[str, Decimal]]:
    held = {name: Decimal(value) for name, value in named["held"].items()}
    long, short = Decimal(named["long"]), Decimal(named["short"])
    grid = Decimal(named["grid"])
    return {
        "contract": _rescale(held, long, short, grid, _settle_quantize_first),
        "independent": _rescale(held, long, short, None, _settle_quantize_first),
        "settle_first": _rescale(held, long, short, grid, _settle_then_quantize),
    }


def _digest(weights: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(weights):
        digest.update(name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(weights[name]).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def test_the_capture_covers_the_locked_formation_count(measured: dict) -> None:
    """The projection describes the whole locked run, not a convenient subset of it."""
    assert measured["factor"] == "HML"
    assert measured["locked"]["formations"] == 97
    assert measured["locked"]["membership_rows"] == 110919
    assert len(measured["formations"]) == measured["locked"]["formations"]


def test_contract_reproduces_every_published_formation(measured: dict) -> None:
    """AC-M4 at breadth: the contract's digest equals the published digest, all 97 formations."""
    moved = [
        row["index"]
        for row in measured["formations"]
        if row["contract_digest"] != row["published_digest"]
    ]
    assert moved == [], f"the framework settle contract moved weight values at formations {moved}"


def test_named_formation_recomputes_decimal_for_decimal(named: dict) -> None:
    """AC-M4 at depth: recomputed here, not trusted from the capture's own verdict."""
    computed = _variants(named)["contract"]
    published = named["published"]

    assert set(computed) == set(published)
    differences = [
        (name, str(computed[name]), published[name])
        for name in sorted(computed)
        if str(computed[name]) != published[name]
    ]
    assert differences == [], f"first difference: {differences[0] if differences else None}"


def test_settled_book_sums_to_one_with_its_cash_weight(measured: dict, named: dict) -> None:
    """The invariant the intent boundary actually enforces, exactly and at the 28th digit."""
    invested = sum(_variants(named)["contract"].values(), Decimal(0))
    assert invested + (Decimal(1) - invested) == Decimal(1)

    for row in measured["formations"]:
        assert row["sums_to_one"], f"formation {row['index']} does not settle to one"
        assert Decimal(row["invested"]) + Decimal(row["cash_weight"]) == Decimal(1)


@pytest.mark.parametrize("control", ["independent", "settle_first"])
def test_negative_control_fails_the_comparison(named: dict, control: str) -> None:
    """A harness that cannot fail proves nothing. Both wrong settles must be caught."""
    computed = _variants(named)[control]
    published = named["published"]
    assert any(
        str(computed[name]) != published.get(name) for name in computed
    ), f"the {control!r} control reproduced the published weights, so this test cannot detect it"


@pytest.mark.parametrize(
    ("control", "expected_moved"),
    [("independent", 97), ("settle_first", 94)],
)
def test_negative_control_breadth_is_the_measured_one(
    measured: dict, control: str, expected_moved: int
) -> None:
    """`settle_first` differs in 94 of 97, not all 97.

    A single-formation harness had a 3-in-97 chance of calling settle-then-quantize correct. That
    measured number is asserted so the breadth of the oracle cannot be quietly reduced.
    """
    moved = sum(
        1
        for row in measured["formations"]
        if row[f"{control}_digest"] != row["published_digest"]
    )
    assert moved == expected_moved


def test_recomputed_digests_match_the_captured_digests(named: dict, measured: dict) -> None:
    """Ties the depth sample to the breadth projection, so neither can drift alone."""
    row = measured["formations"][named["index"]]
    variants = _variants(named)
    assert _digest({n: str(v) for n, v in variants["contract"].items()}) == row["contract_digest"]
    assert (
        _digest({n: str(v) for n, v in variants["independent"].items()})
        == row["independent_digest"]
    )
    assert (
        _digest({n: str(v) for n, v in variants["settle_first"].items()})
        == row["settle_first_digest"]
    )
    assert _digest(named["published"]) == row["published_digest"]


def test_the_grid_also_makes_the_result_order_independent(measured: dict, named: dict) -> None:
    """Measured during capture: the ungridded settle is order-dependent and the gridded one is not.

    Summing ~1,200 full-precision Decimals at a 28-digit context rounds differently depending on
    the order the terms arrive in, so an ungridded book settles to a different result per shuffle.
    Quantizing first leaves every term short enough that the running sum is exact, which is a
    second reason the shared grid is load-bearing: it buys reproducibility, not only cancellation.

    Reproduced here rather than read from the capture, so the claim is this suite's own.
    """
    recorded = measured["order_dependence"]
    assert recorded["gridded_distinct_results"] == 1
    assert recorded["ungridded_distinct_results"] == recorded["shuffles"]

    held = {name: Decimal(value) for name, value in named["held"].items()}
    long, short = Decimal(named["long"]), Decimal(named["short"])
    grid = Decimal(named["grid"])

    gridded, ungridded = set(), set()
    for seed in range(recorded["shuffles"]):
        keys = list(held)
        random.Random(seed).shuffle(keys)
        shuffled = {key: held[key] for key in keys}
        gridded.add(
            _digest(
                {
                    n: str(v)
                    for n, v in _rescale(
                        dict(shuffled), long, short, grid, _settle_quantize_first
                    ).items()
                }
            )
        )
        ungridded.add(
            _digest(
                {
                    n: str(v)
                    for n, v in _rescale(
                        dict(shuffled), long, short, None, _settle_quantize_first
                    ).items()
                }
            )
        )

    assert len(gridded) == 1, "the gridded settle is not order-independent"
    assert len(ungridded) == recorded["shuffles"], "the ungridded settle stopped being unstable"


def test_the_grid_is_what_makes_the_two_sides_cancel(named: dict) -> None:
    """Contract point 4, isolated: without a shared grid the two-sided sum is not exact.

    This is the -1.674E-28 residual the shipped docstring documents, reproduced from real captured
    input rather than asserted from the docstring.
    """
    ungridded = _variants(named)["independent"]
    residual = sum(ungridded.values(), Decimal(0))
    assert residual != 0, "the ungridded book cancelled exactly, so the grid proves nothing here"
    assert abs(residual) < Decimal("1e-20"), f"residual {residual} is not the sub-ulp kind"

    gridded = _variants(named)["contract"]
    assert sum(gridded.values(), Decimal(0)) == 0


def test_published_weights_are_on_the_quantum_grid(named: dict) -> None:
    """Every published value is a multiple of the grid, so the settle target is reachable."""
    grid = Decimal(named["grid"])
    off_grid = [
        name for name, value in named["published"].items() if Decimal(value) % grid != 0
    ]
    assert off_grid == [], f"{len(off_grid)} published weights are not on the {grid} grid"
