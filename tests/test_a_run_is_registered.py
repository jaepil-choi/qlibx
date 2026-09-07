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

from vqapr.account.account import AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.data.sources import SourceSpec
from vqapr.declarations import apply
from vqapr.domain.errors import VqaprError
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionInputRegistration, ExecutionTableSpec
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import RunDefinition, StrategyEntry
from vqapr.workspace import Workspace

KST = ZoneInfo("Asia/Seoul")
SESSIONS = (date(2024, 3, 5), date(2024, 3, 6), date(2024, 3, 7))
_RUN_READY: dict[str, object] = {
    "instruments": ["A"],
    "start": None,
    "end": None,
    "timezone": "Asia/Seoul",
    "at": "15:29",
    "sessions": ["2024-03-05"],
    "exchange": None,
    "execution_input": None,
    "initial_account": {"cash": "1000", "mode": "long_only", "positions": {}},
    "strategies": {"ou-k0": None},
}
"""A `runs.<id>` body every model rule accepts, for the malformed cases to break one key of."""


def _component(name: str, kind: ComponentKind, root: Path) -> ComponentRef:
    return ComponentRef.of(name, kind, root / f"{name}.py", "Thing", fingerprint="a" * 64)


def _definition(**overrides: object) -> RunDefinition:
    declared: dict[str, object] = {
        "run_id": "krx-2024",
        "strategies": (StrategyEntry("ou-k0", ("no-short",)), StrategyEntry("ou-ff5")),
        "instruments": ("A", "B"),
        "timezone": "Asia/Seoul",
        "at": time(15, 29),
        "sessions": SESSIONS,
        "exchange": "venue",
        "execution_input_id": "venue-daily",
        "start": datetime(2024, 3, 5, tzinfo=KST),
        "end": datetime(2024, 3, 8, 15, 30, tzinfo=KST),
        "initial_account_snapshot": AccountSnapshot(0, Decimal("1000"), {"A": Decimal("2")}),
        "initial_account_mode": AccountMode.LONG_ONLY,
    }
    declared.update(overrides)
    return RunDefinition(**declared)  # type: ignore[arg-type]


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """Everything a run names, registered: four components and an execution input."""
    space = Workspace.create(tmp_path)
    for name, kind in (
        ("ou-k0", ComponentKind.STRATEGY_MODEL),
        ("ou-ff5", ComponentKind.STRATEGY_MODEL),
        ("no-short", ComponentKind.CONSTRAINT),
        ("venue", ComponentKind.EXCHANGE),
    ):
        with Workspace.transaction(space) as t:
            t.register_component(_component(name, kind, tmp_path))
    execution = tmp_path / "execution.parquet"
    execution.write_bytes(b"")
    with Workspace.transaction(space) as t:
        t.register_execution_input(
            ExecutionInputRegistration.of(
                "venue-daily",
                ExecutionTableSpec(
                    source=SourceSpec.of("venue-source", execution),
                    trade_at_field="trade_at",
                    instrument_field="instrument",
                    is_tradable_field="is_tradable",
                    price_fields={"close": "close"},
                ),
                FillConvention(FillSelector.SAME_DAY, time(15, 30), "Asia/Seoul", "close"),
            )
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
    assert set(written["strategies"]) == {"ou-k0", "ou-ff5"}
    assert written["strategies"]["ou-k0"] == {"constraints": ["no-short"]}
    # The sessions and the one wall time are the run's own keys, in the shape an author writes.
    assert written["timezone"] == "Asia/Seoul"
    assert written["at"] == "15:29:00"
    assert [str(day) for day in written["sessions"]] == ["2024-03-05", "2024-03-06", "2024-03-07"]
    assert "sessions_from" not in written
    assert "valuation" not in written and "monitoring" not in written


def test_a_run_may_take_its_sessions_from_a_registered_dataset_instead(
    workspace: Workspace, tmp_path: Path
) -> None:
    """`sessions_from` names a dataset whose days are the sessions; exactly one of the two."""
    from vqapr.data.datasets import DatasetRegistration

    prices = DatasetRegistration.of(
        "prices",
        "price-source",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
        grain="instrument_instant",
    ).with_span(datetime(2024, 3, 5, tzinfo=KST), datetime(2024, 3, 7, tzinfo=KST))
    with Workspace.transaction(workspace) as t:
        t.register_dataset(prices, SourceSpec.of("price-source", tmp_path / "prices.parquet"))
    definition = _definition(sessions=(), sessions_from="prices")

    with Workspace.transaction(workspace) as t:
        assert t.register_run(definition) is True

    reopened = Workspace.open(workspace.project_root)
    assert reopened.run_definition("krx-2024") == definition
    written = yaml.safe_load(reopened.path.read_text(encoding="utf-8"))["runs"]["krx-2024"]
    assert written["sessions_from"] == "prices"
    assert "sessions" not in written


def test_a_changed_run_under_an_existing_id_is_refused_naming_the_run(
    workspace: Workspace,
) -> None:
    with Workspace.transaction(workspace) as t:
        t.register_run(_definition())

    with pytest.raises(VqaprError) as refused, Workspace.transaction(workspace) as t:
        t.register_run(_definition(instruments=("A",)))
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"] == "workspace.run.register.conflict"
    assert "run_id 'krx-2024'" in failure["requirement"]
    # `docs/issues/084`: the two options the fix used to list were the two things an author
    # editing a run during setup did not want. The third ships, and the refusal names it.
    assert "vqapr rm run-definition krx-2024" in failure["fix"]


@pytest.mark.parametrize(
    ("override", "names"),
    [
        ({"strategies": (StrategyEntry("absent"),)}, "strategy 'absent'"),
        ({"strategies": (StrategyEntry("venue"),)}, "strategy 'venue'"),
        ({"strategies": (StrategyEntry("ou-k0", ("ou-ff5",)),)}, "constraint 'ou-ff5'"),
        ({"exchange": "ou-k0"}, "exchange 'ou-k0'"),
        ({"execution_input_id": "nope"}, "execution input 'nope'"),
        ({"sessions": (), "sessions_from": "nope"}, "dataset 'nope'"),
    ],
)
def test_a_run_naming_anything_unregistered_is_refused_by_name(
    workspace: Workspace, override: dict[str, object], names: str
) -> None:
    """Refused at registration, so `vqapr run <id>` never meets an id it cannot resolve."""
    with pytest.raises(VqaprError) as refused, Workspace.transaction(workspace) as t:
        t.register_run(_definition(**override))
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"] == "workspace.run.register.reference"
    assert names in failure["requirement"], failure["requirement"]


def test_a_run_holds_what_it_names_so_removal_is_refused_by_name(workspace: Workspace) -> None:
    with Workspace.transaction(workspace) as t:
        t.register_run(_definition())

    assert workspace.references_to("component", "ou-ff5") == ("run 'krx-2024'",)
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
                "at": "15:29",
                "sessions": ["2024-03-05", "2024-03-06", "2024-03-07"],
                "exchange": "venue",
                "execution_input": "venue-daily",
                "initial_account": {"cash": "1000", "mode": "long_only", "positions": {"A": "2"}},
                "strategies": {"ou-k0": {"constraints": ["no-short"]}, "ou-ff5": None},
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
        ({**_RUN_READY, "strategies": {}}, "must name at least one model"),
        (
            {
                **_RUN_READY,
                "sessions": ["2024-03-05"],
                "sessions_from": "prices",
            },
            "exactly one of sessions_from",
        ),
        ({**_RUN_READY, "sessions": []}, "at least one date"),
    ],
)
def test_a_malformed_run_declaration_is_refused_with_its_own_code(
    workspace: Workspace, body: dict[str, object], said: str
) -> None:
    document = {"runs": {"bad": body}}

    with pytest.raises(VqaprError) as refused:
        apply(document, workspace.project_root, base=workspace.project_root)
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"] == "declaration.read.run_invalid"
    assert failure["source"]["key_path"] == "runs.bad"
    assert said in failure["observed"], failure["observed"]


