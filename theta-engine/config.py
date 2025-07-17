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
MIN_TARGET_DTE = 14                 # Minimum days to expiration for option selection
MAX_TARGET_DTE = 45                 # Maximum days to expiration for option selection
MIN_MONEYNESS = 0.70                # Minimum moneyness (strike/price) - 0.70 = 30% OTM
MAX_MONEYNESS = 0.99                # Maximum moneyness (strike/price) - 0.99 = 1% OTM
MIN_PREMIUM = 10                    # Minimum premium per contract in dollars

# =============================================================================
# POSITION SIZING PARAMETERS
# =============================================================================
MIN_BUYING_POWER = 10000            # Minimum buying power required to enter new position
MIN_CONTRACTS = 1                   # Minimum number of contracts per position
MAX_CONTRACTS = 25                  # Maximum number of contracts per position
MIN_MARGIN_PER_POSITION_PCT = 0.02  # Minimum margin per position as % of account (2%)
MARGIN_SAFETY_FACTOR = 0.8          # Safety factor for margin calculations (80% of available)
ESTIMATED_MARGIN_PCT = 0.20         # Estimated margin requirement as % of strike price (20%)
TARGET_MARGIN_USE = 0.40            # Target margin utilization as % of account (40%)
MAX_POSITIONS = 8                   # Maximum number of concurrent positions
MARGIN_BUFFER = 0.05                # Buffer margin to keep available (5%)

# =============================================================================
# DELTA HEDGING PARAMETERS
# =============================================================================
TARGET_PORTFOLIO_DELTA = 5.0        # Target portfolio delta (positive = long bias)
DELTA_TOLERANCE = 10.0              # Delta tolerance before hedging (shares)
HEDGE_RATIO = 1.0                   # Hedge ratio for delta adjustments

# =============================================================================
# EXIT STRATEGY PARAMETERS
# =============================================================================
QUICK_PROFIT_TARGET = 0.35          # Quick profit target as % of credit received (35%)
NORMAL_PROFIT_TARGET = 0.50         # Normal profit target as % of credit received (50%)
LET_EXPIRE_THRESHOLD = 0.05         # Let expire if price <= 5% of entry price
STOP_LOSS_MULTIPLIER = 2.5          # Stop loss as multiple of credit received (250%)
MIN_DTE = 5                         # Minimum DTE before rolling position
QUICK_PROFIT_MIN_DTE = 10           # Minimum DTE for quick profit exit

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
DEBUG_MODE = True                   # Enable debug logging
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
#
# Key benefits:
# - Reduced directional risk vs naked puts
# - Consistent premium income from theta decay
# - Systematic position sizing and risk management
# - Automated delta hedging for market neutrality
# ============================================================================= 