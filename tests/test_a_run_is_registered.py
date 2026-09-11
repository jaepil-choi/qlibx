"""A run is a registered declaration: the reusable unit is a name in the workspace, not a file.

Record `139` (campaign Step 7); design §4.1. Before it, `cli/run.py` read a spec file on every
call and built a `RunDefinition` from it, so "the same run with another strategy" was a second
file kept in step by hand (architecture §17.3). The `runs:` section is registered through the same
transaction as everything else, refused when it names anything the workspace does not hold, and
read back as the same value.

Record `148`: a run declares its own sessions and the one wall time `at` every strategy is called
at, so there is no agenda or strategy binding left for it to name. What a run still names is
components, an execution input, and -- when it takes its sessions from a dataset -- that dataset.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from pydantic import ValidationError

from vqapr.component.reference import ComponentRef
from vqapr.data.dataset import DatasetRegistration
from vqapr.data.source import SourceSpec
from vqapr.domain.account import AccountMode, AccountSnapshot
from vqapr.domain.errors import VqaprError
from vqapr.domain.wiring import Role
from vqapr.workspace.registration import apply
from vqapr.workspace.registry import Workspace
from vqapr.workspace.run_definition import RunDefinition, RunExecution, RunFill, StrategyEntry

KST = ZoneInfo("Asia/Seoul")
SESSIONS = (date(2024, 3, 5), date(2024, 3, 6), date(2024, 3, 7))
_RUN_READY: dict[str, object] = {
    "instruments": ["A"],
    "start": None,
    "end": None,
    "timezone": "Asia/Seoul",
    "agenda": {"every": "1d", "at": "15:29"},
    "exchange": None,
    "execution": None,
    "initial_account": {"cash": "1000", "mode": "long_only", "positions": {}},
    "writes": "krx-2024-weights",
    "strategies": {"ou-k0": None},
}
"""A `runs.<id>` body every model rule accepts, for the malformed cases to break one key of."""


def _component(name: str, kind: Role, root: Path) -> ComponentRef:
    return ComponentRef.of(name, kind, root / f"{name}.py", "Thing", fingerprint="a" * 64)


def _definition(**overrides: object) -> RunDefinition:
    declared: dict[str, object] = {
        "run_id": "krx-2024",
        "writes": "krx-2024-weights",
        "strategy": StrategyEntry("ou-k0"),
        "compliance": ("no-short",),
        "instruments": ("A", "B"),
        "timezone": "Asia/Seoul",
        "agenda": {"every": "1d", "at": time(15, 29)},
        "exchange": "venue",
        "execution": RunExecution(
            dataset="venue-daily",
            trade_price="close",
            fill=RunFill(at=time(15, 30)),
        ),
        "start": datetime(2024, 3, 5, tzinfo=KST),
        "end": datetime(2024, 3, 8, 15, 30, tzinfo=KST),
        "initial_account_snapshot": AccountSnapshot(0, Decimal("1000"), {"A": Decimal("2")}),
        "initial_account_mode": AccountMode.LONG_ONLY,
    }
    declared.update(overrides)
    return RunDefinition(**declared)  # type: ignore[arg-type]


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """Everything a run names, registered: four components and a venue dataset."""
    space = Workspace.create(tmp_path)
    for name, kind in (
        ("ou-k0", Role.STRATEGY_MODEL),
        ("ou-ff5", Role.STRATEGY_MODEL),
        ("no-short", Role.COMPLIANCE),
        ("venue", Role.EXCHANGE),
    ):
        with Workspace.transaction(space) as t:
            t.register_component(_component(name, kind, tmp_path))
    execution = tmp_path / "execution.parquet"
    execution.write_bytes(b"")
    with Workspace.transaction(space) as t:
        t.register_dataset(
            DatasetRegistration.of(
                'venue-daily',
                'venue-source',
                instrument_field="instrument",
                available_at="trade_at",
                grain="instrument_instant",
                key_fields=("trade_at", "instrument"),
                fields={"close": "close", "is_tradable": "is_tradable"},
                field_types={"close": "DOUBLE", "is_tradable": "BOOLEAN"},
                execution={"is_tradable": "is_tradable"},
            ).with_span(
                datetime(2024, 3, 5, 15, 30, tzinfo=KST), datetime(2024, 3, 8, 15, 30, tzinfo=KST)
            ),
            SourceSpec.of("venue-source", execution),
        )
    return Workspace.open(tmp_path)


def test_a_run_registers_reads_back_and_is_idempotent(workspace: Workspace) -> None:
    definition = _definition()

    with Workspace.transaction(workspace) as t:
        assert t.register_run(definition) is True
    with Workspace.transaction(workspace) as t:
        assert t.register_run(definition) is False, "the same run again changes nothing"

    reopened = Workspace.open(workspace.project_root)
    assert reopened.run_definition("krx-2024") == definition
    assert [run.run_id for run in reopened.run_definitions] == ["krx-2024"]
    document = yaml.safe_load(reopened.path.read_text(encoding="utf-8"))
    written = document["runs"]["krx-2024"]
    assert written["writes"] == "krx-2024-weights"
    assert written["strategy"] == {"component": "ou-k0"}
    assert written["compliance"] == ["no-short"], "the rules are the run's, beside the venue"
    assert "strategies" not in written, "the singular block replaced the keyed mapping"
    # The sessions and the one wall time are the run's own keys, in the shape an author writes.
    assert written["timezone"] == "Asia/Seoul"
    assert written["agenda"] == {"every": "1d", "at": ["15:29:00"]}
    assert "at" not in written and "sessions" not in written and "sessions_from" not in written
    assert "valuation" not in written and "monitoring" not in written


def test_a_strategy_run_names_no_day_source(workspace: Workspace) -> None:
    """Design §3.3: a strategy run's trading days are the days its execution table has rows
    for, so `agenda.days_from` is a datamodel run's word and is refused here by name."""
    with pytest.raises(ValueError, match="declares no agenda.days_from"):
        _definition(agenda={"every": "1d", "at": "15:29", "days_from": "prices"})


