"""
Volatility Hedged Theta Engine - Clean Main Algorithm

This is the main algorithm file that orchestrates the theta strategy.
All core logic has been modularized into separate components for maintainability.
"""

from AlgorithmImports import *
import numpy as np
from datetime import datetime, timedelta
from config import *
import math
from QuantConnect.Orders.Fills import ImmediateFillModel
from QuantConnect.Orders import OrderEvent, OrderStatus, OrderDirection

# Import Theta Engine modules
from delta_hedging import DeltaHedger
from black_scholes import BlackScholesCalculator
from exit_rules import ExitRulesManager
from execution_modes import ExecutionModeManager
from position_management import PositionManager


class ClosePriceFillModel(ImmediateFillModel):
    """
    Fills market and limit orders at the current bar's close immediately.
    Intended for EOD backtests on Daily data to simulate 'trade at the close'.
    Prevents MOO conversion by using Limit orders with immediate fills.
    """
    def MarketFill(self, asset, order):
        # Call base to build the fill container
        fill = super().MarketFill(asset, order)

        if asset.Symbol.SecurityType == SecurityType.Equity:
            # Use the just-closed price for equities
            px = asset.Close or asset.Price
            fill.FillPrice = px
        # For options, let the original fill price stand (we'll use BBO mid in P&L calculations)

        # Force full quantity fill
        sign = 1 if order.Direction == OrderDirection.Buy else -1
        fill.FillQuantity = sign * order.AbsoluteQuantity
        fill.Status = OrderStatus.Filled

        return fill

    def LimitFill(self, asset, order):
        # Fill at close for equities, use limit price for options to prevent zero fills
        fill = super().LimitFill(asset, order)

        if asset.Symbol.SecurityType == SecurityType.Equity:
            # Use the just-closed price for equities
            px = asset.Close or asset.Price
        else:
            # OPTIONS: fill exactly at our limit price (prevents Daily option Price==0 from leaking into fills)
            px = float(order.LimitPrice) if order.LimitPrice is not None else 0.0

        fill.FillPrice = px

        # Force full quantity fill
        sign = 1 if order.Direction == OrderDirection.Buy else -1
        fill.FillQuantity = sign * order.AbsoluteQuantity
        fill.Status = OrderStatus.Filled

        return fill


class EodFillModel(ImmediateFillModel):
    """
    Custom fill model for EOD atomic execution.
    During eod_phase, fills limit orders immediately at cached EOD prices.
    Prevents MOO conversion and ensures fills happen at close, not next day.
    """
    def __init__(self, algorithm):
        super().__init__()
        self.algorithm = algorithm

    def LimitFill(self, asset, order):
        # During EOD phase, fill immediately at cached price
        if getattr(self.algorithm, "eod_phase", False):
            cached_price = self.algorithm.eod_price_cache.get(asset.Symbol)
            if cached_price is not None:
                fill = Fill(order)
                fill.FillPrice = cached_price
                fill.Status = OrderStatus.Filled

                # Force full quantity fill
                sign = 1 if order.Direction == OrderDirection.Buy else -1
                fill.FillQuantity = sign * order.AbsoluteQuantity

                return fill

        # Fallback to standard immediate fill
        return super().LimitFill(asset, order)

    def MarketFill(self, asset, order):
        # During EOD phase, market orders also use cached prices
        if getattr(self.algorithm, "eod_phase", False):
            cached_price = self.algorithm.eod_price_cache.get(asset.Symbol)
            if cached_price is not None:
                fill = Fill(order)
                fill.FillPrice = cached_price
                fill.Status = OrderStatus.Filled

                # Force full quantity fill
                sign = 1 if order.Direction == OrderDirection.Buy else -1
                fill.FillQuantity = sign * order.AbsoluteQuantity

                return fill

        # Fallback to standard immediate fill
        return super().MarketFill(asset, order)


