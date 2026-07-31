"""SHFEApiDayExtractor requires source_path for trading calendar."""
from unittest.mock import MagicMock

import pytest

from echolon.data.extractors.shfe.api_day_extractor import SHFEApiDayExtractor


def test_missing_source_path_raises_with_clear_message():
    ex = SHFEApiDayExtractor(market="SHFE", asset="aluminum")
    with pytest.raises(ValueError) as exc:
        ex.generate_trading_calendar(source_path=None)
    assert "source_path" in str(exc.value)
    assert "shfe.com.cn" in str(exc.value).lower() or "derive" in str(exc.value).lower()


def test_empty_string_source_path_raises():
    ex = SHFEApiDayExtractor(market="SHFE", asset="aluminum")
    with pytest.raises(ValueError):
        ex.generate_trading_calendar(source_path="")


def test_valid_source_path_loads_and_optionally_saves(tmp_path):
    csv = tmp_path / "calendar.csv"
    csv.write_text("date,is_trading_day,night_market\n2026-01-02,True,True\n", encoding="utf-8")
    ex = SHFEApiDayExtractor(market="SHFE", asset="aluminum")
    out_dir = tmp_path / "deploy-slot"
    df = ex.generate_trading_calendar(source_path=str(csv), output_dir=str(out_dir))
    assert len(df) == 1
    assert (out_dir / "trading_calendar.csv").exists()


def test_no_hardcoded_quant_engine_path_reference():
    """The dead 'quant_engine/deploy/config' path must be removed."""
    from pathlib import Path
    src = Path(__import__("echolon.data.extractors.shfe.api_day_extractor", fromlist=["__file__"]).__file__).read_text(encoding="utf-8")
    assert "quant_engine" not in src, "dead hardcoded path still present"
    assert "deploy/config/trading_calendar.csv" not in src
