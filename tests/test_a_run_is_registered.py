"""A run is a registered declaration: the reusable unit is a name in the workspace, not a file.

Record `139` (campaign Step 7); design §4.1. Before it, `cli/run.py` read a spec file on every
call and built a `RunDefinition` from it, so "the same run with another strategy" was a second
file kept in step by hand (architecture §17.3). The `runs:` section is registered through the same
transaction as everything else, refused when it names anything the workspace does not hold, and
read back as the same value.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from vqapr.account.account import AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data.sources import SourceSpec
from vqapr.declarations import apply
from vqapr.domain.errors import VqaprError
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionInputRegistration, ExecutionTableSpec
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import RunDefinition, StrategyConfig, StrategyEntry
from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole
from vqapr.valuation.configuration import ValuationConfig
from vqapr.workspace import Workspace

KST = ZoneInfo("Asia/Seoul")


def _component(name: str, kind: ComponentKind, root: Path) -> ComponentRef:
    return ComponentRef.of(name, kind, root / f"{name}.py", "Thing", fingerprint="a" * 64)


def _agenda(agenda_id: str, role: OperationRole) -> OperationAgenda:
    return OperationAgenda.from_occurrences(
        agenda_id=agenda_id,
        role=role,
        timezone="Asia/Seoul",
        occurrences=(
            OperationOccurrence(
                f"{agenda_id}-1",
                role,
                LocalInstantDeclaration(
                    datetime(2024, 3, 5).date(), datetime(2024, 3, 5, 4).time(), "Asia/Seoul", 0, "+09:00"
                ),
            ),
        ),
        provenance="test",
    )


def _definition(**overrides: object) -> RunDefinition:
    declared: dict[str, object] = {
        "run_id": "krx-2024",
        "strategies": (StrategyEntry("ou-k0", ("no-short",)), StrategyEntry("ou-ff5")),
        "valuation": ValuationConfig("valuing", OperationRole.VALUATION),
        "monitoring": MonitoringPolicy("watching", OperationRole.MONITORING),
        "instruments": ("A", "B"),
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
    """Everything a run names, registered: three components, two bindings, three agendas."""
    space = Workspace.create(tmp_path)
    for name, kind in (
        ("ou-k0", ComponentKind.STRATEGY_MODEL),
        ("ou-ff5", ComponentKind.STRATEGY_MODEL),
        ("no-short", ComponentKind.CONSTRAINT),
        ("venue", ComponentKind.EXCHANGE),
    ):
        space.register_component(_component(name, kind, tmp_path))
    for agenda_id, role in (
        ("rebalance", OperationRole.STRATEGY_CALLBACK),
        ("valuing", OperationRole.VALUATION),
        ("watching", OperationRole.MONITORING),
    ):
        space.register_agenda(_agenda(agenda_id, role))
    space = Workspace.open(tmp_path)
    for name in ("ou-k0", "ou-ff5"):
        space.register_strategy_config(
            StrategyConfig(space.component(name), "rebalance", OperationRole.STRATEGY_CALLBACK)
        )
    space.register_valuation_config(ValuationConfig("valuing", OperationRole.VALUATION))
    space.register_monitoring_policy(MonitoringPolicy("watching", OperationRole.MONITORING))
    execution = tmp_path / "execution.parquet"
    execution.write_bytes(b"")
    space.register_execution_input(
        ExecutionInputRegistration.of(
            "venue-daily",
            ExecutionTableSpec(
                source=SourceSpec.of("venue-source", execution),
                trade_at_field="trade_at",
                instrument_field="instrument",
                is_tradable_field="is_tradable",
                price_fields={"close": "close"},
            ),
            FillConvention(FillSelector.SAME_DAY, datetime(2024, 1, 1, 15, 30).time(), "Asia/Seoul", "close"),
        )
    )
    return Workspace.open(tmp_path)


def test_a_run_registers_reads_back_and_is_idempotent(workspace: Workspace) -> None:
    definition = _definition()

    assert workspace.register_run(definition) is True
    assert workspace.register_run(definition) is False, "the same run again changes nothing"

    reopened = Workspace.open(workspace.project_root)
    assert reopened.run_definition("krx-2024") == definition
    assert [run.run_id for run in reopened.run_definitions] == ["krx-2024"]
    document = yaml.safe_load(reopened.path.read_text(encoding="utf-8"))
    assert set(document["runs"]["krx-2024"]["strategies"]) == {"ou-k0", "ou-ff5"}
    assert document["runs"]["krx-2024"]["strategies"]["ou-k0"] == {"constraints": ["no-short"]}


def test_a_changed_run_under_an_existing_id_is_refused_naming_the_run(
    workspace: Workspace,
) -> None:
    workspace.register_run(_definition())

    with pytest.raises(VqaprError) as refused:
        workspace.register_run(_definition(instruments=("A",)))
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"] == "workspace.run.register.conflict"
    assert "run_id 'krx-2024'" in failure["requirement"]


@pytest.mark.parametrize(
    ("override", "names"),
    [
        ({"strategies": (StrategyEntry("absent"),)}, "strategy 'absent'"),
        ({"strategies": (StrategyEntry("venue"),)}, "strategy 'venue'"),
        ({"strategies": (StrategyEntry("ou-k0", ("ou-ff5",)),)}, "constraint 'ou-ff5'"),
        ({"exchange": "ou-k0"}, "exchange 'ou-k0'"),
        ({"execution_input_id": "nope"}, "execution input 'nope'"),
    ],
)
def test_a_run_naming_anything_unregistered_is_refused_by_name(
    workspace: Workspace, override: dict[str, object], names: str
) -> None:
    """Refused at registration, so `vqapr run <id>` never meets an id it cannot resolve."""
    with pytest.raises(VqaprError) as refused:
        workspace.register_run(_definition(**override))
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"] == "workspace.run.register.reference"
    assert names in failure["requirement"], failure["requirement"]


def test_a_strategy_without_a_binding_is_refused(workspace: Workspace) -> None:
    workspace.register_component(_component("unbound", ComponentKind.STRATEGY_MODEL, Path(".")))

    with pytest.raises(VqaprError) as refused:
        Workspace.open(workspace.project_root).register_run(
            _definition(strategies=(StrategyEntry("unbound"),))
        )
    assert "bound to an agenda" in refused.value.as_dict()["failures"][0]["requirement"]


def test_a_run_holds_what_it_names_so_removal_is_refused_by_name(workspace: Workspace) -> None:
    workspace.register_run(_definition())

    assert workspace.references_to("component", "ou-ff5") == (
        "run 'krx-2024'",
        "strategy config 'ou-ff5'",
    )
    assert workspace.references_to("component", "no-short") == ("run 'krx-2024'",)
    assert workspace.references_to("component", "venue") == ("run 'krx-2024'",)
    assert workspace.references_to("agenda", "valuing") == ("run 'krx-2024'", "valuation config 'valuing'")
    assert workspace.references_to("strategy_config", "ou-k0") == ("run 'krx-2024'",)
    assert workspace.references_to("run", "krx-2024") == (), "nothing names a run"
    with pytest.raises(VqaprError, match="referenced"):
        workspace.remove("strategy_config", "ou-k0")
    assert workspace.remove("run", "krx-2024") is True
    assert workspace.remove("run", "krx-2024") is False
    assert workspace.remove("strategy_config", "ou-k0") is True


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
                "valuation": {"agenda_id": "valuing"},
                "monitoring": {"agenda_id": "watching"},
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


def test_a_malformed_run_declaration_is_refused_with_its_own_code(workspace: Workspace) -> None:
    document = {"runs": {"bad": {"instruments": ["A"], "strategies": {}}}}

    with pytest.raises(VqaprError) as refused:
        apply(document, workspace.project_root, base=workspace.project_root)
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"] == "declaration.read.run_invalid"
    assert failure["source"]["key_path"] == "runs.bad"
