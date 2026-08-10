"""Incremental project configuration frozen into complete specs (PRD 7.10.1)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from qlibx import (
    CostRule,
    DailyAccountSeed,
    DailyMarketBinding,
    KrxExchangeConfig,
    QlibxProject,
    Side,
    StockInstrument,
)


def stock(instrument_id: str, *, lot_size: int = 1) -> StockInstrument:
    return StockInstrument(
        instrument_id=instrument_id,
        exchange_id="XKRX",
        currency="KRW",
        lot_size=lot_size,
    )


def venue(schedule_version: str = "config-v1") -> KrxExchangeConfig:
    return KrxExchangeConfig(
        schedule_version=schedule_version,
        cost_rules=tuple(
            CostRule(
                rule_id=f"stock-{side.value.lower()}",
                product_type="stock",
                side=side,
                effective_from=datetime(2020, 1, 1, tzinfo=UTC),
                rate=0,
                minimum_cost=0,
            )
            for side in Side
        ),
    )


def at(day: int) -> datetime:
    return datetime(2024, 1, day, 6, 0, tzinfo=UTC)


def build_spec(project: QlibxProject, run_id: str = "run-1"):
    return project.daily_spec(
        run_id=run_id,
        strategy_fingerprint="strategy-v1",
        account=DailyAccountSeed(
            account_id="account-1",
            base_currency="KRW",
            initial_cash=10_000,
        ),
        market=DailyMarketBinding(market_dataset_id="market"),
        decision_times=(at(2),),
        session_closes=(at(2), at(3)),
    )


def opened(tmp_path: Path) -> QlibxProject:
    root = tmp_path / "project"
    QlibxProject.init(root, apply=True)
    return QlibxProject.open(root)


def test_accumulated_environment_is_frozen_into_a_complete_spec(tmp_path: Path) -> None:
    project = opened(tmp_path)
    project.add_instrument(stock("A000002"))
    project.add_instrument(stock("A000001"))
    project.set_exchange(venue())

    spec = build_spec(project)

    # The spec carries the environment by value, so it replays without this project instance.
    assert tuple(item.instrument_id for item in spec.instruments) == ("A000001", "A000002")
    assert spec.exchange == venue()


def test_later_configuration_cannot_change_an_existing_spec(tmp_path: Path) -> None:
    project = opened(tmp_path)
    project.add_instrument(stock("A000001"))
    project.set_exchange(venue())
    first = build_spec(project, run_id="run-1")
    first_fingerprint = first.frozen_config_fingerprint()

    project.add_instrument(stock("A000002"))
    project.set_exchange(venue("config-v2"))

    assert tuple(item.instrument_id for item in first.instruments) == ("A000001",)
    assert first.frozen_config_fingerprint() == first_fingerprint

    second = build_spec(project, run_id="run-2")
    assert tuple(item.instrument_id for item in second.instruments) == ("A000001", "A000002")
    # The environment is economic configuration, so a changed one must change run identity.
    assert second.frozen_config_fingerprint() != first_fingerprint


def test_conflicting_instrument_declaration_fails_instead_of_shadowing(tmp_path: Path) -> None:
    project = opened(tmp_path)
    project.add_instrument(stock("A000001", lot_size=1))
    project.add_instrument(stock("A000001", lot_size=1))  # identical re-declaration is a no-op

    with pytest.raises(ValueError, match="already configured differently"):
        project.add_instrument(stock("A000001", lot_size=10))

    assert project.configured_instruments == (stock("A000001", lot_size=1),)


def test_spec_requires_a_declared_environment(tmp_path: Path) -> None:
    project = opened(tmp_path)

    with pytest.raises(ValueError, match="add_instrument"):
        build_spec(project)

    project.add_instrument(stock("A000001"))
    with pytest.raises(ValueError, match="set_exchange"):
        build_spec(project)
