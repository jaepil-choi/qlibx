"""An alias over several fields is one scan, and the rows come back already joined.

`docs/issues/046`, first half (lane D of the read-path campaign). A `DataRequirement` names one
field, so an alias over three fields is three requirements; reading them one at a time was three
scans of one window and a join in Python on `(available_at, instrument)`. The window SQL already
ranks each field's own last N rows separately, so one statement over the alias's `fields` returns
exactly what the joined reads did -- and records one access naming every field.

Measured by counting `scan.observation_rows` calls, which is the statement, not by timing.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vqapr.authoring import DatasetInput, RowsLookback
from vqapr.data import store as store_module
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.models.calls import requirements_for
from vqapr.models.contexts import DataModelContext
from vqapr.public import register_dataset
from vqapr.workspace import Workspace

KST = ZoneInfo("Asia/Seoul")
AT = datetime(2024, 3, 7, 16, tzinfo=KST)


def _workspace(tmp_path: Path, parquet: Path) -> Workspace:
    register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "price_daily",
            "prices",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            # Three declared fields on one dataset -- the `ff_factors` shape. The third is an
            # expression, which is what a field is since `docs/issues/049`.
            fields={"close": "close", "volume": "volume", "double_close": "close * 2"},
        ),
        SourceSpec.of("prices", parquet),
    )
    return Workspace.open(tmp_path)


@pytest.fixture
def scans(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Every `observation_rows` statement issued, by the fields it asked for."""
    issued: list[dict[str, str]] = []
    original = store_module.scan.observation_rows

    def counting(spec, **kwargs):
        issued.append(dict(kwargs["fields"]))
        return original(spec, **kwargs)

    monkeypatch.setattr(store_module.scan, "observation_rows", counting)
    return issued


def _window(workspace: Workspace, *requirements: DataRequirement) -> ModelWindow:
    return ModelWindow(
        evaluation_time=AT,
        instruments=("A", "B"),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=requirements,
        consumer_id="reversal",
    )


def test_three_declared_fields_are_one_statement_and_one_access(
    tmp_path: Path, model_price_parquet: Path, scans: list[dict[str, str]]
) -> None:
    workspace = _workspace(tmp_path, model_price_parquet)
    alias = DatasetInput(
        dataset_id="price_daily",
        fields=("close", "volume", "double_close"),
        lookback=RowsLookback(rows=2),
    )
    requirements = requirements_for(alias)
    assert len(requirements) == 3, "a requirement names one field"
    window = _window(workspace, *requirements)

    rows = DataModelContext(window=window, reads={"prices": alias}).read("prices")

    assert len(scans) == 1, scans
    assert set(scans[0]) == {"close", "volume", "double_close"}
    assert len(window.accesses) == 1
    assert window.accesses[0].fields == ("close", "volume", "double_close")
    a_rows = [row for row in rows if row.instrument_id == "A"]
    assert [(row.available_at.day, row.values["close"], row.values["volume"]) for row in a_rows] == [
        (5, None, 10.0),
        (6, 103.0, None),
        (7, 105.0, 12.0),
    ], "each field keeps its own last-N window; the rows are the union, joined on the instant"
    assert [row.values["double_close"] for row in a_rows] == [None, 206.0, 210.0]


def test_the_fused_read_returns_what_the_joined_reads_did(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """The rows one statement returns are the rows the per-field reads returned, joined."""
    workspace = _workspace(tmp_path, model_price_parquet)
    close = DataRequirement.of("price_daily", "close", lookback=RowsLookback(2))
    volume = DataRequirement.of("price_daily", "volume", lookback=RowsLookback(2))

    fused = _window(workspace, close, volume).declared((close, volume)).rows
    separate = {
        (row["available_at"], row["instrument"]): dict(row)
        for requirement in (close, volume)
        for row in _window(workspace, close, volume).observations(requirement).rows
    }
    # Fold the per-field batches the way the deleted Python join did.
    joined: dict[tuple, dict] = {}
    for requirement in (close, volume):
        for row in _window(workspace, close, volume).observations(requirement).rows:
            key = (row["available_at"], row["instrument"])
            merged = joined.setdefault(
                key, {"available_at": key[0], "instrument": key[1], "close": None, "volume": None}
            )
            merged[requirement.field_id] = row[requirement.field_id]

    assert [dict(row) for row in fused] == [joined[key] for key in sorted(joined)]
    assert separate, "the per-field reads still work on their own"


def test_a_read_across_two_datasets_or_two_lookbacks_is_refused(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """One statement serves one dataset and one lookback; an alias cannot span either."""
    workspace = _workspace(tmp_path, model_price_parquet)
    close_2 = DataRequirement.of("price_daily", "close", lookback=RowsLookback(2))
    volume_3 = DataRequirement.of("price_daily", "volume", lookback=RowsLookback(3))

    with pytest.raises(ValueError, match="one lookback"):
        _window(workspace, close_2, volume_3).declared((close_2, volume_3))
    with pytest.raises(ValueError, match="at least one"):
        _window(workspace, close_2).declared(())


def test_an_undeclared_field_in_the_alias_is_refused_like_a_single_one(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace = _workspace(tmp_path, model_price_parquet)
    close = DataRequirement.of("price_daily", "close", lookback=RowsLookback(2))
    volume = DataRequirement.of("price_daily", "volume", lookback=RowsLookback(2))

    from vqapr.domain.errors import VqaprError

    with pytest.raises(VqaprError, match="undeclared"):
        _window(workspace, close).declared((close, volume))
