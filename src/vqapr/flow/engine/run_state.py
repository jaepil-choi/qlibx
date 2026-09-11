"""Accepted callback state and staged Account lifecycle publication."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from itertools import count
from types import MappingProxyType

from vqapr.account.account import (
    PreparedAppend,
    PreparedMark,
)
from vqapr.authoring.records import InvocationRecorder
from vqapr.domain.account_state import AccountState
from vqapr.domain.identifiers import ModelStateRef
from vqapr.domain.ledger import FILL_ORIGIN, LedgerEntry
from vqapr.domain.model_state import PreparedModelState, prepare_model_state
from vqapr.domain.shapes import RecordChunk
from vqapr.domain.values import ModelMemory, normalize_memory, opening_memory


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


_DECISION_KINDS = frozenset({LifecycleKind.NO_DECISION, LifecycleKind.ACCEPTED_INTENT})
"""The lifecycle entries whose detail is a decision's `CallbackEvidence` -- `callback_evidence`
reads them, and a run with a record keeps them (record `256`)."""

_BARE = {kind: LifecycleTrace(kind) for kind in LifecycleKind}
"""One detail-less entry per kind, shared: what a run with a record keeps of a fill-side event."""


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
    # Per table, the chunks appended by each accepted callback -- columns, not rows (record
    # `221`). Appending a chunk is O(new rows); re-wrapping the whole accumulated history on every
    # root was O(all rows so far), which made total cost quadratic in run length. Readers see the
    # flattened row view through `recorder_rows`.
    _recorder_chunks: Mapping[str, tuple[RecordChunk, ...]] = MappingProxyType({})
    feedback: tuple[object, ...] = ()
    finalization: RunFinalization | None = None
    model_state_commit_count: int = 0
    # Every Component carries memory (records `181`, `184`): a Compliance rule's and the venue's are
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

        The chunks are columns; this is the one place rows are rebuilt from them, read-only.
        Read in tests and showcases; a run with a store has already streamed every chunk to its
        record directory, which is what a later run reads, and holds none here.
        """
        return MappingProxyType(
            {
                name: tuple(MappingProxyType(row) for chunk in chunks for row in chunk.rows())
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
            component_id: normalize_memory(self._model_states[ref])
            for component_id, ref in self.component_state_refs.items()
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
    for component_id, memory in component_memory.items():
        candidate = prepare_model_state(memory, b"")
        states[candidate.ref] = candidate.memory
        payloads[candidate.ref] = candidate.payload
        refs[component_id] = candidate.ref
        proved.add(candidate.ref)
    return refs, frozenset(proved)


@dataclass(frozen=True, slots=True)
class PreparedRunState:
    """Validated candidate which is deliberately not visible or loadable."""

    expected_version: int
    root: AcceptedRunState
    new_chunks: tuple[RecordChunk, ...] = ()
    """The recorder chunks this candidate adds, when the repository streams them.

    Empty when the repository has no sink: the chunks are then inside `root` as before.
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
    entries: tuple[LedgerEntry, ...],
    version: int,
    *,
    envelope: Mapping[str, object] | None = None,
    sequencer: Callable[[], int] | None = None,
) -> tuple[Mapping[str, object], ...]:
    """One row per committed fill entry, including zero-dealt ones.

    Read off the ledger entries the append made (record `211`): a fill entry's `detail` is the
    fill's own facts, and `version` is the account version the append produced.

    The five envelope fields are stamped here rather than by `InvocationRecorder`, because these
    rows are staged straight into the run-state chunks and never pass through a recorder. That is
    why they carried none of them while `vqapr.account` -- which does go through one -- carried all
    five (`docs/issues/archive/022`).

    `sequence` comes from the run when the caller supplies its sequencer (record `225`), so a
    fill takes its place in the run's one order beside every other recorded row; without one,
    a batch counts for itself.

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

    The numbers go in as `Decimal` (record `264`). The ledger keeps its facts as text, and these
    rows used to copy that text, so the recorder saw strings and wrote untagged string columns:
    every reader got `"15900.0"` for a price while `nav` came back a `Decimal`, and three testbed
    agents' exporters broke on the difference. A `Decimal` is recorded as the same exact text, now
    tagged, so `read_table` restores it.
    """
    rows = []
    stamp = dict(envelope or {})
    position = count().__next__ if sequencer is None else sequencer
    for entry in entries:
        if entry.origin != FILL_ORIGIN:
            continue
        detail = entry.detail
        rows.append(
            MappingProxyType(
                {
                    "instrument": str(detail["instrument"]),
                    "kind": detail.get("kind"),
                    "account_version": int(version),
                    "requested_quantity": _number(detail["requested_quantity"]),
                    "sized_quantity": _number(detail.get("sized_quantity")),
                    "dealt_quantity": _number(detail["dealt_quantity"]),
                    "price": _number(detail.get("price")),
                    "cash_delta": entry.cash,
                    "commission": _number(detail.get("commission")),
                    "tax": _number(detail.get("tax")),
                    "reason": detail.get("reason"),
                    **stamp,
                    **({"sequence": position()} if stamp else {}),
                }
            )
        )
    return tuple(rows)


def _number(value: object) -> Decimal | None:
    """A ledger detail number as the `Decimal` it was written from; `None` stays `None`."""
    return None if value is None else Decimal(str(value))


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
        sink: Callable[[RecordChunk], None] | None = None,
        initial_component_memory: Mapping[str, object] | None = None,
    ) -> None:
        """`initial_component_memory` is each loaded stateful component's memory as assembled,
        by id -- the Compliance rules', the venue's -- and the run commits what every callback
        leaves from there (record `181`)."""
        if sink is not None and not callable(sink):
            raise TypeError("sink must be callable")
        # `{}` when nothing was handed over (`docs/issues/089`): the same opening memory the
        # frozen layers default to, so a repository seeded without one and a run frozen without
        # one name the same first state.
        prepared = prepare_model_state(opening_memory(initial_model_memory), initial_payload)
        states = {prepared.ref: prepared.memory}
        payloads = {prepared.ref: prepared.payload}
        current_ref = prepared.ref
        component_refs: dict[str, ModelStateRef] = {}
        for component_id, memory in dict(initial_component_memory or {}).items():
            if not component_id:
                raise ValueError("initial_component_memory keys must be component ids")
            seed = prepare_model_state(memory, b"")
            states[seed.ref] = seed.memory
            payloads[seed.ref] = seed.payload
            component_refs[component_id] = seed.ref
        self._root = AcceptedRunState(
            version=0,
            _model_states=states,
            _payloads=payloads,
            current_model_state_ref=current_ref,
            account=initial_account,
            pending_accepted_intent=pending_accepted_intent,
            model_state_commit_count=0,
            component_state_refs=component_refs,
        )
        self._before_swap = before_swap
        # The run's one order for every recorded row (record `225`). Every row a run records
        # passes through this repository, so a counter anywhere else would be a second opinion.
        self._sequence = count()
        # Where accepted recorder chunks go, when they go anywhere but the root. `orchestration.run`
        # passes the run record writer's `append_chunk`; a flow assembled without a store keeps
        # them in its roots as it always did, so every in-memory reader of `recorder_rows` is
        # unchanged.
        self._sink = sink

    @property
    def current(self) -> AcceptedRunState:
        return self._root

    @property
    def keeps_evidence(self) -> bool:
        """Whether this run keeps what its fills produced in memory: only when it has no record.

        A run streaming to a record (`sink`) has its fills, marks and findings as rows there and
        keeps their kinds, not their evidence (record `256`).
        """
        return self._sink is None

    def next_sequence(self) -> int:
        """The next position in the run's one order of recorded rows.

        Handed to every `InvocationRecorder` the run builds and to the fill rows, so `sequence`
        means what its name says across callbacks, valuations and fills alike.
        """
        return next(self._sequence)

    @property
    def root(self) -> AcceptedRunState:
        return self._root

    def load_model_state(self, ref: ModelStateRef) -> ModelMemory:
        return self._root.load_model_state(ref)

    def load_payload(self, ref: ModelStateRef) -> bytes:
        return self._root.load_payload(ref)

    def _stage(
        self,
        chunks: dict[str, tuple[RecordChunk, ...]],
        staged: Sequence[RecordChunk],
    ) -> tuple[RecordChunk, ...]:
        """One occurrence's recorder chunks: into the root, or out to the sink at publish.

        A chunk is detached and validated where it was staged. Without a sink it is appended to
        the root's chunks as before -- O(new rows), so total cost stays linear in run length.
        With one, the root keeps nothing and the chunk rides on the prepared candidate until the
        swap that accepts it.
        """
        new_chunks: list[RecordChunk] = []
        for chunk in staged:
            if self._sink is None:
                chunks[chunk.table_id] = (*chunks.get(chunk.table_id, ()), chunk)
            else:
                new_chunks.append(chunk)
        return tuple(new_chunks)

    def _deliver(self, prepared: PreparedRunState) -> None:
        """Hand an accepted candidate's chunks to the sink, before the swap makes it current.

        Before, not after: a sink that cannot take the rows -- a full disk -- fails the
        occurrence rather than accepting a root whose rows were lost, and everything up to the
        previous occurrence is already on disk.
        """
        if self._sink is None:
            return
        for chunk in prepared.new_chunks:
            self._sink(chunk)

    def _advance(
        self,
        root: AcceptedRunState,
        *,
        lifecycle: LifecycleTrace | None = None,
        states: Mapping[ModelStateRef, ModelMemory] | None = None,
        payloads: Mapping[ModelStateRef, bytes] | None = None,
        verified: frozenset[ModelStateRef] | None = None,
        current_model_state_ref: object = _UNSET,
        component_refs: Mapping[str, ModelStateRef] | None = None,
        account: object = _UNSET,
        pending: object = _UNSET,
        chunks: Mapping[str, tuple[RecordChunk, ...]] | None = None,
        feedback: tuple[object, ...] | None = None,
        finalization: object = _UNSET,
        commits: int = 0,
    ) -> AcceptedRunState:
        """The next root: `root` one version later, with only what a transition names changed.

        Every transition used to spell all fourteen fields of the root it was making, so what a
        transition CHANGED was buried in what it carried over (record `212`). Here a transition
        names its changes and nothing else; the root is otherwise the one it extends.

        **A run with a record keeps the kind of a fill-side event, not its evidence** (record
        `256`). The commit, the mark, the monitoring and the feedback of every fill hung off the
        roots until the run ended -- beside the same evidence in `feedback` and in the market
        clock's traces -- about 1.4 KB a fill that nothing in a stored run reads again: its fills
        are `vqapr.fill` rows the moment they are made (the rule record `221` set for rows). A
        decision's `CallbackEvidence` stays, because `callback_evidence` is how an in-process
        caller reads what its strategy decided. A run without a record keeps everything.
        """
        if lifecycle is not None and not self.keeps_evidence and lifecycle.kind not in (
            _DECISION_KINDS
        ):
            lifecycle = _BARE[lifecycle.kind]
        return AcceptedRunState(
            version=root.version + 1,
            _model_states=root._model_states if states is None else states,
            _payloads=root._payloads if payloads is None else payloads,
            _verified=root._verified if verified is None else verified,
            current_model_state_ref=(
                root.current_model_state_ref
                if current_model_state_ref is _UNSET
                else current_model_state_ref  # type: ignore[arg-type]
            ),
            component_state_refs=(
                root.component_state_refs if component_refs is None else component_refs
            ),
            account=root.account if account is _UNSET else account,  # type: ignore[arg-type]
            pending_accepted_intent=root.pending_accepted_intent if pending is _UNSET else pending,
            lifecycle_trace=(
                root.lifecycle_trace if lifecycle is None else (*root.lifecycle_trace, lifecycle)
            ),
            _recorder_chunks=root._recorder_chunks if chunks is None else chunks,
            feedback=root.feedback if feedback is None else feedback,
            finalization=(
                root.finalization if finalization is _UNSET else finalization  # type: ignore[arg-type]
            ),
            model_state_commit_count=root.model_state_commit_count + commits,
        )

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
        prepared: PreparedModelState | None = None,
    ) -> PreparedRunState:
        """Validate and serialize all callback effects without changing visibility.

        `component_memory` is what each stateful component left, by id, committed in the same
        root as the Strategy's memory; `None` carries the refs over unchanged. `prepared` is the
        candidate the caller already framed with `prepare_model_state` (the callback did, to take
        its ref and to prove the live Strategy reproduces it); handed in, it is not normalized
        and hashed a second time (record `239`). It must be `prepare_model_state`'s own: its ref
        enters the root as proved.
        """
        root = self._root
        if root.finalization is not None:
            raise RuntimeError("cannot publish a callback after finalization")
        expected = root.version if expected_version is None else expected_version
        if expected != root.version:
            raise RuntimeError("run state optimistic conflict")
        candidate = prepared if prepared is not None else prepare_model_state(memory, payload)
        states = dict(root._model_states)
        states[candidate.ref] = candidate.memory
        payloads = dict(root._payloads)
        payloads[candidate.ref] = candidate.payload
        component_refs, proved = _component_states(root, component_memory, states, payloads)
        chunks, new_chunks = self._staged(recorder)
        return PreparedRunState(
            expected,
            self._advance(
                root,
                lifecycle=lifecycle,
                states=states,
                payloads=payloads,
                # `candidate` came straight out of prepare_model_state, so its ref is proved by
                # construction; the rest were proved by the root we are extending.
                verified=root._verified | {candidate.ref} | proved,
                current_model_state_ref=candidate.ref,
                component_refs=component_refs,
                pending=pending_accepted_intent,
                chunks=chunks,
                commits=1,
            ),
            new_chunks,
        )

    def publish(self, prepared: PreparedRunState) -> AcceptedRunState:
        """Perform the sole mutable action after all fallible work is complete."""
        if prepared.expected_version != self._root.version:
            raise RuntimeError("run state optimistic conflict")
        if self._before_swap is not None:
            self._before_swap(prepared)
        self._deliver(prepared)
        self._root = prepared.root
        return self._root

    def publish_infallible(self, prepared: PreparedRunState) -> AcceptedRunState:
        """Publish a prevalidated post-Account candidate without callback hooks.

        One door for every transition after the callback's -- the append, the mark, the
        findings, the feedback -- which until record `212` had a wrapper each that did this.
        """
        if prepared.expected_version != self._root.version:
            raise RuntimeError("run state optimistic conflict")
        self._deliver(prepared)
        self._root = prepared.root
        return self._root

    def _staged(
        self, recorder: InvocationRecorder | None
    ) -> tuple[dict[str, tuple[RecordChunk, ...]], tuple[RecordChunk, ...]]:
        """The root's chunks, extended by `recorder`'s when there is one; and what the sink gets."""
        root = self._root
        chunks = dict(root._recorder_chunks)
        new_chunks: tuple[RecordChunk, ...] = ()
        if recorder is not None:
            new_chunks = self._stage(chunks, recorder.staged_chunks())
        return chunks, new_chunks

    def prepare_account(
        self,
        account: PreparedAppend | PreparedMark,
        *,
        evidence: object = None,
        pending_id: str | None = None,
        envelope: Mapping[str, object] | None = None,
        recorder: InvocationRecorder | None = None,
        component_memory: Mapping[str, object] | None = None,
    ) -> PreparedRunState:
        """Mirror what the Account agreed to -- an append or a mark -- as the next root.

        One door for the two things the ledger accepts (design §5.1; record `212` folded the
        three branches this replaced). An append consumes the pending intent it filled
        (`pending_id` names it), stages its fill rows, and commits what the venue's `execute`
        left in memory. A mark changes no account and no pending slot; it stages the NAV row the
        valuation measured (`recorder`). Both publish `account.next_state`, which the Account
        itself built -- this asks only that it extends the root it is handed.
        """
        root = self._root
        if root.account is None or root.account != account.source:
            raise RuntimeError("prepared Account transition does not match current root")
        states = dict(root._model_states)
        payloads = dict(root._payloads)
        component_refs, proved = _component_states(root, component_memory, states, payloads)
        chunks, new_chunks = self._staged(recorder)
        pending: object = _UNSET
        if isinstance(account, PreparedAppend):
            if getattr(root.pending_accepted_intent, "pending_id", None) != pending_id:
                raise RuntimeError("an append consumes the pending intent it filled; ids differ")
            # Staged like every other table's rows: onto the root without a sink, out to the
            # sink at publish with one (record `211`: until then fill rows reached disk only
            # when the strategy record was frozen, so a run that died left no fill table).
            rows = _fill_rows(
                account.entries,
                account.next_state.snapshot.version,
                envelope=envelope,
                sequencer=self.next_sequence,
            )
            if rows:
                fills = RecordChunk.from_rows(FILL_TABLE, rows)
                new_chunks = (*new_chunks, *self._stage(chunks, (fills,)))
            kind, pending = LifecycleKind.ACCOUNT_COMMITTED, None
        else:
            if pending_id is not None:
                raise RuntimeError("a mark consumes no pending intent")
            kind = LifecycleKind.MARKED
        return PreparedRunState(
            root.version,
            self._advance(
                root,
                lifecycle=LifecycleTrace(kind, evidence),
                states=states,
                payloads=payloads,
                verified=root._verified | proved,
                component_refs=component_refs,
                account=account.next_state,
                pending=pending,
                chunks=chunks,
            ),
            new_chunks,
        )

    def prepare_monitoring(
        self,
        *,
        recorder: InvocationRecorder,
        evidence: object = None,
        component_memory: Mapping[str, object] | None = None,
    ) -> PreparedRunState:
        """Publish the findings the Compliance rules made over the book one mark valued.

        Compliance changes nothing it observes: no fill, no mark, no decision, and the pending
        slot is left exactly as found. What it adds is rows -- one per rule, saying what was
        measured against which limit -- and the memory each rule left (record `181`).
        """
        root = self._root
        states = dict(root._model_states)
        payloads = dict(root._payloads)
        component_refs, proved = _component_states(root, component_memory, states, payloads)
        chunks, new_chunks = self._staged(recorder)
        return PreparedRunState(
            root.version,
            self._advance(
                root,
                lifecycle=LifecycleTrace(LifecycleKind.MONITORED, evidence),
                states=states,
                payloads=payloads,
                verified=root._verified | proved,
                component_refs=component_refs,
                chunks=chunks,
            ),
            new_chunks,
        )

    def prepare_feedback(
        self, feedback: tuple[object, ...], *, evidence: object = None
    ) -> PreparedRunState:
        root = self._root
        return PreparedRunState(
            root.version,
            self._advance(
                root,
                lifecycle=LifecycleTrace(LifecycleKind.FEEDBACK_PUBLISHED, evidence),
                pending=None,
                # Not accumulated by a run with a record (record `256`): nothing in one reads it.
                feedback=(*root.feedback, *feedback) if self.keeps_evidence else None,
            ),
        )

    def prepare_finalization(self, finalization: RunFinalization) -> PreparedRunState:
        """Prepare a typed terminal transition after all pending work is consumed."""
        root = self._root
        if root.pending_accepted_intent is not None:
            raise RuntimeError("cannot finalize with a pending accepted intent")
        if root.finalization is not None:
            raise RuntimeError("run is already finalized")
        return PreparedRunState(
            root.version, self._advance(root, pending=None, finalization=finalization)
        )

    def finalize(self, finalization: RunFinalization) -> AcceptedRunState:
        return self.publish(self.prepare_finalization(finalization))
