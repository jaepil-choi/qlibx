"""`workspace.py` — project 선언을 명령 사이에 보존한다."""

from __future__ import annotations

from pathlib import Path

import pytest

from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import VqaprError
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
