"""An alpha run, its published allocation, and an enhanced index built on top — through the spine.

    alpha run (Academic)  ->  its recorded vqapr.weight, registered  ->  alpha_allocation
                                                                |
    committed benchmark panel  ------------------------------- + -->  enhanced index run (KRX)
                                                                          desired = bench + s·active
                                                                          projected onto NoShort
                                                                          and SingleNameCap

Both halves are ordinary runs: `RunDefinition`, `preflight_run`, `run`, a real `Account`, real order
planning and the declared execution profile. The enhanced-index Strategy reads **two allocation
inputs** — the committed benchmark and the published alpha — through ordinary `DataRequirement`
subscriptions inside its point-in-time window, so the combination is proved on the subscription
path rather than by reading parquet beside it. Its bounds are the ones the registered shipped
constraint set projected for that occurrence, not a second copy of the same rule.

The fill journal the second run committed is replayed independently against the committed
`Account`, the monitoring findings over every marked account version are read back rather than
assumed, and the whole pipeline runs twice into separate projects so the artifact digests can be
compared.

Everything is real KRX data committed under `tests/fixtures/real`. Nothing here invents a price or
an index weight.

Reproduce::

    uv run python showcases/show_005_enhanced_index/run.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from vqapr.cli.register import run as register_cli
from vqapr.public import (
    SHIPPED_CONSTRAINTS,
    AccountMode,
    AccountSnapshot,
    DatasetRegistration,
    ExecutionInputRegistration,
    ExecutionTableSpec,
    FillConvention,
    FillSelector,
    RunDefinition,
    SourceSpec,
    StrategyEntry,
    ZeroDealtReason,
    export_roster,
    preflight_run,
    register_constraint,
    register_dataset,
    register_exchange,
    register_execution_input,
    register_strategy_model,
    run,
    shipped_constraint_path,
)

HERE = Path(__file__).resolve().parent
FIXTURE = HERE.parents[1] / "tests" / "fixtures" / "real"
OUTPUTS = HERE / "outputs"

VENUE = "Asia/Seoul"
OFFSET = "+09:00"
INITIAL_CASH = Decimal("1000000000")
CAP = "0.10"
"""Single-name cap above the index weight, in the shipped constraint's own config spelling."""

VERIFIED_AGAINST = "vqapr-0.7.0"
LAST_VERIFIED_AT = "2026-09-08"


def _sessions(path: Path) -> list[date]:
    con = duckdb.connect()
    try:
        return [
            row[0]
            for row in con.execute(
                f"""
                SELECT DISTINCT CAST(available_at AT TIME ZONE '{VENUE}' AS DATE) AS session
                FROM read_parquet('{path.as_posix()}') ORDER BY session
                """
            ).fetchall()
        ]
    finally:
        con.close()


def _universe(path: Path) -> tuple[str, ...]:
    con = duckdb.connect()
    try:
        return tuple(
            row[0]
            for row in con.execute(
                f"SELECT DISTINCT instrument FROM read_parquet('{path.as_posix()}') ORDER BY 1"
            ).fetchall()
        )
    finally:
        con.close()


_SOURCE_REFS = '''

def _source_refs(context):
    """Exactly the sources this callback read, in first-read order.

    The Flow independently recomputes this from the window and refuses any intent whose provenance
    disagrees, so it must be derived from the accesses rather than declared.
    """
    from vqapr.public import IntentSourceRef, Rebalance

    seen = {}
    for access in context.window.accesses:
        seen.setdefault(access.source_id, access.source_digest)
    return tuple(IntentSourceRef(source, digest) for source, digest in seen.items())
'''


_ALPHA_SOURCE = (
    '''"""A dollar-neutral cross-sectional view, published afterwards as an allocation input."""

from __future__ import annotations

from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from vqapr.public import (
    Budget,
    DataRequirement,
    Hold,
    PortfolioDirection,
    QUANTUM,
    Rebalance,
    RowsLookback,
    StrategyModel,
    TableSpec,
)

ACTIVE_BUDGET = Decimal("0.04")
"""Total absolute active weight the view is allowed to express."""

BUDGET = Budget(
    PortfolioDirection.SIGNED,
    Decimal("0"),
    Decimal("2"),
    Decimal("-1"),
    Decimal("1"),
)


class SignedAlpha(StrategyModel):
    """Cheap names long, expensive names short, demeaned so the legs cancel."""

    def tables(self):
        """The signal, before weighting, so a later run can see what this view actually thought.

        This is the recorder's first real use on the spine: no StrategyModel in this repository had
        declared a table before, so the path existed and had never carried a row from `run()`.
        """
        return (TableSpec("alpha.signal", ("instrument", "signal")),)

    def requirements(self):
        return (
            DataRequirement.of('price_daily', 'close', lookback=RowsLookback(1)),
        )

    def decide(self, context):
        rows = context.window.observations(self.requirements()[0]).rows
        # A DOUBLE field arrives as a float; cross to Decimal once, through str.
        closes = {
            str(row["instrument"]): Decimal(str(row["close"]))
            for row in rows
            if row["close"] is not None
        }
        if len(closes) < 2:
            return Hold(reason="a cross-sectional view needs at least two names")

        mean = sum(closes.values()) / len(closes)
        raw = {name: (mean - close) / mean for name, close in closes.items()}
        centre = sum(raw.values()) / len(raw)
        centred = {name: value - centre for name, value in raw.items()}
        gross = sum(abs(value) for value in centred.values())
        if gross == 0:
            return Hold(reason="the cross-section is flat")

        scale = ACTIVE_BUDGET / gross
        weights = {
            name: (value * scale).quantize(QUANTUM) for name, value in centred.items()
        }
        # The signal before weighting, recorded so a later run can reuse this view.
        for name, value in sorted(centred.items()):
            self.recorder.append("alpha.signal", {"instrument": name, "signal": str(value)})

        history = dict(self.memory or {})
        history["views"] = int(history.get("views", 0)) + 1
        self.memory = history

        return Rebalance(
            target_weights=dict(sorted(weights.items())),
            cash_weight=Decimal(1) - sum(weights.values()),
            budget=BUDGET,
        )
'''
    + _SOURCE_REFS
)


