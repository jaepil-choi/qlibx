"""AC-8 of the two-clocks campaign: one instant, one order, written once (design §3.1).

    ACCRUE -> EXECUTE -> VALUATION -> COMPLIANCE -> DECIDE

The market clock's four stages are dispatched by one method, `_handle_market`, and a decision
at the same instant is a separate event the loop sorts after it. Both halves are pinned here:
the source order of the dispatcher (a boundary, so a later edit cannot quietly reorder the
stages) and the lifecycle a real run leaves at an instant where a fill and a decision coincide.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.acceptance.test_a_minute_strategy_fills_at_the_next_minute import _workspace
from tests.cli.test_commands import _cli
from vqapr.flow.engine.loop import MarketEvent, OccurrenceEvent
from vqapr.flow.engine.run_state import LifecycleKind
from vqapr.flow.run.loop import DueExecutionTrace, OccurrenceTrace, StrategyEventLoop
from vqapr.public import Workspace, preflight_run, run

_ZONE = ZoneInfo("Asia/Seoul")


def test_the_dispatcher_writes_the_stage_order_down_once() -> None:
    """The order is a fact about the code, checked as text so a reordering is a visible diff."""
    source = inspect.getsource(StrategyEventLoop._handle_market)
    calls = [
        "._accrual.accrue(",
        "._execution.fill(",
        "._valuation.mark(",
        "._compliance.observe(",
        "._execution.close(",
    ]
    positions = [source.index(call) for call in calls]
    assert positions == sorted(positions), (
        "ACCRUE, EXECUTE, VALUATION, COMPLIANCE and the fill's epilogue must be called in that order"
    )
    # A decision at the same instant is sorted AFTER the market instant by the event keys.
    at = datetime(2024, 3, 5, 9, 1, tzinfo=_ZONE)
    market = MarketEvent(at)
    assert market.sort_key()[1] < 0, "a market instant sorts before a same-time occurrence"
    assert OccurrenceEvent.__name__  # the other event kind exists; its key carries priority 0


@pytest.mark.slow
def test_a_fill_and_a_decision_at_one_instant_settle_then_decide(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """At 09:01 the 09:00 decision fills (EXECUTE), the book is valued (VALUATION) and the fill
    is closed -- all before the 09:01 decision is asked (DECIDE)."""
    _workspace(tmp_path, capsys)
    runs = tmp_path / "runs.yaml"
    runs.write_text(
        json.dumps(
            {
                "runs": {
                    "ordered": {
                        "writes": "ordered-weights",
                        "strategy": {"component": "always-long"},
                        "timezone": "Asia/Seoul",
                        "agenda": {"every": "1m", "from": "09:00", "to": "09:02"},
                        "exchange": "venue",
                        "execution": {"dataset": "venue-minute", "trade_price": "close"},
                        "start": datetime(2024, 3, 5, 0, tzinfo=_ZONE).isoformat(),
                        "end": datetime(2024, 3, 5, 23, tzinfo=_ZONE).isoformat(),
                        "initial_account": {"cash": "1000", "mode": "long_only"},
                        "instruments": ["A"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", str(runs))
    assert code == 0, payload

    workspace = Workspace.open(tmp_path)
    result = run(tmp_path, preflight_run(workspace, workspace.run_definition("ordered"))).result()

    at_0901 = datetime(2024, 3, 5, 9, 1, tzinfo=_ZONE)
    traces_at = [
        trace
        for trace in result.occurrences
        if (
            trace.due.instant if isinstance(trace, DueExecutionTrace) else trace.occurrence.evaluation_time
        )
        == at_0901
    ]
    assert [type(trace) for trace in traces_at] == [DueExecutionTrace, OccurrenceTrace], (
        "the market instant is handled before the decision at the same instant"
    )
    kinds = [entry.kind for entry in result.final_state.lifecycle_trace]
    # The 09:00 decision, then at 09:01: its fill committed, marked, closed -- then the 09:01
    # decision is accepted. The mark of 09:00 (a held, empty book) precedes the 09:00 decision.
    assert kinds[:5] == [
        LifecycleKind.MARKED,
        LifecycleKind.ACCEPTED_INTENT,
        LifecycleKind.ACCOUNT_COMMITTED,
        LifecycleKind.MARKED,
        LifecycleKind.FEEDBACK_PUBLISHED,
    ], kinds[:8]
    assert kinds[5] is LifecycleKind.ACCEPTED_INTENT, "DECIDE comes last at 09:01"
