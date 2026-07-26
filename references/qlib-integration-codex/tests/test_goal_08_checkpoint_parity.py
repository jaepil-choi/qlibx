from __future__ import annotations

import json

import pandas as pd
import pytest

from _acceptance_contract import MarketScenario


def _assert_frame_equal(left: pd.DataFrame, right: pd.DataFrame) -> None:
    pd.testing.assert_frame_equal(
        left.reset_index(drop=True),
        right.reset_index(drop=True),
        check_like=True,
    )


def test_checkpoint_resume_matches_uninterrupted_observable_results(
    backend_harness, tmp_path
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=6)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(
            {"A": [100.0, 102.0, 101.0, 103.0, 99.0, 104.0]}, index=dates
        ),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
        cost_policy={
            "stock": {"buy_rate": 0.001, "sell_rate": 0.001, "sell_tax": 0.0}
        },
    )

    full, resumed = backend_harness.resume_equivalence_probe(
        scenario, tmp_path / "checkpoint"
    )

    _assert_frame_equal(full.signals(), resumed.signals())
    _assert_frame_equal(full.orders(), resumed.orders())
    _assert_frame_equal(full.fills(), resumed.fills())
    _assert_frame_equal(full.positions(), resumed.positions())
    _assert_frame_equal(full.account_daily(), resumed.account_daily())
    _assert_frame_equal(
        full.research_evaluations(), resumed.research_evaluations()
    )
    assert full.backend_evidence()["result_hash"] == resumed.backend_evidence()[
        "result_hash"
    ]
    assert full.backend_evidence()["qlib_accumulated_info"] == resumed.backend_evidence()[
        "qlib_accumulated_info"
    ]


def test_checkpoint_account_state_must_reconcile_before_resume(
    backend_harness, tmp_path
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=4)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(
            {"A": [100.0, 101.0, 102.0, 103.0]}, index=dates
        ),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
    )
    checkpoint = tmp_path / "corrupt-account-checkpoint"
    backend_harness.resume_equivalence_probe(scenario, checkpoint)
    state_path = checkpoint / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["nav"] = float(state["nav"]) + 1.0
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="reconciliation.*tolerance"):
        backend_harness.resume_from_checkpoint(scenario, checkpoint)


def test_malformed_checkpoint_fails_fast(backend_harness, tmp_path) -> None:
    dates = pd.bdate_range("2024-01-02", periods=2)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
    )
    malformed = tmp_path / "malformed-checkpoint.bin"
    malformed.write_bytes(b"invalid-checkpoint")

    with pytest.raises((ValueError, OSError), match="checkpoint|schema|version"):
        backend_harness.resume_from_checkpoint(scenario, malformed)
