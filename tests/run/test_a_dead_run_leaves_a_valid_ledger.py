"""AC-12 of the two-clocks campaign (design §5.1): a run that dies leaves a short ledger, not a
damaged account.

An append-only ledger has no half-written state: every prefix is a valid ledger. A strategy that
raises on its third decision has two fills behind it, streamed to the record as they were
committed, and what is on disk folds -- entry by entry, from the declared opening cash -- to
exactly the account the last mark valued. Nothing about the death is in the numbers; only the
story is shorter.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from tests.cli.test_commands import _cli, _register_run, _workspace_for_run
from vqapr.domain.account import FILL_ORIGIN, AccountSnapshot, LedgerEntry, fold
from vqapr.record import read_table, strategy_refs
from vqapr.record.reader import unfinished_strategy_refs

_DIES = '''"""Rebalances into A twice, then dies on the third decision."""

from decimal import Decimal

from vqapr import authoring as va


class Dies(va.StrategyModel):
    def inputs(self):
        return {
            "prices": va.DatasetInput(
                dataset_id="prices", fields=("close",), lookback=va.RowsLookback(rows=1)
            )
        }

    def decide(self, call):
        seen = int((self.memory or {}).get("decisions", 0)) + 1
        self.memory = {"decisions": seen}
        if seen >= 3:
            raise RuntimeError("the strategy died on its third decision")
        return va.Rebalance.of(long={"A": Decimal(1)}, invested="1.0")
'''


@pytest.mark.slow
def test_a_run_that_dies_leaves_a_ledger_every_prefix_of_which_is_an_account(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _workspace_for_run(tmp_path, capsys)
    (tmp_path / "dies.py").write_text(_DIES, encoding="utf-8")
    declaration = tmp_path / "dies.yaml"
    declaration.write_text(
        "components:\n  dies:\n    kind: strategy\n    path: dies.py\n    object_name: Dies\n",
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", str(declaration))
    assert code == 0, payload
    code, payload = _register_run(tmp_path, capsys, "dies", strategy={"component": "dies"})
    assert code == 0, payload

    code, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "dies")
    assert code == 1, ran
    assert ran["ok"] is False and ran["stage"] != "unhandled"

    store = tmp_path / ".vqapr"
    assert strategy_refs(store, "dies") == (), "no record marks a run that never finished"
    (ref,) = unfinished_strategy_refs(store, "dies")
    fills = sorted(
        read_table(store, "dies", "vqapr.fill", ref),
        key=lambda row: (int(row["account_version"]), int(row["sequence"])),
    )
    assert fills, f"two fills were committed before the death, and both reached disk: {ran}"

    # Fold what is on disk, from the declared opening book, one append per account version.
    opening = AccountSnapshot(0, Decimal("1000"), {})
    book = opening
    versions: list[int] = []
    for row in fills:
        version = int(row["account_version"])
        if not versions or versions[-1] != version:
            versions.append(version)
            entries: list[LedgerEntry] = []
        dealt = Decimal(str(row["dealt_quantity"]))
        entries.append(
            LedgerEntry(
                at=row["event_time"],
                cash=Decimal(str(row["cash_delta"])),
                positions={str(row["instrument"]): dealt} if dealt else {},
                origin=FILL_ORIGIN,
            )
        )
        if row is fills[-1] or int(fills[fills.index(row) + 1]["account_version"]) != version:
            book = fold(book, entries)
            assert book.version == version, "each append is one version, in order"
            assert book.cash >= 0, "every prefix of the ledger is a valid account"

    assert versions == [1, 2], "two decisions filled; the third never reached the venue"
    assert book.positions == {"A": book.positions["A"]} and book.positions["A"] > 0

    # And the last mark on disk valued exactly the book the ledger folds to.
    account_rows = [
        row
        for row in read_table(store, "dies", "vqapr.account", ref)
        if row["instrument"] == "_ACCOUNT"
    ]
    last = max(account_rows, key=lambda row: (int(row["account_version"]), row["event_time"]))
    assert int(last["account_version"]) == book.version
    assert Decimal(str(last["cash"])) == book.cash
