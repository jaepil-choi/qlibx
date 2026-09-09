"""Accepted callback state and staged Account lifecycle publication."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import chain
from types import MappingProxyType

from vqapr.account.account import (
    JournalEntry,
    PreparedAccountFill,
    PreparedAccountTransition,
    PreparedAccountValuation,
)
from vqapr.authoring.records import InvocationRecorder, RecorderManifest
from vqapr.domain.account_state import AccountState
from vqapr.domain.identifiers import ModelStateRef
from vqapr.domain.model_state import prepare_model_state
from vqapr.domain.values import MarkBatch, ModelMemory, normalize_memory


class LifecycleKind(StrEnum):
    NO_DECISION = "NO_DECISION"
    ACCEPTED_INTENT = "ACCEPTED_INTENT"
    ACCOUNT_COMMITTED = "ACCOUNT_COMMITTED"
    MARKED = "MARKED"
    MONITORED = "MONITORED"
    FEEDBACK_PUBLISHED = "FEEDBACK_PUBLISHED"




@dataclass(frozen=True, slots=True)
class LifecycleTrace:
    kind: LifecycleKind
    detail: object = None


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
    finalization: RunFinalization | None = None
    model_state_commit_count: int = 0
    # Every Component carries memory (records `181`, `184`): a Constraint's and the venue's are
    # committed here beside the Strategy's: one ref per component id, into the same map, proved the
    # same way. `current_model_state_ref` stays the Strategy's own; it is the one with a payload.
    component_state_refs: Mapping[str, ModelStateRef] = MappingProxyType({})
    # Refs a previous root already proved. A ModelStateRef is only ever minted by
    # prepare_model_state, so re-deriving it for an already-proved ref re-proves nothing; it just
    # re-serialises and re-hashes the entire accumulated history on every root. Defaulting to
    # empty means a root built from outside this module is still verified in full.
    _verified: frozenset[ModelStateRef] = frozenset()

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 0:
            raise ValueError("version must be a non-negative integer")
        if (
            self.current_model_state_ref is not None
            and self.current_model_state_ref not in self._model_states
        ):
            raise ValueError("current_model_state_ref must be visible in this root")
        for component_id, ref in self.component_state_refs.items():
            if not component_id:
                raise ValueError("component_state_refs keys must be non-empty component ids")
            if ref not in self._model_states:
                raise ValueError(f"component state for {component_id!r} must be visible here")
        object.__setattr__(
            self, "component_state_refs", MappingProxyType(dict(self.component_state_refs))
        )
        # Key views compare as sets without building two of them. The visible refs grow by one
        # per callback and are never pruned, so anything that allocates per root here is a term
        # that grows with run length.
        if self._payloads.keys() != self._model_states.keys():
            raise ValueError("payloads must be keyed by exactly the visible ModelStateRefs")
        unverified = [ref for ref in self._model_states if ref not in self._verified]
        for ref in unverified:
            memory = self._model_states[ref]
            payload = self._payloads[ref]
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
        concatenates references. Read in tests and showcases; a run with a store has already
        streamed every chunk to its record directory, which is what a later run reads.
        """
        return MappingProxyType(
            {
                name: tuple(chain.from_iterable(chunks))
                for name, chunks in self._recorder_chunks.items()
            }
        )

    def load_model_state(self, ref: ModelStateRef) -> ModelMemory:
        try:
            return normalize_memory(self._model_states[ref])
        except KeyError as exc:
            raise KeyError(f"unknown visible ModelStateRef: {ref.digest}") from exc

    def load_payload(self, ref: ModelStateRef) -> bytes:
        try:
            return bytes(self._payloads[ref])
        except KeyError as exc:
            raise KeyError(f"unknown visible ModelStateRef: {ref.digest}") from exc

    def component_memory(self) -> dict[str, ModelMemory]:
        """Every stateful component's visible memory, by id: what a callback restores."""
        return {
            constraint_id: normalize_memory(self._model_states[ref])
            for constraint_id, ref in self.component_state_refs.items()
        }


