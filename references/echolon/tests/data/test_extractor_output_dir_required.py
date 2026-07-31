"""Extractors raise when neither output_dir nor a default-paths override is supplied."""
import pytest

from echolon.data.extractors.shfe.file_day_extractor import SHFEFileDayExtractor
from echolon.data.extractors.shfe.api_minute_extractor import SHFEApiMinuteExtractor
from echolon.data.extractors.shfe.api_day_extractor import SHFEApiDayExtractor


def test_file_day_extractor_requires_output_dir(tmp_path):
    # SHFEFileDayExtractor now requires raw_data_dir at construction (no
    # PathsConfig.from_env() fallback). Build with an explicit raw root so
    # extract_raw can then surface its own missing-output_dir error.
    ex = SHFEFileDayExtractor(market="SHFE", asset="aluminum", raw_data_dir=tmp_path)
    with pytest.raises(ValueError, match="output_dir"):
        ex.extract_raw()   # no output_dir


def test_api_minute_extractor_requires_output_dir(tmp_path):
    ex = SHFEApiMinuteExtractor(market="SHFE", asset="aluminum", raw_data_dir=tmp_path)
    with pytest.raises(ValueError, match="output_dir"):
        ex.extract_raw()


def test_api_day_extractor_requires_output_dir():
    ex = SHFEApiDayExtractor(market="SHFE", asset="aluminum")
    with pytest.raises(ValueError, match="output_dir"):
        ex.extract_raw()


def test_no_project_root_write_in_extractor_source():
    """Static assertion — grep the sources for PROJECT_ROOT / 'data' writes."""
    import importlib.util
    from pathlib import Path
    # Locate the extractors directory via the base module's file
    spec = importlib.util.find_spec("echolon.data.extractors.base")
    base = Path(spec.origin).parent  # echolon/data/extractors/
    for py in base.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        # Allow imports of PROJECT_ROOT (for reading config), forbid joining into 'data' dir
        assert 'PROJECT_ROOT / "data"' not in src and "PROJECT_ROOT, 'data'" not in src, \
            f"install-dir write in {py}"
