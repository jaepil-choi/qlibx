"""An alpha run, its published allocation, and an enhanced index built on top — through the spine.

    alpha run (Academic)  ->  publish_run_allocation  ->  alpha_allocation dataset
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

import hashlib
import json
import shutil
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from vqapr.public import (
    SHIPPED_CONSTRAINTS,
    AccountMode,
    AccountSnapshot,
    AllocationPublicationSpec,
    ComponentKind,
    ConstraintSet,
    DataRequirement,
    DatasetRegistration,
    ExecutionInputRegistration,
    ExecutionTableSpec,
    FillConvention,
    FillSelector,
    LocalInstantDeclaration,
    MonitoringPolicy,
    OperationAgenda,
    OperationOccurrence,
    OperationRole,
    RowsLookback,
    RunDefinition,
    SourceSpec,
    StrategyConfig,
    ValuationConfig,
    callback_evidence,
    component_ref,
    preflight_run,
    publish_run_allocation,
    register_agenda,
    register_component,
    register_dataset,
    register_execution_input,
    register_monitoring_policy,
    register_strategy_config,
    register_valuation_config,
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

VERIFIED_AGAINST = "vqapr-0.1.0+show-005-working-tree"
LAST_VERIFIED_AT = "2026-08-18"


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


def _agenda(agenda_id: str, role: OperationRole, at: time, days: list[date]) -> OperationAgenda:
    return OperationAgenda.from_occurrences(
        agenda_id=agenda_id,
        role=role,
        timezone=VENUE,
        occurrences=tuple(
            OperationOccurrence(
                f"{agenda_id}-{day.isoformat()}",
                role,
                LocalInstantDeclaration(day, at, VENUE, 0, OFFSET),
            )
            for day in days
        ),
        provenance="show_005 committed KRX sessions",
    )


_SOURCE_REFS = '''

def _source_refs(context):
    """Exactly the sources this callback read, in first-read order.

    The Flow independently recomputes this from the window and refuses any intent whose provenance
    disagrees, so it must be derived from the accesses rather than declared.
    """
    from vqapr.public import IntentSourceRef

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
    QUANTUM,
    Budget,
    DataRequirement,
    EconomicPortfolioIntent,
    NoDecision,
    PortfolioDirection,
    PortfolioTarget,
    RowsLookback,
    StrategyModel,
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

    def requirements(self):
        return (
            DataRequirement.of(
                "show005-alpha", "price_daily", fields=("close",), lookback=RowsLookback(1)
            ),
        )

    def on_occurrence(self, context):
        rows = context.window.observations(self.requirements()[0]).rows
        closes = {
            str(row["instrument"]): row["close"] for row in rows if row["close"] is not None
        }
        if len(closes) < 2:
            return NoDecision("a cross-sectional view needs at least two names")

        mean = sum(closes.values()) / len(closes)
        raw = {name: (mean - close) / mean for name, close in closes.items()}
        centre = sum(raw.values()) / len(raw)
        centred = {name: value - centre for name, value in raw.items()}
        gross = sum(abs(value) for value in centred.values())
        if gross == 0:
            return NoDecision("the cross-section is flat")

        scale = ACTIVE_BUDGET / gross
        weights = {
            name: (value * scale).quantize(QUANTUM) for name, value in centred.items()
        }
        history = dict(self.memory or {})
        history["views"] = int(history.get("views", 0)) + 1
        self.memory = history

        return EconomicPortfolioIntent(
            uuid5(NAMESPACE_URL, "show005/alpha/" + context.occurrence.occurrence_id),
            "show005-alpha",
            tuple(PortfolioTarget(name, weight=w) for name, w in sorted(weights.items())),
            Decimal(1) - sum(weights.values()),
            BUDGET,
            _source_refs(context),
            context.account.version,
            None,
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
    QUANTUM,
    AllocationInvariants,
    AllocationSign,
    Budget,
    DataRequirement,
    EconomicPortfolioIntent,
    NoDecision,
    OptimizeRefusal,
    PortfolioDirection,
    PortfolioTarget,
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
            DataRequirement.of(
                "show005-index",
                self._benchmark_dataset_id,
                fields=("benchmark_weight",),
                lookback=RowsLookback(1),
            ),
            DataRequirement.of(
                "show005-index",
                self._alpha_dataset_id,
                fields=("weight",),
                lookback=RowsLookback(1),
            ),
            DataRequirement.of(
                "show005-index", "price_daily", fields=("close",), lookback=RowsLookback(1)
            ),
        )

    def _panel(self, context, requirement, field):
        return {
            str(row["instrument"]): row[field]
            for row in context.window.observations(requirement).rows
            if row[field] is not None
        }

    def on_occurrence(self, context):
        index_requirement, alpha_requirement, price_requirement = self.requirements()
        benchmark = self._panel(context, index_requirement, "benchmark_weight")
        active = self._panel(context, alpha_requirement, "weight")
        prices = self._panel(context, price_requirement, "close")
        if not benchmark or not active:
            return NoDecision("both allocation inputs must be visible before combining them")

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
        instruments = tuple(sorted(bounds.lower))
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

        # One held name is pinned to prove frozen invariance, and it is the holding with the least
        # slack against its own upper bound, because that is the one that tests the conjunction
        # hardest. A freeze is only honourable while the position still satisfies its box; once
        # overnight drift pushes it past the cap the two demands are unsatisfiable together, and
        # `optimize`'s own refusal is what releases it rather than a duplicate guard here.
        frozen = frozenset()
        if current:
            pinned = min(current, key=lambda name: (bounds.upper[name] - current[name], name))
            frozen = frozenset({pinned})
        released = False
        try:
            result = self._solve(desired, current, bounds, frozen)
        except OptimizeRefusal as error:
            if not frozen or "outside its declared bound" not in str(error):
                raise
            released = True
            frozen = frozenset()
            result = self._solve(desired, current, bounds, frozen)

        for name in frozen:
            if result.weights[name] != current[name]:
                raise AssertionError("a frozen name must be returned verbatim")

        history = dict(self.memory or {})
        history["rebalances"] = int(history.get("rebalances", 0)) + 1
        history["frozen_occurrences"] = int(history.get("frozen_occurrences", 0)) + len(frozen)
        history["freezes_released"] = int(history.get("freezes_released", 0)) + int(released)
        # Monitoring only, recorded after the decision and never fed back into it.
        history["active_norm"] = str(self._active_norm(result.weights, benchmark))
        self.memory = history

        return EconomicPortfolioIntent(
            uuid5(NAMESPACE_URL, "show005/index/" + context.occurrence.occurrence_id),
            "show005-index",
            tuple(PortfolioTarget(n, weight=w) for n, w in sorted(result.weights.items())),
            result.cash,
            BUDGET,
            _source_refs(context),
            account.version,
            None,
        )

    def _solve(self, desired, current, bounds, frozen):
        return optimize(
            desired=desired,
            current=current,
            lower=dict(bounds.lower),
            upper=dict(bounds.upper),
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


def _write_components(project: Path, universe: tuple[str, ...]) -> dict[str, Path]:
    components = project / "components"
    components.mkdir(parents=True, exist_ok=True)

    alpha = components / "alpha.py"
    alpha.write_text(_ALPHA_SOURCE, encoding="utf-8")

    enhanced = components / "enhanced.py"
    enhanced.write_text(_ENHANCED_SOURCE, encoding="utf-8")

    academic = components / "academic_exchange.py"
    academic.write_text(
        f'''"""Fractional quantity, zero cost, full fill — the venue the alpha book runs on."""

from __future__ import annotations

from decimal import Decimal

from vqapr.public import AcademicExchange, ListingRule, Side

UNIVERSE = {universe!r}


class ShowcaseAcademicExchange(AcademicExchange):
    def __init__(self):
        super().__init__(
            {{
                instrument: ListingRule(
                    instrument,
                    Decimal("0.0001"),
                    Decimal("0.0001"),
                    True,
                    frozenset({{Side.BUY, Side.SELL}}),
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
        f'''"""Whole shares, 3bp commission both sides, 20bp sale tax, long only."""

from __future__ import annotations

from vqapr.public import KrxExchange

UNIVERSE = {universe!r}


class ShowcaseKrxExchange(KrxExchange):
    def __init__(self):
        super().__init__(UNIVERSE, "show005-krx")
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
    for entry in account.fill_history:
        fill = entry.fill
        if fill.dealt_quantity == 0:
            continue
        dealt += 1
        cash += fill.cash_delta
        commission += fill.cost.commission
        tax += fill.cost.tax
        held = positions.get(fill.instrument_id, Decimal(0)) + fill.dealt_quantity
        if held == 0:
            positions.pop(fill.instrument_id, None)
        else:
            positions[fill.instrument_id] = held

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


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _pipeline(project: Path) -> tuple[dict[str, Any], dict[str, str]]:
    manifest = json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))
    tolerance = str(manifest["weight_tolerance"])
    observation_path = FIXTURE / str(manifest["observation_path"])
    execution_path = FIXTURE / str(manifest["execution_path"])
    benchmark_path = FIXTURE / str(manifest["benchmark_path"])
    universe = _universe(benchmark_path)
    sessions = _sessions(benchmark_path)
    callback_days = sessions[1:]

    register_dataset(
        project,
        DatasetRegistration.of(
            "price_daily",
            "krx-observation",
            instrument_field="instrument",
            available_at="available_at",
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

    paths = _write_components(project, universe)
    alpha_ref = component_ref(
        "show005-alpha", ComponentKind.STRATEGY_MODEL, paths["alpha"], "SignedAlpha"
    )
    academic_ref = component_ref(
        "show005-academic", ComponentKind.EXCHANGE, paths["academic"], "ShowcaseAcademicExchange"
    )
    krx_ref = component_ref(
        "show005-krx", ComponentKind.EXCHANGE, paths["krx"], "ShowcaseKrxExchange"
    )
    index_ref = component_ref(
        "show005-index",
        ComponentKind.STRATEGY_MODEL,
        paths["enhanced"],
        "EnhancedIndex",
        config={
            "benchmark_dataset_id": "benchmark_weight_daily",
            "alpha_dataset_id": "alpha_allocation",
        },
    )
    # The shipped constraints enter through the same door as any user component: a resolved path,
    # a fingerprint and a config. Nothing about them bypasses registration.
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
    for reference in (alpha_ref, index_ref, academic_ref, krx_ref, no_short_ref, cap_ref):
        register_component(project, reference)

    alpha_agenda = _agenda(
        "show005-alpha", OperationRole.STRATEGY_CALLBACK, time(8, 30), callback_days
    )
    index_agenda = _agenda(
        "show005-index", OperationRole.STRATEGY_CALLBACK, time(9, 0), callback_days
    )
    valuation_agenda = _agenda(
        "show005-valuation", OperationRole.VALUATION, time(16, 0), callback_days
    )
    monitoring_agenda = _agenda(
        "show005-monitoring", OperationRole.MONITORING, time(16, 30), callback_days
    )
    for agenda in (alpha_agenda, index_agenda, valuation_agenda, monitoring_agenda):
        register_agenda(project, agenda)

    alpha_config = StrategyConfig(alpha_ref, "show005-alpha", OperationRole.STRATEGY_CALLBACK)
    index_config = StrategyConfig(index_ref, "show005-index", OperationRole.STRATEGY_CALLBACK)
    valuation_config = ValuationConfig(
        "show005-valuation",
        OperationRole.VALUATION,
        DataRequirement.of(
            "show005-valuation", "price_daily", fields=("close",), lookback=RowsLookback(1)
        ),
    )
    monitoring = MonitoringPolicy("show005-monitoring", OperationRole.MONITORING)
    register_strategy_config(project, alpha_config)
    register_strategy_config(project, index_config)
    register_valuation_config(project, valuation_config)
    register_monitoring_policy(project, monitoring)

    start = datetime.fromisoformat(f"{callback_days[0].isoformat()}T00:00:00{OFFSET}")
    end = datetime.fromisoformat(f"{callback_days[-1].isoformat()}T23:00:00{OFFSET}")

    alpha_definition = RunDefinition(
        alpha_config,
        valuation_config,
        ConstraintSet(()),
        monitoring,
        academic_ref,
        "krx-daily",
        start,
        end,
        AccountSnapshot(0, INITIAL_CASH, {}),
        AccountMode.SIGNED,
        instruments=universe,
    )
    alpha_result = run(project, preflight_run(project, alpha_definition))
    alpha_evidence = callback_evidence(alpha_result)

    published = publish_run_allocation(
        project, AllocationPublicationSpec.of("alpha_allocation"), alpha_evidence
    )

    index_definition = RunDefinition(
        index_config,
        valuation_config,
        ConstraintSet((no_short_ref, cap_ref)),
        monitoring,
        krx_ref,
        "krx-daily",
        start,
        end,
        AccountSnapshot(0, INITIAL_CASH, {}),
        AccountMode.LONG_ONLY,
        instruments=universe,
    )
    index_result = run(project, preflight_run(project, index_definition))

    alpha_memory = _memory(alpha_result)
    index_memory = _memory(index_result)
    index_replay = _replay(index_result)
    index_monitoring = _monitoring(index_result)

    if not index_replay["whole_shares_only"]:
        raise AssertionError("the KRX profile must hold whole shares only")
    # Both frozen outcomes are claimed in the README, so both are checked here rather than merely
    # reported: a holding pinned and returned verbatim, and a pinned holding whose own box refused
    # it and released the freeze.
    if int(index_memory.get("frozen_occurrences", 0)) == 0:
        raise AssertionError("no freeze survived, so frozen invariance was never demonstrated")
    if int(index_memory.get("freezes_released", 0)) == 0:
        raise AssertionError("no freeze was refused, so the out-of-box release was never exercised")
    if not any(position for position in index_replay["replayed_positions"].values()):
        raise AssertionError("the enhanced index never took a position")

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
            "benchmark": str(manifest["benchmark_path"]),
            "weight_tolerance": tolerance,
        },
        "alpha_run": {
            "exchange": "Academic (fractional, zero cost)",
            "account_mode": AccountMode.SIGNED.value,
            "views": alpha_memory.get("views"),
            "published_dataset": str(published.registration.dataset_id),
            "published_occurrences": published.occurrences,
            "published_rows": published.row_count,
            "publication": published.output_path.name,
        },
        "index_run": {
            "exchange": "KRX (whole shares, 3bp commission, 20bp sale tax, long only)",
            "account_mode": AccountMode.LONG_ONLY.value,
            "subscribed_allocation_inputs": ["alpha_allocation", "benchmark_weight_daily"],
            "shipped_constraints": sorted(SHIPPED_CONSTRAINTS),
            "single_name_cap": CAP,
            "rebalances": index_memory.get("rebalances"),
            "frozen_occurrences": index_memory.get("frozen_occurrences"),
            "freezes_released": index_memory.get("freezes_released"),
            "final_active_norm": index_memory.get("active_norm"),
            **index_monitoring,
            **index_replay,
        },
    }
    digests = {
        "alpha_allocation.parquet": _digest(published.output_path),
        "alpha_allocation.lineage.json": _digest(published.lineage_path),
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

    index = trace["index_run"]
    print(f"sessions / callbacks    : {trace['sessions']} / {trace['callbacks']}")
    print(f"alpha views published   : {trace['alpha_run']['published_occurrences']} occurrences")
    print(f"subscribed inputs       : {', '.join(index['subscribed_allocation_inputs'])}")
    print(f"shipped constraints     : {', '.join(index['shipped_constraints'])}")
    print(f"rebalances              : {index['rebalances']}")
    print(f"frozen / released       : {index['frozen_occurrences']} / {index['freezes_released']}")
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
