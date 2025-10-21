"""
Volatility Hedged Theta Engine - Clean Main Algorithm

This is the main algorithm file that orchestrates the theta strategy.
All core logic has been modularized into separate components for maintainability.
"""

from AlgorithmImports import *
import numpy as np
import os
import json
from datetime import datetime, timedelta

# Additional QuantConnect imports for better IDE support
from QuantConnect.Algorithm import QCAlgorithm
from QuantConnect.Data import Slice
from QuantConnect.Indicators import *
from QuantConnect.Orders import *
from QuantConnect.Securities import *
from QuantConnect.Data.Market import *
from QuantConnect.Data.UniverseSelection import *
from QuantConnect.Algorithm.Framework import *
from QuantConnect.Algorithm.Framework.Alphas import *
from QuantConnect.Algorithm.Framework.Portfolio import *
from QuantConnect.Algorithm.Framework.Risk import *
from QuantConnect.Algorithm.Framework.Selection import *
from phase_executor import PhaseExecutor
from config import (
    # Core settings
    BACKTEST_START_DATE, BACKTEST_END_DATE, INITIAL_CASH, UNDERLYING_SYMBOL,
    BENCHMARK_SYMBOL, DEBUG_MODE, PHASE_SPLIT_ENABLED, PHASE_0_TIME, PHASE_1_TIME, PHASE_2_TIME,

    # Option filtering
    STRIKES_BELOW, STRIKES_ABOVE, MIN_TARGET_DTE, MAX_TARGET_DTE,
    MIN_DELTA, MAX_DELTA, MIN_PREMIUM_PCT_OF_SPOT,

    # Position sizing
    MIN_BUYING_POWER, MIN_CONTRACTS, MAX_CONTRACTS_PER_100K,
    MIN_MARGIN_PER_POSITION_PCT, MARGIN_SAFETY_FACTOR, ESTIMATED_MARGIN_PCT,
    TARGET_MARGIN_USE, MAX_POSITIONS, MARGIN_BUFFER, MAX_MARGIN_PER_TRADE_PCT,
    PRE_ORDER_MARGIN_SAFETY,

    # Dynamic position sizing
    DYNAMIC_SIZING_ENABLED, LOW_MARGIN_THRESHOLD, POSITION_SCALING_FACTOR,
    MAX_SCALED_MARGIN_PER_TRADE_PCT, SCALING_GRADUAL_ENABLED,
    SCALING_MIN_THRESHOLD, SCALING_MAX_THRESHOLD,

    # Performance optimization
    GREEKS_CACHE_CLEANUP_DAYS, POSITION_CLEANUP_DAYS, GREEKS_SNAPSHOT_INTERVAL_MINUTES,
    DEBUG_LOGGING_ENABLED, MEMORY_MONITORING_ENABLED,

    # Intraday risk monitoring
    INTRADAY_RISK_MONITORING_ENABLED, RISK_CHECK_INTERVAL_MINUTES, MARGIN_CALL_THRESHOLD,
    PORTFOLIO_LOSS_THRESHOLD, EMERGENCY_EXIT_THRESHOLD, RISK_ALERT_COOLDOWN_MINUTES,

    # Position diversification
    DTE_BUCKETS, DTE_FALLBACK_ENABLED, MAX_POSITIONS_PER_EXPIRY, MIN_STRIKE_SPACING_PCT, EXPIRY_COOLDOWN_DAYS,

    # Delta hedging
    DELTA_REVERT_MODE, DELTA_BAND_MODE,
    DELTA_TARGET_TRADE_PCT_EQUITY, DELTA_TOL_TRADE_PCT_EQUITY,
    DELTA_TARGET_TRADE_PCT_FUTURE, DELTA_TOL_TRADE_PCT_FUTURE,
    DELTA_TARGET_NAV_PCT_EQUITY, DELTA_TOL_NAV_PCT_EQUITY,
    DELTA_TARGET_NAV_PCT_FUTURE, DELTA_TOL_NAV_PCT_FUTURE,
    HEDGE_COOLDOWN_SECONDS, HEDGE_CLOSE_PROXIMITY_SECONDS,

    # Black-Scholes
    BS_DEFAULT_ATM_IV, BS_DEFAULT_RISK_FREE_RATE,

    # Exit rules
    QUICK_PROFIT_TARGET, NORMAL_PROFIT_TARGET, LET_EXPIRE_THRESHOLD,
    STOP_LOSS_MULTIPLIER, MIN_DTE, QUICK_PROFIT_MIN_DTE, TIME_STOP_DTE, TIME_STOP_ACTION,

    # Margin estimation parameters
    MARGIN_ESTIMATE_1_UNDERLYING_PCT, MARGIN_ESTIMATE_2_UNDERLYING_PCT, MARGIN_MINIMUM_FLOOR,

    # Filter relaxation parameters
    FILTER_RELAXATION_THRESHOLD_DAYS, PREMIUM_RELAXATION_FACTOR,
    DTE_RELAXATION_DECREMENT, MIN_DTE_FLOOR,

    # Delta approximation parameters
    DEFAULT_DELTA_SHORT_PUT, ITM_DELTA_MULTIPLIER, ITM_DELTA_MAX, OTM_DELTA_MIN,

    # Schedule
    MARKET_CLOSE_MINUTES,

    # Order housekeeping
    CANCEL_UNFILLED_AT_CLOSE, CANCEL_AT_CLOSE_MINUTES,

    # Order pricing
    ENTRY_MAX_SPREAD_PCT, ENTRY_NUDGE_FRACTION, ENTRY_ABS_SPREAD_MIN,
    EXIT_MAX_SPREAD_PCT, EXIT_NUDGE_FRACTION,
    QUOTE_RETRY_LIMIT, SPREAD_RETRY_LIMIT, NONTRADABLE_RETRY_LIMIT,

    # Fill model
    USE_MID_HAIRCUT_FILL_MODEL, MID_HAIRCUT_FRACTION, MAX_SPREAD_PCT,
    FILL_ON_SUBMISSION_BAR, REQUIRE_BID_ASK, FORCE_LIMIT_FILLS, FORCE_EXACT_LIMIT,

    # Order tagging
    ENTRY_TAG, HEDGE_TAG, EXIT_TAG,

    # Other
    WARMUP_DAYS
)
import math
from QuantConnect.Orders import OrderEvent, OrderStatus

# Import Theta Engine modules
from delta_hedging import DeltaHedger
from exit_rules import ExitRulesManager
from position_management import PositionManager
from order_manager import OrderManager
from risk_manager import RiskManager
from analytics import Analytics
from strategy_base import StrategyContext
import importlib
from fillmodels import MidHaircutFillModel
from greeks_provider import GreeksProvider
from options_data_manager import OptionsDataManager
from intraday_risk_monitor import IntradayRiskMonitor
from market_data_manager import MarketDataManager
from order_event_handler import OrderEventHandler
from data_processor import DataProcessor