_ENHANCED_SOURCE = (
    '''"""An enhanced index built from two subscribed allocation inputs."""

from __future__ import annotations

from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from vqapr.public import (
    AllocationInvariants,
    AllocationSign,
    Budget,
    DataRequirement,
    Hold,
    OptimizeRefusal,
    PortfolioDirection,
    QUANTUM,
    Rebalance,
    RowsLookback,
    StrategyModel,
    optimize,
    validate_allocation,
)

SCALE = Decimal("0.5")
"""How much of the active view the index is tilted by."""

NEUTRALITY = Decimal("0.000000001")
"""What "dollar neutral" is allowed to mean once the view lands on the canonical grid."""

BUDGET = Budget(
    PortfolioDirection.LONG_ONLY,
    Decimal("0"),
    Decimal("1"),
    Decimal("0"),
    Decimal("1"),
)


class EnhancedIndex(StrategyModel):
    """desired = benchmark + SCALE·active, projected onto the projected constraint set."""

    def __init__(self, *, benchmark_dataset_id: str, alpha_dataset_id: str) -> None:
        self._benchmark_dataset_id = benchmark_dataset_id
        self._alpha_dataset_id = alpha_dataset_id

    def requirements(self):
        return (
            DataRequirement.of(self._benchmark_dataset_id, 'benchmark_weight', lookback=RowsLookback(1)),
            DataRequirement.of(self._alpha_dataset_id, "weight", lookback=RowsLookback(1)),
            DataRequirement.of('price_daily', 'close', lookback=RowsLookback(1)),
        )

    def _panel(self, context, requirement, field):
        # A DOUBLE field arrives as a float; cross to Decimal once, through str.
        return {
            str(row["instrument"]): Decimal(str(row[field]))
            for row in context.window.observations(requirement).rows
            if row[field] is not None
        }

    def decide(self, context):
        index_requirement, alpha_requirement, price_requirement = self.requirements()
        benchmark = self._panel(context, index_requirement, "benchmark_weight")
        active = self._panel(context, alpha_requirement, "weight")
        prices = self._panel(context, price_requirement, "close")
        if not benchmark or not active:
            return Hold(reason="both allocation inputs must be visible before combining them")

        # The alpha is this callback's own subscription; no constraint owns it, so its declared
        # invariant is checked here, at consumption, before it can move a single weight.
        validate_allocation(
            active,
            AllocationInvariants.of(
                sign=AllocationSign.SIGNED,
                weight_sum_upper=Decimal(0),
                tolerance=NEUTRALITY,
            ),
            label="subscribed alpha allocation",
        )

        bounds = context.constraint_bounds
        instruments = tuple(sorted(bounds.lower_weights))
        desired = {
            name: (
                benchmark.get(name, Decimal(0)) + SCALE * active.get(name, Decimal(0))
            ).quantize(QUANTUM)
            for name in instruments
        }

        account = context.account
        nav = account.cash + sum(
            (
                quantity * prices[name]
                for name, quantity in account.positions.items()
                if name in prices
            ),
            Decimal(0),
        )
        current = {}
        if nav > 0:
            # Quantized before the call on purpose: a raw NAV ratio carries far more digits than
            # the canonical grid, and the bound-exponent guard would refuse it. The showcase
            # exercises that guard rather than dodging it.
            current = {
                name: (quantity * prices[name] / nav).quantize(QUANTUM)
                for name, quantity in sorted(account.positions.items())
                if name in prices
            }

        # One held name is pinned to prove frozen invariance, and it is the holding with the
        # most slack against its own upper bound, so the freeze stays inside the box for the whole
        # run. `optimize` treats a frozen holding as a market fact rather than a compliance rule
        # (Architecture 5.3) and reports `frozen_outside_box` instead of refusing. It is pinned to
        # the safe name here because the *intent boundary* still judges an out-of-box frozen weight
        # as a constraint violation and fails the callback -- see README, "Known gap".
        frozen = frozenset()
        if current:
            pinned = max(current, key=lambda name: (bounds.upper_weights[name] - current[name], name))
            frozen = frozenset({pinned})
        result = self._solve(desired, current, bounds, frozen)
        reported = len(result.frozen_outside_box)

        for name in frozen:
            if result.weights[name] != current[name]:
                raise AssertionError("a frozen name must be returned verbatim")

        history = dict(self.memory or {})
        history["rebalances"] = int(history.get("rebalances", 0)) + 1
        history["frozen_occurrences"] = int(history.get("frozen_occurrences", 0)) + len(frozen)
        history["frozen_outside_box"] = int(history.get("frozen_outside_box", 0)) + reported
        # Monitoring only, recorded after the decision and never fed back into it.
        history["active_norm"] = str(self._active_norm(result.weights, benchmark))
        self.memory = history

        return Rebalance(
            target_weights=dict(sorted(result.weights.items())),
            cash_weight=result.cash,
            budget=BUDGET,
        )

    def _solve(self, desired, current, bounds, frozen):
        return optimize(
            desired=desired,
            current=current,
            lower=dict(bounds.lower_weights),
            upper=dict(bounds.upper_weights),
            frozen=frozen,
            cash_range=(Decimal("0"), Decimal("1")),
        )

    @staticmethod
    def _active_norm(weights, benchmark):
        """L2 norm of the active weights. Not a realised or forecast tracking error."""
        total = Decimal(0)
        for name in set(weights) | set(benchmark):
            active = weights.get(name, Decimal(0)) - benchmark.get(name, Decimal(0))
            total += active * active
        return total.sqrt()
'''
    + _SOURCE_REFS
)


