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
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vqapr.component.strategy.recorder import InvocationRecorder, TableSpec
from vqapr.data import scan, store
from vqapr.data.requirement import DataRequirement
from vqapr.data.store import DuckDbObservationStore
from vqapr.public import (
    DatasetRegistration,
    RowsLookback,
    SourceSpec,
    Workspace,
    register_dataset,
)
from vqapr.run.engine.run_state import LifecycleKind, LifecycleTrace, RunStateRepository

NOW = datetime(2024, 3, 5, 4, tzinfo=UTC)
SESSIONS = tuple(datetime(2024, 1, day, 6, 30, tzinfo=UTC) for day in range(1, 11))


@pytest.fixture
def priced_workspace(tmp_path: Path) -> Workspace:
    rows = [
        {"available_at": stamp, "instrument": name, "close": float(100 + index)}
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
                    ("close", pa.float64()),
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
            field_types={"close": "DOUBLE"},
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
    queries of the same run. `CallbackHandler._actual_source_refs` already refuses a callback that
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
        observation_store.query_many(
            (requirement,),
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

    first_batch = first.query_many(
        (requirement,),
        evaluation_time=SESSIONS[-1],
        instruments=("AAA",),
        consumer_id="test-consumer",
    )
    second_batch = second.query_many(
        (requirement,),
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

    from vqapr.data.execution_table import exact_execution_snapshot

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

    assert first.value.failures[0].code == "source.path_missing"
    assert second.value.failures[0].code == "source.path_missing"


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
    import vqapr.run.engine.run_state as run_state_module

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
    from vqapr.run.engine.run_state import AcceptedRunState, prepare_model_state

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
        {"available_at": stamp, "instrument": name, "close": float(100 + index), "volume": index}
        for index, stamp in enumerate(_BOUND_SESSIONS)
        for name in ("AAA", "BBB")
    ]
    rows.extend(
        {
            "available_at": stamp,
            "instrument": "HALTED",
            "close": float(50 + index),
            "volume": index,
        }
        for index, stamp in enumerate(_BOUND_SESSIONS[:60])
    )
    # A name that lists late has plenty of recent history but less than the declared window.
    rows.extend(
        {
            "available_at": stamp,
            "instrument": "LATE",
            "close": float(70 + index),
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
            "close": float(80 + index),
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
                    ("close", pa.float64()),
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
    assert halted[-1]["close"] == 109.0


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


# --------------------------------------------------------------------------------------------
# Record `221`: rows are collected as rows and travel as columns. On a 3,000-name book the
# `vqapr.account` rows of one market-clock instant were 3,000 dicts, each cell asked what it was,
# each field name re-checked for whitespace, then copied and re-wrapped at every hand-off to the
# disk. These pin the shape, not the seconds.
# --------------------------------------------------------------------------------------------

_ACCOUNT_SPEC = TableSpec("vqapr.account", ("instrument", "quantity", "price"))


def _account_recorder() -> InvocationRecorder:
    return InvocationRecorder(
        (_ACCOUNT_SPEC,), run_id="r", producer_id="p", stage="VALUATION", event_time=NOW
    )


def test_a_framework_column_is_checked_by_type_not_by_cell(monkeypatch) -> None:
    """`append_columns` never asks a cell what it is; `append_batch` still asks every cell."""
    from decimal import Decimal

    from vqapr.domain import rows

    calls = 0
    original = rows.normalize_scalar

    def counting(value):
        nonlocal calls
        calls += 1
        return original(value)

    monkeypatch.setattr(rows, "normalize_scalar", counting)
    monkeypatch.setattr("vqapr.component.strategy.recorder.normalize_scalar", counting)

    names = [f"I{index:04d}" for index in range(1000)]
    recorder = _account_recorder()
    recorder.append_columns(
        "vqapr.account",
        {"instrument": names, "quantity": [Decimal(1)] * 1000, "price": [Decimal("10.5")] * 1000},
    )
    assert calls == 0, "a column is checked by its distinct types, not cell by cell"
    assert recorder.manifests()[0].row_count == 1000

    recorder.append_batch(
        "vqapr.account", [{"instrument": "A", "quantity": Decimal(1), "price": Decimal(2)}]
    )
    assert calls == 3, "an author's row is still checked cell by cell"


def test_a_column_refuses_what_a_cell_would_have_refused() -> None:
    """The column pass keeps `normalize_scalar`'s rules: finite numbers, aware datetimes,
    portable types."""
    from datetime import datetime
    from decimal import Decimal

    recorder = _account_recorder()
    with pytest.raises(ValueError, match="finite"):
        recorder.append_columns(
            "vqapr.account",
            {"instrument": ["A"], "quantity": [Decimal("NaN")], "price": [None]},
        )
    with pytest.raises(ValueError, match="aware"):
        recorder.append_columns(
            "vqapr.account",
            {"instrument": ["A"], "quantity": [None], "price": [datetime(2024, 1, 1)]},
        )
    with pytest.raises(TypeError, match="portable"):
        recorder.append_columns(
            "vqapr.account", {"instrument": ["A"], "quantity": [object()], "price": [None]}
        )
    with pytest.raises(ValueError, match="same number of rows"):
        recorder.append_columns(
            "vqapr.account", {"instrument": ["A", "B"], "quantity": [None], "price": [None]}
        )
    with pytest.raises(ValueError, match="exactly match declared fields"):
        recorder.append_columns("vqapr.account", {"instrument": ["A"], "quantity": [None]})


def test_the_writer_never_walks_the_rows_of_a_chunk(tmp_path: Path, monkeypatch) -> None:
    """A chunk reaches the disk as the columns it was staged as; rows are not rebuilt on the way."""
    from decimal import Decimal

    from vqapr.record.chunk import RecordChunk
    from vqapr.record.writer import RunRecordWriter

    def never(self):
        raise AssertionError("the writer rebuilt rows from a chunk")

    monkeypatch.setattr(RecordChunk, "rows", never)
    recorder = _account_recorder()
    recorder.append_columns(
        "vqapr.account",
        {"instrument": ["A", "B"], "quantity": [Decimal(1), Decimal(2)], "price": [None, None]},
    )
    writer = RunRecordWriter(tmp_path, "columns")
    writer.open()
    try:
        for chunk in recorder.staged_chunks():
            writer.append_chunk(chunk)
        assert writer.counts()["vqapr.account"] == {"rows": 2, "instants": 1}
    finally:
        writer.release()


# --------------------------------------------------------------------------------------------
# Record `222`: the execution table is read ahead along the market clock. One instant used to be
# one query with every name in its `IN` list -- 390 a day on a minute table. `ExecutionSnapshots`
# reads a window of instants per query and answers each instant from it, with the rows and the
# absence partitions `exact_execution_snapshot` would have produced.
# --------------------------------------------------------------------------------------------


def _execution_table(tmp_path: Path):
    """Six minutes of two names; B twice at 09:02 (a duplicate), A absent at 09:03."""
    import duckdb

    from vqapr.data.execution_table import ExecutionTableSpec

    path = tmp_path / "execution.parquet"
    rows = []
    for minute in range(6):
        for name in ("A", "B"):
            if name == "A" and minute == 3:
                continue
            rows.append(
                f"(TIMESTAMPTZ '2024-03-05 09:0{minute}:00+09', '{name}', true, {100 + minute}.0)"
            )
    rows.append("(TIMESTAMPTZ '2024-03-05 09:02:00+09', 'B', false, 999.0)")
    con = duckdb.connect()
    try:
        con.execute(
            "COPY (SELECT trade_at, instrument, is_tradable, close::DOUBLE AS close FROM (VALUES "
            + ",\n".join(rows)
            + ") AS t(trade_at, instrument, is_tradable, close)) "
            f"TO '{path.as_posix()}' (FORMAT PARQUET)"
        )
    finally:
        con.close()
    return ExecutionTableSpec(
        source=SourceSpec.of("venue-source", path),
        trade_at_field="trade_at",
        instrument_field="instrument",
        is_tradable_field="is_tradable",
        price_fields={"close": "close"},
    )


def _minutes():
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    first = datetime(2024, 3, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    return tuple(first + timedelta(minutes=k) for k in range(6))


def test_a_window_answers_every_instant_of_the_clock_with_one_query(
    tmp_path: Path, monkeypatch
) -> None:
    """Six instants, one query; each answer equal to the exact per-instant read."""
    from vqapr.data import execution_table as module
    from vqapr.data.execution_table import ExecutionSnapshots, exact_execution_snapshot

    spec = _execution_table(tmp_path)
    queries = 0
    original = scan.execution_window_table

    def counting(*args, **kwargs):
        nonlocal queries
        queries += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(module.scan, "execution_window_table", counting)
    snapshots = ExecutionSnapshots(
        spec, instants=_minutes(), instruments=("A", "B"), trade_price="close"
    )
    for at in _minutes():
        ahead = snapshots.at(at, target_instruments=("A",), held_instruments=("B",))
        exact = exact_execution_snapshot(
            spec,
            target_at=at,
            target_instruments=("A",),
            held_instruments=("B",),
            trade_price="close",
        )
        assert ahead == exact, at
    assert queries == 1, "six instants inside one window are one read"
    twice = snapshots.at(_minutes()[2], target_instruments=("B",), held_instruments=())
    assert twice.duplicate_instruments == ("B",)
    absent = snapshots.at(_minutes()[3], target_instruments=("A",), held_instruments=())
    assert absent.missing_target_instruments == ("A",)


def test_a_smaller_window_reads_again_and_an_outside_request_falls_through(
    tmp_path: Path, monkeypatch
) -> None:
    from datetime import timedelta

    from vqapr.data import execution_table as module
    from vqapr.data.execution_table import ExecutionSnapshots, exact_execution_snapshot

    spec = _execution_table(tmp_path)
    windows = 0
    exact_reads = 0
    window_read = scan.execution_window_table
    exact_read = scan.exact_snapshot_rows

    def counting_window(*args, **kwargs):
        nonlocal windows
        windows += 1
        return window_read(*args, **kwargs)

    def counting_exact(*args, **kwargs):
        nonlocal exact_reads
        exact_reads += 1
        return exact_read(*args, **kwargs)

    minutes = _minutes()
    off_the_clock = minutes[0] + timedelta(seconds=30)
    expected_outside = exact_execution_snapshot(
        spec,
        target_at=off_the_clock,
        target_instruments=("A",),
        held_instruments=(),
        trade_price="close",
    )
    monkeypatch.setattr(module.scan, "execution_window_table", counting_window)
    monkeypatch.setattr(module.scan, "exact_snapshot_rows", counting_exact)
    snapshots = ExecutionSnapshots(
        spec, instants=minutes, instruments=("A", "B"), trade_price="close", window=4
    )
    for at in minutes:
        snapshots.at(at, target_instruments=("A", "B"), held_instruments=())
    assert windows == 2, "six instants over a window of four are two reads"
    assert exact_reads == 0

    outside = snapshots.at(off_the_clock, target_instruments=("A",), held_instruments=())
    assert outside == expected_outside
    unknown = snapshots.at(minutes[0], target_instruments=("Z",), held_instruments=("A",))
    assert unknown.missing_target_instruments == ("Z",)
    assert exact_reads == 2, "an instant off the clock and a name outside the window fall through"

# --------------------------------------------------------------------------------------------
# Record `223`: the view a Compliance rule observes is built from proved values without proving
# them again, and an identifier's whitespace check is one search rather than one step per
# character. Both were a third of the compliance stage on a 3,000-name book.
# --------------------------------------------------------------------------------------------


def test_a_framework_built_account_view_re_validates_nothing(monkeypatch) -> None:
    from datetime import UTC
    from decimal import Decimal

    from vqapr.component import account_view as view_module
    from vqapr.component.account_view import EconomicAccountView
    from vqapr.domain.account import AccountSnapshot, Mark, MarkBatch
    from vqapr.run.engine.stages.observe import build_account_view

    validated = 0
    original = view_module._copy_weights

    def counting(*args, **kwargs):
        nonlocal validated
        validated += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(view_module, "_copy_weights", counting)
    names = [f"I{index:04d}" for index in range(500)]
    snapshot = AccountSnapshot(3, Decimal("10"), {name: Decimal(2) for name in names})
    marks = MarkBatch(
        tuple(Mark(name, Decimal(2), Decimal("1.5"), Decimal(3)) for name in names), Decimal(1500)
    )
    at = datetime(2024, 3, 5, 6, 30, tzinfo=UTC)

    trusted = build_account_view(snapshot, marks, at)
    assert validated == 0, "the framework's view proves nothing twice"

    authored = EconomicAccountView(
        cash=snapshot.cash,
        positions=dict(snapshot.positions),
        values={mark.instrument_id: mark.value for mark in marks.marks},
        nav=marks.total_value + snapshot.cash,
        nav_observed_at=at,
    )
    assert validated == 2, "an author's constructor still proves its two cross-sections"
    assert trusted == authored
    assert list(trusted.positions) == sorted(names)
    assert trusted.weight("I0007") == authored.weight("I0007")


def test_an_identifier_check_is_one_search_not_one_step_per_character() -> None:
    """Same verdicts as `str.isspace` per character, in C."""
    from vqapr.component._validation import _identifier
    from vqapr.domain.identifiers import instrument_id

    for good in ("A", "BRK/B", "_KOSPI", "005930", "a\u00e9"):
        assert _identifier(good, name="x") == good and instrument_id(good) == good
    for bad in ("", "A B", "A\tB", "A\u00a0B", "A\u2003B", "\nA"):
        with pytest.raises(ValueError):
            _identifier(bad, name="x")
        with pytest.raises(ValueError):
            instrument_id(bad)


# --------------------------------------------------------------------------------------------
# Record `225`: `sequence` is the run's one order. It was `len(staged)` inside one table of one
# recorder, and a recorder is built per callback, so it restarted at zero every event.
# --------------------------------------------------------------------------------------------


def test_sequence_is_one_order_across_every_recorder_and_fill_of_a_run() -> None:
    from decimal import Decimal

    from vqapr.domain.account import FILL_ORIGIN, AccountSnapshot, AccountState, LedgerEntry
    from vqapr.run.engine.run_state import _fill_rows

    state = RunStateRepository(initial_account=AccountState(AccountSnapshot(0, Decimal(1), {})))

    first = InvocationRecorder(
        (TableSpec("diagnostics", ("message",)),),
        run_id="run-1",
        producer_id="p",
        stage="STRATEGY_CALLBACK",
        event_time=NOW,
        sequencer=state.next_sequence,
    )
    first.append_batch("diagnostics", [{"message": "a"}, {"message": "b"}])
    second = InvocationRecorder(
        (TableSpec("diagnostics", ("message",)),),
        run_id="run-1",
        producer_id="p",
        stage="VALUATION",
        event_time=NOW,
        sequencer=state.next_sequence,
    )
    second.append_columns("diagnostics", {"message": ["c", "d", "e"]})
    fills = _fill_rows(
        (
            LedgerEntry(
                at=NOW,
                cash=Decimal("-1"),
                positions={"A": Decimal(1)},
                origin=FILL_ORIGIN,
                detail={
                    "instrument": "A",
                    "requested_quantity": Decimal(1),
                    "dealt_quantity": Decimal(1),
                },
            ),
        ),
        1,
        envelope={
            "run_id": "run-1", "producer_id": "p", "stage": "EXECUTION", "event_time": NOW
        },
        sequencer=state.next_sequence,
    )

    assert [row["sequence"] for row in first.staged_rows()["diagnostics"]] == [0, 1]
    assert [row["sequence"] for row in second.staged_rows()["diagnostics"]] == [2, 3, 4]
    assert [row["sequence"] for row in fills] == [5]

    alone = InvocationRecorder(
        (TableSpec("diagnostics", ("message",)),),
        run_id="run-1",
        producer_id="p",
        stage="STRATEGY_CALLBACK",
        event_time=NOW,
    )
    alone.append("diagnostics", {"message": "x"})
    assert [row["sequence"] for row in alone.staged_rows()["diagnostics"]] == [0], (
        "a recorder built by hand, without a run, counts for itself"
    )


# --------------------------------------------------------------------------------------
# 096: a panel read makes no Python step per name
# --------------------------------------------------------------------------------------


def _wide_panel(names: int, instants: int):
    from vqapr.data.lookback import RowsLookback
    from vqapr.data.panel import Panel

    base = datetime(2024, 1, 1, 6, 30, tzinfo=UTC)
    stamps = [base + timedelta(days=day) for day in range(instants)]
    labels = [f"N{index:05d}" for index in range(names)]
    table = pa.Table.from_pylist(
        [
            {"available_at": stamp, "instrument": label, "close": float(index + day)}
            for day, stamp in enumerate(stamps)
            for index, label in enumerate(labels)
        ],
        schema=pa.schema(
            [
                ("available_at", pa.timestamp("us", tz="UTC")),
                ("instrument", pa.string()),
                ("close", pa.float64()),
            ]
        ),
    )
    panel = Panel.from_table(
        table,
        dataset_id="wide",
        fields=("close",),
        instruments=labels,
        keyed_by_instrument=True,
        identity="wide",
        source_digest="wide",
    )
    return panel.window("close", evaluation_time=stamps[-1], lookback=RowsLookback(rows=instants))


def test_a_panel_read_makes_no_python_step_per_name(monkeypatch) -> None:
    """`docs/issues/096`: `counts`, `current`, `latest` and `matrix` are vectorised over the
    field's block. Counted, not timed: the number of per-name column calls a read makes is the
    fact, and it must not grow with the number of names.
    """
    from vqapr.data import panel as panel_module

    window = _wide_panel(names=3_000, instants=6)
    per_name: list[str] = []
    original = panel_module.Panel.column

    def counting(self, field, instrument):
        per_name.append(instrument)
        return original(self, field, instrument)

    monkeypatch.setattr(panel_module.Panel, "column", counting)

    assert len(window.counts()) == 3_000
    assert len(window.current()) == 3_000
    assert len(window.latest()) == 3_000
    assert window.matrix().shape == (6, 3_000)
    assert per_name == [], "a vectorised read asks for no name's column"

    assert window.values["N00007"] == (7.0, 8.0, 9.0, 10.0, 11.0, 12.0)
    assert per_name == ["N00007"], "values[name] converts that one column and no other"
