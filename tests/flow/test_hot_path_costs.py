"""The hot path must not silently go back to redoing settled work.

Every cost this file guards is invisible to the rest of the suite. The fixtures are small, so a
per-query re-hash and a per-root re-verification both look free here; they only hurt on a real
warehouse over a long run. These tests therefore assert **counts and shapes**, never wall time,
which would be flaky in CI and would not say what actually regressed.

See `docs/diagnostics/archive/2026-08-19-vqapr-performance.md` sections 6 and 8.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vqapr.data import scan, store
from vqapr.data.requirements import DataRequirement
from vqapr.data.store import DuckDbObservationStore
from vqapr.evidence.recorder import InvocationRecorder
from vqapr.evidence.tables import TableSpec
from vqapr.flow.run_state import LifecycleKind, LifecycleTrace, RunStateRepository
from vqapr.public import (
    DatasetRegistration,
    RowsLookback,
    SourceSpec,
    Workspace,
    register_dataset,
)

NOW = datetime(2024, 3, 5, 4, tzinfo=UTC)
SESSIONS = tuple(datetime(2024, 1, day, 6, 30, tzinfo=UTC) for day in range(1, 11))


@pytest.fixture
def priced_workspace(tmp_path: Path) -> Workspace:
    rows = [
        {"available_at": stamp, "instrument": name, "close": Decimal(100 + index)}
        for index, stamp in enumerate(SESSIONS)
        for name in ("AAA", "BBB")
    ]
    source = tmp_path / "prices.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            rows,
            schema=pa.schema(
                [
                    ("available_at", pa.timestamp("us", tz="UTC")),
                    ("instrument", pa.string()),
                    ("close", pa.decimal128(18, 4)),
                ]
            ),
        ),
        source,
    )
    # Registered through the public entry point, which measures the span persistence requires.
    register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "prices",
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
        ),
        SourceSpec.of("prices-source", source),
    )
    return Workspace.open(tmp_path)


# --------------------------------------------------------------------------------------
# G-2: physical I/O count
# --------------------------------------------------------------------------------------


def test_one_store_hashes_each_source_once_no_matter_how_many_queries(
    priced_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-hashed bytes used to equal query count times full source size.

    A run's sources are frozen for its whole duration, so the digest cannot change between two
    queries of the same run. `SimulationFlow._actual_source_refs` already refuses a callback that
    observes two digests for one source; computing it once per store makes that unrepresentable
    rather than merely detected.
    """
    calls: list[Path] = []
    original = store.physical_digest

    def counting_digest(path: Path) -> str:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(store, "physical_digest", counting_digest)

    observation_store = DuckDbObservationStore(priced_workspace)
    requirement = DataRequirement.of('prices', 'close', lookback=RowsLookback(2))
    for session in SESSIONS[3:]:
        observation_store.query(
            requirement,
            evaluation_time=session,
            instruments=("AAA", "BBB"),
            consumer_id="test-consumer",
        )

    assert len(calls) == 1, f"expected one digest per source per store, saw {len(calls)}"


def test_two_stores_do_not_share_a_digest_cache(priced_workspace: Workspace) -> None:
    """The cache is scoped to one run, deliberately.

    A process-wide cache would outlive the frozen-run scope that justifies it and would happily
    serve a stale digest to a later run over rewritten bytes.
    """
    requirement = DataRequirement.of('prices', 'close', lookback=RowsLookback(1))
    first = DuckDbObservationStore(priced_workspace)
    second = DuckDbObservationStore(priced_workspace)

    first_batch = first.query(
        requirement,
        evaluation_time=SESSIONS[-1],
        instruments=("AAA",),
        consumer_id="test-consumer",
    )
    second_batch = second.query(
        requirement,
        evaluation_time=SESSIONS[-1],
        instruments=("AAA",),
        consumer_id="test-consumer",
    )

    # Same bytes, so the digests agree; the point is that each store computed it independently.
    assert first_batch.access.source_digest == second_batch.access.source_digest
    assert first is not second


