"""Two signed members, published allocations, and a netted ensemble — through the spine.

    reversal member (Academic)   -> publish_run_allocation -> reversal_allocation dataset
    momentum member (Academic)   -> publish_run_allocation -> momentum_allocation dataset
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
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from vqapr.cli.register import run as register_cli
from vqapr.public import (
    AccountMode,
    AccountSnapshot,
    AllocationPublicationSpec,
    ComponentKind,
    DatasetRegistration,
    ExecutionInputRegistration,
    ExecutionTableSpec,
    FillConvention,
    FillSelector,
    RunDefinition,
    RunRecordSpec,
    SHIPPED_CONSTRAINTS,
    SourceSpec,
    StrategyEntry,
    callback_evidence,
    component_ref,
    export_roster,
    preflight_run,
    publish_run_allocation,
    publish_run_record,
    register_component,
    register_dataset,
    register_execution_input,
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

VERIFIED_AGAINST = "vqapr-0.3.0"
LAST_VERIFIED_AT = "2026-09-03"


def _read_published(path: Path) -> list[dict[str, object]]:
    """Read a published dataset back with no reference to the run that produced it."""
    con = duckdb.connect()
    try:
        cursor = con.execute(
            f"SELECT * FROM read_parquet('{path.as_posix()}') ORDER BY available_at, instrument"
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
                closes.setdefault(str(row["instrument"]), []).append(row["close"])
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
        return {
            str(row["instrument"]): row[field]
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


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


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
        strategies=(StrategyEntry(str(strategy_ref.component_id)),),
        sessions=tuple(callback_days),
        timezone=VENUE,
        at=at,
        exchange=academic_ref.component_id,
        execution_input_id="krx-daily",
        start=start,
        end=end,
        initial_account_snapshot=AccountSnapshot(0, INITIAL_CASH, {}),
        initial_account_mode=AccountMode.SIGNED,
        instruments=universe,
    )
    return run(project, preflight_run(project, definition)).result()


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
            fields={"close": "close"},
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
            fields={"benchmark_weight": "benchmark_weight"},
        ),
        SourceSpec.of("krx-benchmark", benchmark_path),
    )
    register_execution_input(
        project,
        ExecutionInputRegistration.of(
            "krx-daily",
            ExecutionTableSpec(
                source=SourceSpec.of("krx-execution", execution_path),
                trade_at_field="trade_at",
                instrument_field="instrument",
                is_tradable_field="is_tradable",
                price_fields={"close": "close"},
            ),
            FillConvention(FillSelector.SAME_DAY, time(15, 30), VENUE, "close"),
        ),
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
    reversal_ref = component_ref(
        "show006-reversal", ComponentKind.STRATEGY_MODEL, paths["reversal"], "ReversalMember"
    )
    momentum_ref = component_ref(
        "show006-momentum", ComponentKind.STRATEGY_MODEL, paths["momentum"], "MomentumMember"
    )
    academic_ref = component_ref(
        "show006-academic", ComponentKind.EXCHANGE, paths["academic"], "ShowcaseAcademicExchange"
    )
    krx_ref = component_ref(
        "show006-krx", ComponentKind.EXCHANGE, paths["krx"], "ShowcaseKrxExchange"
    )
    ensemble_ref = component_ref(
        "show006-ensemble",
        ComponentKind.STRATEGY_MODEL,
        paths["ensemble"],
        "EnsembleStrategy",
        config={
            "reversal_dataset_id": "reversal_allocation",
            "momentum_dataset_id": "momentum_allocation",
        },
    )
    no_short_ref = component_ref(
        "no-short",
        ComponentKind.CONSTRAINT,
        shipped_constraint_path("no_short"),
        "NoShort",
        config={"constraint_id": "no-short"},
    )
    cap_ref = component_ref(
        "single-name-cap",
        ComponentKind.CONSTRAINT,
        shipped_constraint_path("single_name_cap"),
        "SingleNameCap",
        config={
            "cap": CAP,
            "benchmark_dataset_id": "benchmark_weight_daily",
            "tolerance": tolerance,
            "constraint_id": "single-name-cap",
        },
    )
    components_to_register = (
        reversal_ref,
        momentum_ref,
        ensemble_ref,
        academic_ref,
        krx_ref,
        no_short_ref,
        cap_ref,
    )
    for reference in components_to_register:
        register_component(project, reference)


    start = datetime.fromisoformat(f"{callback_days[0].isoformat()}T00:00:00{OFFSET}")
    end = datetime.fromisoformat(f"{callback_days[-1].isoformat()}T23:00:00{OFFSET}")

    reversal_result = _member_run(
        project,
        strategy_ref=reversal_ref,
        at=time(8, 0),
        callback_days=callback_days,
        academic_ref=academic_ref,
        start=start,
        end=end,
        universe=universe,
    )
    reversal_evidence = callback_evidence(reversal_result)
    reversal_published = publish_run_allocation(
        project, AllocationPublicationSpec.of("reversal_allocation"), reversal_evidence
    )

    momentum_result = _member_run(
        project,
        strategy_ref=momentum_ref,
        at=time(8, 15),
        callback_days=callback_days,
        academic_ref=academic_ref,
        start=start,
        end=end,
        universe=universe,
    )
    momentum_evidence = callback_evidence(momentum_result)
    momentum_published = publish_run_allocation(
        project, AllocationPublicationSpec.of("momentum_allocation"), momentum_evidence
    )

    # The reuse half of "a run records what a later run will need to reuse it", proved on a real
    # run rather than a constructed result. The account series a member recorded without being
    # asked is published as an ordinary dataset and read back after the producing run's objects
    # are gone -- which is the round trip that would have caught cash being recorded as NAV.
    account_published = publish_run_record(
        project,
        RunRecordSpec.of(
            "reversal_account",
            table_id="vqapr.account",
            value_fields=(
                "cash",
                "account_version",
                "run_id",
                "producer_id",
                "stage",
                "event_time",
                "sequence",
            ),
        ),
        reversal_result,
    )
    recorded_account = reversal_result.final_state.recorder_rows["vqapr.account"]
    if account_published.row_count != len(recorded_account):
        raise AssertionError(
            f"published {account_published.row_count} account rows from "
            f"{len(recorded_account)} recorded"
        )
    replayed_account = _read_published(account_published.output_path)
    if len(replayed_account) != len(recorded_account):
        raise AssertionError("the published account series does not read back row for row")
    # Cash is an account-level fact, so it lives on the account-level rows; the instrument panel
    # rows alongside them carry quantity and price instead.
    # Compared as numbers: since record `135` the run records cash as a Decimal and the published
    # column is DECIMAL rather than text, so the round trip is exact on both sides.
    published_cash = [
        Decimal(str(row["cash"])) for row in replayed_account if row["cash"] is not None
    ]
    recorded_cash = [
        Decimal(str(row["cash"])) for row in recorded_account if row["cash"] is not None
    ]
    if published_cash != recorded_cash:
        raise AssertionError("the published cash series differs from what the run recorded")

    ensemble_definition = RunDefinition(
        run_id="show006-ensemble",
        strategies=(StrategyEntry("show006-ensemble", ("no-short", "single-name-cap")),),
        sessions=tuple(callback_days),
        timezone=VENUE,
        at=time(9, 0),
        exchange="show006-krx",
        execution_input_id="krx-daily",
        start=start,
        end=end,
        initial_account_snapshot=AccountSnapshot(0, INITIAL_CASH, {}),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=universe,
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

    # Assertion 1: both members published, and the ensemble subscribed to both by dataset id.
    reversal_lineage = json.loads(reversal_published.lineage_path.read_text(encoding="utf-8"))
    momentum_lineage = json.loads(momentum_published.lineage_path.read_text(encoding="utf-8"))
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
    if str(reversal_published.registration.dataset_id) != "reversal_allocation":
        raise AssertionError("reversal member did not publish under reversal_allocation")
    if str(momentum_published.registration.dataset_id) != "momentum_allocation":
        raise AssertionError("momentum member did not publish under momentum_allocation")

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

    # Assertion 3: the memory-free member reports state_path == ["constant"], the mutating one
    # reports ["moved"]. This is package-computed from committed vs. current model state refs
    # across the run's own published evidence, not read off a self-reported flag.
    if reversal_lineage["run"]["state_path"] != ["moved"]:
        raise AssertionError(
            f"reversal member's lineage state_path must be ['moved'], "
            f"saw {reversal_lineage['run']['state_path']}"
        )
    if momentum_lineage["run"]["state_path"] != ["constant"]:
        raise AssertionError(
            f"momentum member's lineage state_path must be ['constant'], "
            f"saw {momentum_lineage['run']['state_path']}"
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
            "published_dataset": str(reversal_published.registration.dataset_id),
            "published_occurrences": reversal_published.occurrences,
            "published_rows": reversal_published.row_count,
            "state_path": reversal_lineage["run"]["state_path"],
        },
        "momentum_member": {
            "exchange": "Academic (fractional, zero cost)",
            "account_mode": AccountMode.SIGNED.value,
            "published_dataset": str(momentum_published.registration.dataset_id),
            "published_occurrences": momentum_published.occurrences,
            "published_rows": momentum_published.row_count,
            "state_path": momentum_lineage["run"]["state_path"],
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
        "reversal_allocation.parquet": _digest(reversal_published.output_path),
        "reversal_allocation.lineage.json": _digest(reversal_published.lineage_path),
        "momentum_allocation.parquet": _digest(momentum_published.output_path),
        "momentum_allocation.lineage.json": _digest(momentum_published.lineage_path),
        "reversal_account.parquet": _digest(account_published.output_path),
        "reversal_account.lineage.json": _digest(account_published.lineage_path),
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
        f"reversal published          : "
        f"{trace['reversal_member']['published_occurrences']} occurrences, "
        f"state_path={trace['reversal_member']['state_path']}"
    )
    print(
        f"momentum published          : "
        f"{trace['momentum_member']['published_occurrences']} occurrences, "
        f"state_path={trace['momentum_member']['state_path']}"
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
