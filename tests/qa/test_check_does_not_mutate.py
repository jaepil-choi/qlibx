"""Adversarial attack on claim 1: `vqapr check` writes nothing under `.vqapr/`.

The package's own docstring in `src/vqapr/cli/check.py` makes a narrower claim than "check is
safe": it says vqapr itself writes nothing, and explicitly disclaims sandboxing user code --
`weights` and `records` are Python, `check` must import the component module to judge it, and an
imported module can do anything a Python module can do, including writing files.

This file tries to break BOTH the narrow claim (`.vqapr/` byte-identical) and check whether the
docstring's disclaimer is itself accurate: does `check` really import the component (so the
disclaimer is honest), and does it really leave `.vqapr/` untouched even when the imported module
tries to write inside `.vqapr/` itself?
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from vqapr.cli.check import check
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionInputRegistration, ExecutionTableSpec
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.flow.run import StrategyConfig, ValuationConfig
from vqapr.public import register_dataset as pub_register_dataset
from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole
from vqapr.workspace import WORKSPACE_DIRECTORY, Workspace

_SPAN = (datetime(2024, 1, 2, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))


def _fingerprint(root: Path) -> dict[str, str]:
    workspace = root / WORKSPACE_DIRECTORY
    if not workspace.exists():
        return {}
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }


def _prices_dataset(root: Path) -> None:
    """A real, registered dataset with a real parquet file behind it."""
    prices_dir = root / "prepared" / "prices"
    prices_dir.mkdir(parents=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
                (TIMESTAMPTZ '2024-01-02 00:00:00+00', 'A', 100.0),
                (TIMESTAMPTZ '2024-01-03 00:00:00+00', 'A', 101.0)
              ) AS t(available_at, instrument, close))
              TO '{(prices_dir / "d.parquet").as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    pub_register_dataset(
        root,
        DatasetRegistration.of(
            "prices",
            "prices-src",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
        ),
        SourceSpec.of("prices-src", prices_dir),
    )


def _run_ready_workspace(root: Path, marker: Path, *, evil_body: str) -> Path:
    """A workspace complete enough that every `check` phase reaches `preflight`.

    This is deliberately more work than the fixtures in `tests/cli/test_check.py`: an incomplete
    spec never reaches `preflight`, and `preflight` is where `weights` (via `_judge_weights`'
    venue lookup) and the strategy component actually get imported. An attack on "check imports
    user code" that never resolves declarations would not prove anything.
    """
    _prices_dataset(root)

    source = root / "evil.py"
    source.write_text(evil_body.format(marker=str(marker).replace("\\", "\\\\")), encoding="utf-8")
    workspace = Workspace.open(root)
    workspace.register_component(
        ComponentRef.of(
            "evil",
            ComponentKind.STRATEGY_MODEL,
            source,
            "Strategy",
            fingerprint=fingerprint_component(
                source, kind=ComponentKind.STRATEGY_MODEL, object_name="Strategy"
            ),
        )
    )

    venue_source = root / "venue.py"
    venue_source.write_text(
        "from decimal import Decimal\n"
        "from vqapr.exchange.venue import AcademicExchange, TradeRule\n"
        "from vqapr.exchange.listings import ListingAccess\n"
        "class Venue(AcademicExchange):\n"
        "    def __init__(self):\n"
        "        super().__init__({'A': TradeRule('A', Decimal('1'), Decimal('1'), False,\n"
        "            ListingAccess.LONG_ONLY)})\n",
        encoding="utf-8",
    )
    Workspace.open(root).register_component(
        ComponentRef.of(
            "venue",
            ComponentKind.EXCHANGE,
            venue_source,
            "Venue",
            fingerprint=fingerprint_component(
                venue_source, kind=ComponentKind.EXCHANGE, object_name="Venue"
            ),
        )
    )

    exec_dir = root / "prepared" / "exec"
    exec_dir.mkdir(parents=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
                (TIMESTAMPTZ '2024-01-02 15:30:00+09', 'A', true, 100.0),
                (TIMESTAMPTZ '2024-01-03 15:30:00+09', 'A', true, 101.0)
              ) AS t(trade_at, instrument, is_tradable, close))
              TO '{(exec_dir / "e.parquet").as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    Workspace.open(root).register_execution_input(
        ExecutionInputRegistration.of(
            "my-exec",
            ExecutionTableSpec(
                source=SourceSpec.of("exec-src", exec_dir),
                trade_at_field="trade_at",
                instrument_field="instrument",
                is_tradable_field="is_tradable",
                price_fields={"close": "close"},
            ),
            FillConvention(
                selector=FillSelector.NEXT_ELIGIBLE,
                local_time=datetime(2024, 1, 1, 15, 30).time(),
                timezone="Asia/Seoul",
                trade_price="close",
            ),
        )
    )

    agenda = OperationAgenda.from_occurrences(
        agenda_id="daily",
        role=OperationRole.STRATEGY_CALLBACK,
        timezone="Asia/Seoul",
        occurrences=(
            OperationOccurrence(
                "o1",
                OperationRole.STRATEGY_CALLBACK,
                LocalInstantDeclaration(
                    datetime(2024, 1, 2).date(),
                    datetime(2024, 1, 2, 9, 0).time(),
                    "Asia/Seoul",
                    0,
                    "+09:00",
                ),
            ),
        ),
        provenance="qa fixture",
    )
    Workspace.open(root).register_agenda(agenda)
    val_agenda = OperationAgenda.from_occurrences(
        agenda_id="daily-val",
        role=OperationRole.VALUATION,
        timezone="Asia/Seoul",
        occurrences=(
            OperationOccurrence(
                "v1",
                OperationRole.VALUATION,
                LocalInstantDeclaration(
                    datetime(2024, 1, 2).date(),
                    datetime(2024, 1, 2, 9, 0).time(),
                    "Asia/Seoul",
                    0,
                    "+09:00",
                ),
            ),
        ),
        provenance="qa fixture",
    )
    Workspace.open(root).register_agenda(val_agenda)
    Workspace.open(root).register_strategy_config(
        StrategyConfig(
            Workspace.open(root).component("evil"), "daily", OperationRole.STRATEGY_CALLBACK
        )
    )
    Workspace.open(root).register_valuation_config(
        ValuationConfig("daily-val", OperationRole.VALUATION)
    )

    import yaml

    document = {
        "strategy": {"agenda_id": "daily", "component": "evil"},
        "valuation": {"agenda_id": "daily-val"},
        "instruments": ["A"],
        "start": "2024-01-02T00:00:00+00:00",
        "end": "2024-01-05T00:00:00+00:00",
        "exchange": "venue",
        "execution_input": "my-exec",
        "initial_account": {"mode": "LONG_ONLY", "cash": "1000", "positions": {}},
    }
    spec = root / "spec.yaml"
    spec.write_text(yaml.safe_dump(document), encoding="utf-8")
    return spec


_STRATEGY_BODY = '''"""A strategy module with a side effect at import time."""
from pathlib import Path
Path(r"{marker}").write_text("pwned", encoding="utf-8")

from vqapr.public import StrategyModel, DataRequirement, RowsLookback, Hold


class Strategy(StrategyModel):
    def requirements(self):
        return (DataRequirement.of('prices', 'close', lookback=RowsLookback(2)),)

    def decide(self, context):
        return Hold(reason="qa probe")
'''


def test_check_does_not_touch_dot_vqapr_even_when_the_imported_module_writes_files(
    tmp_path: Path,
) -> None:
    """AC-C1, attacked with a component that DOES have a side effect at import.

    A byte-for-byte fingerprint of `.vqapr/` before and after, with a component module that is
    guaranteed to be imported (the run is complete enough to reach `preflight`) and that writes a
    marker file when it is. If the component import itself corrupted anything under `.vqapr/`,
    this catches it; the earlier fixtures in `tests/cli/test_check.py` never exercised a module
    that actually does something on import.
    """
    marker = tmp_path / "evil_marker_outside_workspace.txt"
    spec = _run_ready_workspace(tmp_path, marker, evil_body=_STRATEGY_BODY)

    before = _fingerprint(tmp_path)
    assert before, "the fixture must produce a workspace, or this test proves nothing"
    assert not marker.exists(), "the marker must not exist before check ever runs"

    body = check(spec, tmp_path)

    after = _fingerprint(tmp_path)
    assert after == before, ".vqapr/ was mutated by check"
    # The module WAS imported -- this is the property that makes the fingerprint comparison
    # meaningful rather than vacuous, and it is also the evidence for the docstring's own claim.
    assert marker.exists(), (
        "the component module was never imported, so this attack proved nothing about "
        "whether check's own writes are absent"
    )
    assert body["ok"] is True, (
        "the fixture must be a CLEAN spec, or this test cannot tell a mutation from a refusal: "
        f"{[entry['code'] for entry in body['failures']]}"
    )


def _write_into_dot_vqapr_body(marker_relative: str) -> str:
    return f'''"""A strategy module that tries to write INSIDE .vqapr/ itself."""
from pathlib import Path
import os

# Deliberately targets .vqapr/ using the module's own __file__ to find the project root, the
# same way an attacker-controlled or merely careless component author might.
root = Path(__file__).resolve().parent
(root / ".vqapr" / "{marker_relative}").write_text("pwned-inside-dot-vqapr", encoding="utf-8")

from vqapr.public import StrategyModel, DataRequirement, RowsLookback, Hold


class Strategy(StrategyModel):
    def requirements(self):
        return (DataRequirement.of('prices', 'close', lookback=RowsLookback(2)),)

    def decide(self, context):
        return Hold(reason="qa probe")
'''


def test_the_docstrings_claim_is_the_claim_it_actually_keeps(tmp_path: Path) -> None:
    """The docstring says "vqapr writes nothing", NOT "nothing is written under .vqapr/".

    A component that writes a file directly inside `.vqapr/` (using its own path, not a
    vqapr-supplied handle) is user code doing what user code can do -- the docstring's own words
    admit this ("arbitrary user code can write anywhere it likes"). The `.vqapr/` fingerprint
    comparison above only sees FILES vqapr's own fixture created before the run; a file the evil
    module ADDS inside .vqapr/ is new content the fingerprint (which reads the same directory
    both times) would in fact catch, so this test proves the docstring is not overclaiming: it
    is honest that user code, including inside `.vqapr/`, is unsandboxed.
    """
    marker_name = "evil_wrote_this_inside_dot_vqapr.txt"
    spec = _run_ready_workspace(
        tmp_path,
        tmp_path / "unused",
        evil_body=_write_into_dot_vqapr_body(marker_name),
    )

    before = _fingerprint(tmp_path)
    check(spec, tmp_path)
    after = _fingerprint(tmp_path)

    marker_path = tmp_path / ".vqapr" / marker_name
    assert marker_path.exists(), "the module import never ran, so this attack proved nothing"
    # The fingerprint necessarily differs now -- a new file exists under .vqapr/. This is not a
    # failure of the claim; it is exactly what the docstring says will happen, and the assertion
    # exists so a future reader who "fixes" this by weakening the docstring's disclaimer is
    # caught, rather than silently regressing the guarantee to something check cannot make.
    assert after != before, (
        "a file written by user code directly under .vqapr/ was not observed by the "
        "fingerprint, so the byte-identical test elsewhere in the suite would not have caught it"
    )


def test_check_creates_no_workspace_where_none_existed(tmp_path: Path) -> None:
    """Checking an uninitialised directory must not initialise it (regression pin)."""
    check(tmp_path / "spec.yaml", tmp_path)
    assert not (tmp_path / WORKSPACE_DIRECTORY).exists()