def test_a_scan_session_serves_one_connection_per_source(priced_workspace: Workspace) -> None:
    """duckdb caches parquet metadata per connection; closing per query threw that away."""
    opened: list[object] = []
    session = scan.ScanSession()
    spec = priced_workspace.source("prices-source")

    for _ in range(5):
        opened.append(session.connection(spec))

    assert len({id(connection) for connection in opened}) == 1
    session.close()


def test_the_execution_table_reuses_the_run_connection(priced_workspace: Workspace) -> None:
    """The fill path opened its own duckdb handle on every selected instant.

    A run already opens one connection for observations, but `exact_execution_snapshot` took no
    session, so every fill paid a fresh open and close. Measured on the sample journey that is
    27% of the whole run -- 91.7s to 66.6s -- and it grows with the number of fills, which is the
    axis a 2,096-session backtest scales along.
    """
    spec = priced_workspace.source("prices-source")
    session = scan.ScanSession()
    borrowed = session.connection(spec)

    # Whatever else changes, a session hands back the same physical handle rather than reopening.
    assert session.connection(spec) is borrowed

    # And the execution-table reader accepts one, which is what closes the gap.
    import inspect

    from vqapr.exchange.execution_table import exact_execution_snapshot

    assert "session" in inspect.signature(exact_execution_snapshot).parameters, (
        "the execution table must be able to borrow the run's connection"
    )
    session.close()


def test_a_scan_session_still_refuses_a_missing_path_on_every_lookup(tmp_path: Path) -> None:
    """The typed failure must not be lost to connection reuse.

    If the existence check were bound to connection creation, a source deleted mid-run would
    surface as a raw duckdb error instead of `source.scan.path_missing`.
    """
    from vqapr.domain.errors import VqaprError

    missing = SourceSpec.of("gone", tmp_path / "not-there.parquet")
    session = scan.ScanSession()

    with pytest.raises(VqaprError) as first:
        session.connection(missing)
    with pytest.raises(VqaprError) as second:
        session.connection(missing)

    assert first.value.failures[0].code == "source.scan.path_missing"
    assert second.value.failures[0].code == "source.scan.path_missing"


# --------------------------------------------------------------------------------------
# G-3: verification count is linear in callbacks, not quadratic
# --------------------------------------------------------------------------------------


def _recorder(index: int) -> InvocationRecorder:
    recorder = InvocationRecorder(
        (TableSpec("diagnostics", ("message",)),),
        run_id="run-1",
        producer_id="strategy-1",
        stage="STRATEGY_CALLBACK",
        event_time=NOW,
    )
    recorder.append("diagnostics", {"message": f"observed-{index}"})
    return recorder


