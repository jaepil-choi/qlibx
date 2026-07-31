"""Q51 — TradingDataRecord.pathway_id field.

Per qorka decisions_log.md 2026-05-12 "Pre-Wave-1A plan-composition
readiness pass". The new field carries per-pathway identifier for
paradigms that decompose signal generation into named pathways (TRS
uses P1..P8). Default None for non-pathway paradigms; consumed by
qorka A9 §4.11 live-replay diagnostic for per-pathway hit-rate drift.
"""
from __future__ import annotations

from echolon.live.io.data_logger import TradingDataRecord


def _baseline(**overrides) -> TradingDataRecord:
    base = dict(
        timestamp="2026-05-13T09:30:00",
        symbol="al2605.SF",
        current_price=24600.0,
        daily_open=24500.0,
        daily_high=24700.0,
        daily_low=24400.0,
        volume=1234,
    )
    base.update(overrides)
    return TradingDataRecord(**base)


def test_pathway_id_defaults_to_none():
    """Non-pathway paradigms (TSMOM, carry, etc.) should produce records
    with pathway_id=None — no behavior change."""
    r = _baseline()
    assert r.pathway_id is None


def test_pathway_id_accepts_string():
    """TRS pathway routing labels each emission with a pathway ID."""
    r = _baseline(pathway_id="P5_range_meanrev")
    assert r.pathway_id == "P5_range_meanrev"


def test_pathway_id_included_in_serialization():
    """`to_dict()` round-trips include pathway_id so CSV outputs preserve
    it for downstream A9 live-replay consumption."""
    r = _baseline(pathway_id="P3_trending_up_highvol")
    d = r.to_dict()
    assert "pathway_id" in d
    assert d["pathway_id"] == "P3_trending_up_highvol"


def test_pathway_id_omitted_serializes_as_none():
    """Records without pathway_id serialize the field as None (CSV
    writers can substitute empty string downstream)."""
    r = _baseline()
    d = r.to_dict()
    assert "pathway_id" in d
    assert d["pathway_id"] is None
