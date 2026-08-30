"""Accepted callback state and staged Account lifecycle publication."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from itertools import chain
from types import MappingProxyType
from typing import Any

from vqapr.account.account import (
    PreparedAccountFill,
    PreparedAccountTransition,
    PreparedAccountValuation,
)
from vqapr.account.snapshot import AccountState
from vqapr.domain.references import ModelStateRef
from vqapr.evidence.recorder import InvocationRecorder, RecorderManifest
from vqapr.flow.model_state import prepare_model_state
from vqapr.models.memory import ModelMemory, normalize_memory
from vqapr.valuation.marks import MarkBatch


class LifecycleKind(StrEnum):
    NO_DECISION = "NO_DECISION"
    ACCEPTED_INTENT = "ACCEPTED_INTENT"
    ACCOUNT_COMMITTED = "ACCOUNT_COMMITTED"
    MARKED = "MARKED"
    FEEDBACK_PUBLISHED = "FEEDBACK_PUBLISHED"


@dataclass(frozen=True, slots=True)
class LifecycleTrace:
    kind: LifecycleKind
    detail: object = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, LifecycleKind):
            raise TypeError("kind must be a LifecycleKind")


@dataclass(frozen=True, slots=True)
class RunFinalization:
    """Typed terminal declaration published through the sole state root."""

    provenance: object


@dataclass(frozen=True, slots=True)
class AcceptedRunState:
    """The complete visible authority. Readers must only traverse this root."""

    version: int
    _model_states: Mapping[ModelStateRef, ModelMemory]
    _payloads: Mapping[ModelStateRef, bytes]
    current_model_state_ref: ModelStateRef | None
    account: AccountState | None = None
    pending_accepted_intent: object = None
    lifecycle_trace: tuple[LifecycleTrace, ...] = ()
    recorder_manifests: tuple[RecorderManifest, ...] = ()
    # Per table, the chunks appended by each accepted callback. Appending a chunk is O(new rows);
    # re-wrapping the whole accumulated history on every root was O(all rows so far), which made
    # total cost quadratic in run length. Readers see the flattened view through `recorder_rows`.
    _recorder_chunks: Mapping[str, tuple[tuple[Mapping[str, object], ...], ...]] = MappingProxyType(
        {}
    )
    feedback: tuple[object, ...] = ()
    finalization: object = None
    model_state_commit_count: int = 0
    # Refs a previous root already proved. A ModelStateRef is only ever minted by
    # prepare_model_state, so re-deriving it for an already-proved ref re-proves nothing; it just
    # re-serialises and re-hashes the entire accumulated history on every root. Defaulting to
    # empty means a root built from outside this module is still verified in full.
    _verified: frozenset[ModelStateRef] = frozenset()

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 0:
            raise ValueError("version must be a non-negative integer")
        if self.account is not None and not isinstance(self.account, AccountState):
            raise TypeError("account must be an AccountState or None")
        if self.finalization is not None and not isinstance(self.finalization, RunFinalization):
            raise TypeError("finalization must be a RunFinalization or None")
        if (
            self.current_model_state_ref is not None
            and self.current_model_state_ref not in self._model_states
        ):
            raise ValueError("current_model_state_ref must be visible in this root")
        # Key views compare as sets without building two of them. The visible refs grow by one
        # per callback and are never pruned, so anything that allocates per root here is a term
        # that grows with run length.
        if self._payloads.keys() != self._model_states.keys():
            raise ValueError("payloads must be keyed by exactly the visible ModelStateRefs")
        unverified = [ref for ref in self._model_states if ref not in self._verified]
        for ref in unverified:
            memory = self._model_states[ref]
            payload = self._payloads[ref]
            if not isinstance(payload, bytes):
                _invalid_payload(ref)
            if prepare_model_state(memory, payload).ref != ref:
                raise ValueError("ModelStateRef must identify its exact memory and payload")
        # Detach by copying -- an externally supplied mapping must not stay reachable for
        # mutation -- but normalize and re-check only the refs no earlier root proved. The copy
        # itself runs in C; the per-entry work does not, so it is the part worth narrowing.
        states = dict(self._model_states)
        payloads = dict(self._payloads)
        for ref in unverified:
            states[ref] = normalize_memory(states[ref])
            payloads[ref] = bytes(payloads[ref])
        object.__setattr__(self, "_model_states", MappingProxyType(states))
        object.__setattr__(self, "_payloads", MappingProxyType(payloads))
        # Everything visible in this root has now been proved, either by an earlier root or by
        # the loop above.
        object.__setattr__(self, "_verified", frozenset(self._model_states))
        object.__setattr__(
            self,
            "_recorder_chunks",
            MappingProxyType(
                {name: tuple(chunks) for name, chunks in self._recorder_chunks.items()}
            ),
        )

    @property
    def recorder_rows(self) -> Mapping[str, tuple[Mapping[str, object], ...]]:
        """The flattened rows every reader has always seen.

        Rows are wrapped read-only once, where the chunk is appended, so flattening here only
        concatenates references. The sole in-run consumer is `publish_run_record`, after the run;
        everything else reads this in tests and showcases.
        """
        return MappingProxyType(
            {
                name: tuple(chain.from_iterable(chunks))
                for name, chunks in self._recorder_chunks.items()
            }
        )

    @property
    def model_states(self) -> Mapping[ModelStateRef, ModelMemory]:
        return MappingProxyType(
            {ref: normalize_memory(memory) for ref, memory in self._model_states.items()}
        )

    def load_model_state(self, ref: ModelStateRef) -> ModelMemory:
        if not isinstance(ref, ModelStateRef):
            raise TypeError("ref must be a ModelStateRef")
        try:
            return normalize_memory(self._model_states[ref])
        except KeyError as exc:
            raise KeyError(f"unknown visible ModelStateRef: {ref.digest}") from exc

    def load_payload(self, ref: ModelStateRef) -> bytes:
        if not isinstance(ref, ModelStateRef):
            raise TypeError("ref must be a ModelStateRef")
        try:
            return bytes(self._payloads[ref])
        except KeyError as exc:
            raise KeyError(f"unknown visible ModelStateRef: {ref.digest}") from exc


@dataclass(frozen=True, slots=True)
class PreparedRunState:
    """Validated candidate which is deliberately not visible or loadable."""

    expected_version: int
    root: AcceptedRunState


_UNSET = object()

_FILL_TABLE = "vqapr.fill"
"""Package-owned, fixed-schema record of every committed fill.

