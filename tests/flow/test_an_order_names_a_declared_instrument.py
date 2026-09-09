"""The instrument declaration gate, at its two instants (design §6.2-6.3, record `203`).

Three sets are independent -- the execution table, the roster, the orders -- and only two
inclusions are required: orders ⊆ roster (the venue must know what it sizes and charges) and
orders ⊆ table (it must have a price). Preflight can only see the roster's EXISTENCE, since
which ids get ordered is the strategy's decision at run time; so the gate has a preflight half
(`roster.absent`: nothing declared, nothing can succeed) and a runtime half
(`instrument.undeclared`: this order names an id the roster never described -- every such id,
in one refusal). This file pins the helpers both halves are built from and the judge `check`
asks; `tests/cli/test_the_three_instrument_sets_are_independent.py` drives them end to end.
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vqapr.account.account import AccountMode
from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.errors import FailureSource, Stage, Status, VqaprError
from vqapr.domain.instruments import (
    INSTRUMENT_UNDECLARED,
    InstrumentRoster,
    instruments,
    require_declared,
    undeclared_instruments,
)
from vqapr.flow.declaration import judgments
from vqapr.flow.declaration.roster import ROSTER_ABSENT, require_declared_roster
from vqapr.project.run import DataModelEntry, RunAgenda, RunDefinition, RunExecution, RunFill, StrategyEntry
from vqapr.project.store import Workspace
from vqapr.public import register_instruments

KST = ZoneInfo("Asia/Seoul")
DECLARED = InstrumentRoster(instruments({"A005930": "stock", "A069500": "etf"}))


def test_the_undeclared_ids_are_listed_once_each_in_order() -> None:
    """Every id the roster never described, none twice, in the order the orders named them."""
    assert undeclared_instruments(DECLARED, ("A005930",)) == ()
    assert undeclared_instruments(DECLARED, ("Q1", "A005930", "Q2", "Q1")) == ("Q1", "Q2")


def test_no_roster_means_every_id_is_undeclared() -> None:
    """A run assembled without a workspace has no roster to consult; the gate does not guess."""
    assert undeclared_instruments(None, ("A005930", "A069500")) == ("A005930", "A069500")


def test_the_runtime_refusal_names_all_of_them_at_once() -> None:
    """Design §6.3: not the alphabetically first unknown id -- all of them, one refusal."""
    with pytest.raises(VqaprError) as refused:
        require_declared(DECLARED, ("Q2", "A005930", "Q1", "Q2"), exchange_id="krx")
    error = refused.value
    assert error.stage is Stage.RUN
    (failure,) = error.failures
    assert failure.code == INSTRUMENT_UNDECLARED == "instrument.undeclared"
    assert failure.status is Status.PRECONDITION
    assert "2 undeclared instrument(s) reached 'krx': Q2, Q1" in str(failure.observed)
    assert "vqapr register" in str(failure.fix)
    # And nothing to say when every ordered id is declared.
    require_declared(DECLARED, ("A005930", "A069500"), exchange_id="krx")


def test_the_two_spellings_of_roster_absent_are_one_string() -> None:
    """Preflight spells the code in `flow/declaration/roster.py`, `check` in the judgments module
    (which publishes its own list); a reader must meet one code at both doors."""
    assert ROSTER_ABSENT == judgments.ROSTER_ABSENT == "roster.absent"
    assert ROSTER_ABSENT in judgments.JUDGMENT_CODES


def _strategy_run(run_id: str = "alpha") -> RunDefinition:
    return RunDefinition(
        run_id=run_id,
        writes=f"{run_id}-weights",
        strategy=StrategyEntry("model"),
        instruments=("A005930",),
        timezone="Asia/Seoul",
        agenda=RunAgenda(every="1d", at=(time(9, 0),)),
        exchange="venue",
        execution=RunExecution(
            dataset="fills",
            fill=RunFill(
                selector="same_day", at=time(15, 30), timezone="Asia/Seoul", trade_price="close"
            ),
        ),
        start=datetime(2024, 3, 5, tzinfo=KST),
        end=datetime(2024, 3, 6, tzinfo=KST),
        initial_account_snapshot=AccountSnapshot(0, Decimal("1000"), {}),
        initial_account_mode=AccountMode.LONG_ONLY,
    )


def _datamodel_run() -> RunDefinition:
    return RunDefinition(
        run_id="scores",
        writes="scores_1d",
        datamodel=DataModelEntry("model", ("score",)),
        instruments=("A005930",),
        timezone="Asia/Seoul",
        agenda=RunAgenda(every="1d", at=(time(16, 0),), days_from="prices"),
        start=datetime(2024, 3, 5, tzinfo=KST),
        end=datetime(2024, 3, 6, tzinfo=KST),
    )


def test_a_strategy_run_over_no_roster_is_refused_before_it_freezes(tmp_path: Path) -> None:
    """The preflight half. Only the pointer is read: a roster that exists has an instrument."""
    workspace = Workspace.create(tmp_path)
    with pytest.raises(VqaprError) as refused:
        require_declared_roster(workspace, run_id="alpha")
    error = refused.value
    assert error.stage is Stage.FREEZE
    (failure,) = error.failures
    assert failure.code == ROSTER_ABSENT
    assert failure.status is Status.PRECONDITION
    assert "'alpha'" in str(failure.observed)
    assert "vqapr new instruments" in str(failure.fix)

    register_instruments(tmp_path, {"A005930": "stock"})
    require_declared_roster(Workspace.open(tmp_path), run_id="alpha")


def test_the_judge_asks_a_strategy_run_and_not_a_datamodel_run(tmp_path: Path) -> None:
    """`check` reports it beside the run's other defects; a datamodel run orders nothing."""
    workspace = Workspace.create(tmp_path)
    at = FailureSource(key_path="runs.alpha")

    (failure,) = judgments._judge_roster(_strategy_run(), workspace, at)
    assert failure.code == ROSTER_ABSENT
    assert failure.source is not None and failure.source.key_path == "runs.alpha.exchange"
    assert judgments._judge_roster(_datamodel_run(), workspace, at) == []

    register_instruments(tmp_path, {"A005930": "stock"})
    assert judgments._judge_roster(_strategy_run(), Workspace.open(tmp_path), at) == []


def test_register_instruments_exports_and_registers_in_one_call(tmp_path: Path) -> None:
    """The public door the showcases and the sample use: tables written, roster registered."""
    Workspace.create(tmp_path)
    receipt = register_instruments(tmp_path, {"A005930": "stock", "A069500": "etf"})

    assert receipt["by_kind"] == {"etf": 1, "stock": 1}
    assert receipt["instruments"] == 2
    assert (tmp_path / "instruments" / "instruments_stock.parquet").is_file()
    assert (tmp_path / "instruments" / "instruments_etf.parquet").is_file()
    pointer = Workspace.open(tmp_path).registered_instruments()
    assert pointer is not None and pointer["digest"] == receipt["digest"]
    # Re-registering is ordinary and replaces the slot.
    again = register_instruments(tmp_path, {"A005930": "stock"})
    assert again["by_kind"] == {"stock": 1}
