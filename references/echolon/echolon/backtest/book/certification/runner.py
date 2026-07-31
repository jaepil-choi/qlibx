"""Loader and executor for the immutable futures certification fixture."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from importlib.resources import files
from pathlib import Path

from echolon.portfolio import BookState, RebalanceRecord, TargetBook

from ..engine import DailyBookBacktester
from ..models import BookBacktestConfig, BookLifecycleContract, BookResult
from .models import CertificationBundle, CertificationFixture, CertificationOracle
from .panel import CertificationPanel


V1_FIXTURE_SHA256 = "8758e7d277930987b9dc37583b2792eaef31ff9f8fef27b025e2ff8736229e2c"
V1_ORACLE_SHA256 = "0e9d44c507ec0446ee960ad492e6c1e01e16fbccd1e1cc747485742bc7d1a2a9"
V1_BUNDLE_SHA256 = "34f25ad2d2e35f5a6b78ace89d76e1926bb64432190e973543facc6aed7fee57"


def _require_v1_code_pins(bundle: CertificationBundle) -> CertificationBundle:
    """Reject a self-consistent substitute for the committed v1 artifacts."""
    if bundle.fixture.sha256 != V1_FIXTURE_SHA256:
        raise ValueError("v1 certification fixture does not match its code pin")
    if bundle.oracle.sha256 != V1_ORACLE_SHA256:
        raise ValueError("v1 certification oracle does not match its code pin")
    if certification_bundle_sha256(bundle) != V1_BUNDLE_SHA256:
        raise ValueError("v1 certification bundle does not match its code pin")
    return bundle


class _FixtureStrategy:
    def __init__(self, targets_by_date: dict[dt.date, dict[str, float]]) -> None:
        self._targets_by_date = targets_by_date
        self.calls: list[dt.date] = []

    def rebalance(self, view, book: BookState):
        del book
        self.calls.append(view.date)
        return (
            TargetBook(
                date=view.date,
                targets=dict(self._targets_by_date.get(view.date, {})),
            ),
            RebalanceRecord(date=view.date, instruments={}),
        )


def load_certification_bundle(version: str = "v1") -> CertificationBundle:
    """Load and cryptographically validate one packaged fixture version."""
    if version != "v1":
        raise ValueError(f"unsupported futures certification fixture version: {version}")
    root = files("echolon.backtest.book.certification").joinpath("data", version)
    fixture = CertificationFixture.model_validate_json(
        root.joinpath("fixture.json").read_text(encoding="utf-8")
    )
    oracle = CertificationOracle.model_validate_json(
        root.joinpath("oracle.json").read_text(encoding="utf-8")
    )
    return _require_v1_code_pins(
        CertificationBundle(fixture=fixture, oracle=oracle)
    )


def certification_bundle_sha256(bundle: CertificationBundle | None = None) -> str:
    """Return a stable combined identity for the separately sealed artifacts."""
    loaded = bundle or load_certification_bundle()
    encoded = json.dumps(
        {
            "schema": "futures-book-certification-bundle/v1",
            "fixture_sha256": loaded.fixture.sha256,
            "oracle_sha256": loaded.oracle.sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_certification_scenario(
    name: str,
    *,
    output_dir: Path,
    bundle: CertificationBundle | None = None,
) -> BookResult:
    """Execute one frozen scenario through the production daily book engine."""
    loaded = (
        load_certification_bundle()
        if bundle is None
        else _require_v1_code_pins(bundle)
    )
    matches = [row for row in loaded.fixture.scenarios if row.name == name]
    if len(matches) != 1:
        raise KeyError(f"unknown certification fixture scenario: {name}")
    scenario = matches[0]
    panel = CertificationPanel(scenario)
    strategy = _FixtureStrategy(
        {
            row.date: {target.instrument: target.lots for target in row.targets}
            for row in scenario.targets_by_date
        }
    )
    config = BookBacktestConfig(
        start=scenario.calendar[0],
        end=scenario.calendar[-1],
        initial_equity_rmb=scenario.initial_equity_rmb,
        panel_snapshot=scenario.panel_snapshot,
        panel_manifest_sha256=scenario.panel_manifest_sha256,
        execution_contract_schedule=scenario.execution_contract_schedule,
        lifecycle_contract=BookLifecycleContract(
            terminal_open_date=scenario.calendar[-1]
        ),
    )
    return DailyBookBacktester(
        output_dir=Path(output_dir),
        slippage_bps=scenario.slippage_bps,
        rebalance_weekday=None,
    ).run(strategy, panel, config)
