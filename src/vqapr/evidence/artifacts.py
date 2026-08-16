"""Typed, immutable evidence emitted by the simulation Flow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from vqapr.account.snapshot import AccountSnapshot
from vqapr.domain.timestamps import require_tz_aware
from vqapr.valuation.marks import MarkBatch


class SimulationFailure(RuntimeError, ValueError):
    """Typed fail-closed runtime error with exact visible authority versions."""

    def __init__(
        self,
        *,
        stage: str,
        cutoff: datetime,
        root_version: int,
        account_version: int | None,
        pending_id: str | None,
        cause: Exception,
    ) -> None:
        if not isinstance(stage, str) or not stage:
            raise ValueError("stage must be a non-empty string")
        require_tz_aware(cutoff, name="cutoff")
        if isinstance(root_version, bool) or not isinstance(root_version, int):
            raise TypeError("root_version must be an integer")
        if account_version is not None and (
            isinstance(account_version, bool) or not isinstance(account_version, int)
        ):
            raise TypeError("account_version must be an integer or None")
        if pending_id is not None and (not isinstance(pending_id, str) or not pending_id):
            raise ValueError("pending_id must be a non-empty string or None")
        if not isinstance(cause, Exception):
            raise TypeError("cause must be an Exception")
        self.stage = stage
        self.mutation = False
        self.cutoff = cutoff
        self.root_version = root_version
        self.account_version = account_version
        self.pending_id = pending_id
        self.cause_type = type(cause).__name__
        self.detail = str(cause)
        super().__init__(f"{stage}: {cause}")


@dataclass(frozen=True, slots=True)
class CallbackEvidence:
    stage: str
    mutation: bool
    root_version: int
    cutoff: datetime
    account: AccountSnapshot
    pending_id: str | None
    decision: object
    constraints: tuple[object, ...]

    def __post_init__(self) -> None:
        _common(self.stage, self.mutation, self.root_version, self.cutoff, self.account)
        if self.pending_id is not None and (
            not isinstance(self.pending_id, str) or not self.pending_id
        ):
            raise ValueError("pending_id must be a non-empty string or None")
        if not isinstance(self.constraints, tuple):
            raise TypeError("constraints must be a tuple")


@dataclass(frozen=True, slots=True)
class DueExecutionEvidence:
    stage: str
    mutation: bool
    root_version: int
    cutoff: datetime
    pending_id: str
    before: AccountSnapshot
    after: AccountSnapshot
    nav: Decimal
    marks: MarkBatch
    orders: object
    fills: object
    constraints: tuple[object, ...]

    def __post_init__(self) -> None:
        _common(self.stage, self.mutation, self.root_version, self.cutoff, self.after)
        if not isinstance(self.pending_id, str) or not self.pending_id:
            raise ValueError("pending_id must be a non-empty string")
        if not isinstance(self.before, AccountSnapshot):
            raise TypeError("before must be an AccountSnapshot")
        if not isinstance(self.nav, Decimal) or not self.nav.is_finite():
            raise ValueError("nav must be a finite Decimal")
        if not isinstance(self.marks, MarkBatch):
            raise TypeError("marks must be a MarkBatch")
        if not isinstance(self.constraints, tuple):
            raise TypeError("constraints must be a tuple")


@dataclass(frozen=True, slots=True)
class ValuationEvidence:
    stage: str
    mutation: bool
    root_version: int
    cutoff: datetime
    account: AccountSnapshot
    nav: Decimal
    marks: MarkBatch

    def __post_init__(self) -> None:
        _common(self.stage, self.mutation, self.root_version, self.cutoff, self.account)
        if not isinstance(self.nav, Decimal) or not self.nav.is_finite():
            raise ValueError("nav must be a finite Decimal")
        if not isinstance(self.marks, MarkBatch):
            raise TypeError("marks must be a MarkBatch")


@dataclass(frozen=True, slots=True)
class FinalizationEvidence:
    stage: str
    mutation: bool
    root_version: int
    cutoff: datetime
    account: AccountSnapshot | None

    def __post_init__(self) -> None:
        if not isinstance(self.stage, str) or not self.stage:
            raise ValueError("stage must be a non-empty string")
        if self.mutation is not False:
            raise ValueError("evidence must be prepared before mutation")
        if (
            isinstance(self.root_version, bool)
            or not isinstance(self.root_version, int)
            or self.root_version < 0
        ):
            raise ValueError("root_version must be a non-negative integer")
        require_tz_aware(self.cutoff, name="cutoff")
        if self.account is not None and not isinstance(self.account, AccountSnapshot):
            raise TypeError("account must be an AccountSnapshot or None")


def _common(
    stage: str, mutation: bool, root_version: int, cutoff: datetime, account: AccountSnapshot
) -> None:
    if not isinstance(stage, str) or not stage:
        raise ValueError("stage must be a non-empty string")
    if mutation is not False:
        raise ValueError("evidence must be prepared before mutation")
    if isinstance(root_version, bool) or not isinstance(root_version, int) or root_version < 0:
        raise ValueError("root_version must be a non-negative integer")
    require_tz_aware(cutoff, name="cutoff")
    if not isinstance(account, AccountSnapshot):
        raise TypeError("account must be an AccountSnapshot")
