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


def _register(
    root: Path,
    component_id: str,
    source: Path,
    *,
    kind: ComponentKind = ComponentKind.STRATEGY_MODEL,
    object_name: str = "Wide",
) -> None:
    space = Workspace.create(root) if not (root / ".vqapr").exists() else Workspace.open(root)
    with Workspace.transaction(space) as t:
        t.register_component(
            ComponentRef.of(
                component_id,
                kind,
                source,
                object_name,
                fingerprint=fingerprint_component(source, kind=kind, object_name=object_name),
            )
        )


EXCHANGE = """
from decimal import Decimal
from vqapr.exchange.venue import AcademicExchange, TradeRule
from vqapr.exchange.listings import ListingAccess


class Venue(AcademicExchange):
    def __init__(self):
        super().__init__(
            {"A": TradeRule("A", Decimal("1"), Decimal("1"), False, ListingAccess.SIGNED)}
        )
"""


def test_a_registered_component_of_a_kind_this_verb_does_not_describe_is_refused_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`docs/issues/083`. Feeding `list components` to `show model` broke on the exchange with

        {"stage": "unhandled", "failures": [], "error": "TypeError: ref must identify a
         strategy_model component"}

    which is false -- this verb reads three kinds and had just shown a datamodel -- and
    unstructured. The neighbouring mistake, an unregistered id, gets a `argument.value_invalid`
    naming what is registered; the wrong kind is the same mistake and gets the same answer.
    """
    source = tmp_path / "wide.py"
    source.write_text(STRATEGY, encoding="utf-8")
    _register(tmp_path, "wide", source)
    venue = tmp_path / "venue.py"
    venue.write_text(EXCHANGE, encoding="utf-8")
    _register(tmp_path, "venue", venue, kind=ComponentKind.EXCHANGE, object_name="Venue")

    code = main(["--project-root", str(tmp_path), "show", "model", "venue"])
    refused = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert code != 0
    assert refused["stage"] != "unhandled", refused
    (failure,) = refused["failures"]
    assert failure["code"] == "argument.value_invalid"
    assert "strategy, datamodel, constraint" in failure["requirement"]
    assert failure["observed"] == "'venue' is registered as exchange"
    assert "list components --kind" in refused["retry_precondition"]


def test_list_components_filters_by_kind_so_the_wrong_ref_is_never_assembled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other half of `083` (and of `082`): `--kind`, spelled the way `list` reports it."""
    source = tmp_path / "wide.py"
    source.write_text(STRATEGY, encoding="utf-8")
    _register(tmp_path, "wide", source)
    venue = tmp_path / "venue.py"
    venue.write_text(EXCHANGE, encoding="utf-8")
    _register(tmp_path, "venue", venue, kind=ComponentKind.EXCHANGE, object_name="Venue")

    def listed(*argv: str) -> dict:
        main(["--project-root", str(tmp_path), "list", *argv])
        return json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert [row["component_id"] for row in listed("components")["items"]] == ["venue", "wide"]
    assert [row["component_id"] for row in listed("components", "--kind", "strategy")["items"]] == [
        "wide"
    ]
    assert [row["component_id"] for row in listed("components", "--kind", "exchange")["items"]] == [
        "venue"
    ]
    assert listed("components", "--kind", "datamodel")["count"] == 0

    wrong = listed("runs", "--kind", "strategy")
    assert wrong["ok"] is False
    assert wrong["failures"][0]["code"] == "argument.value_invalid"


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
