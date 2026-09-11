"""The CLI is the surface a first-time user actually types, so it is driven here as typed.

`test_envelope.py` covers the envelope's shape and asserts the parser *mentions* every command.
Mentioning is not running: before this file, no test invoked `new`, `register`, `list` or `run`,
so the whole `runs: -> register -> RunDefinition -> preflight_run -> run` path was unexecuted.
These tests call `main(argv)` and read the JSON it emits, which is exactly what an agent gets.

Datasets, execution inputs, components and runs are declared through `vqapr register`, which is
the command that closed that gap. This file previously reached past the CLI into the library for
all of them, under a docstring admitting the CLI could not register them; the workspace below is
now reachable by typing `vqapr` commands only, which is the property that matters.

Since the two-clocks campaign a run declares its own strategy clock (`agenda`, `timezone`,
`at`): there is no agenda to register and no binding to write, so the fixture is one file
shorter than it was.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.cli.main import main

_ZONE = ZoneInfo("Asia/Seoul")

OCCURRENCES = 6
"""What the fixture run dispatches: three sessions, so three callbacks, and one execution each.

The book is valued at the instant the venue fills and the declared Compliance rules observe it right
after each commit (record 148), so neither valuation nor monitoring is an occurrence of its own
any more. Before 148 this was 12: three days times callback, valuation and monitoring, plus the
three executions.
"""


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    """Run one command exactly as the console script would and parse its one JSON line."""
    code = main(argv)
    out = capsys.readouterr().out.strip()
    return code, json.loads(out.splitlines()[-1])


def _parquets(root: Path) -> tuple[Path, Path]:
    """Observations the Strategy reads, and the venue table the run fills against."""
    observation = root / "observation.parquet"
    execution = root / "execution.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT session_date, available_at, instrument, close::DOUBLE AS close
            FROM (VALUES
              (DATE '2024-03-05', TIMESTAMPTZ '2024-03-05 03:00:00+09', 'A', 100.0),
              (DATE '2024-03-06', TIMESTAMPTZ '2024-03-06 03:00:00+09', 'A', 101.0),
              (DATE '2024-03-07', TIMESTAMPTZ '2024-03-07 03:00:00+09', 'A', 104.0)
            ) AS t(session_date, available_at, instrument, close))
            TO '{observation.as_posix()}' (FORMAT PARQUET)"""
        )
        con.execute(
            f"""COPY (SELECT trade_at, instrument, is_tradable, close::DOUBLE AS close
            FROM (VALUES
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 100.0),
              (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', true, 103.0),
              (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'A', true, 105.0)
            ) AS t(trade_at, instrument, is_tradable, close))
            TO '{execution.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    return observation, execution


def _exchange_component(root: Path) -> Path:
    path = root / "venue.py"
    path.write_text(
        "from decimal import Decimal\n"
        "from vqapr.public import AcademicExchange, TradeRule\n"
        "from vqapr.public import ListingAccess\n"
        "class Venue(AcademicExchange):\n"
        "    def __init__(self):\n"
        "        super().__init__({'A': TradeRule('A', Decimal('1'), Decimal('1'), False,\n"
        "            ListingAccess.SIGNED)})\n",
        encoding="utf-8",
    )
    return path


def _declaration(root: Path, observation: Path, execution: Path) -> Path:
    """The whole non-component workspace as one file, exactly as a user would write it."""
    path = root / "workspace.yaml"
    path.write_text(
        f"""
datasets:
  prices:
    source_id: price-source
    path: {observation.as_posix()}
    instrument_field: instrument
    available_at: available_at
    grain: instrument_instant
    key_fields: [available_at, instrument]
    fields: {{close: close}}
    field_types: {{close: DOUBLE}}
  venue-daily:
    source_id: venue-source
    path: {execution.as_posix()}
    instrument_field: instrument
    available_at: trade_at
    grain: instrument_instant
    key_fields: [trade_at, instrument]
    fields: {{close: close, is_tradable: is_tradable}}
    field_types: {{close: DOUBLE, is_tradable: BOOLEAN}}
    execution: {{is_tradable: is_tradable}}
""",
        encoding="utf-8",
    )
    return path


def _register_roster(
    root: Path, capsys: pytest.CaptureFixture[str], universe: dict[str, str]
) -> dict:
    """Declare what each id IS, through `vqapr register` -- the way a user does."""
    from vqapr.domain.instrument import export_roster

    written = export_roster(universe, root / "roster")
    declaration = root / "roster.yaml"
    declaration.write_text(
        "instruments:\n  tables:\n"
        + "".join(
            f"    {kind}: {path.relative_to(root).as_posix()}\n"
            for kind, path in sorted(written.items())
        ),
        encoding="utf-8",
    )
    code, registered = _cli(capsys, "--project-root", str(root), "register", str(declaration))
    assert code == 0, registered
    return registered


def _workspace_for_run(
    root: Path, capsys: pytest.CaptureFixture[str], *, roster: bool = True
) -> None:
    """Everything `run` needs, reached through the CLI alone.

    `roster=False` leaves the instruments undeclared, for the tests that assert what a strategy
    run says about that (design §6.3: preflight refuses it).
    """
    observation, execution = _parquets(root)
    if roster:
        _register_roster(root, capsys, {"A": "stock"})

    code, payload = _cli(
        capsys, "--project-root", str(root),
        "register", str(_declaration(root, observation, execution)),
    )
    assert code == 0, payload

    code, payload = _cli(
        capsys, "--project-root", str(root), "new", "strategy", "my-alpha",
        "--dataset", "prices", "--lookback", "2",
    )
    assert code == 0, payload
    code, registered = _cli(
        capsys, "--project-root", str(root), "register", payload["declaration"],
    )
    assert code == 0, registered

    venue = root / "venue.yaml"
    venue.write_text(
        f"""
components:
  venue:
    kind: exchange
    path: {_exchange_component(root).as_posix()}
    object_name: Venue
""",
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(root), "register", str(venue))
    assert code == 0, payload

    # The run itself is a registration too (record 139): `vqapr run r1` is what the tests type.
    code, payload = _register_run(root, capsys, "r1")
    assert code == 0, payload
    assert payload["registered"]["runs"] == ["r1"]


def _runs_declaration(root: Path, run_id: str = "r1", **overrides: object) -> Path:
    """A `runs:` declaration for one run over this workspace, exactly as a user would write it.

    `compliance=[...]` names the run's Compliance rules (design §7.2: on the run, beside the
    venue). Any other keyword replaces the run's key of that name -- `at="15:30"` is how a test declares
    a look-ahead, since the run's own `at` is the decision time (record 148).

    The strategy decides at 04:00 on every day the `prices` dataset has a row for: the rows
    become available at 03:00, and the venue fills at 15:30.
    """
    compliance = overrides.pop("compliance", None)
    body: dict[str, object] = {
        # A run declares what it writes (design §2); a test that cares overrides it.
        "writes": f"{run_id}-weights",
        "strategy": {"component": "my-alpha"},
        **({} if compliance is None else {"compliance": compliance}),
        "timezone": "Asia/Seoul",
        "agenda": {"every": "1d", "at": "04:00"},
        "exchange": "venue",
        "execution": {
            "dataset": "venue-daily",
            "trade_price": "close", "fill": {"at": "15:30"},
        },
        "start": datetime(2024, 3, 5, 0, tzinfo=_ZONE).isoformat(),
        "end": datetime(2024, 3, 7, 23, tzinfo=_ZONE).isoformat(),
        "initial_account": {"cash": "1000", "mode": "long_only"},
        "instruments": ["A"],
    }
    body.update(overrides)
    path = root / f"runs-{run_id}.yaml"
    path.write_text(json.dumps({"runs": {run_id: body}}), encoding="utf-8")  # JSON is YAML
    return path


def _register_run(
    root: Path, capsys: pytest.CaptureFixture[str], run_id: str = "r1", **overrides: object
) -> tuple[int, dict]:
    """Register one run through `vqapr register`, returning what the CLI answered."""
    return _cli(
        capsys, "--project-root", str(root),
        "register", str(_runs_declaration(root, run_id, **overrides)),
    )


def _strategy_ref(root: Path, capsys: pytest.CaptureFixture[str], run_id: str) -> str:
    """The one strategy record a run holds, as `<id>@<fp8>`, found the way a reader finds it."""
    code, listed = _cli(
        capsys, "--project-root", str(root), "list", "strategies", "--run", run_id
    )
    assert code == 0, listed
    assert listed["count"] == 1, listed
    return listed["items"][0]["strategy_ref"]


def test_new_register_and_list_are_one_working_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """What a first-time user types, in order, with nothing else set up."""
    code, created = _cli(
        capsys, "--project-root", str(tmp_path), "new", "strategy", "my-alpha",
        "--dataset", "prices",
    )
    assert code == 0
    assert created["stage"] == "component.new"
    assert Path(created["path"]).exists()

    # `new` emits the declaration `register` requires, so the two compose without the user
    # writing YAML from documentation on their first command.
    assert Path(created["declaration"]).exists()

    code, registered = _cli(
        capsys, "--project-root", str(tmp_path), "register", created["declaration"],
    )
    assert code == 0, registered
    assert registered["stage"] == "workspace.register"
    assert registered["registered"]["components"] == ["my-alpha"]

    code, listed = _cli(capsys, "--project-root", str(tmp_path), "list", "components")
    assert code == 0
    assert listed["count"] == 1
    assert listed["items"][0]["component_id"] == "my-alpha"
    # `new` emits the object name `register` needs, so the two commands compose without the
    # user opening the generated file.
    assert listed["items"][0]["object_name"] == created["object_name"]


def test_run_executes_a_registered_run_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The path the testbed never walked: `runs:` -> register -> preflight -> a completed run."""
    _workspace_for_run(tmp_path, capsys)

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "run", "r1")

    assert code == 0, payload
    assert payload["ok"] is True
    assert payload["stage"] == "run.complete"
    assert payload["run_id"] == "r1"
    # One strategy, reported under its own id: a run is configuration and the strategy record is
    # its output (record 139), so the numbers below are the strategy's.
    assert list(payload["strategies"]) == ["my-alpha"]
    strategy = payload["strategies"]["my-alpha"]
    assert strategy["record"].startswith("my-alpha@")
    # One callback per session (record 148: the run's sessions at its `at`, nothing else is
    # dispatched) plus the execution occurrences the fills land on. Pinned rather than `> 0`,
    # which a run that did nothing would also satisfy.
    assert strategy["occurrences"] == OCCURRENCES
    # The scaffold TRADES. It used to hold throughout -- the old template returned Hold --
    # and this assertion pinned account_version at zero, which meant the end-to-end test proved a
    # run that never bought anything. The authoring-contract scaffold ranks the cross-section and
    # rebalances, so fills commit and the Account advances, which is the stronger property: it
    # exercises the intent path, the execution path and the account commit rather than skipping
    # all three.
    assert strategy["account_version"] == 2
    # What the orders DID (`docs/issues/archive/039`). `ok: true` says the simulation executed; it does
    # not say the declared book is the held book, and in the run that filed the issue those
    # differed by nine percent of NAV because 3.1% of fills dealt nothing. Pinned rather than
    # `>= 0`, which a run that placed no orders would also satisfy.
    #
    # Two orders across the run: the first buys the single instrument, the second asks for no
    # change and the venue answers `no_trade`. Both are visible now; before this, the envelope
    # reported neither.
    assert strategy["fills"] == {
        "orders": 2,
        "dealt": 1,
        "partial": 0,
        "zero_dealt": 1,
        "reasons": {"no_trade": 1},
        "never_filled": [],
    }


