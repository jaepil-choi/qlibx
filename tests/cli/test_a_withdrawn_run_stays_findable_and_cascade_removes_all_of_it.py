"""`docs/issues/archive/081`, both halves, on a datamodel run that really ran.

Withdrawing a run definition left its records readable and unfindable: `list runs` walked the
registrations, so the id vanished from the surface while `rm run` still needed it. Owner ruling,
2026-09-05: deletion must be easy -- `rm run --cascade` removes all of it in one gesture, with
`080`'s enumeration underneath it so nothing is left behind unseen, and the two smaller halves
(`list runs` shows orphans, `rm run-definition` says what it left) beside it.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from vqapr.cli.main import main

_MODEL = """from vqapr import public as vq

class Ratio(vq.DataModel):
    def inputs(self):
        return {"prices": vq.DatasetInput(
            dataset_id='price_daily', fields=('close',), lookback=vq.RowsLookback(rows=2)
        )}

    def compute(self, context):
        window = context.read("prices", "close")
        return [{"instrument": name, "score": 1.0} for name in window.instruments]
"""


def _cli(capsys: pytest.CaptureFixture[str], project: Path, *argv: str) -> tuple[int, dict]:
    code = main(["--project-root", str(project), *argv])
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _prices(root: Path) -> Path:
    parquet = root / "price_daily.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT available_at, instrument, close::DOUBLE AS close FROM (VALUES
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', 100.0),
              (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', 103.0),
              (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'A', 105.0)
            ) AS t(available_at, instrument, close))
            TO '{parquet.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    return parquet


def _run_block(run_id: str, dataset_id: str) -> str:
    return f"""  {run_id}:
    instruments: [A]
    start: "2024-03-06T00:00:00+09:00"
    end: "2024-03-08T00:00:00+09:00"
    timezone: Asia/Seoul
    schedule: {{every: 1d, at: "16:00", days_from: price_daily}}
    datamodels:
      ratio:
        dataset_id: {dataset_id}
        value_fields: [score]
"""


def _declaration(root: Path, *runs: tuple[str, str]) -> Path:
    model = root / "model.py"
    model.write_text(_MODEL, encoding="utf-8")
    path = root / "declaration.yaml"
    path.write_text(
        f"""datasets:
  price_daily:
    source_id: prices
    path: {_prices(root).as_posix()}
    instrument_field: instrument
    available_at: available_at
    grain: instrument_instant
    key_fields: [available_at, instrument]
    fields:
      close: close
    field_types:
      close: DOUBLE
components:
  ratio:
    kind: datamodel
    path: {model.as_posix()}
    object_name: Ratio
runs:
""" + "".join(_run_block(run_id, dataset_id) for run_id, dataset_id in runs),
        encoding="utf-8",
    )
    return path


def _runs(capsys: pytest.CaptureFixture[str], project: Path) -> dict[str, dict]:
    code, listed = _cli(capsys, project, "list", "runs")
    assert code == 0, listed
    return {row["run_id"]: row for row in listed["items"]}


def test_a_withdrawn_definition_leaves_an_orphan_the_surface_still_shows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    declaration = _declaration(tmp_path, ("alpha", "alpha_values"))
    code, _ = _cli(capsys, tmp_path, "register", str(declaration))
    assert code == 0
    code, ran = _cli(capsys, tmp_path, "run", "alpha")
    assert code == 0, ran
    record = ran["datamodels"]["ratio"]["record"]
    assert _runs(capsys, tmp_path)["alpha"]["status"] == "registered"

    code, withdrawn = _cli(capsys, tmp_path, "rm", "run-definition", "alpha")

    assert code == 0, withdrawn
    assert withdrawn["removed"] is True
    assert withdrawn["records_remaining"] == [record], "what the withdrawal left behind"
    assert withdrawn["remove_records_with"] == "vqapr rm run alpha"
    orphan = _runs(capsys, tmp_path)["alpha"]
    assert orphan["status"] == "orphaned" and orphan["definition"] is None
    assert orphan["recorded"] == [record] and orphan["unfinished"] == []
    # And the entry point it gives works: the last step no longer needs the id from memory.
    code, removed = _cli(capsys, tmp_path, "rm", "run", "alpha")
    assert code == 0, removed
    assert "alpha" not in _runs(capsys, tmp_path)


def test_cascade_removes_records_definition_outputs_and_components_in_one_gesture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    declaration = _declaration(tmp_path, ("alpha", "alpha_values"))
    code, _ = _cli(capsys, tmp_path, "register", str(declaration))
    assert code == 0
    code, ran = _cli(capsys, tmp_path, "run", "alpha")
    assert code == 0, ran
    materialized = tmp_path / ".vqapr" / "materialized" / "alpha_values"
    assert materialized.is_dir()

    code, gone = _cli(capsys, tmp_path, "rm", "run", "alpha", "--cascade")

    assert code == 0, gone
    assert gone["cascade"] is True
    assert gone["removed"]["records"] and gone["removed"]["run_definition"] is True
    assert gone["removed"]["datasets"] == ["alpha_values"]
    assert gone["removed"]["components"] == ["ratio"]
    assert gone["kept"] == []
    assert not materialized.exists(), "the package's own output directory goes with it"
    assert (tmp_path / "price_daily.parquet").exists(), "the user's own data is never touched"
    assert _runs(capsys, tmp_path) == {}
    _, datasets = _cli(capsys, tmp_path, "list", "datasets")
    assert [row["dataset_id"] for row in datasets["items"]] == ["price_daily"]
    _, components = _cli(capsys, tmp_path, "list", "components")
    assert components["count"] == 0


def test_cascade_keeps_what_another_registered_run_still_names_and_says_who_holds_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    declaration = _declaration(tmp_path, ("alpha", "alpha_values"), ("beta", "beta_values"))
    code, _ = _cli(capsys, tmp_path, "register", str(declaration))
    assert code == 0
    code, ran = _cli(capsys, tmp_path, "run", "alpha")
    assert code == 0, ran

    code, gone = _cli(capsys, tmp_path, "rm", "run", "alpha", "--cascade")

    assert code == 0, gone
    assert gone["removed"]["run_definition"] is True
    assert gone["removed"]["datasets"] == ["alpha_values"]
    assert gone["removed"]["components"] == [], "`ratio` is still named by `beta`"
    assert gone["kept"] == [{"kind": "component", "id": "ratio", "held_by": "run 'beta'"}]
    assert set(_runs(capsys, tmp_path)) == {"beta"}


def test_cascade_belongs_to_rm_run_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, refused = _cli(capsys, tmp_path, "rm", "dataset", "whatever", "--cascade")
    assert code != 0
    assert refused["failures"][0]["code"] == "argument.value_invalid"
    assert "rm run <run-id> --cascade" in refused["retry_precondition"]
