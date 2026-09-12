"""The immutable evidence a stage leaves: canonical lineage emitted by the loop.

One value per thing a stage did -- a callback, an account commit, a mark, a fill's feedback, a due
execution, a valuation, a monitoring pass, the run's finalization. Values only; how a run fails is
`failure.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from vqapr.domain.account import AccountSnapshot, MarkSummary
from vqapr.domain.identifiers import ModelStateRef
from vqapr.domain.instants import require_tz_aware

__all__ = [
    "AccountCommitEvidence",
    "CallbackEvidence",
    "DueExecutionEvidence",
    "FeedbackEvidence",
    "FinalizationEvidence",
    "MarkEvidence",
    "MonitoringEvidence",
    "ValuationEvidence",
]


@dataclass(frozen=True, slots=True)
class CallbackEvidence:
    """Pre-publication callback authority, inputs, decision, and candidate output."""

    run_identity: str
    strategy: object
    schedule: object
    event: object
    cutoff: datetime
    root_version: int
    account: AccountSnapshot
    current_model_state_ref: ModelStateRef
    committed_model_state_ref: ModelStateRef
    strategy_accesses: tuple[object, ...]
    actual_source_refs: tuple[object, ...]
    decision: object
    pending: object | None
    mutation: bool = False

    def __post_init__(self) -> None:
        if self.mutation:
            raise ValueError("callback evidence must precede publication")
        require_tz_aware(self.cutoff, name="cutoff")


@dataclass(frozen=True, slots=True)
class AccountCommitEvidence:
    """All exact inputs and committed values for the irreversible Account fill."""

    run_identity: str
    schedule: object
    event: object
    cutoff: datetime
    pending: object
    target: object
    fill_convention: object
    execution_snapshot: object
    """The snapshot's partitions and row count (`ExecutionSnapshotSummary`, record `224`), not its
    rows: a 3,000-name book's rows per fill are the venue's data, read again from the table."""
    planning_nav: object
    planning_cash_target: object
    planning_budget: object
    intended_targets: tuple[object, ...]
    requested_orders: object
    dealt_fills: object
    before: AccountSnapshot
    committed: AccountSnapshot
    root_version: int
    account_version_before: int
    account_version_committed: int
    mutation: bool = True


@dataclass(frozen=True, slots=True)
class MarkEvidence:
    """Valuation declaration, the marks' summary, and post-mark Account authority.

    `selected` is how many names the venue's snapshot priced and `marks` the batch's total and
    count (record `224`): the marks themselves are `vqapr.account` rows by the time this exists,
    and keeping a `SelectedMark` and a `Mark` per name per fill held instants x names objects
    until the run ended.
    """

    run_identity: str
    schedule: object
    event: object
    cutoff: datetime
    selected: int
    marks: MarkSummary
    limitations: tuple[object, ...]
    account: AccountSnapshot
    root_version: int
    account_version: int
    mutation: bool = True


@dataclass(frozen=True, slots=True)
class FeedbackEvidence:
    """Published feedback transition; no fallible work follows Account commit."""

    run_identity: str
    schedule: object
    event: object
    cutoff: datetime
    pending: object
    candidates: tuple[object, ...]
    root_version: int
    account_version: int
    mutation: bool = True


@dataclass(frozen=True, slots=True)
class DueExecutionEvidence:
    """Complete due lifecycle lineage, including commit, marking, and feedback."""

    commit: AccountCommitEvidence
    mark: MarkEvidence
    feedback: FeedbackEvidence


@dataclass(frozen=True, slots=True)
class ValuationEvidence:
    """A held book valued at a market-clock instant: the account it valued and the marks'
    summary (record `224`; the marks are `vqapr.account` rows)."""

    run_identity: str
    schedule: object
    event: object
    cutoff: datetime
    account: AccountSnapshot
    marks: MarkSummary
    root_version: int
    account_version: int
    mutation: bool = False


@dataclass(frozen=True, slots=True)
class MonitoringEvidence:
    """What the declared Compliance rules found on the committed, marked book at one market-clock
    instant (design §7.2). No event: the observer has no decision of its own to point at."""

    run_identity: str
    schedule: object
    cutoff: datetime
    account: AccountSnapshot
    valuation: ValuationEvidence
    report: object
    root_version: int
    mutation: bool = False


@dataclass(frozen=True, slots=True)
class FinalizationEvidence:
    run_identity: str
    strategy_schedule: object
    cutoff: datetime
    account: AccountSnapshot | None
    root_version: int
    mutation: bool = False