def test_model_state_verification_is_linear_in_callback_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each root used to re-hash the entire accumulated history.

    A ModelStateRef is only ever minted by prepare_model_state, so re-deriving one for a ref an
    earlier root already proved re-proves nothing. The bound here is deliberately loose: it only
    has to be tight enough that a return to quadratic behaviour fails it.
    """
    import vqapr.flow.run_state as run_state_module

    calls = 0
    original = run_state_module.prepare_model_state

    def counting_prepare(memory: object, payload: bytes):
        nonlocal calls
        calls += 1
        return original(memory, payload)

    # One module now (one-shape Step 6 folded `model_state` into `run_state`), so one patch.
    monkeypatch.setattr(run_state_module, "prepare_model_state", counting_prepare)

    callbacks = 40
    state = RunStateRepository(initial_model_memory={"n": 0}, initial_payload=b"seed")
    baseline = calls

    for index in range(callbacks):
        prepared = state.prepare_callback(
            {"n": index + 1},
            b"payload",
            lifecycle=LifecycleTrace(LifecycleKind.NO_DECISION),
            recorder=_recorder(index),
        )
        state.publish(prepared)

    used = calls - baseline
    # Quadratic would be ~callbacks^2/2 = 800 here. Linear is a small multiple of callbacks.
    assert used <= 4 * callbacks, f"{used} prepare_model_state calls for {callbacks} callbacks"


def test_recorder_rows_accumulate_without_rebuilding_history() -> None:
    """Rows stay flat, ordered, and read-only through the public view."""
    callbacks = 25
    state = RunStateRepository(initial_model_memory={"n": 0}, initial_payload=b"seed")

    for index in range(callbacks):
        prepared = state.prepare_callback(
            {"n": index + 1},
            b"payload",
            lifecycle=LifecycleTrace(LifecycleKind.NO_DECISION),
            recorder=_recorder(index),
        )
        state.publish(prepared)

    rows = state.root.recorder_rows["diagnostics"]
    assert len(rows) == callbacks
    assert [row["message"] for row in rows] == [f"observed-{i}" for i in range(callbacks)]

    with pytest.raises(TypeError):
        rows[0]["message"] = "mutated"  # type: ignore[index]


def test_an_externally_built_root_is_still_verified_in_full() -> None:
    """The incremental path requires an explicit claim from the previous root.

    `_verified` defaults to empty, so a root built from outside `run_state.py` pays full
    verification. Anything else would let a caller skip the proof by omission.
    """
    from vqapr.flow.run_state import AcceptedRunState, prepare_model_state

    prepared = prepare_model_state({"count": 1}, b"before")

    with pytest.raises(ValueError, match="exact memory and payload"):
        AcceptedRunState(
            version=0,
            _model_states={prepared.ref: prepared.memory},
            _payloads={prepared.ref: b"after"},
            current_model_state_ref=prepared.ref,
        )

    with pytest.raises(ValueError, match="exact memory and payload"):
        AcceptedRunState(
            version=0,
            _model_states={prepared.ref: {"count": 999}},
            _payloads={prepared.ref: prepared.payload},
            current_model_state_ref=prepared.ref,
        )


# --------------------------------------------------------------------------------------
# G-1: a RowsLookback lower bound must not change what a query returns
# --------------------------------------------------------------------------------------

_BOUND_SESSIONS = tuple(
    datetime(2024, 1, 1, 6, 30, tzinfo=UTC) + timedelta(days=day) for day in range(400)
)


@pytest.fixture
def halted_source(tmp_path: Path) -> SourceSpec:
    """A panel whose third name stopped publishing long before the evaluation time.

    This is the case a naive SQL lower bound corrupts in silence: HALTED's last observation is
    340 sessions old, so any bound tight enough to be worth pushing down excludes every row it
    has, and the name vanishes from a result that used to carry its final price.
    """
    rows = [
        {"available_at": stamp, "instrument": name, "close": Decimal(100 + index), "volume": index}
        for index, stamp in enumerate(_BOUND_SESSIONS)
        for name in ("AAA", "BBB")
    ]
    rows.extend(
        {
            "available_at": stamp,
            "instrument": "HALTED",
            "close": Decimal(50 + index),
            "volume": index,
        }
        for index, stamp in enumerate(_BOUND_SESSIONS[:60])
    )
    # A name that lists late has plenty of recent history but less than the declared window.
    rows.extend(
        {
            "available_at": stamp,
            "instrument": "LATE",
            "close": Decimal(70 + index),
            "volume": index,
        }
        for index, stamp in enumerate(_BOUND_SESSIONS[-5:])
    )
    # A name that stops publishing *during* a run, rather than before it. A bound proved while it
    # was still dense outlives that callback, so this is the name that says the proof and the
    # bound it is applied with are the same pair.
    rows.extend(
        {
            "available_at": stamp,
            "instrument": "STOPS",
            "close": Decimal(80 + index),
            "volume": index,
        }
        for index, stamp in enumerate(_BOUND_SESSIONS[:386])
    )
    source = tmp_path / "halted.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            rows,
            schema=pa.schema(
                [
                    ("available_at", pa.timestamp("us", tz="UTC")),
                    ("instrument", pa.string()),
                    ("close", pa.decimal128(18, 4)),
                    ("volume", pa.int64()),
                ]
            ),
        ),
        source,
    )
    return SourceSpec.of("halted-source", source)


@pytest.fixture
def bound_every_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the estimate apply to a fixture-sized source.

    The production gate keeps small sources on the unbounded path, so without this every G-1
    assertion below would pass by never exercising the bound it exists to guard.
    """
    monkeypatch.setattr(scan, "ROWS_BOUND_MIN_BYTES", 0)


