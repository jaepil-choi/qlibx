"""The CLI is the surface a first-time user actually types, so it is driven here as typed.

`test_envelope.py` covers the envelope's shape and asserts the parser *mentions* every command.
Mentioning is not running: before this file, no test invoked `new`, `register`, `list` or `run`,
so the whole `spec.yaml -> RunDefinition -> preflight_run -> run` path was unexecuted. These tests
call `main(argv)` and read the JSON it emits, which is exactly what an agent gets.

Datasets, sources, agendas, execution inputs and configs are declared through `vqapr declare`,
which is the command that closed that gap. This file previously reached past the CLI into the
library for all seven, under a docstring admitting the CLI could not register them; the workspace
below is now reachable by typing `vqapr` commands only, which is the property that matters.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.cli.main import main
from vqapr.public import (
    LocalInstantDeclaration,
    OperationAgenda,
    OperationOccurrence,
    OperationRole,
)

_ZONE = ZoneInfo("Asia/Seoul")


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    """Run one command exactly as the console script would and parse its one JSON line."""
    code = main(argv)
    out = capsys.readouterr().out.strip()
    return code, json.loads(out.splitlines()[-1])


def _agenda(agenda_id: str, role: OperationRole, at: time) -> OperationAgenda:
    return OperationAgenda.from_occurrences(
        agenda_id=agenda_id,
        role=role,
        timezone="Asia/Seoul",
        occurrences=tuple(
            OperationOccurrence(
                f"{agenda_id}-{day}",
                role,
                LocalInstantDeclaration(date(2024, 3, day), at, "Asia/Seoul", 0, "+09:00"),
            )
            for day in (5, 6, 7)
        ),
        provenance="cli end-to-end fixture",
    )


def _parquets(root: Path) -> tuple[Path, Path]:
    """Observations the Strategy reads, and the venue table the run fills against."""
    observation = root / "observation.parquet"
    execution = root / "execution.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
              (DATE '2024-03-05', TIMESTAMPTZ '2024-03-05 03:00:00+09', 'A', 100.0),
              (DATE '2024-03-06', TIMESTAMPTZ '2024-03-06 03:00:00+09', 'A', 101.0),
              (DATE '2024-03-07', TIMESTAMPTZ '2024-03-07 03:00:00+09', 'A', 104.0)
            ) AS t(session_date, available_at, instrument, close))
            TO '{observation.as_posix()}' (FORMAT PARQUET)"""
        )
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
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
        "from vqapr.exchange.venue import AcademicExchange, TradeRule\n"
        "from vqapr.exchange.listings import ListingAccess\n"
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
    key_fields: [available_at, instrument]
    fields: {{close: close}}

execution_inputs:
  venue-daily:
    table:
      source_id: venue-source
      path: {execution.as_posix()}
      trade_at_field: trade_at
      instrument_field: instrument
      is_tradable_field: is_tradable
      price_fields: {{close: close}}
    fill:
      selector: next_eligible
      at: "15:30"
      timezone: Asia/Seoul
      trade_price: close

agendas:
  alpha:
    role: strategy_callback
    from_dataset: prices
    at: "04:00"
    timezone: Asia/Seoul
  valuing:
    role: valuation
    from_dataset: prices
    at: "16:00"
    timezone: Asia/Seoul
  watching:
    role: monitoring
    from_dataset: prices
    at: "17:00"
    timezone: Asia/Seoul
""",
        encoding="utf-8",
    )
    return path


def _workspace_for_run(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Everything `run` needs, reached through the CLI alone."""
    observation, execution = _parquets(root)

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

    configs = root / "configs.yaml"
    configs.write_text(
        f"""
components:
  venue:
    kind: exchange
    path: {_exchange_component(root).as_posix()}
    object_name: Venue
strategy_configs:
  my-alpha:
    agenda_id: alpha
valuation_configs:
  valuing:
    agenda_id: valuing
monitoring_policies:
  watching:
    agenda_id: watching
""",
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(root), "register", str(configs))
    assert code == 0, payload


