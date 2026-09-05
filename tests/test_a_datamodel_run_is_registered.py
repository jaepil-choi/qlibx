"""A datamodel run is a registered run of one kind: `datamodels:` where a strategy run has
`strategies:`.

Record `148` (campaign Step 7, M2). A run holds strategies or datamodels, never both, and what a
datamodel run cannot use -- a venue, an execution input, an opening account -- it may not declare.
The output's shape (`dataset_id`, `value_fields`) is the entry's, not the model's (architecture
4.4), so it is validated where the run is declared and written back in the shape an author writes.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from vqapr.account.account import AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.declarations import apply
from vqapr.domain.errors import VqaprError
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import DataModelEntry, RunDefinition, StrategyEntry
from vqapr.workspace import Workspace

KST = ZoneInfo("Asia/Seoul")
SESSIONS = (date(2024, 3, 6), date(2024, 3, 7))
ENTRY = DataModelEntry("reversal", "reversal_2d", ("score",))
_RUN_READY: dict[str, object] = {
    "instruments": ["A", "B"],
    "start": "2024-03-06T00:00:00+09:00",
    "end": "2024-03-08T00:00:00+09:00",
    "timezone": "Asia/Seoul",
    "at": "16:00",
    "sessions": ["2024-03-06", "2024-03-07"],
}
"""A `runs.<id>` body with everything but its models, for each test to add one kind to."""
_DATAMODELS = {"reversal": {"dataset_id": "reversal_2d", "value_fields": ["score"]}}


def _definition(**overrides: object) -> RunDefinition:
    declared: dict[str, object] = {
        "run_id": "factors",
        "strategies": (),
        "datamodels": (ENTRY,),
        "instruments": ("A", "B"),
        "timezone": "Asia/Seoul",
        "at": time(16, 0),
        "sessions": SESSIONS,
        "start": datetime(2024, 3, 6, tzinfo=KST),
        "end": datetime(2024, 3, 8, tzinfo=KST),
    }
    declared.update(overrides)
    return RunDefinition(**declared)  # type: ignore[arg-type]


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """One datamodel and one strategy registered: the right kind and the wrong kind to name."""
    space = Workspace.create(tmp_path)
    for name, kind in (
        ("reversal", ComponentKind.DATA_MODEL),
        ("ou-k0", ComponentKind.STRATEGY_MODEL),
    ):
        space.register_component(
            ComponentRef.of(name, kind, tmp_path / f"{name}.py", "Thing", fingerprint="a" * 64)
        )
    return Workspace.open(tmp_path)


def test_a_run_holds_one_kind_of_model() -> None:
    """Strategies or datamodels: the two share sessions but nothing else a run declares."""
    with pytest.raises(ValueError, match="not both"):
        _definition(strategies=(StrategyEntry("ou-k0"),))
    with pytest.raises(ValueError, match="at least one strategy or at least one datamodel"):
        _definition(datamodels=())

    definition = _definition()
    assert definition.kind == "datamodel"
    assert definition.members == (ENTRY,)
    assert definition.member("reversal") is ENTRY
    assert definition.datamodel("reversal") is ENTRY
    with pytest.raises(KeyError, match="does not name datamodel 'absent'"):
        definition.datamodel("absent")
    with pytest.raises(KeyError, match="does not name strategy 'reversal'"):
        definition.strategy("reversal")


@pytest.mark.parametrize(
    "override",
    [
        {"exchange": "venue", "execution_input_id": "venue-daily"},
        {
            "initial_account_snapshot": AccountSnapshot(0, Decimal("1000"), {}),
            "initial_account_mode": AccountMode.LONG_ONLY,
        },
    ],
)
def test_a_datamodel_run_may_not_declare_what_it_cannot_use(override: dict[str, object]) -> None:
    """A datamodel sees no account and passes through no venue; a run saying otherwise lies."""
    with pytest.raises(ValueError, match="declares no exchange, execution_input or initial_acc"):
        _definition(**override)


def test_a_run_writes_each_output_dataset_once() -> None:
    with pytest.raises(ValueError, match="each output dataset at most once"):
        _definition(datamodels=(ENTRY, DataModelEntry("momentum", "reversal_2d", ("score",))))
    with pytest.raises(ValueError, match="each model at most once"):
        _definition(datamodels=(ENTRY, DataModelEntry("reversal", "other", ("score",))))


@pytest.mark.parametrize(
    ("value_fields", "error", "said"),
    [
        ((), ValueError, "at least one output field"),
        (("score", "score"), ValueError, "unique"),
        (("sc ore",), TypeError, "without whitespace"),
        (("",), TypeError, "non-empty strings"),
        (("available_at",), ValueError, "package-owned"),
        (("instrument",), ValueError, "package-owned"),
    ],
)
def test_the_entry_refuses_a_value_field_the_output_cannot_carry(
    value_fields: tuple[str, ...], error: type[Exception], said: str
) -> None:
    """`available_at` and `instrument` are the package's columns; a value field is the model's."""
    with pytest.raises(error, match=said):
        DataModelEntry("reversal", "reversal_2d", value_fields)


def test_the_entry_normalizes_its_opening_memory() -> None:
    assert DataModelEntry("reversal", "out", ("score",)).initial_model_memory is None
    assert DataModelEntry(
        "reversal", "out", ("score",), initial_model_memory={"calls": 10}
    ).initial_model_memory == {"calls": 10}


def test_a_datamodel_run_registers_reads_back_and_is_idempotent(workspace: Workspace) -> None:
    """Written in the shape an author writes, and read back as the same value."""
    definition = _definition(
        datamodels=(
            DataModelEntry("reversal", "reversal_2d", ("score",), initial_model_memory={"k": 1}),
        )
    )

    assert workspace.register_run(definition) is True
    assert workspace.register_run(definition) is False, "the same run again changes nothing"

    reopened = Workspace.open(workspace.project_root)
    assert reopened.run_definition("factors") == definition
    assert reopened.run_definition("factors").kind == "datamodel"
    written = yaml.safe_load(reopened.path.read_text(encoding="utf-8"))["runs"]["factors"]
    assert written["datamodels"] == {
        "reversal": {
            "dataset_id": "reversal_2d",
            "value_fields": ["score"],
            "initial_model_memory": {"k": 1},
        }
    }
    assert "strategies" not in written
    assert "initial_account" not in written


def test_a_declaration_document_registers_a_datamodel_run(workspace: Workspace) -> None:
    """The `runs:` section with `datamodels:`, through the same transaction as everything else."""
    document = {"runs": {"factors": {**_RUN_READY, "datamodels": _DATAMODELS}}}

    registered = apply(document, workspace.project_root, base=workspace.project_root)

    assert registered["runs"] == ["factors"]
    assert Workspace.open(workspace.project_root).run_definition("factors") == _definition()


@pytest.mark.parametrize(
    ("component_id", "names"),
    [
        ("absent", "datamodel 'absent'"),
        ("ou-k0", "datamodel 'ou-k0'"),
    ],
)
def test_a_run_naming_a_datamodel_that_is_not_one_is_refused_by_name(
    workspace: Workspace, component_id: str, names: str
) -> None:
    """Unregistered, or registered as a strategy: either way `vqapr run` would meet an id it
    cannot freeze, so registration refuses it first."""
    with pytest.raises(VqaprError) as refused:
        workspace.register_run(
            _definition(datamodels=(DataModelEntry(component_id, "out", ("score",)),))
        )
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"] == "workspace.run.register.reference"
    assert names in failure["requirement"], failure["requirement"]


@pytest.mark.parametrize(
    ("body", "said"),
    [
        (
            {**_RUN_READY, "strategies": {"ou-k0": None}, "datamodels": _DATAMODELS},
            "exactly one of `strategies:` or `datamodels:`",
        ),
        ({**_RUN_READY}, "exactly one of `strategies:` or `datamodels:`"),
        ({**_RUN_READY, "strategies": {}, "datamodels": {}}, "exactly one of `strategies:`"),
        (
            {**_RUN_READY, "strategies": {"ou-k0": None}, "execution_input": "venue-daily"},
            "exchange and execution_input_id must be declared together",
        ),
        (
            {**_RUN_READY, "datamodels": _DATAMODELS, "exchange": "venue"},
            "a datamodel run declares no exchange",
        ),
        (
            {
                **_RUN_READY,
                "datamodels": _DATAMODELS,
                "initial_account": {"cash": "1000", "mode": "long_only", "positions": {}},
            },
            "a datamodel run declares no initial_account",
        ),
    ],
)
def test_a_document_declaring_the_wrong_kind_or_half_a_kind_is_refused(
    workspace: Workspace, body: dict[str, object], said: str
) -> None:
    """Both sections, neither, a strategy run with half its venue, a datamodel run with one: each
    is refused as a malformed run before anything it names is looked up."""
    document = {"runs": {"bad": body}}

    with pytest.raises(VqaprError) as refused:
        apply(document, workspace.project_root, base=workspace.project_root)
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"] == "declaration.read.run_invalid"
    assert failure["source"]["key_path"] == "runs.bad"
    assert said in failure["observed"], failure["observed"]