def test_show_strategy_reads_back_the_tables_a_run_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`RunRecorder` writes evidence tables on every run and nothing could read one back.

    `show run` reported each table's row count and formation count, so a reader could learn that
    `vqapr.fill` held 64 rows and had no way to see one. The only route was knowing the on-disk
    layout and opening the `.jsonl` by hand -- the same class of gap `list instruments` closed for
    the roster sidecar, and the reason the first-time-user journeys ended up reading package
    internals to answer questions the CLI was supposed to answer.

    The tables belong to the strategy since record 139, so `show strategy <run>/<strategy>` is
    the reader; `show run <id> --table` on such a run points there instead of guessing.
    """
    _workspace_for_run(tmp_path, capsys)
    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "r1")
    assert code == 0, ran

    code, record = _cli(
        capsys, "--project-root", str(tmp_path), "show", "strategy", "r1/my-alpha"
    )
    assert code == 0, record
    assert record["stage"] == "strategy.show"
    recorded = sorted(record["tables"])
    # `decisions` is the scaffold's own table (record `267`), read back the same way.
    assert recorded == ["decisions", "vqapr.account", "vqapr.fill", "vqapr.weight"]

    for table in recorded:
        code, page = _cli(
            capsys, "--project-root", str(tmp_path), "show", "strategy", "r1/my-alpha",
            "--table", table,
        )
        assert code == 0, page
        assert page["stage"] == "strategy.table"
        assert page["table"] == table
        # The record's own count for this table is what the readback must agree with, or one of
        # the two is lying about the same run.
        assert page["rows_total"] == record["tables"][table]["rows"]
        assert page["returned"] == len(page["items"])
        assert page["items"], f"{table} was counted in the record and read back empty"

    # `vqapr.fill` is the table the cost questions are asked of, so its columns are pinned.
    code, fills = _cli(
        capsys, "--project-root", str(tmp_path), "show", "strategy", "r1/my-alpha",
        "--table", "vqapr.fill",
    )
    assert {"instrument", "kind", "dealt_quantity", "price", "commission", "tax"} <= set(
        fills["items"][0]
    )

    # Truncation reports both numbers. Returning only `len(items)` would let a reader conclude the
    # run wrote one row when it wrote five.
    code, page = _cli(
        capsys, "--project-root", str(tmp_path), "show", "strategy", "r1/my-alpha",
        "--table", "vqapr.account", "--limit", "1",
    )
    assert code == 0, page
    assert page["returned"] == 1 and page["rows_total"] > 1

    # The run's own view no longer holds tables; asking it for one names where they went.
    code, redirected = _cli(
        capsys, "--project-root", str(tmp_path), "show", "run", "r1", "--table", "vqapr.fill"
    )
    assert code == 1
    assert redirected["stage"] != "unhandled"
    assert "show strategy" in redirected["failures"][0]["fix"]

    # A mistyped table names the ones this run actually recorded, the way a mistyped run id does.
    code, refused = _cli(
        capsys, "--project-root", str(tmp_path), "show", "strategy", "r1/my-alpha",
        "--table", "vqapr.fils",
    )
    assert code == 1
    assert refused["stage"] != "unhandled"
    assert "vqapr.fill" in refused["failures"][0]["observed"]

    # A damaged chunk is reported, never skipped. Skipping would return a short table that looks
    # complete, and a reader comparing it against the record's own count would find two numbers
    # disagreeing with no reason given.
    ref = _strategy_ref(tmp_path, capsys, "r1")
    (part,) = (
        tmp_path / ".vqapr" / "runs" / "r1" / "strategies" / ref / "tables" / "vqapr.fill"
    ).glob("*.parquet")
    part.write_bytes(part.read_bytes()[: part.stat().st_size // 2])
    code, damaged = _cli(
        capsys, "--project-root", str(tmp_path), "show", "strategy", f"r1/{ref}",
        "--table", "vqapr.fill",
    )
    assert code == 1
    assert damaged["stage"] != "unhandled", "a damaged chunk is an answer, not a crash"
    assert "parquet" in damaged["failures"][0]["observed"], "the refusal must name the bad file"


def test_an_empty_recorded_table_reads_back_as_empty_not_as_broken(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A run may record a table and write nothing to it, and that is not damage.

    Pinned separately from the corrupt-row case because the two look alike from the reader's side
    and must not be conflated: one is a legal outcome and the other is a file that was edited.
    """
    _workspace_for_run(tmp_path, capsys)
    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "r1")
    assert code == 0, ran
    ref = _strategy_ref(tmp_path, capsys, "r1")

    # A table directory with no chunk in it: recorded, and holding nothing (record `146`).
    (tmp_path / ".vqapr" / "runs" / "r1" / "strategies" / ref / "tables" / "vqapr.blank").mkdir()

    code, page = _cli(
        capsys, "--project-root", str(tmp_path), "show", "strategy", f"r1/{ref}",
        "--table", "vqapr.blank",
    )
    assert code == 0, page
    assert page["rows_total"] == 0 and page["items"] == []


