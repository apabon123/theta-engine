"""
Analytics Module - Greeks Consumption & EOD Reporting

=============================================================================
GREEKS DATA CONSUMPTION ARCHITECTURE
=============================================================================

This module is the PRIMARY CONSUMER of Greeks data for EOD reporting and
portfolio analytics. It demonstrates the complete Greeks hierarchy in action.

GREEKS SOURCE PRIORITY (Implemented in log_eod_greeks):

Priority 1: QC-CHAIN-CACHED (OnData Cache - PREFERRED)
   --------------------------------------------------------
   Source: greeks_cache[symbol] with same-day timestamp
   When Used: At EOD (16:00) after 15:59 chain refresh
   Age: Typically 1 bar (15:59 → 16:00)
   Label: "QC-CHAIN-CACHED (N bars)" where N = age in minutes
   
   WHY PREFERRED: OnData chain Greeks are the freshest data from QC's real-time
   feed. By prioritizing cached OnData Greeks, we ensure EOD reporting uses the
   most current market data available, captured just 1 minute before close.

Priority 2: QC-SECURITY (Securities Fallback)
   --------------------------------------------------------
   Source: algorithm.Securities[symbol].Greeks
   When Used: If OnData cache unavailable or stale
   Age: Variable (QC updates irregularly)
   Label: "QC-SECURITY"
   
   WHY FALLBACK: Securities Greeks are updated by QC's internal pricing model,
   but NOT guaranteed to update every bar. They may be stale or None. Only used
   when OnData cache fails, which should be rare after 15:59 refresh.

Priority 3: QC-CHAIN-STALE (Old Cache)
   --------------------------------------------------------
   Source: greeks_cache[symbol] with old timestamp (previous day)
   When Used: Last resort if both above fail
   Age: Hours to days old
   Label: "QC-CHAIN-STALE"
   
   WHY LAST RESORT: Better than nothing, but indicates data pipeline issues.
   Should rarely occur with proper EOD refresh at 15:59.

Priority 4: QC-NONE (No Data)
   --------------------------------------------------------
   Source: No Greeks available
   When Used: Complete data failure
   Values: Returns zeros (delta=0, gamma=0, theta=0, vega=0)
   Label: "QC-NONE"
   
   WHY PROBLEMATIC: Indicates serious data initialization or subscription issues.
   Investigate immediately if this appears in logs.

=============================================================================
EOD REPORTING FLOW
=============================================================================

Timeline of EOD Greeks Capture:

15:55:00 - Phase 2 portfolio rebalancing executes
15:56:00 - OnData processes chain (fill refresh after Phase 2)
         - Greeks cached with 15:56 timestamp
         - Greeks are now 0 bars old

15:57:00-15:58:00 - No chain processing (throttled)
         - Greeks age to 1-2 bars old
         
15:59:00 - OnData processes chain (EOD EXCEPTION)
         - update_chain() BYPASSES 15-minute throttling
         - Fresh Greeks captured with 15:59 timestamp
         - Greeks are now 0 bars old (CRITICAL FOR EOD)

16:00:00 - EOD reporting runs (log_eod_greeks)
         - Reads Greeks from greeks_cache (15:59 timestamp)
         - Age: 1 bar (15:59 → 16:00)
         - Source: "QC-CHAIN-CACHED (1 bars)"
         - Fresh data for accurate portfolio metrics

Without 15:59 Refresh (OLD BEHAVIOR):
15:56:00 - Last chain update
15:57:00-15:59:00 - Throttled (no updates)
16:00:00 - EOD uses 15:56 cache
         - Age: 4 bars (15:56 → 16:00)
         - Source: "QC-CHAIN-CACHED (4 bars)"
         - Stale data reduces EOD accuracy

=============================================================================
SOURCE LABEL INTERPRETATION
=============================================================================

When reviewing logs, source labels indicate data freshness:

"EOD Greeks for QQQ 150220P00099000: Δ=-0.2685 (QC-CHAIN-CACHED (1 bars))"
→ EXCELLENT: Fresh OnData Greeks from 1 bar ago (15:59)
→ Expected behavior with 15:59 EOD refresh enabled

"EOD Greeks for QQQ 150220P00099000: Δ=-0.2685 (QC-CHAIN-CACHED (4 bars))"
→ WARNING: Stale OnData Greeks from 4 bars ago (15:56)
→ Indicates 15:59 refresh failed or was throttled
→ Check: Is is_eod_time logic working in update_chain()?

"EOD Greeks for QQQ 150220P00099000: Δ=-0.2685 (QC-SECURITY)"
→ UNUSUAL: Fallback to Securities Greeks
→ Indicates OnData cache was unavailable at EOD
→ Check: Did OnData process chain at execution phases?

"EOD Greeks for QQQ 150220P00099000: Δ=-0.2685 (QC-CHAIN-STALE)"
→ PROBLEM: Using previous day's Greeks
→ Indicates no same-day cache available
→ Check: Is option chain being processed at all?

"EOD Greeks for QQQ 150220P00099000: Δ=0.0000 (QC-NONE)"
→ CRITICAL: No Greeks data available
→ Indicates serious data pipeline failure
→ Check: Option subscription, initialization, and data feed

=============================================================================
USAGE PATTERNS ACROSS MODULES
=============================================================================

1. EOD Reporting (This Module):
   - Time: 16:00 daily
   - Purpose: Portfolio summary with Greeks
   - Source: Prefers QC-CHAIN-CACHED from 15:59
   - Fallback: QC-SECURITY → QC-CHAIN-STALE → QC-NONE

2. Position Sizing (risk_manager.py):
   - Time: 15:50 during Phase 1
   - Purpose: Calculate option position sizes
   - Source: Prefers real-time OnData or recent cache
   - Fallback: Uses GreeksProvider with BS approximation

3. Delta Hedging (delta_hedging.py):
   - Time: 15:50 (P1D) and 15:55 (P2)
   - Purpose: Portfolio delta calculation
   - Source: Uses GreeksProvider (QC → QC-CHAIN → Cached)
   - Fallback: 0.25 delta approximation for stability

4. Exit Rules (exit_rules.py):
   - Time: 15:45 during Phase 0
   - Purpose: Monitor profit/loss thresholds
   - Source: Uses current option prices + cached Greeks
   - Fallback: P&L based on prices if Greeks unavailable

=============================================================================
PERFORMANCE CONSIDERATIONS
=============================================================================

Cache Hit Rates (Expected):
- During execution phases (15:45-15:55): 95%+ QC-CHAIN hit rate
- At EOD (16:00): 99%+ QC-CHAIN-CACHED hit rate (1 bar old)
- During day: 85%+ cache hit rate (depends on throttling interval)

Memory Usage:
- Greeks cache: ~200 entries (option symbols with Greeks)
- Cache entry: ~128 bytes (4 floats + timestamp + Symbol object)
- Total: ~25 KB (negligible memory footprint)

Processing Time:
- Cache lookup: O(1) dictionary access
- Greeks extraction: ~0.1ms per symbol
- EOD reporting: <10ms for typical portfolio (10-20 positions)

=============================================================================
DEBUGGING GUIDE
=============================================================================

Common Issues & Solutions:

Issue: "QC-CHAIN-CACHED (4 bars)" at EOD instead of (1 bars)
→ Solution: Check is_eod_time logic in options_data_manager.py
→ Verify: OnData is processing chain at 15:59

Issue: Frequent "QC-SECURITY" fallback during execution
→ Solution: Check OnData chain processing frequency
→ Verify: update_chain() is being called successfully

Issue: "QC-CHAIN-STALE" appearing frequently
→ Solution: Check greeks_cache timestamp updates
→ Verify: seed_active_positions() is caching Greeks

Issue: "QC-NONE" at EOD for any position
→ Solution: Check option contract initialization
→ Verify: Option is subscribed and tradable in QC

=============================================================================
"""

