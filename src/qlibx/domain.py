"""Dependency-neutral domain data shared across calculation and state layers."""

from dataclasses import dataclass
from enum import StrEnum


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    instrument_id: str
    side: Side
    requested_quantity: float
    dealt_quantity: float
    price: float
    trade_value: float
    total_cost: float
    cost_rule_id: str
    schedule_version: str