def _write_components(
    project: Path, universe: tuple[str, ...], kinds: Mapping[str, str]
) -> dict[str, Path]:
    components = project / "components"
    components.mkdir(parents=True, exist_ok=True)
    # What KRX needs to charge correctly: one category per traded name, in the emitted source, so
    # the component declares it rather than inheriting a default nobody chose.
    kinds_for_universe = {name: kinds[name] for name in universe}

    alpha = components / "alpha.py"
    alpha.write_text(_ALPHA_SOURCE, encoding="utf-8")

    enhanced = components / "enhanced.py"
    enhanced.write_text(_ENHANCED_SOURCE, encoding="utf-8")

    academic = components / "academic_exchange.py"
    academic.write_text(
        f'''"""Fractional quantity, zero cost, full fill — the venue the alpha book runs on."""

from __future__ import annotations

from decimal import Decimal

from vqapr.public import AcademicExchange, ListingAccess, Rebalance, TradeRule

UNIVERSE = {universe!r}


class ShowcaseAcademicExchange(AcademicExchange):
    def __init__(self):
        super().__init__(
            {{
                instrument: TradeRule(
                    instrument,
                    Decimal("0.0001"),
                    Decimal("0.0001"),
                    True,
                    ListingAccess.SIGNED,
                )
                for instrument in UNIVERSE
            }},
            "show005-academic",
        )
''',
        encoding="utf-8",
    )

    krx = components / "krx_exchange.py"
    krx.write_text(
        f'''"""Whole shares, 3bp commission both sides, 20bp sale tax on shares only, long only.

Built from `krx_rules({{instrument_id: kind}})` rather than from a bare sequence of ids. The
bare form is shorter and silently wrong for this book: it gives every name the STOCK terms, so
the ETF sleeve would pay the securities transaction tax KRX exempts it from. Nothing downstream
would notice, because the category is consumed when the venue is built and the charge is a
dictionary lookup afterwards -- the wrong rate is frozen in at construction.
"""

from __future__ import annotations

from vqapr.public import KrxExchange, Rebalance, krx_rules

UNIVERSE = {kinds_for_universe!r}


class ShowcaseKrxExchange(KrxExchange):
    def __init__(self):
        # price_limits=False because this fixture's execution table publishes a close and no
        # session base price. Left on, `execution_requirements()` would demand that column and
        # preflight would refuse the run -- correctly, since a limit band computed from a missing
        # base would produce numbers that look limit-aware and are not.
        #
        # `krx_rules` still takes the universe's categories, because KRX's TERMS are per-category:
        # a share pays the sale tax and an ETF does not. What it no longer does is tell the venue
        # what each instrument IS -- that comes from the project's registered roster, bound in by
        # the Flow at run assembly. Terms are the venue's; identity is the project's.
        listings, _ = krx_rules(UNIVERSE, price_limits=False)
        super().__init__(listings, "show005-krx")
''',
        encoding="utf-8",
    )
    return {"alpha": alpha, "enhanced": enhanced, "academic": academic, "krx": krx}


