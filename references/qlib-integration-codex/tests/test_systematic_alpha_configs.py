from __future__ import annotations

from pathlib import Path

import pytest

from qlib_extended.research import (
    AlphaDefinition,
    DataCatalog,
    load_alpha_definitions,
)


ROOT = Path(__file__).resolve().parents[1]


def _catalog() -> DataCatalog:
    return DataCatalog.from_directory(ROOT / "configs" / "data")


def test_all_alpha_yamls_resolve_only_logical_dataset_keys() -> None:
    definitions = load_alpha_definitions(
        ROOT / "configs" / "alphas",
        data_catalog=_catalog(),
    )

    quarterly = definitions["financial.statement_and_dividend.quarterly_shadow"]
    annual = definitions["financial.statement.annual_252d_deprecated"]
    assert quarterly.track == "financial_shadow"
    assert quarterly.rebalance_days == 63
    assert set(quarterly.inputs.values()).issubset(_catalog().datasets)
    assert annual.track == "legacy"
    assert annual.rebalance_days == 252


def test_financial_trusted_track_is_rejected(tmp_path: Path) -> None:
    path = _write_alpha(tmp_path, track="trusted", rebalance_days=63)

    with pytest.raises(ValueError, match="cannot use the trusted track"):
        AlphaDefinition.from_yaml(path, data_catalog=_catalog())


def test_financial_shadow_over_63_days_is_rejected(tmp_path: Path) -> None:
    path = _write_alpha(tmp_path, track="financial_shadow", rebalance_days=64)

    with pytest.raises(ValueError, match="must not exceed 63"):
        AlphaDefinition.from_yaml(path, data_catalog=_catalog())


def test_unknown_dataset_key_fails_fast(tmp_path: Path) -> None:
    path = _write_alpha(
        tmp_path,
        track="financial_shadow",
        rebalance_days=63,
        dataset="guessed_financial_table",
    )

    with pytest.raises(KeyError, match="Missing dataset"):
        AlphaDefinition.from_yaml(path, data_catalog=_catalog())


def _write_alpha(
    root: Path,
    *,
    track: str,
    rebalance_days: int,
    dataset: str = "financial_statement_items",
) -> Path:
    path = root / "alpha.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "key: financial.test",
                "family: financial",
                f"track: {track}",
                "hypothesis: test hypothesis",
                "inputs:",
                f"  statement: {dataset}",
                "signal:",
                "  implementation: test_signal",
                "execution:",
                "  order_calendar_key: quarterly",
                "  lag_days: 1",
                f"  rebalance_days: {rebalance_days}",
                f"  max_holding_days: {rebalance_days}",
                "neutralization:",
                "  method: market_demean",
                "search:",
                "  fixed: true",
            ]
        ),
        encoding="utf-8",
    )
    return path