def test_a_changed_run_under_an_existing_id_is_refused_naming_the_run(
    workspace: Workspace,
) -> None:
    with Workspace.transaction(workspace) as t:
        t.register_run(_definition())

    with pytest.raises(VqaprError) as refused, Workspace.transaction(workspace) as t:
        t.register_run(_definition(instruments=("A",)))
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"] == "run.registered"
    assert "run_id 'krx-2024'" in failure["requirement"]
    # `docs/issues/archive/084`: the two options the fix used to list were the two things an author
    # editing a run during setup did not want. The third ships, and the refusal names it.
    assert "vqapr rm run-definition krx-2024" in failure["fix"]


@pytest.mark.parametrize(
    ("override", "names"),
    [
        ({"strategy": StrategyEntry("absent")}, "strategy 'absent'"),
        ({"strategy": StrategyEntry("venue")}, "strategy 'venue'"),
        ({"compliance": ("ou-ff5",)}, "compliance rule 'ou-ff5'"),
        ({"exchange": "ou-k0"}, "exchange 'ou-k0'"),
        (
            {
                "execution": RunExecution(
                    dataset="nope",
                    trade_price="close",
                    fill=RunFill(at=time(15, 30)),
                )
            },
            "dataset 'nope'",
        ),
    ],
)
def test_a_run_naming_anything_unregistered_is_refused_by_name(
    workspace: Workspace, override: dict[str, object], names: str
) -> None:
    """Refused at registration, so `vqapr run <id>` never meets an id it cannot resolve."""
    with pytest.raises(VqaprError) as refused, Workspace.transaction(workspace) as t:
        t.register_run(_definition(**override))
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"] == "run.reference_invalid"
    assert names in failure["requirement"], failure["requirement"]


def test_a_run_holds_what_it_names_so_removal_is_refused_by_name(workspace: Workspace) -> None:
    with Workspace.transaction(workspace) as t:
        t.register_run(_definition())

    assert workspace.references_to("component", "no-short") == ("run 'krx-2024'",)
    assert workspace.references_to("component", "venue") == ("run 'krx-2024'",)
    assert workspace.references_to("run", "krx-2024") == (), "nothing names a run"
    with pytest.raises(VqaprError, match="referenced"):
        workspace.remove("component", "ou-k0")
    assert workspace.remove("run", "krx-2024") is True
    assert workspace.remove("run", "krx-2024") is False
    assert workspace.remove("component", "ou-k0") is True


