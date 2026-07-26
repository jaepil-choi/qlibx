from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from kwam_enhanced_index.config import ProjectConfig
from kwam_enhanced_index.data.loader import ConfigDrivenDataLoader
from kwam_enhanced_index.data.matrix import (
    build_benchmark_weight,
    pivot_long_to_matrix,
)
from kwam_enhanced_index.data.preprocessing import dataguide_wide_to_tidy
from kwam_enhanced_index.universe.masks import build_universe_mask


# 역할: 실제 project catalog를 Qlib-native strategy와 Exchange가 소비할 축으로 고정합니다.
# 책임:
# - research stock axis와 physical ETF axis를 명시적으로 분리합니다.
# - Qlib strategy의 observation/trade date 조회를 제공합니다.
# - 누락 schema와 유효하지 않은 execution 입력은 실행 전에 실패시킵니다.


@dataclass(frozen=True)
class QlibPeerMomentumData:
    universe_mask: pd.DataFrame
    returns: pd.DataFrame
    peer_groups: pd.DataFrame
    benchmark_weight: pd.DataFrame
    execution_price: pd.DataFrame
    position_unit_factor: pd.DataFrame
    volume: pd.DataFrame
    buyable: pd.DataFrame
    sellable: pd.DataFrame
    suspended: pd.DataFrame
    asset_class: pd.Series
    etf_ticker: str

    @classmethod
    def from_project_config(
        cls,
        config: ProjectConfig,
        *,
        etf_ticker: str,
        peer_group_dataset: str = "industry_code",
    ) -> "QlibPeerMomentumData":
        loader = ConfigDrivenDataLoader.from_project_config(config)
        panel = loader.load_table("base_universe_inputs")
        universe = build_universe_mask(panel).sort_index().sort_index(axis=1)
        index_weight = loader.load_matrix("index_weight").sort_index().sort_index(axis=1)
        stock_columns = index_weight.columns
        universe = universe.reindex(
            index=index_weight.index,
            columns=stock_columns,
            fill_value=False,
        ).astype(bool)

        stock_execution = _load_stock_execution_matrices(loader)
        stock_matrices = {
            "returns": loader.load_matrix("returns"),
            "peer_groups": loader.load_matrix(peer_group_dataset),
            **stock_execution,
        }
        stock_matrices = {
            name: matrix.reindex(index=universe.index, columns=stock_columns)
            for name, matrix in stock_matrices.items()
        }
        benchmark_weight = build_benchmark_weight(index_weight).reindex(
            index=universe.index,
            columns=stock_columns,
        )

        etf_price, etf_factor, etf_volume = _load_etf_execution_matrices(
            config.raw_dataguide_dir / config.data["dataguide"]["k200_etfs"],
            etf_ticker,
        )
        calendar = universe.index.intersection(etf_price.index).sort_values()
        if len(calendar) < 2:
            raise ValueError("Qlib peer momentum requires at least two common trading dates.")

        universe = universe.reindex(calendar)
        returns = stock_matrices["returns"].reindex(calendar)
        peer_groups = stock_matrices["peer_groups"].reindex(calendar)
        benchmark_weight = benchmark_weight.reindex(calendar)
        stock_price = stock_matrices["execution_price"].reindex(calendar)
        stock_factor = stock_matrices["position_unit_factor"].reindex(calendar)
        stock_volume = stock_matrices["volume"].reindex(calendar)
        stock_suspended = stock_matrices["suspended"].reindex(calendar).fillna(
            False
        ).astype(bool)

        execution_price = stock_price.copy()
        execution_price[etf_ticker] = etf_price.reindex(calendar)[etf_ticker]
        position_unit_factor = stock_factor.copy()
        position_unit_factor[etf_ticker] = etf_factor.reindex(calendar)[etf_ticker]
        volume = stock_volume.copy()
        volume[etf_ticker] = etf_volume.reindex(calendar)[etf_ticker]
        suspended = stock_suspended.copy()
        suspended[etf_ticker] = False

        valid_price = execution_price.notna() & execution_price.gt(0.0)
        invalid_factor = valid_price & (
            position_unit_factor.isna() | position_unit_factor.le(0.0)
        )
        if invalid_factor.any().any():
            date, ticker = invalid_factor.stack()[lambda value: value].index[0]
            raise ValueError(
                "Execution price requires a positive position unit factor. "
                f"date={date}, ticker={ticker}"
            )
        invalid_volume = valid_price & (volume.isna() | volume.lt(0.0))
        if invalid_volume.any().any():
            date, ticker = invalid_volume.stack()[lambda value: value].index[0]
            raise ValueError(
                "Execution price requires non-negative actual volume. "
                f"date={date}, ticker={ticker}"
            )

        buyable = pd.DataFrame(False, index=calendar, columns=execution_price.columns)
        buyable.loc[:, stock_columns] = universe & ~stock_suspended & valid_price.loc[
            :, stock_columns
        ]
        buyable.loc[:, etf_ticker] = valid_price[etf_ticker]
        # Production holdings ledger는 universe에서 제외된 보유종목을 당일
        # 유효가격으로 0 target까지 청산합니다. Qlib twin도 동일하게 거래정지
        # 종목의 신규 매수는 막되, 남아 있는 position의 exit는 허용합니다.
        sellable = valid_price
        asset_class = pd.Series("stock", index=execution_price.columns, dtype="object")
        asset_class.loc[etf_ticker] = "etf"
        result = cls(
            universe_mask=universe,
            returns=returns.astype("float64"),
            peer_groups=peer_groups,
            benchmark_weight=benchmark_weight.astype("float64"),
            execution_price=execution_price.astype("float64"),
            position_unit_factor=position_unit_factor.astype("float64"),
            volume=volume.astype("float64"),
            buyable=buyable.astype(bool),
            sellable=sellable.astype(bool),
            suspended=suspended.astype(bool),
            asset_class=asset_class,
            etf_ticker=etf_ticker,
        )
        result._validate_axes()
        return result

    @property
    def calendar(self) -> pd.DatetimeIndex:
        return self.execution_price.index

    @property
    def stock_columns(self) -> pd.Index:
        return self.universe_mask.columns

    @property
    def physical_columns(self) -> pd.Index:
        return self.execution_price.columns

    def previous_observation_date(self, trade_date: pd.Timestamp) -> pd.Timestamp:
        date = pd.Timestamp(trade_date).normalize()
        prior = self.calendar[self.calendar < date]
        if prior.empty:
            raise ValueError(f"No observation date precedes trade date {date.date()}.")
        return pd.Timestamp(prior[-1])

    def resolve_run_dates(
        self,
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp | None,
    ) -> tuple[pd.Timestamp, pd.Timestamp]:
        requested_start = pd.Timestamp(start_date)
        starts = self.calendar[self.calendar >= requested_start]
        if starts.empty:
            raise ValueError(f"No trading date on or after {requested_start.date()}.")
        start = pd.Timestamp(starts[0])
        if self.calendar.get_loc(start) == 0:
            raise ValueError("Backtest start requires one prior observation date.")
        requested_end = self.calendar[-1] if end_date is None else pd.Timestamp(end_date)
        ends = self.calendar[self.calendar <= requested_end]
        if ends.empty:
            raise ValueError(f"No trading date on or before {requested_end.date()}.")
        end = pd.Timestamp(ends[-1])
        if end < start:
            raise ValueError("end_date must not precede start_date.")
        return start, end

    def _validate_axes(self) -> None:
        research = {
            "returns": self.returns,
            "peer_groups": self.peer_groups,
            "benchmark_weight": self.benchmark_weight,
        }
        for name, matrix in research.items():
            if not matrix.index.equals(self.universe_mask.index) or not matrix.columns.equals(
                self.universe_mask.columns
            ):
                raise ValueError(f"{name} axes must match universe_mask.")
        physical = {
            "position_unit_factor": self.position_unit_factor,
            "volume": self.volume,
            "buyable": self.buyable,
            "sellable": self.sellable,
            "suspended": self.suspended,
        }
        for name, matrix in physical.items():
            if not matrix.index.equals(self.execution_price.index) or not matrix.columns.equals(
                self.execution_price.columns
            ):
                raise ValueError(f"{name} axes must match execution_price.")
        if not self.asset_class.index.equals(self.execution_price.columns):
            raise ValueError("asset_class index must match execution physical columns.")


