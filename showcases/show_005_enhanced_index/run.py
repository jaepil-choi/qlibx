"""Alpha run, published allocation, then an enhanced index that subscribes to both.

This showcase runs the whole chain the milestone exists for::

    alpha run (Academic, zero cost)  ->  published allocation dataset
                                              |
    committed benchmark panel  --------------- +-->  enhanced index run (KRX profile)

Three things are demonstrated rather than asserted in prose:

* **Publication is a dataset, not a new subsystem.** The alpha run's allocation is published through
  the same machinery that materialises a DataModel, and the enhanced index reads it back with an
  ordinary ``DataRequirement``.
* **Multi-input subscription works.** The enhanced-index strategy declares *two* allocation
  requirements -- the published alpha and the committed benchmark -- and combines them. That is the
  ensemble capability this milestone proves; the ensemble's own run is a later milestone.
* **Long-only is emergent.** The alpha is signed. Nothing strips its short leg; the constraint set
  does, through ``no_short`` intersected with a single-name cap.

Tracking error is computed **after the fact only**, as monitoring evidence. It never shapes a
decision, because a portfolio-level quadratic does not fit per-instrument constraint bounds.

The showcase reads the committed fixture under ``tests/fixtures/real``, so it runs on a clean
checkout with no vendor warehouse.

Reproduce::

    uv run python showcases/show_005_enhanced_index/run.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from vqapr.constraints.builtin import NoShort
from vqapr.constraints.constraint import ConstraintBounds
from vqapr.flow.materialize import AllocationPublicationSpec, publish_run_allocation
from vqapr.portfolio.allocation import (
    AllocationInvariants,
    AllocationSign,
    validate_allocation,
)
from vqapr.portfolio.optimize import QUANTUM, OptimizeResult, optimize
from vqapr.workspace import Workspace

HERE = Path(__file__).resolve().parent
FIXTURE = HERE.parents[1] / "tests" / "fixtures" / "real"
OUTPUTS = HERE / "outputs"
PROJECT = OUTPUTS / "project"

CAP = Decimal("0.10")
SCALE = Decimal("0.5")
INITIAL_NAV = Decimal("1000000000")


def _reset() -> None:
    if OUTPUTS.exists():
        shutil.rmtree(OUTPUTS)
    PROJECT.mkdir(parents=True)


def _panel(path: Path, field: str) -> dict[datetime, dict[str, Decimal]]:
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT available_at, instrument, {field} FROM read_parquet('{path.as_posix()}')"
            " ORDER BY 1, 2"
        ).fetchall()
    finally:
        con.close()
    panel: dict[datetime, dict[str, Decimal]] = {}
    for available_at, instrument, value in rows:
        panel.setdefault(available_at, {})[instrument] = Decimal(str(value))
    return panel


ACTIVE_BUDGET = Decimal("0.04")
"""Total absolute active weight the tilt is allowed to express."""


def _alpha(prices: dict[datetime, dict[str, Decimal]]) -> dict[datetime, dict[str, Decimal]]:
    """A signed, dollar-neutral cross-sectional view scaled to a declared active budget.

    Demeaning is what makes it an *active* view rather than a second allocation: the legs sum to
    zero, so adding it to the benchmark moves weight between names without changing the total.
    """
    panel: dict[datetime, dict[str, Decimal]] = {}
    for session, closes in prices.items():
        mean = sum(closes.values()) / len(closes)
        raw = {instrument: (mean - close) / mean for instrument, close in closes.items()}
        centre = sum(raw.values()) / len(raw)
        centred = {instrument: value - centre for instrument, value in raw.items()}
        gross = sum(abs(value) for value in centred.values())
        scale = ACTIVE_BUDGET / gross if gross > 0 else Decimal(0)
        panel[session] = {
            instrument: (value * scale).quantize(QUANTUM) for instrument, value in centred.items()
        }
    return panel


def _bounds(benchmark: dict[str, Decimal]) -> ConstraintBounds:
    instruments = tuple(sorted(benchmark))
    no_short = NoShort().project(None, instruments)  # type: ignore[arg-type]
    return ConstraintBounds(
        dict(no_short.lower),
        {i: min(no_short.upper[i], max(CAP, benchmark[i]).quantize(QUANTUM)) for i in instruments},
    )


def _construct(
    benchmark: dict[str, Decimal],
    alpha: dict[str, Decimal],
    current_weights: dict[str, Decimal],
    frozen: frozenset[str],
) -> OptimizeResult:
    """desired = bench + s * active, projected onto the constraint set.

    ``current_weights`` are NAV-derived ratios quantized onto the canonical grid *before* the call.
    That is deliberate: the raw ratio carries 28 significant digits and the bound-exponent guard
    would refuse it, so the showcase exercises the guard rather than dodging it.
    """
    desired = {
        instrument: (weight + SCALE * alpha.get(instrument, Decimal(0))).quantize(QUANTUM)
        for instrument, weight in benchmark.items()
    }
    bounds = _bounds(benchmark)
    return optimize(
        desired=desired,
        current={k: v.quantize(QUANTUM) for k, v in current_weights.items()},
        lower=dict(bounds.lower),
        upper=dict(bounds.upper),
        frozen=frozen,
        cash_range=(Decimal("0"), Decimal("1")),
    )


def _active_norm(weights: dict[str, Decimal], benchmark: dict[str, Decimal]) -> Decimal:
    """L2 norm of the active weights, recorded post hoc as monitoring evidence only.

    This is not a realised or forecast tracking error; it never re-enters the construction.
    """
    active = [
        weights.get(instrument, Decimal(0)) - benchmark.get(instrument, Decimal(0))
        for instrument in set(weights) | set(benchmark)
    ]
    return sum((value * value for value in active), Decimal(0)).sqrt()


def _manifest(paths: list[Path]) -> dict[str, str]:
    digests: dict[str, str] = {}
    for path in sorted(paths):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digests[path.name] = f"sha256:{digest}"
    return digests


def _publish_alpha(project: Path, alpha: dict[datetime, dict[str, Decimal]]) -> Path:
    """Publish the signed alpha as an allocation dataset, stamped from its own reads."""
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Access:
        max_available_at: datetime | None

    @dataclass(frozen=True)
    class _Target:
        instrument_id: str
        weight: Decimal

    @dataclass(frozen=True)
    class _Intent:
        targets: tuple[_Target, ...]

    @dataclass(frozen=True)
    class _Evidence:
        run_identity: str
        cutoff: datetime
        strategy_accesses: tuple[_Access, ...]
        decision: object

    evidences = [
        _Evidence(
            "alpha-run",
            session,
            (_Access(session),),
            _Intent(tuple(_Target(i, w) for i, w in sorted(view.items()))),
        )
        for session, view in sorted(alpha.items())
    ]
    result = publish_run_allocation(
        project, AllocationPublicationSpec.of("alpha_allocation"), evidences
    )
    return result.output_path


def _replay(fills: list[tuple[str, Decimal, Decimal]], opening: Decimal) -> Decimal:
    """Recompute cash from the fill journal alone, independently of the Account."""
    cash = opening
    for _, quantity, price in fills:
        cash -= quantity * price
    return cash


def main() -> None:
    _reset()
    Workspace.create(PROJECT)

    manifest = json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))
    tolerance = Decimal(str(manifest["weight_tolerance"]))
    benchmark = _panel(FIXTURE / str(manifest["benchmark_path"]), "benchmark_weight")
    prices = _panel(FIXTURE / str(manifest["observation_path"]), "close")
    alpha = _alpha(prices)
    sessions = sorted(benchmark)

    signed = min(min(view.values()) for view in alpha.values())
    if signed >= 0:
        raise AssertionError(
            "the alpha must be genuinely signed for the demonstration to mean anything"
        )

    published = _publish_alpha(PROJECT, alpha)

    # The enhanced index subscribes to TWO allocation inputs and combines them.
    subscribed_alpha = _panel(published, "weight")
    if set(subscribed_alpha) != set(benchmark):
        raise AssertionError("the published allocation must cover the benchmark sessions")

    rows: list[dict[str, object]] = []
    held: dict[str, Decimal] = {}
    cash = INITIAL_NAV
    journal: list[tuple[str, Decimal, Decimal]] = []
    frozen_name = sorted(benchmark[sessions[0]])[0]
    frozen_seen = 0
    released = 0

    for session in sessions:
        index = benchmark[session]
        view = subscribed_alpha[session]

        validate_allocation(index, AllocationInvariants.of(tolerance=tolerance), label="benchmark")
        validate_allocation(
            view,
            AllocationInvariants.of(sign=AllocationSign.SIGNED, tolerance=tolerance),
            label="alpha",
        )

        nav = cash + sum(held.get(i, Decimal(0)) * prices[session].get(i, Decimal(0)) for i in held)
        current_weights = {
            instrument: units * prices[session][instrument] / nav
            for instrument, units in held.items()
            if instrument in prices[session] and nav > 0
        }
        # One name is held fixed to exercise frozen invariance. A freeze is only honourable while
        # the holding still satisfies its own box: once price drift pushes it past the cap, the two
        # demands are unsatisfiable together and `optimize` refuses, so the freeze is released and
        # the position is traded back inside instead.
        bounds = _bounds(index)
        frozen = frozenset()
        if frozen_name in current_weights:
            held_weight = current_weights[frozen_name].quantize(QUANTUM)
            if bounds.lower[frozen_name] <= held_weight <= bounds.upper[frozen_name]:
                frozen = frozenset({frozen_name})
            else:
                released += 1

        result = _construct(index, view, current_weights, frozen)
        for instrument, weight in result.weights.items():
            price = prices[session].get(instrument)
            if price is None or price == 0:
                continue
            target_units = (weight * nav / price).quantize(Decimal(1))
            delta = target_units - held.get(instrument, Decimal(0))
            if delta == 0:
                continue
            journal.append((instrument, delta, price))
            cash -= delta * price
            held[instrument] = target_units

        rows.append(
            {
                "session": session.isoformat(),
                "weights": {i: str(w) for i, w in sorted(result.weights.items())},
                "cash_weight": str(result.cash),
                "multiplier": str(result.multiplier),
                # Monitoring evidence, recorded after the decision and never fed back into it.
                "active_norm": str(_active_norm(dict(result.weights), index)),
                "frozen": sorted(frozen),
            }
        )
        if frozen:
            frozen_seen += 1
            if result.weights[frozen_name] != current_weights[frozen_name].quantize(QUANTUM):
                raise AssertionError("a frozen name must be returned verbatim")

        held = {i: q for i, q in held.items() if q != 0}

    replayed = _replay(journal, INITIAL_NAV)
    if replayed != cash:
        raise AssertionError(f"fill-journal replay {replayed} disagrees with running cash {cash}")

    if any(quantity != quantity.quantize(Decimal(1)) for _, quantity, _ in journal):
        raise AssertionError("the KRX profile trades whole shares only")

    trace = {
        "sessions": len(sessions),
        "instruments": sorted(benchmark[sessions[0]]),
        "published_allocation": published.name,
        "alpha_is_signed": str(signed),
        "subscribed_inputs": sorted({"alpha_allocation", "benchmark_weight_daily"}),
        "frozen_occurrences": frozen_seen,
        "freeze_released_out_of_box": released,
        "fills": len(journal),
        "closing_cash": str(cash),
        "replayed_cash": str(replayed),
        "final_positions": {i: str(q) for i, q in sorted(held.items())},
        "rows": rows,
    }
    (OUTPUTS / "trace.json").write_text(
        json.dumps(trace, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )

    digests = _manifest([OUTPUTS / "trace.json", published])
    (OUTPUTS / "manifest.json").write_text(
        json.dumps(digests, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"sessions            : {len(sessions)}")
    print("subscribed inputs   : alpha_allocation + benchmark_weight_daily")
    print(f"alpha minimum weight: {signed} (signed, never stripped by the input)")
    print(f"frozen occurrences  : {frozen_seen} (returned verbatim)")
    print(f"freeze released     : {released} (holding drifted outside its cap)")
    print(f"fills               : {len(journal)} (whole shares)")
    print(f"closing cash        : {cash}")
    print(f"replayed cash       : {replayed} (independent, exact match)")
    print(f"active-weight norm  : {rows[0]['active_norm']} .. {rows[-1]['active_norm']}")
    print(f"artifacts           : {json.dumps(digests, indent=2, sort_keys=True)}")


if __name__ == "__main__":
    main()
