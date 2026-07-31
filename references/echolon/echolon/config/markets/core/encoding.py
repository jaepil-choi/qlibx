"""
Session Phase Encoding Utilities.

Backtrader data feed lines must be numeric, so we encode session phases.
This module provides the interface for encoding/decoding session phases.

Each market implements its own encoding in its phases module.
This module provides the dispatch mechanism based on market code.
"""

from typing import Dict, Callable, Optional


# Registry of market-specific encoders/decoders
_encoders: Dict[str, Callable[[str], int]] = {}
_decoders: Dict[str, Callable[[int], str]] = {}


def register_encoder(market: str, encoder: Callable[[str], int]) -> None:
 """Register a market-specific phase encoder."""
 _encoders[market.upper()] = encoder


def register_decoder(market: str, decoder: Callable[[int], str]) -> None:
 """Register a market-specific phase decoder."""
 _decoders[market.upper()] = decoder

