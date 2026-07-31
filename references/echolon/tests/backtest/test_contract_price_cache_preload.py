from datetime import date

import pandas as pd

from echolon.backtest.engine.hooks.contract_aware.broker import (
    clear_contract_price_cache,
    get_cached_contract_price,
    preload_contract_prices,
)


def _write_contract(root, contract: str, close: float) -> None:
    by_contract = root / "by_contract"
    by_contract.mkdir(parents=True)
    pd.DataFrame(
        [{"trading_date": "20260105", "close": close}]
    ).to_csv(by_contract / f"{contract}_indicators.csv", index=False)


def test_contract_price_cache_preload_clears_previous_directory(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_contract(first, "aa2601", 101.0)
    _write_contract(second, "bb2601", 202.0)

    clear_contract_price_cache()
    assert preload_contract_prices(str(first)) == 1
    assert get_cached_contract_price("aa2601", date(2026, 1, 5)) == 101.0

    assert preload_contract_prices(str(second)) == 1

    assert get_cached_contract_price("aa2601", date(2026, 1, 5)) is None
    assert get_cached_contract_price("bb2601", date(2026, 1, 5)) == 202.0
    clear_contract_price_cache()