_BOUND_NAMES = ("AAA", "BBB", "HALTED", "LATE")


def _observation_rows(
    spec: SourceSpec,
    *,
    rows: int,
    session: scan.ScanSession | None,
    evaluation_time: datetime | None = None,
    instruments: tuple[str, ...] = _BOUND_NAMES,
):
    return scan.observation_rows(
        spec,
        instrument_field="instrument",
        available_at_field="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close", "volume": "volume"},
        aggregated=False,
        instruments=instruments,
        evaluation_time=_BOUND_SESSIONS[-1] if evaluation_time is None else evaluation_time,
        rows=rows,
        session=session,
    )


@contextmanager
def _counted_statements() -> Iterator[list[str]]:
    """Every statement the session issues, in order.

    Counted at `ScanSession.connection` because that is the one door: the estimate, the grid and
    the read all go through it. The cursor setup inside it does not, which is the intent -- what
    is being counted is round trips per callback, not what opening a source costs once.
    """
    issued: list[str] = []
    original = scan.ScanSession.connection

    class _Counting:
        __slots__ = ("_inner",)

        def __init__(self, inner: object) -> None:
            self._inner = inner

        def execute(self, sql: str, *args: object, **kwargs: object) -> object:
            issued.append(sql)
            return self._inner.execute(sql, *args, **kwargs)  # type: ignore[attr-defined]

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    def connection(self: scan.ScanSession, spec: SourceSpec) -> object:
        return _Counting(original(self, spec))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(scan.ScanSession, "connection", connection)
        yield issued


@pytest.mark.parametrize("rows", [1, 5, 60, 120])
def test_a_bounded_rows_lookback_returns_the_unbounded_result(
    halted_source: SourceSpec, bound_every_source: None, rows: int
) -> None:
    """G-1. The bound is an optimisation, so the answer may not depend on it.

    Without a session there is no grid to estimate from and the query stays unbounded, which
    makes the sessionless call the reference the bounded one has to reproduce exactly -- rows,
    values and order.
    """
    reference = _observation_rows(halted_source, rows=rows, session=None)
    with scan.ScanSession() as session:
        bounded = _observation_rows(halted_source, rows=rows, session=session)
    assert bounded == reference
    assert {str(row["instrument"]) for row in reference} == {"AAA", "BBB", "HALTED", "LATE"}


def test_a_bounded_rows_lookback_still_carries_the_halted_name(
    halted_source: SourceSpec, bound_every_source: None
) -> None:
    """The specific corruption the two-stage form exists to prevent.

    HALTED's newest close is what a run marks that holding at. A bound that dropped it would not
    fail; the run would simply value the book differently.
    """
    with scan.ScanSession() as session:
        bounded = _observation_rows(halted_source, rows=5, session=session)
    halted = [row for row in bounded if str(row["instrument"]) == "HALTED"]
    assert len(halted) == 5
    assert halted[-1]["available_at"] == _BOUND_SESSIONS[59]
    assert halted[-1]["close"] == Decimal("109.0000")


