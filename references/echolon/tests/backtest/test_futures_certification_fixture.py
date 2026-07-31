"""Release-gate falsifiers for the packaged futures certification fixture."""
from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from echolon.backtest.book import (
    certification_bundle_sha256,
    commission_rmb,
    load_certification_bundle,
    run_certification_scenario,
    verify_full_result_manifest_sha256,
)
from echolon.backtest.book.certification import (
    V1_BUNDLE_SHA256,
    V1_FIXTURE_SHA256,
    V1_ORACLE_SHA256,
    canonical_artifact_sha256,
)
from echolon.backtest.book.certification.models import (
    CertificationBundle,
    CertificationFixture,
    CertificationOracle,
)
from echolon.backtest.book.models import BookBacktestConfig
from echolon.portfolio import round_toward_zero_lot


def test_packaged_v1_artifacts_are_hash_locked_and_cross_bound() -> None:
    bundle = load_certification_bundle()

    assert bundle.fixture.schema == "futures-book-certification-fixture/v1"
    assert bundle.oracle.schema == "futures-book-certification-oracle/v1"
    assert bundle.oracle.fixture_sha256 == bundle.fixture.sha256
    assert canonical_artifact_sha256(bundle.fixture) == bundle.fixture.sha256
    assert canonical_artifact_sha256(bundle.oracle) == bundle.oracle.sha256
    assert bundle.fixture.sha256 == V1_FIXTURE_SHA256
    assert bundle.oracle.sha256 == V1_ORACLE_SHA256
    assert certification_bundle_sha256(bundle) == V1_BUNDLE_SHA256

    tampered = bundle.fixture.model_dump(mode="json")
    tampered["scenarios"][0]["initial_equity_rmb"] += 1.0
    with pytest.raises(ValidationError, match="fixture hash mismatch"):
        CertificationFixture.model_validate(tampered)

    oracle_tampered = bundle.oracle.model_dump(mode="json")
    oracle_tampered["scenarios"][0]["ending_cash_rmb"] += 1.0
    with pytest.raises(ValidationError, match="oracle hash mismatch"):
        CertificationOracle.model_validate(oracle_tampered)


def test_fully_rehashed_substitute_bundle_still_fails_code_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = load_certification_bundle()
    fixture_payload = bundle.fixture.model_dump(mode="json")
    fixture_payload["scenarios"][0]["initial_equity_rmb"] += 1.0
    fixture_payload["sha256"] = canonical_artifact_sha256(fixture_payload)
    substituted_fixture = CertificationFixture.model_validate(fixture_payload)

    oracle_payload = bundle.oracle.model_dump(mode="json")
    oracle_payload["fixture_sha256"] = substituted_fixture.sha256
    oracle_payload["sha256"] = canonical_artifact_sha256(oracle_payload)
    substituted_oracle = CertificationOracle.model_validate(oracle_payload)
    data_dir = tmp_path / "data" / "v1"
    data_dir.mkdir(parents=True)
    (data_dir / "fixture.json").write_text(
        json.dumps(substituted_fixture.model_dump(mode="json")), encoding="utf-8"
    )
    (data_dir / "oracle.json").write_text(
        json.dumps(substituted_oracle.model_dump(mode="json")), encoding="utf-8"
    )
    monkeypatch.setattr(
        "echolon.backtest.book.certification.runner.files", lambda package: tmp_path
    )

    with pytest.raises(ValueError, match="does not match its code pin"):
        load_certification_bundle()

    substituted_bundle = CertificationBundle(
        fixture=substituted_fixture,
        oracle=substituted_oracle,
    )
    with pytest.raises(ValueError, match="does not match its code pin"):
        run_certification_scenario(
            "normal_scheduled",
            output_dir=tmp_path / "substitute-run",
            bundle=substituted_bundle,
        )
    assert not (tmp_path / "substitute-run").exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload["scenarios"][0]["instruments"][0][
                "main_bars"
            ].append(
                copy.deepcopy(
                    payload["scenarios"][0]["instruments"][0]["main_bars"][-1]
                )
            ),
            "unique, ordered dates",
        ),
        (
            lambda payload: payload["scenarios"][0]["instruments"][0].update(
                {
                    "exact_bars": list(
                        reversed(
                            payload["scenarios"][0]["instruments"][0]["exact_bars"]
                        )
                    )
                }
            ),
            "deterministically ordered",
        ),
        (
            lambda payload: payload["scenarios"][0]["targets_by_date"].append(
                copy.deepcopy(payload["scenarios"][0]["targets_by_date"][-1])
            ),
            "unique and ordered",
        ),
    ],
)
def test_fixture_rejects_ambiguous_ordering(mutation, message: str) -> None:
    payload = load_certification_bundle().fixture.model_dump(mode="json")
    mutation(payload)
    with pytest.raises(ValidationError, match=message):
        CertificationFixture.model_validate(payload)


