"""`workspace.py` — project 선언을 명령 사이에 보존한다."""

from __future__ import annotations

from pathlib import Path

import pytest

from vqapr.data.datasets import DatasetRegistration
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


def test_registration_survives_reopening_the_workspace(tmp_path: Path) -> None:
    expected = _registration()
    workspace = Workspace.create(tmp_path)

    assert workspace.register_dataset(expected) is True

    reopened = Workspace.open(tmp_path)
    assert reopened.dataset("price_daily") == expected


def test_two_datasets_are_both_queryable_after_reopen(tmp_path: Path) -> None:
    first = _registration()
    second = _registration("price_adjusted", fields={"close": "adjusted_close"})
    workspace = Workspace.create(tmp_path)

    workspace.register_dataset(first)
    workspace.register_dataset(second)

    reopened = Workspace.open(tmp_path)
    assert {item.dataset_id: item for item in reopened.datasets} == {
        first.dataset_id: first,
        second.dataset_id: second,
    }


def test_identical_reregistration_is_an_idempotent_noop(tmp_path: Path) -> None:
    registration = _registration()
    workspace = Workspace.create(tmp_path)
    assert workspace.register_dataset(registration) is True
    before = workspace.path.read_bytes()

    assert workspace.register_dataset(_registration()) is False
    assert workspace.path.read_bytes() == before


def test_conflicting_reregistration_fails_without_mutation(tmp_path: Path) -> None:
    original = _registration()
    workspace = Workspace.create(tmp_path)
    workspace.register_dataset(original)
    before = workspace.path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        workspace.register_dataset(_registration(fields={"open": "open"}))

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

    first.register_dataset(_registration())
    second.register_dataset(_registration("fundamentals"))

    assert [str(item.dataset_id) for item in Workspace.open(first_root).datasets] == ["price_daily"]
    assert [str(item.dataset_id) for item in Workspace.open(second_root).datasets] == [
        "fundamentals"
    ]
