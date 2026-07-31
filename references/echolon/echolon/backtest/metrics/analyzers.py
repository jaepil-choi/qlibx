"""
Performance Analyzers
=====================

Backtrader analyzers for computing performance metrics.

MIGRATED FROM: modules/backtest/backtesting/engine/analyzers.py
Changes:
- Parameterized with IMarketAdapter instead of hardcoded SHFE/aluminum logic
- Uses ContractIndicatorManager from quant_engine.data module
- Removed hardcoded paths and futures type
- Works with any market that implements IMarketAdapter

Metrics calculated:
1. Returns metrics:
   - Total return
   - Annualized return
   - Monthly returns

2. Risk metrics:
   - Sharpe ratio
   - Sortino ratio
   - Calmar ratio
   - Maximum drawdown
   - Average drawdown

3. Trade metrics:
   - Total trades
   - Win rate
   - Average win/loss
   - Profit factor
   - Average holding period
   - Max consecutive wins/losses

4. Position metrics:
   - Time in market
   - Average position size
   - Max position size

Analyzer classes:
- ContractAwareTradeAnalyzer: Trade analyzer with contract-specific PnL corrections
- TradeList: Detailed trade statistics
- add_analyzers(): Add all analyzers to cerebro
- extract_analysis_results(): Extract results from strategy
"""

import backtrader as bt
import pandas as pd
import datetime
import logging
from typing import Optional, Dict, Any, List, TYPE_CHECKING

# Classifier labels come from the registered classifier's label_map. The
# trade analyzer stratifies trades by segmentation column (typically the
# TRS-paradigm 'market_regime' indicator). Conversion happens via the
# registered classifier; if no classifier is registered, the analyzer returns
# the raw value (numeric or string) without normalization.
def convert_regime_to_string(value):
    """Best-effort label conversion for trade-log display.

    Tries the registered ``market_regime`` classifier's label_map first.
    If unregistered, returns the value coerced to string ('unknown' for NaN/None).
    """
    import pandas as _pd
    if value is None or _pd.isna(value):
        return "unknown"
    if isinstance(value, str):
        return value  # already a label
    try:
        from echolon.indicators.registry import get_regime_classifier
        classifier = get_regime_classifier("market_regime")
        return classifier.label_map.get(int(value), "unknown")
    except (KeyError, ValueError, TypeError):
        return str(value)

if TYPE_CHECKING:
    from echolon.strategy.interfaces import IMarketAdapter
    from echolon.data.loaders.contract_loader import ContractIndicatorManager

logger = logging.getLogger(__name__)


def _calculate_profit_factor(trade_analysis: Dict[str, Any]) -> float:
    """
    Safely calculate profit factor, handling cases where there are no losing trades.

    Parameters
    ----------
    trade_analysis : dict
        Trade analysis results from backtrader

    Returns
    -------
    float
        Profit factor or 0.0 if cannot be calculated
    """
    gross_profit = abs(trade_analysis.get('won', {}).get('pnl', {}).get('total', 0))
    gross_loss = abs(trade_analysis.get('lost', {}).get('pnl', {}).get('total', 0))

    if gross_loss == 0:
        return float('inf') if gross_profit > 0 else 0.0

    return gross_profit / gross_loss


def _calculate_calmar_ratio(annual_return_pct: float, max_drawdown_pct: float) -> float:
    """
    Calculate Calmar ratio manually.

    Calmar Ratio = Annual Return / Maximum Drawdown

    Parameters
    ----------
    annual_return_pct : float
        Annual return as percentage
    max_drawdown_pct : float
        Maximum drawdown as percentage (positive value)

    Returns
    -------
    float
        Calmar ratio or 0.0 if cannot be calculated
    """
    if max_drawdown_pct <= 0:
        return float('inf') if annual_return_pct > 0 else 0.0

    calmar = annual_return_pct / abs(max_drawdown_pct)

    logger.debug(f"Calculated Calmar ratio: {annual_return_pct:.3f}% / {abs(max_drawdown_pct):.3f}% = {calmar:.3f}")

    return calmar