@pytest.mark.parametrize(
    ("override", "error", "said"),
    [
        ({"timezone": ""}, ValueError, "timezone must be a non-empty IANA timezone name"),
        ({"timezone": "Mars/Olympus"}, ValueError, "unknown IANA timezone"),
        ({"at": None}, ValueError, "at must be declared"),
        ({"at": object()}, ValidationError, "at"),
        ({"at": time(15, 29, tzinfo=KST)}, ValueError, "timezone-naive wall time"),
        ({"sessions": ()}, ValueError, "exactly one of sessions_from or sessions"),
        ({"sessions_from": "prices"}, ValueError, "exactly one of sessions_from or sessions"),
        ({"sessions": (datetime(2024, 3, 5, 9, 30, tzinfo=KST),)}, ValidationError, "sessions"),
    ],
)
def test_the_run_definition_refuses_a_half_declared_clock(
    override: dict[str, object], error: type[Exception], said: str
) -> None:
    """The zone, the wall time and the sessions are the run's whole clock; each is checked."""
    with pytest.raises(error, match=said):
        _definition(**override)


def test_the_run_names_the_one_agenda_preflight_derives() -> None:
    assert _definition().agenda_id == "krx-2024.sessions"


def test_a_run_without_an_initial_account_reopens(workspace: Workspace) -> None:
    """`RunDefinition` lets a run leave its initial account undeclared; the document must too.

    What is written must be what is read: a run the workspace accepted and wrote is not allowed
    to make `Workspace.open()` refuse the whole workspace on the next command.
    """
    definition = _definition(initial_account_snapshot=None, initial_account_mode=None)
    with Workspace.transaction(workspace) as t:
        assert t.register_run(definition) is True

    assert Workspace.open(workspace.project_root).run_definition("krx-2024") == definition