class DeltaHedgedThetaEngine(QCAlgorithm):
    """
    Clean, modular implementation of the Volatility Hedged Theta Engine.
    All core logic has been moved to separate modules for maintainability.
    """

    def Initialize(self):
        """
        Initialize the algorithm with modular components.
        """
        # Test period
        self.SetStartDate(*BACKTEST_START_DATE)
        self.SetEndDate(*BACKTEST_END_DATE)
        self.SetCash(INITIAL_CASH)

        # Set QQQ as benchmark for performance comparison
        self.SetBenchmark(BENCHMARK_SYMBOL)

        # Initialize core modules
        self.delta_hedger = DeltaHedger(self)
        self.black_scholes = BlackScholesCalculator(self)
        self.exit_rules = ExitRulesManager(self)
        self.execution_manager = ExecutionModeManager(self)
        self.position_manager = PositionManager(self)

        # Basic configuration
        self.underlying_symbol = UNDERLYING_SYMBOL
        self.positions = {}
        self.debug_mode = DEBUG_MODE

        # EOD phase management for atomic execution
        self.eod_phase = False
        self.eod_price_cache = {}  # {Symbol: price at close}

        # Initialize fill models for EOD mode
        self.close_fill_model = ClosePriceFillModel()
        self.eod_fill_model = EodFillModel(self)

        # Execution mode configuration
        self.hedge_frequency = HEDGE_FREQUENCY

        # Position management configuration
        self.min_buying_power = MIN_BUYING_POWER
        self.min_contracts = MIN_CONTRACTS
        self.max_contracts_per_100k = MAX_CONTRACTS_PER_100K
        self.min_margin_per_position_pct = MIN_MARGIN_PER_POSITION_PCT
        self.margin_safety_factor = MARGIN_SAFETY_FACTOR
        self.estimated_margin_pct = ESTIMATED_MARGIN_PCT
        self.target_margin_use = TARGET_MARGIN_USE
        self.max_positions = MAX_POSITIONS
        self.margin_buffer = MARGIN_BUFFER
        self.max_margin_per_trade_pct = MAX_MARGIN_PER_TRADE_PCT

        # Option filtering configuration
        self.strikes_below = STRIKES_BELOW
        self.strikes_above = STRIKES_ABOVE
        self.min_target_dte = MIN_TARGET_DTE
        self.max_target_dte = MAX_TARGET_DTE
        self.min_moneyness = MIN_MONEYNESS
        self.max_moneyness = MAX_MONEYNESS
        self.min_premium_pct_of_spot = MIN_PREMIUM_PCT_OF_SPOT

        # Exit rules configuration
        self.quick_profit_target = QUICK_PROFIT_TARGET
        self.normal_profit_target = NORMAL_PROFIT_TARGET
        self.let_expire_threshold = LET_EXPIRE_THRESHOLD
        self.stop_loss_multiplier = STOP_LOSS_MULTIPLIER
        self.min_dte = MIN_DTE
        self.quick_profit_min_dte = QUICK_PROFIT_MIN_DTE
        self.time_stop_dte = TIME_STOP_DTE
        self.time_stop_action = TIME_STOP_ACTION

        # Warmup configuration
        self.warmup_days = WARMUP_DAYS
        self.warmup_resolution = WARMUP_RESOLUTION

        # Delta hedging configuration
        self.delta_sizing_mode = DELTA_SIZING_MODE
        self.delta_revert_mode = DELTA_REVERT_MODE
        self.equity_delta_target_points = EQUITY_DELTA_TARGET_POINTS
        self.equity_delta_tol_points = EQUITY_DELTA_TOL_POINTS
        self.futures_delta_target_contracts = FUTURES_DELTA_TARGET_CONTRACTS
        self.futures_delta_tol_contracts = FUTURES_DELTA_TOL_CONTRACTS
        self.delta_target_nav_pct_equity = DELTA_TARGET_NAV_PCT_EQUITY
        self.delta_tol_nav_pct_equity = DELTA_TOL_NAV_PCT_EQUITY
        self.delta_target_nav_pct_future = DELTA_TARGET_NAV_PCT_FUTURE
        self.delta_tol_nav_pct_future = DELTA_TOL_NAV_PCT_FUTURE

        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_win_pnl = 0.0
        self.total_loss_pnl = 0.0

        # Setup execution mode (EOD vs Intraday)
        self.execution_manager.setup_execution_mode()

        self.Log("✅ Volatility Hedged Theta Engine initialized with modular architecture")

    def OnData(self, data):
        """
        Main data handler - delegates to execution manager.
        """
        try:
            if self.execution_manager:
                self.execution_manager.handle_data(data)
            
            # Debug option chain data (already gated by debug_mode)
            if self.debug_mode and data.OptionChains:
                self.Debug(f"Received option chains: {len(data.OptionChains)} chains")
                for kvp in data.OptionChains:
                    chain = kvp.Value
                    self.Debug(f"Chain {kvp.Key}: {len(chain)} contracts")
                    
        except Exception as e:
            self.Debug(f"OnData error: {e}")

    def OnOrderEvent(self, order_event):
        """
        Order event handler - delegates to execution manager.
        """
        if self.execution_manager:
            self.execution_manager.handle_order_events(order_event)

    def _build_eod_snapshot(self):
        """
        Build a static snapshot of all prices at EOD for atomic execution.
        Returns dict with prices for all symbols we might need to trade.
        """
        snapshot = {'prices': {}}

        try:
            # Underlying price
            if self.underlying_symbol in self.Securities:
                underlying_price = self.Securities[self.underlying_symbol].Close
                if underlying_price > 0:
                    snapshot['prices'][self.underlying_symbol] = underlying_price

            # Option prices from current chain
            if hasattr(self, '_current_option_chain') and self._current_option_chain:
                for contract in self._current_option_chain:
                    if contract.BidPrice > 0 and contract.AskPrice > 0:
                        mid_price = (contract.BidPrice + contract.AskPrice) / 2
                        snapshot['prices'][contract.Symbol] = mid_price

        except Exception as e:
            if self.debug_mode:
                self.Debug(f"Error building EOD snapshot: {e}")

        return snapshot

    def _run_atomic_eod_execution(self):
        """
        Atomic EOD execution: build snapshot, run all operations, single hedge.
        """
        try:
            # Enter EOD phase
            self.eod_phase = True

            # Build static price snapshot
            snapshot = self._build_eod_snapshot()
            self.eod_price_cache = snapshot['prices']

            # Use EOD fill model during this phase
            if not self.intraday_hedging:
                self.underlying.SetFillModel(self.eod_fill_model)
                self.option.SetFillModel(self.eod_fill_model)

            # Run EOD operations atomically
            self._run_eod_closes(snapshot)
            self._run_eod_entries(snapshot)
            self._run_eod_single_hedge(snapshot)

            # Exit EOD phase
            self.eod_phase = False

            if self.debug_mode:
                self.Debug(f"EOD atomic execution completed with {len(snapshot['prices'])} cached prices")

        except Exception as e:
            self.eod_phase = False  # Ensure we exit phase on error
            if self.debug_mode:
                self.Debug(f"EOD atomic execution error: {e}")

    def _run_eod_closes(self, snapshot):
        """Run exit conditions and position closes using static snapshot."""
        try:
            if self.exit_rules:
                self.exit_rules.check_exit_conditions()
        except Exception as e:
            if self.debug_mode:
                self.Debug(f"EOD closes error: {e}")

    def _run_eod_entries(self, snapshot):
        """Run new position entries using static snapshot."""
        try:
            if self.execution_manager and hasattr(self.execution_manager, '_process_eod_option_chain_data'):
                # Get current option chain data
                if hasattr(self, '_current_option_chain') and self._current_option_chain:
                    candidates = self.position_manager.find_tradable_options(self._current_option_chain)

                    if candidates:
                        best_option = self.position_manager.select_best_option(candidates)
                        if best_option:
                            if self.debug_mode:
                                self.Debug(f"EOD entry attempt: {best_option['symbol']}")
                            success = self.position_manager.try_enter_position(best_option)
                            if success:
                                self.position_manager.track_entry_attempt(True)
                            else:
                                self.position_manager.track_entry_attempt(False)
                                self.position_manager.update_adaptive_constraints()
        except Exception as e:
            if self.debug_mode:
                self.Debug(f"EOD entries error: {e}")

    def _run_eod_single_hedge(self, snapshot):
        """Run single hedge pass using portfolio delta after all position changes."""
        try:
            if self.delta_hedger:
                self.delta_hedger.execute_delta_hedge_universal()
        except Exception as e:
            if self.debug_mode:
                self.Debug(f"EOD single hedge error: {e}")

    def OnEndOfAlgorithm(self):
        """
        Final cleanup and reporting.
        """
        self.Log("=== STRATEGY COMPLETE ===")
        self.Log(f"Total Positions Tracked: {len(self.positions)}")

    def GetOptionEodPrice(self, symbol):
        """
        Get EOD option price using cached BBO mid from current chain.
        PERFORMANCE: Uses O(1) cache lookup instead of O(n) linear search.
        """
        try:
            # Use cached prices for O(1) lookup instead of scanning entire chain
            if hasattr(self, '_eod_price_cache') and symbol in self._eod_price_cache:
                return self._eod_price_cache[symbol]

            # Fallback to linear search if cache not available (shouldn't happen)
            if hasattr(self, '_current_option_chain') and self._current_option_chain:
                for contract in self._current_option_chain:
                    if contract.Symbol == symbol:
                        if contract.BidPrice > 0 and contract.AskPrice > 0:
                            price = (contract.BidPrice + contract.AskPrice) / 2
                            # Cache this lookup for future use
                            if not hasattr(self, '_eod_price_cache'):
                                self._eod_price_cache = {}
                            self._eod_price_cache[symbol] = price
                            return price
                        break
            return 0.0
        except Exception as e:
            self.Debug(f"Error getting EOD price for {symbol}: {e}")
            return 0.0

    def EstimatePutDelta(self, strike, underlying_price, expiration):
        """
        Estimate put delta using Black-Scholes approximation.
        """
        try:
            if self.black_scholes:
                return self.black_scholes.estimate_put_delta(strike, underlying_price, expiration)
            else:
                # Simple approximation: delta roughly proportional to moneyness
                moneyness = strike / underlying_price
                if moneyness > 1.0:  # ITM put
                    return min(-0.5, -0.3 * moneyness)
                else:  # OTM put
                    return max(-0.05, -0.3 * moneyness)
        except Exception as e:
            self.Debug(f"Error estimating put delta: {e}")
            return -0.25  # Default delta for short puts