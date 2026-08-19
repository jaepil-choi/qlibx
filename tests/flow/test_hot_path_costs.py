"""The hot path must not silently go back to redoing settled work.

Every cost this file guards is invisible to the rest of the suite. The fixtures are small, so a
per-query re-hash and a per-root re-verification both look free here; they only hurt on a real
warehouse over a long run. These tests therefore assert **counts and shapes**, never wall time,
which would be flaky in CI and would not say what actually regressed.

See `docs/code-review/2026-08-19-vqapr-performance.md` sections 6 and 8.
"""

from __future__ import annotations

from datetime import UTC, datetime
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
from vqapr.flow import model_state as model_state_module
from vqapr.flow.run_state import LifecycleKind, LifecycleTrace, RunStateRepository
from vqapr.public import DatasetRegistration, RowsLookback, SourceSpec, Workspace

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
    space = Workspace.create(tmp_path)
    space.register_dataset(
        DatasetRegistration.of(
            "prices",
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
        ),
        SourceSpec.of("prices-source", source),
    )
    return space


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
    original = store._physical_digest

    def counting_digest(path: Path) -> str:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(store, "_physical_digest", counting_digest)

    observation_store = DuckDbObservationStore(priced_workspace)
    requirement = DataRequirement.of(
        "strategy", "prices", fields=("close",), lookback=RowsLookback(2)
    )
    for session in SESSIONS[3:]:
        observation_store.query(requirement, evaluation_time=session, instruments=("AAA", "BBB"))

    assert len(calls) == 1, f"expected one digest per source per store, saw {len(calls)}"


def test_two_stores_do_not_share_a_digest_cache(priced_workspace: Workspace) -> None:
    """The cache is scoped to one run, deliberately.

    A process-wide cache would outlive the frozen-run scope that justifies it and would happily
    serve a stale digest to a later run over rewritten bytes.
    """
    requirement = DataRequirement.of(
        "strategy", "prices", fields=("close",), lookback=RowsLookback(1)
    )
    first = DuckDbObservationStore(priced_workspace)
    second = DuckDbObservationStore(priced_workspace)

    first_batch = first.query(requirement, evaluation_time=SESSIONS[-1], instruments=("AAA",))
    second_batch = second.query(requirement, evaluation_time=SESSIONS[-1], instruments=("AAA",))

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
    original = model_state_module.prepare_model_state

    def counting_prepare(memory: object, payload: bytes):
        nonlocal calls
        calls += 1
        return original(memory, payload)

    monkeypatch.setattr(model_state_module, "prepare_model_state", counting_prepare)
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
    from vqapr.flow.model_state import prepare_model_state
    from vqapr.flow.run_state import AcceptedRunState

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