def test_the_instant_grid_is_read_once_per_source_for_the_whole_run(
    halted_source: SourceSpec, bound_every_source: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The estimate is only worth making if its input is not re-read per callback."""
    with scan.ScanSession() as session:
        grids = 0
        original = scan.ScanSession.instant_grid

        def counting(self, spec, available_at_field):  # type: ignore[no-untyped-def]
            nonlocal grids
            before = dict(self._grids)
            result = original(self, spec, available_at_field)
            if len(self._grids) != len(before):
                grids += 1
            return result

        monkeypatch.setattr(scan.ScanSession, "instant_grid", counting)
        for _ in range(8):
            _observation_rows(halted_source, rows=5, session=session)
        assert grids == 1


def test_a_small_source_is_never_probed_for_a_lower_bound(halted_source: SourceSpec) -> None:
    """The gate, not the estimate. An extra statement is a loss on a source read in one gulp."""
    with scan.ScanSession() as session:
        assert session.source_bytes(halted_source) < scan.ROWS_BOUND_MIN_BYTES
        with _counted_statements() as issued:
            _observation_rows(halted_source, rows=5, session=session)
        assert len(issued) == 1, "a gated-out source pays for the read and nothing else"
        assert session._grids == {}, "a gated-out source must not pay for a grid"
        assert session._bounds == {}, "and has no bound to prove"


# --------------------------------------------------------------------------------------
# 046: one round trip per declared input
# --------------------------------------------------------------------------------------

_LADDER = _BOUND_SESSIONS[380::4]
"""Evaluation times late enough for a `rows=5` bound to exist, spread far enough apart that the
grid position moves several instants between callbacks. LATE lists inside this range and STOPS
falls silent inside it."""


def test_a_declared_input_costs_one_statement_per_callback(
    halted_source: SourceSpec, bound_every_source: None
) -> None:
    """046 acceptance 1: two statements per declared input become one.

    The first callback pays for what the run then keeps -- the source's instant grid, and the
    proof that says which instruments the bound is not safe for. Every callback after it reads
    with a single statement, because the read carries the next callback's proof out with it
    instead of asking for it separately.
    """
    with scan.ScanSession() as session:
        counts = []
        for stamp in _LADDER:
            with _counted_statements() as issued:
                _observation_rows(halted_source, rows=5, session=session, evaluation_time=stamp)
            counts.append(len(issued))
        assert counts[0] == 3, "grid, proof, read"
        assert counts[1:] == [1] * (len(_LADDER) - 1)
        # One statement is also what a bound nobody can use costs, so say which one this was:
        # the proof exempts the two sparse names and bounds the other two.
        (kept,) = session._bounds.values()
        assert set(kept.unbounded) == {"HALTED", "LATE"}


@pytest.mark.parametrize("rows", [1, 5, 60])
def test_a_proof_that_outlives_its_callback_still_returns_the_unbounded_result(
    halted_source: SourceSpec, bound_every_source: None, rows: int
) -> None:
    """046 acceptance 2: a sparse name gets exactly what the unbounded query would have given.

    The proof is taken once and applied at later evaluation times, so this walks the ladder and
    compares every callback against the same read with no session -- the form that has no bound
    to be wrong about. Three names make it mean something: HALTED stopped publishing 340 sessions
    before the ladder begins, LATE lists partway through it, and STOPS falls silent inside it
    while a proof taken when it was dense is still being applied.
    """
    names = (*_BOUND_NAMES, "STOPS")
    seen: set[str] = set()
    with scan.ScanSession() as session:
        for stamp in _LADDER:
            bounded = _observation_rows(
                halted_source, rows=rows, session=session, evaluation_time=stamp, instruments=names
            )
            reference = _observation_rows(
                halted_source, rows=rows, session=None, evaluation_time=stamp, instruments=names
            )
            assert bounded == reference, f"the bound changed the answer at {stamp:%Y-%m-%d}"
            # The proof the read carries for the next callback is not part of the answer. Record
            # 119 took the normalization out of the read path, so nothing between here and
            # `ObservationBatch._trusted` would notice a column that leaked; and the shape test
            # in `tests/data/test_observation_batch_shape.py` builds its store without a session,
            # which means it never reaches the bounded form this could leak from.
            assert all(
                sorted(row) == ["available_at", "close", "instrument", "volume"] for row in bounded
            ), "a bounded read must return the declared fields and nothing else"
            seen.update(str(row["instrument"]) for row in bounded)
    assert seen == set(names), "a ladder that never reads the sparse names proves nothing"