from AlgorithmImports import *  # noqa: F401
from typing import Optional, Tuple, Dict, List


class Analytics:
    def __init__(self, algorithm):
        self.algorithm = algorithm

    def log_eod_greeks(self):
        """Log end-of-day portfolio position summary with breakdowns"""
        hedge_positions = []
        option_positions = []

        ddelta_total = 0.0
        dgamma_total = 0.0
        dtheta_total = 0.0
        dvega_total = 0.0

        # Debug: Log position count and actual time
        if self.algorithm.debug_mode:
            actual_time = self.algorithm.Time.strftime("%Y-%m-%d %H:%M:%S")
            self.algorithm.Debug(f"EOD [actual={actual_time}]: Positions in dictionary: {len(self.algorithm.positions)}")

        for pos_id, pos in [(pid, p) for pid, p in self.algorithm.positions.items() if p.get('quantity', 0) != 0]:
            sym = pos['symbol']
            qty = pos['quantity']
            is_hedge = pos.get('is_hedge', False)

            # Handle hedge positions differently - they use the underlying symbol
            if is_hedge:
                # For hedge positions, use the underlying symbol for price and calculations
                und = self.algorithm.underlying_symbol
                if und not in self.algorithm.Securities:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"EOD SKIP: hedge underlying {und} not in Securities")
                    continue
                price = float(self.algorithm.Securities[und].Price)
                kind = 'equity' if self.algorithm.Securities[und].Symbol.SecurityType == SecurityType.Equity else 'future'
                mult = self.algorithm.Securities[und].SymbolProperties.ContractMultiplier or 1.0
                per = 100.0 if kind == 'equity' else 1.0
            else:
                # For option positions, use the symbol directly
                if sym not in self.algorithm.Securities:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"EOD SKIP: {sym} not in Securities")
                    continue

                und = sym.Underlying if hasattr(sym, 'Underlying') else self.algorithm.underlying_symbol
                if und not in self.algorithm.Securities:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"EOD SKIP: underlying {und} not in Securities")
                    continue

                price = float(self.algorithm.Securities[und].Price)
                kind = 'equity' if self.algorithm.Securities[und].Symbol.SecurityType == SecurityType.Equity else 'future'
                mult = self.algorithm.Securities[und].SymbolProperties.ContractMultiplier or 1.0
                per = 100.0 if kind == 'equity' else 1.0

            # Calculate Greeks - PREFER OnData chain cache, fallback to Securities
            if is_hedge:
                # Hedge positions are equity positions with delta = 1.0
                delta = 1.0
                gamma = 0.0
                theta = 0.0
                vega = 0.0
                greek_source = "HEDGE"
            elif sym.SecurityType == SecurityType.Option:
                # PRIORITY 1: Try cached Greeks from OnData chain (same-day)
                cached = getattr(self.algorithm, 'greeks_cache', {}).get(sym, None)
                if cached and cached[1] and cached[1].date() == self.algorithm.Time.date():
                    if len(cached[0]) >= 4:  # Check if vega is available in cache
                        dval, gval, tval, vval = cached[0]
                        vega = float(vval if vval is not None else 0.0)
                    else:  # Fallback for old cache format
                        dval, gval, tval = cached[0]
                        vega = 0.0
                    delta = float(dval if dval is not None else 0.0)
                    gamma = float(gval if gval is not None else 0.0)
                    theta = float(tval if tval is not None else 0.0)
                    greek_source = "QC-CHAIN-CACHED"
                    try:
                        if hasattr(self.algorithm, 'options_data'):
                            age_min = self.algorithm.options_data.get_cache_age_minutes(sym)
                            if age_min is not None:
                                greek_source = f"QC-CHAIN-CACHED ({int(age_min)} bars)"
                    except Exception:
                        pass
                else:
                    # PRIORITY 2: Fallback to Securities Greeks (may be stale)
                    greeks = getattr(self.algorithm.Securities[sym], 'Greeks', None)
                    if greeks and greeks.Delta is not None:
                        delta = float(greeks.Delta)
                        gamma = float(greeks.Gamma) if greeks.Gamma is not None else 0.0
                        theta = float(greeks.Theta) if greeks.Theta is not None else 0.0
                        vega = float(greeks.Vega) if hasattr(greeks, 'Vega') and greeks.Vega is not None else 0.0
                        greek_source = "QC-SECURITY"
                    else:
                        # PRIORITY 3: Use stale cache if available
                        cached_any = getattr(self.algorithm, 'greeks_cache', {}).get(sym, None)
                        if cached_any:
                            if len(cached_any[0]) >= 4:  # Check if vega is available in cache
                                dval, gval, tval, vval = cached_any[0]
                                vega = float(vval if vval is not None else 0.0)
                            else:  # Fallback for old cache format
                                dval, gval, tval = cached_any[0]
                                vega = 0.0
                            delta = float(dval if dval is not None else 0.0)
                            gamma = float(gval if gval is not None else 0.0)
                            theta = float(tval if tval is not None else 0.0)
                            greek_source = "QC-CHAIN-STALE"
                            if self.algorithm.debug_mode:
                                try:
                                    ts = cached_any[1]
                                    age_min = int((self.algorithm.Time - ts).total_seconds() // 60) if ts else None
                                    self.algorithm.Debug(f"EOD: Using STALE cached greeks for {sym} (age={age_min} min)")
                                except Exception:
                                    pass
                        else:
                            delta = 0.0
                            gamma = 0.0
                            theta = 0.0
                            vega = 0.0
                            greek_source = "QC-NONE"

                # Log EOD Greeks with vega for PnL attribution
                self.algorithm.Debug(f"EOD Greeks for {sym}: Δ={delta:.4f}, Γ={gamma:.6f}, Θ={theta:.6f}, ν={vega:.6f} ({greek_source})")
            else:
                # This should not happen with the new logic above
                delta = 1.0
                gamma = 0.0
                theta = 0.0
                vega = 0.0

            # Dollar Greeks
            if is_hedge:
                # Hedge positions are equity positions
                ddelta_usd = delta * qty * price
                dgamma_usd = gamma * qty * (price ** 2)
                dtheta_usd = theta * qty
                dvega_usd = vega * qty
            elif sym.SecurityType == SecurityType.Option:
                ddelta_usd = delta * qty * per * price
                # Gamma: rate of change of delta with respect to price (price^2 scaling)
                dgamma_usd = gamma * qty * per * (price ** 2)
                # QC Theta appears to be 100x too large - divide by 100 to get realistic decay
                dtheta_usd = theta * qty / 100
                # QC Vega appears to be scaled incorrectly - divide by 100
                dvega_usd = vega * qty / 100
            else:
                ddelta_usd = delta * qty * price
                dgamma_usd = gamma * qty * (price ** 2)
                dtheta_usd = theta * qty
                dvega_usd = vega * qty

            ddelta_total += ddelta_usd
            dgamma_total += dgamma_usd
            dtheta_total += dtheta_usd
            dvega_total += dvega_usd

            # For hedge positions, use the underlying symbol for display
            display_symbol = und if is_hedge else sym
            pos_info = {
                'symbol': display_symbol,
                'quantity': qty,
                'delta_usd': ddelta_usd,
                'gamma_usd': dgamma_usd,
                'theta_usd': dtheta_usd,
                'vega_usd': dvega_usd,
                'entry_price': pos.get('entry_price', 0)
            }

            # Debug hedge classification
            if self.algorithm.debug_mode:
                symbol_type = "UNKNOWN"
                security_type_check = False
                try:
                    symbol_type = str(sym.SecurityType)
                    security_type_check = (sym.SecurityType == SecurityType.Equity)
                except:
                    pass
                # Removed verbose EOD CLASSIFY, EOD DATA CHECK, and EOD CONDITION logging

            # Handle classification: hedge positions are always equities, even if symbol not in Securities
            if is_hedge or (sym in self.algorithm.Securities and sym.SecurityType == SecurityType.Equity):
                hedge_positions.append(pos_info)
                # Hedge position added
            else:
                option_positions.append(pos_info)
                # Option position added

        # Hedge positions are already processed in the main loop above
        # No need to include additional hedge positions to avoid double counting

        # Enhanced EOD summary with all Greeks in single line format
        self.algorithm.Debug("=== EOD POSITION SUMMARY ===")
        
        # Display hedge positions
        if hedge_positions:
            self.algorithm.Debug("HEDGE POSITIONS:")
            for pos in hedge_positions:
                symbol = pos['symbol']
                qty = pos['quantity']
                entry_price = pos['entry_price']
                delta_usd = pos['delta_usd']
                gamma_usd = pos['gamma_usd']
                theta_usd = pos['theta_usd']
                vega_usd = pos['vega_usd']
                
                if entry_price > 0:
                    self.algorithm.Debug(f"  {symbol}: {qty} @ ${entry_price:.2f} (Δ${delta_usd:,.0f} | Γ${gamma_usd:,.0f} | Θ${theta_usd:,.0f} | ν${vega_usd:,.0f})")
                else:
                    self.algorithm.Debug(f"  {symbol}: {qty} @ N/A (Δ${delta_usd:,.0f} | Γ${gamma_usd:,.0f} | Θ${theta_usd:,.0f} | ν${vega_usd:,.0f})")
        
        # Display option positions
        if option_positions:
            self.algorithm.Debug("OPTION POSITIONS:")
            for pos in option_positions:
                symbol = pos['symbol']
                qty = pos['quantity']
                entry_price = pos['entry_price']
                delta_usd = pos['delta_usd']
                gamma_usd = pos['gamma_usd']
                theta_usd = pos['theta_usd']
                vega_usd = pos['vega_usd']
                
                if entry_price > 0:
                    self.algorithm.Debug(f"  {symbol}: {qty} @ ${entry_price:.2f} (Δ${delta_usd:,.0f} | Γ${gamma_usd:,.0f} | Θ${theta_usd:,.0f} | ν${vega_usd:,.0f})")
                else:
                    self.algorithm.Debug(f"  {symbol}: {qty} @ N/A (Δ${delta_usd:,.0f} | Γ${gamma_usd:,.0f} | Θ${theta_usd:,.0f} | ν${vega_usd:,.0f})")
        
        # Display portfolio totals in single line
        self.algorithm.Debug("PORTFOLIO TOTALS:")
        self.algorithm.Debug(f"  DDelta: ${ddelta_total:,.0f} | DGamma: ${dgamma_total:,.0f} | DTheta: ${dtheta_total:,.0f} | DVega: ${dvega_total:,.0f}")
        
        # Generate PnL explanation if PnL explainer is available
        self._generate_pnl_explanation(option_positions, hedge_positions)

    def _generate_pnl_explanation(self, option_positions: List[Dict], hedge_positions: List[Dict]):
        """
        Generate detailed PnL explanation using PnL Explainer module.
        
        Args:
            option_positions: List of option position dictionaries
            hedge_positions: List of hedge position dictionaries
        """
        try:
            # Check if PnL explainer is available
            if not hasattr(self.algorithm, 'pnl_explainer'):
                # Initialize PnL explainer if not exists
                PnLExplainer = self._get_pnl_explainer_class()
                if PnLExplainer is None:
                    self.algorithm.Debug("PnL Explainer not available - skipping PnL explanation")
                    return
                self.algorithm.pnl_explainer = PnLExplainer(self.algorithm)
            
            # Get current QuantConnect portfolio value
            qc_portfolio_value = float(self.algorithm.Portfolio.TotalPortfolioValue)
            
            # Generate PnL explanation
            explanation = self.algorithm.pnl_explainer.explain_daily_pnl(
                date=self.algorithm.Time,
                option_positions=option_positions,
                hedge_positions=hedge_positions,
                qc_portfolio_value=qc_portfolio_value
            )
            
            # Generate and log the PnL report
            pnl_report = self.algorithm.pnl_explainer.generate_pnl_report(self.algorithm.Time)
            
            # Condensed PnL explanation with entry/current prices for manual verification
            self.algorithm.Debug("")
            self.algorithm.Debug("=" * 60)
            self.algorithm.Debug("PnL EXPLANATION")
            self.algorithm.Debug("=" * 60)
            
            # QC Reconciliation (condensed)
            qc_rec = explanation['qc_reconciliation']
            self.algorithm.Debug(f"QC: ${qc_rec['qc_portfolio_value']:,.0f} | Attributed: ${qc_rec['attributed_pnl']:,.0f} | Var: ${qc_rec['variance']:,.0f} ({qc_rec['variance_pct']:.1f}%) | {qc_rec['reconciliation_quality']}")
            
            # Option PnL breakdown (condensed with prices)
            opt_pnl = explanation['option_pnl']
            self.algorithm.Debug(f"OPTIONS: Total=${opt_pnl['total_pnl']:,.0f} | Δ=${opt_pnl['total_delta_pnl']:,.0f} | Γ=${opt_pnl['total_gamma_pnl']:,.0f} | Θ=${opt_pnl['total_theta_pnl']:,.0f} | ν=${opt_pnl['total_vega_pnl']:,.0f}")
            
            # Individual option positions with entry/current prices
            if opt_pnl['positions']:
                for pos in opt_pnl['positions']:
                    entry_price = pos.get('entry_price', 0)
                    current_price = pos.get('current_price', 0)
                    price_change = pos.get('price_change', 0)
                    self.algorithm.Debug(f"  {pos['symbol']}: ${pos['total_pnl']:,.0f} | Entry: ${entry_price:.2f} → Current: ${current_price:.2f} (Δ${price_change:.2f}) | Δ=${pos['delta_pnl']:,.0f} Γ=${pos['gamma_pnl']:,.0f} Θ=${pos['theta_pnl']:,.0f}")
            
            # Hedge PnL breakdown (condensed)
            hedge_pnl = explanation['hedge_pnl']
            if hedge_pnl['total_pnl'] != 0 or hedge_pnl['positions']:
                self.algorithm.Debug(f"HEDGES: Total=${hedge_pnl['total_pnl']:,.0f} | Price=${hedge_pnl['total_price_pnl']:,.0f} | Div=${hedge_pnl['total_dividend_pnl']:,.0f} | Cost=${hedge_pnl['total_borrowing_cost']:,.0f}")
                
                # Individual hedge positions with entry/current prices
                if hedge_pnl['positions']:
                    for pos in hedge_pnl['positions']:
                        entry_price = pos.get('entry_price', 0)
                        current_price = pos.get('current_price', 0)
                        price_change = pos.get('price_change', 0)
                        self.algorithm.Debug(f"  {pos['symbol']}: ${pos['total_pnl']:,.0f} | Entry: ${entry_price:.2f} → Current: ${current_price:.2f} (Δ${price_change:.2f}) | Price=${pos['price_pnl']:,.0f}")
            
            # Summary (condensed)
            total_attributed = explanation['total_attributed_pnl']
            
            if abs(total_attributed) > 0.01:
                opt_contrib = opt_pnl['total_pnl'] / total_attributed * 100
                hedge_contrib = hedge_pnl['total_pnl'] / total_attributed * 100
                self.algorithm.Debug(f"TOTAL: ${total_attributed:,.0f} | Options: {opt_contrib:.0f}% | Hedges: {hedge_contrib:.0f}%")
            else:
                self.algorithm.Debug(f"TOTAL: ${total_attributed:,.0f} | No PnL attribution")
            
            self.algorithm.Debug("=" * 60)
            
        except Exception as e:
            self.algorithm.Debug(f"PnL Explanation Error: {str(e)}")
            # Continue without PnL explanation if there's an error

    def _get_pnl_explainer_class(self):
        """
        Safely import PnLExplainer class with multiple fallback strategies.
        
        Returns:
            PnLExplainer class if successful, None if all imports fail
        """
        try:
            # Strategy 1: Direct import (same directory)
            from pnl_explainer import PnLExplainer
            return PnLExplainer
        except ImportError:
            pass
        
        try:
            # Strategy 2: Absolute import with full module path
            from volatility_hedged_theta_engine.pnl_explainer import PnLExplainer
            return PnLExplainer
        except ImportError:
            pass
        
        try:
            # Strategy 3: Import from current module's directory
            import sys
            import os
            current_dir = os.path.dirname(os.path.abspath(__file__))
            if current_dir not in sys.path:
                sys.path.insert(0, current_dir)
            from pnl_explainer import PnLExplainer
            return PnLExplainer
        except ImportError:
            pass
        
        # All import strategies failed
        return None

    def delta_bands(self):
        """
        Check if portfolio delta is outside tolerance bands.
        Returns True if rebalancing is needed.
        """
        try:
            # Use the delta hedger to compute current delta groups
            if not hasattr(self.algorithm, 'delta_hedger') or not self.algorithm.delta_hedger:
                return False
                
            # Include today's new trades in delta calculation to prevent double-hedging
            pending_trades = getattr(self.algorithm, 'todays_new_trades', [])
            pending_list = []
            # Removed redundant debug log for pending trades count
            for intent in pending_trades:
                if hasattr(intent, 'candidate') and intent.candidate:
                    candidate = intent.candidate
                    symbol = candidate.get('symbol')
                    target_qty = candidate.get('target_contracts', 0)
                    cached_delta = candidate.get('delta', 0.0)
                    
                    # CRITICAL FIX: Check if this trade is already filled in QC Portfolio
                    # If it's filled, don't count it as pending to avoid double-counting
                    already_filled = False
                    if symbol and symbol in self.algorithm.Portfolio:
                        holding = self.algorithm.Portfolio[symbol]
                        if holding.Invested and abs(holding.Quantity) > 0:
                            already_filled = True
                            # Removed redundant debug log for already filled trades
                    
                    # Use the already calculated target_contracts from try_enter_position
                    if symbol and target_qty != 0 and not already_filled:
                        pending_list.append((symbol, target_qty, cached_delta))
                        # Removed redundant debug log for pending trade addition
            
            # CRITICAL FIX: Use the same calculation as Phase 2A - no pending list to avoid double-counting
            # The filled positions are already in QC Portfolio, so we don't need to add pending trades
            groups = self.algorithm.delta_hedger.compute_delta_groups()

            # Log total portfolio delta (using dollar delta, not notional)
            # CRITICAL FIX: Use the separate dollar_delta field that properly handles options vs equity
            total_portfolio_delta = sum(g['dollar_delta'] for g in groups.values())
            
            # Removed redundant portfolio delta logging (already shown in P2A)

            for und_sym, group in groups.items():
                if group['kind'] != 'equity':  # Skip non-equity for now
                    continue
                    
                current_notional = group['notional']
                current_units = group['units']

                mode = getattr(self.algorithm, 'delta_band_mode', 'TRADE').upper()
                current_dollar_delta = group['dollar_delta']

                if mode == 'NAV':
                    # NAV mode: bands as percentages of portfolio MTM
                    nav = float(self.algorithm.Portfolio.TotalPortfolioValue)
                    target_notional = nav * float(getattr(self.algorithm, 'delta_target_nav_pct_equity', 0.05))
                    tolerance_notional = nav * float(getattr(self.algorithm, 'delta_tol_nav_pct_equity', 0.10))
                else:
                    # TRADE mode: bands as percentages of option notional
                    price = group['price']
                    base_notional = current_notional  # Option notional only
                    target_notional = base_notional * float(getattr(self.algorithm, 'delta_target_trade_pct_equity', 0.05))
                    tolerance_notional = base_notional * float(getattr(self.algorithm, 'delta_tol_trade_pct_equity', 0.10))
                
                lower_band = target_notional - tolerance_notional
                upper_band = target_notional + tolerance_notional

                # Log delta bands information - compare PORTFOLIO DOLLAR DELTA to bands
                if self.algorithm.debug_mode:
                    is_outside = current_dollar_delta < lower_band or current_dollar_delta > upper_band
                    self.algorithm.Debug(f"DELTA BANDS {und_sym}: ${current_dollar_delta:,.0f} vs [${lower_band:,.0f}, ${upper_band:,.0f}] → {'OUTSIDE' if is_outside else 'INSIDE'}")

                # Check if outside bands (using portfolio dollar delta)
                if current_dollar_delta < lower_band or current_dollar_delta > upper_band:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"PORTFOLIO REBALANCE: Delta outside bounds, rebalancing needed")
                    return True
                        
            # All underlyings are within bounds
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"PORTFOLIO REBALANCE: Delta within bounds, no rebalancing needed")
            return False
            
        except Exception as e:
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Delta bands check error: {e}")
            return False

    def portfolio_delta_usd(self) -> float:
        try:
            total = 0.0
            for pos in [p for p in self.algorithm.positions.values() if p.get('quantity', 0) != 0]:
                sym = pos['symbol']
                if sym not in self.algorithm.Securities:
                    continue
                if sym.SecurityType == SecurityType.Option:
                    und = sym.Underlying if hasattr(sym, 'Underlying') else self.algorithm.underlying_symbol
                    if und not in self.algorithm.Securities:
                        continue
                    price = float(self.algorithm.Securities[und].Price)
                    greeks = getattr(self.algorithm.Securities[sym], 'Greeks', None)
                    if greeks and greeks.Delta is not None:
                        d = float(greeks.Delta)
                    else:
                        cached = getattr(self.algorithm, 'greeks_cache', {}).get(sym, None)
                        if cached:
                            d = float(cached[0][0] if cached[0][0] is not None else 0.0)
                        else:
                            d = 0.0
                    total += d * pos['quantity'] * 100.0 * price
                else:
                    price = float(self.algorithm.Securities[sym].Price)
                    total += pos['quantity'] * price
            # Include underlying positions from Portfolio holdings (avoid double counting)
            if self.algorithm.Portfolio[self.algorithm.underlying_symbol].Invested:
                holding = self.algorithm.Portfolio[self.algorithm.underlying_symbol]
                q = float(holding.Quantity)
                px = float(self.algorithm.Securities[self.algorithm.underlying_symbol].Price)

                # Check if this position is already tracked in our positions dictionary
                already_tracked = False
                for pos_id, pos in self.algorithm.positions.items():
                    if (pos.get('symbol') == self.algorithm.Securities[self.algorithm.underlying_symbol].Symbol and
                        abs(pos.get('quantity', 0) - q) < 1e-6):  # Allow for small floating point differences
                        already_tracked = True
                        break

                if not already_tracked:
                    total += q * px
            return total
        except Exception:
            return 0.0


    def log_eod(self):
        if self.algorithm.debug_mode:
            self.log_eod_greeks()