def test_show_dataset_reads_back_what_a_dataset_holds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`list datasets` proves a registration; nothing could read a row.

    A first-time-user journey materialized a DataModel, wanted to see what it had computed, and
    had to build a SECOND complete run -- execution input, exchange, strategy, agendas, spec --
    purely to observe the values, then fell back to opening the parquet by hand anyway.

    The same gap `show run --table` closed one artifact over, and the same answer.
    """
    _workspace_for_run(tmp_path, capsys)

    code, shown = _cli(
        capsys, "--project-root", str(tmp_path), "show", "dataset", "prices", "--limit", "2"
    )

    assert code == 0, shown
    assert shown["dataset_id"] == "prices"
    # Two numbers, for the same reason the table readback reports two: a page reporting only what
    # it returned would let a reader conclude the dataset holds two rows.
    assert shown["returned"] == 2 and shown["rows_total"] == 3
    assert len(shown["items"]) == 2
    assert "close" in shown["items"][0], "the declared field must be present in the rows"
    # The registration's own facts come back with the rows, so one call answers both what this
    # dataset IS and what it holds.
    assert shown["fields"] == {"close": "close"}
    assert shown["span"] is not None

    code, everything = _cli(
        capsys, "--project-root", str(tmp_path), "show", "dataset", "prices", "--limit", "0"
    )
    # A count is a count: 0 rows, and the registration's facts. It used to mean "every row", which
    # on a 430 MB source read 8.7 million rows into memory before answering
    # (`docs/issues/report-2026-09-10-show-dataset-limit-zero-does-not-return-on-a-large-source`).
    assert everything["returned"] == 0 and everything["items"] == []
    assert everything["rows_total"] == 3 and everything["span"] is not None

    code, refused = _cli(capsys, "--project-root", str(tmp_path), "show", "dataset", "nope")
    assert code == 1
    assert refused["stage"] != "unhandled"
    assert "prices" in refused["failures"][0]["observed"], "the refusal names what is registered"


def test_show_dataset_shows_the_declared_projection_not_the_source_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`items` holds the declared fields with the values a model receives (`docs/issues/093`).

    The one registration whose fields are aggregate expressions is the one carrying the whole
    reduction rule, and it is exactly there that a source-file head confirms nothing: nine columns
    the dataset does not expose, none of the nine it does, on rows the projection filters out. The
    response's own `fields`, `field_types` and `aggregated` describe the projection, so `items` must
    too -- and `--source` is the explicit way to ask for the file's rows, with `items_are` saying
    which was answered either way.
    """
    _workspace_for_run(tmp_path, capsys)
    observation = tmp_path / "observation.parquet"
    grouped = tmp_path / "grouped.yaml"
    grouped.write_text(
        f"""
datasets:
  prices-high:
    source_id: price-source-grouped
    path: {observation.as_posix()}
    instrument_field: instrument
    available_at: available_at
    grain: instrument_instant
    key_fields: [available_at, instrument]
    fields: {{high: "max(close)"}}
    field_types: {{high: DOUBLE}}
""",
        encoding="utf-8",
    )
    code, registered = _cli(capsys, "--project-root", str(tmp_path), "register", str(grouped))
    assert code == 0, registered

    code, shown = _cli(
        capsys, "--project-root", str(tmp_path), "show", "dataset", "prices-high", "--limit", "2"
    )
    assert code == 0, shown
    assert shown["aggregated"] is True and shown["items_are"] == "projection"
    assert set(shown["items"][0]) == {"available_at", "instrument", "high"}, (
        "the declared fields and the identity columns, nothing the file happens to hold"
    )
    assert "session_date" not in shown["items"][0] and "close" not in shown["items"][0]
    assert shown["returned"] == 2 and shown["rows_total"] == 3 == shown["source_rows_total"]
    assert {row["high"] for row in shown["items"]} <= {100.0, 101.0, 104.0}

    code, raw = _cli(
        capsys, "--project-root", str(tmp_path), "show", "dataset", "prices-high",
        "--limit", "2", "--source",
    )
    assert code == 0, raw
    assert raw["items_are"] == "source"
    assert {"session_date", "close"} <= set(raw["items"][0]), "the file's own columns"
    assert "high" not in raw["items"][0]
    assert raw["rows_total"] == raw["source_rows_total"] == 3

    # An identity projection reads the same either way, so nothing that worked before changes.
    code, identity = _cli(capsys, "--project-root", str(tmp_path), "show", "dataset", "prices")
    assert identity["items_are"] == "projection"
    assert set(identity["items"][0]) == {"available_at", "instrument", "close"}


