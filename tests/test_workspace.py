"""`workspace.py` — project 선언을 명령 사이에 보존한다."""

from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import VqaprError
from vqapr.exchange.conventions import FillConvention
from vqapr.exchange.execution_table import ExecutionInputRegistration, ExecutionTableSpec
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.workspace import Workspace


def _registration(raw_id: str = "price_daily", **overrides) -> DatasetRegistration:
    kwargs = {
        "instrument_field": "instrument",
        "available_at": "available_at",
        "key_fields": ("session_date", "instrument"),
        "fields": {"close": "close", "session_date": "session_date"},
    }
    kwargs.update(overrides)
    return DatasetRegistration.of(raw_id, "prices", **kwargs)


def _source(**overrides) -> SourceSpec:
    kwargs = {"hive_partitioned": True}
    kwargs.update(overrides)
    return SourceSpec.of("prices", "prepared/price_daily", **kwargs)


def _execution(
    path: Path, raw_id: str = "krx-daily", *, trade_price: str = "close"
) -> ExecutionInputRegistration:
    return ExecutionInputRegistration.of(
        raw_id,
        ExecutionTableSpec(
            source=SourceSpec.of("krx-execution", path),
            trade_at_field="trade_at",
            instrument_field="instrument",
            is_tradable_field="is_tradable",
            price_fields={"open": "open", "close": "close"},
        ),
        FillConvention(
            offset_sessions=0,
            local_time=time(15, 30),
            timezone="Asia/Seoul",
            trade_price=trade_price,
        ),
    )


def test_registration_survives_reopening_the_workspace(tmp_path: Path) -> None:
    expected = _registration()
    workspace = Workspace.create(tmp_path)

    assert workspace.register_dataset(expected, _source()) is True

    reopened = Workspace.open(tmp_path)
    assert reopened.dataset("price_daily") == expected


def test_two_datasets_are_both_queryable_after_reopen(tmp_path: Path) -> None:
    first = _registration()
    second = _registration("price_adjusted", fields={"close": "adjusted_close"})
    workspace = Workspace.create(tmp_path)

    workspace.register_dataset(first, _source())
    workspace.register_dataset(second, _source())

    reopened = Workspace.open(tmp_path)
    assert {item.dataset_id: item for item in reopened.datasets} == {
        first.dataset_id: first,
        second.dataset_id: second,
    }


def test_identical_reregistration_is_an_idempotent_noop(tmp_path: Path) -> None:
    registration = _registration()
    workspace = Workspace.create(tmp_path)
    assert workspace.register_dataset(registration, _source()) is True
    before = workspace.path.read_bytes()

    assert workspace.register_dataset(_registration(), _source()) is False
    assert workspace.path.read_bytes() == before


def test_conflicting_reregistration_fails_without_mutation(tmp_path: Path) -> None:
    original = _registration()
    workspace = Workspace.create(tmp_path)
    workspace.register_dataset(original, _source())
    before = workspace.path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        workspace.register_dataset(_registration(fields={"open": "open"}), _source())

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["stage"] == "workspace.dataset.register"
    assert [failure["code"] for failure in payload["failures"]] == [
        "workspace.dataset.register.conflict"
    ]
    assert workspace.path.read_bytes() == before
    assert Workspace.open(tmp_path).dataset("price_daily") == original


def test_opening_a_missing_workspace_is_a_structured_failure(tmp_path: Path) -> None:
    with pytest.raises(VqaprError) as caught:
        Workspace.open(tmp_path)

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.open.missing"


def test_opening_malformed_yaml_is_a_structured_failure(tmp_path: Path) -> None:
    path = tmp_path / ".vqapr" / "workspace.yaml"
    path.parent.mkdir()
    path.write_text("datasets: [not, a, mapping]", encoding="utf-8")

    with pytest.raises(VqaprError) as caught:
        Workspace.open(tmp_path)

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.open.invalid"


