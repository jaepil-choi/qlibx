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

# The showcase's own directory is not guaranteed to be on sys.path - an acceptance
# test importing this module runs from the repo root. Locate it explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import show001_models as models

import vqapr
from vqapr.domain.errors import VqaprError
from vqapr.simulation import (
    AccountMode,
    AccountSnapshot,
    Cadence,
    Execution,
    ExecutionInput,
    FillConvention,
    FillSelector,
    InitialAccount,
    Schedule,
    Simulation,
)
from vqapr.venues import Academic, Listing, ListingAccess

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
PROJECT = OUTPUTS / "project"
VERIFIED_AGAINST = "vqapr-0.1.0+implementation-008-working-tree"
LAST_VERIFIED_AT = "2026-08-25"

SESSIONS = (date(2024, 3, 5), date(2024, 3, 6), date(2024, 3, 7))
KST = "Asia/Seoul"


def _reset_outputs() -> None:
    if OUTPUTS.exists():
        shutil.rmtree(OUTPUTS)
    OUTPUTS.mkdir(parents=True)
    PROJECT.mkdir(parents=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_parquets() -> tuple[Path, Path, Path]:
    """The dense execution table (with 10:00 rows nobody selects), its canonical trim,
    and one invalid table a rejected registration must never make visible."""
    execution = OUTPUTS / "execution_krx_daily.parquet"
    invalid = OUTPUTS / "invalid_execution_price.parquet"
    canonical = OUTPUTS / "execution_krx_daily_canonical.parquet"
    execution_target = execution.as_posix()
    invalid_target = invalid.as_posix()
    canonical_target = canonical.as_posix()
    con = duckdb.connect()
    try:
        con.execute(f"""COPY (SELECT * FROM (VALUES
          (TIMESTAMPTZ '2024-03-05 10:00:00+09', 'A', true, 98.0),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 100.0),
          (TIMESTAMPTZ '2024-03-06 10:00:00+09', 'A', true, 101.0),
          (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', true, 103.0),
          (TIMESTAMPTZ '2024-03-07 10:00:00+09', 'A', true, 104.0),
          (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'A', true, 105.0)
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
    return execution, invalid, canonical


def _simulation(*, execution_path: Path, input_id: str) -> Simulation:
    return Simulation(
        schedule=Schedule(
            strategy=Cadence(sessions=SESSIONS, at=time(4, 0), timezone=KST),
            valuation=Cadence(sessions=SESSIONS, at=time(16, 0), timezone=KST),
            # Public run: `monitoring=None` states no monitoring cadence, explicitly.
            monitoring=None,
            start=datetime.fromisoformat("2024-03-05T00:00:00+09:00"),
            end=datetime.fromisoformat("2024-03-07T23:00:00+09:00"),
        ),
        execution=Execution(
            input=ExecutionInput(
                input_id=input_id,
                path=execution_path,
                hive_partitioned=False,
                trade_at_field="trade_at",
                instrument_field="instrument",
                is_tradable_field="is_tradable",
                price_fields={"close": "close"},
            ),
            fill=FillConvention(
                selector=FillSelector.NEXT_ELIGIBLE,
                at=time(15, 30),
                timezone=KST,
                trade_price="close",
            ),
        ),
        exchange=Academic(
            listings=(Listing(instrument_id="A", access=ListingAccess.SIGNED),),
            quantity_step=Decimal("0.1"),
            price_step=Decimal("0.1"),
            costs=(),
        ),
        account=InitialAccount(
            snapshot=AccountSnapshot(version=0, cash=Decimal("100"), positions={}),
            mode=AccountMode.LONG_ONLY,
        ),
        # The generated legacy constraint was inert scaffolding (always passed, projected
        # trivial [0, 1] bounds); it demonstrated no economic behaviour of its own, so the
        # migration drops it rather than authoring a Constraint whose only job would be to
        # exist. See README for the explicit record of this drop.
        constraints=(),
        instruments=("A",),
        initial_strategy_state=None,
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
<h1>Public Project.simulate: declare, register, run</h1>
<p>Every VQAPR import in this entry point comes from <code>vqapr</code>,
<code>vqapr.simulation</code>,
and <code>vqapr.venues</code>. The authored strategy in <code>models.py</code> implements
<code>vqapr.authoring.StrategyModel</code>. The result comes from
<code>vqapr.open(root).simulate(...)</code>, which registers the strategy component, its
agendas, the exchange, and the execution input itself - no caller touches a
<code>ComponentRef</code>, a fingerprint, an agenda id, or an
<code>EconomicPortfolioIntent</code>.</p>
<h2>Execution input rows (10:00 rows are deliberately non-selected)</h2>{execution_rows}
<h2>Public run summary</h2><pre>{run_trace}</pre>
<h2>Density invariance</h2><pre>{density}</pre>
<h2>Invalid execution input rejection</h2><pre>{invalid}</pre>
<p>Verified against {VERIFIED_AGAINST}; last verified {LAST_VERIFIED_AT}.</p>"""


def main() -> None:
    _reset_outputs()
    execution_path, invalid_path, canonical_path = _write_parquets()
    strategy_path = Path(models.__file__).resolve()

    project = vqapr.open(PROJECT)

    dense_simulation = _simulation(execution_path=execution_path, input_id="krx-daily")

    # `project.simulate` registers the strategy component, its agendas, the exchange, and
    # the execution input from these public declarations - that registration IS this
    # showcase's "execution input registration" claim, now implicit in one call instead of
    # a manual `register_execution_input` step.
    dense_summary = project.simulate(
        definition=dense_simulation, strategy=models.ShowcaseStrategy, run_id="showcase"
    )

    # --- Density invariance -------------------------------------------------------------
    # Same declaration, same run_id (every other registration is idempotent), only the
    # physical execution parquet's non-selected 10:00 rows differ from the canonical trim.
    dense_bytes = execution_path.read_bytes()
    shutil.copyfile(canonical_path, execution_path)
    try:
        canonical_summary = project.simulate(
            definition=dense_simulation, strategy=models.ShowcaseStrategy, run_id="showcase"
        )
    finally:
        execution_path.write_bytes(dense_bytes)

    dense_signature = _json_value(dense_summary)
    canonical_signature = _json_value(canonical_summary)
    if dense_signature != canonical_signature:
        raise AssertionError(
            "non-selected execution row density changed outcome: "
            f"{dense_signature} != {canonical_signature}"
        )

    # --- Invalid execution input is rejected without workspace mutation -----------------
    workspace_path = PROJECT / ".vqapr" / "workspace.yaml"
    before_invalid = workspace_path.read_bytes()
    invalid_simulation = _simulation(execution_path=invalid_path, input_id="invalid-close")
    try:
        project.simulate(
            definition=invalid_simulation, strategy=models.ShowcaseStrategy, run_id="showcase"
        )
    except VqaprError as error:
        invalid = error.as_dict()
        invalid.pop("correlation_id", None)
    else:
        raise AssertionError("invalid selected price unexpectedly registered")
    after_invalid = workspace_path.read_bytes()
    if after_invalid != before_invalid:
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

    trace = {
        "status": "current",
        "verified_against": VERIFIED_AGAINST,
        "last_verified_at": LAST_VERIFIED_AT,
        "authored_component_sources": {strategy_path.name: _sha256(strategy_path)},
        "execution_rows": _json_value(rows),
        "run": dense_signature,
        "density_invariance": {
            "extra_non_selected_rows": 3,
            "dense_outcome_equals_canonical_outcome": dense_signature == canonical_signature,
            "dense_signature": dense_signature,
            "canonical_signature": canonical_signature,
            "claim": (
                "Two Project.simulate runs over the same Simulation declaration and run_id "
                "differ only by three non-selected 10:00 physical execution rows. Their "
                "SimulationSummary values are equal."
            ),
        },
        "invalid_registration": {
            "workspace_unchanged": True,
            "checked_file": ".vqapr/workspace.yaml",
            "note": (
                "Project.simulate registers the execution input through the same "
                "retained engine path the legacy register/preflight/run spine used; this "
                "project never writes .vqapr/catalog.json at all, so the byte-identity "
                "check is against workspace.yaml here instead."
            ),
            "error": invalid,
        },
    }
    shutil.copyfile(workspace_path, OUTPUTS / "workspace.yaml")
    (OUTPUTS / "trace.json").write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
    (OUTPUTS / "report.html").write_text(_report(trace), encoding="utf-8")
    print(OUTPUTS / "report.html")


if __name__ == "__main__":
    main()
