from __future__ import annotations

import hashlib
import html
import json
import shutil
import sys
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import duckdb

from vqapr.public import (
    AccountMode,
    AccountSnapshot,
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
    VqaprError,
    component_ref,
    preflight_run,
    register_agenda,
    register_component,
    register_dataset,
    register_execution_input,
    register_monitoring_policy,
    register_strategy_config,
    register_valuation_config,
    run,
)

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
PROJECT = OUTPUTS / "project"
VERIFIED_AGAINST = "vqapr-0.1.0+implementation-008-working-tree"
LAST_VERIFIED_AT = "2026-08-16"


def _reset_outputs() -> None:
    if OUTPUTS.exists():
        shutil.rmtree(OUTPUTS)
    OUTPUTS.mkdir(parents=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_parquets() -> tuple[Path, Path, Path, Path]:
    observation = OUTPUTS / "observation_price_daily.parquet"
    execution = OUTPUTS / "execution_krx_daily.parquet"
    invalid = OUTPUTS / "invalid_execution_price.parquet"
    canonical = OUTPUTS / "execution_krx_daily_canonical.parquet"
    observation_target = observation.as_posix()
    execution_target = execution.as_posix()
    invalid_target = invalid.as_posix()
    canonical_target = canonical.as_posix()
    con = duckdb.connect()
    try:
        con.execute(f"""COPY (SELECT * FROM (VALUES
          (DATE '2024-03-05', TIMESTAMPTZ '2024-03-05 03:00:00+09', 'A', 99.0),
          (DATE '2024-03-06', TIMESTAMPTZ '2024-03-06 03:00:00+09', 'A', 101.0),
          (DATE '2024-03-07', TIMESTAMPTZ '2024-03-07 03:00:00+09', 'A', 104.0)
        ) AS t(session_date, available_at, instrument, close))
        TO '{observation_target}' (FORMAT PARQUET)""")
        con.execute(f"""COPY (SELECT * FROM (VALUES
          (TIMESTAMPTZ '2024-03-05 10:00:00+09', 'A', true, 98.0),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 100.0),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'B', true, 50.0),
          (TIMESTAMPTZ '2024-03-06 10:00:00+09', 'A', true, 101.0),
          (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', true, 103.0),
          (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'B', false, 51.0),
          (TIMESTAMPTZ '2024-03-07 10:00:00+09', 'A', true, 104.0),
          (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'A', true, 105.0),
          (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'B', true, 53.0)
        ) AS t(trade_at, instrument, is_tradable, close))
        TO '{execution_target}' (FORMAT PARQUET)""")
        con.execute(f"""COPY (SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
          'A' AS instrument, true AS is_tradable, CAST('NaN' AS DOUBLE) AS close)
          TO '{invalid_target}' (FORMAT PARQUET)""")
        con.execute(f"""COPY (
          SELECT * FROM read_parquet('{execution_target}')
          WHERE EXTRACT(hour FROM trade_at) = 15
        ) TO '{canonical_target}' (FORMAT PARQUET)""")
    finally:
        con.close()
    return observation, execution, invalid, canonical


def _write_components(source_digest: str) -> tuple[Path, Path, Path]:
    components = PROJECT / "components"
    components.mkdir(parents=True)
    strategy = components / "strategy.py"
    exchange = components / "exchange.py"
    constraint = components / "constraint.py"
    strategy.write_text(
        f'''from decimal import Decimal
from uuid import UUID

from vqapr.public import (Budget, EconomicPortfolioIntent, IntentSourceRef,
    NoDecision, PortfolioDirection, PortfolioTarget, RowsLookback,
    StrategyModel, DataRequirement)


class ShowcaseStrategy(StrategyModel):
    def requirements(self):
        return (DataRequirement.of(
            "showcase-strategy",
            "price_daily",
            fields=("close",),
            lookback=RowsLookback(1),
        ),)

    def on_occurrence(self, context):
        context.window.observations(self.requirements()[0])
        if self.memory:
            return NoDecision("the one demonstrated intent is already pending or executed")
        self.memory = {{"issued": True}}
        return EconomicPortfolioIntent(
            UUID("00000000-0000-0000-0000-000000000001"), "showcase-strategy",
            (PortfolioTarget("A", weight=Decimal("0.5")),), Decimal("0.5"),
            Budget(
                PortfolioDirection.LONG_ONLY,
                Decimal("0"),
                Decimal("1"),
                Decimal("0"),
                Decimal("1"),
            ),
            (IntentSourceRef("price-observation", "{source_digest}"),),
            context.account.version, None)
''',
        encoding="utf-8",
    )
    exchange.write_text(
        """from decimal import Decimal
from vqapr.public import AcademicExchange, ListingRule, Side


class ShowcaseExchange(AcademicExchange):
    def __init__(self):
        listing = ListingRule(
            "A",
            Decimal("0.1"),
            Decimal("0.1"),
            True,
            frozenset({Side.BUY, Side.SELL}),
        )
        super().__init__({"A": listing}, "showcase-exchange")
""",
        encoding="utf-8",
    )
    constraint.write_text(
        """from decimal import Decimal
from vqapr.public import Constraint, ConstraintBounds, ConstraintFinding


class ShowcaseConstraint(Constraint):
    @property
    def constraint_id(self):
        return "showcase-constraint"

    def requirements(self):
        return ()

    def project(self, window, instruments):
        return ConstraintBounds(
            {instrument: Decimal("0") for instrument in instruments},
            {instrument: Decimal("1") for instrument in instruments},
        )

    def validate_intended(self, intent, bounds):
        return ConstraintFinding(
            self.constraint_id,
            True,
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            {},
        )

    def evaluate(self, window, account, marks, bounds):
        return ConstraintFinding(
            self.constraint_id,
            True,
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            {},
        )
""",
        encoding="utf-8",
    )
    return strategy, exchange, constraint


def _agenda(agenda_id: str, role: OperationRole, local_time: time) -> OperationAgenda:
    return OperationAgenda.from_occurrences(
        agenda_id=agenda_id,
        role=role,
        timezone="Asia/Seoul",
        occurrences=tuple(
            OperationOccurrence(
                f"{agenda_id}-{day}",
                role,
                LocalInstantDeclaration(date(2024, 3, day), local_time, "Asia/Seoul", 0, "+09:00"),
            )
            for day in (5, 6, 7)
        ),
        provenance="show_001 finite public agenda",
    )


def _execution_registration(raw_id: str, source: SourceSpec) -> ExecutionInputRegistration:
    return ExecutionInputRegistration.of(
        raw_id,
        ExecutionTableSpec(
            source=source,
            trade_at_field="trade_at",
            instrument_field="instrument",
            is_tradable_field="is_tradable",
            price_fields={"close": "close"},
        ),
        FillConvention(FillSelector.NEXT_ELIGIBLE, time(15, 30), "Asia/Seoul", "close"),
    )


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, frozenset)):
        return [_json_value(item) for item in value]
    if isinstance(value, (Decimal, datetime)):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p>No rows.</p>"
    columns = list(rows[0])
    return (
        "<table><tr>"
        + "".join(f"<th>{html.escape(key)}</th>" for key in columns)
        + "</tr>"
        + "".join(
            "<tr>" + "".join(f"<td>{html.escape(str(row[key]))}</td>" for key in columns) + "</tr>"
            for row in rows
        )
        + "</table>"
    )