class ContractAwareTradeAnalyzer(bt.Analyzer):
    """
    Enhanced trade analyzer that calculates correct PnL using contract-specific prices.

    This analyzer addresses the issue where positions held across contract rolls
    have incorrect PnL calculations due to using rolling main contract prices
    instead of the specific contract where the position was opened.

    Parameters
    ----------
    market_adapter : IMarketAdapter
        Market adapter for contract management
    contract_manager : ContractIndicatorManager
        Manager for contract-specific indicator/price data
    regime_data : pd.DataFrame, optional
        Pre-loaded regime data (if None, will attempt to load)
    contract_multiplier : float
        Contract multiplier for PnL calculations 
    """

    params = (
        ('market_adapter', None),
        ('contract_manager', None),
        ('regime_data', None),
        ('contract_multiplier', None),  # Required - passed from ctx.multiplier via add_analyzers()
        ('regime_column', 'market_regime'),
    )

    def __init__(self):
        super(ContractAwareTradeAnalyzer, self).__init__()

        self.market_adapter = self.p.market_adapter
        self.contract_manager = self.p.contract_manager
        self.contract_multiplier = self.p.contract_multiplier

        # Track orders for trade reconstruction
        self.orders: List[Dict[str, Any]] = []
        self.completed_trades: List[Dict[str, Any]] = []

        # Load regime data
        self.regime_data = self.p.regime_data
        if self.regime_data is not None:
            logger.debug(f"ContractAwareTradeAnalyzer received pre-loaded regime data with {len(self.regime_data)} records.")

        # Debug information
        self.debug_info: List[Dict[str, Any]] = []

    def _get_contract_price(self, contract_name: str, trading_date: datetime.datetime,
                           price_type: str = 'close') -> Optional[float]:
        """Get price for a specific contract on a specific date."""
        if self.contract_manager is None:
            return None

        # Convert datetime to date if needed
        if hasattr(trading_date, 'date'):
            trading_date = trading_date.date()

        return self.contract_manager.get_indicator(contract_name, trading_date, price_type)

    def _get_main_contract_for_date(self, trading_date: datetime.datetime) -> Optional[str]:
        """Get main contract for a given date using market adapter."""
        if self.market_adapter is None:
            return None

        # Convert datetime to date if needed
        if hasattr(trading_date, 'date'):
            trading_date = trading_date.date()

        # Get instrument from market adapter (property is 'symbol', not 'instrument')
        instrument = getattr(self.market_adapter, 'symbol')
        return self.market_adapter.get_main_contract(trading_date, instrument)

    def _get_market_regime(self, dt: datetime.datetime) -> str:
        """Get market regime for a specific date."""
        if self.regime_data is None or len(self.regime_data) == 0:
            return "unknown"

        target_date = pd.to_datetime(dt.date()) if hasattr(dt, 'date') else pd.to_datetime(dt)
        available_dates = self.regime_data[self.regime_data['trading_date'] <= target_date]

        if available_dates.empty:
            return "unknown"

        last_trading_date = available_dates['trading_date'].max()
        regime_row = available_dates[available_dates['trading_date'] == last_trading_date]

        if regime_row.empty:
            return "unknown"

        regime_col = self.p.regime_column
        if regime_col not in regime_row.columns:
            return "unknown"

        numeric_regime = regime_row[regime_col].iloc[0]

        # Convert numeric regime to string using canonical mapping
        return convert_regime_to_string(numeric_regime)

    def _get_previous_trading_day(self, dt: datetime.datetime) -> Optional[datetime.datetime]:
        """Get the previous trading day strictly before dt using regime_data."""
        if self.regime_data is None or len(self.regime_data) == 0:
            return None
        target_date = pd.to_datetime(dt.date()) if hasattr(dt, 'date') else pd.to_datetime(dt)
        prior_dates = self.regime_data[self.regime_data['trading_date'] < target_date]
        if prior_dates.empty:
            return None
        return prior_dates['trading_date'].max()

    def notify_order(self, order):
        """Track order executions using broker's unified position system."""
        if order.status == bt.Order.Completed:
            current_date = bt.num2date(order.executed.dt)

            # Get contract information from the broker's tracking system
            order_contract = None
            if hasattr(self.strategy.broker, '_position_contracts'):
                order_contract = self.strategy.broker._position_contracts.get(order.data)

            # Fallback to main contract determination
            if not order_contract:
                logger.debug(f"No contract found for order {order.ref}, using main contract for date {current_date}")
                order_contract = self._get_main_contract_for_date(current_date)

            order_info = {
                'ref': order.ref,
                'datetime': current_date,
                'data_id': id(order.data),
                'size': order.executed.size,
                'price': order.executed.price,
                'commission': order.executed.comm,
                'contract': order_contract,
                'is_long': order.executed.size > 0
            }

            self.orders.append(order_info)

            # Get position information from broker
            broker_position = self.strategy.broker.getposition(order.data, clone=True)

            if hasattr(broker_position, 'size'):
                current_position_size = broker_position.size
            else:
                current_position_size = broker_position.size if broker_position else 0

            # Check if this order closes a position
            is_position_closing = (
                current_position_size == 0 or
                (order.executed.size > 0 and current_position_size <= 0) or
                (order.executed.size < 0 and current_position_size >= 0)
            )

            if is_position_closing:
                self._process_potential_trade_closure(order_info, broker_position)

            logger.debug(f"Order {order.ref} processed: {order_contract} size={order.executed.size} "
                        f"at {order.executed.price:.2f}, broker position: {current_position_size}")

    def _process_potential_trade_closure(self, exit_order_info: Dict[str, Any], broker_position):
        """Process a potential trade closure using available order history.

        Handles partial exits correctly by:
        1. Using exit order size (not entry size) for P&L calculation
        2. Allocating entry commission proportionally to the exited size
        """
        if not self.orders:
            return

        exit_is_long = exit_order_info['is_long']

        # Look for recent entry orders with opposite direction
        potential_entries = []
        for order_info in reversed(self.orders[:-1]):
            order_is_long = order_info['is_long']
            if order_is_long != exit_is_long:
                potential_entries.append(order_info)

            if len(potential_entries) >= 10:
                break

        if not potential_entries:
            logger.debug("No matching entry order found for potential trade closure")
            return

        # Use the most recent matching entry
        entry_order_info = potential_entries[0]

        entry_date = entry_order_info['datetime']
        exit_date = exit_order_info['datetime']
        entry_contract = entry_order_info['contract']

        # Calculate corrected exit price using the entry contract's price on exit date
        corrected_exit_price = self._get_contract_price(entry_contract, exit_date, 'close')

        if corrected_exit_price is None or corrected_exit_price == 0.0:
            corrected_exit_price = exit_order_info['price']
            logger.warning(f"[CONTRACT_AWARE_TRADES] Price fallback | contract={entry_contract}, date={exit_date}")

        # Get entry and exit sizes
        # entry_order_info['size'] is signed (e.g., +3 for long entry)
        # exit_order_info['size'] is signed (e.g., -1 for partial long exit)
        entry_size = abs(entry_order_info['size'])
        exit_size = abs(exit_order_info['size'])  # Actual size being exited (for partial exits)

        # Use exit size for P&L calculation (handles partial exits)
        actual_trade_size = exit_size

        entry_price = entry_order_info['price']
        is_long = entry_order_info['size'] > 0  # Determine direction from entry

        if is_long:
            price_diff = corrected_exit_price - entry_price
        else:
            price_diff = entry_price - corrected_exit_price

        # Calculate P&L using actual exited size (not full entry size)
        corrected_pnl = price_diff * actual_trade_size * self.contract_multiplier

        # Calculate return percentage
        return_pct = (price_diff / entry_price) * 100 if entry_price != 0 else 0

        # Get market regime at execution date and at signal generation date
        entry_regime = self._get_market_regime(entry_date)
        decision_date = self._get_previous_trading_day(entry_date)
        decision_regime = self._get_market_regime(decision_date) if decision_date else entry_regime

        # Compare with backtrader's calculation (for debug info)
        backtrader_exit_price = exit_order_info['price']
        backtrader_price_diff = (backtrader_exit_price - entry_price) if is_long else (entry_price - backtrader_exit_price)
        backtrader_pnl = backtrader_price_diff * actual_trade_size * self.contract_multiplier

        price_correction = corrected_exit_price - backtrader_exit_price
        pnl_correction = corrected_pnl - backtrader_pnl

        # Commission calculation for partial exits:
        # Entry commission is allocated proportionally to the exited size
        # Total commission = (entry_comm / entry_size * exit_size) + exit_comm
        entry_commission = entry_order_info['commission']
        exit_commission = exit_order_info['commission']
        entry_comm_portion = (entry_commission / entry_size * actual_trade_size) if entry_size > 0 else 0.0
        total_commission = entry_comm_portion + exit_commission

        pnlcomm = corrected_pnl - total_commission

        # Store the corrected trade
        trade_record = {
            'entry_date': entry_date,
            'exit_date': exit_date,
            'entry_time': entry_date,
            'direction': 'long' if is_long else 'short',
            'size': actual_trade_size,  # Use actual exit size
            'entry_price': entry_price,
            'exit_price': corrected_exit_price,
            'pnl': corrected_pnl,
            'commission': total_commission,
            'pnlcomm': pnlcomm,
            'return_pct': return_pct,
            'entry_regime': entry_regime,
            'decision_regime': decision_regime,
            'exit_reason': 'strategy_exit',
            'entry_contract': entry_contract,
            'backtrader_exit_price': backtrader_exit_price,
            'contract_exit_price': corrected_exit_price,
            'price_correction': price_correction,
            'pnl_correction': pnl_correction
        }

        self.completed_trades.append(trade_record)

        # Store debug information
        debug_record = {
            'trade_date': exit_date,
            'entry_contract': entry_contract,
            'entry_price': entry_price,
            'backtrader_exit_price': backtrader_exit_price,
            'contract_exit_price': corrected_exit_price,
            'price_correction': price_correction,
            'backtrader_pnl': backtrader_pnl,
            'corrected_pnl': corrected_pnl,
            'pnl_correction': pnl_correction,
            'position_size': actual_trade_size,
            'entry_size': entry_size,
            'exit_size': exit_size
        }
        self.debug_info.append(debug_record)

        if abs(price_correction) > 0.01:
            logger.debug(f"PnL CORRECTED: {entry_contract} exit on {exit_date.strftime('%Y-%m-%d')}: "
                       f"BT price {backtrader_exit_price:.2f} -> Contract price {corrected_exit_price:.2f} "
                       f"(correction: {price_correction:.2f}), PnL: {backtrader_pnl:.2f} -> {corrected_pnl:.2f}")

    def save_debug_info(self, filepath: str):
        """Save debug information about price corrections."""
        if self.debug_info:
            debug_df = pd.DataFrame(self.debug_info)
            debug_filepath = filepath.replace('.csv', '_contract_corrections.csv')
            debug_df.to_csv(debug_filepath, index=False)
            logger.debug(f"Contract price correction debug info saved to {debug_filepath}")

            # Print summary statistics
            total_corrections = len(debug_df)
            significant_corrections = len(debug_df[abs(debug_df['price_correction']) > 0.01])
            avg_price_correction = debug_df['price_correction'].mean()
            avg_pnl_correction = debug_df['pnl_correction'].mean()
            total_pnl_correction = debug_df['pnl_correction'].sum()

            logger.debug("=== CONTRACT PRICE CORRECTION SUMMARY ===")
            logger.debug(f"Total trades: {total_corrections}")
            logger.debug(f"Significant price corrections (>0.01): {significant_corrections}")
            logger.debug(f"Average price correction: {avg_price_correction:.3f}")
            logger.debug(f"Average PnL correction per trade: {avg_pnl_correction:.2f}")
            logger.debug(f"Total PnL correction: {total_pnl_correction:.2f}")

    def get_analysis(self) -> Dict[str, Any]:
        """Return the analysis with corrected trade data."""
        if not self.completed_trades:
            return {}

        trades_records = []
        for trade in self.completed_trades:
            record = {
                'entry_date': trade['entry_date'].strftime('%Y-%m-%d'),
                'exit_date': trade['exit_date'].strftime('%Y-%m-%d'),
                'entry_time': trade['entry_time'],
                'direction': trade['direction'],
                'size': trade['size'],
                'entry_price': trade['entry_price'],
                'exit_price': trade['exit_price'],
                'pnl': trade['pnl'],
                'commission': trade['commission'],
                'pnlcomm': trade['pnlcomm'],
                'return_pct': trade['return_pct'],
                'entry_regime': trade['entry_regime'],
                'decision_regime': trade['decision_regime'],
                'exit_reason': trade['exit_reason'],
                'entry_contract': trade['entry_contract'],
                'price_correction': trade['price_correction'],
                'pnl_correction': trade['pnl_correction']
            }
            trades_records.append(record)

        return {
            'trades': trades_records,
            'total_trades': len(self.completed_trades),
            'total_pnl': sum(t['pnl'] for t in self.completed_trades),
            'total_pnl_correction': sum(t['pnl_correction'] for t in self.completed_trades),
            'avg_pnl': sum(t['pnl'] for t in self.completed_trades) / len(self.completed_trades) if self.completed_trades else 0
        }


