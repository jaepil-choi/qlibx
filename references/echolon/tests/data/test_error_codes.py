"""Data-layer errors use catalog codes DAT-002/003/004."""
import json
from pathlib import Path

import pytest

from echolon.errors import DataError


def test_corrupt_state_raises_dat_002(tmp_path: Path):
    """_load_state_file must raise DAT-002 on corrupt JSON, not silently return {}."""
    state_file = tmp_path / "strategy_state.json"
    state_file.write_text("{ this is not valid json", encoding="utf-8")

    from echolon.live.slot.trading_slot import _load_state_file

    with pytest.raises(DataError) as exc:
        _load_state_file(str(state_file))

    assert exc.value.code == "DAT-002"
    assert "strategy_state.json" in str(exc.value) or str(state_file) in str(exc.value)


def test_nonexistent_state_file_returns_empty(tmp_path: Path):
    """Cold start (file does NOT exist) is still valid; returns {} without raising."""
    from echolon.live.slot.trading_slot import _load_state_file

    result = _load_state_file(str(tmp_path / "does_not_exist.json"))
    assert result == {}


def test_missing_main_contract_raises_dat_003(tmp_path: Path):
    """_load_main_contract_data raises DAT-003 when the main_contract.csv is absent.

    main_contract.csv now lives in market_data_dir alongside trading_calendar.csv
    (was raw_data_dir; migrated in 2026-Q2)."""
    from echolon.markets.shfe.contract_rules import _load_main_contract_data

    with pytest.raises(DataError) as exc:
        _load_main_contract_data("al", market_data_dir=tmp_path)

    assert exc.value.code == "DAT-003"
    assert "al" in str(exc.value)


def test_empty_calendar_generation_raises_dat_004(tmp_path: Path):
    """CalendarGenerator.generate raises DAT-004 when zero valid dates remain."""
    import pandas as pd
    from echolon.data.transformers.calendar_generator import CalendarGenerator

    gen = CalendarGenerator(output_dir=str(tmp_path))
    empty_df = pd.DataFrame(columns=["date", "open", "close"])

    with pytest.raises(DataError) as exc:
        gen.generate(df=empty_df, start_date="2024-01-01", end_date="2024-12-31")

    assert exc.value.code == "DAT-004"