def test_explicit_workspaces_do_not_share_declarations(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = Workspace.create(first_root)
    second = Workspace.create(second_root)

    first.register_dataset(_registration(), _source())
    second.register_dataset(_registration("fundamentals"), _source())

    assert [str(item.dataset_id) for item in Workspace.open(first_root).datasets] == ["price_daily"]
    assert [str(item.dataset_id) for item in Workspace.open(second_root).datasets] == [
        "fundamentals"
    ]


def test_direct_construction_cannot_bypass_an_existing_workspace(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    workspace.register_dataset(_registration(), _source())
    before = workspace.path.read_bytes()

    with pytest.raises(TypeError, match=r"Workspace\.create.*Workspace\.open"):
        Workspace(tmp_path, {})

    assert workspace.path.read_bytes() == before


def test_stale_instance_merges_with_current_durable_state(tmp_path: Path) -> None:
    current = Workspace.create(tmp_path)
    current.register_dataset(_registration("one"), _source())
    stale = Workspace.open(tmp_path)

    current.register_dataset(_registration("two"), _source())
    stale.register_dataset(_registration("three"), _source())

    assert [str(item.dataset_id) for item in Workspace.open(tmp_path).datasets] == [
        "one",
        "three",
        "two",
    ]


def test_idempotent_registration_rechecks_that_workspace_still_exists(tmp_path: Path) -> None:
    registration = _registration()
    workspace = Workspace.create(tmp_path)
    workspace.register_dataset(registration, _source())
    workspace.path.unlink()

    with pytest.raises(VqaprError) as caught:
        workspace.register_dataset(registration, _source())

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.open.missing"
    assert not workspace.path.exists()


def test_source_spec_survives_reopening_the_workspace(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    source = _source()

    workspace.register_dataset(_registration(), source)

    assert Workspace.open(tmp_path).source("prices") == source


def test_invalid_dataset_id_lookup_is_a_structured_failure(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)

    with pytest.raises(VqaprError) as caught:
        workspace.dataset("bad id")

    payload = caught.value.as_dict()
    assert payload["stage"] == "workspace.dataset.lookup"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.dataset.lookup.invalid"


def test_missing_dataset_lookup_is_a_structured_failure(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)

    with pytest.raises(VqaprError) as caught:
        workspace.dataset("missing")

    payload = caught.value.as_dict()
    assert payload["stage"] == "workspace.dataset.lookup"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.dataset.lookup.missing"


def test_registration_rejects_a_mismatched_source_without_mutation(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    before = workspace.path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        workspace.register_dataset(_registration(), SourceSpec.of("other", "prepared/other"))

    payload = caught.value.as_dict()
    assert payload["stage"] == "workspace.dataset.register"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.dataset.register.source_mismatch"
    assert workspace.path.read_bytes() == before


def test_conflicting_source_spec_fails_without_mutation(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    workspace.register_dataset(_registration(), _source())
    before = workspace.path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        workspace.register_dataset(
            _registration("price_adjusted"),
            _source(hive_partitioned=False),
        )

    payload = caught.value.as_dict()
    assert payload["stage"] == "workspace.dataset.register"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.dataset.register.source_conflict"
    assert workspace.path.read_bytes() == before


@pytest.mark.parametrize(
    ("raw_source_id", "code"),
    [
        ("bad id", "workspace.source.lookup.invalid"),
        ("missing", "workspace.source.lookup.missing"),
    ],
)
def test_source_lookup_failures_are_structured(
    tmp_path: Path, raw_source_id: str, code: str
) -> None:
    workspace = Workspace.create(tmp_path)

    with pytest.raises(VqaprError) as caught:
        workspace.source(raw_source_id)

    payload = caught.value.as_dict()
    assert payload["stage"] == "workspace.source.lookup"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == code


def test_execution_input_round_trips_through_workspace(
    tmp_path: Path, execution_parquet: Path
) -> None:
    workspace = Workspace.create(tmp_path)
    expected = _execution(execution_parquet)

    assert workspace.register_execution_input(expected) is True

    reopened = Workspace.open(tmp_path)
    assert reopened.execution_input("krx-daily") == expected
    assert reopened.execution_inputs == (expected,)
    assert reopened.source("krx-execution") == expected.table.source


def test_execution_input_registration_is_idempotent(
    tmp_path: Path, execution_parquet: Path
) -> None:
    workspace = Workspace.create(tmp_path)
    registration = _execution(execution_parquet)

    assert workspace.register_execution_input(registration) is True
    before = workspace.path.read_bytes()
    assert workspace.register_execution_input(registration) is False
    assert workspace.path.read_bytes() == before


def test_conflicting_execution_input_fails_without_mutation(
    tmp_path: Path, execution_parquet: Path
) -> None:
    workspace = Workspace.create(tmp_path)
    workspace.register_execution_input(_execution(execution_parquet))
    before = workspace.path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        workspace.register_execution_input(_execution(execution_parquet, trade_price="open"))

    assert caught.value.stage == "workspace.execution_input.register"
    assert caught.value.mutation is False
    assert caught.value.failures[0].code == "workspace.execution_input.register.conflict"
    assert workspace.path.read_bytes() == before


def test_legacy_workspace_without_execution_inputs_still_opens(tmp_path: Path) -> None:
    workspace_path = tmp_path / ".vqapr" / "workspace.yaml"
    workspace_path.parent.mkdir(parents=True)
    workspace_path.write_text("sources: {}\ndatasets: {}\n", encoding="utf-8")

    workspace = Workspace.open(tmp_path)

    assert workspace.datasets == ()
    assert workspace.execution_inputs == ()


def test_datamodel_component_round_trips_through_workspace(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    expected = ComponentRef.of(
        "reversal",
        ComponentKind.DATA_MODEL,
        tmp_path / "reversal.py",
        "ReversalModel",
        config={"window": 20},
        fingerprint="a" * 64,
    )

    assert workspace.register_component(expected) is True
    assert Workspace.open(tmp_path).component("reversal") == expected
    assert Workspace.open(tmp_path).components == (expected,)


def test_legacy_workspace_without_components_still_opens(tmp_path: Path) -> None:
    workspace_path = tmp_path / ".vqapr" / "workspace.yaml"
    workspace_path.parent.mkdir(parents=True)
    workspace_path.write_text("sources: {}\ndatasets: {}\nexecution_inputs: {}\n", encoding="utf-8")

    workspace = Workspace.open(tmp_path)

    assert workspace.components == ()