class TradeList(bt.Analyzer):
    """
    Enhanced Trade List analyzer with comprehensive debugging for futures PnL calculations.

    Parameters
    ----------
    regime_data : pd.DataFrame, optional
        Pre-loaded regime data
    contract_multiplier : float
        Contract multiplier for PnL calculations
    """

    params = (
        ('regime_data', None),
        ('contract_multiplier', None),  # Required - passed from ctx.multiplier via add_analyzers()
        ('regime_column', 'market_regime'),
        ('session_context_provider', None),  # For intraday session tracking
    )

    def __init__(self):
        super(TradeList, self).__init__()
        self.completed_trades: List[Dict[str, Any]] = []
        self.order_history: Dict[int, Dict[str, Any]] = {}
        self.position_sizes: Dict[str, int] = {}
        self.position_state: Dict[str, Dict[str, Any]] = {}

        self.contract_mult = self.p.contract_multiplier
        self.debug_info: List[Dict[str, Any]] = []

        self.regime_data = self.p.regime_data
        if self.regime_data is not None:
            logger.debug("TradeList analyzer received pre-loaded regime data.")

        # Session context for intraday trading
        self._session_provider = self.p.session_context_provider
        if self._session_provider is not None:
            logger.debug(f"TradeList analyzer received session context provider: {self._session_provider}")

    def start(self):
        """Initialize contract multiplier from commission info."""
        try:
            if hasattr(self.strategy, 'broker'):
                broker = self.strategy.broker
                if hasattr(broker, 'comminfo'):
                    comminfo = broker.comminfo.get(None)
                    if comminfo and hasattr(comminfo, 'p') and hasattr(comminfo.p, 'mult'):
                        self.contract_mult = comminfo.p.mult
                        logger.debug(f"Contract multiplier detected from broker: {self.contract_mult}")
                        return

            logger.warning(f"[TRADELIST] Using default multiplier | value={self.contract_mult}")
        except Exception as e:
            logger.error(f"[TRADELIST] Multiplier detection failed | error={e}, using_default={self.contract_mult}")

    def notify_order(self, order):
        """Track order executions with detailed debugging information."""
        if order.status == bt.Order.Completed:
            order_info = {
                'ref': order.ref,
                'size': abs(order.executed.size),
                'price': order.executed.price,
                'value': order.executed.value,
                'commission': order.executed.comm,
                'datetime': bt.num2date(order.executed.dt),
                'direction': 'long' if order.executed.size > 0 else 'short',
                'raw_size': order.executed.size,
                'created_size': order.created.size if hasattr(order, 'created') else None,
                'data_name': order.data._name if hasattr(order.data, '_name') else 'data0'
            }

            # Capture session context for intraday trading
            if self._session_provider is not None:
                try:
                    order_time = bt.num2date(order.executed.dt)
                    session_ctx = self._session_provider.get_session_context(order_time)
                    if session_ctx:
                        order_info['session_phase'] = session_ctx.session_phase
                        order_info['session_type'] = session_ctx.session_type
                        order_info['bar_of_session'] = session_ctx.bar_of_session
                        order_info['total_bars_in_session'] = session_ctx.total_bars_in_session
                        # Create session_id as date + session_type (e.g., "2023-01-03_day")
                        order_date = order_time.strftime('%Y-%m-%d')
                        order_info['session_id'] = f"{order_date}_{session_ctx.session_type}"
                except Exception as e:
                    logger.debug(f"Could not capture session context for order {order.ref}: {e}")

            self.order_history[order.ref] = order_info

            # Track position state
            data_name = order_info['data_name']
            if data_name not in self.position_state:
                self.position_state[data_name] = {'size': 0, 'in_position': False}

            prev_size = self.position_state[data_name]['size']
            new_size = prev_size + order.executed.size
            self.position_state[data_name]['size'] = new_size

            if prev_size == 0 and new_size != 0:
                self.position_state[data_name]['in_position'] = True
            elif prev_size != 0 and new_size == 0:
                self.position_state[data_name]['in_position'] = False

            logger.debug(f"Order {order.ref} executed: size={order.executed.size}, "
                        f"price={order.executed.price}, position size now: {new_size}")

    def notify_trade(self, trade):
        """Track completed trades with comprehensive debugging."""
        if trade.isclosed:
            # Find entry and exit prices from order history
            entry_size = 0
            exit_size = 0
            entry_price = None
            exit_price = None
            entry_orders = []
            exit_orders = []
            exit_commission = 0.0

            for order_ref, order_data in self.order_history.items():
                order_time_diff_open = abs((order_data['datetime'] - bt.num2date(trade.dtopen)).total_seconds())
                order_time_diff_close = abs((order_data['datetime'] - bt.num2date(trade.dtclose)).total_seconds())

                if trade.long:
                    if order_data['raw_size'] > 0 and order_time_diff_open < 86400:
                        entry_price = order_data['price']
                        entry_size = order_data['size']
                        entry_orders.append(order_data)
                    elif order_data['raw_size'] < 0 and order_time_diff_close < 86400:
                        exit_price = order_data['price']
                        exit_size = order_data['size']  # This is the actual exit size
                        exit_commission = order_data.get('commission', 0.0)
                        exit_orders.append(order_data)
                else:
                    if order_data['raw_size'] < 0 and order_time_diff_open < 86400:
                        entry_price = order_data['price']
                        entry_size = order_data['size']
                        entry_orders.append(order_data)
                    elif order_data['raw_size'] > 0 and order_time_diff_close < 86400:
                        exit_price = order_data['price']
                        exit_size = order_data['size']  # This is the actual exit size
                        exit_commission = order_data.get('commission', 0.0)
                        exit_orders.append(order_data)

            # Use exit_size as the actual trade size (for partial exits)
            actual_trade_size = exit_size

            # Debug: Log trade and matched orders for partial exit investigation
            print(
                f"[TRADELIST] Trade closed | dtopen={bt.num2date(trade.dtopen).date()}, "
                f"dtclose={bt.num2date(trade.dtclose).date()}, entry_size={entry_size}, "
                f"exit_size={exit_size}, exit_orders_count={len(exit_orders)}"
            )
            for eo in exit_orders:
                print(f"  Exit order: datetime={eo['datetime']}, size={eo['size']}, raw_size={eo['raw_size']}")

            # Calculate P&L for the actual exited size using contract multiplier
            multiplier = self.contract_mult if self.contract_mult else 1.0
            if trade.long:
                price_diff = exit_price - entry_price
            else:
                price_diff = entry_price - exit_price
            calculated_pnl = price_diff * actual_trade_size * multiplier

            # Commission calculation for partial exits:
            # Entry commission is allocated proportionally to each partial exit
            # Total commission = (entry_comm / entry_size * exit_size) + exit_comm
            entry_commission = entry_orders[0]['commission'] if entry_orders else 0.0
            entry_comm_portion = (entry_commission / entry_size * actual_trade_size) if entry_size > 0 else 0.0
            calculated_commission = entry_comm_portion + exit_commission
            calculated_pnlcomm = calculated_pnl - calculated_commission

            # Calculate return percentage
            return_pct = 0.0
            if entry_price and entry_price != 0 and exit_price is not None:
                return_pct = (price_diff / entry_price) * 100

            # Get market regime at execution date and at signal generation date
            trade_open_date = bt.num2date(trade.dtopen)
            entry_regime = self._get_market_regime(trade_open_date)
            decision_date = self._get_previous_trading_day(trade_open_date)
            decision_regime = self._get_market_regime(decision_date) if decision_date else entry_regime

            # Get session context from entry order (for intraday)
            entry_session_phase = None
            entry_session_type = None
            entry_bar_of_session = None
            entry_session_id = None
            if entry_orders:
                first_entry = entry_orders[0]
                entry_session_phase = first_entry.get('session_phase')
                entry_session_type = first_entry.get('session_type')
                entry_bar_of_session = first_entry.get('bar_of_session')
                entry_session_id = first_entry.get('session_id')

            # Get session context from exit order (for intraday)
            exit_bar_of_session = None
            exit_session_id = None
            exit_total_bars = None
            if exit_orders:
                last_exit = exit_orders[-1]
                exit_bar_of_session = last_exit.get('bar_of_session')
                exit_session_id = last_exit.get('session_id')
                exit_total_bars = last_exit.get('total_bars_in_session')

            trade_record = {
                'entry_date': bt.num2date(trade.dtopen),
                'exit_date': bt.num2date(trade.dtclose),
                'entry_time': bt.num2date(trade.dtopen),
                'exit_time': bt.num2date(trade.dtclose),  # Full exit datetime for MFE/MAE
                'direction': 'long' if trade.long else 'short',
                'size': actual_trade_size,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'pnl': calculated_pnl,
                'commission': calculated_commission,
                'pnlcomm': calculated_pnlcomm,
                'return_pct': return_pct,
                'entry_regime': entry_regime,
                'decision_regime': decision_regime,
                'exit_reason': 'strategy_exit',
                # Intraday session context
                'entry_session_phase': entry_session_phase,
                'entry_session_type': entry_session_type,
                'session_id': entry_session_id,
                'entry_bar_of_session': entry_bar_of_session,
                'exit_bar_of_session': exit_bar_of_session,
                'total_bars_in_session': exit_total_bars,
            }

            self.completed_trades.append(trade_record)

            logger.debug(f"Trade recorded: {trade_record['direction']} {actual_trade_size} contracts, "
                       f"Entry: {entry_price:.2f}, Exit: {exit_price:.2f}, "
                       f"PnL: {calculated_pnl:.2f}, Return: {return_pct:.2f}%")

    def _get_market_regime(self, dt: datetime.datetime) -> str:
        """Get market regime for a specific date."""
        if self.regime_data is None or len(self.regime_data) == 0:
            return "unknown"

        target_date = pd.to_datetime(dt.date()) if hasattr(dt, 'date') else pd.to_datetime(dt)
        available_dates = self.regime_data[self.regime_data['trading_date'] <= target_date]

        if available_dates.empty:
            return "unknown"

        last_trading_date = available_dates['trading_date'].max()
        regime_row = available_dates[available_dates['trading_date'] == last_trading_date]

        if regime_row.empty:
            return "unknown"

        regime_col = self.p.regime_column
        if regime_col not in regime_row.columns:
            return "unknown"

        numeric_regime = regime_row[regime_col].iloc[0]

        # Convert numeric regime to string using canonical mapping
        return convert_regime_to_string(numeric_regime)

    def _get_previous_trading_day(self, dt: datetime.datetime) -> Optional[datetime.datetime]:
        """Get the previous trading day strictly before dt using regime_data."""
        if self.regime_data is None or len(self.regime_data) == 0:
            return None
        target_date = pd.to_datetime(dt.date()) if hasattr(dt, 'date') else pd.to_datetime(dt)
        prior_dates = self.regime_data[self.regime_data['trading_date'] < target_date]
        if prior_dates.empty:
            return None
        return prior_dates['trading_date'].max()

    def save_debug_info(self, filepath: str):
        """Save debug information to CSV for analysis."""
        if self.debug_info:
            debug_df = pd.DataFrame(self.debug_info)
            debug_filepath = filepath.replace('.csv', '_debug.csv')
            debug_df.to_csv(debug_filepath, index=False)
            logger.debug(f"Debug information saved to {debug_filepath}")

    def get_analysis(self) -> Dict[str, Any]:
        """Return the analysis with properly formatted trades."""
        if not self.completed_trades:
            return {}

        trades_records = []
        for trade in self.completed_trades:
            record = {
                'entry_date': trade['entry_date'].strftime('%Y-%m-%d'),
                'exit_date': trade['exit_date'].strftime('%Y-%m-%d'),
                'entry_time': trade['entry_time'],
                'exit_time': trade.get('exit_time'),  # Full exit datetime for MFE/MAE
                'direction': trade['direction'],
                'size': trade['size'],
                'entry_price': trade['entry_price'],
                'exit_price': trade['exit_price'],
                'pnl': trade['pnl'],
                'commission': trade['commission'],
                'pnlcomm': trade['pnlcomm'],
                'return_pct': trade['return_pct'],
                'entry_regime': trade['entry_regime'],
                'decision_regime': trade.get('decision_regime'),
                'exit_reason': trade['exit_reason'],
                # Intraday session context fields
                'entry_session_phase': trade.get('entry_session_phase'),
                'entry_session_type': trade.get('entry_session_type'),
                'session_id': trade.get('session_id'),
                'entry_bar_of_session': trade.get('entry_bar_of_session'),
                'exit_bar_of_session': trade.get('exit_bar_of_session'),
                'total_bars_in_session': trade.get('total_bars_in_session'),
            }
            trades_records.append(record)

        return {
            'trades': trades_records,
            'total_trades': len(self.completed_trades),
            'total_pnl': sum(t['pnl'] for t in self.completed_trades),
            'avg_pnl': sum(t['pnl'] for t in self.completed_trades) / len(self.completed_trades) if self.completed_trades else 0
        }