def test_a_declaration_document_registers_a_run_in_the_same_transaction(
    workspace: Workspace,
) -> None:
    """The `runs:` section, in the shape `vqapr new run` emits."""
    document = {
        "runs": {
            "krx-2024": {
                "instruments": ["A", "B"],
                "start": "2024-03-05T00:00:00+09:00",
                "end": "2024-03-08T15:30:00+09:00",
                "timezone": "Asia/Seoul",
                "agenda": {"every": "1d", "at": "15:29"},
                "exchange": "venue",
                "execution": {
                    "dataset": "venue-daily",
                    "trade_price": "close", "fill": {"at": "15:30"},
                },
                "initial_account": {"cash": "1000", "mode": "long_only", "positions": {"A": "2"}},
                "writes": "krx-2024-weights",
                "strategies": {"ou-k0": {}},
                "compliance": ["no-short"],
            }
        }
    }

    registered = apply(document, workspace.project_root, base=workspace.project_root)

    assert registered["runs"] == ["krx-2024"]
    assert Workspace.open(workspace.project_root).run_definition("krx-2024") == _definition()


@pytest.mark.parametrize(
    ("body", "said"),
    [
        # A key-set fault names the keys the run lacks: the model is refused before any rule
        # about the values can run, so the clock keys are what a 0.3.0-shaped run hears first.
        ({"instruments": ["A"], "strategies": {}}, "timezone: Field required"),
        ({**_RUN_READY, "strategies": {}}, "exactly one of"),
        (
            {**_RUN_READY, "agenda": {"every": "1d"}},
            "needs at",
        ),
        ({**_RUN_READY, "agenda": {"every": "5m", "at": "15:29"}}, "not at"),
    ],
)
def test_a_malformed_run_declaration_is_refused_with_its_own_code(
    workspace: Workspace, body: dict[str, object], said: str
) -> None:
    document = {"runs": {"bad": body}}

    with pytest.raises(VqaprError) as refused:
        apply(document, workspace.project_root, base=workspace.project_root)
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"] == "declaration.run_invalid"
    assert failure["source"]["key_path"] == "runs.bad"
    assert said in failure["observed"], failure["observed"]


@pytest.mark.parametrize(
    ("override", "error", "said"),
    [
        ({"timezone": ""}, ValueError, "timezone must be a non-empty IANA timezone name"),
        ({"timezone": "Mars/Olympus"}, ValueError, "unknown IANA timezone"),
        ({"agenda": None}, ValidationError, "agenda"),
        ({"agenda": {"every": "1d", "at": object()}}, ValidationError, "at"),
        (
            {"agenda": {"every": "1d", "at": time(15, 29, tzinfo=KST)}},
            ValueError,
            "timezone-naive wall time",
        ),
        ({"agenda": {"every": "1d"}}, ValueError, "needs at"),
        ({"agenda": {"every": "1x", "at": "15:29"}}, ValueError, "count and a unit"),
        ({"agenda": {"every": "1h", "at": "15:29"}}, ValueError, "declare from/to, not at"),
    ],
)
def test_the_run_definition_refuses_a_half_declared_clock(
    override: dict[str, object], error: type[Exception], said: str
) -> None:
    """The zone and the agenda are the run's whole clock; each half is checked."""
    with pytest.raises(error, match=said):
        _definition(**override)


def test_the_run_names_the_one_agenda_preflight_derives() -> None:
    assert _definition().agenda_id == "krx-2024.agenda"


def test_a_run_without_an_initial_account_reopens(workspace: Workspace) -> None:
    """`RunDefinition` lets a run leave its initial account undeclared; the document must too.

    What is written must be what is read: a run the workspace accepted and wrote is not allowed
    to make `Workspace.open()` refuse the whole workspace on the next command.
    """
    definition = _definition(initial_account_snapshot=None, initial_account_mode=None)
    with Workspace.transaction(workspace) as t:
        assert t.register_run(definition) is True

    assert Workspace.open(workspace.project_root).run_definition("krx-2024") == definition
