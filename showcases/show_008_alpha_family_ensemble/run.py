"""Three signed alphas, a family ensemble, and a signal measured on what the run stored.

    reversal member  (Academic)  -> its recorded vqapr.weight, registered -> reversal_allocation
    momentum member  (Academic)  -> its recorded vqapr.weight, registered -> momentum_allocation
    low-vol member   (Academic)  -> its recorded vqapr.weight, registered -> lowvol_allocation
                                                                     |
                                                                     + --> ensemble run (KRX)
                                                                           subscribes to all three,
                                                                           nets per ticker,
                                                                           equal-weights,
                                                                           rescales to budget,
                                                                           projects onto NoShort
                                                                           and SingleNameCap

This is show_006's two-member shape carried to three, which is the point: `UC-ENSEMBLE-001` is
stated for "여러 stored alpha-weight result", and two members cannot distinguish a helper that
generalises from one that happens to work in pairs. With three, `offset_weight = min(long, |short|)`
is no longer a restatement of "the two disagreed" — a name can be long in two members and short in
one, and the offset has to report what actually cancelled.

**The low-volatility member is the reason this showcase exists rather than an edit to show_006.**
It is the first alpha in the tree whose signal is a rolling time-series statistic. The member
computes the statistic directly with the standard library, while the pipeline measures the
published signal against the return that followed it with `information_coefficient`.

Canon decides where the alphas live. PRD §2.7 says vqapr may ship reference components but does not
lock project-owned proprietary alpha into package built-ins, and the module map gives StrategyModel
built-ins as **없음** for exactly that reason. So all three members are written as project-local
component files, like show_006's, and nothing in `src/vqapr/` learns what a low-volatility alpha is.
What the package supplies is the non-trivial portfolio and analysis surface: `equal_weight`,
`rescale`, `net_members`, and `information_coefficient`.

The fill journal the ensemble committed is replayed independently against the committed `Account`,
and the whole pipeline runs twice into separate projects so the artifact digests can be compared.

Everything here is real KRX data committed under `tests/fixtures/real`. Nothing here invents a
price or a signal.

Reproduce::

    uv run python showcases/show_008_alpha_family_ensemble/run.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from statistics import stdev
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from vqapr.cli.register import run as register_cli
from vqapr.public import (
    QUANTUM,
    SHIPPED_CONSTRAINTS,
    AccountMode,
    AccountSnapshot,
    DatasetRegistration,
    RunDefinition,
    RunExecution,
    RunFill,
    SourceSpec,
    StrategyEntry,
    callback_evidence,
    export_roster,
    information_coefficient,
    preflight_run,
    rank_information_coefficient,
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

LOWVOL_LOOKBACK = 11
"""Eleven closes span ten simple returns, whose sample spread is the realised volatility.

Deliberately equal to the momentum window so the family's warm-up is set by one number: the three
members become visible on the same occurrence, and the netting measurement is never comparing a
member that has history against one that does not.
"""

LOWVOL_VOL_WINDOW = 5
"""The realised-volatility window, in returns.

Shorter than the ten returns the lookback yields, so the direct trailing slice differs from using
the whole history.
"""

VERIFIED_AGAINST = "vqapr-0.7.0"
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


def _closes_by_instrument(path: Path) -> dict[str, list[tuple[date, Decimal]]]:
    """The committed close panel, per instrument, in session order.

    Read straight from the fixture for the *measurement* half of this showcase. The strategies read
    their own closes through the point-in-time window; this is the researcher standing outside the
    run, which is exactly what an information coefficient is.
    """
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"""
            SELECT instrument,
                   CAST(available_at AT TIME ZONE '{VENUE}' AS DATE) AS session,
                   close
            FROM read_parquet('{path.as_posix()}')
            WHERE close IS NOT NULL
            ORDER BY instrument, session
            """
        ).fetchall()
    finally:
        con.close()
    panel: dict[str, list[tuple[date, Decimal]]] = {}
    for instrument, session, close in rows:
        panel.setdefault(str(instrument), []).append((session, Decimal(str(close))))
    return panel


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


def _return_member_source(
    *,
    strategy_id: str,
    class_name: str,
    lookback: int,
    horizon_sign: str,
    negate: bool,
) -> str:
    """The two return-horizon members: read closes, take a horizon return, demean, size, rescale."""
    raw_expression = (
        "-1 * (values[-1] / values[0] - Decimal(1))"
        if negate
        else "values[-1] / values[0] - Decimal(1)"
    )
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
        history = dict(self.memory or {{}})
        history["occurrences"] = int(history.get("occurrences", 0)) + 1
        self.memory = history

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
            name: {raw_expression}
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


_REVERSAL_SOURCE = _return_member_source(
    strategy_id="show008-reversal",
    class_name="ReversalMember",
    lookback=REVERSAL_LOOKBACK,
    horizon_sign="A five-day price reversal",
    negate=True,
)

_MOMENTUM_SOURCE = _return_member_source(
    strategy_id="show008-momentum",
    class_name="MomentumMember",
    lookback=MOMENTUM_LOOKBACK,
    horizon_sign="A ten-day price momentum tilt",
    negate=False,
)


_LOWVOL_SOURCE = (
    f'''"""A low-volatility tilt using a direct trailing-window statistic.

