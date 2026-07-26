from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from _acceptance_contract import MarketScenario, StrategyRunIdentity


RUN_COLUMNS = {
    "strategy_registry": {
        "strategy_id",
        "strategy_name",
        "definition_hash",
        "code_version",
        "created_at",
    },
    "strategy_runs": {
        "run_id",
        "strategy_id",
        "start_date",
        "end_date",
        "status",
        "input_fingerprint",
        "result_hash",
        "schema_version",
        "run_fingerprint",
    },
    "signals": {
        "run_id",
        "strategy_id",
        "start_date",
        "end_date",
        "trade_date",
        "signal_name",
        "instrument_id",
        "signal_value",
        "max_observation_date",
    },
    "portfolio_targets": {
        "run_id",
        "strategy_id",
        "start_date",
        "end_date",
        "trade_date",
        "instrument_id",
        "target_weight",
    },
    "orders": {
        "run_id",
        "strategy_id",
        "start_date",
        "end_date",
        "trade_date",
        "order_id",
        "instrument_id",
        "requested_quantity",
        "raw_target_quantity",
        "target_quantity",
        "lot_size",
        "lot_rounding_quantity",
    },
    "fills": {
        "run_id",
        "strategy_id",
        "start_date",
        "end_date",
        "trade_date",
        "fill_id",
        "order_id",
        "instrument_id",
        "filled_quantity",
        "trade_price",
        "trade_cost",
        "reason",
        "reason_code",
        "blocked_by",
        "quantity_after_tradability",
        "quantity_after_volume",
        "quantity_after_position",
        "quantity_after_cash",
        "quantity_after_lot",
        "asset_class",
        "execution_policy",
        "effective_cost_rate",
        "short_enabled",
    },
    "positions": {
        "run_id",
        "strategy_id",
        "start_date",
        "end_date",
        "trade_date",
        "instrument_id",
        "held_quantity",
        "market_value",
    },
    "account_daily": {
        "run_id",
        "strategy_id",
        "start_date",
        "end_date",
        "trade_date",
        "cash",
        "nav",
        "portfolio_return",
        "trade_cost",
        "turnover",
    },
    "research_evaluations": {
        "run_id",
        "strategy_id",
        "start_date",
        "end_date",
        "trade_date",
        "candidate_id",
        "score",
        "selected",
        "max_observation_date",
    },
    "artifact_manifest": {
        "run_id",
        "strategy_id",
        "start_date",
        "end_date",
        "table_name",
        "schema_version",
        "relative_path",
        "row_count",
        "content_hash",
    },
}


PRIMARY_KEYS = {
    "strategy_registry": ["strategy_id"],
    "strategy_runs": ["run_id"],
    "signals": [
        "run_id",
        "trade_date",
        "signal_name",
        "instrument_id",
    ],
    "portfolio_targets": [
        "run_id",
        "trade_date",
        "instrument_id",
    ],
    "orders": [
        "run_id",
        "trade_date",
        "order_id",
    ],
    "fills": [
        "run_id",
        "trade_date",
        "fill_id",
    ],
    "positions": [
        "run_id",
        "trade_date",
        "instrument_id",
    ],
    "account_daily": ["run_id", "trade_date"],
    "research_evaluations": [
        "run_id",
        "trade_date",
        "candidate_id",
    ],
    "artifact_manifest": ["run_id", "table_name"],
}


def _completed_run(
    backend_harness,
    *,
    target: float | list[float] = 0.6,
    signal_target: float | list[float] | None = None,
):
    dates = pd.bdate_range("2024-01-02", periods=2)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
    )
    weights = pd.DataFrame(target, index=dates, columns=["A"])
    signal_value = target if signal_target is None else signal_target
    signals = {
        "peer_momentum": pd.DataFrame(signal_value, index=dates, columns=["A"])
    }
    result = backend_harness.run_weight_targets(
        scenario, weights, signals=signals
    )
    identity = StrategyRunIdentity(
        run_id="00000000-0000-0000-0000-000000000001",
        strategy_id="peer_momentum.fixture.v1",
        strategy_name="peer_momentum_fixture",
        start_date=dates[0],
        end_date=dates[-1],
        definition_hash="definition-v1",
        code_version="fixture-code-v1",
        input_fingerprint="fixture-input-v1",
        reuse_scope="portable_signal",
        run_fingerprint="fixture-semantic-input-v1",
    )
    return identity, result


def test_completed_run_is_a_keyed_parquet_database(backend_harness, tmp_path) -> None:
    identity, result = _completed_run(backend_harness)
    store = backend_harness.artifact_store(tmp_path / "alpha-db")

    manifest = store.write_run(identity, result)

    assert manifest["status"] == "complete"
    assert manifest["run_id"] == identity.run_id
    assert manifest["files"]
    assert all(Path(path).suffix == ".parquet" for path in manifest["files"])
    for table_name, required_columns in RUN_COLUMNS.items():
        table = store.load_table(identity, table_name)
        assert required_columns <= set(table.columns)
        assert not table.duplicated(PRIMARY_KEYS[table_name]).any()
    assert pd.api.types.is_integer_dtype(
        store.load_table(identity, "orders")["requested_quantity"]
    )
    assert pd.api.types.is_integer_dtype(
        store.load_table(identity, "fills")["filled_quantity"]
    )
    assert pd.api.types.is_integer_dtype(
        store.load_table(identity, "positions")["held_quantity"]
    )


