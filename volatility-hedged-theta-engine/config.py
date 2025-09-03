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
BACKTEST_START_DATE = (2015, 1, 1)  # (year, month, day) - Start of backtest period
BACKTEST_END_DATE = (2025, 1, 1)    # (year, month, day) - End of backtest period
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
MIN_MONEYNESS = 0.50                # Minimum moneyness (strike/price) - 0.50 = 50% OTM
MAX_MONEYNESS = 0.99                # Maximum moneyness (strike/price) - 0.99 = 1% OTM
MIN_PREMIUM_PCT_OF_SPOT = 0.005     # Minimum premium as % of underlying price (0.5% of spot) - will add $10 minimum

# =============================================================================
# POSITION SIZING PARAMETERS
# =============================================================================
MIN_BUYING_POWER = 5000             # Minimum buying power required to enter new position
MIN_CONTRACTS = 1                   # Minimum number of contracts per position
MAX_CONTRACTS_PER_100K = 5          # Maximum contracts per $100K portfolio value (scales with size)
MIN_MARGIN_PER_POSITION_PCT = 0.01  # Minimum margin per position as % of account (1%)
MARGIN_SAFETY_FACTOR = 0.9          # Safety factor for margin calculations (90% of available)
ESTIMATED_MARGIN_PCT = 0.15         # Estimated margin requirement as % of strike price (15%)
TARGET_MARGIN_USE = 0.80            # Target margin utilization as % of account (80% as requested)
MAX_POSITIONS = 12                  # Maximum number of concurrent positions
MARGIN_BUFFER = 0.05                # Buffer margin to keep available (5%)
MAX_MARGIN_PER_TRADE_PCT = 0.08     # Maximum margin per trade as % of NAV (8% to prevent spikes)

# =============================================================================
# DELTA HEDGING PARAMETERS
# =============================================================================
# Universal Delta Hedging (supports equity options and futures options)
DELTA_SIZING_MODE = "POINTS"        # "POINTS" or "NAV" - sizing method
DELTA_REVERT_MODE = "TARGET"        # "TARGET" or "BAND" - snap to target vs nearest band edge

# POINTS Mode: Per-asset delta units (recommended for precision)
EQUITY_DELTA_TARGET_POINTS = 5.0    # +5Δ points (= +500 shares for equity options)
EQUITY_DELTA_TOL_POINTS = 10.0      # ±10Δ points (= ±1000 shares tolerance)
FUTURES_DELTA_TARGET_CONTRACTS = 0.0  # Target delta in contracts (often neutral)
FUTURES_DELTA_TOL_CONTRACTS = 3.0   # ±3 contracts tolerance

# NAV Mode: Percentage of portfolio value (portable across assets)
DELTA_TARGET_NAV_PCT_EQUITY = 0.05  # +5% of NAV long-delta target
DELTA_TOL_NAV_PCT_EQUITY = 0.10     # ±10% of NAV band
DELTA_TARGET_NAV_PCT_FUTURE = 0.00  # Often neutral for futures options
DELTA_TOL_NAV_PCT_FUTURE = 0.04     # ±4% of NAV band

# Legacy parameters (used if DELTA_SIZING_MODE != "POINTS")
TARGET_PORTFOLIO_DELTA = 500.0     # Legacy: Target portfolio delta (shares)
DELTA_TOLERANCE = 1000.0            # Legacy: Delta tolerance (shares)
HEDGE_RATIO = 1.0                   # Hedge ratio for delta adjustments
HEDGE_FREQUENCY = "EOD"             # "EOD" for end-of-day only, "INTRADAY" for real-time hedging
                                      # EOD: Faster backtests, hedges at market close using daily closing price
                                      #      Uses SecurityInitializer + ClosePriceFillModel + LimitOrders
                                      #      Prevents MOO (Market-On-Open) conversion - fills at same-day close
                                      # INTRADAY: Slower backtests, real-time hedging with actual Greeks

# =============================================================================
# EXIT STRATEGY PARAMETERS
# =============================================================================
QUICK_PROFIT_TARGET = 0.35          # Quick profit target as % of credit received (35%)
NORMAL_PROFIT_TARGET = 0.50         # Normal profit target as % of credit received (50%)
LET_EXPIRE_THRESHOLD = 0.05         # Let expire if price <= 5% of entry price
STOP_LOSS_MULTIPLIER = 2.5          # Stop loss as multiple of credit received (250%)
MIN_DTE = 5                         # Minimum DTE before rolling position (per documentation)
QUICK_PROFIT_MIN_DTE = 10           # Minimum DTE for quick profit exit
TIME_STOP_DTE = 15                   # Time stop DTE threshold (< 15 DTE and not at profit target)
TIME_STOP_ACTION = "ROLL"            # Action when time stop triggers: "ROLL" or "CLOSE"
                                              # ROLL: Close and open new position with same strike/expiration
                                              # CLOSE: Simply close the position to avoid gamma spikes

# =============================================================================
# TRADING SCHEDULE PARAMETERS
# =============================================================================
MARKET_OPEN_MINUTES = 30            # Minutes after market open to start trading

# =============================================================================
# WARMUP CONFIGURATION
# =============================================================================
WARMUP_DAYS = 5                     # Number of days to warm up before trading
WARMUP_RESOLUTION = "Daily"         # Resolution for warmup period

# =============================================================================
# DEBUG AND MONITORING PARAMETERS
# =============================================================================
DEBUG_MODE = False                  # Enable debug logging (set to False for production performance)
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