def _replay(result: Any) -> dict[str, Any]:
    """Rebuild cash and positions from the fill journal and demand an exact match.

    The journal and the snapshot are two independent records of the same committed history: the
    snapshot is what the Account carries forward, the journal is every fill it accepted. If they
    disagree the run is not reportable, so this aborts rather than annotating.
    """
    account = result.final_state.account
    cash = INITIAL_CASH
    positions: dict[str, Decimal] = {}
    commission = Decimal(0)
    tax = Decimal(0)
    dealt = 0
    refused: dict[str, int] = {}
    for row in _recorded_fills(result):
        if Decimal(row["dealt_quantity"]) == 0:
            # An order was planned and the venue would not fill it. The Strategy could not have
            # known: tradability is an execution-time fact. The position simply stays put.
            if (
                row["reason"] == str(ZeroDealtReason.NONTRADABLE)
                and Decimal(row["requested_quantity"]) != 0
            ):
                refused[str(row["instrument"])] = refused.get(str(row["instrument"]), 0) + 1
            continue
        dealt += 1
        cash += Decimal(row["cash_delta"])
        commission += Decimal(row["commission"] or 0)
        tax += Decimal(row["tax"] or 0)
        held = positions.get(str(row["instrument"]), Decimal(0)) + Decimal(row["dealt_quantity"])
        if held == 0:
            positions.pop(str(row["instrument"]), None)
        else:
            positions[str(row["instrument"])] = held

    snapshot = account.snapshot
    if cash != snapshot.cash:
        raise AssertionError(f"journal replay cash {cash} != committed {snapshot.cash}")
    if positions != dict(snapshot.positions):
        raise AssertionError("journal replay positions do not match the committed Account")

    marked = account.latest_mark
    return {
        "dealt_fills": dealt,
        "refused_fills": dict(sorted(refused.items())),
        "replayed_cash": str(cash),
        "committed_cash": str(snapshot.cash),
        "replayed_positions": {name: str(q) for name, q in sorted(positions.items())},
        "commission": str(commission),
        "sale_tax": str(tax),
        "account_version": snapshot.version,
        "final_nav": None if marked is None else str(marked.nav),
        "whole_shares_only": all(
            quantity == quantity.to_integral_value() for quantity in snapshot.positions.values()
        ),
    }


def _monitoring(result: Any) -> dict[str, Any]:
    """Read back the monitoring verdict the run produced over every marked account version.

    Registering a constraint set proves nothing by itself. The set is *enforced* at the decision:
    an intent that fails its projected bounds is refused and the run stops, so 21 completed
    rebalances are 21 compliant intents. Monitoring is the other half, and it is evidence rather
    than a gate -- a failing finding does not stop anything, so it has to be read to exist.

    A drift finding here is not a defect. `single_name_cap` is defined relative to the index, and
    the index moves: the book is built at 09:00 against the previous session's weight and marked at
    16:30 against the current one, so a position sized exactly to yesterday's ceiling sits above
    today's. That is a property of benchmark-relative caps between rebalances, and it is reported
    rather than smoothed away.

    `no_short` is different. It has no moving reference, and a marked short position in a long-only
    account would mean the account authority itself failed, so that one aborts.
    """
    reports = [
        occurrence.result.report
        for occurrence in result.occurrences
        if getattr(getattr(occurrence, "result", None), "report", None) is not None
    ]
    if not reports:
        raise AssertionError("the run produced no monitoring evidence")

    drift_findings = 0
    drift: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    for report in reports:
        for finding in report.findings:
            if finding.passed:
                continue
            if finding.constraint_id == "no-short":
                raise AssertionError(
                    "a long-only account marked a short position: "
                    f"{finding.measured} against {finding.bound}"
                )
            drift_findings += 1
            seen = drift.get(finding.constraint_id)
            if seen is None or finding.excess > seen[0]:
                drift[finding.constraint_id] = (finding.excess, finding.measured, finding.bound)
    return {
        "monitoring_occurrences": len(reports),
        "monitoring_drift_findings": drift_findings,
        "worst_drift": {
            name: f"{measured} against {bound}, excess {excess}"
            for name, (excess, measured, bound) in sorted(drift.items())
        },
    }


def _memory(result: Any) -> dict[str, Any]:
    state = result.final_state
    return dict(state.load_model_state(state.current_model_state_ref) or {})


def _recorded_fills(result: Any) -> list[dict[str, Any]]:
    """Every committed fill, from the run's own published record.

    The Account no longer carries the whole journal -- it is published to ``vqapr.fill`` and
    dropped -- so replaying its arithmetic reads the record. Rows arrive in commit order, which is
    the order the Account applied them.
    """
    return [dict(row) for row in result.final_state.recorder_rows.get("vqapr.fill", ())]