Canon 9.1 forbids a *free-form* recorder at the execution stage, because two ways to state the
same fact leaves a reader not knowing which to trust. This is the opposite: one fixed schema the
package writes itself, from the journal entries the Account already committed. It exists so the
fill journal can be published and then dropped from memory rather than carried for the whole run.
"""


def _fill_rows(
    entries: tuple[object, ...], *, envelope: Mapping[str, object] | None = None
) -> tuple[Mapping[str, object], ...]:
    """One row per committed fill, including zero-dealt ones.

    The five envelope fields are stamped here rather than by `InvocationRecorder`, because these
    rows are staged straight into the run-state chunks and never pass through a recorder. That is
    why they carried none of them while `vqapr.account` -- which does go through one -- carried all
    five (`docs/issues/022`).

    `sequence` is per call, matching the recorder's own contract: it numbers rows within one
    staged batch, and `account_version` is what orders batches against each other.

    The parameter is optional because a caller with no occurrence in hand -- the direct
    `AccountState` constructors in the test suite -- has nothing truthful to stamp, and inventing
    an `event_time` would be worse than omitting it. Production always supplies it.

    A refused fill is a market fact the run has to be able to show afterwards, so it is recorded
    with its reason rather than filtered out here.

    `kind` is the category the venue charged this fill under, and it is written here because this
    is the only place a later reader can recover it: the charge is a dictionary lookup at fill
    time and nothing downstream re-derives it. It was computed and then dropped, so every fill in
    a run reported no category even when the project had registered one -- which made
    `FillBatch.cost_by_kind()` collapse to a single unlabelled bucket, and made registering a
    roster produce no observable difference anywhere.

    `None` stays legal and means the run genuinely did not know: no roster reached the venue, or
    the roster described no category for this id. That is a fact worth recording rather than a
    reason to refuse, because a venue charging one flat rate does not need a category at all.
    """
    rows = []
    stamp = dict(envelope or {})
    for sequence, entry in enumerate(entries):
        fill = entry.fill
        cost = fill.cost
        rows.append(
            MappingProxyType(
                {
                    "instrument": str(fill.instrument_id),
                    "kind": None if fill.kind is None else str(fill.kind),
                    "account_version": int(entry.version),
                    "requested_quantity": str(fill.requested_quantity),
                    "dealt_quantity": str(fill.dealt_quantity),
                    "price": None if fill.price is None else str(fill.price),
                    "cash_delta": str(fill.cash_delta),
                    "commission": None if cost is None else str(cost.commission),
                    "tax": None if cost is None else str(cost.tax),
                    "reason": None if fill.reason is None else str(fill.reason),
                    **stamp,
                    **({"sequence": sequence} if stamp else {}),
                }
            )
        )
    return tuple(rows)


def _invalid_payload(ref: ModelStateRef) -> bytes:
    raise TypeError(f"payload for {ref.digest} must be bytes")


class RunStateRepository:
    """Prepare complete immutable roots and publish them with one pointer swap."""

    def __init__(
        self,
        *,
        initial_account: AccountState | None = None,
        initial_model_memory: object = None,
        initial_payload: bytes = b"",
        pending_accepted_intent: object = None,
        before_swap: Callable[[PreparedRunState], None] | None = None,
    ) -> None:
        if not isinstance(initial_payload, bytes):
            raise TypeError("initial_payload must be bytes")
        prepared = prepare_model_state(initial_model_memory, initial_payload)
        states = {prepared.ref: prepared.memory}
        payloads = {prepared.ref: prepared.payload}
        current_ref = prepared.ref
        self._root = AcceptedRunState(
            version=0,
            _model_states=states,
            _payloads=payloads,
            current_model_state_ref=current_ref,
            account=initial_account,
            pending_accepted_intent=pending_accepted_intent,
            model_state_commit_count=0,
        )
        self._before_swap = before_swap

    @property
    def current(self) -> AcceptedRunState:
        return self._root

    @property
    def root(self) -> AcceptedRunState:
        return self._root

    def load_model_state(self, ref: ModelStateRef) -> ModelMemory:
        return self._root.load_model_state(ref)

    def load_payload(self, ref: ModelStateRef) -> bytes:
        return self._root.load_payload(ref)

    def prepare_callback(
        self,
        memory: object,
        payload: bytes,
        *,
        lifecycle: LifecycleTrace,
        recorder: InvocationRecorder | None = None,
        pending_accepted_intent: object = _UNSET,
        expected_version: int | None = None,
    ) -> PreparedRunState:
        """Validate and serialize all callback effects without changing visibility."""
        if not isinstance(lifecycle, LifecycleTrace):
            raise TypeError("lifecycle must be a LifecycleTrace")
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        root = self._root
        if root.finalization is not None:
            raise RuntimeError("cannot publish a callback after finalization")
        expected = root.version if expected_version is None else expected_version
        if expected != root.version:
            raise RuntimeError("run state optimistic conflict")
        candidate = prepare_model_state(memory, payload)
        states = dict(root._model_states)
        states[candidate.ref] = candidate.memory
        payloads = dict(root._payloads)
        payloads[candidate.ref] = candidate.payload
        chunks = dict(root._recorder_chunks)
        manifests = root.recorder_manifests
        if recorder is not None:
            if not isinstance(recorder, InvocationRecorder):
                raise TypeError("recorder must be an InvocationRecorder")
            staged_rows = recorder.staged_rows()
            for table_id, table_rows in staged_rows.items():
                # staged_rows() already returned detached, normalized rows. Wrapping read-only
                # happens once, here, instead of on every subsequent root.
                chunk = tuple(MappingProxyType(row) for row in table_rows)
                chunks[table_id] = (*chunks.get(table_id, ()), chunk)
            manifests = manifests + recorder.manifests()
        next_root = AcceptedRunState(
            version=root.version + 1,
            _model_states=states,
            _payloads=payloads,
            # `candidate` came straight out of prepare_model_state, so its ref is proved by
            # construction; the rest were proved by the root we are extending.
            _verified=root._verified | {candidate.ref},
            current_model_state_ref=candidate.ref,
            account=root.account,
            pending_accepted_intent=(
                root.pending_accepted_intent
                if pending_accepted_intent is _UNSET
                else pending_accepted_intent
            ),
            lifecycle_trace=(*root.lifecycle_trace, lifecycle),
            recorder_manifests=manifests,
            _recorder_chunks=chunks,
            feedback=root.feedback,
            finalization=root.finalization,
            model_state_commit_count=root.model_state_commit_count + 1,
        )
        return PreparedRunState(expected_version=expected, root=next_root)

    def publish(self, prepared: PreparedRunState) -> AcceptedRunState:
        """Perform the sole mutable action after all fallible work is complete."""
        if not isinstance(prepared, PreparedRunState):
            raise TypeError("prepared must be a PreparedRunState")
        if prepared.expected_version != self._root.version:
            raise RuntimeError("run state optimistic conflict")
        if self._before_swap is not None:
            self._before_swap(prepared)
        self._root = prepared.root
        return self._root

    def _publish_infallible(self, prepared: PreparedRunState) -> AcceptedRunState:
        """Publish a prevalidated post-Account candidate without callback hooks."""
        if not isinstance(prepared, PreparedRunState):
            raise TypeError("prepared must be a PreparedRunState")
        if prepared.expected_version != self._root.version:
            raise RuntimeError("run state optimistic conflict")
        self._root = prepared.root
        return self._root

    def prepare_account_commit(
        self,
        *,
        pending_id: str,
        account: PreparedAccountFill,
        fill: object,
        evidence: object = None,
        envelope: Mapping[str, object] | None = None,
    ) -> PreparedRunState:
        """Prepare the root which consumes pending and mirrors the fill commit."""
        root = self._root
        if getattr(root.pending_accepted_intent, "pending_id", None) != pending_id:
            raise RuntimeError("due completion pending identity does not match current pending")
        if root.account != account.source or fill != account.fill_batch:
            raise RuntimeError("prepared Account fill does not match current root")
        committed = AccountState(
            snapshot=account.next_snapshot,
            # Published, not retained. The journal entries this commit produced go into the
            # vqapr.fill chunk below and the account keeps only them, so fill_history stops
            # growing for the life of the run while every fill still reaches parquet.
            mark_history=account.source.mark_history,
            fill_history=tuple(account.journal_entries),
        )
        chunks = dict(root._recorder_chunks)
        rows = _fill_rows(account.journal_entries, envelope=envelope)
        if rows:
            chunks[_FILL_TABLE] = (*chunks.get(_FILL_TABLE, ()), rows)
        return PreparedRunState(
            root.version,
            AcceptedRunState(
                version=root.version + 1,
                _model_states=root._model_states,
                _payloads=root._payloads,
                _verified=root._verified,
                current_model_state_ref=root.current_model_state_ref,
                account=committed,
                pending_accepted_intent=None,
                lifecycle_trace=(
                    *root.lifecycle_trace,
                    LifecycleTrace(LifecycleKind.ACCOUNT_COMMITTED, evidence),
                ),
                recorder_manifests=root.recorder_manifests,
                _recorder_chunks=chunks,
                feedback=root.feedback,
                finalization=root.finalization,
                model_state_commit_count=root.model_state_commit_count,
            ),
        )

    def publish_account_commit(self, prepared: PreparedRunState) -> AcceptedRunState:
        return self._publish_infallible(prepared)

    def prepare_marked(
        self, *, account: PreparedAccountTransition, mark: MarkBatch, evidence: object = None
    ) -> PreparedRunState:
        root = self._root
        if root.account is None or root.account.snapshot != account.fill.next_snapshot:
            raise RuntimeError("prepared Account mark does not match current root")
        if mark != account.next_state.latest_mark.marks:  # type: ignore[union-attr]
            raise ValueError("mark must be the prepared Account mark batch")
        return PreparedRunState(
            root.version,
            AcceptedRunState(
                version=root.version + 1,
                _model_states=root._model_states,
                _payloads=root._payloads,
                _verified=root._verified,
                current_model_state_ref=root.current_model_state_ref,
                account=account.next_state,
                pending_accepted_intent=None,
                lifecycle_trace=(
                    *root.lifecycle_trace,
                    LifecycleTrace(LifecycleKind.MARKED, evidence),
                ),
                recorder_manifests=root.recorder_manifests,
                _recorder_chunks=root._recorder_chunks,
                feedback=root.feedback,
                finalization=root.finalization,
                model_state_commit_count=root.model_state_commit_count,
            ),
        )

    def publish_marked(self, prepared: PreparedRunState) -> AcceptedRunState:
        return self._publish_infallible(prepared)

    def prepare_valuation_only(
        self,
        *,
        pending_id: str,
        account: PreparedAccountValuation,
        mark: MarkBatch,
        evidence: object = None,
    ) -> PreparedRunState:
        """Publish a mark taken by an occurrence that requested no orders.

        The Account did not change, so this consumes the pending identity and appends a mark
        without an ACCOUNT_COMMITTED step. There is no fill to commit.
        """
        root = self._root
        if getattr(root.pending_accepted_intent, "pending_id", None) != pending_id:
            raise RuntimeError("due completion pending identity does not match current pending")
        if root.account is None or root.account != account.source:
            raise RuntimeError("prepared Account valuation does not match current root")
        if mark != account.next_state.latest_mark.marks:  # type: ignore[union-attr]
            raise ValueError("mark must be the prepared Account mark batch")
        return PreparedRunState(
            root.version,
            AcceptedRunState(
                version=root.version + 1,
                _model_states=root._model_states,
                _payloads=root._payloads,
                _verified=root._verified,
                current_model_state_ref=root.current_model_state_ref,
                account=account.next_state,
                pending_accepted_intent=None,
                lifecycle_trace=(
                    *root.lifecycle_trace,
                    LifecycleTrace(LifecycleKind.MARKED, evidence),
                ),
                recorder_manifests=root.recorder_manifests,
                _recorder_chunks=root._recorder_chunks,
                feedback=root.feedback,
                finalization=root.finalization,
                model_state_commit_count=root.model_state_commit_count,
            ),
        )

    def publish_valuation_only(self, prepared: PreparedRunState) -> AcceptedRunState:
        return self._publish_infallible(prepared)

    def prepare_standalone_valuation(
        self,
        *,
        account: PreparedAccountValuation,
        mark: MarkBatch,
        recorder: InvocationRecorder,
        evidence: object = None,
    ) -> PreparedRunState:
        """Publish a mark taken by a valuation occurrence that no decision prepared.

        This is `prepare_valuation_only`'s sibling for the independent valuation clock, and the
        difference between them is the pending slot. `prepare_valuation_only` CONSUMES a pending
        identity, because a NoDecision minted one and the mark is that pending's completion. A
        standalone valuation never minted one: it is its own occurrence on its own clock, so
        there is no identity to match and none to clear. Touching the slot here is precisely what
        must not happen -- it holds at most one occupant, so a daily valuation passing through it
        would evict accepted decisions on most sessions.

        The Account does not change, so there is no ACCOUNT_COMMITTED step. The recorder rows are
        staged the same way a callback's are, because the NAV series has to be readable from the
        same table whichever clock measured it.
        """
        if not isinstance(recorder, InvocationRecorder):
            raise TypeError("recorder must be an InvocationRecorder")
        root = self._root
        if root.account is None or root.account != account.source:
            raise RuntimeError("prepared Account valuation does not match current root")
        if mark != account.next_state.latest_mark.marks:  # type: ignore[union-attr]
            raise ValueError("mark must be the prepared Account mark batch")

        chunks = dict(root._recorder_chunks)
        for table_id, table_rows in recorder.staged_rows().items():
            chunk = tuple(MappingProxyType(row) for row in table_rows)
            chunks[table_id] = (*chunks.get(table_id, ()), chunk)

        return PreparedRunState(
            root.version,
            AcceptedRunState(
                version=root.version + 1,
                _model_states=root._model_states,
                _payloads=root._payloads,
                _verified=root._verified,
                current_model_state_ref=root.current_model_state_ref,
                account=account.next_state,
                # Left exactly as found. A standalone valuation neither takes nor releases it.
                pending_accepted_intent=root.pending_accepted_intent,
                lifecycle_trace=(
                    *root.lifecycle_trace,
                    LifecycleTrace(LifecycleKind.MARKED, evidence),
                ),
                recorder_manifests=root.recorder_manifests + recorder.manifests(),
                _recorder_chunks=chunks,
                feedback=root.feedback,
                finalization=root.finalization,
                model_state_commit_count=root.model_state_commit_count,
            ),
        )

    def publish_standalone_valuation(self, prepared: PreparedRunState) -> AcceptedRunState:
        return self._publish_infallible(prepared)

    def prepare_feedback(
        self, feedback: tuple[object, ...], *, evidence: object = None
    ) -> PreparedRunState:
        if not isinstance(feedback, tuple):
            raise TypeError("feedback must be a tuple")
        root = self._root
        return PreparedRunState(
            root.version,
            AcceptedRunState(
                version=root.version + 1,
                _model_states=root._model_states,
                _payloads=root._payloads,
                _verified=root._verified,
                current_model_state_ref=root.current_model_state_ref,
                account=root.account,
                pending_accepted_intent=None,
                lifecycle_trace=(
                    *root.lifecycle_trace,
                    LifecycleTrace(LifecycleKind.FEEDBACK_PUBLISHED, evidence),
                ),
                recorder_manifests=root.recorder_manifests,
                _recorder_chunks=root._recorder_chunks,
                feedback=(*root.feedback, *feedback),
                finalization=root.finalization,
                model_state_commit_count=root.model_state_commit_count,
            ),
        )

    def publish_feedback(self, prepared: PreparedRunState) -> AcceptedRunState:
        """Publish already-prepared feedback without running an external hook."""
        return self._publish_infallible(prepared)

    def accept_no_decision(
        self,
        memory: object,
        payload: bytes,
        *,
        detail: object = None,
        recorder: InvocationRecorder | None = None,
    ) -> AcceptedRunState:
        return self.publish(
            self.prepare_callback(
                memory,
                payload,
                lifecycle=LifecycleTrace(LifecycleKind.NO_DECISION, detail),
                recorder=recorder,
            )
        )

    def accept_intent(
        self,
        memory: object,
        payload: bytes,
        intent: object,
        *,
        detail: object = None,
        recorder: InvocationRecorder | None = None,
    ) -> AcceptedRunState:
        return self.publish(
            self.prepare_callback(
                memory,
                payload,
                lifecycle=LifecycleTrace(LifecycleKind.ACCEPTED_INTENT, detail),
                recorder=recorder,
                pending_accepted_intent=intent,
            )
        )

    def prepare_finalization(self, finalization: RunFinalization) -> PreparedRunState:
        """Prepare a typed terminal transition after all pending work is consumed."""
        if not isinstance(finalization, RunFinalization):
            raise TypeError("finalization must be a RunFinalization")
        root = self._root
        if root.pending_accepted_intent is not None:
            raise RuntimeError("cannot finalize with a pending accepted intent")
        if root.finalization is not None:
            raise RuntimeError("run is already finalized")
        return PreparedRunState(
            root.version,
            AcceptedRunState(
                version=root.version + 1,
                _model_states=root._model_states,
                _payloads=root._payloads,
                _verified=root._verified,
                current_model_state_ref=root.current_model_state_ref,
                account=root.account,
                pending_accepted_intent=None,
                lifecycle_trace=root.lifecycle_trace,
                recorder_manifests=root.recorder_manifests,
                _recorder_chunks=root._recorder_chunks,
                feedback=root.feedback,
                finalization=finalization,
                model_state_commit_count=root.model_state_commit_count,
            ),
        )

    def finalize(self, finalization: RunFinalization) -> AcceptedRunState:
        return self.publish(self.prepare_finalization(finalization))


def capture_live_memory(memory: object) -> ModelMemory:
    """Capture a detached invocation baseline for restoration after a rejected callback."""
    return normalize_memory(memory)


def restore_live_memory(model: Any, memory: object) -> None:
    """Restore a Model's mutable live memory from a detached baseline."""
    model.memory = normalize_memory(memory)
