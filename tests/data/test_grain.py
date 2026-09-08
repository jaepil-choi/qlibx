"""A dataset declares what one of its rows IS, and nothing reads a dataset that has not.

`docs/design/the-panel-the-surface-and-the-run.md` §2.2 and §7-3; campaign Step 5 (M5.1).

Three grains: `instrument_instant` (a date x ticker table; a panel can be built), `instant`
(no instrument axis), `rows` (the vendor's long grain). Declared, never derived -- and refused
when absent, naming the three values *and* what changed: on a panel grain `RowsLookback(n)` is
the last n rows of the pivoted table, the same instants for every name. Every registration written
before `grain` existed is edited once by hand, and that refusal is where its author hears it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vqapr.data import scan
from vqapr.data.datasets import (
    GRAIN_STAGE,
    DatasetRegistration,
    Grain,
    check_key,
    require_declared,
)
from vqapr.data.sources import SourceSpec
from vqapr.declarations import apply
from vqapr.domain.errors import VqaprError
from vqapr.public import register_dataset
from vqapr.workspace import Workspace


def _registration(grain: object = Grain.INSTRUMENT_INSTANT, **overrides) -> DatasetRegistration:
    kwargs = {
        "instrument_field": "instrument",
        "available_at": "available_at",
        "key_fields": ("available_at", "instrument"),
        "fields": {"close": "close"},
        # `conftest._ROWS` writes `close` as an integer literal, so `hive_parquet` holds INTEGER.
        "field_types": {"close": "INTEGER"},
        "grain": grain,
    }
    kwargs.update(overrides)
    return DatasetRegistration.of("price_daily", "s", **kwargs)


# --------------------------------------------------------------------------------------
# The declaration.
# --------------------------------------------------------------------------------------


def test_a_registration_without_a_grain_is_refused_naming_the_three_and_the_change() -> None:
    with pytest.raises(ValueError) as refused:
        _registration(grain=None)
    message = str(refused.value)
    for name in ("instrument_instant", "instant", "rows"):
        assert name in message
    assert "RowsLookback" in message and "InstantsLookback" in message


def test_an_unknown_grain_is_refused_the_same_way() -> None:
    with pytest.raises(ValueError, match="instrument_instant, instant, rows"):
        _registration(grain="wide")


def test_a_grain_may_be_spelled_as_its_name() -> None:
    assert _registration(grain="rows").grain is Grain.ROWS
    assert (
        _registration(
            grain=Grain.INSTANT, instrument_field=None, key_fields=("available_at",)
        ).grain
        is Grain.INSTANT
    )


def test_the_grain_and_the_instrument_axis_must_agree() -> None:
    with pytest.raises(ValueError, match="needs an instrument_field"):
        _registration(grain=Grain.INSTRUMENT_INSTANT, instrument_field=None)
    with pytest.raises(ValueError, match="has no instrument axis"):
        _registration(grain=Grain.INSTANT)


def test_the_uniqueness_axis_is_the_grains_not_the_authors() -> None:
    """§17.1.2: what registration proves unique follows the grain."""
    assert _registration(grain=Grain.INSTRUMENT_INSTANT, key_fields=("a", "b", "c")).key_axis() == (
        "available_at",
        "instrument",
    )
    assert _registration(
        grain=Grain.INSTANT, instrument_field=None, key_fields=("a", "b")
    ).key_axis() == ("available_at",)
    assert _registration(grain=Grain.ROWS, key_fields=("a", "b", "c")).key_axis() == ("a", "b", "c")


def test_check_key_asks_the_scan_for_the_grains_axis(
    hive_parquet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[str, ...]] = []
    original = scan.key_check

    def capturing(spec, fields):
        asked.append(tuple(fields))
        return original(spec, fields)

    monkeypatch.setattr(scan, "key_check", capturing)
    spec = SourceSpec.of("s", hive_parquet, hive_partitioned=True)

    check_key(_registration(grain=Grain.ROWS, key_fields=("session_date", "instrument")), spec)
    check_key(_registration(grain=Grain.INSTRUMENT_INSTANT, key_fields=("session_date",)), spec)

    assert asked == [("session_date", "instrument"), ("available_at", "instrument")]


def test_a_grouped_projection_on_a_panel_grain_is_unique_by_construction(
    hive_parquet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`GROUP BY` yields one row per pair; there is nothing to scan for."""
    monkeypatch.setattr(scan, "key_check", lambda *a, **k: pytest.fail("scanned"))
    spec = SourceSpec.of("s", hive_parquet, hive_partitioned=True)
    grouped = _registration().with_aggregation(True)

    assert check_key(grouped, spec).ok


# --------------------------------------------------------------------------------------
# The document, and what a document written before grain existed can still do.
# --------------------------------------------------------------------------------------


def _dataset_body(parquet: Path, *, grain: str | None) -> dict[str, object]:
    body: dict[str, object] = {
        "source_id": "src",
        "path": str(parquet),
        "instrument_field": "instrument",
        "available_at": "available_at",
        "key_fields": ["available_at", "instrument"],
        "fields": {"close": "close"},
        "field_types": {"close": "DOUBLE"},
    }
    if grain is not None:
        body["grain"] = grain
    return body


def test_a_declaration_document_without_grain_is_refused_with_its_own_code(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    with pytest.raises(VqaprError) as refused:
        apply(
            {"datasets": {"px": _dataset_body(model_price_parquet, grain=None)}},
            tmp_path,
            base=tmp_path,
        )
    payload = refused.value.as_dict()
    codes = [failure["code"] for failure in payload["failures"]]
    assert codes == ["declaration.read.grain_undeclared"]
    fix = payload["failures"][0]["fix"]
    assert "instrument_instant" in fix and "rows" in fix and "RowsLookback" in fix
    assert not (tmp_path / ".vqapr").exists(), "a refused document creates nothing"


def test_a_declared_grain_round_trips_through_the_workspace(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    apply(
        {"datasets": {"px": _dataset_body(model_price_parquet, grain="instrument_instant")}},
        tmp_path,
        base=tmp_path,
    )
    assert Workspace.open(tmp_path).dataset("px").grain is Grain.INSTRUMENT_INSTANT


def test_a_workspace_written_before_grain_still_opens_and_refuses_reads(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """Write-forward, one release decodable -- and not silently `rows` (§7-3)."""
    register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "px",
            "src",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
            field_types={"close": "DOUBLE"},
            grain="instrument_instant",
        ),
        SourceSpec.of("src", model_price_parquet),
    )
    document_path = tmp_path / ".vqapr" / "workspace.yaml"
    document = yaml.safe_load(document_path.read_text(encoding="utf-8"))
    del document["datasets"]["px"]["grain"]
    document_path.write_text(yaml.safe_dump(document), encoding="utf-8")

    reopened = Workspace.open(tmp_path)
    registration = reopened.dataset("px")
    assert registration.grain is None, "decoded as undeclared, never as rows"

    with pytest.raises(VqaprError) as refused:
        require_declared(registration)
    payload = refused.value.as_dict()
    assert payload["stage"] == GRAIN_STAGE
    assert [f["code"] for f in payload["failures"]] == [f"{GRAIN_STAGE}.undeclared"]
    assert "RowsLookback" in payload["failures"][0]["fix"]

    # Registering it again, with a grain, is the repair -- and it is an ordinary registration.
    register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "px",
            "src",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
            field_types={"close": "DOUBLE"},
            grain="instrument_instant",
        ),
        SourceSpec.of("src", model_price_parquet),
    )
    assert Workspace.open(tmp_path).dataset("px").grain is Grain.INSTRUMENT_INSTANT