def _report(trace: dict[str, Any]) -> str:
    execution_rows = _table(trace["execution_rows"])
    run_trace = html.escape(json.dumps(trace["run"], indent=2, default=str))
    density = html.escape(json.dumps(trace["density_invariance"], indent=2, default=str))
    invalid = html.escape(json.dumps(trace["invalid_registration"], indent=2, default=str))
    return f"""<!doctype html><meta charset="utf-8"><title>VQAPR public run evidence</title>
<style>
body{{font-family:system-ui;max-width:1100px;margin:2rem auto}}
pre,table{{border:1px solid #ccc;padding:1rem;overflow:auto}}
td,th{{padding:.4rem;border:1px solid #ddd}}
</style>
<h1>Public register → configure → preflight → run</h1>
<p>All VQAPR imports in this entry point and generated Strategy, Exchange, and Constraint
modules use <code>vqapr.public</code>. The result comes from
<code>vqapr.public.run</code>.</p>
<h2>Execution input rows (10:00 rows are deliberately non-selected)</h2>{execution_rows}
<h2>Public run trace</h2><pre>{run_trace}</pre>
<h2>Density invariance</h2><pre>{density}</pre>
<h2>Invalid selected price</h2><pre>{invalid}</pre>
<p>Verified against {VERIFIED_AGAINST}; last verified {LAST_VERIFIED_AT}.</p>"""


def _run_signature(result: Any) -> dict[str, Any]:
    """Complete, unmodified canonical lifecycle evidence."""
    return _json_value(result)


def _first_difference(left: Any, right: Any, path: str = "$") -> str:
    if type(left) is not type(right):
        return f"{path}: {type(left).__name__} != {type(right).__name__}"
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return f"{path}: keys {tuple(left)} != {tuple(right)}"
        for key in left:
            difference = _first_difference(left[key], right[key], f"{path}.{key}")
            if difference:
                return difference
        return ""
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: length {len(left)} != {len(right)}"
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            difference = _first_difference(left_item, right_item, f"{path}[{index}]")
            if difference:
                return difference
        return ""
    return "" if left == right else f"{path}: {left!r} != {right!r}"


