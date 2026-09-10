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
from pydantic import BaseModel

# The showcase's own directory is not guaranteed to be on sys.path - an acceptance
# test importing this module runs from the repo root. Locate it explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import show001_models as models

from vqapr.domain.errors import VqaprError
from vqapr.public import (
    AccountMode,
    AccountSnapshot,
    DatasetRegistration,
    RunAgenda,
    RunDefinition,
    RunExecution,
    RunFill,
    SourceSpec,
    StrategyEntry,
    preflight_run,
    register_dataset,
    register_exchange,
    register_instruments,
    register_strategy_model,
    run,
)

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
PROJECT = OUTPUTS / "project"
VERIFIED_AGAINST = "vqapr-0.11.0"
LAST_VERIFIED_AT = "2026-09-10"

SESSIONS = (date(2024, 3, 5), date(2024, 3, 6), date(2024, 3, 7))
KST = "Asia/Seoul"
OFFSET = "+09:00"


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


def _write_parquets() -> tuple[Path, Path, Path, Path]:
    """The dense execution table (with 10:00 rows nobody selects), its canonical trim,
    one invalid table a rejected registration must never make visible, and the observation
    dataset the strategy declares."""
    execution = OUTPUTS / "execution_krx_daily.parquet"
    invalid = OUTPUTS / "invalid_execution_price.parquet"
    canonical = OUTPUTS / "execution_krx_daily_canonical.parquet"
    observation = OUTPUTS / "price_daily.parquet"
    execution_target = execution.as_posix()
    invalid_target = invalid.as_posix()
    canonical_target = canonical.as_posix()
    observation_target = observation.as_posix()
    con = duckdb.connect()
    try:
        con.execute(f"""COPY (SELECT trade_at, instrument, is_tradable, CAST(close AS DOUBLE) AS close
        FROM (VALUES
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
        # The observation dataset the strategy declares. Its instants are session closes, so
        # the 04:00 callback on day N sees day N-1's close and nothing later. The close is a
        # DOUBLE on purpose: a bare `100.0` literal is DECIMAL to duckdb, and a DECIMAL column
        # cannot be declared as a dataset field (issue 088).
        con.execute(f"""COPY (SELECT available_at, instrument, CAST(close AS DOUBLE) AS close
        FROM (VALUES
          (TIMESTAMPTZ '2024-03-04 15:30:00+09', 'A', 99.0),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', 100.0),
          (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', 103.0),
          (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'A', 105.0)
        ) AS t(available_at, instrument, close))
        TO '{observation_target}' (FORMAT PARQUET)""")
    finally:
        con.close()
    return execution, invalid, canonical, observation


def _venue_dataset(dataset_id: str) -> DatasetRegistration:
    """The venue table as a dataset with an execution role (record 185).

    `trade_at` is the instant a row is a fact about, the role names the tradable flag, and
    the numeric fields are the prices the venue published. Which one a run fills at is the
    run's own `execution.fill.trade_price`, so this table serves any fill without being
    registered twice.
    """
    return DatasetRegistration.of(
        dataset_id,
        f"{dataset_id}-source",
        instrument_field="instrument",
        available_at="trade_at",
        grain="instrument_instant",
        key_fields=("trade_at", "instrument"),
        fields={"close": "close", "is_tradable": "is_tradable"},
        field_types={"close": "DOUBLE", "is_tradable": "BOOLEAN"},
        execution={"is_tradable": "is_tradable"},
    )


def _fill(dataset_id: str) -> RunExecution:
    """This run's fill on the venue table: the next eligible 15:30 close after a decision."""
    return RunExecution(
        dataset=dataset_id,
        trade_price="close",
        fill=RunFill(at=time(15, 30)),
    )


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, BaseModel):
        return {name: _json_value(getattr(value, name)) for name in type(value).model_fields}
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


MARKET_CLOCK_KINDS = ("MARKED", "MONITORED")
"""Lifecycle kinds the MARKET clock writes (design §3.1): one per execution instant, so their
count is the table's density -- exactly what `UC-TIME-002` lets vary."""


def _signature(result: Any) -> dict[str, Any]:
    """What a run is, reduced to values two runs can be compared on.

    `SimulationResult` carries object identity - occurrence ids minted per run, trace objects -
    so comparing the results themselves would report a difference that means nothing. Two
    halves (design §3): `outcome` is what the STRATEGY clock and the account say -- how the
    account ended, how many decisions were made and settled -- and must not move with the
    execution table's density (`UC-TIME-002`); `market_clock` is how many instants the book was
    valued at, which IS the table's density and moves with it on purpose (record `206`).
    """
    final_state = result.final_state
    snapshot = final_state.account.snapshot
    lifecycle: dict[str, int] = {}
    for entry in final_state.lifecycle_trace:
        lifecycle[entry.kind.value] = lifecycle.get(entry.kind.value, 0) + 1
    decisions = sum(1 for trace in result.occurrences if type(trace).__name__ == "OccurrenceTrace")
    return {
        "outcome": {
            "account_version": snapshot.version,
            "cash": str(snapshot.cash),
            "positions": {
                str(key): str(value) for key, value in sorted(snapshot.positions.items())
            },
            "lifecycle": {
                kind: count
                for kind, count in sorted(lifecycle.items())
                if kind not in MARKET_CLOCK_KINDS
            },
            "decisions": decisions,
        },
        "market_clock": {
            "valuations": lifecycle.get("MARKED", 0),
            "instants": len(result.occurrences) - decisions,
        },
    }


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
    return f"""<!doctype html><meta charset="utf-8">
<title>VQAPR venue dataset registration</title>
<style>
body{{font-family:system-ui;max-width:1100px;margin:2rem auto}}
pre,table{{border:1px solid #ccc;padding:1rem;overflow:auto}}
td,th{{padding:.4rem;border:1px solid #ddd}}
</style>
<h1>Execution input registration: declare, register, run</h1>
<p>Every VQAPR import in this entry point comes from <code>vqapr.public</code>, the surface
the shipped CLI stands on. The authored strategy in <code>show001_models.py</code> implements
<code>vqapr.authoring.StrategyModel</code> and returns only <code>Hold</code>/<code>Rebalance</code>
- the loader adapts it and the framework stamps every identity fact (intent id, strategy id,
source refs, account version) itself.</p>
<h2>Execution input rows (10:00 rows are deliberately non-selected)</h2>{execution_rows}
<h2>Run summary</h2><pre>{run_trace}</pre>
<h2>Density invariance</h2><pre>{density}</pre>
<h2>Invalid venue table refused at registration</h2><pre>{invalid}</pre>
<p>Verified against {VERIFIED_AGAINST}; last verified {LAST_VERIFIED_AT}.</p>"""


def main() -> None:
    _reset_outputs()
    execution_path, invalid_path, canonical_path, observation_path = _write_parquets()
    strategy_path = Path(models.__file__).resolve()

    # --- Registration -------------------------------------------------------------------
    register_dataset(
        PROJECT,
        DatasetRegistration.of(
            "price_daily",
            "showcase-observation",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
            field_types={"close": "DOUBLE"},
        ),
        SourceSpec.of("showcase-observation", observation_path),
    )
    register_dataset(
        PROJECT,
        _venue_dataset("krx-daily"),
        SourceSpec.of("krx-daily-source", execution_path),
    )

    register_strategy_model(PROJECT, "showcase-strategy", strategy_path, "ShowcaseStrategy")
    # What the one name IS, declared before the run that orders it (design §6.2).
    register_instruments(PROJECT, {"A": "stock"})
    register_exchange(
        PROJECT, "showcase-exchange", ROOT / "show001_exchange.py", "ShowcaseExchange",
    )


    definition = RunDefinition(
        run_id="show001",
        # The legacy showcase generated a Constraint whose methods were unconditionally-passing
        # stubs projecting trivial [0, 1] bounds. It demonstrated no economic behaviour, so the
        # run declares no compliance rule rather than an inert one authored to keep a field
        # non-empty. See README.
        strategy=StrategyEntry("showcase-strategy"),
        timezone=KST,
        agenda=RunAgenda(every="1d", at=(time(4, 0),)),
        exchange="showcase-exchange",
        execution=_fill("krx-daily"),
        start=datetime.fromisoformat(f"2024-03-05T00:00:00{OFFSET}"),
        end=datetime.fromisoformat(f"2024-03-07T23:00:00{OFFSET}"),
        initial_account_snapshot=AccountSnapshot(0, Decimal("100"), {}),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=("A",),
        writes="show001-weights",
    )

    # --- One real run -------------------------------------------------------------------
    dense_summary = _signature(run(PROJECT, preflight_run(PROJECT, definition)).result())

    # --- Density invariance -------------------------------------------------------------
    # Same registered declaration, only the physical execution parquet's non-selected 10:00
    # rows differ from the canonical trim. Nothing is re-registered: the registration names a
    # path, and this rewrites what is at that path.
    dense_bytes = execution_path.read_bytes()
    shutil.copyfile(canonical_path, execution_path)
    try:
        # The same run again, deliberately: its first pass published `show001-weights`, and a
        # run replaces its own output the way it replaces its own record (design §2).
        canonical_summary = _signature(
            run(PROJECT, preflight_run(PROJECT, definition), replace_record=True).result()
        )
    finally:
        execution_path.write_bytes(dense_bytes)

    dense_signature = _json_value(dense_summary)
    canonical_signature = _json_value(canonical_summary)
    if dense_signature["outcome"] != canonical_signature["outcome"]:
        raise AssertionError(
            "non-selected execution row density changed outcome: "
            f"{dense_signature['outcome']} != {canonical_signature['outcome']}"
        )
    # The other half moves BY DESIGN (§3, record `206`): the extra 10:00 rows are extra points
    # of the market clock, and the book is valued at each of them.
    if dense_signature["market_clock"]["valuations"] <= canonical_signature["market_clock"]["valuations"]:
        raise AssertionError(
            "a denser execution table must value the book at more instants: "
            f"{dense_signature['market_clock']} vs {canonical_signature['market_clock']}"
        )

    # --- An invalid venue table is refused at registration, without workspace mutation --
    # The venue table is a dataset (record 185), so the dataset door judges it: a NaN close
    # is `dataset.value_not_finite`, the same refusal any dataset gets, and nothing is written.
    workspace_path = PROJECT / ".vqapr" / "workspace.yaml"
    before_invalid = workspace_path.read_bytes()
    try:
        register_dataset(
            PROJECT,
            _venue_dataset("invalid-close"),
            SourceSpec.of("invalid-close-source", invalid_path),
        )
    except VqaprError as error:
        invalid = error.as_dict()
        invalid.pop("correlation_id", None)
    else:
        raise AssertionError("a venue table with a non-finite close unexpectedly registered")
    after_invalid = workspace_path.read_bytes()
    if after_invalid != before_invalid:
        raise AssertionError("a refused registration mutated the workspace")

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
                "Two runs over the same registered declaration differ only by three "
                "non-selected 10:00 physical execution rows. Their economic signatures "
                "are equal."
            ),
        },
        "invalid_registration": {
            "workspace_unchanged": True,
            "checked_file": ".vqapr/workspace.yaml",
            "note": (
                "the venue table is a dataset, so register_dataset validates it before it "
                "writes: a non-finite close is refused as dataset.value_not_finite with the "
                "workspace byte-identical to what it was."
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
