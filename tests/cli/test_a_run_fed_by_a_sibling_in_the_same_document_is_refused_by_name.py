"""`docs/issues/archive/084`, the second half: a document holding two runs where the second takes its
sessions from the first's output cannot be registered -- the dataset does not exist until the
first has run, and the first cannot run until the document is registered. The refusal used to
say only that the dataset is unregistered, while the run producing it sat in the same document.
`vqapr new run --out` scaffolds a `runs:` block that holds several runs and invites exactly this;
the reporter split one file per run and lost ten minutes finding out why.
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
            dataset_id='price_daily', fields=('close',), lookback=vq.RowsLookback(rows=1)
        )}

    def compute(self, context):
        window = context.read("prices", "close")
        return [{"instrument": name, "score": 1.0} for name in window.instruments]
"""


def _prices(root: Path) -> Path:
    parquet = root / "price_daily.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT available_at, instrument, close::DOUBLE AS close FROM (VALUES
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', 100.0),
              (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', 103.0)
            ) AS t(available_at, instrument, close))
            TO '{parquet.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    return parquet


def test_the_refusal_names_the_producer_and_says_to_split_the_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    model = tmp_path / "model.py"
    model.write_text(_MODEL, encoding="utf-8")
    declaration = tmp_path / "declaration.yaml"
    declaration.write_text(
        f"""datasets:
  price_daily:
    source_id: prices
    path: {_prices(tmp_path).as_posix()}
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
  upstream:
    instruments: [A]
    start: "2024-03-05T00:00:00+09:00"
    end: "2024-03-07T00:00:00+09:00"
    timezone: Asia/Seoul
    schedule: {{every: 1d, at: "16:00", days_from: price_daily}}
    datamodels:
      ratio:
        dataset_id: ratio_values
        value_fields: [score]
  downstream:
    instruments: [A]
    start: "2024-03-05T00:00:00+09:00"
    end: "2024-03-07T00:00:00+09:00"
    timezone: Asia/Seoul
    schedule: {{every: 1d, at: "16:00", days_from: ratio_values}}
    datamodels:
      ratio:
        dataset_id: ratio_again
        value_fields: [score]
""",
        encoding="utf-8",
    )

    code = main(["--project-root", str(tmp_path), "register", str(declaration)])
    refused = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert code != 0
    (failure,) = refused["failures"]
    assert failure["code"] == "declaration.run_fed_by_sibling"
    assert "run 'downstream' takes its trading days from 'ratio_values'" in failure["observed"]
    assert "run 'upstream' in this same document will write" in failure["observed"]
    assert "split the document" in failure["fix"]
    assert "register and run 'upstream' first" in failure["fix"]
    assert failure["source"]["key_path"] == "runs.downstream.schedule.days_from"
    # Nothing was registered: the document is one transaction.
    assert not (tmp_path / ".vqapr" / "workspace.yaml").exists()
