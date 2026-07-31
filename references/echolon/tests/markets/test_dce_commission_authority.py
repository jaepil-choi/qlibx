"""Falsifier: DCE eb/a/b/cs commission == the ratified exchange-standard authority.

Unlike the multiplier/tick specs, these four DCE commissions are pinned to the
exchange-standard per-lot rate (flat 平今) ratified 2026-07-20 — the runtime spec
source must match the authority artifact (instrument-consistency law). akshare's
``futures_fees_info`` carries a systematic +0.01 元/手 broker-negotiated offset that
is deliberately excluded.

Two layers:
  1. an always-on value pin (runs with no external dependency);
  2. a cross-artifact consistency check against the ratified authority JSON in the
     artifact store, whose location the caller injects (see ``tests/conftest.py``).
     Layer 2 skips when no store is injected and FAILS when an injected store does
     not hold the artifact.
"""

from __future__ import annotations

import json
from pathlib import Path

from echolon.config.markets.dce.instruments import INSTRUMENTS as DCE

# Exchange-standard per-lot rate (元/手), flat: open = 平昨 = 平今.
RATIFIED = {"eb": 1.00, "a": 2.00, "b": 1.00, "cs": 1.50}


def test_dce_commissions_are_exchange_standard() -> None:
    for code, expected in RATIFIED.items():
        spec = DCE[code]
        assert spec.commission == expected, (code, spec.commission, expected)
        assert spec.commission_type == "per_contract"


def test_dce_commissions_match_ratified_authority_artifact(
    dce_commission_authority_v2: Path,
) -> None:
    """Echolon canonical commission == the v2 authority ``records`` for the 4 products."""
    records = json.loads(dce_commission_authority_v2.read_text())["records"]
    for code in RATIFIED:
        assert DCE[code].commission == records[code]["commission"], code
