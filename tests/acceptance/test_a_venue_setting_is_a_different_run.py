"""AC-11 of the two-clocks campaign (design §6.1): a venue's settings are the venue's own.

One KRX venue file, registered twice -- once as KRX charges, once with the sale tax switched off
through `config:` -- and one run declaration pointed at each. The two runs fill the same rotation
on the same prices, charge differently, carry different identities, put their allocations in the
warehouse under different names, and each records what its venue declared it modelled.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.cli.test_krx_cost_journey import _STRATEGY, ETF, STOCK, _cli, _declaration, _parquets
from vqapr.domain.instrument import export_roster
from vqapr.record import read_strategy_record, read_table, strategy_refs

_ZONE = ZoneInfo("Asia/Seoul")

_VENUE = f'''"""A KRX venue whose sale tax is a setting, set from the registration's config."""

from vqapr.public import KrxExchange


class Venue(KrxExchange):
    def __init__(self, *, sale_tax_rate: str = "0.002") -> None:
        super().__init__([{STOCK!r}, {ETF!r}], "krx", sale_tax_rate=sale_tax_rate)
'''


def _run(run_id: str, exchange: str) -> dict[str, object]:
    return {
        "writes": f"{run_id}-weights",
        "strategy": {"component": "rotate"},
        "timezone": "Asia/Seoul",
        "agenda": {"every": "1d", "at": "04:00"},
        "exchange": exchange,
        "execution": {"dataset": "venue-daily", "trade_price": "close", "fill": {"at": "15:30"}},
        "start": datetime(2024, 3, 5, 0, tzinfo=_ZONE).isoformat(),
        "end": datetime(2024, 3, 8, 23, tzinfo=_ZONE).isoformat(),
        "initial_account": {"cash": "1000000", "mode": "long_only"},
        "instruments": [STOCK, ETF],
    }


@pytest.mark.slow
def test_the_same_venue_file_with_the_tax_off_is_a_different_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    observation, execution = _parquets(tmp_path)
    code, payload = _cli(
        capsys, "--project-root", str(tmp_path), "register",
        str(_declaration(tmp_path, observation, execution)),
    )
    assert code == 0, payload

    written = export_roster({STOCK: "stock", ETF: "etf"}, tmp_path / "roster")
    roster = tmp_path / "roster.yaml"
    roster.write_text(
        "instruments:\n  tables:\n"
        + "".join(
            f"    {kind}: {path.relative_to(tmp_path).as_posix()}\n"
            for kind, path in sorted(written.items())
        ),
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", str(roster))
    assert code == 0, payload

    (tmp_path / "venue.py").write_text(_VENUE, encoding="utf-8")
    (tmp_path / "rotate.py").write_text(_STRATEGY, encoding="utf-8")
    components = tmp_path / "components.yaml"
    components.write_text(
        "components:\n"
        "  krx-taxed:\n    kind: exchange\n    path: venue.py\n    object_name: Venue\n"
        "  krx-untaxed:\n    kind: exchange\n    path: venue.py\n    object_name: Venue\n"
        '    config: {sale_tax_rate: "0"}\n'
        "  rotate:\n    kind: strategy\n    path: rotate.py\n    object_name: Rotate\n",
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", str(components))
    assert code == 0, payload

    runs = tmp_path / "runs.yaml"
    runs.write_text(
        json.dumps({"runs": {"taxed": _run("taxed", "krx-taxed"), "untaxed": _run("untaxed", "krx-untaxed")}}),
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", str(runs))
    assert code == 0, payload

    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "taxed", "untaxed")
    assert code == 0, ran

    store = tmp_path / ".vqapr"
    records = {}
    stock_sale_tax = {}
    identities = {}
    for run_id in ("taxed", "untaxed"):
        (ref,) = strategy_refs(store, run_id)
        records[run_id] = read_strategy_record(store, run_id, ref)
        fills = [
            row
            for row in read_table(store, run_id, "vqapr.fill", ref)
            if Decimal(str(row.get("dealt_quantity") or 0)) != 0
        ]
        assert fills, f"{run_id} must trade, or it proves nothing about what a setting changes"
        sales = [row for row in fills if Decimal(str(row["dealt_quantity"])) < 0 and row["kind"] == "stock"]
        assert sales, f"{run_id} must sell the stock, or the tax setting is never exercised"
        stock_sale_tax[run_id] = {Decimal(str(row["tax"])) > 0 for row in sales}
        identities[run_id] = {row["run_id"] for row in fills}

    # Same rotation, same prices: the taxed venue charges the stock sale, the untaxed one does not.
    assert stock_sale_tax == {"taxed": {True}, "untaxed": {False}}
    # Each record says what its venue declared it modelled -- the setting is on the record.
    assert records["taxed"]["exchange"]["settings"]["sale_tax_rate"] == "0.002"
    assert records["untaxed"]["exchange"]["settings"]["sale_tax_rate"] == "0"
    assert records["taxed"]["exchange"]["component_id"] == "krx-taxed"
    assert records["untaxed"]["exchange"]["component_id"] == "krx-untaxed"
    # Two venues from one file: two fingerprints, two run identities, two datasets in the warehouse.
    assert records["taxed"]["exchange"]["fingerprint"] != records["untaxed"]["exchange"]["fingerprint"]
    assert identities["taxed"].isdisjoint(identities["untaxed"])
    assert set(ran["runs"]) == {"taxed", "untaxed"}
    code, listed = _cli(capsys, "--project-root", str(tmp_path), "list", "datasets")
    names = {row["dataset_id"] for row in listed["items"]}
    assert {"taxed-weights", "untaxed-weights"} <= names