def test_show_model_describes_a_datamodel_and_not_only_a_strategy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both authored kinds declare the same things, so both are describable.

    `show model` loaded only a StrategyModel and refused a DataModel with a message about the
    wrong kind, so the one component whose whole job is to derive a column could be scaffolded and
    registered and never described. A first-time-user journey reported that as a blocker while
    trying to work out what a DataModel is for -- with `show model` refusing and the skill silent,
    the surface offered no way to find out.
    """
    _workspace_for_run(tmp_path, capsys)
    code, emitted = _cli(
        capsys, "--project-root", str(tmp_path), "new", "datamodel", "derived",
        "--dataset", "prices", "--lookback", "1",
    )
    assert code == 0, emitted
    _cli(capsys, "--project-root", str(tmp_path), "register", emitted["declaration"])

    # And a compliance rule, which fell through to the StrategyModel loader and raised a bare
    # TypeError as `stage: "unhandled"` -- so the component a reader most needs to inspect before
    # trusting it could not be inspected at all.
    code, cap = _cli(capsys, "--project-root", str(tmp_path), "new", "compliance", "cap20")
    _cli(capsys, "--project-root", str(tmp_path), "register", cap["declaration"])
    code, rule = _cli(capsys, "--project-root", str(tmp_path), "show", "model", "cap20")
    assert code == 0, rule
    assert rule["kind"] == "compliance"
    assert rule["compliance_id"] == "cap20"
    assert "book" in rule["decides"], "what a rule decides is stated, not left blank"

    code, described = _cli(capsys, "--project-root", str(tmp_path), "show", "model", "derived")

    assert code == 0, described
    assert described["component_id"] == "derived"
    # Spelled the way `new` and `register` accept it. It reported the domain enum's `data_model`,
    # which is a string a reader cannot type at any verb -- one spelling in, another out.
    assert described["kind"] == "datamodel"
    code, listed = _cli(capsys, "--project-root", str(tmp_path), "list", "components")
    assert {row["component_id"]: row["kind"] for row in listed["items"]}["derived"] == "datamodel"
    assert all(
        row["kind"] in {"strategy", "datamodel", "compliance", "exchange"}
        for row in listed["items"]
    ), "every reported kind must be one the CLI accepts, or the enum value where it takes none"
    # What it reads is the question a reader opens this command to answer.
    assert described["decides"] == ["prices"]


def test_a_yaml_path_handed_to_run_or_check_is_refused_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The spec file is retired (record 148); a path is refused before it is opened.

    `vqapr run <spec.yaml>` was the one door a DataModel went through, with its own `check`
    phases, its own nine judgment codes and its own success envelope. A datamodel is a `runs:`
    entry with `datamodels:` now, so `run` and `check` take the id of a registered run and
    nothing else. A YAML path is refused by NAME rather than parsed: the only honest reply to a
    reader following stale notes is where the shape went -- declare, register, run by id -- and
    `vqapr new datamodel` emits the block they need.

    A path that does not exist is refused identically, which is what proves the refusal is about
    the argument's shape and not about what the file says. The datamodel run itself is proven in
    `test_a_datamodel_run_through_the_cli.py`.
    """
    _workspace_for_run(tmp_path, capsys)
    _, before = _cli(capsys, "--project-root", str(tmp_path), "list", "datasets")

    spec = tmp_path / "materialize.yaml"
    spec.write_text(
        json.dumps(
            {
                "datamodel": "derived",
                "instruments": ["A"],
                "output": {"dataset_id": "derived-values", "value_fields": ["value"]},
                "evaluate_at": ["2024-03-06T04:00:00+09:00"],
            }
        ),
        encoding="utf-8",
    )

    for verb in ("run", "check"):
        for target in (spec, tmp_path / "never-written.yml"):
            code, refused = _cli(capsys, "--project-root", str(tmp_path), verb, str(target))

            assert code == 1, refused
            assert refused["stage"] == "usage"
            detail = refused["failures"][0]
            assert detail["code"] == "argument.value_invalid"
            assert detail["requirement"] == f"`vqapr {verb}` takes the id of a registered run"
            assert target.name in detail["observed"]
            for command in (f"vqapr register {target}", f"vqapr {verb} <run-id>"):
                assert command in detail["fix"], f"the fix does not name {command}"
            assert "datamodels:" in detail["fix"], "the fix says where the spec's shape went"
            assert detail["source"]["file"] == str(target)

    # Refused by name means never executed: nothing registered, nothing materialized.
    _, after = _cli(capsys, "--project-root", str(tmp_path), "list", "datasets")
    assert after == before
    assert not (tmp_path / ".vqapr" / "materialized").exists()