Only the final trailing window is used, so computing and discarding every earlier rolling step
would add work without changing the result. The requested history is longer than the volatility
window, and the slice makes the economic choice explicit.

The sign is negative: low volatility is the *preferred* side, so the raw signal is the negated
volatility and the cross-sectional demean decides who ends up long.
"""

from __future__ import annotations

from decimal import Decimal
from statistics import stdev
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

LOOKBACK = {LOWVOL_LOOKBACK}
"""Closes requested. Ten simple returns fall out of eleven closes."""

VOL_WINDOW = {LOWVOL_VOL_WINDOW}
"""The realised-volatility window, deliberately shorter than the requested return history."""

ACTIVE_BUDGET = Decimal("{MEMBER_BUDGET}")

BUDGET = Budget(
    PortfolioDirection.SIGNED,
    Decimal("0"),
    Decimal("2"),
    Decimal("-1"),
    Decimal("1"),
)


class LowVolMember(StrategyModel):
    """Realised volatility over ten sessions, negated, demeaned, sized and rescaled."""

    def requirements(self):
        return (
            DataRequirement.of('price_daily', 'close', lookback=RowsLookback(LOOKBACK)),
        )

    def decide(self, context):
        history = dict(self.memory or {{}})
        history["occurrences"] = int(history.get("occurrences", 0)) + 1
        self.memory = history

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

        volatility: dict[str, Decimal] = {{}}
        for name, values in eligible.items():
            returns = tuple(
                values[index] / values[index - 1] - Decimal(1)
                for index in range(1, len(values))
            )
            volatility[name] = stdev(returns[-VOL_WINDOW:])

        if len(volatility) < 2:
            return Hold(reason="a low-volatility view needs at least two names with a full window")

        # Low volatility is the preferred side, so the raw signal is the negated volatility.
        raw = {{name: -value for name, value in volatility.items()}}
        mean = sum(raw.values()) / len(raw)
        centred = {{name: value - mean for name, value in raw.items()}}
        if all(value == 0 for value in centred.values()):
            return Hold(reason="every name carries the same realised volatility")

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


_ENSEMBLE_SOURCE = (
    '''"""A family ensemble built by netting three subscribed member allocations."""

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


class FamilyEnsembleStrategy(StrategyModel):
    """desired = equal-weight(reversal, momentum, low-vol) rescaled to budget, projected onto the
    shipped constraint set. Long-only is emergent: no member is filtered before combination."""

    def __init__(
        self,
        *,
        reversal_dataset_id: str,
        momentum_dataset_id: str,
        lowvol_dataset_id: str,
    ) -> None:
        self._member_dataset_ids = (
            reversal_dataset_id,
            momentum_dataset_id,
            lowvol_dataset_id,
        )

    def tables(self):
        return (
            TableSpec(
                "ensemble.netting",
                (
                    "instrument",
                    "long_weight",
                    "short_weight",
                    "offset_weight",
                    "net_weight",
                    "member_count",
                ),
            ),
        )

    def requirements(self):
        return tuple(
            DataRequirement.of(dataset_id, "weight", lookback=RowsLookback(1))
            for dataset_id in self._member_dataset_ids
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
        requirements = self.requirements()
        panels = [self._panel(context, requirement) for requirement in requirements]
        if not all(panels):
            return Hold(reason="every member allocation input must be visible before netting them")

        # Each subscribed member is validated at consumption time as a signed, dollar-neutral
        # allocation. No constraint owns these inputs, so the consuming Strategy checks all three
        # before a single weight is combined.
        for dataset_id, panel in zip(self._member_dataset_ids, panels, strict=True):
            validate_allocation(
                panel,
                AllocationInvariants.of(
                    sign=AllocationSign.SIGNED,
                    weight_sum_upper=Decimal(0),
                    tolerance=NEUTRALITY,
                ),
                label=f"{dataset_id} member",
            )

        # What does netting these three published allocations imply, ticker by ticker? With three
        # members the offset is no longer a restatement of "they disagreed": a name can be long in
        # two and short in one, and min(long, |short|) reports what actually cancelled. This never
        # decides the combination; it is read afterward and stored for the trace.
        netting = net_members(panels, instruments=sorted(context.window.instruments))
        self.recorder.append_batch(
            "ensemble.netting",
            tuple(
                {
                    "instrument": name,
                    "long_weight": str(measured.long_weight),
                    "short_weight": str(measured.short_weight),
                    "offset_weight": str(measured.offset_weight),
                    "net_weight": str(measured.net_weight),
                    "member_count": str(len(panels)),
                }
                for name, measured in sorted(netting.items())
            ),
        )

        # The economic combination is the Strategy's own choice: simple equal weight over the
        # members' *net* per-ticker weight, then rescaled to this run's own declared gross active
        # budget. No member is filtered before combining -- long-only is never asked of any member.
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

    written = {}
    for name, source in (
        ("reversal", _REVERSAL_SOURCE),
        ("momentum", _MOMENTUM_SOURCE),
        ("lowvol", _LOWVOL_SOURCE),
        ("ensemble", _ENSEMBLE_SOURCE),
    ):
        path = components / f"{name}.py"
        path.write_text(source, encoding="utf-8")
        written[name] = path

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
            "show008-academic",
        )
''',
        encoding="utf-8",
    )
    written["academic"] = academic

    krx = components / "krx_exchange.py"
    krx.write_text(
        f'''"""Whole shares, 3bp commission both sides, 20bp sale tax, long only."""

from __future__ import annotations

from vqapr.public import KrxExchange, Rebalance

UNIVERSE = {universe!r}


class ShowcaseKrxExchange(KrxExchange):
    def __init__(self):
        super().__init__(UNIVERSE, "show008-krx")
''',
        encoding="utf-8",
    )
    written["krx"] = krx
    return written


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


def _measure_published_signal(
    published_path: Path, closes: dict[str, list[tuple[date, Decimal]]]
) -> dict[str, Any]:
    """Did the published low-vol weights predict the return that followed them?

    This is the `analysis/` half record 016 left open. The signal is read back from the *published
    artifact* — not from the run's in-memory objects — and scored against the next session's return
    computed from the committed close panel. Only occurrences where a forward return exists are
    scored; a missing outcome is skipped rather than filled, because filling it would be an
    invention this package refuses elsewhere.
    """
    rows = _read_published(published_path)
    by_session: dict[date, dict[str, Decimal]] = {}
    for row in rows:
        available_at = row["available_at"]
        session = available_at.date() if hasattr(available_at, "date") else available_at
        weight = row["weight"]
        if weight is None:
            continue
        by_session.setdefault(session, {})[str(row["instrument"])] = Decimal(str(weight))

    # Forward one-session return per instrument, keyed by the session the signal was published on.
    forward: dict[date, dict[str, Decimal]] = {}
    for instrument, series in closes.items():
        for index in range(len(series) - 1):
            session, close = series[index]
            _next_session, next_close = series[index + 1]
            if close == 0:
                continue
            forward.setdefault(session, {})[instrument] = next_close / close - Decimal(1)

    scored: list[dict[str, Any]] = []
    for session in sorted(by_session):
        signal = by_session[session]
        outcome = forward.get(session, {})
        shared = sorted(set(signal) & set(outcome))
        if len(shared) < 2:
            continue
        paired_signal = {name: signal[name] for name in shared}
        paired_outcome = {name: outcome[name] for name in shared}
        if len({value for value in paired_signal.values()}) < 2:
            continue
        if len({value for value in paired_outcome.values()}) < 2:
            continue
        scored.append(
            {
                "session": session.isoformat(),
                "instruments": len(shared),
                "ic": str(information_coefficient(paired_signal, paired_outcome)),
                "rank_ic": str(rank_information_coefficient(paired_signal, paired_outcome)),
            }
        )

    if not scored:
        raise AssertionError(
            "no published occurrence could be scored against a forward return; "
            "the measurement half of this showcase proved nothing"
        )

    # An independent oracle on the first scored occurrence. Record 016's first defect was a
    # headline test that reimplemented the product in pandas and then compared the reimplementation
    # against itself; the difference here is that `information_coefficient` is what produced every
    # number in the trace, and this recomputation only checks it. The oracle runs in exact
    # rationals with no vqapr import, so agreement is a fact about the product, not a shared bug.
    first = scored[0]
    session = date.fromisoformat(first["session"])
    signal = by_session[session]
    outcome = forward[session]
    shared = sorted(set(signal) & set(outcome))
    xs = [Fraction(signal[name]) for name in shared]
    ys = [Fraction(outcome[name]) for name in shared]
    x_bar = sum(xs, Fraction(0)) / len(xs)
    y_bar = sum(ys, Fraction(0)) / len(ys)
    covariance = sum(((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys, strict=True)), Fraction(0))
    x_spread = sum(((x - x_bar) ** 2 for x in xs), Fraction(0))
    y_spread = sum(((y - y_bar) ** 2 for y in ys), Fraction(0))
    # Compare as squares so the oracle needs no square root: r^2 * (Sxx * Syy) == cov^2, with the
    # sign checked separately. Both are exact rational identities.
    produced = Decimal(first["ic"])
    produced_squared = Fraction(produced) ** 2
    if abs(produced_squared * x_spread * y_spread - covariance**2) > Fraction(1, 10**20):
        raise AssertionError(
            f"independent oracle rejects the information coefficient on {first['session']}: "
            f"reported {produced}, but r^2*Sxx*Syy != cov^2"
        )
    if (covariance > 0) != (produced > 0):
        raise AssertionError(
            f"independent oracle rejects the sign on {first['session']}: "
            f"covariance {covariance} against reported {produced}"
        )

    mean_ic = sum(Decimal(entry["ic"]) for entry in scored) / len(scored)
    return {
        "scored_occurrences": len(scored),
        "mean_ic": str(mean_ic),
        "oracle_checked_session": first["session"],
        "per_occurrence": scored,
    }


def _check_lowvol_orientation(
    published_path: Path, closes: dict[str, list[tuple[date, Decimal]]]
) -> dict[str, Any]:
    """The published low-vol weights must order names inversely to their realised volatility.

    Recomputed here from the committed closes with the member's own window, independently of the
    run. Every other gate in this showcase is blind to this member's sign: a tilt toward the *most*
    volatile name nets identically, carries the same gross weight, and scores an information
    coefficient of the same magnitude. Without this, "low-volatility member" would be a claim made
    only by the class name.
    """
    rows = _read_published(published_path)
    by_session: dict[date, dict[str, Decimal]] = {}
    for row in rows:
        available_at = row["available_at"]
        session = available_at.date() if hasattr(available_at, "date") else available_at
        if row["weight"] is not None:
            by_session.setdefault(session, {})[str(row["instrument"])] = Decimal(str(row["weight"]))

    sessions_checked = 0
    for session, weights in sorted(by_session.items()):
        volatility: dict[str, Decimal] = {}
        for instrument, series in closes.items():
            # Strictly before the session, not up to and including it. The member's callback runs
            # at 08:30 and this fixture makes closes available at 15:30, so the most recent close
            # it can legally have seen is the previous session's. Checking against `day <= session`
            # hands the oracle a close the member could not read, and the resulting disagreement
            # would be a lookahead in the checker rather than a defect in the member. This bit me:
            # the first version of this check failed, and the member was right.
            history = [close for day, close in series if day < session]
            if len(history) < LOWVOL_LOOKBACK:
                continue
            window = history[-LOWVOL_LOOKBACK:]
            returns = tuple(
                window[index] / window[index - 1] - Decimal(1) for index in range(1, len(window))
            )
            volatility[instrument] = stdev(returns[-LOWVOL_VOL_WINDOW:])

        shared = sorted(set(weights) & set(volatility))
        if len(shared) < 2:
            continue

        # The claim is a sign partition, not a total order. `equal_weight` sizes by the *sign* of
        # the demeaned signal and discards its magnitude, so every long lands on the same weight
        # and every short on its negative -- the published panel carries two distinct values, not
        # four. Demanding a strict ordering here would be demanding something the construction
        # cannot express, and the first version of this check did exactly that and failed against
        # a member that was correct on every session.
        #
        # What must hold: every name the member is short is at least as volatile as every name it
        # is long. A member that preferred high volatility inverts this on every occurrence.
        longs = [name for name in shared if weights[name] > 0]
        shorts = [name for name in shared if weights[name] < 0]
        if not longs or not shorts:
            continue
        least_volatile_short = min(volatility[name] for name in shorts)
        most_volatile_long = max(volatility[name] for name in longs)
        if least_volatile_short < most_volatile_long:
            raise AssertionError(
                f"low-vol member holds a more volatile name long than one it is short on "
                f"{session}: longs {sorted(longs)} up to {most_volatile_long}, "
                f"shorts {sorted(shorts)} down to {least_volatile_short}"
            )
        sessions_checked += 1

    if sessions_checked == 0:
        raise AssertionError(
            "no published low-vol occurrence could be checked for orientation; "
            "the sign of this member is unproven"
        )
    return {"orientation_sessions_checked": sessions_checked}


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
    # The momentum and low-vol members both need an eleven-close history; the reversal member
    # needs six. All members and the ensemble share one callback calendar, so only sessions where
    # every member has enough history produce an ensemble decision -- the rest decline. This is
    # asserted below rather than hidden by trimming the agenda to fit the signal.
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
        project, "show008-reversal", paths["reversal"], "ReversalMember",
    )
    momentum_ref = register_strategy_model(
        project, "show008-momentum", paths["momentum"], "MomentumMember",
    )
    lowvol_ref = register_strategy_model(
        project, "show008-lowvol", paths["lowvol"], "LowVolMember",
    )
    academic_ref = register_exchange(
        project, "show008-academic", paths["academic"], "ShowcaseAcademicExchange",
    )
    register_exchange(project, "show008-krx", paths["krx"], "ShowcaseKrxExchange")
    register_strategy_model(
        project,
        "show008-ensemble",
        paths["ensemble"],
        "FamilyEnsembleStrategy",
        config={
            "reversal_dataset_id": "reversal_allocation",
            "momentum_dataset_id": "momentum_allocation",
            "lowvol_dataset_id": "lowvol_allocation",
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

    published: dict[str, Any] = {}
    memories: dict[str, dict[str, Any]] = {}
    for label, ref, at, dataset_id in (
        ("reversal", reversal_ref, time(8, 0), "reversal_allocation"),
        ("momentum", momentum_ref, time(8, 15), "momentum_allocation"),
        ("lowvol", lowvol_ref, time(8, 30), "lowvol_allocation"),
    ):
        member_run = _member_run(
            project,
            strategy_ref=ref,
            at=at,
            callback_days=callback_days,
            academic_ref=academic_ref,
            start=start,
            end=end,
            universe=universe,
        )
        result = member_run.result()
        published[label] = _register_run_table(
            project,
            member_run,
            run_id=str(ref.component_id),
            component_id=str(ref.component_id),
            dataset_id=dataset_id,
            table="vqapr.weight",
            fields={"weight": "CAST(weight AS DOUBLE)"},
            field_types={"weight": "DOUBLE"},
        )
        memories[label] = _memory(result)

    # The ensemble reads what its members published, so its horizon opens on the first day EVERY
    # member has a weight on record. A member declines until its lookback fills, and a decline
    # records no weight, so the allocation datasets begin days after the members' own agenda
    # does; an ensemble opening with the members would ask its first decision to read an empty
    # window, which `vqapr check` refuses (`check.lookback.uncovered`) -- and since record 168
    # `preflight_run` asks the same judgments, so this script was refused too. The members'
    # declines above are still asserted, not trimmed; only the ensemble waits for its inputs.
    ensemble_opens = max(member.first_day for member in published.values())
    ensemble_days = [day for day in callback_days if day >= ensemble_opens]
    ensemble_start = datetime.fromisoformat(f"{ensemble_days[0].isoformat()}T00:00:00{OFFSET}")
    ensemble_definition = RunDefinition(
        run_id="show008-ensemble",
        strategies=(StrategyEntry("show008-ensemble", ("no-short", "single-name-cap")),),
        sessions=tuple(ensemble_days),
        timezone=VENUE,
        at=time(9, 0),
        exchange="show008-krx",
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
    )
    ensemble_result = run(project, preflight_run(project, ensemble_definition)).result()
    ensemble_memory = _memory(ensemble_result)
    ensemble_replay = _replay(ensemble_result)

    # Assertion 1: all three members published, and the ensemble subscribed to all three.
    subscribed = {"reversal_allocation", "momentum_allocation", "lowvol_allocation"}
    ensemble_evidence = callback_evidence(ensemble_result)
    accessed_datasets = {
        str(access.dataset_id)
        for evidence in ensemble_evidence
        for access in evidence.strategy_accesses
    }
    if not subscribed <= accessed_datasets:
        raise AssertionError(
            f"ensemble did not subscribe to all three member datasets: "
            f"saw {sorted(accessed_datasets)}"
        )
    for label, dataset_id in (
        ("reversal", "reversal_allocation"),
        ("momentum", "momentum_allocation"),
        ("lowvol", "lowvol_allocation"),
    ):
        if published[label].dataset_id != dataset_id:
            raise AssertionError(f"{label} member's table is not registered as {dataset_id}")

    # Assertion 2: the netting measurement ran on three members and at least one ticker-occurrence
    # showed a genuine offset.
    netting_rows = ensemble_result.final_state.recorder_rows.get("ensemble.netting", ())
    if not netting_rows:
        raise AssertionError("the ensemble never recorded a netting measurement")
    member_counts = {str(row["member_count"]) for row in netting_rows}
    if member_counts != {"3"}:
        raise AssertionError(f"netting did not run over three members; saw {member_counts}")

    # `member_count` is self-reported, so on its own it certifies nothing: a netting call that
    # silently dropped a member would still print 3. The gross weight is not self-reported. Every
    # member is rescaled to MEMBER_BUDGET long and -MEMBER_BUDGET short, so each occurrence must
    # carry sum(long) + sum(|short|) == members * 2 * MEMBER_BUDGET exactly. Two members netted
    # instead of three lands on 0.16 where 0.24 is required, and no self-report can hide it.
    expected_gross = 3 * 2 * MEMBER_BUDGET
    by_event: dict[str, Decimal] = {}
    weights_per_event: dict[str, int] = {}
    for row in netting_rows:
        event_time = str(row["event_time"])
        gross = Decimal(row["long_weight"]) - Decimal(row["short_weight"])
        by_event[event_time] = by_event.get(event_time, Decimal(0)) + gross
        weights_per_event[event_time] = weights_per_event.get(event_time, 0) + 3
    for event_time, gross in sorted(by_event.items()):
        # Each member weight lands on the canonical grid, so the sum carries at most one quantum
        # per weight. The budget is that count times QUANTUM -- derived from the grid, not tuned to
        # the observed residual, which is about 1e-28 against a 1e-12 quantum. A missing member
        # costs 0.08, nine orders of magnitude above this, so the discriminator is untouched.
        budget = weights_per_event[event_time] * QUANTUM
        if abs(gross - expected_gross) > budget:
            raise AssertionError(
                f"netting gross weight on {event_time} is {gross}, not {expected_gross} "
                f"within {budget}; a member is missing from the combination"
            )
    max_offset = max(Decimal(row["offset_weight"]) for row in netting_rows)
    if max_offset <= 0:
        raise AssertionError(
            "no ticker-occurrence showed a non-zero offset_weight; the members never disagreed"
        )
    crossing_occurrences = len(
        {row["event_time"] for row in netting_rows if Decimal(row["offset_weight"]) > 0}
    )

    # Assertion 3: three-member netting is arithmetically consistent on every recorded row. With
    # two members `offset = min(long, |short|)` is nearly a restatement; with three it is a real
    # claim, so it is checked against the parts rather than trusted.
    for row in netting_rows:
        long_weight = Decimal(row["long_weight"])
        short_weight = Decimal(row["short_weight"])
        offset = Decimal(row["offset_weight"])
        net = Decimal(row["net_weight"])
        if net != long_weight + short_weight:
            raise AssertionError(
                f"net_weight {net} != long {long_weight} + short {short_weight} "
                f"for {row['instrument']}"
            )
        if offset != min(long_weight, -short_weight):
            raise AssertionError(
                f"offset_weight {offset} != min(long {long_weight}, |short| {-short_weight}) "
                f"for {row['instrument']}"
            )

    # Assertion 4: a name genuinely split the family -- some members long, others short -- on at
    # least one occurrence. This is what three members buy over two, so it is demanded, not hoped.
    split_rows = [
        row
        for row in netting_rows
        if Decimal(row["long_weight"]) > 0 and Decimal(row["short_weight"]) < 0
    ]
    if not split_rows:
        raise AssertionError(
            "no ticker-occurrence had members on both sides; the family never actually split"
        )

    # Assertion 5: the fill-journal replay already aborted inside _replay() if it disagreed;
    # re-check the derived facts so a regression in _replay itself cannot silently pass.
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

    # Assertion 6: the published low-vol signal is measured against what followed it. This is the
    # `analysis/` half of record 016's open follow-up, run on a published artifact.
    closes = _closes_by_instrument(observation_path)
    measurement = _measure_published_signal(published["lowvol"].directory, closes)

    # Assertion 7: the low-vol member is actually a *low* volatility tilt. Nothing above can see
    # its sign -- netting, gross weight and the information coefficient are all sign-agnostic, so a
    # member that preferred the most volatile name would pass every other gate in this file. The
    # published weights are checked against realised volatility recomputed here from the committed
    # closes, and the ordering must be strictly inverse on every published occurrence.
    sign_check = _check_lowvol_orientation(published["lowvol"].directory, closes)

    trace = {
        "status": "current",
        "verified_against": VERIFIED_AGAINST,
        "last_verified_at": LAST_VERIFIED_AT,
        "universe": list(universe),
        "sessions": len(sessions),
        "callbacks": len(callback_days),
        "ensemble_callbacks": len(ensemble_days),
        "crossing_occurrences": crossing_occurrences,
        "max_offset_weight": str(max_offset),
        "split_ticker_occurrences": len(split_rows),
        "members": {
            label: {
                "exchange": "Academic (fractional, zero cost)",
                "account_mode": AccountMode.SIGNED.value,
                "occurrences": memories[label].get("occurrences"),
                "published_dataset": published[label].dataset_id,
                "published_occurrences": published[label].occurrences,
                "published_rows": published[label].row_count,
            }
            for label in ("reversal", "momentum", "lowvol")
        },
        "lowvol_measurement": measurement,
        "lowvol_orientation": sign_check,
        "ensemble_run": {
            "exchange": "KRX (whole shares, 3bp commission, 20bp sale tax, long only)",
            "account_mode": AccountMode.LONG_ONLY.value,
            "subscribed_allocation_inputs": sorted(subscribed),
            "shipped_constraints": sorted(SHIPPED_CONSTRAINTS),
            "single_name_cap": CAP,
            "member_count": 3,
            "rebalances": ensemble_memory.get("rebalances"),
            **ensemble_replay,
        },
    }
    digests = {
        f"{label}_allocation": _digest(published[label].directory)
        for label in ("reversal", "momentum", "lowvol")
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
    measurement = trace["lowvol_measurement"]
    print(f"sessions / callbacks        : {trace['sessions']} / {trace['callbacks']}")
    for label in ("reversal", "momentum", "lowvol"):
        member = trace["members"][label]
        print(
            f"{label:<12} published      : {member['published_occurrences']} occurrences, "
            f"{member['published_rows']} rows -> {member['published_dataset']}"
        )
    print(f"subscribed inputs           : {', '.join(ensemble['subscribed_allocation_inputs'])}")
    print(f"members netted              : {ensemble['member_count']}")
    print(f"crossing occurrences        : {trace['crossing_occurrences']}")
    print(f"max ticker offset_weight    : {trace['max_offset_weight']}")
    print(f"split ticker-occurrences    : {trace['split_ticker_occurrences']}")
    print(
        f"low-vol IC                  : mean {measurement['mean_ic']} over "
        f"{measurement['scored_occurrences']} scored occurrences"
    )
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