def _component_states(
    root: AcceptedRunState,
    component_memory: Mapping[str, object] | None,
    states: dict[ModelStateRef, ModelMemory],
    payloads: dict[ModelStateRef, bytes],
) -> tuple[dict[str, ModelStateRef], frozenset[ModelStateRef]]:
    """Detach what each stateful component's callback left, into the maps the next root carries.

    `None` means the occurrence did not run these components, so their refs are carried over
    unchanged. A mapping must name exactly the components the root already knows: one that
    appears from nowhere, or one that vanished, is an assembly error rather than a state change.
    """
    if component_memory is None:
        return dict(root.component_state_refs), frozenset()
    if set(component_memory) != set(root.component_state_refs):
        raise ValueError(
            "component_memory must name exactly the components this run state carries: "
            f"got {sorted(component_memory)!r}, carrying {sorted(root.component_state_refs)!r}"
        )
    refs: dict[str, ModelStateRef] = {}
    proved: set[ModelStateRef] = set()
    for constraint_id, memory in component_memory.items():
        candidate = prepare_model_state(memory, b"")
        states[candidate.ref] = candidate.memory
        payloads[candidate.ref] = candidate.payload
        refs[constraint_id] = candidate.ref
        proved.add(candidate.ref)
    return refs, frozenset(proved)


@dataclass(frozen=True, slots=True)
class PreparedRunState:
    """Validated candidate which is deliberately not visible or loadable."""

    expected_version: int
    root: AcceptedRunState
    new_rows: tuple[tuple[str, tuple[Mapping[str, object], ...]], ...] = ()
    """The recorder chunks this candidate adds, when the repository streams them.

    Empty when the repository has no row sink: the chunks are then inside `root` as before.
    With a sink they are here instead, handed over at publish and never retained by a root, so a
    run's heap holds one occurrence's rows rather than the run's.
    """


_UNSET = object()

FILL_TABLE = "vqapr.fill"
"""The fill journal's table id, named once: `context.DEFAULT_TABLES` builds its spec from
this and every reader imports it from here (one-shape Step 6; it was spelled in three places)."""
"""Package-owned, fixed-schema record of every committed fill.

Canon 9.1 forbids a *free-form* recorder at the execution stage, because two ways to state the
same fact leaves a reader not knowing which to trust. This is the opposite: one fixed schema the
package writes itself, from the journal entries the Account already committed. It exists so the
fill journal can be published and then dropped from memory rather than carried for the whole run.
"""