def _recorded_rows(
    project: Path, run_result: Any, *, run_id: str, component_id: str, table: str
) -> list[dict[str, Any]]:
    """The rows a stored run recorded for one table, read back from its record in commit order.

    A run given a store streams every chunk to `tables/<table>/` and keeps none on its roots, so
    `final_state.recorder_rows` is empty for it; this is the same rows from the place they went.
    """
    ref = str(run_result.records[component_id]["strategy_ref"])
    directory = project / ".vqapr" / "runs" / run_id / "strategies" / ref / "tables" / table
    if not any(directory.glob("*.parquet")):
        return []
    con = duckdb.connect()
    try:
        cursor = con.execute(
            f"SELECT * FROM read_parquet('{directory.as_posix()}/*.parquet', union_by_name = true) "
            "ORDER BY event_time, sequence"
        )
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    finally:
        con.close()


def _digest(path: Path) -> str:
    """One digest over a file, or over every parquet part of a directory in name order."""
    digest = hashlib.sha256()
    if path.is_dir():
        for part in sorted(path.glob("*.parquet")):
            digest.update(part.name.encode("utf-8"))
            digest.update(part.read_bytes())
    else:
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


@dataclass(frozen=True)
class _Registered:
    """A run's table, registered as a dataset: where it is and what it holds."""

    dataset_id: str
    directory: Path
    row_count: int
    occurrences: int


def _register_run_table(
    project: Path,
    run_result: Any,
    *,
    run_id: str,
    component_id: str,
    dataset_id: str,
    table: str,
    fields: dict[str, str],
    field_types: dict[str, str],
) -> _Registered:
    """Register one table a member run recorded, as the dataset the next run reads.

    A run with a store streams every table it writes as a parquet directory under its own record,
    `.vqapr/runs/<run>/strategies/<id>@<fp8>/tables/<table>/`, and that directory registers like
    any other source (one-shape campaign Step 4). `available_at` is the row's `event_time`, the
    decision instant it was written at. A record stores a `Decimal` as text, so a numeric field is
    `CAST` in the registration -- to DOUBLE, the one numeric type a field may be declared as
    (issue 088). A weight on the `1e-12` grid has at most twelve significant digits, so the reader
    gets it back exactly through `Decimal(str(...))`.
    """
    ref = str(run_result.records[component_id]["strategy_ref"])
    directory = project / ".vqapr" / "runs" / run_id / "strategies" / ref / "tables" / table
    if not any(directory.glob("*.parquet")):
        raise AssertionError(f"run {run_id!r} recorded no {table!r} rows under {directory}")
    source_id = f"{dataset_id}-source"
    register_dataset(
        project,
        DatasetRegistration.of(
            dataset_id,
            source_id,
            instrument_field="instrument",
            available_at="event_time",
            grain="instrument_instant",
            key_fields=("event_time", "instrument"),
            fields=fields,
            field_types=field_types,
        ),
        SourceSpec.of(source_id, directory),
    )
    con = duckdb.connect()
    try:
        rows, occurrences = con.execute(
            f"SELECT count(*), count(DISTINCT event_time) "
            f"FROM read_parquet('{directory.as_posix()}/*.parquet', union_by_name = true)"
        ).fetchone()
    finally:
        con.close()
    return _Registered(dataset_id, directory, int(rows), int(occurrences))