def test_new_compliance_emits_a_rule_that_registers_and_runs_unedited(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The run spec advertised `compliance:` and nothing said what went in it.

    The observing role had no scaffold, `register --help` named only datamodel and strategy, and
    the skill never mentioned it. The only way to learn the shapes was to register an empty
    subclass and read the `TypeError`.
    """
    _workspace_for_run(tmp_path, capsys)

    # No --dataset: a rule about the book reads nothing. Requiring one would make an author
    # invent a dataset to scaffold a rule that never opens it.
    code, emitted = _cli(capsys, "--project-root", str(tmp_path), "new", "compliance", "cap20")
    assert code == 0, emitted
    assert emitted["object_name"] == "Cap20"

    source = Path(emitted["path"]).read_text(encoding="utf-8")
    for member in ("compliance_id", "inputs", "observe"):
        assert f"def {member}" in source, f"{member} must be present, not left to a TypeError"
    # The template states what a rule is: an observer, not a gate and not a box.
    assert "A rule observes" in source

    code, registered = _cli(
        capsys, "--project-root", str(tmp_path), "register", emitted["declaration"]
    )
    assert code == 0, registered
    assert registered["registered"]["components"] == ["cap20"]

    # The scaffold cannot reproduce the crash T1 fixed: its `compliance_id` is fixed to the id it
    # was scaffolded under, so registering it as anything else is refused rather than crashing at
    # run assembly.
    code, mismatched = _cli(
        capsys, "--project-root", str(tmp_path), "register", "compliance", "cap20b",
        emitted["path"],
    )
    assert code == 1
    assert mismatched["failures"][0]["code"] == "component.compliance_id_mismatch"

    # The rule BITES, and the run FINISHES. This workspace holds one instrument, so the scaffold
    # strategy proposes 100% of the book in it, which a 20% cap reports.
    #
    # A breach never ends the run: whether a limit held is a question about the committed account,
    # which Compliance answers on the market clock (PRD 7.1, design §7.2). Stopping would hide
    # what the strategy went on to do, and could never see the breach that only appears once
    # whole shares are filled.
    code, registered_run = _register_run(tmp_path, capsys, "capped", compliance=["cap20"])
    assert code == 0, registered_run
    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "capped")
    assert code == 0, ran
    assert ran["ok"] is True

    # And the breach is IN THE RECORD, named. The block that carries it reported `{}` for every
    # run ever written until `docs/issues/archive/051`, so this asserts its content and not its presence.
    code, shown = _cli(
        capsys, "--project-root", str(tmp_path), "show", "strategy", "capped/my-alpha",
    )
    assert code == 0, shown
    assert [entry["component_id"] for entry in shown["compliance"]] == ["cap20"], (
        "the strategy record names the compliance rules the run declared"
    )
    contract = shown["contract"]
    assert "cap20" in contract, f"the record names which rule observed: {contract}"
    entry = contract["cap20"]
    assert entry["checked"] > 0, "a rule nobody checked proves nothing"
    assert entry["ok"] is False, "the book breached the cap, and the record says so"
    assert entry["held"] < entry["checked"]

    # And it PERMITS. `--cap` is the marked place to change, exposed as a flag the way `--lookback`
    # is for a strategy, so the same scaffold runs clean where the book satisfies it. Without this
    # half, a rule that reported everything would pass the assertion above just as well.
    code, wide = _cli(
        capsys, "--project-root", str(tmp_path), "new", "compliance", "cap-any", "--cap", "1.0"
    )
    assert code == 0, wide
    code, registered_wide = _cli(
        capsys, "--project-root", str(tmp_path), "register", wide["declaration"]
    )
    assert code == 0, registered_wide

    code, registered_run = _register_run(tmp_path, capsys, "uncapped", compliance=["cap-any"])
    assert code == 0, registered_run
    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "uncapped")
    assert code == 0, ran
    assert ran["ok"] is True and ran["stage"] == "run.complete"


def test_list_instruments_answers_without_opening_the_sidecar_by_hand(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`list` covered eight kinds and not the roster, so a registered one was uninspectable.

    Both first-time-user journeys ended up reading `.vqapr/instruments.json` directly, which is a
    file this surface should never require a reader to know about.

    Empty is an answer, not a failure: `list` is the command an agent runs first to orient itself,
    and a project with no roster is an ordinary state.
    """
    from vqapr.domain.instrument import export_roster

    # Before a workspace exists at all, and after one exists with no roster. Both are zero.
    code, empty = _cli(capsys, "--project-root", str(tmp_path), "list", "instruments")
    assert code == 0, empty
    assert empty["count"] == 0 and empty["items"] == []

    _workspace_for_run(tmp_path, capsys, roster=False)
    code, still_empty = _cli(capsys, "--project-root", str(tmp_path), "list", "instruments")
    assert code == 0 and still_empty["count"] == 0

    written = export_roster(
        {"A005930": "stock", "A000660": "stock", "A069500": "etf"}, tmp_path / "roster"
    )
    declaration = tmp_path / "roster.yaml"
    declaration.write_text(
        "instruments:\n  tables:\n"
        + "".join(
            f"    {kind}: {path.relative_to(tmp_path).as_posix()}\n"
            for kind, path in sorted(written.items())
        ),
        encoding="utf-8",
    )
    code, registered = _cli(capsys, "--project-root", str(tmp_path), "register", str(declaration))
    assert code == 0, registered

    code, listed = _cli(capsys, "--project-root", str(tmp_path), "list", "instruments")

    assert code == 0, listed
    # One roster, so one row. How many instruments it describes is a different question and has
    # its own field rather than overloading `count`.
    assert listed["count"] == 1
    row = listed["items"][0]
    assert row["digest"] == registered["registered"]["instruments"][0]["digest"]
    assert row["by_kind"] == {"stock": 2, "etf": 1}
    assert row["instruments"] == 3
    assert sorted(row["tables"]) == ["etf", "stock"]

    # A table that moved after registration must not turn orientation into a failure: the pointer
    # is still reportable, and the read that could not happen says so.
    for path in written.values():
        path.unlink()
    code, degraded = _cli(capsys, "--project-root", str(tmp_path), "list", "instruments")
    assert code == 0, degraded
    assert degraded["count"] == 1
    assert degraded["items"][0]["digest"] == row["digest"]
    assert "unreadable" in degraded["items"][0]
    assert "by_kind" not in degraded["items"][0], "a count that could not be read is not reported"


def test_a_run_says_whether_it_knew_what_its_instruments_were(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A strategy run over a project that declared no instrument is refused before it freezes.

    It used to complete with every fill `kind: None` and say so on the success path. Design §6.3
    turned that into a precondition: the venue must know what every ordered id IS, and zero
    declarations means no order can succeed, so `check` and `run` both refuse `roster.absent`
    and name the two commands that declare one. Once a roster is registered the run completes
    and the envelope and the frozen record both state which roster it read.
    """
    import json as _json

    from vqapr.record import read_strategy_record

    _workspace_for_run(tmp_path, capsys, roster=False)
    store = tmp_path / ".vqapr"
    code, registered_run = _register_run(tmp_path, capsys, "categorised")
    assert code == 0, registered_run

    code, judged = _cli(capsys, "--project-root", str(tmp_path), "check", "categorised")
    assert code == 1, judged
    codes = [failure["code"] for failure in judged["failures"]]
    # Once by the judge, once by the freeze (record `171`): one fact, two doors.
    assert codes.count("roster.absent") == 2, codes
    assert all(failure["status"] == 412 for failure in judged["failures"]), judged["failures"]
    assert "vqapr register" in judged["failures"][0]["fix"]

    code, refused = _cli(capsys, "--project-root", str(tmp_path), "run", "categorised")
    assert code == 1, refused
    assert refused["ok"] is False
    assert "roster.absent" in {failure["code"] for failure in refused["failures"]}
    assert not (store / "runs" / "categorised").exists(), "refused before anything was written"

    registered = _register_roster(tmp_path, capsys, {"A": "stock"})
    digest = registered["registered"]["instruments"][0]["digest"]

    code, with_roster = _cli(capsys, "--project-root", str(tmp_path), "run", "categorised")

    assert code == 0, with_roster
    assert with_roster["roster"]["known"] is True
    assert with_roster["roster"]["digest"] == digest
    assert with_roster["roster"]["by_kind"] == {"stock": 1}
    # The frozen record carries the same facts, so a later reader gets them without the envelope.
    frozen = read_strategy_record(
        store, "categorised", _strategy_ref(tmp_path, capsys, "categorised")
    )
    assert frozen["roster"]["digest"] == digest
    assert frozen["roster"]["by_kind"] == {"stock": 1}
    assert _json.dumps(frozen)  # the record must stay JSON-serialisable


def test_one_run_command_opens_the_workspace_document_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`docs/issues/archive/070`: `run` opened `workspace.yaml` four times -- to look the definition
    up, again inside preflight, again for the roster at run start, and again for the envelope's
    roster after the run. Four reads of a file other commands write is four chances to judge
    one document and freeze another. One open, and everything else is handed that snapshot."""
    from vqapr.workspace.registry import Workspace

    _workspace_for_run(tmp_path, capsys)
    code, registered_run = _register_run(tmp_path, capsys, "once")
    assert code == 0, registered_run

    opened: list[Path] = []
    original = Workspace.open

    def counted(root: str | Path) -> Workspace:
        opened.append(Path(root))
        return original(root)

    monkeypatch.setattr(Workspace, "open", staticmethod(counted))
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "run", "once")

    assert code == 0, payload
    assert len(opened) == 1, f"`run` opened the workspace {len(opened)} times: {opened}"
    assert payload["roster"]["known"] is True, "the envelope's roster came from the run's read"


def test_a_run_says_where_its_time_went(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`docs/issues/archive/068`: a per-phase timing block in the record and the envelope.

    The testbed's agent needed cProfile to learn that its strategy was 5% of the wall clock and
    two execution snapshots were half of it. The record now says so: `total` for the loop,
    `callback` for the model's side, `due` for the fill's, and every due stage by its name.
    """
    from vqapr.record import read_strategy_record

    _workspace_for_run(tmp_path, capsys)
    code, registered_run = _register_run(tmp_path, capsys, "timed")
    assert code == 0, registered_run

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "run", "timed")
    assert code == 0, payload
    (strategy,) = payload["strategies"].values()
    timing = strategy["timing"]

    assert {"total", "callback", "due", "simulation.due.snapshot"} <= set(timing), timing
    assert all(isinstance(seconds, float) and seconds >= 0 for seconds in timing.values())
    assert timing["callback"] + timing["due"] <= timing["total"] + 1e-6
    due_stages = sum(seconds for phase, seconds in timing.items() if phase.startswith("simulation."))
    assert due_stages <= timing["due"] + 1e-6, "the due stages are parts of the due side"
    ref = _strategy_ref(tmp_path, capsys, "timed")
    assert read_strategy_record(tmp_path / ".vqapr", "timed", ref)["timing"] == timing


def test_a_rule_that_slipped_past_registration_is_refused_by_check_not_by_a_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reported crash, driven through the two verbs a user actually types.

    `check` used to return `ok:true` on all five phases and `run` then died inside
    `strategy_loop` with `stage:"unhandled"`, `failures:[]` and a raw traceback.

    `vqapr register` now refuses the mismatch outright, so the workspace is populated through the
    Python API here on purpose — that is precisely the route the acceptance criterion anticipates
    (*"if registration is permitted for a case (1) does not cover"*), and it is what any caller
    using `Workspace` directly does. The point of the test is that the two CLI verbs still refuse,
    and refuse in the structured shape rather than by crashing.
    """
    from vqapr.component.fingerprint import fingerprint_component
    from vqapr.component.reference import ComponentRef
    from vqapr.domain.wiring import Role
    from vqapr.workspace.registry import Workspace

    _workspace_for_run(tmp_path, capsys)

    source = tmp_path / "mislabelled.py"
    source.write_text(
        "from vqapr.public import Compliance\n"
        "class Limit(Compliance):\n"
        "    @property\n"
        "    def compliance_id(self):\n"
        "        return 'position-cap'\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def observe(self, call):\n"
        "        return None\n",
        encoding="utf-8",
    )
    with Workspace.transaction(tmp_path) as t:
        t.register_component(
            ComponentRef.of(
                "limit",
                Role.COMPLIANCE,
                source,
                "Limit",
                fingerprint=fingerprint_component(
                    source, kind=Role.COMPLIANCE, object_name="Limit"
                ),
            )
        )
    # Registering the run is a reference check only -- `limit` IS a registered rule -- so
    # the mismatch is still the two verbs' to refuse, exactly as before.
    code, registered_run = _register_run(tmp_path, capsys, "limited", compliance=["limit"])
    assert code == 0, registered_run

    code, checked = _cli(capsys, "--project-root", str(tmp_path), "check", "limited")

    assert code == 1, checked
    assert checked["ok"] is False
    assert "component.compliance_id_mismatch" in [
        failure["code"] for failure in checked["failures"]
    ]

    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "limited")

    assert code == 1, ran
    assert ran["ok"] is False
    # The whole point. A bare exception here reaches the envelope as `stage:"unhandled"` with an
    # empty `failures[]`, which tells a user the framework broke when their registration was wrong.
    assert ran["stage"] != "unhandled"
    assert ran["failures"], "a refusal must carry its failures, not an empty list"
    assert "component.compliance_id_mismatch" in [
        failure["code"] for failure in ran["failures"]
    ]


def test_a_rule_registered_under_the_id_it_answers_to_still_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other half of the reported case, which a refusal test alone cannot prove.

    Registering `NoShort` as `noshort` crashed and the identical file as `no-short` ran clean. A
    test that only pins the refusal would pass just as well if the new check refused everything,
    so this carries the accepted spelling all the way through `check` and `run` and asserts the
    counts are the ones the unconstrained run produces.
    """
    from vqapr.component.compliance.shipped import shipped_compliance_path

    _workspace_for_run(tmp_path, capsys)

    declaration = tmp_path / "compliance.yaml"
    declaration.write_text(
        "components:\n  no-short:\n    kind: compliance\n"
        f"    path: {shipped_compliance_path('no_short').as_posix()}\n"
        "    object_name: NoShort\n",
        encoding="utf-8",
    )
    code, registered = _cli(capsys, "--project-root", str(tmp_path), "register", str(declaration))
    assert code == 0, registered
    assert registered["registered"]["components"] == ["no-short"]

    # `ok:true` outright, which this test could not assert until issue 012 was closed: the fixture
    # spec used to fail `check` on `lookback.uncovered` while `run` completed it, so this
    # compared against the unconstrained spec's failures instead and said so. The judgment now
    # measures at the first decision rather than at `start`, the two verbs agree, and the weaker
    # comparison is gone with the defect it worked around.
    code, registered_run = _register_run(tmp_path, capsys, "no-short-run", compliance=["no-short"])
    assert code == 0, registered_run

    code, checked = _cli(capsys, "--project-root", str(tmp_path), "check", "no-short-run")
    assert code == 0, checked
    assert checked["ok"] is True, (
        "naming a correctly-registered rule must add no refusal of its own"
    )
    assert checked.get("failures", []) == []
    assert checked["blocked"] == []
    assert checked["passed"] == checked["checked"], "every phase answered, none skipped"
    # `ok:true` with no failures already says the mismatch refusal did not fire; asserting its
    # absence separately would restate the line above.

    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "no-short-run")
    assert code == 0, ran
    assert ran["ok"] is True
    assert ran["stage"] == "run.complete"
    # Identical to the unconstrained end-to-end run above: a long-only strategy never proposes a
    # short, so no-short binds nothing and must change no number. A different count here would
    # mean the rule altered the book rather than merely observing it.
    strategy = ran["strategies"]["my-alpha"]
    assert strategy["occurrences"] == OCCURRENCES
    assert strategy["account_version"] == 2


def test_register_refuses_a_date_boundary_as_a_structured_declaration_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The old template promised dates, then preflight crashed on the naive datetime.

    A run is a registered declaration since record 139, so the refusal moves one verb earlier:
    `register` refuses the bare date, and neither `check` nor `run` can ever see such a run. That
    is still one defect with one name, which is the point -- a reader is told once, at the first
    command that reads the value, rather than by a crash two commands later.

    What must NOT change is how much the reader is told. The refusal names the missing offset and
    points at the well-formed shape (`vqapr new run`), exactly as `_timestamp` did -- parity that
    cost a diagnostic would be a bad trade.
    """
    _workspace_for_run(tmp_path, capsys)

    code, payload = _register_run(
        tmp_path, capsys, "dated", start="2024-03-05", end="2024-03-07"
    )

    assert code == 1
    assert payload["stage"] != "unhandled"
    failure = payload["failures"][0]
    assert failure["code"] == "declaration.run_invalid"
    assert "UTC offset" in failure["observed"]
    assert "vqapr new run" in failure["requirement"]
    assert failure["source"]["key_path"] == "runs.dated"

    # And nothing was registered under that id, so the two run verbs report it as unknown rather
    # than judging a half-declared run.
    code, listed = _cli(capsys, "--project-root", str(tmp_path), "list", "runs")
    assert code == 0, listed
    assert "dated" not in [row["run_id"] for row in listed["items"]]


def test_an_incomplete_run_declaration_names_every_key_a_run_declares(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A `runs:` entry carrying only part of what a run declares cannot be registered.

    The shape refusal names every key a run declares, so an agent gets the whole list in one
    reply instead of discovering the keys one exception at a time -- and it names the command
    that emits the shape, which is where the list came from.
    """
    _workspace_for_run(tmp_path, capsys)
    thin = tmp_path / "thin.yaml"
    thin.write_text(
        json.dumps(
            {
                "runs": {
                    "thin": {
                        "timezone": "Asia/Seoul",
                        "instruments": ["A"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", str(thin))

    assert code == 1
    assert payload["stage"] != "unhandled"
    failure = payload["failures"][0]
    assert failure["code"] == "declaration.run_invalid"
    for key in (
        "writes", "strategy", "instruments", "start", "end", "exchange",
        "execution", "initial_account",
    ):
        assert key in failure["requirement"], f"{key} was not named: {failure['requirement']}"
    # `writes` is declared before `at` on the model, so it is the first key pydantic names;
    # what the assertion pins is that SOME missing key is named, not which comes first.
    assert "writes" in failure["observed"], "a key that stopped the read is named"
    assert "vqapr new run" in failure["requirement"]


def test_a_rejected_command_line_still_answers_in_the_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """argparse's own exit path bypassed stdout entirely.

    The agent's only parsing contract is one JSON line, so a mistyped command that answered with
    an empty stdout and a bare exit code was the single shape it could not read.
    """
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "new", "bogus", "x")

    assert code == 1
    assert payload["ok"] is False
    assert payload["stage"] == "usage"
    assert payload["failures"][0]["code"] == "usage.rejected"
    # argparse's wording rides verbatim; the CLI does not invent a second remedy text.
    assert "invalid choice" in payload["failures"][0]["requirement"]
    assert "datamodel" in payload["failures"][0]["requirement"]
    # What was refused is the line as typed, not the program's name (record `250`).
    assert "new bogus x" in payload["failures"][0]["observed"]


def test_an_unrecognized_argument_is_refused_by_the_command_it_followed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`docs/issues/report-2026-09-11-a-usage-refusal-names-only-vqapr-help-...` (record `250`).

    argparse raises an unrecognized argument from the TOP-level parser, so the refusal said
    "run `vqapr --help`" -- a page that lists no subcommand's arguments -- and `observed` was the
    program name. Five agents met it; two wrote down opposite rules. The refusal now names the
    subcommand's own form, and the tokens nobody accepted.
    """
    target = tmp_path / "i.yaml"
    code, payload = _cli(
        capsys,
        "--project-root", str(tmp_path),
        "new", "instruments", "A000020", "A000030", "--out", str(target),
    )

    assert code == 1
    (failure,) = payload["failures"]
    assert failure["code"] == "usage.rejected"
    assert failure["observed"] == "A000030"
    assert "`vqapr new --help`" in failure["fix"]
    assert "--instruments" in failure["fix"], "the fix carries the form the command accepts"
    assert not target.exists()

    _, shown = _cli(
        capsys,
        "--project-root", str(tmp_path),
        "show", "strategy", "sample-run", "--strategy", "sample-reversal-5d",
    )
    (refused,) = shown["failures"]
    assert refused["observed"] == "--strategy sample-reversal-5d"
    assert "`vqapr show --help`" in refused["fix"]


def test_a_usage_refusal_is_a_400_at_the_usage_stage_with_no_dump(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command line is the submission, and it is what must change (record `171`)."""
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "list", "nonsense")

    assert code == 1
    assert payload["stage"] == "usage"
    assert payload["failures"][0]["status"] == 400
    assert payload["failures"][0]["cause"]["where"], "even a usage refusal names its line"
    assert payload["mutation"] is False
    # No traceback and no dump: the command line is the whole evidence.
    assert "traceback" not in payload
    assert "detail" not in payload


def test_an_unknown_command_does_not_escape_as_a_bare_exit_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, payload = _cli(capsys, "definitely-not-a-command")

    assert code == 1
    assert payload["stage"] == "usage"


def test_help_keeps_argparses_own_behaviour(capsys: pytest.CaptureFixture[str]) -> None:
    """Only failure is rerouted. `--help` still exits zero through argparse."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    assert "usage: vqapr" in capsys.readouterr().out


def test_one_run_records_one_clock(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`docs/issues/archive/058`: the fill table's `event_time` is in the run's zone like every other.

    The execution table normalises its target to UTC and the fill row used to carry that, so a
    reader lining a fill up against the NAV row written at that same instant converted by hand.
    """
    from vqapr.record import read_table

    _workspace_for_run(tmp_path, capsys)
    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "r1")
    assert code == 0, ran
    ref = _strategy_ref(tmp_path, capsys, "r1")
    store = tmp_path / ".vqapr"

    offsets = {
        table: {row["event_time"].utcoffset() for row in read_table(store, "r1", table, ref)}
        for table in ("vqapr.fill", "vqapr.account", "vqapr.weight")
    }
    assert all(offsets.values()), offsets
    assert len({offset for found in offsets.values() for offset in found}) == 1, offsets


_NEVER_READY = '''
from vqapr.authoring import DatasetInput, RowsLookback, StrategyModel


class {object_name}(StrategyModel):
    def inputs(self):
        return {{"prices": DatasetInput(dataset_id="prices", fields=("close",),
                                       lookback=RowsLookback(rows=2))}}

    def decide(self, call):
        raise ValueError("the signal is not ready")
'''


def test_a_run_names_every_strategy_it_ran_when_one_of_them_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`docs/issues/archive/073`: the envelope of a run with one failed strategy used to be that
    strategy's refusal alone -- or, under `--jobs`, `stage: unhandled` with `failures: []` --
    and said nothing about the strategies that completed. It now has the same `strategies` map
    as a green run, with a `status` per strategy, and the failed one's block is the refusal.
    `docs/issues/archive/071`: the refusal names its strategy, its file and its line."""
    _workspace_for_run(tmp_path, capsys)
    code, scaffold = _cli(
        capsys, "--project-root", str(tmp_path), "new", "strategy", "never-ready",
        "--dataset", "prices", "--lookback", "2",
    )
    assert code == 0, scaffold
    Path(scaffold["path"]).write_text(
        _NEVER_READY.format(object_name=scaffold["object_name"]), encoding="utf-8"
    )
    code, registered = _cli(
        capsys, "--project-root", str(tmp_path), "register", scaffold["declaration"]
    )
    assert code == 0, registered
    code, payload = _register_run(tmp_path, capsys, "good", strategies={"my-alpha": {}})
    assert code == 0, payload
    code, payload = _register_run(tmp_path, capsys, "bad", strategies={"never-ready": {}})
    assert code == 0, payload

    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "bad")

    assert code == 1 and ran["ok"] is False
    assert ran["stage"] == "run.strategy_failed"
    assert "family" not in ran, "record 171: stage and status replaced family"
    assert ran["run_id"] == "bad" and ran["store_root"]
    failed = ran["strategies"]["never-ready"]
    assert failed["status"] == "failed"
    assert failed["stage"] == "simulation.callback.intent"
    assert failed["component_id"] == "never-ready"
    assert failed["at"]["clock"], "the replay coordinates ride with the strategy's block"
    (entry,) = ran["failures"]
    assert entry["strategy"] == "never-ready"
    assert entry["code"] == "strategy.callback.intent"
    assert entry["status"] == 502, "the author's own decide() raised: theirs to fix"
    assert entry["cause"]["type"] == "ValueError"
    assert "the signal is not ready" in entry["cause"]["traceback"]
    assert entry["observed"] == "the signal is not ready"
    assert entry["source"]["key_path"] == "strategies.never-ready"
    assert entry["source"]["file"].endswith(".py") and isinstance(entry["source"]["line"], int)
    assert "read `observed`" in entry["fix"]

    # A run holds one model since 2026-09-09, so "named beside the one that did not" is now a
    # property of naming several RUNS: one refusal is that run's entry and the other still runs.
    code, both = _cli(capsys, "--project-root", str(tmp_path), "run", "good", "bad")

    assert code == 1 and both["ok"] is False
    assert set(both["runs"]) == {"good", "bad"}
    assert both["runs"]["good"]["ok"] is True
    assert both["runs"]["good"]["strategies"]["my-alpha"]["record"].startswith("my-alpha@")
    assert both["runs"]["bad"]["ok"] is False

    # The record store agrees: the good run left a record, the refused one left none.
    code, listed = _cli(
        capsys, "--project-root", str(tmp_path), "list", "strategies", "--run", "good"
    )
    assert code == 0
    assert {row["strategy_id"]: row["status"] for row in listed["items"]} == {
        "my-alpha": "completed"
    }
    code, refused = _cli(
        capsys, "--project-root", str(tmp_path), "list", "strategies", "--run", "bad"
    )
    assert code == 0
    assert {row["strategy_id"]: row["status"] for row in refused["items"]} == {
        "never-ready": "unfinished"
    }, "the failed strategy's directory is listed too (074): rows, no record, lock released"
