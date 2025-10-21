# =============================================================================
# DELTA-HEDGED THETA ENGINE CONFIGURATION
# =============================================================================
# This file contains all configurable parameters for the delta-hedged theta engine
# strategy. Modify these values to adjust strategy behavior without changing the
# core algorithm logic.
# =============================================================================

# =============================================================================
# BACKTEST PERIOD CONFIGURATION
# =============================================================================
BACKTEST_START_DATE = (2015, 1, 1)  # (year, month, day) - Start of backtest period 8/3/2015
BACKTEST_END_DATE = (2016, 1, 1)    # (year, month, day) - End of backtest period 10/1/2015
INITIAL_CASH = 1000000              # Initial account value in dollars ($1M)

# =============================================================================
# UNDERLYING ASSET CONFIGURATION
# =============================================================================
UNDERLYING_SYMBOL = "QQQ"           # The underlying ETF/stock to trade options on
BENCHMARK_SYMBOL = "QQQ"            # Benchmark for performance comparison

# =============================================================================
# OPTION FILTERING PARAMETERS
# =============================================================================
STRIKES_BELOW = 20                  # Number of strikes below current price to consider
STRIKES_ABOVE = 0                   # Number of strikes above current price to consider
MIN_TARGET_DTE = 21                 # Minimum days to expiration for option selection (avoid high gamma)
MAX_TARGET_DTE = 105                # Maximum days to expiration for option selection (quarterly cycles)
MIN_DELTA = 0.18                    # Minimum delta (absolute value) - narrowed to liquid, higher-theta band
MAX_DELTA = 0.25                    # Maximum delta (absolute value) - sweet spot without ATM drift
MIN_PREMIUM_PCT_OF_SPOT = 0.005     # Minimum premium as 0.5% of underlying price (fixed: was 0.0025 = 0.25%)

# =============================================================================
# POSITION SIZING PARAMETERS
# =============================================================================
MIN_BUYING_POWER = 5000             # Minimum buying power required to enter new position
MIN_CONTRACTS = 1                   # Minimum number of contracts per position
MAX_CONTRACTS_PER_100K = 10          # Maximum contracts per $100K portfolio value (scales with size)
MIN_MARGIN_PER_POSITION_PCT = 0.01  # Minimum margin per position as % of account (1%)
MARGIN_SAFETY_FACTOR = 0.9          # Safety factor for margin calculations (90% of available)
ESTIMATED_MARGIN_PCT = 0.15         # Estimated margin requirement as 15% of strike price (fixed: was 0.10)
TARGET_MARGIN_USE = 0.85            # Target margin utilization as % of account (85% for better deployment)
MAX_POSITIONS = 15                  # Maximum number of concurrent positions
MARGIN_BUFFER = 0.03                # Buffer margin to keep available (3%)
MAX_MARGIN_PER_TRADE_PCT = 0.15     # Maximum margin per trade as % of NAV (15% for better position sizing)
PRE_ORDER_MARGIN_SAFETY = 0.8       # Pre-order margin check safety factor (80% of available margin)

# =============================================================================
# DYNAMIC POSITION SIZING PARAMETERS
# =============================================================================
# When margin utilization is low, increase position sizes to improve performance
DYNAMIC_SIZING_ENABLED = False      # DISABLED: Turn off dynamic sizing to confirm hedge posture first
LOW_MARGIN_THRESHOLD = 0.6         # Threshold below which to apply scaling (50% margin available)
POSITION_SCALING_FACTOR = 2.0       # Multiplier for position size when margin is underutilized
MAX_SCALED_MARGIN_PER_TRADE_PCT = 0.16  # Max margin per trade when scaled (16% = 2x normal 8%)
SCALING_GRADUAL_ENABLED = True      # Apply gradual scaling instead of binary on/off
SCALING_MIN_THRESHOLD = 0.30        # Minimum margin utilization to start scaling
SCALING_MAX_THRESHOLD = 0.60        # Maximum margin utilization to apply full scaling