def _build_position_unit_factor(
    quantity_adjustment_factor: pd.DataFrame,
) -> pd.DataFrame:
    factor = quantity_adjustment_factor.astype("float64")
    if factor.lt(0.0).any().any():
        raise ValueError("Quantity adjustment factor must be non-negative.")
    event_factor = factor.mask(factor.eq(0.0), 1.0)
    multiplier = event_factor.iloc[::-1].shift(1).cumprod().iloc[::-1].fillna(1.0)
    result = 1.0 / multiplier.where(multiplier.gt(0.0))
    result.index = quantity_adjustment_factor.index
    result.columns = quantity_adjustment_factor.columns
    return result


def _load_stock_execution_matrices(
    loader: ConfigDrivenDataLoader,
) -> dict[str, pd.DataFrame]:
    source = loader.catalog.require_source("adjusted_prices")
    table = loader.query_engine.execute(
        """
        select
          date,
          ticker,
          "종가" as execution_price,
          "수정계수" as quantity_adjustment_factor,
          trade_volume,
          is_trading_halt
        from adjusted_prices
        """,
        [source],
    )
    table["date"] = pd.to_datetime(table["date"], errors="coerce")
    matrices = {
        name: pivot_long_to_matrix(table, column)
        for name, column in {
            "execution_price": "execution_price",
            "quantity_adjustment_factor": "quantity_adjustment_factor",
            "volume": "trade_volume",
            "suspended": "is_trading_halt",
        }.items()
    }
    matrices["position_unit_factor"] = _build_position_unit_factor(
        matrices.pop("quantity_adjustment_factor")
    )
    return matrices


def _load_etf_execution_matrices(
    path: Path,
    ticker: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    field_map = {
        "종가(원)": "execution_close_price",
        "수정계수": "quantity_adjustment_factor",
        "거래량(주)": "trade_volume",
    }
    tidy = dataguide_wide_to_tidy(path, field_map=field_map)
    required = {"date", "ticker", *field_map.values()}
    missing = sorted(required - set(tidy.columns))
    if missing:
        raise KeyError(f"K200 ETF source is missing fields: {missing}")
    selected = tidy.loc[tidy["ticker"].eq(ticker)].copy()
    if selected.empty:
        raise KeyError(f"Configured physical ETF ticker is missing: {ticker}")
    for column in field_map.values():
        selected[column] = pd.to_numeric(selected[column], errors="coerce")
    matrices = {
        column: selected.pivot(index="date", columns="ticker", values=column)
        .sort_index()
        .loc[:, [ticker]]
        for column in field_map.values()
    }
    position_factor = _build_position_unit_factor(
        matrices["quantity_adjustment_factor"]
    )
    return (
        matrices["execution_close_price"],
        position_factor,
        matrices["trade_volume"],
    )