def _spec(root: Path, **overrides: object) -> Path:
    document: dict[str, object] = {
        "strategy": {"component": "my-alpha", "agenda_id": "alpha"},
        "valuation": {"agenda_id": "valuing"},
        "monitoring": {"agenda_id": "watching"},
        "exchange": "venue",
        "execution_input": "venue-daily",
        "start": datetime(2024, 3, 5, 0, tzinfo=_ZONE).isoformat(),
        "end": datetime(2024, 3, 7, 23, tzinfo=_ZONE).isoformat(),
        "initial_account": {"cash": "1000", "mode": "long_only"},
        "instruments": ["A"],
    }
    document.update(overrides)
    path = root / "spec.yaml"
    path.write_text(json.dumps(document), encoding="utf-8")  # JSON is a subset of YAML
    return path


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


def test_run_executes_a_declared_spec_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The path the testbed never walked: spec.yaml -> preflight -> a completed run."""
    _workspace_for_run(tmp_path, capsys)

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "run", str(_spec(tmp_path)))

    assert code == 0, payload
    assert payload["ok"] is True
    assert payload["stage"] == "run.complete"
    # Three days x (strategy, valuation, monitoring) plus the execution occurrences the fills
    # land on. Pinned rather than `> 0`, which a run that did nothing would also satisfy.
    assert payload["occurrences"] == 12
    # The scaffold TRADES. It used to hold throughout -- the old template returned NoDecision --
    # and this assertion pinned account_version at zero, which meant the end-to-end test proved a
    # run that never bought anything. The authoring-contract scaffold ranks the cross-section and
    # rebalances, so fills commit and the Account advances, which is the stronger property: it
    # exercises the intent path, the execution path and the account commit rather than skipping
    # all three.
    assert payload["account_version"] == 2
    # The run state advances further than the Account: once per published mark, plus the
    # intents and fills a trading strategy now produces.
    assert payload["run_state_version"] == 14


def test_show_run_reads_back_the_tables_a_run_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`RunRecorder` writes evidence tables on every run and nothing could read one back.

    `show run` reported each table's row count and formation count, so a reader could learn that
    `vqapr.fill` held 64 rows and had no way to see one. The only route was knowing the on-disk
    layout and opening the `.jsonl` by hand -- the same class of gap `list instruments` closed for
    the roster sidecar, and the reason the first-time-user journeys ended up reading package
    internals to answer questions the CLI was supposed to answer.
    """
    _workspace_for_run(tmp_path, capsys)
    code, ran = _cli(
        capsys, "--project-root", str(tmp_path), "run", str(_spec(tmp_path)), "--run-id", "r1"
    )
    assert code == 0, ran

    code, record = _cli(capsys, "--project-root", str(tmp_path), "show", "run", "r1")
    assert code == 0, record
    recorded = sorted(record["tables"])
    assert recorded == ["vqapr.account", "vqapr.fill", "vqapr.weight"]

    for table in recorded:
        code, page = _cli(
            capsys, "--project-root", str(tmp_path), "show", "run", "r1", "--table", table
        )
        assert code == 0, page
        assert page["stage"] == "run.table"
        assert page["table"] == table
        # The record's own count for this table is what the readback must agree with, or one of
        # the two is lying about the same run.
        assert page["rows_total"] == record["tables"][table]["rows"]
        assert page["returned"] == len(page["items"])
        assert page["items"], f"{table} was counted in the record and read back empty"

    # `vqapr.fill` is the table the cost questions are asked of, so its columns are pinned.
    code, fills = _cli(
        capsys, "--project-root", str(tmp_path), "show", "run", "r1", "--table", "vqapr.fill"
    )
    assert {"instrument", "kind", "dealt_quantity", "price", "commission", "tax"} <= set(
        fills["items"][0]
    )

    # Truncation reports both numbers. Returning only `len(items)` would let a reader conclude the
    # run wrote one row when it wrote five.
    code, page = _cli(
        capsys, "--project-root", str(tmp_path), "show", "run", "r1",
        "--table", "vqapr.account", "--limit", "1",
    )
    assert code == 0, page
    assert page["returned"] == 1 and page["rows_total"] > 1

    # A mistyped table names the ones this run actually recorded, the way a mistyped run id does.
    code, refused = _cli(
        capsys, "--project-root", str(tmp_path), "show", "run", "r1", "--table", "vqapr.fils"
    )
    assert code == 1
    assert refused["stage"] != "unhandled"
    assert "vqapr.fill" in refused["failures"][0]["observed"]

    # A damaged row is reported, never skipped. Skipping would return a short table that looks
    # complete, and a reader comparing it against the record's own count would find two numbers
    # disagreeing with no reason given.
    fill_file = tmp_path / ".vqapr" / "runs" / "r1" / "tables" / "vqapr.fill.jsonl"
    fill_file.write_text(fill_file.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    code, damaged = _cli(
        capsys, "--project-root", str(tmp_path), "show", "run", "r1", "--table", "vqapr.fill"
    )
    assert code == 1
    assert damaged["stage"] != "unhandled", "a damaged row is an answer, not a crash"
    assert "line" in damaged["failures"][0]["observed"], "the refusal must locate the bad row"

    # Valid JSON of the wrong shape is damage too: yielding a bare number would break the reader's
    # own `Iterator[dict[str, Any]]` contract and hand every caller something that is not a row.
    for wrong in ("5", "null", '"text"', "[1, 2]"):
        fill_file.write_text(f"{wrong}\n", encoding="utf-8")
        code, typed = _cli(
            capsys, "--project-root", str(tmp_path), "show", "run", "r1", "--table", "vqapr.fill"
        )
        assert code == 1, f"{wrong} is not a row"
        assert typed["stage"] != "unhandled"


def test_an_empty_recorded_table_reads_back_as_empty_not_as_broken(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A run may record a table and write nothing to it, and that is not damage.

    Pinned separately from the corrupt-row case because the two look alike from the reader's side
    and must not be conflated: one is a legal outcome and the other is a file that was edited.
    """
    _workspace_for_run(tmp_path, capsys)
    _cli(capsys, "--project-root", str(tmp_path), "run", str(_spec(tmp_path)), "--run-id", "r1")

    empty = tmp_path / ".vqapr" / "runs" / "r1" / "tables" / "vqapr.blank.jsonl"
    empty.write_text("\n\n", encoding="utf-8")

    code, page = _cli(
        capsys, "--project-root", str(tmp_path), "show", "run", "r1", "--table", "vqapr.blank"
    )
    assert code == 0, page
    assert page["rows_total"] == 0 and page["items"] == []


def test_a_registered_datamodel_is_runnable_through_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A DataModel could be scaffolded, registered and described, and never run.

    `vqapr new datamodel` emitted one, `register` accepted it, `show model` described it, and no
    command executed it: `flow/materialize.py` held a real entry point the CLI never called. The
    front door is `run`, dispatching on the component the spec already names, because registration
    is already symmetric and a second top-level verb would add an asymmetry rather than remove one.
    """
    _workspace_for_run(tmp_path, capsys)

    code, emitted = _cli(
        capsys, "--project-root", str(tmp_path), "new", "datamodel", "derived",
        "--dataset", "prices", "--lookback", "1",
    )
    assert code == 0, emitted
    code, registered = _cli(
        capsys, "--project-root", str(tmp_path), "register", emitted["declaration"]
    )
    assert code == 0, registered

    spec = tmp_path / "materialize.yaml"
    spec.write_text(
        json.dumps(
            {
                "datamodel": "derived",
                "instruments": ["A"],
                "output": {"dataset_id": "derived-values", "value_fields": ["value"]},
                "evaluate_at": [
                    "2024-03-06T04:00:00+09:00",
                    "2024-03-07T04:00:00+09:00",
                ],
            }
        ),
        encoding="utf-8",
    )

    code, checked = _cli(capsys, "--project-root", str(tmp_path), "check", str(spec))

    assert code == 0, checked
    assert checked["ok"] is True
    # The two RunDefinition-shaped phases do not apply: a materialization has no venue, no
    # execution table, no account and no trading period. Running them anyway would refuse every
    # valid materialization spec on `check.period.uncovered`.
    assert checked["checked"] == ["spec", "workspace", "judgments"]
    assert checked["blocked"] == []
    for absent in ("check.period.", "check.weights.", "check.execution_ordering."):
        assert absent not in json.dumps(checked), f"{absent} judges a simulation, not this"

    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", str(spec))

    assert code == 0, ran
    assert ran["stage"] == "materialize.complete"
    assert ran["dataset_id"] == "derived-values"
    assert ran["evaluations"] == 2, "one invocation per declared evaluation instant"
    assert ran["rows_total"] > 0
    assert Path(ran["output_path"]).is_file()
    assert Path(ran["lineage_path"]).is_file()

    # `list datasets` is the readback: the output is a registered dataset like any other, which is
    # what makes it readable by the next model.
    code, datasets = _cli(capsys, "--project-root", str(tmp_path), "list", "datasets")
    assert code == 0, datasets
    assert "derived-values" in [row["dataset_id"] for row in datasets["items"]]


def test_a_materialization_spec_refuses_what_it_cannot_honour(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`check` must refuse what `run` would refuse, or it is worse than not existing.

    A verb that certifies a spec the next command rejects teaches the reader to stop trusting it,
    and `docs/issues/012` records exactly that divergence still open elsewhere. Every judgment here
    is a refusal `materialize()` raises later, hoisted to where it costs nothing.
    """
    _workspace_for_run(tmp_path, capsys)
    _, emitted = _cli(
        capsys, "--project-root", str(tmp_path), "new", "datamodel", "derived",
        "--dataset", "prices", "--lookback", "1",
    )
    _cli(capsys, "--project-root", str(tmp_path), "register", emitted["declaration"])

    spec = tmp_path / "m.yaml"
    base = {
        "datamodel": "derived",
        "instruments": ["A"],
        "output": {"dataset_id": "out", "value_fields": ["value"]},
        "evaluate_at": ["2024-03-06T04:00:00+09:00"],
    }

    def codes(document: dict[str, object]) -> list[str]:
        spec.write_text(json.dumps(document), encoding="utf-8")
        _, payload = _cli(capsys, "--project-root", str(tmp_path), "check", str(spec))
        return [failure["code"] for failure in payload.get("failures", [])]

    # A spec cannot disagree with itself about what it is, and neither can it decline to say.
    assert codes({**base, "strategy": {"component": "x", "agenda_id": "a"}}) == [
        "check.spec.kind_ambiguous"
    ]
    without = {key: value for key, value in base.items() if key != "datamodel"}
    assert codes(without) == ["check.spec.kind_ambiguous"]

    # `materialize()` refuses an output dataset_id that already exists. Asked here instead.
    assert codes({**base, "output": {"dataset_id": "prices", "value_fields": ["value"]}}) == [
        "check.materialize.output_registered"
    ]
    assert codes({**base, "instruments": []}) == ["check.materialize.no_instruments"]
    assert codes({**base, "evaluate_at": []}) == ["check.materialize.no_evaluation_instants"]
    assert codes({**base, "datamodel": "nope"}) == [
        "check.materialize.component_unregistered"
    ]
    # A registered component of the wrong kind is named as that, not as missing.
    assert codes({**base, "datamodel": "venue"}) == ["check.materialize.component_wrong_kind"]

    # The ninth judgment, and the reason it exists: `_instant` returns None for a naive datetime,
    # so these entries were skipped and the spec passed `check` with ok:true before `run` refused
    # it. A verb that certifies what the next command rejects is the divergence this slice exists
    # to close, and it had opened inside the task meant to close it.
    assert codes({**base, "evaluate_at": ["2024-03-06T04:00:00"]}) == [
        "check.materialize.evaluation_instant_invalid"
    ]


def test_a_materialization_refuses_the_flags_that_belong_to_a_run_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Refused, not ignored.

    `--run-id` and `--force` are defined entirely in terms of a run record, and a materialization
    writes none -- it registers a dataset. Accepting a flag that cannot do what its name says is
    how a reader learns the wrong model of a command, and `--force` in particular names a
    destructive act it would not perform.
    """
    _workspace_for_run(tmp_path, capsys)
    code, emitted = _cli(
        capsys, "--project-root", str(tmp_path), "new", "datamodel", "derived",
        "--dataset", "prices", "--lookback", "1",
    )
    _cli(capsys, "--project-root", str(tmp_path), "register", emitted["declaration"])
    spec = tmp_path / "m.yaml"
    spec.write_text(
        json.dumps(
            {
                "datamodel": "derived",
                "instruments": ["A"],
                "output": {"dataset_id": "out", "value_fields": ["value"]},
                "evaluate_at": ["2024-03-06T04:00:00+09:00"],
            }
        ),
        encoding="utf-8",
    )

    for flag in ("--run-id", "--force"):
        argv = ["--project-root", str(tmp_path), "run", str(spec), flag]
        if flag == "--run-id":
            argv.append("whatever")
        code, refused = _cli(capsys, *argv)
        assert code == 1, refused
        assert refused["stage"] != "unhandled"
        assert flag in json.dumps(refused), f"{flag} must be named in its own refusal"


def test_new_constraint_emits_a_rule_that_registers_and_runs_unedited(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The run spec advertised `constraints:` and nothing said what went in it.

    `Constraint` has five abstract members and had no scaffold, `register --help` named only
    datamodel and strategy, and the skill never mentioned constraints. The only way to learn the
    shapes was to register an empty subclass and read the `TypeError` -- and `project` is a
    semantic contract that cannot be guessed from a signature, so an agent asked for a 20% position
    cap correctly refused to guess and the requirement went unmet.
    """
    _workspace_for_run(tmp_path, capsys)

    # No --dataset: a Constraint is a rule about weights and reads nothing. Requiring one would
    # make an author invent a dataset to scaffold a rule that never opens it.
    code, emitted = _cli(capsys, "--project-root", str(tmp_path), "new", "constraint", "cap20")
    assert code == 0, emitted
    assert emitted["object_name"] == "Cap20"

    source = Path(emitted["path"]).read_text(encoding="utf-8")
    for member in ("constraint_id", "requirements", "project", "validate_intended", "evaluate"):
        assert f"def {member}" in source, f"{member} must be present, not left to a TypeError"
    # `project` is the member that cannot be guessed, so the template states its contract.
    assert "the box the optimiser must stay inside" in source

    code, registered = _cli(
        capsys, "--project-root", str(tmp_path), "register", emitted["declaration"]
    )
    assert code == 0, registered
    assert registered["registered"]["components"] == ["cap20"]

    # The scaffold cannot reproduce the crash T1 fixed: its `constraint_id` is fixed to the id it
    # was scaffolded under, so registering it as anything else is refused rather than crashing at
    # run assembly.
    code, mismatched = _cli(
        capsys, "--project-root", str(tmp_path), "register", "constraint", "cap20b",
        emitted["path"],
    )
    assert code == 1
    assert mismatched["failures"][0]["code"] == "component.load.constraint_id_mismatch"

    # The rule BITES. This workspace holds one instrument, so the scaffold strategy proposes 100%
    # of the book in it, which a 20% cap forbids. The run refuses by name rather than crashing --
    # a constraint that could not stop anything would be the more worrying result.
    code, refused = _cli(
        capsys, "--project-root", str(tmp_path), "run",
        str(_spec(tmp_path, constraints=["cap20"])), "--run-id", "capped",
    )
    assert code == 1
    assert "constraint" in json.dumps(refused).lower()
    assert refused["stage"] != "unhandled", "a bound constraint is a decision, not a crash"

    # And it PERMITS. `--cap` is the marked place to change, exposed as a flag the way `--lookback`
    # is for a strategy, so the same scaffold runs clean where the book satisfies it. Without this
    # half, a constraint that refused everything would pass the assertion above just as well.
    code, wide = _cli(
        capsys, "--project-root", str(tmp_path), "new", "constraint", "cap-any", "--cap", "1.0"
    )
    assert code == 0, wide
    code, registered_wide = _cli(
        capsys, "--project-root", str(tmp_path), "register", wide["declaration"]
    )
    assert code == 0, registered_wide

    code, ran = _cli(
        capsys, "--project-root", str(tmp_path), "run",
        str(_spec(tmp_path, constraints=["cap-any"])), "--run-id", "uncapped",
    )
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
    from vqapr.domain.roster_export import export_roster

    # Before a workspace exists at all, and after one exists with no roster. Both are zero.
    code, empty = _cli(capsys, "--project-root", str(tmp_path), "list", "instruments")
    assert code == 0, empty
    assert empty["count"] == 0 and empty["items"] == []

    _workspace_for_run(tmp_path, capsys)
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
    """A run with no roster completes with every fill `kind: None`, and used to say nothing.

    No refusal, no warning, nothing in the success envelope distinguished it from a run whose
    categories were known. On an academic venue that is harmless. On a KRX-shaped venue every name
    is charged identically while the record says the categories were never known, and
    `cost_by_kind()` collapses to one unlabelled bucket -- the report that would expose it is the
    one the gap erases.

    Reported on the SUCCESS path, because the run is legitimate. What was missing was not a
    refusal but a statement of what the run was computed against.
    """
    import json as _json

    from vqapr.domain.roster_export import export_roster
    from vqapr.flow.run_records import read_record

    _workspace_for_run(tmp_path, capsys)
    spec = str(_spec(tmp_path))

    code, without = _cli(capsys, "--project-root", str(tmp_path), "run", spec, "--run-id", "bare")

    assert code == 0, without
    assert without["roster"]["known"] is False
    # The note names the consequence and the remedy, not merely the absence.
    assert "kind: None" in without["roster"]["note"]
    assert "vqapr register" in without["roster"]["note"]
    assert read_record(tmp_path / ".vqapr", "bare")["roster"] is None

    written = export_roster({"A": "stock"}, tmp_path / "roster")
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
    digest = registered["registered"]["instruments"][0]["digest"]

    code, with_roster = _cli(
        capsys, "--project-root", str(tmp_path), "run", spec, "--run-id", "categorised"
    )

    assert code == 0, with_roster
    assert with_roster["roster"]["known"] is True
    assert with_roster["roster"]["digest"] == digest
    assert with_roster["roster"]["by_kind"] == {"stock": 1}
    # The frozen record carries the same facts, so a later reader gets them without the envelope.
    frozen = read_record(tmp_path / ".vqapr", "categorised")
    assert frozen["roster"]["digest"] == digest
    assert frozen["roster"]["by_kind"] == {"stock": 1}
    assert _json.dumps(frozen)  # the record must stay JSON-serialisable


def test_a_constraint_that_slipped_past_registration_is_refused_by_check_not_by_a_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reported crash, driven through the two verbs a user actually types.

    `check` used to return `ok:true` on all five phases and `run` then died inside
    `SimulationFlow.__init__` with `stage:"unhandled"`, `failures:[]` and a raw traceback.

    `vqapr register` now refuses the mismatch outright, so the workspace is populated through the
    Python API here on purpose — that is precisely the route the acceptance criterion anticipates
    (*"if registration is permitted for a case (1) does not cover"*), and it is what any caller
    using `Workspace` directly does. The point of the test is that the two CLI verbs still refuse,
    and refuse in the structured shape rather than by crashing.
    """
    from vqapr.extension.component import ComponentKind, ComponentRef
    from vqapr.extension.fingerprint import fingerprint_component
    from vqapr.workspace import Workspace

    _workspace_for_run(tmp_path, capsys)

    source = tmp_path / "mislabelled.py"
    source.write_text(
        "from vqapr.public import Constraint, ConstraintBounds\n"
        "class Limit(Constraint):\n"
        "    @property\n"
        "    def constraint_id(self):\n"
        "        return 'position-cap'\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def project(self, window, instruments):\n"
        "        return ConstraintBounds({}, {})\n"
        "    def validate_intended(self, intent, bounds):\n"
        "        return None\n"
        "    def evaluate(self, window, account, marks, bounds):\n"
        "        return None\n",
        encoding="utf-8",
    )
    Workspace.create(tmp_path).register_component(
        ComponentRef.of(
            "limit",
            ComponentKind.CONSTRAINT,
            source,
            "Limit",
            fingerprint=fingerprint_component(
                source, kind=ComponentKind.CONSTRAINT, object_name="Limit"
            ),
        )
    )
    spec = str(_spec(tmp_path, constraints=["limit"]))

    code, checked = _cli(capsys, "--project-root", str(tmp_path), "check", spec)

    assert code == 1, checked
    assert checked["ok"] is False
    assert "component.load.constraint_id_mismatch" in [
        failure["code"] for failure in checked["failures"]
    ]

    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", spec)

    assert code == 1, ran
    assert ran["ok"] is False
    # The whole point. A bare exception here reaches the envelope as `stage:"unhandled"` with an
    # empty `failures[]`, which tells a user the framework broke when their registration was wrong.
    assert ran["stage"] != "unhandled"
    assert ran["failures"], "a refusal must carry its failures, not an empty list"
    assert "component.load.constraint_id_mismatch" in [
        failure["code"] for failure in ran["failures"]
    ]


def test_a_constraint_registered_under_the_id_it_answers_to_still_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other half of the reported case, which a refusal test alone cannot prove.

    Registering `NoShort` as `noshort` crashed and the identical file as `no-short` ran clean. A
    test that only pins the refusal would pass just as well if the new check refused everything,
    so this carries the accepted spelling all the way through `check` and `run` and asserts the
    counts are the ones the unconstrained run produces.
    """
    from vqapr.constraints.builtin import shipped_constraint_path

    _workspace_for_run(tmp_path, capsys)

    declaration = tmp_path / "constraint.yaml"
    declaration.write_text(
        "components:\n  no-short:\n    kind: constraint\n"
        f"    path: {shipped_constraint_path('no_short').as_posix()}\n"
        "    object_name: NoShort\n",
        encoding="utf-8",
    )
    code, registered = _cli(capsys, "--project-root", str(tmp_path), "register", str(declaration))
    assert code == 0, registered
    assert registered["registered"]["components"] == ["no-short"]

    # Compared against the identical spec WITHOUT the constraint, rather than against `ok:true`.
    # This fixture's spec already fails `check` on `check.lookback.uncovered` while `run` completes
    # -- a pre-existing check/run divergence reproduced at HEAD 7ae3d3af and recorded as a
    # follow-up, not introduced here. Asserting `ok:true` would be asserting something false about
    # the fixture; asserting that the constraint adds no refusal is the property under test.
    _, without = _cli(capsys, "--project-root", str(tmp_path), "check", str(_spec(tmp_path)))

    spec = str(_spec(tmp_path, constraints=["no-short"]))

    code, checked = _cli(capsys, "--project-root", str(tmp_path), "check", spec)
    assert [failure["code"] for failure in checked["failures"]] == [
        failure["code"] for failure in without["failures"]
    ], "naming a correctly-registered constraint must add no refusal of its own"
    assert checked["blocked"] == without["blocked"]
    assert "component.load.constraint_id_mismatch" not in [
        failure["code"] for failure in checked["failures"]
    ]

    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", spec)
    assert code == 0, ran
    assert ran["ok"] is True
    assert ran["stage"] == "run.complete"
    # Identical to the unconstrained end-to-end run above: a long-only strategy never proposes a
    # short, so no-short binds nothing and must change no number. A different count here would
    # mean the constraint altered the book rather than merely permitting it.
    assert ran["occurrences"] == 12
    assert ran["account_version"] == 2
    assert ran["run_state_version"] == 14


def test_run_refuses_a_date_boundary_as_structured_cli_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The old template promised dates, then preflight crashed on the naive datetime."""
    _workspace_for_run(tmp_path, capsys)

    code, payload = _cli(
        capsys,
        "--project-root",
        str(tmp_path),
        "run",
        str(_spec(tmp_path, start="2024-03-05", end="2024-03-07")),
    )

    assert code == 1
    assert payload["stage"] == "cli.input"
    failure = payload["failures"][0]
    assert failure["code"] == "cli.input.value_invalid"
    assert "UTC offset" in failure["requirement"]
    assert failure["examples"] == ["2024-01-02T00:00:00+09:00"]


def test_strategy_config_list_exposes_and_filters_by_component_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Registration keys a strategy config by component id, so list must show that identity."""
    _workspace_for_run(tmp_path, capsys)

    code, payload = _cli(
        capsys,
        "--project-root",
        str(tmp_path),
        "list",
        "strategy-configs",
        "--id",
        "my-alpha",
    )

    assert code == 0
    assert payload["count"] == 1
    assert payload["items"] == [{"component_id": "my-alpha", "agenda_id": "alpha"}]


def test_an_incomplete_spec_names_every_missing_key_at_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A spec carrying only what canon documents as required still cannot run.

    `RunDefinition` tolerates an absent start, end, exchange, execution input and account because
    other callers supply them another way. This command always continues into `preflight_run` and
    `run`, which refuse without them, so they are required *here* — and an agent gets all of them
    in one reply instead of discovering them one exception at a time.
    """
    spec = tmp_path / "thin.yaml"
    spec.write_text(
        json.dumps(
            {
                "strategy": {"component": "my-alpha", "agenda_id": "alpha"},
                "valuation": {"agenda_id": "valuing"},
                "instruments": ["A"],
            }
        ),
        encoding="utf-8",
    )

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "run", str(spec))

    assert code == 1
    missing = payload["error"]
    for key in ("start", "end", "exchange", "execution_input", "initial_account"):
        assert key in missing, f"{key} was not named: {missing}"


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
    assert payload["stage"] == "cli.usage"
    assert payload["failures"][0]["code"] == "cli.usage.rejected"
    # argparse's wording rides verbatim; the CLI does not invent a second remedy text.
    assert "invalid choice" in payload["failures"][0]["requirement"]
    assert "datamodel" in payload["failures"][0]["requirement"]


def test_a_usage_refusal_carries_no_package_failure_family(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`FailureFamily` is the closed set of package stages, and usage never reached one."""
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "list", "nonsense")

    assert code == 1
    assert payload["family"] is None
    assert payload["mutation"] is False
    # No traceback and no dump: the command line is the whole evidence.
    assert "traceback" not in payload
    assert "detail" not in payload


def test_an_unknown_command_does_not_escape_as_a_bare_exit_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, payload = _cli(capsys, "definitely-not-a-command")

    assert code == 1
    assert payload["stage"] == "cli.usage"


def test_help_keeps_argparses_own_behaviour(capsys: pytest.CaptureFixture[str]) -> None:
    """Only failure is rerouted. `--help` still exits zero through argparse."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    assert "usage: vqapr" in capsys.readouterr().out
