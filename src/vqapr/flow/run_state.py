"""Single-root atomic callback state for the future SessionFlow cutover."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from vqapr.domain.references import ModelStateRef
from vqapr.evidence.recorder import InvocationRecorder, RecorderManifest
from vqapr.flow.model_state import InMemoryModelStateStore
from vqapr.models.memory import ModelMemory, normalize_memory


class LifecycleKind(StrEnum):
    NO_DECISION = "NO_DECISION"
    ACCEPTED_INTENT = "ACCEPTED_INTENT"
    DUE_EXECUTED = "DUE_EXECUTED"


@dataclass(frozen=True, slots=True)
class LifecycleTrace:
    kind: LifecycleKind
    detail: object = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, LifecycleKind):
            raise TypeError("kind must be a LifecycleKind")


@dataclass(frozen=True, slots=True)
class AcceptedRunState:
    """The complete visible authority. Readers must only traverse this root."""

    version: int
    _model_states: Mapping[ModelStateRef, ModelMemory]
    current_model_state_ref: ModelStateRef | None
    account_declaration: object = None
    account_version: int = 0
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
        if (
            self.current_model_state_ref is not None
            and self.current_model_state_ref not in self._model_states
        ):
            raise ValueError("current_model_state_ref must be visible in this root")
        object.__setattr__(
            self,
            "_model_states",
            MappingProxyType(
                {ref: normalize_memory(memory) for ref, memory in self._model_states.items()}
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


@dataclass(frozen=True, slots=True)
class PreparedRunState:
    """Validated candidate which is deliberately not visible or loadable."""

    expected_version: int
    root: AcceptedRunState


_UNSET = object()


class RunStateRepository:
    """Prepare complete immutable roots and publish them with one pointer swap."""

    def __init__(
        self,
        *,
        initial_account: object = None,
        initial_model_memory: object = None,
        pending_accepted_intent: object = None,
        before_swap: Callable[[PreparedRunState], None] | None = None,
        state_store: InMemoryModelStateStore | None = None,
    ) -> None:
        self._state_store = state_store or InMemoryModelStateStore()
        states: dict[ModelStateRef, ModelMemory] = {}
        current_ref: ModelStateRef | None = None
        if initial_model_memory is not None:
            prepared = self._state_store.prepare(initial_model_memory)
            states[prepared.ref] = prepared.memory
            current_ref = prepared.ref
        self._root = AcceptedRunState(
            version=0,
            _model_states=states,
            current_model_state_ref=current_ref,
            account_declaration=initial_account,
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

    def prepare_callback(
        self,
        memory: object,
        *,
        lifecycle: LifecycleTrace,
        recorder: InvocationRecorder | None = None,
        pending_accepted_intent: object = _UNSET,
        expected_version: int | None = None,
    ) -> PreparedRunState:
        """Validate and serialize all callback effects without changing visibility."""
        if not isinstance(lifecycle, LifecycleTrace):
            raise TypeError("lifecycle must be a LifecycleTrace")
        root = self._root
        expected = root.version if expected_version is None else expected_version
        if expected != root.version:
            raise RuntimeError("run state optimistic conflict")
        candidate = self._state_store.prepare(memory)
        states = dict(root._model_states)
        states[candidate.ref] = candidate.memory
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
            current_model_state_ref=candidate.ref,
            account_declaration=root.account_declaration,
            account_version=root.account_version,
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

    def accept_no_decision(
        self, memory: object, *, detail: object = None, recorder: InvocationRecorder | None = None
    ) -> AcceptedRunState:
        return self.publish(
            self.prepare_callback(
                memory,
                lifecycle=LifecycleTrace(LifecycleKind.NO_DECISION, detail),
                recorder=recorder,
            )
        )

    def accept_intent(
        self,
        memory: object,
        intent: object,
        *,
        detail: object = None,
        recorder: InvocationRecorder | None = None,
    ) -> AcceptedRunState:
        return self.publish(
            self.prepare_callback(
                memory,
                lifecycle=LifecycleTrace(LifecycleKind.ACCEPTED_INTENT, detail),
                recorder=recorder,
                pending_accepted_intent=intent,
            )
        )

    def complete_due(
        self,
        *,
        pending_id: str,
        account_declaration: object,
        account_version: int,
        fill: object,
        mark: object,
        feedback: tuple[object, ...] = (),
        evidence: object = None,
    ) -> AcceptedRunState:
        """Atomically publish a completed due chain and consume its exact pending identity."""
        if not isinstance(pending_id, str) or not pending_id:
            raise ValueError("pending_id must be a non-empty string")
        if isinstance(account_version, bool) or not isinstance(account_version, int):
            raise TypeError("account_version must be an integer")
        if account_version < 0:
            raise ValueError("account_version must be non-negative")
        if not isinstance(feedback, tuple):
            raise TypeError("feedback must be a tuple")
        root = self._root
        pending = root.pending_accepted_intent
        if getattr(pending, "pending_id", None) != pending_id:
            raise RuntimeError("due completion pending identity does not match current pending")
        next_root = AcceptedRunState(
            version=root.version + 1,
            _model_states=root._model_states,
            current_model_state_ref=root.current_model_state_ref,
            account_declaration=account_declaration,
            account_version=account_version,
            pending_accepted_intent=None,
            lifecycle_trace=(
                *root.lifecycle_trace,
                LifecycleTrace(
                    LifecycleKind.DUE_EXECUTED,
                    {"pending_id": pending_id, "fill": fill, "mark": mark, "evidence": evidence},
                ),
            ),
            recorder_manifests=root.recorder_manifests,
            recorder_rows=root.recorder_rows,
            feedback=(*root.feedback, *feedback),
            finalization=root.finalization,
            model_state_commit_count=root.model_state_commit_count,
        )
        return self.publish(PreparedRunState(root.version, next_root))

    def record_post_account_failure(
        self,
        *,
        pending_id: str,
        account_declaration: object,
        account_version: int,
        fill: object,
        error: object,
    ) -> AcceptedRunState:
        """Publish the irreversible Account mutation and its failed post-commit stage."""
        if not isinstance(pending_id, str) or not pending_id:
            raise ValueError("pending_id must be a non-empty string")
        root = self._root
        if getattr(root.pending_accepted_intent, "pending_id", None) != pending_id:
            raise RuntimeError(
                "post-account failure pending identity does not match current pending"
            )
        next_root = AcceptedRunState(
            version=root.version + 1,
            _model_states=root._model_states,
            current_model_state_ref=root.current_model_state_ref,
            account_declaration=account_declaration,
            account_version=account_version,
            pending_accepted_intent=root.pending_accepted_intent,
            lifecycle_trace=(
                *root.lifecycle_trace,
                LifecycleTrace(
                    LifecycleKind.DUE_EXECUTED,
                    {"pending_id": pending_id, "fill": fill, "post_account_failure": error},
                ),
            ),
            recorder_manifests=root.recorder_manifests,
            recorder_rows=root.recorder_rows,
            feedback=root.feedback,
            finalization=root.finalization,
            model_state_commit_count=root.model_state_commit_count,
        )
        return self.publish(PreparedRunState(root.version, next_root))


def capture_live_memory(memory: object) -> ModelMemory:
    """Capture a detached invocation baseline for restoration after a rejected callback."""
    return normalize_memory(memory)


def restore_live_memory(model: Any, memory: object) -> None:
    """Restore a Model's mutable live memory from a detached baseline."""
    model.memory = normalize_memory(memory)