# =============================================================================
# INTRADAY RISK MONITORING PARAMETERS
# =============================================================================
# Intraday risk monitoring to prevent margin calls
INTRADAY_RISK_MONITORING_ENABLED = True    # Enable intraday risk monitoring
RISK_CHECK_INTERVAL_MINUTES = 15          # Check risk every 15 minutes (less frequent to avoid over-trading)
MARGIN_CALL_THRESHOLD = 0.93               # Alert when margin utilization hits 95%
PORTFOLIO_LOSS_THRESHOLD = 0.30           # Alert when portfolio loss exceeds 30% (higher threshold)
EMERGENCY_EXIT_THRESHOLD = 0.40           # Emergency exit when portfolio loss exceeds 40%
RISK_ALERT_COOLDOWN_MINUTES = 120          # Cooldown between risk alerts (2 hours)

# Risk Reduction Parameters
RISK_REDUCTION_ENABLED = True             # Enable intelligent risk reduction
RISK_REDUCTION_THRESHOLD = 0.95           # Trigger risk reduction at 97% margin utilization (higher threshold)
RISK_REDUCTION_TARGET = 0.9              # Reduce to 92% margin utilization
RISK_REDUCTION_COOLDOWN_MINUTES = 60     # Cooldown between risk reduction actions

# =============================================================================
# PERFORMANCE OPTIMIZATION PARAMETERS
# =============================================================================
GREEKS_CACHE_CLEANUP_DAYS = 7        # Keep only last 7 days of Greeks cache
POSITION_CLEANUP_DAYS = 7            # Clean up zero-quantity positions older than 7 days
CHAIN_SNAPSHOT_MAX_ENTRIES = 100     # Hard cap for chain snapshot cache (per day)
GREEKS_CACHE_MAX_ENTRIES = 200       # Hard cap for greeks_cache entries
GREEKS_SNAPSHOT_INTERVAL_MINUTES = 15  # Interval for Greeks snapshot updates (15 minutes)
DEBUG_LOGGING_ENABLED = False         # Enable/disable debug logging for performance
MEMORY_MONITORING_ENABLED = False    # Enable memory usage monitoring

# =============================================================================
# DELTA HEDGING PARAMETERS
# =============================================================================
# Use NAV bands only for portfolio hedging; make TRADE bands inert to disable per-trade hedging
DELTA_REVERT_MODE = "BAND"          # "BAND" = hedge to nearest boundary (good for controlled drift)

# TRADE Mode: Made INERT to disable per-trade hedging (Phase 1)
DELTA_TARGET_TRADE_PCT_EQUITY = 0.0   # Zero target = no per-trade hedging
DELTA_TOL_TRADE_PCT_EQUITY = 1.0      # Very wide tolerance = never triggers
DELTA_TARGET_TRADE_PCT_FUTURE = 0.0   # Zero target = no per-trade hedging  
DELTA_TOL_TRADE_PCT_FUTURE = 1.0      # Very wide tolerance = never triggers

# NAV Mode: Re-centered with controlled long bias for equity drift capture
DELTA_TARGET_NAV_PCT_EQUITY = 0.12    # +12% of NAV (controlled long tilt)
DELTA_TOL_NAV_PCT_EQUITY = 0.18       # ±18% tolerance band (hedge only when truly offside)
DELTA_TARGET_NAV_PCT_FUTURE = 0.12    # +12% of NAV  
DELTA_TOL_NAV_PCT_FUTURE = 0.18       # ±18% tolerance band

# Delta Band Calculation Mode
DELTA_BAND_MODE = "NAV"                # NAV mode only - portfolio-level hedging at Phase 2

# =============================================================================
# POSITION DIVERSIFICATION PARAMETERS
# =============================================================================
# DTE Bucket Rotation - prevents clustering in specific DTE ranges
# Single DTE bucket covering full range
DTE_BUCKETS = [(21, 105)]  # Single bucket covering full DTE range
DTE_FALLBACK_ENABLED = True        # Allow fallback to other DTE buckets when primary has no candidates

# Expiry Management - prevents overconcentration in specific expiries
MAX_POSITIONS_PER_EXPIRY = 2        # Maximum positions per expiry date
MIN_STRIKE_SPACING_PCT = 0.015      # Minimum 1.5% spacing between strikes in same expiry (fixed: was 0.01 = 1%)
EXPIRY_COOLDOWN_DAYS = 2            # Cooldown period before adding to same expiry