def test_artifacts_feed_reporting_and_ensemble_without_strategy_rerun(
    backend_harness, tmp_path
) -> None:
    identity, result = _completed_run(backend_harness)
    store = backend_harness.artifact_store(tmp_path / "alpha-db")
    store.write_run(identity, result)
    invocations_before = backend_harness.strategy_invocation_count()

    reporting = store.load_reporting_bundle(identity)
    reusable = store.load_ensemble_input(identity, "signals/peer_momentum")

    assert {"signals", "portfolio_targets", "orders", "fills", "positions", "account_daily"} <= set(reporting)
    assert not reusable.empty
    assert backend_harness.strategy_invocation_count() == invocations_before


def test_write_is_idempotent_but_same_run_key_cannot_change_content(
    backend_harness, tmp_path
) -> None:
    identity, result = _completed_run(backend_harness)
    store = backend_harness.artifact_store(tmp_path / "alpha-db")
    first = store.write_run(identity, result)
    second = store.write_run(identity, result)
    _, changed_result = _completed_run(backend_harness, target=0.3)

    assert first["result_hash"] == second["result_hash"]
    with pytest.raises(ValueError, match="content|hash|identity"):
        store.write_run(identity, changed_result)


def test_result_hash_distinguishes_targets_with_identical_execution(
    backend_harness, tmp_path
) -> None:
    identity, result = _completed_run(
        backend_harness, target=[0.6, 0.6], signal_target=0.6
    )
    _, changed_result = _completed_run(
        backend_harness, target=[0.6, 0.61], signal_target=0.6
    )
    pd.testing.assert_frame_equal(result.orders(), changed_result.orders())
    pd.testing.assert_frame_equal(result.fills(), changed_result.fills())
    pd.testing.assert_frame_equal(
        result.account_daily(), changed_result.account_daily()
    )
    assert result.backend_evidence()["result_hash"] != changed_result.backend_evidence()[
        "result_hash"
    ]

    store = backend_harness.artifact_store(tmp_path / "alpha-db")
    store.write_run(identity, result)
    with pytest.raises(ValueError, match="content|hash|identity"):
        store.write_run(identity, changed_result)


def test_same_strategy_and_dates_can_publish_distinct_run_ids(
    backend_harness, tmp_path
) -> None:
    first_identity, first_result = _completed_run(backend_harness, target=0.6)
    _, second_result = _completed_run(backend_harness, target=0.3)
    second_identity = replace(
        first_identity,
        run_id="00000000-0000-0000-0000-000000000002",
        input_fingerprint="fixture-input-v2",
        run_fingerprint="fixture-semantic-input-v2",
    )
    store = backend_harness.artifact_store(tmp_path / "alpha-db")

    store.write_run(first_identity, first_result)
    store.write_run(second_identity, second_result)

    first_run = store.load_table(first_identity, "strategy_runs").iloc[0]
    second_run = store.load_table(second_identity, "strategy_runs").iloc[0]
    assert first_run["run_id"] != second_run["run_id"]
    assert first_run["result_hash"] != second_run["result_hash"]
    assert first_run["strategy_id"] == second_run["strategy_id"]
    assert first_run["start_date"] == second_run["start_date"]
    assert first_run["end_date"] == second_run["end_date"]


def test_run_id_cannot_be_reused_with_different_provenance(
    backend_harness, tmp_path
) -> None:
    identity, result = _completed_run(backend_harness)
    changed_identity = replace(
        identity,
        input_fingerprint="different-input",
        run_fingerprint="different-semantic-input",
    )
    store = backend_harness.artifact_store(tmp_path / "alpha-db")
    store.write_run(identity, result)

    with pytest.raises(ValueError, match="run_id.*different provenance"):
        store.write_run(changed_identity, result)


def test_run_id_must_be_non_empty(backend_harness, tmp_path) -> None:
    identity, result = _completed_run(backend_harness)
    store = backend_harness.artifact_store(tmp_path / "alpha-db")

    with pytest.raises(ValueError, match="run_id.*non-empty"):
        store.write_run(replace(identity, run_id="  "), result)


def test_exact_run_target_is_not_silently_claimed_portable(
    backend_harness, tmp_path
) -> None:
    identity, result = _completed_run(backend_harness)
    exact_identity = StrategyRunIdentity(
        **{**identity.__dict__, "reuse_scope": "exact_run"}
    )
    store = backend_harness.artifact_store(tmp_path / "alpha-db")
    store.write_run(exact_identity, result)

    with pytest.raises(ValueError, match="reuse|portable|exact_run"):
        store.load_ensemble_input(exact_identity, "portfolio_targets")


def test_reader_cannot_promote_stored_reuse_scope_with_forged_identity(
    backend_harness, tmp_path
) -> None:
    identity, result = _completed_run(backend_harness)
    store = backend_harness.artifact_store(tmp_path / "alpha-db")
    store.write_run(identity, result)
    forged_identity = replace(identity, reuse_scope="portable_target")

    with pytest.raises(ValueError, match="different provenance.*reuse_scope"):
        store.load_ensemble_input(forged_identity, "portfolio_targets")


def test_corrupt_parquet_cannot_be_read_as_a_complete_run(
    backend_harness, tmp_path
) -> None:
    identity, result = _completed_run(backend_harness)
    store = backend_harness.artifact_store(tmp_path / "alpha-db")
    manifest = store.write_run(identity, result)
    signal_path = Path(manifest["tables"]["signals"]["file_path"])
    signal_path.write_bytes(b"not-a-valid-parquet-file")

    with pytest.raises((ValueError, OSError), match="hash|corrupt|parquet|manifest"):
        store.load_table(identity, "signals")