class DeltaHedgedThetaEngine(QCAlgorithm):
    """
    Clean, modular implementation of the Volatility Hedged Theta Engine.
    All core logic has been moved to separate modules for maintainability.
    """

    def Initialize(self):
        """
        Initialize the algorithm with modular components.
        """
        # NOTE: SecurityChanges logging is QuantConnect's built-in system logging
        # It cannot be suppressed from algorithm code, but you can filter it out when viewing logs
        # Use this filter: grep -v "SecurityChanges" your_log_file.txt
        # Or in QuantConnect dashboard: exclude lines containing "SecurityChanges"

        # Test period
        self.SetStartDate(*BACKTEST_START_DATE)
        self.SetEndDate(*BACKTEST_END_DATE)
        self.SetCash(INITIAL_CASH)

        # Set QQQ as benchmark for performance comparison
        self.SetBenchmark(BENCHMARK_SYMBOL)

        # Initialize core modules
        self.delta_hedger = DeltaHedger(self)
        self.greeks_provider = GreeksProvider(self)
        self.options_data = OptionsDataManager(self)
        self.market_data = MarketDataManager(self)  # Centralized market data access
        self.order_handler = OrderEventHandler(self)  # Order event processing
        self.data_processor = DataProcessor(self)  # OnData processing
        self.exit_rules = ExitRulesManager(self)
        self.position_manager = PositionManager(self)
        self.order_manager = OrderManager(self)
        self.risk_manager = RiskManager(self)
        self.risk_manager.set_exit_rules_manager(self.exit_rules)
        self.analytics = Analytics(self)
        self.intraday_risk_monitor = IntradayRiskMonitor(self)
        self.phase_executor = PhaseExecutor(self)
        # Dynamic strategy load from config.json (field: "strategy_module")
        # Prefer QC algorithm parameter over file I/O (cloud-safe). Expect base filename without package, e.g. 'theta_engine' or 'ssvi_strategy'
        try:
            param_mod = self.GetParameter("strategy_module")
            module_basename = param_mod if param_mod else 'theta_engine'
        except Exception:
            module_basename = 'theta_engine'

        # Load strategy module from file path to avoid package name issues with hyphens
        try:
            import importlib.util
            strategy_path = os.path.join(os.path.dirname(__file__), f"{module_basename}.py")
            if not os.path.exists(strategy_path):
                # Fallback to default theta_engine
                strategy_path = os.path.join(os.path.dirname(__file__), "theta_engine.py")
            spec = importlib.util.spec_from_file_location(module_basename, strategy_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore
            StrategyCls = getattr(mod, 'ThetaEngineStrategy', None) or getattr(mod, 'Strategy', None)
            self.strategy = StrategyCls(self) if StrategyCls else None
        except Exception as e:
            if self.debug_mode:
                self.Debug(f"Strategy load error for file {module_basename}.py: {e}")
            self.strategy = None

        # Order tagging constants for selective cancellation
        self.ENTRY_TAG = ENTRY_TAG
        self.HEDGE_TAG = HEDGE_TAG
        self.EXIT_TAG = EXIT_TAG

        # Basic configuration
        self.underlying_symbol = UNDERLYING_SYMBOL
        self.positions = {}
        self.pending_exit_hedges = []  # Track exit orders that need delta hedging
        self.debug_mode = DEBUG_MODE
        # Cache recent implied volatilities per option symbol
        self.iv_cache = {}
        # Cache recent QC Greeks per option symbol: {symbol: ((delta,gamma,theta), timestamp)}
        self.greeks_cache = {}

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
        self.pre_order_margin_safety = PRE_ORDER_MARGIN_SAFETY

        # Dynamic position sizing configuration
        self.dynamic_sizing_enabled = DYNAMIC_SIZING_ENABLED
        self.low_margin_threshold = LOW_MARGIN_THRESHOLD
        self.position_scaling_factor = POSITION_SCALING_FACTOR
        self.max_scaled_margin_per_trade_pct = MAX_SCALED_MARGIN_PER_TRADE_PCT
        self.scaling_gradual_enabled = SCALING_GRADUAL_ENABLED
        self.scaling_min_threshold = SCALING_MIN_THRESHOLD
        self.scaling_max_threshold = SCALING_MAX_THRESHOLD

        # Performance optimization configuration
        self.greeks_cache_cleanup_days = GREEKS_CACHE_CLEANUP_DAYS
        self.position_cleanup_days = POSITION_CLEANUP_DAYS
        self.debug_logging_enabled = DEBUG_LOGGING_ENABLED
        self.memory_monitoring_enabled = MEMORY_MONITORING_ENABLED
        

        # Option filtering configuration
        self.strikes_below = STRIKES_BELOW
        self.strikes_above = STRIKES_ABOVE
        self.min_target_dte = MIN_TARGET_DTE
        self.max_target_dte = MAX_TARGET_DTE
        self.min_delta = MIN_DELTA
        self.max_delta = MAX_DELTA
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

        # Order pricing configuration
        self.entry_max_spread_pct = ENTRY_MAX_SPREAD_PCT
        self.entry_abs_spread_min = ENTRY_ABS_SPREAD_MIN
        self.entry_nudge_fraction = ENTRY_NUDGE_FRACTION
        self.exit_max_spread_pct = EXIT_MAX_SPREAD_PCT
        self.exit_nudge_fraction = EXIT_NUDGE_FRACTION
        self.quote_retry_limit = QUOTE_RETRY_LIMIT
        self.spread_retry_limit = SPREAD_RETRY_LIMIT
        self.nontradable_retry_limit = NONTRADABLE_RETRY_LIMIT

        # Black-Scholes configuration
        self.bs_default_atm_iv = BS_DEFAULT_ATM_IV
        self.bs_default_risk_free_rate = BS_DEFAULT_RISK_FREE_RATE

        # Fill behavior configuration
        self.fill_on_submission_bar = FILL_ON_SUBMISSION_BAR
        self.require_bid_ask = REQUIRE_BID_ASK
        self.force_limit_fills = FORCE_LIMIT_FILLS
        self.mid_haircut_fraction = MID_HAIRCUT_FRACTION

        # Delta hedging configuration
        self.delta_revert_mode = DELTA_REVERT_MODE
        self.delta_band_mode = DELTA_BAND_MODE
        self.delta_target_trade_pct_equity = DELTA_TARGET_TRADE_PCT_EQUITY
        self.delta_tol_trade_pct_equity = DELTA_TOL_TRADE_PCT_EQUITY
        self.delta_target_trade_pct_future = DELTA_TARGET_TRADE_PCT_FUTURE
        self.delta_tol_trade_pct_future = DELTA_TOL_TRADE_PCT_FUTURE
        self.delta_target_nav_pct_equity = DELTA_TARGET_NAV_PCT_EQUITY
        self.delta_tol_nav_pct_equity = DELTA_TOL_NAV_PCT_EQUITY
        self.delta_target_nav_pct_future = DELTA_TARGET_NAV_PCT_FUTURE
        self.delta_tol_nav_pct_future = DELTA_TOL_NAV_PCT_FUTURE

        # Hedge cooldown to prevent over-hedging bursts
        self.last_hedge_time = None
        self.hedge_cooldown_seconds = HEDGE_COOLDOWN_SECONDS  # Configurable cooldown between hedges
        self.last_hedge_minute = None  # Track last hedge minute to prevent multiple per minute

        # Position diversification configuration
        self.dte_buckets = DTE_BUCKETS
        self.dte_fallback_enabled = DTE_FALLBACK_ENABLED
        self.max_positions_per_expiry = MAX_POSITIONS_PER_EXPIRY
        self.min_strike_spacing_pct = MIN_STRIKE_SPACING_PCT
        self.expiry_cooldown_days = EXPIRY_COOLDOWN_DAYS
        # Delta band filter removed - using moneyness filter instead

        # NOTE: Orchestrator state removed - hedging now controlled by daily flow
        
        # Cache for new trades executed today (prevents double-hedging)
        self.todays_new_trades = []
        # Cache dollar deltas of new trades for universal hedge to account for
        self.todays_new_trade_deltas = []

        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_win_pnl = 0.0
        self.total_loss_pnl = 0.0

        # Subscribe to minute-resolution data for underlying and options
        self.underlying = self.AddEquity(self.underlying_symbol, Resolution.Minute)
        self.option = self.AddOption(self.underlying_symbol, Resolution.Minute)
        # Filter option universe
        self.option.SetFilter(lambda u: u.Strikes(-self.strikes_below, self.strikes_above)
                                        .Expiration(self.min_target_dte, self.max_target_dte)
                                        .PutsOnly())
        # Enable pricing model that supports American options Greeks
        self.option.PriceModel = OptionPriceModels.CrankNicolsonFD()
        
        # Disable automatic option assignment during testing (QuantConnect only)
        # This prevents automatic assignment of ITM options at expiration
        # Useful for testing and development to maintain control over position exits
        # Note: Only available in newer QuantConnect versions
        if hasattr(self, 'SetOptionAssignmentModel'):
            try:
                self.SetOptionAssignmentModel(OptionAssignmentModel.DoNotAssign())
                if self.debug_mode:
                    self.Log("Option assignment model set to DoNotAssign() for testing")
            except Exception as e:
                if self.debug_mode:
                    self.Debug(f"Could not set option assignment model: {e}")
        else:
            if self.debug_mode:
                self.Debug("SetOptionAssignmentModel not available in this QuantConnect version (skipping)")

        # Set up MidHaircutFillModel for realistic option fills
        if USE_MID_HAIRCUT_FILL_MODEL:
            from QuantConnect.Orders.Slippage import NullSlippageModel
            # Use NullSlippageModel to avoid double-counting slippage (fill model already includes it)
            self.Securities[self.option.Symbol].SetSlippageModel(NullSlippageModel.Instance)
            self.Securities[self.option.Symbol].SetFillModel(
                MidHaircutFillModel(
                    self,
                    haircut=MID_HAIRCUT_FRACTION,
                    max_spread_pct=MAX_SPREAD_PCT,
                    force_fills=FORCE_LIMIT_FILLS,
                    clamp_to_book=not FORCE_EXACT_LIMIT,
                    force_exact_limit=FORCE_EXACT_LIMIT,
                )
            )
            # Ensure any subsequently added option contracts inherit the same models
            def _init_models(sec):
                try:
                    if sec.Symbol.SecurityType == SecurityType.Option:
                        sec.SetSlippageModel(NullSlippageModel.Instance)
                        sec.SetFillModel(
                            MidHaircutFillModel(
                                self,
                                haircut=MID_HAIRCUT_FRACTION,
                                max_spread_pct=MAX_SPREAD_PCT,
                                force_fills=FORCE_LIMIT_FILLS,
                                clamp_to_book=not FORCE_EXACT_LIMIT,
                                force_exact_limit=FORCE_EXACT_LIMIT,
                            )
                        )
                except Exception as _e:
                    if self.debug_mode:
                        self.Debug(f"SecurityInitializer model set error for {sec.Symbol}: {_e}")
            self.SetSecurityInitializer(_init_models)
            if self.debug_mode:
                self.Log(f"Enabled MidHaircutFillModel: haircut={MID_HAIRCUT_FRACTION}, max_spread={MAX_SPREAD_PCT}")

        # Warm up minute data
        self.SetWarmUp(self.warmup_days, Resolution.Minute)

        # Configure Greeks snapshot interval (minutes)
        self.greeks_snapshot_minutes = GREEKS_SNAPSHOT_INTERVAL_MINUTES

        # Intraday hedging mode for market-order hedges
        self.intraday_hedging = True

        # Schedule Phase 0: Exits (15:45)
        if PHASE_SPLIT_ENABLED:
            self.Schedule.On(
                self.DateRules.EveryDay(self.underlying_symbol),
                self.TimeRules.At(15, 45),  # 15:45 for Phase 0 (exits)
                self.ExecuteStrategy
            )

            # Schedule Phase 1: New trades + per-trade hedges (15:50)
            self.Schedule.On(
                self.DateRules.EveryDay(self.underlying_symbol),
                self.TimeRules.At(15, 50),  # 15:50 for Phase 1 (new trades)
                self.ExecuteStrategy
            )

            # Schedule Phase 2: Portfolio rebalancing (15:55)
            self.Schedule.On(
                self.DateRules.EveryDay(self.underlying_symbol),
                self.TimeRules.At(15, 55),  # 15:55 for Phase 2 (rebalancing)
                self.ExecuteStrategy
            )
        else:
            # Original single execution if timing split is disabled
            self.Schedule.On(
                self.DateRules.EveryDay(self.underlying_symbol),
                self.TimeRules.BeforeMarketClose(self.underlying_symbol, MARKET_CLOSE_MINUTES),
                self.ExecuteStrategy
            )

        # Schedule cancel sweep for unfilled entry orders closer to market close
        if CANCEL_UNFILLED_AT_CLOSE:
            self.Schedule.On(
                self.DateRules.EveryDay(self.underlying_symbol),
                self.TimeRules.BeforeMarketClose(self.underlying_symbol, CANCEL_AT_CLOSE_MINUTES),
                self.CancelStaleEntryOrders
            )

        # Schedule EOD Greeks logging at market close
        self.Schedule.On(
            self.DateRules.EveryDay(self.underlying_symbol),
            self.TimeRules.AfterMarketClose(self.underlying_symbol, 0),  # At market close
            self.LogEODPosition
        )

        # Schedule daily cleanup and cache reset
        self.Schedule.On(
            self.DateRules.EveryDay(self.underlying_symbol),
            self.TimeRules.AfterMarketClose(self.underlying_symbol, 1),  # 1 minute after close
            self.daily_cleanup
        )
        
        # Weekly aggressive cleanup on Sundays
        self.Schedule.On(
            self.DateRules.Every(DayOfWeek.Sunday),
            self.TimeRules.AfterMarketClose(self.underlying_symbol, 1),
            self.weekly_aggressive_cleanup
        )

        self.Log("Volatility Hedged Theta Engine initialized with modular architecture")

    def OnData(self, data):
        """
        Main data handler - delegates to data processor.
        """
        self.data_processor.process_data(data)

        # NOTE: Orchestrator logic removed - hedging now controlled by daily ExecuteStrategy flow

    def OnOrderEvent(self, order_event):
        """
        Order event handler - delegates to execution manager.
        """
        # Update position tracking on fills
        if order_event.Status == OrderStatus.Filled:
            try:
                symbol = order_event.Symbol
                fill_price = order_event.FillPrice
                fill_quantity = order_event.FillQuantity

                # Find and update position - be specific about matching
                updated = False
                for pos_id, position in list(self.positions.items()):
                    # Match on both symbol AND position type to avoid cross-contamination
                    symbol_match = (position['symbol'] == symbol)
                    is_hedge_position = pos_id.startswith('hedge_')
                    is_equity_order = (symbol.SecurityType == SecurityType.Equity)
                    is_option_order = (symbol.SecurityType == SecurityType.Option)

                    # Hedge positions should only match equity orders, option positions should only match option orders
                    if symbol_match and (
                        (is_hedge_position and is_equity_order) or
                        (not is_hedge_position and is_option_order)
                    ):
                        current_qty = position['quantity']

                        # FIX: Detect zero crossing ONLY when the resulting position flips sign
                        total_quantity = current_qty + fill_quantity
                        zero_crossing = (
                            (current_qty > 0 and total_quantity < 0) or
                            (current_qty < 0 and total_quantity > 0)
                        )

                        # For hedges, just update quantity - no need to track entry prices
                        position['quantity'] = total_quantity
                        
                        # Only track entry prices for options (not hedges)
                        if not is_hedge_position and current_qty == 0:
                            # Starting from zero - simple case for options
                            position['entry_price'] = fill_price
                        elif not is_hedge_position and zero_crossing:
                            # CROSSING THROUGH ZERO: Reset basis to the new side and keep the residual qty
                            # This prevents nonsensical average prices when flipping sides
                            if self.debug_mode:
                                old_price = position['entry_price']
                                self.Debug(f"Zero crossing detected: {current_qty} -> {total_quantity} | "
                                          f"Resetting basis ${old_price:.2f} -> ${fill_price:.2f}")
                            position['entry_price'] = fill_price
                        elif not is_hedge_position:
                            # Same-side add or partial reduction without crossing for options
                            if current_qty * fill_quantity > 0:
                                # Same-side addition: update weighted average entry
                                if total_quantity != 0:
                                    position['entry_price'] = (
                                        (position['entry_price'] * current_qty) +
                                        (fill_price * fill_quantity)
                                    ) / total_quantity
                            # For partial reduction without crossing, keep entry price unchanged

                        if symbol.SecurityType == SecurityType.Option and fill_quantity < 0:
                            # Store credit as positive cash received (for short puts)
                            credit = fill_price * abs(fill_quantity) * 100
                            position['credit_received'] = position.get('credit_received', 0) + credit

                        # Only show entry price for options, not hedges
                        if is_hedge_position:
                            self.Log(f"POSITION FILLED: {pos_id} | Quantity: {position['quantity']} | "
                                     f"Credit: ${position.get('credit_received', 0):.0f}")
                        else:
                            self.Log(f"POSITION FILLED: {pos_id} | Quantity: {position['quantity']} | "
                                     f"Entry: ${position['entry_price']:.2f} | "
                                     f"Credit: ${position.get('credit_received', 0):.0f}")

                        if abs(position['quantity']) < 1e-6:
                            if self.debug_mode:
                                self.Debug(f"POSITION CLOSED: Removing {pos_id}")
                            # Guard against concurrent deletion
                            if pos_id in self.positions:
                                del self.positions[pos_id]

                        if self.debug_mode:
                            total_quantity = current_qty + fill_quantity
                            self.Debug(f"POSITION: {symbol} qty {current_qty} -> {total_quantity} ({'hedge' if is_hedge_position else 'option'})")
                        updated = True
                        break


                # Track equity hedge fills if not matched
                if not updated and abs(fill_quantity) > 0 and symbol.SecurityType == SecurityType.Equity:
                    # Use order tag to create unique hedge position ID for per-trade hedging
                    order_tag = order_event.OrderId  # Get the order tag from the order event
                    if hasattr(order_event, 'Order') and hasattr(order_event.Order, 'Tag') and order_event.Order.Tag:
                        tag_parts = order_event.Order.Tag.split('_')
                        if len(tag_parts) >= 2 and tag_parts[0] == 'HEDGE':
                            # Extract option symbol from tag for unique hedge position ID
                            option_symbol_part = '_'.join(tag_parts[1:])  # Everything after 'HEDGE_'
                            hedge_id = f"hedge_{symbol}_{option_symbol_part}_{self.Time.strftime('%Y%m%d_%H%M%S')}"
                        else:
                            # Fallback to original logic for non-per-trade hedges
                            hedge_id = f"hedge_{symbol}_{self.Time.strftime('%Y%m%d_%H%M%S')}"
                    else:
                        # Fallback to original logic if no tag available
                        hedge_id = f"hedge_{symbol}_{self.Time.strftime('%Y%m%d_%H%M%S')}"
                    self.positions[hedge_id] = {
                        'symbol': symbol,
                        'quantity': fill_quantity,
                        'entry_price': 0.0,  # Not used for hedges, but needed for compatibility
                        'credit_received': 0.0,
                        'expiration': None,
                        'strike': None,
                        'timestamp': self.Time,
                        'target_contracts': None,
                        'is_hedge': True
                    }
                    if self.debug_mode:
                        self.Debug(f"Tracked hedge fill: {hedge_id} | Qty: {fill_quantity} | Price: ${fill_price:.2f}")

                    # NOTE: Orchestrator logic removed - hedging controlled by daily flow
            except Exception as e:
                if self.debug_mode:
                    self.Debug(f"OnOrderEvent update error: {e}")

            # Consolidated option fill logging - only for fills, not position updates
            if (hasattr(order_event, 'Symbol') and
                order_event.Symbol.SecurityType == SecurityType.Option and
                order_event.FillQuantity != 0 and
                order_event.Status == OrderStatus.Filled and
                self.debug_mode):
                # Single consolidated log entry for option fills
                self._log_consolidated_option_fill(order_event)

    def _log_consolidated_option_fill(self, order_event):
        """
        Single consolidated log entry for option fills with all essential information.
        Replaces multiple redundant log entries with one comprehensive line.
        """
        try:
            symbol = order_event.Symbol
            current_time = self.Time.strftime("%H:%M:%S")
            
            # Log OnData timing for fills
            self.Debug(f"OnData FILL: Processing fill at {current_time} for {symbol}")
            
            # Check if we have current option chain data for this symbol
            option_chain_bid = None
            option_chain_ask = None
            if hasattr(self, 'current_chain') and self.current_chain:
                for contract in self.current_chain:
                    if contract.Symbol == symbol:
                        option_chain_bid = contract.BidPrice if contract.BidPrice and contract.BidPrice > 0 else None
                        option_chain_ask = contract.AskPrice if contract.AskPrice and contract.AskPrice > 0 else None
                        break
            
            # Log option chain data if available
            if option_chain_bid and option_chain_ask:
                chain_spread = option_chain_ask - option_chain_bid
                chain_spread_pct = (chain_spread / ((option_chain_bid + option_chain_ask) / 2)) * 100 if (option_chain_bid + option_chain_ask) / 2 > 0 else 0
                self.Debug(f"OnData CHAIN: {symbol} bid/ask from option chain: ${option_chain_bid:.2f}/${option_chain_ask:.2f} (${chain_spread:.2f}, {chain_spread_pct:.1f}%)")
            else:
                self.Debug(f"OnData CHAIN: {symbol} no option chain data available")
            
            # Use centralized market data manager for consistent data source
            bid, ask, source = self.market_data.get_bid_ask(symbol)
            
            direction = "SELL" if order_event.FillQuantity < 0 else "BUY"
            
            if bid and ask:
                spread = ask - bid
                spread_pct = (spread / ((bid + ask) / 2)) * 100 if (bid + ask) / 2 > 0 else 0
                source_label = f" [{source}]" if source != "OPTION_CHAIN" else ""
                
                # Single comprehensive log entry with data source info
                self.Debug(f"OPTION FILL: {symbol} {direction} {abs(order_event.FillQuantity)} @ ${order_event.FillPrice:.2f} | Market: ${bid:.2f}/${ask:.2f} (${spread:.2f}, {spread_pct:.1f}%){source_label}")
            else:
                self.Debug(f"OPTION FILL: {symbol} {direction} {abs(order_event.FillQuantity)} @ ${order_event.FillPrice:.2f} | Market: No quotes")
                
        except Exception as e:
            direction = "SELL" if order_event.FillQuantity < 0 else "BUY"
            self.Debug(f"OPTION FILL: {order_event.Symbol} {direction} {abs(order_event.FillQuantity)} @ ${order_event.FillPrice:.2f} | Market: Error getting quotes")

    def _log_option_fill_analysis(self, order_event):
        """
        Log detailed fill analysis for option trades, similar to fill model logging.
        Provides comprehensive execution quality analysis for all option trades.
        """
        try:
            symbol = order_event.Symbol
            security = self.Securities[symbol]
            
            # Get current market data
            bid = security.BidPrice if security.BidPrice > 0 else None
            ask = security.AskPrice if security.AskPrice > 0 else None
            
            if bid is None or ask is None:
                self.Debug(f"Option fill confirmed: {symbol} quantity {order_event.FillQuantity} @ ${order_event.FillPrice:.2f} (no market data)")
                return
                
            # Calculate market metrics
            mid = (bid + ask) / 2
            spread = ask - bid
            spread_pct = (spread / mid) * 100 if mid > 0 else 0
            
            # Determine direction
            direction = "SELL" if order_event.FillQuantity < 0 else "BUY"
            
            # Get limit price if available
            limit_price = getattr(order_event, 'LimitPrice', None)
            if limit_price is None:
                # Try to get from the order if available
                try:
                    order = self.Transactions.GetOrderById(order_event.OrderId)
                    limit_price = order.LimitPrice
                except:
                    limit_price = None
            
            # Log comprehensive fill analysis
            limit_str = f"limit={limit_price:.2f}" if limit_price else "limit=None"
            self.Debug(f"OPTION FILL ANALYSIS: {symbol}")
            self.Debug(f"  Direction: {direction} | Quantity: {order_event.FillQuantity}")
            self.Debug(f"  Market: bid={bid:.2f} ask={ask:.2f} mid={mid:.2f}")
            self.Debug(f"  Spread: ${spread:.2f} ({spread_pct:.1f}%)")
            self.Debug(f"  Execution: {limit_str} -> fill=${order_event.FillPrice:.2f}")
            
            # Execution quality analysis
            if limit_price:
                if direction == "SELL":
                    execution_quality = "BETTER" if order_event.FillPrice >= limit_price else "WORSE"
                else:
                    execution_quality = "BETTER" if order_event.FillPrice <= limit_price else "WORSE"
                self.Debug(f"  Quality: {execution_quality} than limit (${order_event.FillPrice:.2f} vs ${limit_price:.2f})")
            
        except Exception as e:
            # Fallback to simple logging if analysis fails
            self.Debug(f"Option fill confirmed: {order_event.Symbol} quantity {order_event.FillQuantity} @ ${order_event.FillPrice:.2f}")
            if self.debug_mode:
                self.Debug(f"Fill analysis error: {e}")

    def _get_current_execution_phase(self):
        """
        Determine which execution phase we should run based on current time.
        With separate schedules, each execution time corresponds to a specific phase.
        Returns: (phase_0_allowed, phase_1_allowed, phase_2_allowed)
        """
        if not PHASE_SPLIT_ENABLED:
            return True, True, True  # Run all phases if split is disabled

        current_time = self.Time.time()
        phase_0_time = datetime.strptime(PHASE_0_TIME, "%H:%M").time()
        phase_1_time = datetime.strptime(PHASE_1_TIME, "%H:%M").time()
        phase_2_time = datetime.strptime(PHASE_2_TIME, "%H:%M").time()

        # With separate schedules, determine phase based on exact execution time
        # Phase 0 runs at exactly 15:45 (exits)
        phase_0_allowed = (current_time.hour == phase_0_time.hour and
                          current_time.minute == phase_0_time.minute)

        # Phase 1 runs at exactly 15:50 (new trades)
        phase_1_allowed = (current_time.hour == phase_1_time.hour and
                          current_time.minute == phase_1_time.minute)

        # Phase 2 runs at exactly 15:55 (portfolio rebalancing)
        phase_2_allowed = (current_time.hour == phase_2_time.hour and
                          current_time.minute == phase_2_time.minute)

        return phase_0_allowed, phase_1_allowed, phase_2_allowed

    def ExecuteStrategy(self):
        """
        Execute the daily trading flow in split phases to prevent race conditions:
        Phase 0 (15:45): Exit trades - free up margin before new trades
        Phase 1 (15:50): Strategy Eval + New trades + Per-trade hedges
        Phase 2 (15:55): Portfolio rebalancing

        This timing split ensures exits complete before new trades, freeing margin,
        and new trades have time to fill before portfolio rebalancing runs.
        
        CRITICAL DATA SOURCE RULE:
        - Option filtering: Hybrid approach (OnData discovery + Securities pricing) - ALLOWED
        - ALL trading execution: OnData chain data ONLY - MANDATORY
        - ALL risk management: OnData chain data ONLY - MANDATORY
        """
        try:
            # Determine which execution phases to run based on time
            phase_0_allowed, phase_1_allowed, phase_2_allowed = self._get_current_execution_phase()

            if self.debug_mode:
                current_time_str = self.Time.strftime("%H:%M:%S")
                self.Debug(f"EXECUTION PHASE CHECK: Time={current_time_str}, Phase0={phase_0_allowed}, Phase1={phase_1_allowed}, Phase2={phase_2_allowed}")

            if self.IsWarmingUp:
                return

            # === PHASE 0: EXITS ===
            if phase_0_allowed:
                self.phase_executor.execute_phase_0_exits()

            # === PHASE 1: NEW TRADES + PER-TRADE HEDGES ===
            if phase_1_allowed:
                self.phase_executor.execute_phase_1_trades_and_hedges()

            # === PHASE 2: PORTFOLIO REBALANCING ===
            if phase_2_allowed:
                self.phase_executor.execute_phase_2_portfolio_rebalancing()

            # If no phases are allowed, skip execution
            if not phase_0_allowed and not phase_1_allowed and not phase_2_allowed and PHASE_SPLIT_ENABLED:
                if self.debug_mode:
                    current_time_str = self.Time.strftime("%H:%M:%S")
                    self.Debug(f"EXECUTION SKIPPED: Outside execution windows (Time={current_time_str})")

        except Exception as e:
            if self.debug_mode:
                self.Debug(f"ExecuteStrategy error: {e}")

    def cleanup_old_positions(self):
        """Aggressive cleanup of old positions to prevent memory bloat"""
        try:
            from datetime import timedelta
            cutoff_time = self.Time - timedelta(days=self.position_cleanup_days)
            
            old_positions = []
            for pos_id, position in self.positions.items():
                # Clean up zero-quantity positions that are old
                if (abs(position.get('quantity', 0)) == 0 and 
                    position.get('timestamp') and 
                    position.get('timestamp') < cutoff_time):
                    old_positions.append(pos_id)
            
            # AGGRESSIVE CLEANUP: Also remove very old positions regardless of quantity
            # This prevents positions dictionary from growing indefinitely
            very_old_cutoff = self.Time - timedelta(days=30)  # 30 days max
            for pos_id, position in self.positions.items():
                if (position.get('timestamp') and 
                    position.get('timestamp') < very_old_cutoff):
                    if pos_id not in old_positions:  # Don't double-count
                        old_positions.append(pos_id)
            
            # HARD CAP: If positions dict is still too large, remove oldest entries
            max_positions = 1000  # Hard cap on positions dictionary
            if len(self.positions) > max_positions:
                # Sort by timestamp and remove oldest
                sorted_positions = sorted(
                    self.positions.items(), 
                    key=lambda x: x[1].get('timestamp', self.Time)
                )
                excess_count = len(self.positions) - max_positions
                for i in range(excess_count):
                    pos_id = sorted_positions[i][0]
                    if pos_id not in old_positions:
                        old_positions.append(pos_id)
            
            for pos_id in old_positions:
                del self.positions[pos_id]
            
            if old_positions:
                self.debug_log(f"POSITION CLEANUP: Removed {len(old_positions)} positions (dict size: {len(self.positions)})")
                
        except Exception as e:
            self.debug_log(f"Position cleanup error: {e}")

    def debug_log(self, message):
        """Conditional debug logging for performance optimization"""
        if self.debug_mode and self.debug_logging_enabled:
            self.Debug(message)

    def log_memory_usage(self):
        """Log memory usage statistics for monitoring with alerts"""
        try:
            if self.memory_monitoring_enabled:
                greeks_cache_size = len(getattr(self, 'greeks_cache', {}))
                positions_size = len(self.positions)
                chain_snapshot_size = len(getattr(self.options_data, 'chain_greeks_snapshot', {})) if hasattr(self, 'options_data') else 0
                todays_trades_size = len(getattr(self, 'todays_new_trades', []))
                
                # Memory usage summary
                self.debug_log(f"MEMORY USAGE: Greeks={greeks_cache_size}, Positions={positions_size}, Chain={chain_snapshot_size}, Trades={todays_trades_size}")
                
                # ALERTS for excessive memory usage
                if greeks_cache_size > 500:
                    self.Log(f"MEMORY ALERT: Greeks cache too large ({greeks_cache_size} entries)")
                if positions_size > 2000:
                    self.Log(f"MEMORY ALERT: Positions dict too large ({positions_size} entries)")
                if chain_snapshot_size > 200:
                    self.Log(f"MEMORY ALERT: Chain snapshot too large ({chain_snapshot_size} entries)")
                if todays_trades_size > 1000:
                    self.Log(f"MEMORY ALERT: Today's trades list too large ({todays_trades_size} entries)")
                    
        except Exception as e:
            self.debug_log(f"Memory monitoring error: {e}")

    def daily_cleanup(self):
        """Daily cleanup and cache reset to prevent memory bloat"""
        try:
            self.debug_log("=== DAILY CLEANUP START ===")
            
            # Reset daily caches
            self.todays_new_trades.clear()
            self.todays_new_trade_deltas.clear()
            
            # Clean up old Greeks cache
            if hasattr(self, 'options_data') and self.options_data:
                self.options_data.cleanup_old_greeks()
            
            # Clean up old positions
            self.cleanup_old_positions()
            
            # Reset intraday risk monitor daily tracking
            if hasattr(self, 'intraday_risk_monitor') and self.intraday_risk_monitor:
                self.intraday_risk_monitor.reset_daily()
            
            # AGGRESSIVE CLEANUP: Also clean up Greeks cache more frequently
            if hasattr(self, 'options_data') and self.options_data:
                self.options_data.cleanup_old_greeks()
            
            # Log memory usage if monitoring enabled
            self.log_memory_usage()
            
            self.debug_log("=== DAILY CLEANUP COMPLETE ===")
                
        except Exception as e:
            self.debug_log(f"Daily cleanup error: {e}")

    def weekly_aggressive_cleanup(self):
        """Weekly aggressive cleanup to prevent long-term memory bloat"""
        try:
            self.debug_log("=== WEEKLY AGGRESSIVE CLEANUP START ===")
            
            # Clear all caches aggressively
            if hasattr(self, 'greeks_cache'):
                old_size = len(self.greeks_cache)
                self.greeks_cache.clear()
                self.debug_log(f"WEEKLY CLEANUP: Cleared Greeks cache ({old_size} entries)")
            
            if hasattr(self, 'options_data') and hasattr(self.options_data, 'chain_greeks_snapshot'):
                old_size = len(self.options_data.chain_greeks_snapshot)
                self.options_data.chain_greeks_snapshot.clear()
                self.debug_log(f"WEEKLY CLEANUP: Cleared chain snapshot ({old_size} entries)")
            
            # Keep only very recent positions (last 7 days)
            from datetime import timedelta
            cutoff_time = self.Time - timedelta(days=7)
            old_positions = []
            for pos_id, position in self.positions.items():
                if (position.get('timestamp') and 
                    position.get('timestamp') < cutoff_time):
                    old_positions.append(pos_id)
            
            for pos_id in old_positions:
                del self.positions[pos_id]
            
            if old_positions:
                self.debug_log(f"WEEKLY CLEANUP: Removed {len(old_positions)} old positions")
            
            # Force garbage collection
            import gc
            gc.collect()
            
            self.debug_log("=== WEEKLY AGGRESSIVE CLEANUP COMPLETE ===")
            
        except Exception as e:
            self.debug_log(f"Weekly cleanup error: {e}")

    def OnEndOfAlgorithm(self):
        """
        Final cleanup and reporting.
        """
        self.Log("=== STRATEGY COMPLETE ===")
        self.Log(f"Total Positions Tracked: {len(self.positions)}")


    def EstimatePutDelta(self, strike, underlying_price, expiration):
        """
        Estimate put delta using GreeksProvider.
        """
        try:
            if hasattr(self, 'greeks_provider') and self.greeks_provider:
                delta, source = self.greeks_provider.get_delta(None, strike, underlying_price, expiration)
                return float(delta) if delta is not None else DEFAULT_DELTA_SHORT_PUT
            else:
                # Simple approximation: delta roughly proportional to moneyness
                moneyness = strike / underlying_price
                if moneyness > 1.0:  # ITM put
                    return min(ITM_DELTA_MAX, ITM_DELTA_MULTIPLIER * moneyness)
                else:  # OTM put
                    return max(OTM_DELTA_MIN, ITM_DELTA_MULTIPLIER * moneyness)
        except Exception as e:
            if self.debug_mode:
                self.Debug(f"Error estimating put delta: {e}")
            return DEFAULT_DELTA_SHORT_PUT  # Default delta for short puts

    def CancelStaleEntryOrders(self):
        """
        Cancel any unfilled ENTRY orders before market close to prevent MOO conversion.
        This prevents orders from rolling into next-day market-on-open fills.
        """
        try:
            # Get ALL open orders (not just for option symbol - specific contracts have different symbols)
            all_open_orders = self.Transactions.GetOpenOrders()

            cancelled = 0
            for order in all_open_orders:
                # Cancel ALL ENTRY orders that are still open or partially filled, regardless of age/symbol
                if (getattr(order, "Tag", "") == ENTRY_TAG and
                    order.Status in [OrderStatus.Submitted, OrderStatus.PartiallyFilled]):
                    self.Transactions.CancelOrder(order.Id, "Cancel unfilled entry before close")
                    cancelled += 1

            if cancelled > 0 and self.debug_mode:
                self.Debug(f"Canceled {cancelled} unfilled ENTRY order(s) before close")

        except Exception as e:
            if self.debug_mode:
                self.Debug(f"CancelStaleEntryOrders error: {e}")

    def LogEODPosition(self):
        """Log EOD portfolio position at market close"""
        if self.debug_mode:
            # Log EOD with cache age for QC-CACHED sources
            if self.analytics:
                self.analytics.log_eod_greeks()

    # --- Helpers for the new daily flow ---
    
    def _refresh_margin_values(self):
        """
        Refresh margin values to ensure accurate calculations after position exits.
        This helps address timing issues where QC's margin values might not be updated immediately.
        """
        try:
            # Force a portfolio update by accessing margin values
            # This can help trigger QC's internal margin recalculation
            _ = self.Portfolio.TotalMarginUsed
            _ = self.Portfolio.MarginRemaining
            _ = self.Portfolio.TotalPortfolioValue
            
            if self.debug_mode:
                self.Debug(f"MARGIN REFRESH: Used=${self.Portfolio.TotalMarginUsed:,.0f}, "
                          f"Available=${self.Portfolio.MarginRemaining:,.0f}, "
                          f"Portfolio=${self.Portfolio.TotalPortfolioValue:,.0f}")
        except Exception as e:
            if self.debug_mode:
                self.Debug(f"Margin refresh error: {e}")

    def _analyze_margin_capacity(self):
        """
        MARGIN ANALYSIS: Determine if we have capacity to add new positions.
        Delegates to risk manager for calculation.
        """
        if hasattr(self, 'risk_manager') and self.risk_manager:
            has_capacity, available_margin = self.risk_manager.check_margin_capacity()
            return has_capacity
        else:
            self.Debug("Risk manager not available, assuming no margin capacity")
            return False
    
    def _execute_single_trade(self, intent):
        """
        Execute a single trade with proper position sizing.
        Returns option log data if trade was successfully placed, False otherwise.
        """
        try:
            if not intent.candidate:
                return False
            
            # Delegate to position manager for execution
            result = self.position_manager.try_enter_position(intent.candidate)
            
            # If successful, result contains option log data
            if result:
                return result
            else:
                return False
            
        except Exception as e:
            if self.debug_mode:
                self.Debug(f"Single trade execution error: {e}")
            return False
    
    def _log_option_selected_from_intent(self, intent):
        """
        Log information about a selected option trade from intent in P1C section
        Note: This logs the SELECTION, not the execution. Actual limit price and quantity
        will be calculated during execution.
        """
        try:
            candidate = intent.candidate
            if not candidate:
                return
                
            symbol = candidate.get('symbol')
            strike = candidate.get('strike', 0)
            dte = candidate.get('dte', 0)
            delta = candidate.get('delta', 0)
            premium = candidate.get('premium', 0)  # Mid price from filtering
            
            if delta and delta != 'N/A':
                delta_str = f"Δ={delta:.3f}"
            else:
                delta_str = "Δ=N/A"
            
            # Log the option selection (actual sizing and pricing happens during execution)
            self.Debug(f"OPTION SELECTED: {symbol} | Strike: ${strike:.2f} | DTE: {dte} | Premium: ${premium:.2f} | {delta_str}")
            
        except Exception as e:
            if self.debug_mode:
                self.Debug(f"Error logging OPTION SELECTED: {e}")
    
    def _log_option_selected(self, option_log_data):
        """
        Log the OPTION SELECTED message in the P1C section (deprecated - kept for compatibility)
        """
        try:
            symbol = option_log_data['symbol']
            strike = option_log_data['strike']
            dte = option_log_data['dte']
            delta = option_log_data['delta']
            limit_price = option_log_data['limit_price']
            position_size = option_log_data['position_size']
            
            if delta != 'N/A':
                delta_str = f"Δ={delta:.3f}"
            else:
                delta_str = "Δ=N/A"
            
            self.Debug(f"OPTION SELECTED: {symbol} | Strike: ${strike:.2f} | DTE: {dte} | Premium: ${limit_price:.2f} | {delta_str} | Qty: {position_size}")
            
        except Exception as e:
            # Fallback logging if data is incomplete
            try:
                symbol = option_log_data['symbol']
                strike = option_log_data['strike']
                limit_price = option_log_data['limit_price']
                position_size = option_log_data['position_size']
                self.Debug(f"OPTION SELECTED: {symbol} | Strike: ${strike:.2f} | Premium: ${limit_price:.2f} | Qty: {position_size}")
            except Exception:
                if self.debug_mode:
                    self.Debug(f"Error logging OPTION SELECTED: {e}")
    
    def _execute_new_trade_hedges(self, executed_trades):
        """
        NEW HEDGE EXECUTION: Execute per-trade hedges for newly executed trades.
        Since FORCE_LIMIT_FILLS=True, we know option orders will fill, so we can
        hedge immediately using target_contracts without waiting for actual fills.
        
        IMPORTANT: This is SKIPPED entirely if TRADE bands are "inert" (target=0, tolerance>=1.0).
        When using NAV-only hedging, only P2 portfolio rebalancing should execute.
        """
        try:
            if not executed_trades:
                return
            
            # CHECK: Skip P1D per-trade hedging if TRADE bands are effectively disabled
            # TRADE bands are "inert" when target=0 and tolerance is very wide (>=1.0)
            # In this case, only P2 NAV-based portfolio rebalancing should hedge
            trade_target_equity = getattr(self, 'delta_target_trade_pct_equity', 0.0)
            trade_tol_equity = getattr(self, 'delta_tol_trade_pct_equity', 0.15)
            trade_target_future = getattr(self, 'delta_target_trade_pct_future', 0.0)
            trade_tol_future = getattr(self, 'delta_tol_trade_pct_future', 0.04)
            
            # If BOTH equity and future TRADE targets are 0 AND tolerances are very wide, skip P1D entirely
            equity_disabled = (trade_target_equity == 0.0 and trade_tol_equity >= 1.0)
            future_disabled = (trade_target_future == 0.0 and trade_tol_future >= 1.0)
            
            if equity_disabled and future_disabled:
                if self.debug_mode:
                    self.Debug("P1D HEDGING DISABLED: TRADE bands are inert (target=0, tol>=1.0). Only P2 NAV hedging will run.")
                return
            
            hedges_executed = 0
            for intent in executed_trades:
                candidate = intent.candidate
                if not candidate:
                    continue
                
                symbol = candidate.get('symbol')
                if not symbol:
                    continue
                
                # Prefer target_contracts (intent) and fall back to current quantity if missing
                target_qty = 0
                for pos in self.positions.values():
                    if pos.get('symbol') == symbol:
                        tc = pos.get('target_contracts', 0) or 0
                        q = pos.get('quantity', 0) or 0
                        target_qty = abs(tc if tc != 0 else q)
                        break
                
                if target_qty != 0:
                    # Calculate and cache the dollar delta for universal hedge
                    try:
                        pos = None
                        for p in self.positions.values():
                            if p.get('symbol') == symbol:
                                pos = p
                                break
                        
                        if pos and 'delta' in pos:
                            delta = float(pos['delta'])
                            underlying_symbol = symbol.Underlying if hasattr(symbol, 'Underlying') else self.underlying_symbol
                            price = float(self.Securities[underlying_symbol].Price)
                            units_contrib = delta * target_qty * 100.0  # 100 shares per contract
                            dollar_delta = units_contrib * price
                            
                            # Cache the dollar delta for universal hedge to account for
                            self.todays_new_trade_deltas.append({
                                'symbol': symbol,
                                'dollar_delta': dollar_delta
                            })
                            
                            if self.debug_mode:
                                self.Debug(f"CACHED DOLLAR DELTA: {symbol} = ${dollar_delta:,.0f}")
                    except Exception as e:
                        if self.debug_mode:
                            self.Debug(f"Failed to cache dollar delta for {symbol}: {e}")
                    
                    # Execute per-trade hedge using SIGNED quantity for short puts (we sell puts)
                    signed_qty = -int(target_qty)
                    success = self.delta_hedger.execute_delta_hedge_for_trade(symbol, signed_qty)
                    if success:
                        hedges_executed += 1
            
            if self.debug_mode:
                self.Debug(f"NEW HEDGE EXECUTION: Executed {hedges_executed}/{len(executed_trades)} per-trade hedges")
                
        except Exception as e:
            if self.debug_mode:
                self.Debug(f"New trade hedges execution error: {e}")
    
    def _analyze_portfolio_state(self):
        """
        PHASE 2A: Analyze and print current portfolio state
        Shows filled trades, hedge positions, and total portfolio delta
        """
        if not self.debug_mode:
            return
            
        # Calculate and show total portfolio delta (consolidated logging)
        if hasattr(self, 'delta_hedger') and self.delta_hedger:
            groups = self.delta_hedger.compute_delta_groups()
            total_dollar_delta = sum(g['dollar_delta'] for g in groups.values())
            
            # Show breakdown by underlying with consolidated info
            for und_sym, group in groups.items():
                option_delta = group.get('option_delta', 0)
                hedge_delta = group.get('hedge_delta', 0)
                self.Debug(f"  - {und_sym}: ${group['dollar_delta']:,.0f} (options: ${option_delta:,.0f}, hedges: ${hedge_delta:,.0f})")
            
            self.Debug(f"TOTAL PORTFOLIO DELTA: ${total_dollar_delta:,.0f} across {len(groups)} underlyings")

    def _execute_portfolio_rebalancing(self):
        """
        PHASE 2B: Portfolio-wide delta rebalancing.
        This ensures the entire portfolio stays within delta tolerance bands.
        """
        # Portfolio rebalancing logic
            
        try:
            # Collect pending trades for analysis and rebalancing
            pending_trades = getattr(self, 'todays_new_trades', [])
            pending_list = []
            for intent in pending_trades:
                if hasattr(intent, 'candidate') and intent.candidate:
                    candidate = intent.candidate
                    symbol = candidate.get('symbol')
                    target_qty = candidate.get('target_contracts', 0)
                    cached_delta = candidate.get('delta', 0.0)
                    if symbol and target_qty != 0:
                        pending_list.append((symbol, target_qty, cached_delta))

            # Check if we need to rebalance based on delta bands
            out_of_bounds = self.analytics.delta_bands() if self.analytics else False

            if out_of_bounds:
                # Execute universal hedge with cooldown/timing checks
                if self.delta_hedger:
                    self.delta_hedger.execute_delta_hedge_universal(pending_list if pending_list else None)
                    
        except Exception as e:
            if self.debug_mode:
                self.Debug(f"Portfolio rebalancing error: {e}")

    # Removed duplicate _portfolio_delta_usd() and _portfolio_delta_check_and_log() functions
    # These are now handled by the analytics module

    def _execute_exit_delta_hedge(self, symbol, qty, reason):
        """Execute delta hedge when an option position is closed"""
        try:
            if self.debug_mode:
                self.Debug(f"EXIT HEDGE: Processing {symbol} qty={qty} reason={reason}")
            
            # Get option contract details
            if not hasattr(self, 'current_chain') or not self.current_chain:
                if self.debug_mode:
                    self.Debug(f"EXIT HEDGE: No chain data available")
                return
            
            # Find the option contract in the chain
            option_contract = None
            for contract in self.current_chain:
                if contract.Symbol == symbol:
                    option_contract = contract
                    break
            
            if option_contract is None:
                if self.debug_mode:
                    self.Debug(f"EXIT HEDGE: Symbol {symbol} not found in current chain")
                return
            if not hasattr(option_contract, 'Greeks') or not option_contract.Greeks:
                if self.debug_mode:
                    self.Debug(f"EXIT HEDGE: No Greeks for {symbol}")
                return
            
            # Calculate hedge quantity based on option delta
            option_delta = option_contract.Greeks.Delta
            underlying_symbol = self.underlying_symbol
            close_price = self.Securities[underlying_symbol].Price
            
            # For exit hedges, we need to offset the delta impact of closing the position
            # If we're buying back short puts (qty > 0), we lose negative delta exposure
            # So we need to sell shares to maintain the same net delta
            hedge_quantity = int(abs(qty) * 100 * option_delta)  # 100 shares per contract
            if qty > 0:  # Buying back (closing short position)
                hedge_quantity = -hedge_quantity  # Sell shares to offset lost negative delta
            else:  # Selling (closing long position)
                hedge_quantity = hedge_quantity   # Buy shares to offset lost positive delta
            
            if self.debug_mode:
                self.Debug(f"EXIT HEDGE: QQQ {hedge_quantity:+d} shares | Option delta: {option_delta:.4f} | Impact: {abs(hedge_quantity):.2f} | Reason: {reason}")
            
            if abs(hedge_quantity) < 1:
                return
                
            # Place the actual hedge order
            if hedge_quantity != 0:
                # Tag as HEDGE to allow OnOrderEvent to link/update the tracked hedge position exactly once
                try:
                    self.MarketOrder(underlying_symbol, hedge_quantity, tag=f"{self.HEDGE_TAG}_{symbol}")
                except TypeError:
                    # Older LEAN versions may not accept tag kwarg in Python wrapper
                    self.MarketOrder(underlying_symbol, hedge_quantity)
                
        except Exception as e:
            if self.debug_mode:
                self.Debug(f"EXIT HEDGE ERROR: {e}")

    # Removed unused _maybe_execute_universal_hedge() function