# Delta band filter removed - using moneyness filter instead for simpler logic

# Hedging Throttling and Market Protection
HEDGE_COOLDOWN_SECONDS = 900        # 15 minutes between hedges (reduced churn, Phase 2 only)
HEDGE_CLOSE_PROXIMITY_SECONDS = 60  # Don't hedge within N seconds of market close

# =============================================================================
# BLACK-SCHOLES PARAMETERS
# =============================================================================
# Fallback values for Black-Scholes Greeks estimation when QuantConnect Greeks unavailable
BS_DEFAULT_ATM_IV = 0.25            # Default at-the-money implied volatility (25%)
BS_DEFAULT_RISK_FREE_RATE = 0.045   # Default risk-free rate as 4.5% (fixed: was 0.025 = 2.5%)

# =============================================================================
# EXIT STRATEGY PARAMETERS
# =============================================================================
QUICK_PROFIT_TARGET = 0.45          # Quick profit target as % of credit received (45% - lower to realize theta more often)
NORMAL_PROFIT_TARGET = 0.75         # Normal profit target as % of credit received (75%)
LET_EXPIRE_THRESHOLD = 0.05         # Let expire if price <= 5% of entry price
STOP_LOSS_MULTIPLIER = 2.5          # Stop loss as multiple of credit received (250%)
MIN_DTE = 14                         # Minimum DTE before rolling position (per documentation)
QUICK_PROFIT_MIN_DTE = 21           # Minimum DTE for quick profit exit (don't exit winners early)
TIME_STOP_DTE = 7                   # Time stop DTE threshold (< 7 DTE and not at profit target)
TIME_STOP_ACTION = "CLOSE"          # Action when time stop triggers: "ROLL" or "CLOSE"
                                              # ROLL: Close and open new position with same strike/expiration
                                              # CLOSE: Simply close the position to avoid gamma spikes

# =============================================================================
# TRADING SCHEDULE PARAMETERS
# =============================================================================
MARKET_OPEN_MINUTES = 30            # Minutes after market open to start trading
MARKET_CLOSE_MINUTES = 5            # Minutes before market close to execute strategy

# =============================================================================
# ORDER HOUSEKEEPING PARAMETERS
# =============================================================================
CANCEL_UNFILLED_AT_CLOSE = True     # Cancel open entry orders before the bell to prevent MOO conversion
CANCEL_AT_CLOSE_MINUTES = 1         # Run cancel sweep N minutes before close

# =============================================================================
# ORDER PRICING PARAMETERS
# =============================================================================
# Entry Order Pricing (when placing new option orders)
ENTRY_MAX_SPREAD_PCT = 0.10         # Skip entry if spread/price > 10% (too wide)
ENTRY_NUDGE_FRACTION = 0.25         # Nudge limit price by 25% of spread toward favorable side
ENTRY_ABS_SPREAD_MIN = 0.05         # Absolute minimum spread in dollars allowed (combined with % of mid)

# Exit Order Pricing (when closing option positions)
EXIT_MAX_SPREAD_PCT = 0.50          # Consider spread "too wide" if > 50% (exit aggressively if needed)
EXIT_NUDGE_FRACTION = 0.25          # Nudge limit price by 25% of spread toward favorable side

# Retry Limits for Exit Orders
QUOTE_RETRY_LIMIT = 1               # Retry once if quotes are missing/stale
SPREAD_RETRY_LIMIT = 1              # Retry once if spread is too wide
NONTRADABLE_RETRY_LIMIT = 3         # Retry up to 3 times if security is non-tradable

# =============================================================================
# FILL MODEL PARAMETERS
# =============================================================================
USE_MID_HAIRCUT_FILL_MODEL = True   # Use MidHaircutFillModel for realistic option fills
MID_HAIRCUT_FRACTION = 0.25         # Fraction of spread taken against you (0.25 = 25%)
MAX_SPREAD_PCT = 0.30               # Skip fill if spread/price > this (30%)

