# Development Guide

## Table of Contents
- [Architecture Overview](#architecture-overview)
- [Framework vs Strategy Separation](#framework-vs-strategy-separation)
- [Creating New Strategies](#creating-new-strategies)
- [Understanding Logs](#understanding-logs)
- [Extending the System](#extending-the-system)

---

## Architecture Overview

### Clean Modular Architecture

The system follows a clean layered architecture with clear separation of concerns:

```
Strategy Layer - Pure signal generation:
├── strategy_base.py      # EntryIntent/ExitIntent interfaces
├── theta_engine.py        # Primary systematic put selling strategy
├── ssvi_strategy.py       # SSVI-based relative value strategy
└── strategy_sell_puts.py  # Legacy strategy (deprecated)

Risk Layer - Position sizing and risk management:
├── risk_manager.py           # Position sizing, margin analysis, dynamic scaling
├── exit_rules.py             # Exit conditions, profit targets, stop losses
└── intraday_risk_monitor.py  # Real-time risk monitoring, margin call prevention

Execution Layer - Order management and fills:
├── order_manager.py       # Order placement facade
├── position_management.py # Position entry validation and tracking
├── fillmodels.py          # Custom MidHaircutFillModel
├── phase_executor.py      # P0/P1/P2 execution flow orchestration
└── Order Consistency: ALL options use Limit orders (entry, exit, risk, P2)

Data Layer - Unified data access:
├── greeks_provider.py        # Unified Greeks access (formerly VolModel)
├── options_data_manager.py   # Greeks caching and chain snapshots
└── option_filters.py         # Centralized option filtering utilities

Analytics Layer - Performance and reporting:
├── analytics.py           # Performance tracking, delta bands analysis, EOD Greeks
└── pnl_explainer.py       # PnL attribution with underlying price tracking

Hedging Layer - Dynamic risk management:
└── delta_hedging.py       # Universal delta hedging (TRADE/NAV/POINTS modes)

Core Engine:
└── main.py                # Orchestrator: scheduling, module wiring, lifecycle
```

### Complete Engine Flow

1. **Strategy Selection**: `strategy.select_entries(chain, ctx)` → EntryIntent objects
2. **Risk Analysis**: `risk_manager.calculate_position_size()` → margin-aware sizing with dynamic scaling
3. **Position Validation**: `position_management.try_enter_position()` → tradability checks
4. **Order Execution**: `order_manager.place_entries()` → submits limit orders
5. **Per-Trade Hedging**: `delta_hedging.execute_delta_hedge_for_trade()` → hedges new positions
6. **Portfolio Rebalancing (P2)**: `analytics.delta_bands()` + `delta_hedger.execute_delta_hedge_universal()` → maintains target delta
   - **Delta Band Analysis**: Calculate current portfolio delta vs. target bands (NAV mode: 5% ± 10% of NAV)
   - **Margin-Aware Decision**: Project margin for underlying hedge, check against overnight margin max (95%)
   - **Decision Tree**: If margin OK → hedge with underlying; if margin exceeds limit → reduce option positions
   - **Option Reduction**: Hybrid scoring (delta 40%, margin 30%, risk 30%), reduce up to 20% per position
   - **Boundary Hedging**: Hedge to nearest band edge when outside bounds (not center)
7. **Intraday Risk Monitoring**: `intraday_risk_monitor.check_risk()` → monitors margin utilization and portfolio loss
8. **Risk Monitoring**: `exit_rules.check_exit_conditions()` → manages exits/rolls
9. **Data Access**: `greeks_provider.get_delta()` → provides Greeks throughout
10. **EOD Reporting (16:00)**: `analytics.log_eod_greeks()` → comprehensive portfolio summary with all four Greeks (Δ, Γ, Θ, ν)
11. **PnL Attribution**: `pnl_explainer.explain_daily_pnl()` → tracks underlying price movements and Greek contributions

---

## Framework vs Strategy Separation

### The Problem (Before Refactor)

The theta strategy scoring logic was embedded in infrastructure code:

```
position_management.py (infrastructure)
└── select_best_option()  ❌ HARDCODED THETA STRATEGY
    ├── Score: premium / (margin * DTE)
    ├── Target: 18-25Δ
    └── Target: 30-45 DTE
```

**Issue:** To plug in SSVI strategy, you'd have to modify `PositionManager` (infrastructure), which defeats the purpose of having a pluggable strategy system.

### The Solution (After Refactor)

Clean separation between **reusable framework** and **pluggable strategies**:

```
FRAMEWORK (strategy-agnostic)          STRATEGIES (pluggable)
├── main.py                            ├── theta_engine.py
│   └── P0-P2 execution phases         │   └── Premium-per-day scoring
├── position_management.py             ├── ssvi_strategy.py
│   ├── find_tradable_options()        │   └── Vol surface arbitrage
│   ├── try_enter_position()           └── [your_strategy.py]
│   └── track positions                    └── Your custom logic
├── delta_hedging.py
├── exit_rules.py
├── risk_manager.py
└── ... (all other modules)
```

### Framework Layers

#### Layer 1: Execution Framework (P0-P2)

**File:** `main.py`

**Responsibilities:**
- P0 (15:45): Process exits based on exit rules
- P1 (15:50): Execute new trades + per-trade hedges
- P2 (15:55): Portfolio rebalancing
- Orchestrate all modules

**Strategy-agnostic:** Works the same for theta, SSVI, or any strategy.

#### Layer 2: Infrastructure Modules

**Files:** `position_management.py`, `delta_hedging.py`, `exit_rules.py`, `risk_manager.py`, etc.

**PositionManager responsibilities:**
- `find_tradable_options()`: Filter for liquidity, spreads, basic criteria
- `try_enter_position()`: Execute orders, size positions
- Track positions in dictionary
- Manage diversification (expiry spacing, strike spacing)

**What PositionManager does NOT do:**
- ❌ Score options (that's strategy-specific)
- ❌ Pick which option to trade (that's strategy-specific)
- ❌ Define target delta/DTE ranges (that's strategy-specific)

#### Layer 3: Strategy Plugins

**Files:** `theta_engine.py`, `ssvi_strategy.py`

**Strategy responsibilities:**
- Implement `select_entries()`: Find and score candidates
- Define scoring logic (THIS IS THE STRATEGY)
- Return `EntryIntent` objects

**Example - Theta Strategy:**
```python
def _score_and_select(self, candidates, ctx):
    """Score by: premium / (margin * DTE) with delta/DTE targets"""
    for c in candidates:
        score = (c['premium'] / (margin * c['dte'])) * delta_mult * dte_mult
        # Select highest score
```

**Example - SSVI Strategy:**
```python
def _ssvi_arbitrage_score(self, candidates, ctx):
    """Score by: vol surface mispricing vs SSVI model"""
    for c in candidates:
        model_iv = ssvi_model(c['strike'], c['dte'])
        mispricing = abs(c['market_iv'] - model_iv)
        score = mispricing * vega * mean_reversion_speed
        # Select highest arbitrage opportunity
```

### What Goes Where?

#### Infrastructure (PositionManager, etc.)

✅ **Belongs in Infrastructure:**
- Filter by liquidity (bid-ask spreads)
- Filter by data quality
- Calculate position sizes
- Execute orders
- Track positions
- Manage diversification constraints
- Calculate margin requirements

#### Strategy (ThetaEngine, SSVI, etc.)

✅ **Belongs in Strategy:**
- Scoring logic (what makes an option attractive?)
- Target parameters (what delta/DTE do I want?)
- Selection criteria (theta efficiency? vol arbitrage? carry?)
- Trade sizing preferences (aggressive? conservative?)

---

## Creating New Strategies

### Step-by-Step Guide

1. **Create strategy file** (e.g., `my_strategy.py`)

```python
from strategy_base import StrategyBase, StrategyContext, EntryIntent

class MyStrategy(StrategyBase):
    def select_entries(self, option_chain, ctx: StrategyContext):
        # Get infrastructure-filtered candidates
        candidates = ctx.algorithm.position_manager.find_tradable_options(chain)
        
        # YOUR STRATEGY LOGIC HERE
        best = self._my_custom_scoring(candidates, ctx)
        
        return [EntryIntent(candidate=best)] if best else []
    
    def _my_custom_scoring(self, candidates, ctx):
        # Score based on YOUR criteria
        # - Momentum signals?
        # - Volatility regime?
        # - Greeks ratios?
        # - Machine learning predictions?
        for c in candidates:
            score = your_custom_logic(c)
        return best_candidate
```

2. **Update config:**
   - `config.json`: `"strategy_module": "my_strategy"`
   - Or parameter: `--strategy-module my_strategy`

3. **Run backtest** - framework handles everything else!

### Switching Strategies

#### Current (ThetaEngine)
No changes needed - strategy already loaded by default.

#### Switch to SSVI
```json
// config.json
{
  "strategy_module": "ssvi_strategy"
}
```

Or command line:
```bash
--strategy-module ssvi_strategy
```

### Benefits of This Architecture

#### For Development
- ✅ Test strategies independently
- ✅ Swap strategies without touching infrastructure
- ✅ Reuse all framework code (P0-P2, hedging, exits, risk, analytics)
- ✅ Debug strategy vs infrastructure issues separately

#### For Testing
- ✅ Unit test strategies in isolation
- ✅ A/B test different strategies on same data
- ✅ Compare theta vs SSVI vs custom strategies

#### For Production
- ✅ Run multiple strategies in parallel
- ✅ Update strategy logic without redeploying framework
- ✅ Strategy-specific parameters isolated from framework config

---

## Understanding Logs

### Log Format Overview

The system uses clear, structured logging to help you understand what's happening at each step:

```
2015-01-02 15:50:00 === P1A: STRATEGY EVAL ===
2015-01-02 15:50:00 Finding options: Price=$103.17, DTE=21-105
2015-01-02 15:50:00 Option filtering (OnData chain): 23 total, 23 puts
2015-01-02 15:50:00   Filtered OUT: Moneyness=5, DTE=12, Premium=0, Spread=0, DeltaBand=1
2015-01-02 15:50:00   ✅ PASSED all filters: 5 candidates
2015-01-02 15:50:00   📊 Scoring: Selected BEST option from 5 candidates (premium-per-margin ranking)
2015-01-02 15:50:00 P1A: Strategy selected 1 BEST option(s) from filtered candidates
```

### What Each Line Means

#### 1. Chain Summary
```
Option filtering (OnData chain): 23 total, 23 puts
```
- **23 total**: Total option contracts in the chain
- **23 puts**: Number of put options (should match total since we filter PutsOnly)

#### 2. Filter Results (Rejected Contracts)
```
Filtered OUT: Moneyness=5, DTE=12, Premium=0, Spread=0, DeltaBand=1
```
**These numbers show contracts REJECTED by each filter:**
- **Moneyness=5**: 5 contracts too far OTM/ITM (outside 0.50-0.99 strike/spot range)
- **DTE=12**: 12 contracts wrong expiration (outside 21-105 day range)
- **Premium=0**: 0 contracts too cheap (premium < 0.2% of underlying price)
- **Spread=0**: 0 contracts too illiquid (bid-ask spread too wide)
- **DeltaBand=1**: 1 contract outside delta band (|delta| not in 0.18-0.32 range)

**Math Check:** 23 total - 5 - 12 - 0 - 0 - 1 = **5 candidates passed**

#### 3. Candidates That Passed
```
✅ PASSED all filters: 5 candidates
```
- **5 candidates**: These options passed ALL filters and are eligible for trading
- These move to the scoring phase

#### 4. Best Option Selection
```
📊 Scoring: Selected BEST option from 5 candidates (premium-per-margin ranking)
```
- **Scoring Method**: Premium-per-margin ratio (premium collected / margin required)
- **Result**: The HIGHEST scoring option is selected
- **Bonuses Applied**:
  - DTE bucket bonus (if in today's target bucket)
  - Expiry distribution bonus (prefers unexpired expirations)
  - Spread quality bonus (tighter spreads score higher)

#### 5. Final Selection
```
P1A: Strategy selected 1 BEST option(s) from filtered candidates
```
- **1 option**: The strategy returns this single best option for execution
- This is normal behavior - we trade the best opportunity, not all candidates

### Understanding the Flow

```
23 contracts in chain
    ↓
Filter by Moneyness → 18 remain (5 rejected)
    ↓
Filter by DTE → 6 remain (12 rejected)
    ↓
Filter by Premium → 6 remain (0 rejected)
    ↓
Filter by Spread → 6 remain (0 rejected)
    ↓
Filter by Delta Band → 5 remain (1 rejected)
    ↓
Score 5 candidates by premium-per-margin
    ↓
Select TOP 1 for trading
```

### Common Patterns

#### Many Candidates Found
```
Filtered OUT: Moneyness=3, DTE=5, Premium=0, Spread=0, DeltaBand=2
✅ PASSED all filters: 13 candidates
```
✅ **GOOD**: Many options meet criteria, strong selection pool

#### Few Candidates Found
```
Filtered OUT: Moneyness=8, DTE=12, Premium=0, Spread=1, DeltaBand=1
✅ PASSED all filters: 1 candidates
```
⚠️ **WARNING**: Limited selection, may need to adjust filters

#### No Candidates Found
```
Filtered OUT: Moneyness=15, DTE=8, Premium=0, Spread=0, DeltaBand=0
❌ NO CANDIDATES: Price=$103.17, Moneyness=0.50-0.99, DTE=21-105, DeltaBand=0.18-0.32
```
❌ **BAD**: No options meet criteria, filters may be too strict

### Key Takeaways

1. **Filter Numbers = REJECTED**: High numbers mean many contracts don't meet criteria
2. **5-10 Candidates = Healthy**: Good selection pool for premium-per-margin scoring
3. **1 Selected = Normal**: Strategy picks the BEST option, not all candidates
4. **0 Candidates = Problem**: Filters too restrictive or market conditions extreme

### Debugging Tips

**If you see 0 candidates:**
1. Check which filter has the highest rejection count
2. Most common culprits:
   - **DTE filter**: Market may lack options in 21-105 day range
   - **Moneyness filter**: Options too far OTM/ITM
   - **DeltaBand filter**: Delta values outside 0.18-0.32 range

**If you see 1 candidate consistently:**
- This might be normal in low-volatility periods
- Consider widening filters slightly if desired

**If you see too many candidates (>20):**
- Filters may be too loose
- Consider tightening moneyness or delta band ranges

---

## Extending the System

### Add Strategies
Implement `StrategyBase` in new files, update main.py strategy loading. See "Creating New Strategies" section above.

### Modify Risk Logic
Update `risk_manager.py` for different sizing algorithms:
- Position sizing multipliers
- Margin utilization targets
- Dynamic scaling thresholds

### Add Data Sources
Extend `greeks_provider.py` for additional data providers:
- Alternative pricing models
- External volatility feeds
- Custom Greek calculations

### Custom Analytics
Add new metrics to `analytics.py` and `pnl_explainer.py`:
- Additional performance metrics
- Custom risk measures
- Portfolio attribution
- Enhanced PnL breakdown with underlying price tracking
- Greek contribution analysis (Delta, Gamma, Theta, Vega)

### Alternative Hedging
Modify `delta_hedging.py` for different risk management approaches:
- Gamma hedging
- Vega hedging
- Custom hedge instruments

### Custom Risk Monitoring
Extend `intraday_risk_monitor.py` for additional risk metrics:
- VaR calculations
- Stress testing
- Scenario analysis

**Note:** All options orders in risk monitor use Limit orders with mid ± haircut*spread pricing, maintaining consistency with entry/exit logic. Only equity hedges use Market orders.

### Performance Tuning
Adjust cache sizes and cleanup intervals in `config.py`:
- `GREEKS_SNAPSHOT_INTERVAL_MINUTES`
- `GREEKS_CACHE_MAX_ENTRIES`
- `POSITION_CLEANUP_DAYS`
- `CHAIN_SNAPSHOT_MAX_ENTRIES`

---

## Data Architecture & Performance

### Greeks Data Hierarchy

**OnData Chain** (PREFERRED): Real-time Greeks from QC's pricing model, captured during execution phases (15:45/15:50/15:55/15:59). Source: `QC-CHAIN` or `QC-CHAIN-CACHED (N bars)`.

**Securities Greeks** (FALLBACK): Irregularly updated by QC's internal model, may be stale or None. Source: `QC-SECURITY`.

**Cache Strategy**: 15-minute throttling reduces processing from 390/day to ~29/day (93% reduction). EOD exception at 15:59 ensures fresh Greeks for 16:00 reporting.

### Throttling Impact
- **Performance**: Multi-year backtests reduced from DAYS to HOURS
- **Memory**: 90% reduction (2000 → 200 cache entries)
- **Accuracy**: EOD Greeks are 1 bar old (15:59 → 16:00) vs 4 bars without refresh

### Implementation Modules
- `options_data_manager.py`: Throttling logic, data source hierarchy
- `data_processor.py`: OnData timing gates, execution phase control
- `analytics.py`: Greeks consumption, EOD reporting with all four Greeks (Δ, Γ, Θ, ν)
- `pnl_explainer.py`: PnL attribution with underlying price tracking and QC raw Greeks comparison

### EOD Reporting Enhancement
- **Timing**: EOD logs now run at 16:00 (4 PM market close) instead of midnight
- **Complete Greeks**: All four main Greeks (Delta, Gamma, Theta, Vega) logged for each position
- **Underlying Price Tracking**: Shows current price, previous day price, change, and change %
- **QC Raw Greeks**: PnL explainer compares calculated Greeks vs QC raw Greeks for troubleshooting
- **Format**: `UNDERLYING QQQ: $103.93 | Prev: $102.14 | Change: $+1.79 (+1.75%)`

See module docstrings for comprehensive technical documentation.

---

## Refactoring History

### What Changed

Moved option scoring logic from infrastructure (`PositionManager`) to strategy modules (`ThetaEngineStrategy`).

### Files Modified

#### 1. `theta_engine.py` ✅
**Added:** `_score_and_select()` method with theta-specific scoring
- Premium-per-day efficiency calculation
- Delta targeting (18-25Δ)
- DTE targeting (30-45 days)
- Spread quality penalties
- Expiry diversification

#### 2. `position_management.py` ✅
**Removed:** `select_best_option()` method
- This was strategy-specific logic
- Replaced with comment explaining architecture

**Kept:** All infrastructure methods
- `find_tradable_options()`: Generic filtering
- `try_enter_position()`: Execution
- Position tracking dictionary

#### 3. `ssvi_strategy.py` ✅ NEW
**Created:** Template SSVI strategy to demonstrate plug-in architecture
- Shows completely different scoring approach
- Vol surface arbitrage vs theta decay
- Same infrastructure, different strategy

### Migration Notes

If you have custom code calling `position_manager.select_best_option()`:
- ❌ Old: `best = position_manager.select_best_option(candidates)`
- ✅ New: Call strategy directly or implement scoring in your strategy module

The method has been removed because it contained theta-specific logic that doesn't belong in infrastructure.

---

## Design Decisions

### Option Scoring: Premium-Per-Day vs Premium-Per-Margin

**The Problem:**
Original scoring used `premium / margin` which created an inherent ATM bias:
- ATM options have 2-3x higher premiums than 20Δ options
- Margin requirements don't scale proportionally
- Result: System consistently selected 27-30Δ options despite targeting 18-25Δ

**The Solution:**
New scoring uses `premium / (margin * DTE)` which:
- ✅ **Naturally time-normalized** - eliminates short-DTE bias
- ✅ **Stable** - uses actual market prices, not estimated Greeks
- ✅ **Simple** - daily return on capital, easy to interpret
- ✅ **Robust** - immune to Greek calculation quirks
- ✅ **Aligned** - measures "profit per dollar per day"

**Target Matching:**
Instead of complex penalties, discrete multiplier bands:
- **Delta**: 18-25Δ = 1.0×, 15-28Δ = 0.85×, outside = 0.50×
- **DTE**: 30-45d = 1.0×, 21-60d = 0.90×, outside = 0.70×
- **Spread**: ≤5% = 1.0×, ≤10% = 0.95×, >10% = 0.85×
- **Expiry**: New = 1.0×, existing = 0.95× (diversification)

**Why Not Complex Multi-Factor Scoring?**
- ❌ Requires tuning multiple weights (w1, w2, w3, w4)
- ❌ Needs z-score normalization across different units
- ❌ Harder to reason about and debug
- ✅ Premium-per-day with discrete bands captures 95% benefit with 20% complexity

**Expected Behavior:**
- Before: Typical 27-30Δ, 70-100 DTE selections
- After: Consistent 18-25Δ, 30-45 DTE selections aligned with strategy targets

---

**For more information, see the main [README.md](README.md) or [STATUS.md](STATUS.md)**