def add_analyzers(
    cerebro: bt.Cerebro,
    contract_multiplier: float,
    use_contract_aware_trades: bool = True,
    market_adapter: Optional['IMarketAdapter'] = None,
    contract_manager: Optional['ContractIndicatorManager'] = None,
    segmentation_data: Optional[pd.DataFrame] = None,
    session_context_provider: Optional[Any] = None,
):
    """
    Add all analyzers to cerebro engine.

    Parameters
    ----------
    cerebro : bt.Cerebro
        Backtrader cerebro engine
    use_contract_aware_trades : bool
        Whether to use contract-aware trade analyzer
    market_adapter : IMarketAdapter, optional
        Market adapter for contract management
    contract_manager : ContractIndicatorManager, optional
        Manager for contract-specific data
    segmentation_data : pd.DataFrame, optional
        Pre-loaded per-bar categorical column for stratifying trade metrics
        (e.g., TRS-paradigm 'market_regime'; other paradigms can use any
        categorical column).
    contract_multiplier : float
        Contract multiplier for PnL calculations
    session_context_provider : ISessionContext, optional
        Session context provider for intraday trading
    """
    # Core analyzers
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='tradeanalyzer')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio_A, _name='sharpe', timeframe=bt.TimeFrame.Days, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='timereturn', timeframe=bt.TimeFrame.Days)

    # Yearly returns
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='yearlyreturn', timeframe=bt.TimeFrame.Years)

    # Additional built-in analyzers
    cerebro.addanalyzer(bt.analyzers.VWR, _name='vwr')
    cerebro.addanalyzer(bt.analyzers.TimeDrawDown, _name='timedrawdown')
    cerebro.addanalyzer(bt.analyzers.PeriodStats, _name='periodstats')
    cerebro.addanalyzer(bt.analyzers.LogReturnsRolling, _name='logrolling', timeframe=bt.TimeFrame.Days)

    # Time-based returns
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='monthlyreturn', timeframe=bt.TimeFrame.Months)
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='weeklyreturn', timeframe=bt.TimeFrame.Weeks)
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='quarterlyreturn', timeframe=bt.TimeFrame.Months, compression=3)

    # Multiple Sharpe ratio timeframes
    cerebro.addanalyzer(bt.analyzers.SharpeRatio_A, _name='sharpe_monthly', timeframe=bt.TimeFrame.Months, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio_A, _name='sharpe_weekly', timeframe=bt.TimeFrame.Weeks, riskfreerate=0.0)

    # Additional metrics
    cerebro.addanalyzer(bt.analyzers.GrossLeverage, _name='leverage')
    cerebro.addanalyzer(bt.analyzers.PositionsValue, _name='positions')
    cerebro.addanalyzer(bt.analyzers.Transactions, _name='transactions')

    # Trade analyzers — pass segmentation_data via the analyzer's params dict.
    # The analyzer's internal param name is ``regime_data`` (Backtrader
    # references params by attribute name on ``self.p``).
    if use_contract_aware_trades:
        cerebro.addanalyzer(
            ContractAwareTradeAnalyzer,
            _name='contract_aware_trades',
            market_adapter=market_adapter,
            contract_manager=contract_manager,
            regime_data=segmentation_data,
            contract_multiplier=contract_multiplier
        )
        logger.debug("Added ContractAwareTradeAnalyzer for corrected PnL calculations")
    else:
        cerebro.addanalyzer(
            TradeList,
            _name='tradelist',
            regime_data=segmentation_data,
            contract_multiplier=contract_multiplier,
            session_context_provider=session_context_provider
        )
        logger.debug("Added TradeList analyzer for standard trade analysis")


