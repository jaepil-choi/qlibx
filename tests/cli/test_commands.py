"""The CLI is the surface a first-time user actually types, so it is driven here as typed.

`test_envelope.py` covers the envelope's shape and asserts the parser *mentions* every command.
Mentioning is not running: before this file, no test invoked `new`, `register`, `list` or `run`,
so the whole `spec.yaml -> RunDefinition -> preflight_run -> run` path was unexecuted. These tests
call `main(argv)` and read the JSON it emits, which is exactly what an agent gets.

Datasets, sources, agendas, execution inputs and configs are registered through the library,
because the CLI has no command that registers them (`register` takes `datamodel|strategy`, while
`list` reads eight kinds). That asymmetry is a finding, recorded in the handoff, not a thing this
file works around silently.
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
    ComponentKind,
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
    SourceSpec,
    StrategyConfig,
    ValuationConfig,
    component_ref,
    register_agenda,
    register_component,
    register_dataset,
    register_execution_input,
    register_monitoring_policy,
    register_strategy_config,
    register_valuation_config,
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
        "from vqapr.exchange.venue import AcademicExchange, ListingRule, Side\n"
        "class Venue(AcademicExchange):\n"
        "    def __init__(self):\n"
        "        super().__init__({'A': ListingRule('A', Decimal('1'), Decimal('1'), False,\n"
        "            frozenset((Side.BUY, Side.SELL)))})\n",
        encoding="utf-8",
    )
    return path


def _workspace_for_run(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Everything `run` needs that the CLI itself cannot register."""
    observation, execution = _parquets(root)
    register_dataset(
        root,
        DatasetRegistration.of(
            "prices",
            "price-source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
        ),
        SourceSpec.of("price-source", observation),
    )
    register_execution_input(
        root,
        ExecutionInputRegistration.of(
            "venue-daily",
            ExecutionTableSpec(
                source=SourceSpec.of("venue-source", execution),
                trade_at_field="trade_at",
                instrument_field="instrument",
                is_tradable_field="is_tradable",
                price_fields={"close": "close"},
            ),
            FillConvention(FillSelector.NEXT_ELIGIBLE, time(15, 30), "Asia/Seoul", "close"),
        ),
    )
    strategy_agenda = _agenda("alpha", OperationRole.STRATEGY_CALLBACK, time(4))
    valuation_agenda = _agenda("valuing", OperationRole.VALUATION, time(16))
    monitoring_agenda = _agenda("watching", OperationRole.MONITORING, time(17))
    for agenda in (strategy_agenda, valuation_agenda, monitoring_agenda):
        register_agenda(root, agenda)

    code, payload = _cli(
        capsys, "--project-root", str(root), "new", "strategy", "my-alpha",
        "--dataset", "prices", "--lookback", "2",
    )
    assert code == 0, payload
    code, registered = _cli(
        capsys, "--project-root", str(root), "register", "strategy", "my-alpha",
        payload["path"], payload["object_name"],
    )
    assert code == 0, registered

    register_component(
        root, component_ref("venue", ComponentKind.EXCHANGE, _exchange_component(root), "Venue")
    )
    register_strategy_config(
        root,
        StrategyConfig(
            component_ref(
                "my-alpha",
                ComponentKind.STRATEGY_MODEL,
                Path(registered["path"]),
                "MyAlpha",
            ),
            "alpha",
            OperationRole.STRATEGY_CALLBACK,
        ),
    )
    register_valuation_config(root, ValuationConfig("valuing", OperationRole.VALUATION))
    register_monitoring_policy(root, MonitoringPolicy("watching", OperationRole.MONITORING))


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

    code, registered = _cli(
        capsys, "--project-root", str(tmp_path), "register", "strategy", "my-alpha",
        created["path"], created["object_name"],
    )
    assert code == 0
    assert registered["stage"] == "component.register"
    assert len(registered["fingerprint"]) == 64

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
    # The account moved, so the callbacks were really invoked and really committed.
    assert payload["account_version"] == 7


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
    code, payload = _cli(
        capsys, "--project-root", str(tmp_path), "register", "dataset", "x", "y.parquet", "Z"
    )

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
