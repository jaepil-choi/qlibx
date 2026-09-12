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

from vqapr.component.reference import ComponentRef
from vqapr.data.dataset import DatasetRegistration
from vqapr.data.source import SourceSpec
from vqapr.domain.account import AccountMode, AccountSnapshot
from vqapr.domain.errors import VqaprError
from vqapr.domain.wiring import Role
from vqapr.workspace.registration import apply
from vqapr.workspace.registry import Workspace
from vqapr.workspace.run_definition import (
    DataModelEntry,
    RunDefinition,
    RunExecution,
    RunFill,
    StrategyEntry,
)

KST = ZoneInfo("Asia/Seoul")
SESSIONS = (date(2024, 3, 6), date(2024, 3, 7))
ENTRY = DataModelEntry("reversal", ("score",))
_RUN_READY: dict[str, object] = {
    "instruments": ["A", "B"],
    "start": "2024-03-06T00:00:00+09:00",
    "end": "2024-03-08T00:00:00+09:00",
    "timezone": "Asia/Seoul",
    "schedule": {"every": "1d", "at": "16:00", "days_from": "prices"},
    "writes": "reversal_2d",
}
"""A `runs.<id>` body with everything but its models, for each test to add one kind to."""
_DATAMODELS = {"reversal": {"dataset_id": "reversal_2d", "value_fields": ["score"]}}


def _definition(**overrides: object) -> RunDefinition:
    declared: dict[str, object] = {
        "run_id": "factors",
        "writes": "reversal_2d",
        "datamodel": ENTRY,
        "instruments": ("A", "B"),
        "timezone": "Asia/Seoul",
        "schedule": {"every": "1d", "at": time(16, 0), "days_from": "prices"},
        "start": datetime(2024, 3, 6, tzinfo=KST),
        "end": datetime(2024, 3, 8, tzinfo=KST),
    }
    declared.update(overrides)
    return RunDefinition(**declared)  # type: ignore[arg-type]


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """One datamodel and one strategy registered: the right kind and the wrong kind to name --
    and the dataset a datamodel run takes its trading days from (design §3.3)."""
    space = Workspace.create(tmp_path)
    with Workspace.transaction(space) as t:
        t.register_dataset(
            DatasetRegistration.of(
                "prices",
                "prices-source",
                instrument_field="instrument",
                available_at="available_at",
                grain="instrument_instant",
                key_fields=("available_at", "instrument"),
                fields={"close": "close"},
                field_types={"close": "DOUBLE"},
            ).with_span(datetime(2024, 3, 1, tzinfo=KST), datetime(2024, 3, 31, tzinfo=KST)),
            SourceSpec.of("prices-source", tmp_path / "prices"),
        )
    for name, kind in (
        ("reversal", Role.DATA_MODEL),
        ("ou-k0", Role.STRATEGY_MODEL),
    ):
        with Workspace.transaction(space) as t:
            t.register_component(
                ComponentRef.of(name, kind, tmp_path / f"{name}.py", "Thing", fingerprint="a" * 64)
            )
    return Workspace.open(tmp_path)


def test_a_run_holds_one_kind_of_model() -> None:
    """Strategies or datamodels: the two share sessions but nothing else a run declares."""
    with pytest.raises(ValueError, match="not both"):
        _definition(strategy=StrategyEntry("ou-k0"))
    with pytest.raises(ValueError, match="not both and not neither"):
        _definition(datamodel=None)

    definition = _definition()
    assert definition.kind == "datamodel"
    assert definition.member is ENTRY
    assert definition.datamodel is ENTRY
    assert definition.strategy is None


@pytest.mark.parametrize(
    "override",
    [
        {
            "exchange": "venue",
            "execution": RunExecution(
                dataset="venue-daily",
                trade_price="close",
                fill=RunFill(at=time(15, 30)),
            ),
        },
        {
            "initial_account_snapshot": AccountSnapshot(0, Decimal("1000"), {}),
            "initial_account_mode": AccountMode.LONG_ONLY,
        },
    ],
)
def test_a_datamodel_run_may_not_declare_what_it_cannot_use(override: dict[str, object]) -> None:
    """A datamodel sees no account and passes through no venue; a run saying otherwise lies."""
    with pytest.raises(ValueError, match="declares no exchange, execution or initial_acc"):
        _definition(**override)


def test_a_run_writes_one_output_dataset() -> None:
    """A run is one arrow of the graph, so it writes one thing and two members are refused."""
    with pytest.raises(ValueError, match="names exactly one model"):
        _definition(
            datamodels={
                "reversal": {"dataset_id": "reversal_2d", "value_fields": ["score"]},
                "momentum": {"dataset_id": "momentum_2d", "value_fields": ["score"]},
            }
        )


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
        DataModelEntry("reversal", value_fields)


def test_the_entry_normalizes_its_opening_memory() -> None:
    # `{}` unless declared (`docs/issues/089`, record `215`): the first callback finds a mapping.
    assert DataModelEntry("reversal", ("score",)).initial_model_memory == {}
    assert DataModelEntry("reversal", ("score",), initial_model_memory={"calls": 10}).initial_model_memory == {"calls": 10}


def test_a_datamodel_run_registers_reads_back_and_is_idempotent(workspace: Workspace) -> None:
    """Written in the shape an author writes, and read back as the same value."""
    definition = _definition(
        datamodel=DataModelEntry("reversal", ("score",), initial_model_memory={"k": 1}), writes="reversal_2d"
    )

    with Workspace.transaction(workspace) as t:
        assert t.register_run(definition) is True
    with Workspace.transaction(workspace) as t:
        assert t.register_run(definition) is False, "the same run again changes nothing"

    reopened = Workspace.open(workspace.project_root)
    assert reopened.run_definition("factors") == definition
    assert reopened.run_definition("factors").kind == "datamodel"
    written = yaml.safe_load(reopened.path.read_text(encoding="utf-8"))["runs"]["factors"]
    # The stored spelling since 2026-09-09: `writes` on the run, the one model as a block.
    assert written["writes"] == "reversal_2d"
    assert written["datamodel"] == {
        "component": "reversal",
        "value_fields": ["score"],
        "initial_model_memory": {"k": 1},
    }
    assert "strategy" not in written and "datamodels" not in written
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
    with pytest.raises(VqaprError) as refused, Workspace.transaction(workspace) as t:
        t.register_run(
            _definition(datamodel=DataModelEntry(component_id, ("score",)), writes="out")
        )
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"] == "run.reference_invalid"
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
            {
                **_RUN_READY,
                "schedule": {"every": "1d", "at": "16:00"},
                "strategies": {"ou-k0": None},
                "execution": {
                    "dataset": "venue-daily",
                    "trade_price": "close", "fill": {"at": "15:30"},
                },
            },
            "exchange and execution must be declared together",
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
    assert failure["code"] == "declaration.run_invalid"
    assert failure["source"]["key_path"] == "runs.bad"
    assert said in failure["observed"], failure["observed"]