def _normalize_trade_analysis(trade_analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize Backtrader TradeAnalyzer output to ensure schema compliance.

    When there are no closed trades, Backtrader only returns:
        {'total': {'total': N, 'open': N}}

    This function ensures all required fields exist with defaults.
    """
    # Default structure for empty/missing fields
    default_pnl = {'total': 0.0, 'average': 0.0, 'max': 0.0}
    default_len = {'total': 0, 'average': 0, 'max': 0, 'min': 0}

    normalized = dict(trade_analysis)

    # Ensure total has 'closed' and 'open' fields
    if 'total' in normalized:
        if 'closed' not in normalized['total']:
            normalized['total']['closed'] = 0
        if 'open' not in normalized['total']:
            normalized['total']['open'] = 0

    # Ensure streak exists
    if 'streak' not in normalized:
        normalized['streak'] = {
            'won': {'current': 0, 'longest': 0},
            'lost': {'current': 0, 'longest': 0}
        }

    # Ensure pnl exists
    if 'pnl' not in normalized:
        normalized['pnl'] = {
            'gross': {'total': 0.0, 'average': 0.0},
            'net': {'total': 0.0, 'average': 0.0}
        }

    # Ensure won exists
    if 'won' not in normalized:
        normalized['won'] = {
            'total': 0,
            'pnl': default_pnl.copy(),
            'len': default_len.copy()
        }

    # Ensure lost exists
    if 'lost' not in normalized:
        normalized['lost'] = {
            'total': 0,
            'pnl': default_pnl.copy(),
            'len': default_len.copy()
        }

    return normalized


def extract_analysis_results(
    strategy: bt.Strategy,
    use_contract_aware_trades: bool = True
) -> Dict[str, Any]:
    """
    Extract results using backtrader's built-in analyzer results.

    Parameters
    ----------
    strategy : bt.Strategy
        Strategy instance after backtest
    use_contract_aware_trades : bool
        Whether contract-aware trades were used

    Returns
    -------
    Dict[str, Any]
        Dictionary containing all analysis results
    """
    analysis: Dict[str, Any] = {}

    def get_analyzer_results(analyzer_name: str) -> Dict[str, Any]:
        return strategy.analyzers.getbyname(analyzer_name).get_analysis()

    # Portfolio Values
    analysis['initial_capital'] = strategy.broker.startingcash
    analysis['final_portfolio_value'] = strategy.broker.getvalue()
    analysis['total_return_pct'] = ((analysis['final_portfolio_value'] - analysis['initial_capital']) /
                                   analysis['initial_capital']) * 100 if analysis['initial_capital'] > 0 else 0

    # Trade Analysis
    trade_analysis = get_analyzer_results('tradeanalyzer')
    analysis.update({
        'total_trades': trade_analysis.get('total', {}).get('total', 0),
        'trades_open': trade_analysis.get('total', {}).get('open', 0),
        'trades_closed': trade_analysis.get('total', {}).get('closed', 0),
        'win_rate_analyzer': (trade_analysis.get('won', {}).get('total', 0) /
                             trade_analysis.get('total', {}).get('closed', 1)) * 100,
        'avg_win_pnl': trade_analysis.get('won', {}).get('pnl', {}).get('average', 0),
        'avg_loss_pnl': trade_analysis.get('lost', {}).get('pnl', {}).get('average', 0),
        'profit_factor_analyzer': _calculate_profit_factor(trade_analysis),
        'trade_analyzer_details': _normalize_trade_analysis(trade_analysis)
    })

    # Drawdown Analysis
    drawdown_analysis = get_analyzer_results('drawdown')
    analysis.update({
        'max_drawdown_pct': drawdown_analysis.get('max', {}).get('drawdown', 0),
        'max_drawdown_len': drawdown_analysis.get('max', {}).get('len', 0)
    })

    # Sharpe Ratio
    sharpe_analysis = get_analyzer_results('sharpe')
    analysis['sharpe_ratio_annual'] = sharpe_analysis.get('sharperatio', 0.0) or 0.0

    # Returns
    returns_analysis = get_analyzer_results('returns')
    analysis['average_annual_return_pct'] = returns_analysis.get('rnorm100', 0.0) or 0.0

    # Annual Returns
    yearly_return_analysis = get_analyzer_results('yearlyreturn')
    annual_returns_dict = {}
    if yearly_return_analysis:
        for date_key, return_value in yearly_return_analysis.items():
            if hasattr(date_key, 'year'):
                year = date_key.year
            elif hasattr(date_key, 'date'):
                year = date_key.date().year
            elif isinstance(date_key, str):
                year = pd.to_datetime(date_key).year
            else:
                year = int(date_key)
            annual_returns_dict[year] = float(return_value) * 100

    analysis['annual_returns'] = annual_returns_dict

    # Calmar Ratio (calculated manually)
    annual_return = analysis['average_annual_return_pct']
    max_drawdown = abs(analysis['max_drawdown_pct'])
    analysis['calmar_ratio'] = _calculate_calmar_ratio(annual_return, max_drawdown)

    # SQN
    sqn_analysis = get_analyzer_results('sqn')
    analysis['sqn'] = sqn_analysis.get('sqn', 0.0) or 0.0

    # VWR
    vwr_analysis = get_analyzer_results('vwr')
    analysis['vwr'] = vwr_analysis.get('vwr', 0.0) or 0.0

    # Time-based Drawdown
    timedrawdown_analysis = get_analyzer_results('timedrawdown')
    analysis['time_drawdown'] = {
        'max_drawdown_duration': timedrawdown_analysis.get('maxdrawdownperiod', 0),
        'drawdown_periods': timedrawdown_analysis.get('drawdownlen', {}),
        'money_down_periods': timedrawdown_analysis.get('moneydownlen', {})
    }

    # Period Statistics
    periodstats_analysis = get_analyzer_results('periodstats')
    analysis['period_stats'] = periodstats_analysis

    # Multiple Sharpe Ratios
    sharpe_monthly_analysis = get_analyzer_results('sharpe_monthly')
    analysis['sharpe_ratio_monthly'] = sharpe_monthly_analysis.get('sharperatio', 0.0) or 0.0

    sharpe_weekly_analysis = get_analyzer_results('sharpe_weekly')
    analysis['sharpe_ratio_weekly'] = sharpe_weekly_analysis.get('sharperatio', 0.0) or 0.0

    # Daily Returns
    timereturn_analysis = get_analyzer_results('timereturn')
    analysis['daily_returns'] = {
        dt.isoformat(): ret for dt, ret in timereturn_analysis.items()
    } if timereturn_analysis else {}

    # Equity Curve
    equity_curve = []
    if timereturn_analysis:
        current_equity = strategy.broker.startingcash

        for dt in sorted(timereturn_analysis.keys()):
            ret = timereturn_analysis[dt]
            current_equity = current_equity * (1 + ret)
            equity_curve.append({
                'date': dt.isoformat(),
                'equity': current_equity
            })

    analysis['equity_curve'] = equity_curve

    # Time-based Returns
    monthly_return_analysis = get_analyzer_results('monthlyreturn')
    analysis['monthly_returns'] = {
        dt.isoformat(): float(ret) * 100 for dt, ret in monthly_return_analysis.items()
    } if monthly_return_analysis else {}

    weekly_return_analysis = get_analyzer_results('weeklyreturn')
    analysis['weekly_returns'] = {
        dt.isoformat(): float(ret) * 100 for dt, ret in weekly_return_analysis.items()
    } if weekly_return_analysis else {}

    quarterly_return_analysis = get_analyzer_results('quarterlyreturn')
    analysis['quarterly_returns'] = {
        dt.isoformat(): float(ret) * 100 for dt, ret in quarterly_return_analysis.items()
    } if quarterly_return_analysis else {}

    # Trade Frequencies
    total_trades = analysis['total_trades']
    num_weeks = len(weekly_return_analysis) if weekly_return_analysis else 0
    num_months = len(monthly_return_analysis) if monthly_return_analysis else 0
    num_years = len(yearly_return_analysis) if yearly_return_analysis else 0

    analysis['weekly_trade_frequency'] = total_trades / num_weeks if num_weeks > 0 else 0.0
    analysis['monthly_trade_frequency'] = total_trades / num_months if num_months > 0 else 0.0
    analysis['annual_trade_frequency'] = total_trades / num_years if num_years > 0 else 0.0

    # Rolling Returns
    logrolling_analysis = get_analyzer_results('logrolling')
    analysis['rolling_log_returns'] = logrolling_analysis

    # Additional Metrics - summarize leverage to avoid bloating results file
    leverage_analysis = get_analyzer_results('leverage')
    if leverage_analysis:
        leverage_values = [v for v in leverage_analysis.values() if v > 0]
        analysis['leverage_metrics'] = {
            'mean': sum(leverage_values) / len(leverage_values) if leverage_values else 0,
            'max': max(leverage_values) if leverage_values else 0,
            'bars_with_position': len(leverage_values),
            'total_bars': len(leverage_analysis)
        }
    else:
        analysis['leverage_metrics'] = {}

    positions_analysis = get_analyzer_results('positions')
    analysis['position_metrics'] = positions_analysis

    transactions_analysis = get_analyzer_results('transactions')
    analysis['transaction_details'] = transactions_analysis

    # Trade Data
    if use_contract_aware_trades:
        contract_aware_analysis = get_analyzer_results('contract_aware_trades')
        analysis['trades'] = contract_aware_analysis
        analysis['contract_corrected_trades'] = True
        logger.debug("Using contract-aware trade analysis for corrected PnL calculations")
    else:
        analysis['trades'] = get_analyzer_results('tradelist') or []
        analysis['contract_corrected_trades'] = False

    return analysis
