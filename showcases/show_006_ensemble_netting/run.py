"""Two signed members, published allocations, and a netted ensemble — through the spine.

    reversal member (Academic)   -> its recorded vqapr.weight, registered -> reversal_allocation
    momentum member (Academic)   -> its recorded vqapr.weight, registered -> momentum_allocation
                                                                        |
                                                                        + --> ensemble run (KRX)
                                                                                subscribes to both,
                                                                                nets per ticker,
                                                                                equal-weights,
                                                                                rescales to budget,
                                                                                projects onto
                                                                                NoShort and
                                                                                SingleNameCap

All three runs are ordinary runs: `RunDefinition`, `preflight_run`, `run`, a real `Account`, real
order planning and the declared execution profile. `reversal` mutates `self.memory` every
occurrence, exactly as show_005's alpha does; `momentum` never assigns `self.memory` at all, so its
published lineage carries `state_path == ["constant"]` while `reversal`'s carries `["moved"]` — the
package-computed, unforgeable proof that one callback body actually moved state and the other did
not.

The ensemble reads **two allocation inputs** — the published `reversal_allocation` and
`momentum_allocation` datasets — through ordinary `DataRequirement` subscriptions inside its
point-in-time window. It measures what combining them implies with `net_members` (ticker-level
long side, short side, the offset that cancelled, and what survived), combines the members by
`equal_weight` and matches its own gross-active budget with `rescale`. Long-only is never asked of
either member: it emerges only from the registered `no_short` and `single_name_cap` constraints the
ensemble runs under on the KRX profile.

The fill journal the ensemble run committed is replayed independently against the committed
`Account`, and the whole pipeline runs twice into separate projects so the artifact digests can be
compared.

Everything here is real KRX data committed under `tests/fixtures/real`. Nothing here invents a
price or a signal.

Reproduce::

    uv run python showcases/show_006_ensemble_netting/run.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from vqapr.cli.register import run as register_cli
from vqapr.public import (
    SHIPPED_CONSTRAINTS,
    AccountMode,
    AccountSnapshot,
    DatasetRegistration,
    RunAgenda,
    RunDefinition,
    RunExecution,
    RunFill,
    SourceSpec,
    StrategyEntry,
    callback_evidence,
    export_roster,
    preflight_run,
    register_constraint,
    register_dataset,
    register_exchange,
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

MEMBER_BUDGET = Decimal("0.04")
"""Total absolute active weight each member is allowed to express."""

ENSEMBLE_BUDGET = Decimal("0.04")
"""Total absolute active weight the ensemble is rescaled to after equal-weight combination."""

REVERSAL_LOOKBACK = 6
"""Six closes span a five-session return."""

MOMENTUM_LOOKBACK = 11
"""Eleven closes span a ten-session return."""

VERIFIED_AGAINST = "vqapr-0.8.0"
LAST_VERIFIED_AT = "2026-09-08"


def _read_published(path: Path) -> list[dict[str, object]]:
    """Read a published dataset back with no reference to the run that produced it."""
    con = duckdb.connect()
    try:
        cursor = con.execute(
            "SELECT *, event_time AS available_at "
            f"FROM read_parquet('{path.as_posix()}/*.parquet', union_by_name = true) "
            "ORDER BY available_at, instrument"
        )
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    finally:
        con.close()


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


def _member_source(
    *,
    strategy_id: str,
    class_name: str,
    lookback: int,
    horizon_sign: str,
    memory_write: str,
) -> str:
    """Both members share the same shape: read closes, demean a cross-sectional return, size and
    rescale to a fixed gross active budget. Only the horizon and the memory-mutation behaviour
    differ, and both differences are the entire point of this showcase.
    """
    return (
        f'''"""A dollar-neutral cross-sectional view, published as an allocation input."""

from __future__ import annotations

from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from vqapr.public import (
    Budget,
    DataRequirement,
    Hold,
    PortfolioDirection,
    Rebalance,
    RowsLookback,
    StrategyModel,
    equal_weight,
    rescale,
)

LOOKBACK = {lookback}
ACTIVE_BUDGET = Decimal("{MEMBER_BUDGET}")

BUDGET = Budget(
    PortfolioDirection.SIGNED,
    Decimal("0"),
    Decimal("2"),
    Decimal("-1"),
    Decimal("1"),
)


class {class_name}(StrategyModel):
    """{horizon_sign}, demeaned, sized equal-weight and rescaled to a fixed gross active budget."""

    def requirements(self):
        return (
            DataRequirement.of('price_daily', 'close', lookback=RowsLookback(LOOKBACK)),
        )

    def decide(self, context):
        {memory_write}

        rows = context.window.observations(self.requirements()[0]).rows
        closes: dict[str, list[Decimal]] = {{}}
        for row in rows:
            if row["close"] is not None:
                # A DOUBLE field arrives as a float; cross to Decimal once, through str.
                closes.setdefault(str(row["instrument"]), []).append(Decimal(str(row["close"])))
        eligible = {{
            name: values for name, values in closes.items() if len(values) == LOOKBACK
        }}
        if len(eligible) < 2:
            return Hold(reason="a cross-sectional view needs at least two names with full history")

        raw = {{
            name: -1 * (values[-1] / values[0] - Decimal(1))
            for name, values in eligible.items()
        }}
        mean = sum(raw.values()) / len(raw)
        centred = {{name: value - mean for name, value in raw.items()}}
        if all(value == 0 for value in centred.values()):
            return Hold(reason="the cross-section is flat")

        sized = equal_weight(centred)
        weights = rescale(sized, long=ACTIVE_BUDGET, short=-ACTIVE_BUDGET)

        return Rebalance(
            target_weights=dict(sorted(weights.items())),
            cash_weight=Decimal(1) - sum(weights.values()),
            budget=BUDGET,
        )
'''
        + _SOURCE_REFS
    )


_REVERSAL_SOURCE = _member_source(
    strategy_id="show006-reversal",
    class_name="ReversalMember",
    lookback=REVERSAL_LOOKBACK,
    horizon_sign="A five-day price reversal",
    memory_write=(
        "history = dict(self.memory or {})\n"
        '        history["occurrences"] = int(history.get("occurrences", 0)) + 1\n'
        "        self.memory = history"
    ),
)

_MOMENTUM_SOURCE = _member_source(
    strategy_id="show006-momentum",
    class_name="MomentumMember",
    lookback=MOMENTUM_LOOKBACK,
    horizon_sign="A ten-day price momentum tilt",
    memory_write=(
        "# self.memory is deliberately never assigned: this member's published lineage must\n"
        '        # report state_path == ["constant"], proving the memory-free path structurally.'
    ),
)
# The momentum member's raw signal must be the *return itself*, not its negation, so the two
# members disagree in sign on genuinely reversing names. Patch the sign back for momentum only.
_MOMENTUM_SOURCE = _MOMENTUM_SOURCE.replace(
    "raw = {\n            name: -1 * (values[-1] / values[0] - Decimal(1))\n"
    "            for name, values in eligible.items()\n        }",
    "raw = {\n            name: values[-1] / values[0] - Decimal(1)\n"
    "            for name, values in eligible.items()\n        }",
)


_ENSEMBLE_SOURCE = (
    '''"""An ensemble built by netting two subscribed member allocations."""

from __future__ import annotations

from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from vqapr.public import (
    AllocationInvariants,
    AllocationSign,
    Budget,
    DataRequirement,
    Hold,
    PortfolioDirection,
    QUANTUM,
    Rebalance,
    RowsLookback,
    StrategyModel,
    TableSpec,
    equal_weight,
    net_members,
    optimize,
    rescale,
    validate_allocation,
)

ENSEMBLE_BUDGET = Decimal("'''
    + str(ENSEMBLE_BUDGET)
    + '''")
NEUTRALITY = Decimal("0.000000001")
"""What "dollar neutral" is allowed to mean once a published member lands on the canonical grid."""

BUDGET = Budget(
    PortfolioDirection.LONG_ONLY,
    Decimal("0"),
    Decimal("1"),
    Decimal("0"),
    Decimal("1"),
)


class EnsembleStrategy(StrategyModel):
    """desired = equal-weight(reversal, momentum) rescaled to budget, projected onto the shipped
    constraint set. Long-only is emergent: neither member is filtered before combination."""

    def __init__(self, *, reversal_dataset_id: str, momentum_dataset_id: str) -> None:
        self._reversal_dataset_id = reversal_dataset_id
        self._momentum_dataset_id = momentum_dataset_id

    def tables(self):
        return (
            TableSpec(
                "ensemble.netting",
                ("instrument", "long_weight", "short_weight", "offset_weight", "net_weight"),
            ),
        )

    def requirements(self):
        return (
            DataRequirement.of(self._reversal_dataset_id, "weight", lookback=RowsLookback(1)),
            DataRequirement.of(self._momentum_dataset_id, "weight", lookback=RowsLookback(1)),
        )

    def _panel(self, context, requirement):
        field = requirement.field_id
        # A DOUBLE field arrives as a float; cross to Decimal once, through str.
        return {
            str(row["instrument"]): Decimal(str(row[field]))
            for row in context.window.observations(requirement).rows
            if row[field] is not None
        }

    def decide(self, context):
        reversal_requirement, momentum_requirement = self.requirements()
        reversal = self._panel(context, reversal_requirement)
        momentum = self._panel(context, momentum_requirement)
        if not reversal or not momentum:
            return Hold(reason="both member allocation inputs must be visible before netting them")

        # Each subscribed member is validated at consumption time as a signed, dollar-neutral
        # allocation. No constraint owns either input, so the consuming Strategy checks both
        # before a single weight is combined.
        for label, panel in (("reversal member", reversal), ("momentum member", momentum)):
            validate_allocation(
                panel,
                AllocationInvariants.of(
                    sign=AllocationSign.SIGNED,
                    weight_sum_upper=Decimal(0),
                    tolerance=NEUTRALITY,
                ),
                label=label,
            )

        # The measurement UC-ENSEMBLE-001 requires: what does netting these two published
        # allocations imply, ticker by ticker? This never decides the combination; it is read
        # afterward and stored for the trace, never fed back into desired.
        netting = net_members([reversal, momentum], instruments=sorted(context.window.instruments))
        self.recorder.append_batch(
            "ensemble.netting",
            tuple(
                {
                    "instrument": name,
                    "long_weight": str(measured.long_weight),
                    "short_weight": str(measured.short_weight),
                    "offset_weight": str(measured.offset_weight),
                    "net_weight": str(measured.net_weight),
                }
                for name, measured in sorted(netting.items())
            ),
        )

        # The economic combination is the Strategy's own choice: simple equal weight over the two
        # members' *net* per-ticker weight, then rescaled to this run's own declared gross active
        # budget. Neither member is filtered before combining -- long-only is never asked of
        # either member here.
        net_signal = {name: measured.net_weight for name, measured in netting.items()}
        if all(value == 0 for value in net_signal.values()):
            return Hold(reason="the netted signal is flat")
        combined = equal_weight(net_signal)
        desired_active = rescale(combined, long=ENSEMBLE_BUDGET, short=-ENSEMBLE_BUDGET)

        bounds = context.constraint_bounds
        instruments = tuple(sorted(bounds.lower_weights))
        desired = {
            name: desired_active.get(name, Decimal(0)).quantize(QUANTUM) for name in instruments
        }

        result = optimize(
            desired=desired,
            current={},
            lower=dict(bounds.lower_weights),
            upper=dict(bounds.upper_weights),
            frozen=frozenset(),
            cash_range=(Decimal("0"), Decimal("1")),
        )

        history = dict(self.memory or {})
        history["rebalances"] = int(history.get("rebalances", 0)) + 1
        self.memory = history

        return Rebalance(
            target_weights=dict(sorted(result.weights.items())),
            cash_weight=result.cash,
            budget=BUDGET,
        )
'''
    + _SOURCE_REFS
)


def _write_components(project: Path, universe: tuple[str, ...]) -> dict[str, Path]:
    components = project / "components"
    components.mkdir(parents=True, exist_ok=True)

    reversal = components / "reversal.py"
    reversal.write_text(_REVERSAL_SOURCE, encoding="utf-8")

    momentum = components / "momentum.py"
    momentum.write_text(_MOMENTUM_SOURCE, encoding="utf-8")

    ensemble = components / "ensemble.py"
    ensemble.write_text(_ENSEMBLE_SOURCE, encoding="utf-8")

    academic = components / "academic_exchange.py"
    academic.write_text(
        f'''"""Fractional quantity, zero cost, full fill — the venue each member runs on."""

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
            "show006-academic",
        )
''',
        encoding="utf-8",
    )

    krx = components / "krx_exchange.py"
    krx.write_text(
        f'''"""Whole shares, 3bp commission both sides, 20bp sale tax, long only."""

from __future__ import annotations

from vqapr.public import KrxExchange, Rebalance

UNIVERSE = {universe!r}


class ShowcaseKrxExchange(KrxExchange):
    def __init__(self):
        super().__init__(UNIVERSE, "show006-krx")
''',
        encoding="utf-8",
    )
    return {
        "reversal": reversal,
        "momentum": momentum,
        "ensemble": ensemble,
        "academic": academic,
        "krx": krx,
    }


def _replay(result: Any) -> dict[str, Any]:
    """Rebuild cash and positions from the fill journal and demand an exact match."""
    account = result.final_state.account
    cash = INITIAL_CASH
    positions: dict[str, Decimal] = {}
    commission = Decimal(0)
    tax = Decimal(0)
    dealt = 0
    for row in _recorded_fills(result):
        if Decimal(row["dealt_quantity"]) == 0:
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
        "any_short": any(quantity < 0 for quantity in snapshot.positions.values()),
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
    first_day: date
    """The venue-local day of the first row, which is the first day a reader can read it."""


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
        rows, occurrences, first = con.execute(
            f"SELECT count(*), count(DISTINCT event_time), min(event_time) "
            f"FROM read_parquet('{directory.as_posix()}/*.parquet', union_by_name = true)"
        ).fetchone()
    finally:
        con.close()
    first_day = (
        first.astimezone(ZoneInfo(VENUE)) if first.tzinfo is not None else first
    ).date()
    return _Registered(dataset_id, directory, int(rows), int(occurrences), first_day)


def _member_run(
    project: Path,
    *,
    strategy_ref: Any,
    at: time,
    callback_days: list[date],
    academic_ref: Any,
    start: datetime,
    end: datetime,
    universe: tuple[str, ...],
) -> Any:
    definition = RunDefinition(
        run_id=str(strategy_ref.component_id),
        strategy=StrategyEntry(str(strategy_ref.component_id)),
        timezone=VENUE,
        agenda=RunAgenda(every="1d", at=(at,)),
        exchange=academic_ref.component_id,
        execution=RunExecution(
            dataset="krx-daily",
            fill=RunFill(
                selector="same_day",
                at=time(15, 30),
                timezone=VENUE,
                trade_price="close",
            ),
        ),
        start=start,
        end=end,
        initial_account_snapshot=AccountSnapshot(0, INITIAL_CASH, {}),
        initial_account_mode=AccountMode.SIGNED,
        instruments=universe,
        writes=f"{str(strategy_ref.component_id)}-weights",
    )
    return run(project, preflight_run(project, definition), store_root=project / ".vqapr")


def _pipeline(project: Path) -> tuple[dict[str, Any], dict[str, str]]:
    manifest = json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))
    tolerance = str(manifest["weight_tolerance"])
    observation_path = FIXTURE / str(manifest["observation_path"])
    execution_path = FIXTURE / str(manifest["execution_path"])
    benchmark_path = FIXTURE / str(manifest["benchmark_path"])
    universe = _universe(benchmark_path)
    sessions = _sessions(benchmark_path)
    all_days = sessions[1:]
    # The momentum member needs an eleven-close history (ten-session return); the reversal
    # member needs six. Both members and the ensemble share one callback calendar, so only
    # sessions where both members have enough history produce a decision -- the rest decline.
    # This is asserted below rather than hidden by trimming the agenda to fit the signal.
    callback_days = all_days

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
    register_dataset(
        project,
        # The venue table is a dataset with an execution role (record 185): `trade_at` is the
        # instant its row is a fact about, the role names the tradable flag, and which price
        # a run fills at is that run's own `execution.fill.trade_price`.
        DatasetRegistration.of(
            "krx-daily",
            "krx-execution",
            instrument_field="instrument",
            available_at="trade_at",
            grain="instrument_instant",
            key_fields=("trade_at", "instrument"),
            fields={"close": "CAST(close AS DOUBLE)", "is_tradable": "is_tradable"},
            field_types={"close": "DOUBLE", "is_tradable": "BOOLEAN"},
            execution={"is_tradable": "is_tradable"},
        ),
        SourceSpec.of("krx-execution", execution_path),
    )

    # The project declares what each id IS, once, before anything trades. `KrxExchange` resolves
    # what a fill costs from this roster rather than from the venue, so the KRX profile cannot run
    # without it. This fixture trades stocks only, so every name is declared a stock.
    written = export_roster(dict.fromkeys(universe, "stock"), project)
    roster_declaration = project / "instruments.yaml"
    roster_declaration.write_text(
        "instruments:\n  tables:\n"
        + "".join(f"    {kind}: {path.name}\n" for kind, path in sorted(written.items())),
        encoding="utf-8",
    )
    # Registered through the CLI's own entry point, which is what a user runs.
    register_cli(argparse.Namespace(declaration=str(roster_declaration)), project_root=project)

    paths = _write_components(project, universe)
    reversal_ref = register_strategy_model(
        project, "show006-reversal", paths["reversal"], "ReversalMember",
    )
    momentum_ref = register_strategy_model(
        project, "show006-momentum", paths["momentum"], "MomentumMember",
    )
    academic_ref = register_exchange(
        project, "show006-academic", paths["academic"], "ShowcaseAcademicExchange",
    )
    register_exchange(project, "show006-krx", paths["krx"], "ShowcaseKrxExchange")
    register_strategy_model(
        project,
        "show006-ensemble",
        paths["ensemble"],
        "EnsembleStrategy",
        config={
            "reversal_dataset_id": "reversal_allocation",
            "momentum_dataset_id": "momentum_allocation",
        },
    )
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

    reversal_run = _member_run(
        project,
        strategy_ref=reversal_ref,
        at=time(8, 0),
        callback_days=callback_days,
        academic_ref=academic_ref,
        start=start,
        end=end,
        universe=universe,
    )
    reversal_result = reversal_run.result()
    reversal_published = _register_run_table(
        project,
        reversal_run,
        run_id=str(reversal_ref.component_id),
        component_id=str(reversal_ref.component_id),
        dataset_id="reversal_allocation",
        table="vqapr.weight",
        fields={"weight": "CAST(weight AS DOUBLE)"},
        field_types={"weight": "DOUBLE"},
    )

    momentum_run = _member_run(
        project,
        strategy_ref=momentum_ref,
        at=time(8, 15),
        callback_days=callback_days,
        academic_ref=academic_ref,
        start=start,
        end=end,
        universe=universe,
    )
    momentum_result = momentum_run.result()
    momentum_published = _register_run_table(
        project,
        momentum_run,
        run_id=str(momentum_ref.component_id),
        component_id=str(momentum_ref.component_id),
        dataset_id="momentum_allocation",
        table="vqapr.weight",
        fields={"weight": "CAST(weight AS DOUBLE)"},
        field_types={"weight": "DOUBLE"},
    )

    # The reuse half of "a run records what a later run will need to reuse it", proved on a real
    # run rather than a constructed result. The account series a member recorded without being
    # asked is registered as an ordinary dataset and read back after the producing run's objects
    # are gone -- which is the round trip that would have caught cash being recorded as NAV.
    account_published = _register_run_table(
        project,
        reversal_run,
        run_id=str(reversal_ref.component_id),
        component_id=str(reversal_ref.component_id),
        dataset_id="reversal_account",
        table="vqapr.account",
        fields={"cash": "cash", "account_version": "account_version", "run_id": "run_id"},
        # `cash` is decimal-marked text in the record (record.py `_arrow_type`), so VARCHAR is its
        # declared type; the comparison below reads the raw parquet and crosses back itself.
        field_types={"cash": "VARCHAR", "account_version": "INTEGER", "run_id": "VARCHAR"},
    )
    recorded_account = _recorded_rows(
        project,
        reversal_run,
        run_id=str(reversal_ref.component_id),
        component_id=str(reversal_ref.component_id),
        table="vqapr.account",
    )
    if account_published.row_count != len(recorded_account):
        raise AssertionError(
            f"registered {account_published.row_count} account rows from "
            f"{len(recorded_account)} recorded"
        )
    replayed_account = _read_published(account_published.directory)
    if len(replayed_account) != len(recorded_account):
        raise AssertionError("the published account series does not read back row for row")
    # Cash is an account-level fact, so it lives on the account-level rows; the instrument panel
    # rows alongside them carry quantity and price instead.
    # Compared as numbers: since record `135` the run records cash as a Decimal, stored as
    # decimal-marked text, so `Decimal(str(...))` is exact on both sides of the round trip.
    published_cash = [
        Decimal(str(row["cash"])) for row in replayed_account if row["cash"] is not None
    ]
    recorded_cash = [
        Decimal(str(row["cash"])) for row in recorded_account if row["cash"] is not None
    ]
    if published_cash != recorded_cash:
        raise AssertionError("the published cash series differs from what the run recorded")

    # The ensemble reads what its members published, so its horizon opens on the first day EVERY
    # member has a weight on record. A member declines until its lookback fills, and a decline
    # records no weight, so the allocation datasets begin days after the members' own agenda
    # does; an ensemble opening with the members would ask its first decision to read an empty
    # window, which `vqapr check` refuses (`check.lookback.uncovered`) -- and since record 168
    # `preflight_run` asks the same judgments, so this script was refused too. The members'
    # declines above are still asserted, not trimmed; only the ensemble waits for its inputs.
    ensemble_opens = max(member.first_day for member in (reversal_published, momentum_published))
    ensemble_days = [day for day in callback_days if day >= ensemble_opens]
    ensemble_start = datetime.fromisoformat(f"{ensemble_days[0].isoformat()}T00:00:00{OFFSET}")
    ensemble_definition = RunDefinition(
        run_id="show006-ensemble",
        strategy=StrategyEntry("show006-ensemble", ("no-short", "single-name-cap")),
        timezone=VENUE,
        agenda=RunAgenda(every="1d", at=(time(9, 0),)),
        exchange="show006-krx",
        execution=RunExecution(
            dataset="krx-daily",
            fill=RunFill(
                selector="same_day",
                at=time(15, 30),
                timezone=VENUE,
                trade_price="close",
            ),
        ),
        start=ensemble_start,
        end=end,
        initial_account_snapshot=AccountSnapshot(0, INITIAL_CASH, {}),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=universe,
        writes="show006-ensemble-weights",
    )
    ensemble_result = run(project, preflight_run(project, ensemble_definition)).result()

    reversal_memory = _memory(reversal_result)
    momentum_memory = _memory(momentum_result)
    ensemble_memory = _memory(ensemble_result)
    ensemble_replay = _replay(ensemble_result)

    if momentum_memory:
        raise AssertionError(
            f"momentum member must never assign self.memory; saw {momentum_memory}"
        )

    # Assertion 1: both members' tables are registered, and the ensemble subscribed to both by
    # dataset id.
    subscribed = {"reversal_allocation", "momentum_allocation"}
    # The ensemble's own strategy_accesses over its callbacks are the authoritative proof of what
    # it actually subscribed to and read -- not a static declaration read off the component.
    ensemble_evidence = callback_evidence(ensemble_result)
    accessed_datasets = {
        str(access.dataset_id)
        for evidence in ensemble_evidence
        for access in evidence.strategy_accesses
    }
    if not subscribed <= accessed_datasets:
        raise AssertionError(
            f"ensemble did not subscribe to both member datasets: saw {sorted(accessed_datasets)}"
        )
    if reversal_published.dataset_id != "reversal_allocation":
        raise AssertionError("reversal member's table is not registered as reversal_allocation")
    if momentum_published.dataset_id != "momentum_allocation":
        raise AssertionError("momentum member's table is not registered as momentum_allocation")

    # Assertion 2: at least one ticker on at least one occurrence disagreed (non-zero offset).
    netting_rows = ensemble_result.final_state.recorder_rows.get("ensemble.netting", ())
    if not netting_rows:
        raise AssertionError("the ensemble never recorded a netting measurement")
    max_offset = max(Decimal(row["offset_weight"]) for row in netting_rows)
    if max_offset <= 0:
        raise AssertionError(
            "no ticker-occurrence showed a non-zero offset_weight; the members never disagreed"
        )
    crossing_occurrences = len(
        {row["event_time"] for row in netting_rows if Decimal(row["offset_weight"]) > 0}
    )

    # Assertion 3: the mutating member carried state across the run and the memory-free one did
    # not. Read off the run's own final model state (`_memory`), the same source the publication
    # lineage used to derive its `state_path` from before that path went (campaign Step 4).
    if not reversal_memory:
        raise AssertionError("reversal member must carry state across the run; its memory is empty")
    if momentum_memory:
        raise AssertionError(
            f"momentum member must never assign self.memory; saw {momentum_memory}"
        )

    # Assertion 4 (the fill-journal replay against the committed Account) already aborted inside
    # _replay() if it disagreed; re-check the derived facts here so a regression in _replay itself
    # cannot silently pass.
    if ensemble_replay["replayed_cash"] != ensemble_replay["committed_cash"]:
        raise AssertionError("fill-journal replay diverged from the committed Account")
    if not ensemble_replay["whole_shares_only"]:
        raise AssertionError("the KRX profile must hold whole shares only")
    if ensemble_replay["any_short"]:
        raise AssertionError("a long-only ensemble account marked a short position")
    if int(ensemble_memory.get("rebalances", 0)) == 0:
        raise AssertionError("the ensemble never rebalanced; nothing to net was ever executed")
    if not any(position for position in ensemble_replay["replayed_positions"].values()):
        raise AssertionError("the ensemble never took a position")

    trace = {
        "status": "current",
        "verified_against": VERIFIED_AGAINST,
        "last_verified_at": LAST_VERIFIED_AT,
        "universe": list(universe),
        "sessions": len(sessions),
        "callbacks": len(callback_days),
        "ensemble_callbacks": len(ensemble_days),
        "run_record": {
            "dataset": "reversal_account",
            "rows": account_published.row_count,
            "read_back": len(replayed_account),
        },
        "crossing_occurrences": crossing_occurrences,
        "max_offset_weight": str(max_offset),
        "reversal_member": {
            "exchange": "Academic (fractional, zero cost)",
            "account_mode": AccountMode.SIGNED.value,
            "occurrences": reversal_memory.get("occurrences"),
            "published_dataset": reversal_published.dataset_id,
            "published_occurrences": reversal_published.occurrences,
            "published_rows": reversal_published.row_count,
        },
        "momentum_member": {
            "exchange": "Academic (fractional, zero cost)",
            "account_mode": AccountMode.SIGNED.value,
            "published_dataset": momentum_published.dataset_id,
            "published_occurrences": momentum_published.occurrences,
            "published_rows": momentum_published.row_count,
        },
        "ensemble_run": {
            "exchange": "KRX (whole shares, 3bp commission, 20bp sale tax, long only)",
            "account_mode": AccountMode.LONG_ONLY.value,
            "subscribed_allocation_inputs": sorted(subscribed),
            "shipped_constraints": sorted(SHIPPED_CONSTRAINTS),
            "single_name_cap": CAP,
            "rebalances": ensemble_memory.get("rebalances"),
            **ensemble_replay,
        },
    }
    digests = {
        "reversal_allocation": _digest(reversal_published.directory),
        "momentum_allocation": _digest(momentum_published.directory),
        "reversal_account": _digest(account_published.directory),
    }
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

    ensemble = trace["ensemble_run"]
    print(f"sessions / callbacks       : {trace['sessions']} / {trace['callbacks']}")
    print(
        f"reversal registered         : "
        f"{trace['reversal_member']['published_occurrences']} occurrences as "
        f"{trace['reversal_member']['published_dataset']} (from the member run's own record)"
    )
    print(
        f"momentum registered         : "
        f"{trace['momentum_member']['published_occurrences']} occurrences as "
        f"{trace['momentum_member']['published_dataset']} (from the member run's own record)"
    )
    print(
        f"run record round trip       : {trace['run_record']['rows']} account rows published "
        f"and read back from a real run"
    )
    print(f"subscribed inputs           : {', '.join(ensemble['subscribed_allocation_inputs'])}")
    print(f"crossing occurrences        : {trace['crossing_occurrences']}")
    print(f"max ticker offset_weight    : {trace['max_offset_weight']}")
    print(f"shipped constraints         : {', '.join(ensemble['shipped_constraints'])}")
    print(f"rebalances                  : {ensemble['rebalances']}")
    print(f"dealt fills                 : {ensemble['dealt_fills']} (whole shares)")
    print(f"commission / sale tax       : {ensemble['commission']} / {ensemble['sale_tax']}")
    print(
        f"replayed == committed       : {ensemble['replayed_cash']} == {ensemble['committed_cash']}"
    )
    print(f"final NAV                   : {ensemble['final_nav']}")
    print(f"any short position          : {ensemble['any_short']}")
    print(
        f"artifacts (2 replicates)    : {json.dumps(trace['artifacts'], indent=2, sort_keys=True)}"
    )


if __name__ == "__main__":
    main()
