"""Phase 0 data pipeline — xtdc connect → per-instrument data download →
per-group indicator calculation.

Extracted from PortfolioTradingRunner._phase0_data_pipeline in the
2026-05-08 refactor. Independent because: takes ``config`` and
``present_date`` as inputs, produces files on disk under
``paths.market_data_dir`` and ``paths.indicators_backtest_dir``. No
runner state crosses the boundary.

Abort policy (architect-flagged safety): if XtdcClient cannot connect,
the pipeline raises ``RuntimeError`` immediately rather than silently
skipping. Trading without fresh market data is unsafe (stale indicators
→ mislead strategy → real-money loss).

Behavioral equivalence: every code path matches PortfolioTradingRunner.
_phase0_data_pipeline pre-refactor (the deferred ``get_regime_params``
import was hoisted to module top in followup F2 — verified no circular
hazard exists from this module's location).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

# Default historical lookback for indicator computation when no slot
# config specifies an explicit `start_date`. 4 years is enough warmup for
# any realistic indicator parameter — even a 200-day MA on weekly bars
# only needs ~4 years — without bloating the data download. Slots with
# tighter lookback needs can override by setting `start_date` on their
# slot config (a dataclass attribute, read via getattr below).
_DEFAULT_INDICATOR_LOOKBACK_DAYS = 4 * 365

from ..config.portfolio_deploy_config import PortfolioDeployConfig
from ..platforms.miniqmt.xtdc_client import XtdcClient
from echolon.config.markets.factory import MarketFactory
from echolon.config.paths_config import PathsConfig
from echolon.data.live_data import run_live_data_update
from echolon.indicators.run import run_indicator_calculation
from echolon.indicators.utils.merge_indicators import (
    load_indicator_list, merge_indicator_lists,
)
from echolon._internal.strategy_files import get_regime_params


class Phase0DataPipeline:
    """One Phase 0 invocation. Construct once per cycle.

    Usage:
        Phase0DataPipeline(config=self.config, log=self.log).run(present_date=...)
    """

    def __init__(self, config: PortfolioDeployConfig, log: Any):
        self.config = config
        self.log = log

    def run(self, present_date: datetime) -> None:
        """Execute Phase 0. Raises RuntimeError if xtdc unavailable."""
        xtdc = XtdcClient()
        if not xtdc.connect():
            self.log.critical(
                "XtdcClient connection failed — ABORTING cycle. Trading without "
                "fresh market data is unsafe (stale indicators → mislead strategy). "
                "Investigate Xuntou auth / network / VPN routing, then re-run."
            )
            raise RuntimeError(
                "Phase 0 abort: XtdcClient connect failed; refusing to trade on stale data"
            )

        try:
            self._download_per_instrument(xtdc, present_date)
        finally:
            xtdc.disconnect()

        self._calculate_indicators_per_group(present_date)

    # ----- Step 1: per-instrument data download -----

    def _download_per_instrument(self, xtdc: XtdcClient, present_date: datetime) -> None:
        groups = self.config.get_slots_by_instrument_and_barsize()
        for (instrument_code, bar_size), slot_configs in groups.items():
            first_sc = slot_configs[0]
            ctx = MarketFactory.create(
                market=first_sc.market,
                instrument=first_sc.instrument_code,
                frequency=first_sc.frequency,
                bar_size=first_sc.bar_size,
            )
            self.log.info(f"Data download: {instrument_code}/{bar_size}")
            try:
                run_live_data_update(
                    ctx=ctx,
                    client=xtdc,
                    present_date=present_date,
                    trading_calendar_path=self.config.deploy.trading_calendar_path,
                    skip_calendar=True,
                )
            except Exception as e:
                self.log.error(f"Data download failed for {instrument_code}/{bar_size}: {e}")

    # ----- Step 2: per-group indicator calculation -----

    def _calculate_indicators_per_group(self, present_date: datetime) -> None:
        paths = PathsConfig.from_env()
        indicators_backtest_dir = paths.indicators_backtest_dir
        end_date = present_date.strftime("%Y-%m-%d")

        groups = self.config.get_slots_by_instrument_and_barsize()
        for (instrument_code, bar_size), slot_configs in groups.items():
            group_id = f"{instrument_code}_{bar_size}"
            group_dir = os.path.join(str(indicators_backtest_dir), group_id)

            slot_configs_with_ind = []
            for sc in slot_configs:
                ind_path = os.path.join(sc.strategy_code_dir, "strategy_indicator_list.json")
                if not os.path.exists(ind_path):
                    self.log.warning(f"[{sc.slot_id}] skipped: no {ind_path}")
                    continue
                ind = load_indicator_list(ind_path)
                rp = get_regime_params(sc.strategy_code_dir)
                slot_configs_with_ind.append((sc, ind, rp))

            if not slot_configs_with_ind:
                self.log.warning(f"Indicators skipped for group {group_id}: no slot has a list")
                continue

            merged_indicator_list = merge_indicator_lists(
                [ind for (_, ind, _) in slot_configs_with_ind]
            )

            regime_params = next(
                (rp for (_, _, rp) in slot_configs_with_ind if rp is not None), None,
            )
            if regime_params is not None:
                for (sc, _, rp) in slot_configs_with_ind:
                    if rp is not None and rp != regime_params:
                        self.log.warning(
                            f"[{sc.slot_id}] regime_params differ within group {group_id}; "
                            f"using first slot's params"
                        )

            start_dates = [
                getattr(sc, "start_date", None)
                for (sc, _, _) in slot_configs_with_ind
            ]
            start_dates = [d for d in start_dates if d]
            if start_dates:
                start_date = min(start_dates)
            else:
                # No slot specified an explicit start_date — fall back to
                # a default lookback. Without this, run_indicator_calculation
                # raises ValueError("start_date and end_date are required
                # when trading_dates is None") and the entire cycle aborts.
                default_start = present_date - timedelta(
                    days=_DEFAULT_INDICATOR_LOOKBACK_DAYS,
                )
                start_date = default_start.strftime("%Y-%m-%d")
                self.log.info(
                    f"Indicators: {group_id} no slot.start_date provided; "
                    f"defaulting to {start_date} "
                    f"(present - {_DEFAULT_INDICATOR_LOOKBACK_DAYS} days)"
                )

            first_sc = slot_configs_with_ind[0][0]
            ctx = MarketFactory.create(
                market=first_sc.market,
                instrument=first_sc.instrument_code,
                frequency=first_sc.frequency,
                bar_size=first_sc.bar_size,
            )

            self.log.info(
                f"Indicators: {group_id} "
                f"({len(slot_configs_with_ind)} slot(s), "
                f"{len(merged_indicator_list)} unique indicators) -> {group_dir}"
            )
            try:
                run_indicator_calculation(
                    ctx=ctx, output_dir=group_dir,
                    indicator_list=merged_indicator_list,
                    use_parallel=True, regime_params=regime_params,
                    start_date=start_date, end_date=end_date,
                    paths=paths,
                )
            except Exception as e:
                self.log.error(f"Indicators failed for group {group_id}: {e}")