# Fill behavior controls
FILL_ON_SUBMISSION_BAR = True       # Force fills on current bar if quotes are sane
REQUIRE_BID_ASK = True              # Don't fill if either side of book is missing
FORCE_LIMIT_FILLS = True            # Force limit order fills even if limit price not met (models spread trading)
FORCE_EXACT_LIMIT = True            # If True, do not clamp to book; fill exactly at submitted limit

# =============================================================================
# ORDER TAGGING CONSTANTS
# =============================================================================
ENTRY_TAG = "ENTRY"                 # Tag for entry orders (short puts)
HEDGE_TAG = "HEDGE"                 # Tag for delta hedge orders (underlying shares)
EXIT_TAG = "EXIT"                   # Tag for exit orders (covering shorts)

# =============================================================================
# WARMUP CONFIGURATION
# =============================================================================
WARMUP_DAYS = 5                     # Number of days to warm up before trading

# =============================================================================
# EXECUTION TIMING PARAMETERS
# =============================================================================
# Split execution into three phases to prevent race conditions and optimize margin usage:
# Phase 0: Exits (earliest time) - free up margin before new trades
# Phase 1: New trades + per-trade hedges (middle time) - use freed margin
# Phase 2: Portfolio rebalancing (latest time) - final delta adjustments
PHASE_SPLIT_ENABLED = True          # Enable/disable timing split
PHASE_0_TIME = "15:45"             # Time to execute exits (HH:MM)
PHASE_1_TIME = "15:50"             # Time to execute new trades and per-trade hedges (HH:MM)
PHASE_2_TIME = "15:55"             # Time to execute portfolio rebalancing (HH:MM)

# =============================================================================
# OVERNIGHT MARGIN MANAGEMENT
# =============================================================================
OVERNIGHT_MARGIN_MAX = 0.98              # Maximum margin utilization overnight (98%)
P2_UNDERLYING_HEDGE_ENABLED = True       # Allow P2 to hedge with underlying
P2_OPTION_REDUCTION_ENABLED = False      # DISABLE position reduction - let positions work
P2_OPTION_REDUCTION_MAX_PCT = 0.10      # Maximum 10% reduction per position (if enabled)

# P2 Position Reduction Strategy (Hybrid Approach)
P2_REDUCTION_STRATEGY = "HYBRID"         # "DELTA", "MARGIN", "RISK", "HYBRID"
P2_DELTA_EFFICIENCY_WEIGHT = 0.4         # Weight for delta efficiency (40%)
P2_SIZE_FACTOR_WEIGHT = 0.2              # Weight for position size (20%)
P2_DTE_FACTOR_WEIGHT = 0.2               # Weight for DTE (20%)
P2_PNL_FACTOR_WEIGHT = 0.2               # Weight for P&L (20%)

# =============================================================================
# DEBUG AND MONITORING PARAMETERS
# =============================================================================
DEBUG_MODE = True                   # Enable debug logging (set to False for production performance)
MAX_CONSECUTIVE_FAILURES = 10       # Maximum consecutive entry failures before relaxing constraints

# =============================================================================
# RISK MANAGEMENT PARAMETERS
# =============================================================================
# These parameters help manage risk and prevent over-leveraging:
# - MIN_BUYING_POWER ensures we have sufficient liquidity
# - MARGIN_SAFETY_FACTOR prevents using all available margin
# - MAX_POSITIONS limits concentration risk
# - STOP_LOSS_MULTIPLIER limits downside on individual positions