def _fill_rows(
    entries: tuple[JournalEntry, ...], *, envelope: Mapping[str, object] | None = None
) -> tuple[Mapping[str, object], ...]:
    """One row per committed fill, including zero-dealt ones.

    The five envelope fields are stamped here rather than by `InvocationRecorder`, because these
    rows are staged straight into the run-state chunks and never pass through a recorder. That is
    why they carried none of them while `vqapr.account` -- which does go through one -- carried all
    five (`docs/issues/archive/022`).

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
    the report's cost by kind collapse to a single "unknown" bucket, and made registering a
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
        row_sink: Callable[[str, Sequence[Mapping[str, object]]], None] | None = None,
        initial_component_memory: Mapping[str, object] | None = None,
    ) -> None:
        """`initial_component_memory` is each loaded constraint's memory as assembled, by id;
        the run commits what every constraint callback leaves from there (record `181`)."""
        if row_sink is not None and not callable(row_sink):
            raise TypeError("row_sink must be callable")
        prepared = prepare_model_state(initial_model_memory, initial_payload)
        states = {prepared.ref: prepared.memory}
        payloads = {prepared.ref: prepared.payload}
        current_ref = prepared.ref
        constraint_refs: dict[str, ModelStateRef] = {}
        for constraint_id, memory in dict(initial_component_memory or {}).items():
            if not constraint_id:
                raise ValueError("initial_component_memory keys must be constraint ids")
            seed = prepare_model_state(memory, b"")
            states[seed.ref] = seed.memory
            payloads[seed.ref] = seed.payload
            constraint_refs[constraint_id] = seed.ref
        self._root = AcceptedRunState(
            version=0,
            _model_states=states,
            _payloads=payloads,
            current_model_state_ref=current_ref,
            account=initial_account,
            pending_accepted_intent=pending_accepted_intent,
            model_state_commit_count=0,
            component_state_refs=constraint_refs,
        )
        self._before_swap = before_swap
        # Where accepted recorder rows go, when they go anywhere but the root. `orchestration.run`
        # passes the run record writer's `append`; a flow assembled without a store keeps rows in
        # its roots as it always did, so every in-memory reader of `recorder_rows` is unchanged.
        self._row_sink = row_sink

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

    def _stage_rows(
        self,
        chunks: dict[str, tuple[tuple[Mapping[str, object], ...], ...]],
        staged_rows: Mapping[str, Sequence[Mapping[str, object]]],
    ) -> tuple[tuple[str, tuple[Mapping[str, object], ...]], ...]:
        """One occurrence's recorder rows: into the root, or out to the sink at publish.

        `staged_rows()` already returned detached, normalized rows. Wrapping read-only happens
        once, here, instead of on every subsequent root. Without a sink the chunk is appended to
        the root's chunks as before -- O(new rows), so total cost stays linear in run length.
        With one, the root keeps nothing and the chunk rides on the prepared candidate until the
        swap that accepts it.
        """
        new_rows: list[tuple[str, tuple[Mapping[str, object], ...]]] = []
        for table_id, table_rows in staged_rows.items():
            chunk = tuple(MappingProxyType(row) for row in table_rows)
            if self._row_sink is None:
                chunks[table_id] = (*chunks.get(table_id, ()), chunk)
            else:
                new_rows.append((table_id, chunk))
        return tuple(new_rows)

    def _deliver(self, prepared: PreparedRunState) -> None:
        """Hand an accepted candidate's rows to the sink, before the swap makes it current.

        Before, not after: a sink that cannot take the rows -- a full disk -- fails the
        occurrence rather than accepting a root whose rows were lost, and everything up to the
        previous occurrence is already on disk.
        """
        if self._row_sink is None or not prepared.new_rows:
            return
        for table_id, rows in prepared.new_rows:
            self._row_sink(table_id, rows)

    def prepare_callback(
        self,
        memory: object,
        payload: bytes,
        *,
        lifecycle: LifecycleTrace,
        recorder: InvocationRecorder | None = None,
        pending_accepted_intent: object = _UNSET,
        expected_version: int | None = None,
        component_memory: Mapping[str, object] | None = None,
    ) -> PreparedRunState:
        """Validate and serialize all callback effects without changing visibility.

        `component_memory` is what each constraint's `project` left, by id, committed in the
        same root as the Strategy's memory; `None` carries the constraints' refs over unchanged.
        """
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
        constraint_refs, proved = _component_states(root, component_memory, states, payloads)
        chunks = dict(root._recorder_chunks)
        manifests = root.recorder_manifests
        new_rows: tuple[tuple[str, tuple[Mapping[str, object], ...]], ...] = ()
        if recorder is not None:
            new_rows = self._stage_rows(chunks, recorder.staged_rows())
            manifests = manifests + recorder.manifests()
        next_root = AcceptedRunState(
            version=root.version + 1,
            _model_states=states,
            _payloads=payloads,
            # `candidate` came straight out of prepare_model_state, so its ref is proved by
            # construction; the rest were proved by the root we are extending.
            _verified=root._verified | {candidate.ref} | proved,
            current_model_state_ref=candidate.ref,
            component_state_refs=constraint_refs,
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
        return PreparedRunState(expected_version=expected, root=next_root, new_rows=new_rows)

    def publish(self, prepared: PreparedRunState) -> AcceptedRunState:
        """Perform the sole mutable action after all fallible work is complete."""
        if prepared.expected_version != self._root.version:
            raise RuntimeError("run state optimistic conflict")
        if self._before_swap is not None:
            self._before_swap(prepared)
        self._deliver(prepared)
        self._root = prepared.root
        return self._root

    def _publish_infallible(self, prepared: PreparedRunState) -> AcceptedRunState:
        """Publish a prevalidated post-Account candidate without callback hooks."""
        if prepared.expected_version != self._root.version:
            raise RuntimeError("run state optimistic conflict")
        self._deliver(prepared)
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
        component_memory: Mapping[str, object] | None = None,
    ) -> PreparedRunState:
        """Prepare the root which consumes pending and mirrors the fill commit.

        `component_memory` is what the venue's `execute` -- and any other stateful component
        this due item called -- left in memory (record `184`), committed with the fills it
        produced; `None` carries every ref over unchanged.
        """
        root = self._root
        if getattr(root.pending_accepted_intent, "pending_id", None) != pending_id:
            raise RuntimeError("due completion pending identity does not match current pending")
        if root.account != account.source or fill != account.fill_batch:
            raise RuntimeError("prepared Account fill does not match current root")
        states = dict(root._model_states)
        payloads = dict(root._payloads)
        component_refs, proved = _component_states(root, component_memory, states, payloads)
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
            chunks[FILL_TABLE] = (*chunks.get(FILL_TABLE, ()), rows)
        return PreparedRunState(
            root.version,
            AcceptedRunState(
                version=root.version + 1,
                _model_states=states,
                _payloads=payloads,
                _verified=root._verified | proved,
                current_model_state_ref=root.current_model_state_ref,
                component_state_refs=component_refs,
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

    def _staged(
        self, recorder: InvocationRecorder | None
    ) -> tuple[dict, tuple[RecorderManifest, ...], tuple]:
        """The root's chunks and manifests, extended by `recorder`'s rows when there is one."""
        root = self._root
        chunks = dict(root._recorder_chunks)
        manifests = root.recorder_manifests
        new_rows: tuple[tuple[str, tuple[Mapping[str, object], ...]], ...] = ()
        if recorder is not None:
            new_rows = self._stage_rows(chunks, recorder.staged_rows())
            manifests = manifests + recorder.manifests()
        return chunks, manifests, new_rows

    def prepare_marked(
        self,
        *,
        account: PreparedAccountTransition,
        mark: MarkBatch,
        evidence: object = None,
        recorder: InvocationRecorder | None = None,
    ) -> PreparedRunState:
        """Publish the mark a fill was valued at, and the NAV it measured.

        Valuation happens at the instant the venue fills (record 148): the marked account and
        the account-table row stating its NAV are one commit, so the rows a run reads its NAV
        series from can never disagree with the marks the run holds.
        """
        root = self._root
        if root.account is None or root.account.snapshot != account.fill.next_snapshot:
            raise RuntimeError("prepared Account mark does not match current root")
        if mark != account.next_state.latest_mark.marks:  # type: ignore[union-attr]
            raise ValueError("mark must be the prepared Account mark batch")
        chunks, manifests, new_rows = self._staged(recorder)
        return PreparedRunState(
            root.version,
            AcceptedRunState(
                version=root.version + 1,
                _model_states=root._model_states,
                _payloads=root._payloads,
                _verified=root._verified,
                current_model_state_ref=root.current_model_state_ref,
                component_state_refs=root.component_state_refs,
                account=account.next_state,
                pending_accepted_intent=None,
                lifecycle_trace=(
                    *root.lifecycle_trace,
                    LifecycleTrace(LifecycleKind.MARKED, evidence),
                ),
                recorder_manifests=manifests,
                _recorder_chunks=chunks,
                feedback=root.feedback,
                finalization=root.finalization,
                model_state_commit_count=root.model_state_commit_count,
            ),
            new_rows,
        )

    def publish_marked(self, prepared: PreparedRunState) -> AcceptedRunState:
        return self._publish_infallible(prepared)

    def prepare_valuation_only(
        self,
        *,
        account: PreparedAccountValuation,
        mark: MarkBatch,
        evidence: object = None,
        recorder: InvocationRecorder | None = None,
    ) -> PreparedRunState:
        """Publish a mark taken at a market-clock instant no fill was due at (design §3.1).

        The Account did not change, so this appends a mark without an ACCOUNT_COMMITTED step,
        and it leaves the pending intent -- whose target is a LATER instant -- exactly where it
        was. The NAV measured rides along as `recorder` rows, as it does on `prepare_marked`.
        """
        root = self._root
        if root.account is None or root.account != account.source:
            raise RuntimeError("prepared Account valuation does not match current root")
        if mark != account.next_state.latest_mark.marks:  # type: ignore[union-attr]
            raise ValueError("mark must be the prepared Account mark batch")
        chunks, manifests, new_rows = self._staged(recorder)
        return PreparedRunState(
            root.version,
            AcceptedRunState(
                version=root.version + 1,
                _model_states=root._model_states,
                _payloads=root._payloads,
                _verified=root._verified,
                current_model_state_ref=root.current_model_state_ref,
                component_state_refs=root.component_state_refs,
                account=account.next_state,
                pending_accepted_intent=root.pending_accepted_intent,
                lifecycle_trace=(
                    *root.lifecycle_trace,
                    LifecycleTrace(LifecycleKind.MARKED, evidence),
                ),
                recorder_manifests=manifests,
                _recorder_chunks=chunks,
                feedback=root.feedback,
                finalization=root.finalization,
                model_state_commit_count=root.model_state_commit_count,
            ),
            new_rows,
        )

    def publish_valuation_only(self, prepared: PreparedRunState) -> AcceptedRunState:
        return self._publish_infallible(prepared)

    def prepare_monitoring(
        self,
        *,
        recorder: InvocationRecorder,
        evidence: object = None,
        component_memory: Mapping[str, object] | None = None,
    ) -> PreparedRunState:
        """Publish the findings monitoring made over the account one commit left.

        Monitoring changes nothing it observes: no fill, no mark, no decision, and the pending
        slot is left exactly as found -- it runs right after a commit (record `148`), and the
        commit already settled that slot. What it adds is rows -- one per constraint, saying what
        was measured against which limit -- and until this path existed those rows had nowhere to
        go. The report sat
        on the occurrence trace, the record counted it (`contract`), and the values themselves
        never reached disk: a run whose book breached a limit could say *that* it did, and not
        *by how much*.

        `component_memory` is what each constraint's `monitor` left (record `181`): a rule that
        counts its breaches commits the count here, with the findings it counted.
        """
        root = self._root
        chunks = dict(root._recorder_chunks)
        new_rows = self._stage_rows(chunks, recorder.staged_rows())
        states = dict(root._model_states)
        payloads = dict(root._payloads)
        constraint_refs, proved = _component_states(root, component_memory, states, payloads)
        return PreparedRunState(
            root.version,
            AcceptedRunState(
                version=root.version + 1,
                _model_states=states,
                _payloads=payloads,
                _verified=root._verified | proved,
                current_model_state_ref=root.current_model_state_ref,
                component_state_refs=constraint_refs,
                account=root.account,
                pending_accepted_intent=root.pending_accepted_intent,
                lifecycle_trace=(
                    *root.lifecycle_trace,
                    LifecycleTrace(LifecycleKind.MONITORED, evidence),
                ),
                recorder_manifests=root.recorder_manifests + recorder.manifests(),
                _recorder_chunks=chunks,
                feedback=root.feedback,
                finalization=root.finalization,
                model_state_commit_count=root.model_state_commit_count,
            ),
            new_rows,
        )

    def publish_monitoring(self, prepared: PreparedRunState) -> AcceptedRunState:
        return self._publish_infallible(prepared)

    def prepare_feedback(
        self, feedback: tuple[object, ...], *, evidence: object = None
    ) -> PreparedRunState:
        root = self._root
        return PreparedRunState(
            root.version,
            AcceptedRunState(
                version=root.version + 1,
                _model_states=root._model_states,
                _payloads=root._payloads,
                _verified=root._verified,
                current_model_state_ref=root.current_model_state_ref,
                component_state_refs=root.component_state_refs,
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

    def prepare_finalization(self, finalization: RunFinalization) -> PreparedRunState:
        """Prepare a typed terminal transition after all pending work is consumed."""
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
                component_state_refs=root.component_state_refs,
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
