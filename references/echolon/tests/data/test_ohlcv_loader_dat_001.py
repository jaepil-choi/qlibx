"""ohlcv_loader raises DAT-001 (not bare FileNotFoundError) when the file is missing."""
import pytest

from echolon.errors import DataError


def test_load_ohlcv_missing_file_raises_dat_001(tmp_path):
    from echolon.data.loaders.ohlcv_loader import load_ohlcv

    with pytest.raises(DataError) as exc:
        load_ohlcv(market="SHFE", asset="aluminum", market_data_dir=tmp_path)
    assert exc.value.code == "DAT-001"
    # Error message should point at the missing path
    assert "aluminum" in str(exc.value) or "sort_by_date.csv" in str(exc.value)


def test_load_contract_ohlcv_missing_file_returns_none(tmp_path):
    """Contract-level loads still return None for missing contracts (intentional)."""
    from echolon.data.loaders.ohlcv_loader import load_contract_ohlcv

    result = load_contract_ohlcv(
        market="SHFE",
        asset="aluminum",
        contract="al9999",
        market_data_dir=tmp_path,
    )
    assert result is None