def main() -> None:
    _reset_outputs()
    observation_path, execution_path, invalid_path, canonical_path = _write_parquets()
    strategy_path, exchange_path, constraint_path = _write_components(_sha256(observation_path))
    observation = DatasetRegistration.of(
        "price_daily",
        "price-observation",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close", "session_date": "session_date"},
    )
    register_dataset(PROJECT, observation, SourceSpec.of("price-observation", observation_path))
    execution = _execution_registration("krx-daily", SourceSpec.of("krx-execution", execution_path))
    register_execution_input(PROJECT, execution)
    strategy_ref = component_ref(
        "showcase-strategy", ComponentKind.STRATEGY_MODEL, strategy_path, "ShowcaseStrategy"
    )
    exchange_ref = component_ref(
        "showcase-exchange", ComponentKind.EXCHANGE, exchange_path, "ShowcaseExchange"
    )
    constraint_ref = component_ref(
        "showcase-constraint", ComponentKind.CONSTRAINT, constraint_path, "ShowcaseConstraint"
    )
    for reference in (strategy_ref, exchange_ref, constraint_ref):
        register_component(PROJECT, reference)
    strategy_agenda = _agenda("showcase-strategy", OperationRole.STRATEGY_CALLBACK, time(4))
    valuation_agenda = _agenda("showcase-valuation", OperationRole.VALUATION, time(16))
    monitoring_agenda = _agenda("showcase-monitoring", OperationRole.MONITORING, time(17))
    for agenda in (strategy_agenda, valuation_agenda, monitoring_agenda):
        register_agenda(PROJECT, agenda)
    strategy_config = StrategyConfig(
        strategy_ref, "showcase-strategy", OperationRole.STRATEGY_CALLBACK
    )
    valuation_config = ValuationConfig(
        "showcase-valuation",
        OperationRole.VALUATION,
        DataRequirement.of(
            "showcase-valuation", "price_daily", fields=("close",), lookback=RowsLookback(1)
        ),
    )
    monitoring = MonitoringPolicy("showcase-monitoring", OperationRole.MONITORING)
    register_strategy_config(PROJECT, strategy_config)
    register_valuation_config(PROJECT, valuation_config)
    register_monitoring_policy(PROJECT, monitoring)
    definition = RunDefinition(
        strategy_config,
        valuation_config,
        ConstraintSet((constraint_ref,)),
        monitoring,
        exchange_ref,
        "krx-daily",
        datetime(2024, 3, 5, 0, tzinfo=strategy_agenda.occurrences[0].evaluation_time.tzinfo),
        datetime(2024, 3, 7, 23, tzinfo=strategy_agenda.occurrences[0].evaluation_time.tzinfo),
        AccountSnapshot(0, Decimal("100"), {}),
        AccountMode.LONG_ONLY,
        instruments=("A",),
    )
    frozen = preflight_run(PROJECT, definition)
    result = run(PROJECT, frozen)
    dense_execution = execution_path.read_bytes()
    shutil.copyfile(canonical_path, execution_path)
    try:
        canonical_result = run(PROJECT, frozen)
    finally:
        execution_path.write_bytes(dense_execution)
    workspace_path = PROJECT / ".vqapr" / "workspace.yaml"
    before_invalid = workspace_path.read_bytes()
    try:
        register_execution_input(
            PROJECT,
            _execution_registration(
                "invalid-close", SourceSpec.of("invalid-execution", invalid_path)
            ),
        )
    except VqaprError as error:
        invalid = error.as_dict()
        invalid.pop("correlation_id", None)
    else:
        raise AssertionError("invalid selected price unexpectedly registered")
    if workspace_path.read_bytes() != before_invalid:
        raise AssertionError("invalid registration mutated the workspace")
    con = duckdb.connect()
    try:
        execution_query = (
            f"SELECT * FROM read_parquet('{execution_path.as_posix()}') "
            "ORDER BY trade_at, instrument"
        )
        cursor = con.execute(execution_query)
        columns = [column[0] for column in cursor.description]
        rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    finally:
        con.close()
    dense_trace = _json_value(result)
    dense_signature = _run_signature(result)
    canonical_signature = _run_signature(canonical_result)
    if dense_signature != canonical_signature:
        difference = _first_difference(dense_signature, canonical_signature)
        raise AssertionError(f"non-selected execution row density changed outcome: {difference}")
    trace = {
        "status": "current",
        "verified_against": VERIFIED_AGAINST,
        "last_verified_at": LAST_VERIFIED_AT,
        "component_sources": {
            path.name: _sha256(path) for path in (strategy_path, exchange_path, constraint_path)
        },
        "preflight": {
            "shared": _json_value(frozen),
        },
        "execution_rows": _json_value(rows),
        "run": dense_trace,
        "density_invariance": {
            "extra_non_selected_rows": 3,
            "dense_outcome_equals_canonical_outcome": dense_signature == canonical_signature,
            "dense_signature": dense_signature,
            "canonical_signature": canonical_signature,
            "claim": (
                "Two runs use the same FrozenRun and differ only by three non-selected "
                "10:00 physical rows. Their complete, unmodified lifecycle traces are equal."
            ),
        },
        "invalid_registration": {"workspace_unchanged": True, "error": invalid},
    }
    shutil.copyfile(workspace_path, OUTPUTS / "workspace.yaml")
    (OUTPUTS / "trace.json").write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
    (OUTPUTS / "report.html").write_text(_report(trace), encoding="utf-8")
    print(OUTPUTS / "report.html")


if __name__ == "__main__":
    main()