# =============================================================================
# STRATEGY ARCHITECTURE
# =============================================================================
# IMPORTANT: Option scoring/selection logic has been moved to strategy modules!
#
# OLD ARCHITECTURE (before refactor):
#   - Scoring logic was in PositionManager.select_best_option()
#   - Strategy logic mixed with infrastructure code
#   - Difficult to plug in different strategies
#
# NEW ARCHITECTURE (after refactor):
#   - Scoring logic is in each strategy module (theta_engine.py, ssvi_strategy.py)
#   - PositionManager is pure infrastructure (filtering, sizing, execution)
#   - Easy to plug in different strategies without touching infrastructure
#
# FRAMEWORK (reusable, strategy-agnostic):
#   - P0-P2 execution phases (main.py)
#   - PositionManager: filter candidates, size positions, execute, track
#   - DeltaHedger: hedge management
#   - ExitRulesManager: position exits
#   - All other modules: data, Greeks, risk, analytics
#
# STRATEGIES (pluggable, strategy-specific):
#   - theta_engine.py: Theta decay (maximize premium/day, 20Δ, 35 DTE)
#   - ssvi_strategy.py: Vol surface arbitrage (SSVI model mispricings)
#   - [Your strategy]: Implement StrategyBase.select_entries() with your logic
#
# To switch strategies:
#   1. Update config.json: "strategy_module": "ssvi_strategy"
#   2. Or pass parameter: --strategy-module ssvi_strategy
#
# See theta_engine.py for theta scoring details (premium-per-day, target bands)

# =============================================================================
# MARGIN ESTIMATION PARAMETERS
# =============================================================================
# Parameters for estimating option margin requirements
MARGIN_ESTIMATE_1_UNDERLYING_PCT = 0.20    # First estimate: 20% of underlying value - OTM + premium
MARGIN_ESTIMATE_2_UNDERLYING_PCT = 0.10    # Second estimate: 10% of underlying value + premium
MARGIN_MINIMUM_FLOOR = 500                 # Minimum margin requirement (hard floor)

# =============================================================================
# FILTER RELAXATION PARAMETERS
# =============================================================================
# Parameters for relaxing filters when no candidates are found
FILTER_RELAXATION_THRESHOLD_DAYS = 10      # Days without candidates before aggressive relaxation
PREMIUM_RELAXATION_FACTOR = 0.5             # Factor to reduce premium filter by (0.5 = halve minimum)
DTE_RELAXATION_DECREMENT = 5                # Days to reduce min DTE by
MIN_DTE_FLOOR = 5                           # Minimum DTE floor during relaxation

# =============================================================================
# DELTA APPROXIMATION PARAMETERS
# =============================================================================
# Parameters for approximating option deltas when Greeks unavailable
DEFAULT_DELTA_SHORT_PUT = -0.25             # Default delta for short puts when moneyness unknown
ITM_DELTA_MULTIPLIER = -0.3                 # Delta multiplier for ITM puts (-0.3 = -30% per unit moneyness)
ITM_DELTA_MAX = -0.5                        # Maximum delta for deep ITM puts
OTM_DELTA_MIN = -0.05                       # Minimum delta for deep OTM puts

# =============================================================================
# STRATEGY LOGIC NOTES
# =============================================================================
# This is a delta-hedged theta engine that:
# 1. Sells OTM puts for premium income (theta decay)
# 2. Uses delta hedging to reduce directional risk
# 3. Manages position size based on margin requirements
# 4. Exits positions based on profit targets or time decay
# 5. Maintains a target portfolio delta through stock hedging
# 6. Supports both EOD and intraday hedging modes
#
# Hedging Modes:
# - EOD (End-of-Day): Faster backtests, hedges once daily at market close using closing price
# -   Uses SecurityInitializer + ClosePriceFillModel + LimitOrders to prevent MOO conversion
# - INTRADAY: Real-time hedging with minute data, uses actual option Greeks
#
# Enhanced Features:
# - BBO Mid Pricing: Uses bid/ask midpoint for accurate option pricing (not zero Security.Close)
# - Premium-per-Margin ranking: Optimizes risk-adjusted returns
# - Delta filtering: Prefers contracts with Δ ∈ [0.15, 0.35] when Greeks available
# - Liquidity screening: Filters out wide spreads (>10% of mid) and low OI
# - Real fill tracking: OnOrderEvent preserves economics for EOD options
# - Black-Scholes estimation: Sophisticated Greeks approximation with market adjustments
# - LimitOrder EOD: Prevents MOO conversion while maintaining Daily resolution speed
#
# Key benefits:
# - Reduced directional risk vs naked puts
# - Consistent premium income from theta decay
# - Systematic position sizing and risk management
# - Automated delta hedging for market neutrality
# - Flexible hedging frequency for different use cases
# ============================================================================= 