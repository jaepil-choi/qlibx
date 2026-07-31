"""SessionAvailabilityLoader must fail loudly when path/config is missing —
either CFG-003 if no kwarg was injected, or DAT-003 if the conventional file
under the supplied tree is missing."""
from pathlib import Path

import pytest

from echolon.errors import ConfigError, DataError


def test_loader_raises_cfg003_when_no_path_or_market_data_dir(tmp_path: Path):
    """With neither path= nor market_data_dir=, the loader must raise CFG-003.
    (No silent PathsConfig.from_env() fallback.)"""
    from echolon.data.loaders.session_availability_loader import SessionAvailabilityLoader

    with pytest.raises(ConfigError) as exc:
        SessionAvailabilityLoader(
            market="SHFE",
            instrument="aluminum",
            bar_size_minutes=15,
        )
    assert exc.value.code == "CFG-003"


def test_loader_with_explicit_path_override_warns_and_empty(tmp_path: Path):
    """When caller passes an explicit `path` that does not exist, the loader
    warns and returns with empty data — no raise (caller knows what they're doing)."""
    from echolon.data.loaders.session_availability_loader import SessionAvailabilityLoader

    loader = SessionAvailabilityLoader(
        market="SHFE",
        instrument="aluminum",
        bar_size_minutes=15,
        path=str(tmp_path / "explicit_missing.csv"),
    )
    assert loader._data == {}


def test_loader_with_explicit_market_data_dir_override_also_raises(tmp_path: Path):
    """When caller passes `market_data_dir` but the conventional
    {market}/{instrument}/session_availability.csv is missing under it,
    still raise DAT-003 — the caller's intent was to point at a real tree
    that should have the file."""
    from echolon.data.loaders.session_availability_loader import SessionAvailabilityLoader

    with pytest.raises(DataError) as exc:
        SessionAvailabilityLoader(
            market="SHFE",
            instrument="aluminum",
            bar_size_minutes=15,
            market_data_dir=tmp_path,  # empty tree under it
        )
    assert exc.value.code == "DAT-003"