def _inject_halt(source: Path, target: Path, instrument: str, days: list[date]) -> tuple[str, ...]:
    """Copy the committed execution input with one instrument halted over a window.

    The fixture records no halts, so a halt has to be constructed to exercise the path. The values
    themselves are untouched; only `is_tradable` flips, which is exactly the venue fact the
    Strategy cannot see in advance.
    """
    stamps = tuple(day.isoformat() for day in days)
    if target.exists():
        return stamps
    quoted = ", ".join(f"DATE '{stamp}'" for stamp in stamps)
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            COPY (
              SELECT trade_at, instrument,
                     CASE WHEN instrument = '{instrument}'
                           AND CAST(trade_at AS DATE) IN ({quoted})
                          THEN FALSE ELSE is_tradable END AS is_tradable,
                     close
              FROM read_parquet('{source.as_posix()}')
            ) TO '{target.as_posix()}' (FORMAT PARQUET)
            """
        )
    finally:
        con.close()
    return stamps


def _pipeline(project: Path) -> tuple[dict[str, Any], dict[str, str]]:
    manifest = json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))
    tolerance = str(manifest["weight_tolerance"])
    observation_path = FIXTURE / str(manifest["observation_path"])
    execution_path = FIXTURE / str(manifest["execution_path"])
    benchmark_path = FIXTURE / str(manifest["benchmark_path"])
    # The index constituents, from the benchmark. An index ETF tracks the index rather than
    # belonging to it, so the sleeve is deliberately absent from that file and is read from the
    # fixture manifest instead -- the one place the fixture states a category, because an ETF's
    # price rows are shaped exactly like a share's and nothing downstream can tell them apart.
    members = _universe(benchmark_path)
    kinds: dict[str, str] = dict(manifest["instrument_kinds"])
    sleeve = tuple(str(entry["ticker"]) for entry in manifest["etf_sleeve"])
    # An enhanced-index book is constituents plus an ETF sleeve: that is the shape issue 003 was
    # closed to deliver, and holding one is what makes the KRX sale-tax exemption observable at
    # all. Without the sleeve every name is a share and the exemption never executes here.
    universe = tuple(sorted(set(members) | set(sleeve)))
    if not sleeve:
        raise AssertionError("the fixture declares no ETF sleeve, so the exemption is untestable")
    if any(kinds.get(name) != "etf" for name in sleeve):
        raise AssertionError("the sleeve must be declared etf in the fixture manifest")
    sessions = _sessions(benchmark_path)
    callback_days = sessions[1:]

    register_dataset(
        project,
        DatasetRegistration.of(
            "price_daily",
            "krx-observation",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            # The committed fixture stores close as DECIMAL(18, 4), which no field may be declared
            # as (issue 088): cast to DOUBLE here, and cross back with Decimal(str(...)) on read.
            fields={"close": "CAST(close AS DOUBLE)"},
            field_types={"close": "DOUBLE"},
        ),
        SourceSpec.of("krx-observation", observation_path),
    )
    register_dataset(
        project,
        DatasetRegistration.of(
            "benchmark_weight_daily",
            "krx-benchmark",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            # DECIMAL(18, 8) in the fixture; the same cast, for the same reason.
            fields={"benchmark_weight": "CAST(benchmark_weight AS DOUBLE)"},
            field_types={"benchmark_weight": "DOUBLE"},
        ),
        SourceSpec.of("krx-benchmark", benchmark_path),
    )
    # A halt the Strategy could not have predicted. Tradability is only knowable at execution
    # time, so the Strategy never freezes for it: it keeps targeting the weight it wants, the
    # Exchange refuses the fill while the halt lasts, the position stays put, monitoring keeps
    # reporting, and the next occurrence tries again. That loop is asserted below.
    # Written once and shared by both replicates: a fresh parquet per run would change the
    # registered source digest and make the determinism check fail on our own scaffolding.
    halted_path = OUTPUTS / "execution_with_halt.parquet"
    halt_days = _inject_halt(execution_path, halted_path, universe[0], sessions[6:12])

    register_execution_input(
        project,
        ExecutionInputRegistration.of(
            "krx-daily",
            ExecutionTableSpec(
                source=SourceSpec.of("krx-execution", halted_path),
                trade_at_field="trade_at",
                instrument_field="instrument",
                is_tradable_field="is_tradable",
                price_fields={"close": "close"},
            ),
            FillConvention(FillSelector.SAME_DAY, time(15, 30), VENUE, "close"),
        ),
    )

    # The project declares what each id IS, once, before anything trades. A venue borrows this;
    # it does not own it -- `kind` does not vary by venue, so the fact was never the venue's to
    # state. The Flow binds this roster into the venue's view at run assembly.
    written = export_roster({name: kinds[name] for name in universe}, project)
    declaration = project / "instruments.yaml"
    # `tables:` sits directly under `instruments:`. There is no id above it: a project holds one
    # roster slot and each registration replaces it, so the name this used to carry was echoed
    # back in the receipt and discarded.
    declaration.write_text(
        "instruments:\n  tables:\n"
        + "".join(f"    {kind}: {path.name}\n" for kind, path in sorted(written.items())),
        encoding="utf-8",
    )
    # Registered through the CLI's own entry point, which is what a user runs. Reaching past it
    # would let this showcase pass while `vqapr register` was broken.
    register_cli(argparse.Namespace(declaration=str(declaration)), project_root=project)


    halted_instrument = universe[0]

    paths = _write_components(project, universe, kinds)
    register_strategy_model(project, "show005-alpha", paths["alpha"], "SignedAlpha")
    register_exchange(project, "show005-academic", paths["academic"], "ShowcaseAcademicExchange")
    register_exchange(project, "show005-krx", paths["krx"], "ShowcaseKrxExchange")
    register_strategy_model(
        project,
        "show005-index",
        paths["enhanced"],
        "EnhancedIndex",
        config={
            "benchmark_dataset_id": "benchmark_weight_daily",
            "alpha_dataset_id": "alpha_allocation",
        },
    )
    # The shipped constraints enter through the same door as any user component: a resolved path,
    # a fingerprint and a config. Nothing about them bypasses registration.
    register_constraint(
        project,
        "no-short",
        shipped_constraint_path("no_short"),
        "NoShort",
        config={"constraint_id": "no-short"},
    )
    register_constraint(
        project,
        "single-name-cap",
        shipped_constraint_path("single_name_cap"),
        "SingleNameCap",
        config={
            "cap": CAP,
            "benchmark_dataset_id": "benchmark_weight_daily",
            "tolerance": tolerance,
            "constraint_id": "single-name-cap",
        },
    )


    start = datetime.fromisoformat(f"{callback_days[0].isoformat()}T00:00:00{OFFSET}")
    end = datetime.fromisoformat(f"{callback_days[-1].isoformat()}T23:00:00{OFFSET}")

    alpha_definition = RunDefinition(
        run_id="show005-alpha",
        strategies=(StrategyEntry("show005-alpha"),),
        sessions=tuple(callback_days),
        timezone=VENUE,
        at=time(8, 30),
        exchange="show005-academic",
        execution_input_id="krx-daily",
        start=start,
        end=end,
        initial_account_snapshot=AccountSnapshot(0, INITIAL_CASH, {}),
        initial_account_mode=AccountMode.SIGNED,
        instruments=universe,
    )
    alpha_run = run(
        project, preflight_run(project, alpha_definition), store_root=project / ".vqapr"
    )
    alpha_result = alpha_run.result()

    # The alpha's decisions reach the index run the way any dataset does: the table the alpha
    # run recorded, registered under the id the index subscribes to.
    published = _register_run_table(
        project,
        alpha_run,
        run_id="show005-alpha",
        component_id="show005-alpha",
        dataset_id="alpha_allocation",
        table="vqapr.weight",
        fields={"weight": "CAST(weight AS DOUBLE)"},
        field_types={"weight": "DOUBLE"},
    )

    index_definition = RunDefinition(
        run_id="show005-index",
        strategies=(StrategyEntry("show005-index", ("no-short", "single-name-cap")),),
        sessions=tuple(callback_days),
        timezone=VENUE,
        at=time(9, 0),
        exchange="show005-krx",
        execution_input_id="krx-daily",
        start=start,
        end=end,
        initial_account_snapshot=AccountSnapshot(0, INITIAL_CASH, {}),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=universe,
    )
    index_result = run(project, preflight_run(project, index_definition)).result()

    alpha_memory = _memory(alpha_result)
    index_memory = _memory(index_result)
    index_replay = _replay(index_result)
    index_monitoring = _monitoring(index_result)

    if not index_replay["whole_shares_only"]:
        raise AssertionError("the KRX profile must hold whole shares only")
    # Both frozen outcomes are claimed in the README, so both are checked here rather than merely
    # reported: the pinned holding is returned verbatim every occurrence, and it never drifts
    # outside its own box, which is what keeps this run clear of the known intent-boundary gap.
    if int(index_memory.get("frozen_occurrences", 0)) == 0:
        raise AssertionError("no freeze survived, so frozen invariance was never demonstrated")
    # The recorder's first real-spine evidence: rows that a run() actually produced, not rows a
    # test constructed against the state object. Nothing in this repository had proved this before.
    signal_rows = _recorded_rows(
        project,
        alpha_run,
        run_id="show005-alpha",
        component_id="show005-alpha",
        table="alpha.signal",
    )
    if len(signal_rows) != len(callback_days) * len(universe):
        raise AssertionError(
            f"expected {len(callback_days) * len(universe)} recorded signal rows, "
            f"saw {len(signal_rows)}"
        )
    # Canon 9.2 makes weight and decision-time account state defaults: no Strategy here
    # declares them and every run records them anyway. A default that needed asking for
    # would not be a default.
    default_weight = _recorded_rows(
        project,
        alpha_run,
        run_id="show005-alpha",
        component_id="show005-alpha",
        table="vqapr.weight",
    )
    default_account = _recorded_rows(
        project,
        alpha_run,
        run_id="show005-alpha",
        component_id="show005-alpha",
        table="vqapr.account",
    )
    if not default_weight or not default_account:
        raise AssertionError("the package-owned default records are missing from a real run")
    # ONE account-level row per occurrence, and every one of them carries a nav.
    #
    # This pinned two rows per occurrence while `vqapr.account` had two writers -- a measurement
    # and a null-nav restatement from the callback path. Issue 010 separated the two facts into
    # two tables, so the naive read of this one is now correct: no filter, no nulls, one value
    # per date. A null appearing here again would mean a non-measuring writer came back.
    #
    # The panel rows are what a later reader rebuilds the run's valuation from, since the run
    # itself retains only the marks somebody declared they would read (canon 7.3).
    account_level = [row for row in default_account if row["instrument"] == "_ACCOUNT"]
    if len(account_level) != len(callback_days):
        raise AssertionError(
            f"expected one account-level row per occurrence, saw {len(account_level)}"
        )
    unmeasured = [row for row in account_level if row["nav"] is None]
    if unmeasured:
        raise AssertionError(
            f"{len(unmeasured)} account rows carry no nav; vqapr.account is measurement-only"
        )
    if len(default_account) <= len(account_level):
        raise AssertionError("the account table carries no instrument panel rows")

    envelope = {"run_id", "producer_id", "stage", "event_time", "sequence"}
    if not envelope <= set(signal_rows[0]):
        raise AssertionError("the Flow envelope is missing from a recorded row")

    if int(index_memory.get("frozen_outside_box", 0)) != 0:
        raise AssertionError(
            "a frozen holding drifted outside its box; the intent boundary cannot carry that yet"
        )
    if not any(position for position in index_replay["replayed_positions"].values()):
        raise AssertionError("the enhanced index never took a position")

    # The halt loop, asserted rather than narrated: the Strategy never froze for the halt because
    # it could not have known, it kept ordering, and the venue refused exactly the sessions the
    # halt covered. The run completed regardless -- one untradable name does not stop a rebalance.
    refusals = index_replay["refused_fills"].get(halted_instrument, 0)
    if refusals != len(halt_days):
        raise AssertionError(
            f"expected {len(halt_days)} refused fills for the halted name, saw {refusals}"
        )
    if index_replay["dealt_fills"] == 0:
        raise AssertionError("the halt must not stop the rest of the book from trading")

    trace = {
        "status": "current",
        "verified_against": VERIFIED_AGAINST,
        "last_verified_at": LAST_VERIFIED_AT,
        "universe": list(universe),
        "sessions": len(sessions),
        "callbacks": len(callback_days),
        "fixture": {
            "observation": str(manifest["observation_path"]),
            "execution": str(manifest["execution_path"]),
            "halt": {"instrument": halted_instrument, "sessions": list(halt_days)},
            "benchmark": str(manifest["benchmark_path"]),
            "weight_tolerance": tolerance,
        },
        "recorder": {
            "table": "alpha.signal",
            "rows": len(signal_rows),
            "envelope": sorted(envelope),
            "defaults": {
                "weight": len(default_weight),
                "account": len(default_account),
            },
        },
        "alpha_run": {
            "exchange": "Academic (fractional, zero cost)",
            "account_mode": AccountMode.SIGNED.value,
            "views": alpha_memory.get("views"),
            "published_dataset": published.dataset_id,
            "published_occurrences": published.occurrences,
            "published_rows": published.row_count,
            "publication": "vqapr.weight, registered from the alpha run's record",
        },
        "index_run": {
            "exchange": "KRX (whole shares, 3bp commission, 20bp sale tax, long only)",
            "account_mode": AccountMode.LONG_ONLY.value,
            "subscribed_allocation_inputs": ["alpha_allocation", "benchmark_weight_daily"],
            "shipped_constraints": sorted(SHIPPED_CONSTRAINTS),
            "single_name_cap": CAP,
            "rebalances": index_memory.get("rebalances"),
            "frozen_occurrences": index_memory.get("frozen_occurrences"),
            "frozen_outside_box": index_memory.get("frozen_outside_box"),
            "final_active_norm": index_memory.get("active_norm"),
            **index_monitoring,
            **index_replay,
        },
    }
    digests = {"alpha_allocation": _digest(published.directory)}
    return trace, digests


def main() -> None:
    if OUTPUTS.exists():
        shutil.rmtree(OUTPUTS)
    OUTPUTS.mkdir(parents=True)

    first, first_digests = _pipeline(OUTPUTS / "replicate-a")
    second, second_digests = _pipeline(OUTPUTS / "replicate-b")
    if first != second:
        raise AssertionError("two clean runs disagreed on their reported outcome")
    if first_digests != second_digests:
        raise AssertionError(f"artifact digests differ: {first_digests} vs {second_digests}")

    trace = {**first, "replicates": 2, "artifacts": first_digests}
    (OUTPUTS / "trace.json").write_text(
        json.dumps(trace, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUTPUTS / "manifest.json").write_text(
        json.dumps(first_digests, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    index = trace["index_run"]
    print(f"sessions / callbacks    : {trace['sessions']} / {trace['callbacks']}")
    print(f"alpha views published   : {trace['alpha_run']['published_occurrences']} occurrences")
    print(f"recorded signal rows    : {trace['recorder']['rows']} (first real-spine recorder use)")
    print(f"subscribed inputs       : {', '.join(index['subscribed_allocation_inputs'])}")
    print(f"shipped constraints     : {', '.join(index['shipped_constraints'])}")
    print(f"rebalances              : {index['rebalances']}")
    print(
        f"frozen / drifted out    : {index['frozen_occurrences']} / {index['frozen_outside_box']}"
    )
    print(
        f"monitored occurrences   : {index['monitoring_occurrences']} "
        f"({index['monitoring_drift_findings']} cap-drift findings, 0 short positions)"
    )
    print(f"worst drift             : {json.dumps(index['worst_drift'], sort_keys=True)}")
    print(f"dealt fills             : {index['dealt_fills']} (whole shares)")
    print(f"commission / sale tax   : {index['commission']} / {index['sale_tax']}")
    print(f"replayed == committed   : {index['replayed_cash']} == {index['committed_cash']}")
    print(f"final NAV               : {index['final_nav']}")
    print(f"active-weight L2 norm   : {index['final_active_norm']}")
    print(f"artifacts (2 replicates): {json.dumps(trace['artifacts'], indent=2, sort_keys=True)}")


if __name__ == "__main__":
    main()
