"""Extractor capabilities declaration tests.

Task 7 implementation: Replace hasattr() duck-typing with explicit
capabilities: ClassVar[Set[str]] per extractor.
"""
import pytest


def test_all_extractors_declare_capabilities():
    """All extractors must declare a capabilities set."""
    from echolon.data.extractors.shfe.file_day_extractor import SHFEFileDayExtractor
    from echolon.data.extractors.shfe.api_minute_extractor import SHFEApiMinuteExtractor
    from echolon.data.extractors.shfe.api_day_extractor import SHFEApiDayExtractor
    from echolon.data.extractors.binance.perpetual_extractor import BinancePerpetualExtractor

    for cls in (
        SHFEFileDayExtractor,
        SHFEApiMinuteExtractor,
        SHFEApiDayExtractor,
        BinancePerpetualExtractor,
    ):
        assert hasattr(cls, "capabilities"), f"{cls.__name__} missing capabilities attribute"
        assert isinstance(cls.capabilities, set), f"{cls.__name__}.capabilities must be a set"
        assert "batch" in cls.capabilities, f"{cls.__name__} must declare 'batch' capability"


def test_shfe_file_day_extractor_capabilities():
    """SHFEFileDayExtractor: {batch, calendar_generate}."""
    from echolon.data.extractors.shfe.file_day_extractor import SHFEFileDayExtractor

    assert SHFEFileDayExtractor.capabilities == {"batch", "calendar_generate"}


def test_shfe_api_minute_extractor_capabilities():
    """SHFEApiMinuteExtractor: {batch, calendar_generate, main_contract}."""
    from echolon.data.extractors.shfe.api_minute_extractor import SHFEApiMinuteExtractor

    assert SHFEApiMinuteExtractor.capabilities == {
        "batch",
        "calendar_generate",
        "main_contract",
    }


def test_shfe_api_day_extractor_capabilities():
    """SHFEApiDayExtractor: {batch, incremental, calendar_load, main_contract}."""
    from echolon.data.extractors.shfe.api_day_extractor import SHFEApiDayExtractor

    assert SHFEApiDayExtractor.capabilities == {
        "batch",
        "incremental",
        "calendar_load",
        "main_contract",
    }


def test_binance_perpetual_extractor_capabilities():
    """BinancePerpetualExtractor: {batch, calendar_generate}."""
    from echolon.data.extractors.binance.perpetual_extractor import BinancePerpetualExtractor

    assert BinancePerpetualExtractor.capabilities == {"batch", "calendar_generate"}


def test_api_day_extractor_has_incremental():
    """Only the api day extractor should have 'incremental' capability."""
    from echolon.data.extractors.shfe.api_day_extractor import SHFEApiDayExtractor
    from echolon.data.extractors.shfe.file_day_extractor import SHFEFileDayExtractor
    from echolon.data.extractors.shfe.api_minute_extractor import SHFEApiMinuteExtractor

    assert "incremental" in SHFEApiDayExtractor.capabilities
    assert "incremental" not in SHFEFileDayExtractor.capabilities
    assert "incremental" not in SHFEApiMinuteExtractor.capabilities


def test_api_extractors_have_main_contract():
    """API extractors (minute, day) should have 'main_contract' capability."""
    from echolon.data.extractors.shfe.api_minute_extractor import SHFEApiMinuteExtractor
    from echolon.data.extractors.shfe.api_day_extractor import SHFEApiDayExtractor
    from echolon.data.extractors.shfe.file_day_extractor import SHFEFileDayExtractor

    assert "main_contract" in SHFEApiMinuteExtractor.capabilities
    assert "main_contract" in SHFEApiDayExtractor.capabilities
    assert "main_contract" not in SHFEFileDayExtractor.capabilities


def test_calendar_load_vs_generate():
    """API day extractor has 'calendar_load'; others have 'calendar_generate'."""
    from echolon.data.extractors.shfe.file_day_extractor import SHFEFileDayExtractor
    from echolon.data.extractors.shfe.api_minute_extractor import SHFEApiMinuteExtractor
    from echolon.data.extractors.shfe.api_day_extractor import SHFEApiDayExtractor
    from echolon.data.extractors.binance.perpetual_extractor import BinancePerpetualExtractor

    # API day extractor loads a pre-built calendar
    assert "calendar_load" in SHFEApiDayExtractor.capabilities
    assert "calendar_generate" not in SHFEApiDayExtractor.capabilities

    # Others generate from data
    assert "calendar_generate" in SHFEFileDayExtractor.capabilities
    assert "calendar_load" not in SHFEFileDayExtractor.capabilities

    assert "calendar_generate" in SHFEApiMinuteExtractor.capabilities
    assert "calendar_load" not in SHFEApiMinuteExtractor.capabilities

    assert "calendar_generate" in BinancePerpetualExtractor.capabilities
    assert "calendar_load" not in BinancePerpetualExtractor.capabilities
