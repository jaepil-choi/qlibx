"""Register the sample panel and run it end to end.

The point of the sample is that it executes. A reader can run this once and see a real result
before writing anything, and the panel it runs on is deliberately unbalanced so the result also
shows what happens when an instrument lists late or stops trading mid-run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from vqapr.agent.sample.build import SamplePanel, build
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.public import (
    AccountMode,
    AccountSnapshot,
    ComponentKind,
    ComponentRef,
    DatasetRegistration,
    ExecutionInputRegistration,
    ExecutionTableSpec,
    FillConvention,
    FillSelector,
    RunDefinition,
    SourceSpec,
    StrategyEntry,
    preflight_run,
    register_component,
    register_dataset,
    register_execution_input,
    register_run,
    register_strategy_model,
    run,
)

VENUE = "Asia/Seoul"
OFFSET = "+09:00"

CALLBACK = time(8, 0)
"""The decision is made before the session opens, reading only closes already published."""
CLOSE = time(15, 30)
"""The fill happens at the close, after the decision, never at the same instant."""

DATASET_ID = "sample-prices"
RUN_ID = "sample-run"
EXECUTION_ID = "sample-execution"
STRATEGY_ID = "sample-reversal-5d"
EXCHANGE_ID = "sample-exchange"

STRATEGY_SOURCE = Path(__file__).with_name("reversal_5d.py")
EXCHANGE_SOURCE = Path(__file__).with_name("exchange.py")

OPENING_CASH = Decimal("100000000")
"""The book starts in cash, so the first rebalance is a plain set of purchases."""


@dataclass(frozen=True, slots=True)
class SampleResult:
    panel: SamplePanel
    occurrences: int
    run_state_version: int
    """How many times the run published state, which is not the Account's version.

    These were conflated while every state publication came from a callback. They are two
    different counters: the Account advances only when a fill commits, while the run state also
    advances when a valuation records a mark without trading. Naming this one for the Account
    made a valuation-clock change look like an accounting change.
    """

    account_version: int


def _sessions(panel: SamplePanel) -> list[date]:
    return [date(int(v[:4]), int(v[4:6]), int(v[6:8])) for v in panel.sessions]


def install(project_root: Path, panel: SamplePanel | None = None) -> SamplePanel:
    """Create the panel and register every declaration a run needs.

    `panel` is a panel already built elsewhere, registered here instead of one built under
    `project_root`. Building reads the local warehouse and takes about 36 seconds; the package's
    own tests install the sample into a dozen projects per run and build it once
    (`tests/conftest.py::sample_panel`). A reader running the sample builds it, as before.
    """
    if panel is None:
        panel = build(project_root)
    register_dataset(
        project_root,
        DatasetRegistration.of(
            DATASET_ID,
            "sample-prices-source",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            fields={name: name for name in ("open", "high", "low", "close", "volume")},
        ),
        SourceSpec.of("sample-prices-source", panel.observations),
    )
    register_execution_input(
        project_root,
        ExecutionInputRegistration.of(
            EXECUTION_ID,
            ExecutionTableSpec(
                source=SourceSpec.of("sample-execution-source", panel.execution),
                trade_at_field="trade_at",
                instrument_field="instrument",
                is_tradable_field="is_tradable",
                price_fields={"close": "close"},
            ),
            FillConvention(FillSelector.SAME_DAY, CLOSE, VENUE, "close"),
        ),
    )
    register_strategy_model(project_root, STRATEGY_ID, STRATEGY_SOURCE, "SampleReversal5d")
    register_component(
        project_root,
        ComponentRef.of(
            EXCHANGE_ID,
            ComponentKind.EXCHANGE,
            EXCHANGE_SOURCE,
            "SampleExchange",
            config={"instruments": list(panel.instruments)},
            fingerprint=fingerprint_component(
                EXCHANGE_SOURCE,
                kind=ComponentKind.EXCHANGE,
                object_name="SampleExchange",
                config={"instruments": list(panel.instruments)},
            ),
        ),
    )

    register_run(project_root, definition(panel))
    return panel


def definition(panel: SamplePanel, run_id: str = RUN_ID) -> RunDefinition:
    """The sample run: one strategy over the sample panel, by ids the workspace registered."""
    # Every session the panel has but the first, at the callback time; the book is valued at
    # the close it fills at and monitored right after (record 148). The first session is left
    # out because its close is published at 15:30 and the decision is made at 08:00: a run whose
    # horizon opened there asked its first decision to read history the dataset did not have
    # yet, and `vqapr check` refused exactly that (`check.lookback.uncovered`) while `execute`
    # below, which reaches `preflight_run` and `run` directly, accepted it (record 167). The
    # strategy Holds until six closes exist either way, so nothing economic moved.
    sessions = _sessions(panel)[1:]
    return RunDefinition(
        run_id=run_id,
        strategies=(StrategyEntry(STRATEGY_ID),),
        sessions=tuple(sessions),
        timezone=VENUE,
        at=CALLBACK,
        exchange=EXCHANGE_ID,
        execution_input_id=EXECUTION_ID,
        start=datetime.fromisoformat(f"{sessions[0].isoformat()}T00:00:00{OFFSET}"),
        end=datetime.fromisoformat(f"{sessions[-1].isoformat()}T23:59:59{OFFSET}"),
        initial_account_snapshot=AccountSnapshot(version=0, cash=OPENING_CASH, positions={}),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=panel.instruments,
    )


def execute(project_root: Path, panel: SamplePanel) -> SampleResult:
    """Freeze the registered run and run it."""
    result = run(project_root, preflight_run(project_root, definition(panel))).result()
    return SampleResult(
        panel,
        len(result.occurrences),
        result.final_state.version,
        result.final_state.account.snapshot.version,
    )


__all__ = ["RUN_ID", "SampleResult", "definition", "execute", "install"]
