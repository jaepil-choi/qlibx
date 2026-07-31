"""A-share cash-equity adapter with an explicitly injected exchange calendar."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from echolon.markets.base import BaseMarketAdapter
from echolon.markets.interface import ContractSpec, SessionWindow


_SESSIONS = [
    SessionWindow("morning", dt.time(9, 30), dt.time(11, 30)),
    SessionWindow("afternoon", dt.time(13, 0), dt.time(15, 0)),
]


class EquityAdapter(BaseMarketAdapter):
    """Research adapter for long-only A-share cash equities; charges are RMB."""

    def __init__(
        self,
        symbol: str,
        trading_calendar_path: str | Path | None = None,
        *,
        commission_rate: float = 0.00025,
        stamp_duty_rate: float = 0.0005,
        transfer_fee_rate: float = 0.00001,
        min_commission: float = 5.0,
    ) -> None:
        super().__init__()
        if trading_calendar_path is None:
            raise ValueError("equity trading calendar path is required")
        path = Path(trading_calendar_path)
        if not path.is_file():
            raise FileNotFoundError(f"equity trading calendar not found: {path}")
        frame = pd.read_csv(path)
        if "date" not in frame.columns:
            raise ValueError("equity trading calendar missing date column")
        self._trading_dates = tuple(sorted(pd.to_datetime(frame["date"]).dt.date.unique()))
        if not self._trading_dates:
            raise ValueError("equity trading calendar is empty")
        self._symbol = symbol.lower()
        # Re-verify stamp duty before ANY live config; this rate has moved before.
        self.register_contract_spec(
            self._symbol,
            ContractSpec(
                symbol=self._symbol,
                multiplier=1.0,
                tick_size=0.01,
                margin_rate=1.0,
                commission=commission_rate,
                commission_type="percentage",
                currency="RMB",
                trading_unit="shares",
                min_order_size=100.0,
                stamp_duty_rate=stamp_duty_rate,
                transfer_fee_rate=transfer_fee_rate,
                min_commission=min_commission,
                long_only=True,
                t_plus_one=True,
            ),
        )

    @property
    def market_code(self) -> str:
        """Return the factory market identifier."""
        return "EQUITY"

    @property
    def market_name(self) -> str:
        """Return the human-readable market name."""
        return "A-Share Equity"

    @property
    def timezone(self) -> str:
        """Return the exchange IANA timezone."""
        return "Asia/Shanghai"

    @property
    def trading_sessions(self) -> list[SessionWindow]:
        """Return cash sessions in China Standard Time."""
        return list(_SESSIONS)

    @property
    def supports_overnight_positions(self) -> bool:
        """Return whether shares may remain held overnight."""
        return True

    @property
    def has_contract_expiry(self) -> bool:
        """Return False because cash equities do not expire."""
        return False

    @property
    def symbol(self) -> str:
        """Return the configured lowercase stock symbol."""
        return self._symbol

    def get_contract_spec(self, symbol: str) -> ContractSpec:
        """Return the RMB/share specification or raise KeyError."""
        try:
            return self._contract_specs[symbol.lower()]
        except KeyError as exc:
            raise KeyError(f"unknown equity symbol: {symbol}") from exc

    def get_main_contract(self, trading_date: dt.date) -> str:
        """Return the stock symbol; equities have no roll chain."""
        return self._symbol

    def should_rollover(self, contract: str, trading_date: dt.date, position_size: int) -> bool:
        """Return False because equities never roll."""
        return False

    def get_rollover_target(self, current_contract: str, trading_date: dt.date) -> None:
        """Return None because equities never roll."""
        return None

    def get_contract_expiry_date(self, contract: str) -> None:
        """Return None because equities do not expire."""
        return None

    def is_trading_day(self, check_date: dt.date) -> bool:
        """Return membership in the injected SSE/SZSE calendar."""
        return check_date in self._trading_dates

    def get_next_trading_day(self, from_date: dt.date) -> dt.date:
        """Return the next injected date or raise KeyError if unavailable."""
        for trading_date in self._trading_dates:
            if trading_date > from_date:
                return trading_date
        raise KeyError(f"next trading day unavailable after {from_date}")

    def get_previous_trading_day(self, from_date: dt.date) -> dt.date:
        """Return the prior injected date or raise KeyError if unavailable."""
        for trading_date in reversed(self._trading_dates):
            if trading_date < from_date:
                return trading_date
        raise KeyError(f"previous trading day unavailable before {from_date}")

    def get_session_close_time(self, check_date: dt.date) -> dt.datetime:
        """Return 15:00 CST on a trading day or raise KeyError."""
        if not self.is_trading_day(check_date):
            raise KeyError(f"not an equity trading day: {check_date}")
        return dt.datetime.combine(check_date, dt.time(15, 0))

    def calculate_commission(
        self,
        symbol: str,
        size: int,
        price: float,
        close_today: bool = False,
        side: str | None = None,
    ) -> float:
        """Return total order charges in RMB; side is required for equity duty accuracy."""
        return self.get_contract_spec(symbol).calculate_commission(
            price, size, close_today=close_today, side=side
        )

    def calculate_margin(self, symbol: str, size: int, price: float) -> float:
        """Return cash required in RMB for the equity position."""
        return self.get_contract_spec(symbol).calculate_margin(price, size)

    def get_price_precision(self, symbol: str) -> int:
        """Return two decimal places for RMB share prices."""
        self.get_contract_spec(symbol)
        return 2

    def get_size_precision(self, symbol: str) -> int:
        """Return zero decimal places for share quantities."""
        self.get_contract_spec(symbol)
        return 0