@pytest.mark.parametrize(
    "scenario_name",
    ["normal_scheduled", "delayed_liquidation", "blocked_terminal"],
)
def test_scenarios_match_frozen_hand_oracles(
    tmp_path: Path, scenario_name: str
) -> None:
    bundle = load_certification_bundle()
    oracle = next(row for row in bundle.oracle.scenarios if row.name == scenario_name)

    result = run_certification_scenario(
        scenario_name,
        output_dir=tmp_path / scenario_name,
        bundle=bundle,
    )

    assert result.outcome.status == oracle.status
    assert result.outcome.ending_cash_rmb == oracle.ending_cash_rmb
    assert result.outcome.ending_equity_rmb == oracle.ending_equity_rmb
    assert result.outcome.ending_margin_used_rmb == oracle.ending_margin_used_rmb
    assert result.summary.fees_total_rmb == oracle.fees_total_rmb
    assert result.summary.slippage_total_rmb == oracle.slippage_total_rmb
    assert sum(row.realized_pnl_rmb for row in result.trades) == oracle.realized_pnl_rmb
    assert result.summary.determinism_hash == oracle.determinism_hash
    assert (
        result.summary.full_result_manifest_sha256
        == oracle.full_result_manifest_sha256
    )
    assert verify_full_result_manifest_sha256(result)
    assert (
        BookBacktestConfig.model_validate(
            result.runtime_manifest.config
        ).panel_manifest_sha256
        == next(
            row.panel_manifest_sha256
            for row in bundle.fixture.scenarios
            if row.name == scenario_name
        )
    )
    assert (tmp_path / scenario_name / "book_result.json").is_file()
    assert [
        (
            row.date,
            row.instrument,
            row.contract,
            row.side,
            row.lots,
            row.fill_price,
            row.commission_rmb,
            row.realized_pnl_rmb,
            row.position_after,
        )
        for row in result.trades
    ] == [
        (
            row.date,
            row.instrument,
            row.contract,
            row.side,
            row.lots,
            row.fill_price,
            row.commission_rmb,
            row.realized_pnl_rmb,
            row.position_after,
        )
        for row in oracle.trades
    ]
    event_types = {row["type"] for row in result.events}
    assert set(oracle.required_event_types) <= event_types


def test_normal_scenario_defers_missing_exact_roll_and_missing_product_session(
    tmp_path: Path,
) -> None:
    result = run_certification_scenario(
        "normal_scheduled", output_dir=tmp_path / "normal"
    )
    deferred = [row for row in result.events if row["type"] == "roll_deferred"]

    assert {
        (row["detail"]["instrument"], row["detail"]["reason"])
        for row in deferred
    } == {
        ("per_contract_asset", "missing_exact_scheduled_contract_bar"),
        ("percentage_asset", "scheduled_contract_non_executable"),
    }
    assert [(row.contract, row.date) for row in result.trades[2:4]] == [
        ("C1", dt.date(2025, 1, 7)),
        ("C2", dt.date(2025, 1, 7)),
    ]


def test_liquidation_waits_and_closes_only_the_exact_held_contract(
    tmp_path: Path,
) -> None:
    result = run_certification_scenario(
        "delayed_liquidation", output_dir=tmp_path / "liquidation"
    )

    assert [row.contract for row in result.trades] == ["A1", "A1"]
    deferred = next(
        row for row in result.events if row["type"] == "liquidation_close_deferred"
    )
    assert deferred["detail"]["held_contract"] == "A1"
    assert deferred["detail"]["reason"] == "missing_exact_held_contract_bar"
    assert result.outcome.liquidation_completion_date > result.outcome.liquidation_trigger_date


def test_blocked_terminal_retains_replayable_position(tmp_path: Path) -> None:
    result = run_certification_scenario(
        "blocked_terminal", output_dir=tmp_path / "blocked"
    )

    assert result.outcome.status == "INVALID_INCOMPLETE"
    assert result.outcome.ending_positions[0].contract == "A1"
    assert result.outcome.ending_positions[0].lots == 1.0
    assert result.outcome.ending_pending_intents == ()


def test_public_fee_primitive_matches_regular_and_close_today_oracles(
    tmp_path: Path,
) -> None:
    bundle = load_certification_bundle()
    assert bundle.oracle.close_today_coverage == "public_primitive_only"

    for case in bundle.fixture.fee_primitive_cases:
        assert commission_rmb(
            case.meta,
            case.price,
            case.lots_abs,
            close_today=case.close_today,
            side="SELL",
        ) == case.expected_commission_rmb

    assert not any(
        trade.close_today
        for scenario in bundle.fixture.scenarios
        for trade in run_certification_scenario(
            scenario.name,
            output_dir=tmp_path / scenario.name,
            bundle=bundle,
        ).trades
    )


def test_public_whole_lot_primitive_matches_boundaries() -> None:
    for case in load_certification_bundle().fixture.lot_primitive_cases:
        assert round_toward_zero_lot(case.value, case.min_order_size) == case.expected


def test_scenario_replay_is_deterministic(tmp_path: Path) -> None:
    first = run_certification_scenario("normal_scheduled", output_dir=tmp_path / "a")
    second = run_certification_scenario("normal_scheduled", output_dir=tmp_path / "b")
    assert first.summary.determinism_hash == second.summary.determinism_hash
    assert (
        first.summary.full_result_manifest_sha256
        == second.summary.full_result_manifest_sha256
    )
