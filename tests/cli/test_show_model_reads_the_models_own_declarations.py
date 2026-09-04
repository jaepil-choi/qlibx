"""`docs/issues/055`: `show model` answers from `inputs()`, `tables()` and `account_history()`.

It read three private attributes nothing in the tree assigned -- `_aliases`, `_authored_tables`,
`_authored_history` -- behind `getattr` defaults, so `reads` was always empty, `records` never
listed a declared table, and `decides` repeated one dataset id once per field.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vqapr.cli.main import main
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.workspace import Workspace

STRATEGY = '''
from vqapr import authoring as va


class Wide(va.StrategyModel):
    def inputs(self):
        return {
            "resid": va.DatasetInput(
                dataset_id="ff6-resid-values",
                fields=("resid", "beta_mkt", "beta_smb"),
                lookback=va.RowsLookback(rows=30),
            ),
            "px": va.DatasetInput(
                dataset_id="kr-daily", fields=("close",), lookback=va.RowsLookback(rows=2)
            ),
        }

    def tables(self):
        return (va.TableSpec("ou_summary", ("instrument", "z")),)

    def account_history(self):
        return va.AccountHistoryInput(fields=("nav",), lookback=va.RowsLookback(rows=5))

    def decide(self, call):
        return va.Hold(reason="never called here")
'''


def _register(root: Path, component_id: str, source: Path) -> None:
    kind = ComponentKind.STRATEGY_MODEL
    Workspace.create(root).register_component(
        ComponentRef.of(
            component_id,
            kind,
            source,
            "Wide",
            fingerprint=fingerprint_component(source, kind=kind, object_name="Wide"),
        )
    )


def test_reads_decides_forms_and_records_come_from_the_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "wide.py"
    source.write_text(STRATEGY, encoding="utf-8")
    _register(tmp_path, "wide", source)

    code = main(["--project-root", str(tmp_path), "show", "model", "wide"])
    described = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert code == 0, described
    assert described["reads"] == {
        "px": {"dataset_id": "kr-daily", "fields": ["close"], "lookback": "RowsLookback(rows=2)"},
        "resid": {
            "dataset_id": "ff6-resid-values",
            "fields": ["resid", "beta_mkt", "beta_smb"],
            "lookback": "RowsLookback(rows=30)",
        },
    }
    assert described["decides"] == ["ff6-resid-values", "kr-daily"], "distinct, in order"
    assert described["forms"] == ["ou_summary"]
    assert described["records"] == ["ou_summary", "vqapr.account"]
