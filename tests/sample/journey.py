"""Install the sample the way a user does, and run it end to end.

The point of the sample is that it executes. `install` materializes it through the same function
`vqapr new sample` calls and registers it through the same verb `vqapr register` runs, so what the
suite proves is the door a user opens (record `172`). The panel is synthetic and shipped in the
package: no warehouse, no build step.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from vqapr.agent.sample import materialize as materialize_module
from vqapr.agent.sample import reversal_5d as reversal_module
from vqapr.agent.sample.materialize import (
    DATASET_ID,
    EXCHANGE_ID,
    EXECUTION_ID,
    OFFSET,
    RUN_ID,
    STRATEGY_ID,
    VENUE,
    Materialized,
    materialize,
)
from vqapr.cli.register import run as register_cli
from vqapr.public import RunDefinition, Workspace, freeze, run

__all__ = [
    "CALLBACK",
    "DATASET_ID",
    "EXCHANGE_ID",
    "EXECUTION_ID",
    "OFFSET",
    "RUN_ID",
    "STRATEGY_ID",
    "STRATEGY_SOURCE",
    "VENUE",
    "Materialized",
    "SampleResult",
    "execute",
    "install",
]


@dataclass(frozen=True, slots=True)
class SampleResult:
    sample: Materialized
    events: int
    run_state_version: int
    """How many times the run published state, which is not the Account's version.

    These were conflated while every state publication came from a callback. They are two
    different counters: the Account advances only when a fill commits, while the run state also
    advances when a valuation records a mark without trading. Naming this one for the Account
    made a valuation-clock change look like an accounting change.
    """

    account_version: int


CALLBACK = time(8, 0)
STRATEGY_SOURCE = Path(reversal_module.__file__)
"""The packaged strategy source, for a test that registers it again under another id."""
OPENING_CASH = Decimal(materialize_module.OPENING_CASH)


def sessions(sample: Materialized) -> list[date]:
    """Every venue-local session the panel has, from the observations themselves."""
    import pyarrow.parquet as pq

    stamps = pq.read_table(sample.observations, columns=["available_at"]).column(0).to_pylist()
    return sorted({stamp.astimezone(ZoneInfo(VENUE)).date() for stamp in stamps})


def definition(sample: Materialized, run_id: str = RUN_ID) -> RunDefinition:
    """The registered sample run, optionally under another id, for a test that derives from it."""
    registered = Workspace.open(sample.directory.parent).run_definition(RUN_ID)
    return registered if run_id == RUN_ID else registered.replace(run_id=run_id)


def install(project_root: Path) -> Materialized:
    """Materialize the sample under `project_root/sample` and register its declaration."""
    sample = materialize(Path(project_root) / "sample")
    registered = register_cli(
        argparse.Namespace(declaration=str(sample.declaration)), project_root=Path(project_root)
    )
    assert registered["ok"], registered
    return sample


def execute(project_root: Path, sample: Materialized) -> SampleResult:
    """Freeze the registered run and run it, through the public door."""
    workspace = Workspace.open(project_root)
    definition = workspace.run_definition(sample.run_id)
    result = run(project_root, freeze(workspace, definition)).result()
    return SampleResult(
        sample,
        len(result.events),
        result.final_state.version,
        result.final_state.account.snapshot.version,
    )
