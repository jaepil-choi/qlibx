"""Accepted callback state and staged Account lifecycle publication."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from vqapr.account.account import PreparedAccountFill, PreparedAccountTransition
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
    recorder_rows: Mapping[str, tuple[Mapping[str, object], ...]] = MappingProxyType({})
    feedback: tuple[object, ...] = ()
    finalization: object = None
    model_state_commit_count: int = 0

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
        if set(self._payloads) != set(self._model_states):
            raise ValueError("payloads must be keyed by exactly the visible ModelStateRefs")
        for ref, memory in self._model_states.items():
            payload = self._payloads[ref]
            if not isinstance(payload, bytes):
                _invalid_payload(ref)
            if prepare_model_state(memory, payload).ref != ref:
                raise ValueError("ModelStateRef must identify its exact memory and payload")
        object.__setattr__(
            self,
            "_model_states",
            MappingProxyType(
                {ref: normalize_memory(memory) for ref, memory in self._model_states.items()}
            ),
        )
        object.__setattr__(
            self,
            "_payloads",
            MappingProxyType(
                {
                    ref: bytes(payload) if isinstance(payload, bytes) else _invalid_payload(ref)
                    for ref, payload in self._payloads.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "recorder_rows",
            MappingProxyType(
                {
                    name: tuple(MappingProxyType(dict(row)) for row in rows)
                    for name, rows in self.recorder_rows.items()
                }
            ),
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
        rows = dict(root.recorder_rows)
        manifests = root.recorder_manifests
        if recorder is not None:
            if not isinstance(recorder, InvocationRecorder):
                raise TypeError("recorder must be an InvocationRecorder")
            staged_rows = recorder.staged_rows()
            for table_id, table_rows in staged_rows.items():
                rows[table_id] = rows.get(table_id, ()) + table_rows
            manifests = manifests + recorder.manifests()
        next_root = AcceptedRunState(
            version=root.version + 1,
            _model_states=states,
            _payloads=payloads,
            current_model_state_ref=candidate.ref,
            account=root.account,
            pending_accepted_intent=(
                root.pending_accepted_intent
                if pending_accepted_intent is _UNSET
                else pending_accepted_intent
            ),
            lifecycle_trace=(*root.lifecycle_trace, lifecycle),
            recorder_manifests=manifests,
            recorder_rows=rows,
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
    ) -> PreparedRunState:
        """Prepare the root which consumes pending and mirrors the fill commit."""
        root = self._root
        if getattr(root.pending_accepted_intent, "pending_id", None) != pending_id:
            raise RuntimeError("due completion pending identity does not match current pending")
        if root.account != account.source or fill != account.fill_batch:
            raise RuntimeError("prepared Account fill does not match current root")
        committed = AccountState(
            snapshot=account.next_snapshot,
            mark_history=account.source.mark_history,
            fill_history=(*account.source.fill_history, *account.journal_entries),
        )
        return PreparedRunState(
            root.version,
            AcceptedRunState(
                version=root.version + 1,
                _model_states=root._model_states,
                _payloads=root._payloads,
                current_model_state_ref=root.current_model_state_ref,
                account=committed,
                pending_accepted_intent=None,
                lifecycle_trace=(
                    *root.lifecycle_trace,
                    LifecycleTrace(LifecycleKind.ACCOUNT_COMMITTED, evidence),
                ),
                recorder_manifests=root.recorder_manifests,
                recorder_rows=root.recorder_rows,
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
                current_model_state_ref=root.current_model_state_ref,
                account=account.next_state,
                pending_accepted_intent=None,
                lifecycle_trace=(
                    *root.lifecycle_trace,
                    LifecycleTrace(LifecycleKind.MARKED, evidence),
                ),
                recorder_manifests=root.recorder_manifests,
                recorder_rows=root.recorder_rows,
                feedback=root.feedback,
                finalization=root.finalization,
                model_state_commit_count=root.model_state_commit_count,
            ),
        )

    def publish_marked(self, prepared: PreparedRunState) -> AcceptedRunState:
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
                current_model_state_ref=root.current_model_state_ref,
                account=root.account,
                pending_accepted_intent=None,
                lifecycle_trace=(
                    *root.lifecycle_trace,
                    LifecycleTrace(LifecycleKind.FEEDBACK_PUBLISHED, evidence),
                ),
                recorder_manifests=root.recorder_manifests,
                recorder_rows=root.recorder_rows,
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
                current_model_state_ref=root.current_model_state_ref,
                account=root.account,
                pending_accepted_intent=None,
                lifecycle_trace=root.lifecycle_trace,
                recorder_manifests=root.recorder_manifests,
                recorder_rows=root.recorder_rows,
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
