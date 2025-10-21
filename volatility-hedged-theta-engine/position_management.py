"""
Position Management Module for Volatility Hedged Theta Engine

This module handles finding tradable options, selecting the best candidates,
and managing position entries with diversification controls.
"""

from AlgorithmImports import *
from typing import List, Dict, Optional, Tuple
import math
from config import (
    # Margin estimation parameters
    MARGIN_ESTIMATE_1_UNDERLYING_PCT, MARGIN_ESTIMATE_2_UNDERLYING_PCT, MARGIN_MINIMUM_FLOOR,

    # Filter relaxation parameters
    FILTER_RELAXATION_THRESHOLD_DAYS, PREMIUM_RELAXATION_FACTOR,
    DTE_RELAXATION_DECREMENT, MIN_DTE_FLOOR,

    # Delta filter parameters
    MIN_DELTA, MAX_DELTA,

    # Delta approximation parameters
    DEFAULT_DELTA_SHORT_PUT, ITM_DELTA_MULTIPLIER, ITM_DELTA_MAX, OTM_DELTA_MIN
)


class PositionManager:
    """Manages position entry and option selection with diversification controls"""
    
    def __init__(self, algorithm):
        self.algorithm = algorithm

    def _calculate_position_size(self, option_price, strike):
        """Calculate position size using risk manager"""
        if hasattr(self.algorithm, 'risk_manager') and self.algorithm.risk_manager:
            return self.algorithm.risk_manager.calculate_position_size(option_price, strike)
        else:
            self.algorithm.Debug("Risk manager not available, using fallback position size")
            return 1

    def _calculate_current_margin_usage(self):
        """Calculate current margin utilization using QuantConnect's internal values"""
        try:
            # Use QuantConnect's built-in margin tracking
            total_margin_used = self.algorithm.Portfolio.TotalMarginUsed
            
            self.algorithm.Debug(f"Current margin usage (QC): ${total_margin_used:,.0f} across {len(self.algorithm.positions)} positions")
            return total_margin_used
        except Exception as e:
            self.algorithm.Debug(f"Error getting margin usage from QC: {e}")
            return 0

    def _positions_by_expiry(self):
        """Group positions by expiry date for diversification analysis"""
        res = {}
        for p in getattr(self.algorithm, 'positions', {}).values():
            qty = p.get('quantity', 0)
            if qty == 0: 
                continue
            exp = p.get('expiration')
            if exp: 
                exp_key = exp.date() if hasattr(exp, 'date') else exp
                res.setdefault(exp_key, []).append(p)
        return res

    def _has_space_for_expiry(self, expiry_date):
        """Check if we can add more positions to this expiry"""
        book = self._positions_by_expiry()
        exp_key = expiry_date.date() if hasattr(expiry_date, 'date') else expiry_date
        max_positions = getattr(self.algorithm, 'max_positions_per_expiry', 1)
        return len(book.get(exp_key, [])) < max_positions

    def _too_close_to_existing_strikes(self, expiry_date, strike, spot):
        """Check if this strike is too close to existing strikes in the same expiry"""
        spacing = getattr(self.algorithm, 'min_strike_spacing_pct', 0.015)
        book = self._positions_by_expiry()
        exp_key = expiry_date.date() if hasattr(expiry_date, 'date') else expiry_date
        for p in book.get(exp_key, []):
            s = p.get('strike')
            if s is None: 
                continue
            if abs(s - strike) / max(spot, 1e-9) < spacing:
                return True
        return False

    def _expiry_on_cooldown(self, expiry_date):
        """Check if this expiry is on cooldown (recently had positions added)"""
        cd = getattr(self.algorithm, 'expiry_cooldown_days', 0)
        if cd <= 0:
            return False
        exp_key = expiry_date.date() if hasattr(expiry_date, 'date') else expiry_date
        for p in getattr(self.algorithm, 'positions', {}).values():
            if p.get('quantity', 0) == 0:
                continue
            exp = p.get('expiration')
            if not exp:
                continue
            ekey = exp.date() if hasattr(exp, 'date') else exp
            if ekey == exp_key:
                last_ts = p.get('timestamp') or self.algorithm.Time
                if (self.algorithm.Time - last_ts).days < cd:
                    return True
        return False

    def _get_todays_dte_bucket(self):
        """Get today's DTE bucket for rotation"""
        buckets = getattr(self.algorithm, 'dte_buckets', [(21, 35), (36, 50), (51, 70), (71, 105)])
        bucket_index = self.algorithm.Time.toordinal() % len(buckets)
        return buckets[bucket_index]

    def find_tradable_options(self, option_chain):
        """Find tradable options based on criteria with DTE bucket fallback"""
        candidates = []
        
        # Try primary bucket first, then fallback to all buckets if no candidates
        primary_candidates = self._find_candidates_in_bucket(option_chain, primary_only=True)
        if len(primary_candidates) > 0:
            return primary_candidates
        
        # No candidates in primary bucket, try all buckets
        # Try fallback to all DTE buckets
        fallback_candidates = self._find_candidates_in_bucket(option_chain, primary_only=False)
        
        # If still no candidates found, track for aggressive adaptation
        if len(fallback_candidates) == 0:
            if not hasattr(self.algorithm, '_no_candidates_streak'):
                self.algorithm._no_candidates_streak = 0
            self.algorithm._no_candidates_streak += 1
            
            # After N consecutive days with no candidates, aggressively relax filters
            if self.algorithm._no_candidates_streak >= FILTER_RELAXATION_THRESHOLD_DAYS:
                # More aggressive relaxation after {self.algorithm._no_candidates_streak} days
                self.algorithm.min_premium_pct_of_spot = max(0.0005, self.algorithm.min_premium_pct_of_spot * PREMIUM_RELAXATION_FACTOR)
                self.algorithm.min_target_dte = max(MIN_DTE_FLOOR, self.algorithm.min_target_dte - DTE_RELAXATION_DECREMENT)
                self.algorithm._no_candidates_streak = 0  # Reset
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"Relaxed filters: Premium {self.algorithm.min_premium_pct_of_spot:.1%}, "
                                       f"DTE {self.algorithm.min_target_dte}")
        else:
            self.algorithm._no_candidates_streak = 0
            
        return fallback_candidates

    def _find_candidates_in_bucket(self, option_chain, primary_only=True):
        """
        FILTERING ONLY: Find candidates using hybrid approach for consistent filtering results.
        
        CRITICAL: This method is ONLY for option discovery/filtering. All trading execution,
        order placement, and risk management MUST use fresh OnData chain data.
        
        Hybrid Approach:
        - Discovery: OnData chain (full option universe)
        - Pricing: Securities data when available (consistent), fallback to chain data
        - Purpose: Eliminate race conditions in filtering while maintaining discovery completeness
        """
        candidates = []

        try:
            underlying_price = self.algorithm.Securities[self.algorithm.underlying_symbol].Price
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Finding options: Price=${underlying_price:.2f}, DTE={self.algorithm.min_target_dte}-{self.algorithm.max_target_dte}")

            # FILTERING ONLY: Use OnData chain for discovery (full option universe)
            # Securities data used only for consistent pricing during filtering
            total_contracts = 0
            puts_found = 0
            delta_filtered = 0
            dte_filtered = 0
            premium_filtered = 0
            spread_filtered = 0
            
            # Iterate through OnData chain for full option discovery
            for contract in option_chain:
                total_contracts += 1
                symbol = contract.Symbol

                # Basic filters
                if contract.Right != OptionRight.Put:
                    continue
                puts_found += 1

                # FILTERING ONLY: Use OnData chain data FIRST (most fresh), fallback to Securities
                # NOTE: This pricing is ONLY for filtering - execution uses fresh OnData data
                bid_price = None
                ask_price = None
                
                # Try OnData chain data FIRST (freshest source during execution phases)
                if contract.BidPrice > 0 and contract.AskPrice > 0:
                    bid_price = contract.BidPrice
                    ask_price = contract.AskPrice
                
                # Fallback to Securities data if OnData not available
                if (bid_price is None or ask_price is None) and symbol in self.algorithm.Securities:
                    security = self.algorithm.Securities[symbol]
                    if security.BidPrice > 0 and security.AskPrice > 0:
                        bid_price = security.BidPrice
                        ask_price = security.AskPrice

                # Convert both to date objects for proper comparison - SAFE DATETIME HANDLING
                try:
                    if hasattr(contract.Expiry, 'date'):
                        expiry_date = contract.Expiry.date()
                    else:
                        expiry_date = contract.Expiry
                    
                    if hasattr(self.algorithm.Time, 'date'):
                        current_date = self.algorithm.Time.date()
                    else:
                        current_date = self.algorithm.Time
                    
                    dte = (expiry_date - current_date).days
                except Exception as e:
                    # Skip contract with DTE calculation error
                    continue
                if not (self.algorithm.min_target_dte <= dte <= self.algorithm.max_target_dte):
                    dte_filtered += 1
                    continue

                # Premium filter - using Securities data already set above
                if bid_price is None or ask_price is None or bid_price <= 0 or ask_price <= 0:
                    premium_filtered += 1
                    continue

                premium = (bid_price + ask_price) / 2
                # Use percentage-based premium filter relative to underlying price
                min_premium_required = underlying_price * self.algorithm.min_premium_pct_of_spot
                if premium < min_premium_required:
                    premium_filtered += 1
                    continue

                # Liquidity filter (combined threshold): allow if spread <= max(pct*mid, abs_min)
                mid_price = (bid_price + ask_price) / 2
                spread_abs = abs(ask_price - bid_price)
                spread_pct = spread_abs / mid_price if mid_price > 0 else 1.0
                max_allowed_spread = max(self.algorithm.entry_max_spread_pct * mid_price,
                                         getattr(self.algorithm, 'entry_abs_spread_min', 0.0))
                if spread_abs > max_allowed_spread:
                    spread_filtered += 1
                    continue

                # CRITICAL FIX: Check if contract is tradable
                if symbol in self.algorithm.Securities:
                    security = self.algorithm.Securities[symbol]
                    if not security.IsTradable:
                        # Skip non-tradable contract
                        continue

                # Greeks validation - PRIORITY: OnData chain contract Greeks (freshest!)
                delta = None
                delta_source = None
                
                # 1) Try OnData chain contract Greeks FIRST (freshest during execution phases)
                if hasattr(contract, 'Greeks') and contract.Greeks is not None and contract.Greeks.Delta is not None:
                    delta = float(contract.Greeks.Delta)
                    delta_source = "QC-CHAIN"
                    
                    # Cache the complete Greeks from OnData chain
                    try:
                        gamma = float(contract.Greeks.Gamma) if contract.Greeks.Gamma is not None else None
                        theta = float(contract.Greeks.Theta) if contract.Greeks.Theta is not None else None
                        vega = float(contract.Greeks.Vega) if hasattr(contract.Greeks, 'Vega') and contract.Greeks.Vega is not None else None
                        if not hasattr(self.algorithm, 'greeks_cache'):
                            self.algorithm.greeks_cache = {}
                        self.algorithm.greeks_cache[symbol] = ((delta, gamma, theta, vega), self.algorithm.Time)
                    except Exception:
                        pass
                
                # 2) Fallback to Securities data if OnData Greeks not available
                if delta is None and symbol in self.algorithm.Securities:
                    security = self.algorithm.Securities[symbol]
                    if hasattr(security, 'Greeks') and security.Greeks is not None and security.Greeks.Delta is not None:
                        delta = float(security.Greeks.Delta)
                        delta_source = "QC-SECURITIES"
                
                # 3) Fallback to centralized options_data manager
                if delta is None:
                    try:
                        if hasattr(self.algorithm, 'options_data') and self.algorithm.options_data is not None:
                            d, src = self.algorithm.options_data.get_delta(symbol)
                            delta = float(d) if d is not None else None
                            delta_source = src
                    except Exception:
                        delta = None
                        delta_source = None

                # 4) Final fallback: use greeks_provider if delta is still None
                if delta is None and hasattr(self.algorithm, 'greeks_provider'):
                    try:
                        strike = contract.Strike
                        expiration = contract.Expiry
                        d, src = self.algorithm.greeks_provider.get_delta(symbol, strike, underlying_price, expiration)
                        delta = float(d) if d is not None else 0.0
                        delta_source = src
                    except Exception:
                        delta = 0.0
                        delta_source = "ERROR"
                
                # Track missing Greeks for debugging
                if delta is None or delta == 0.0:
                    if not hasattr(self.algorithm, '_missing_greeks_count'):
                        self.algorithm._missing_greeks_count = 0
                    self.algorithm._missing_greeks_count += 1
                    # Log first few instances to avoid spam
                    if self.algorithm.debug_mode and self.algorithm._missing_greeks_count <= 3:
                        self.algorithm.Debug(f"Missing/zero delta for {symbol} (source: {delta_source})")
                        # Show what data sources were checked
                        has_chain_greeks = hasattr(contract, 'Greeks') and contract.Greeks is not None
                        has_sec_greeks = (symbol in self.algorithm.Securities and 
                                         hasattr(self.algorithm.Securities[symbol], 'Greeks') and 
                                         self.algorithm.Securities[symbol].Greeks is not None)
                        self.algorithm.Debug(f"  Chain Greeks: {has_chain_greeks}, Securities Greeks: {has_sec_greeks}")

                # DELTA BAND FILTER: Keep only options within 18-25 delta range (for short puts, delta is negative)
                # This ensures we stay in the optimal theta/risk band and avoid drifting too close to ATM
                if delta is not None and delta != 0.0:
                    abs_delta = abs(delta)
                    if not (MIN_DELTA <= abs_delta <= MAX_DELTA):
                        delta_filtered += 1
                        continue

                # Check tradability
                is_tradable = self._is_option_tradable(contract, delta)

                if is_tradable:
                    # NEW FILTERING: DTE Bucket Rotation
                    if primary_only:
                        # Only allow today's primary DTE bucket
                        dte_lo, dte_hi = self._get_todays_dte_bucket()
                        if not (dte_lo <= dte <= dte_hi):
                            dte_filtered += 1
                            continue
                    # If not primary_only, allow any DTE within min/max range

                    # NEW FILTERING: Expiry Management
                    expiry_date = contract.Expiry
                    if not self._has_space_for_expiry(expiry_date):
                        spread_filtered += 1  # Reuse counter for expiry cap
                        continue

                    if self._expiry_on_cooldown(expiry_date):
                        continue

                    if self._too_close_to_existing_strikes(expiry_date, contract.Strike, underlying_price):
                        continue

                    # Delta band filter removed - using moneyness filter instead

                    candidates.append({
                        'symbol': symbol,
                        'contract': contract,
                        'premium': premium,
                        'bid_price': bid_price,
                        'ask_price': ask_price,
                        'delta': delta,
                        'delta_source': delta_source,
                        'dte': dte,
                        'spread_pct': spread_pct
                    })

            # Enhanced filtering results with data source info
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Option filtering (OnData chain): {total_contracts} total, {puts_found} puts")
                self.algorithm.Debug(f"  Filtered OUT: Delta={delta_filtered}, DTE={dte_filtered}, "
                                   f"Premium={premium_filtered}, Spread={spread_filtered}")
                self.algorithm.Debug(f"  PASSED all filters: {len(candidates)} candidates")
                if len(candidates) == 0:
                    self.algorithm.Debug(f"  NO CANDIDATES: Price=${underlying_price:.2f}, "
                                               f"Delta={MIN_DELTA:.2f}-{MAX_DELTA:.2f}, "
                                               f"DTE={self.algorithm.min_target_dte}-{self.algorithm.max_target_dte}")

        except Exception as e:
            self.algorithm.Debug(f"Error finding tradable options: {e}")

        return candidates

    # NOTE: select_best_option() has been REMOVED from PositionManager
    # 
    # This was strategy-specific logic that didn't belong in infrastructure.
    # Each strategy now implements its own scoring in the strategy module:
    #   - ThetaEngineStrategy._score_and_select() for theta strategy
    #   - SSVIStrategy would have its own scoring method
    # 
    # PositionManager remains strategy-agnostic infrastructure for:
    #   - Filtering candidates (find_tradable_options)
    #   - Position sizing (calculate_position_size)
    #   - Execution (try_enter_position)
    #   - Tracking (positions dict, _positions_by_expiry, etc.)

    def try_enter_position(self, option_data):
        """Attempt to enter a new position"""
        try:
            # CRITICAL FIX: Don't enter positions during warmup
            if self.algorithm.IsWarmingUp:
                return False
            symbol = option_data['symbol']
            contract = option_data['contract']
            premium = option_data['premium']
            strike = contract.Strike
            
            # Calculate position size
            position_size = self._calculate_position_size(premium, strike)
            if position_size <= 0:
                # Position size too small, skipping
                return False

            # Check margin capacity before attempting trade
            current_margin_remaining = self.algorithm.Portfolio.MarginRemaining
            
            # Use the same sophisticated margin calculation as the risk manager
            und_px = self.algorithm.Securities[self.algorithm.underlying_symbol].Price
            otm = max(0.0, und_px - strike)  # Out-of-the-money amount

            # Two common Reg-T floors (same as risk manager)
            estimate1 = MARGIN_ESTIMATE_1_UNDERLYING_PCT * und_px * 100 - otm * 100 + premium * 100  # Config % underlying - OTM + premium
            estimate2 = MARGIN_ESTIMATE_2_UNDERLYING_PCT * und_px * 100 + premium * 100              # Config % underlying + premium
            pct_floor = self.algorithm.estimated_margin_pct * strike * 100     # Config percentage floor

            estimated_margin_per_contract = max(estimate1, estimate2, pct_floor)
            estimated_margin_per_contract = max(MARGIN_MINIMUM_FLOOR, estimated_margin_per_contract)  # Configurable hard floor
            
            # Calculate total estimated margin for the position
            estimated_margin = estimated_margin_per_contract * position_size
            
            # Margin calculated successfully
            
            # Use configurable margin safety factor
            margin_safety_threshold = current_margin_remaining * self.algorithm.pre_order_margin_safety
            if estimated_margin > margin_safety_threshold:
                # Trade too large for available margin
                return False

            # Allow adding to existing positions for better margin utilization
            # (Removed duplicate position check to enable position scaling)

            # Create position entry
            position_id = f"{symbol}_{self.algorithm.Time.strftime('%Y%m%d_%H%M%S')}"
            
            # Store position data
            # IMPORTANT: Initialize quantity at 0 to avoid double-counting when the fill event arrives.
            # Save intended size in target_contracts for Phase 1 hedging.
            self.algorithm.positions[position_id] = {
                'symbol': symbol,
                'contract': contract,
                'quantity': 0,  # Will be updated by OnOrderEvent fill
                'target_contracts': position_size,
                'entry_price': premium,
                'strike': strike,
                'expiration': contract.Expiry,
                'timestamp': self.algorithm.Time,
                'delta': option_data.get('delta'),
                'dte': option_data.get('dte'),
                'estimated_margin': estimated_margin  # Store calculated margin
            }

            # Place limit order at mid price (control fills in backtests)
            try:
                # Use centralized market data manager with proper fallback hierarchy
                bid, ask, source = self.algorithm.market_data.get_bid_ask(symbol, option_data)
                if not bid or not ask:
                    # Log the data source issue for debugging
                    self.algorithm.Debug(f"ERROR: No market data available for {symbol} - source: {source}")
                    return False
                
                # Log when we fall back to Securities collection
                if source == "SECURITIES":
                    self.algorithm.Debug(f"MARKET DATA FALLBACK: {symbol} using Securities collection instead of option chain")
                mid = (bid + ask) / 2.0
                spread = max(ask - bid, 0.0)
                nudge = getattr(self.algorithm, 'entry_nudge_fraction', 0.0) or 0.0
                # Aggressive limit order pricing based on direction
                if position_size > 0:
                    # We are selling -position_size, so move toward BID for aggressive execution
                    px = mid - nudge * spread  # Move toward bid (lower price) for selling
                elif position_size < 0:
                    # We are buying -position_size, so move toward ASK for aggressive execution
                    px = mid + nudge * spread  # Move toward ask (higher price) for buying
                else:
                    # Edge case; default to mid
                    px = mid
                
                # Clamp to book
                px = min(max(px, bid), ask)
                limit_price = round(px, 2)
                
                # DEBUG: Log pricing summary
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"PRICING: bid={bid:.2f} ask={ask:.2f} mid={mid:.2f} spread={spread:.2f} nudge={nudge:.2f} → final={limit_price:.2f}")
            except Exception:
                return False

            # Use ENTRY tag for housekeeping/cancellation
            try:
                order_ticket = self.algorithm.LimitOrder(symbol, -position_size, limit_price, tag=self.algorithm.ENTRY_TAG)
            except TypeError:
                # Older LEAN versions may not accept tag kwarg in Python wrapper
                order_ticket = self.algorithm.LimitOrder(symbol, -position_size, limit_price)
            
            # OPTION SELECTED log moved to P1C section in main.py
            
                if self.algorithm.debug_mode:
                    # Use same data source as calculation for consistent logging
                    try:
                        # Get market data using same method as calculation
                        log_bid, log_ask, log_source = self.algorithm.market_data.get_bid_ask(symbol, option_data)
                        if log_bid and log_ask:
                            spread = log_ask - log_bid
                            spread_pct = (spread / ((log_bid + log_ask) / 2)) * 100 if (log_bid + log_ask) / 2 > 0 else 0
                            source_label = f" [{log_source}]" if log_source != "OPTION_CHAIN" else ""
                            self.algorithm.Debug(f"POSITION ENTERED: {symbol} -{position_size} @ ${limit_price:.2f} (Strike: ${strike:.2f}, DTE: {option_data.get('dte', 'N/A')}) | Market: ${log_bid:.2f}/${log_ask:.2f} (${spread:.2f}, {spread_pct:.1f}%){source_label}")
                        else:
                            self.algorithm.Debug(f"POSITION ENTERED: {symbol} -{position_size} @ ${limit_price:.2f} (Strike: ${strike:.2f}, DTE: {option_data.get('dte', 'N/A')}) | Market: No quotes")
                    except Exception:
                        self.algorithm.Debug(f"POSITION ENTERED: {symbol} -{position_size} @ ${limit_price:.2f} (Strike: ${strike:.2f}, DTE: {option_data.get('dte', 'N/A')}) | Market: Error getting quotes")

            # Return option data for P1C logging
            option_log_data = {
                'symbol': symbol,
                'strike': strike,
                'dte': option_data.get('dte', 'N/A'),
                'delta': option_data.get('delta', 'N/A'),
                'limit_price': limit_price,
                'position_size': position_size
            }
            return option_log_data

        except Exception as e:
            self.algorithm.Debug(f"Error entering position for {symbol}: {e}")
            return False

    def _is_option_tradable(self, contract, delta):
        """Check if option meets tradability criteria"""
        try:
            # Basic tradability checks
            if not contract.BidPrice or not contract.AskPrice:
                return False
            
            if contract.BidPrice <= 0 or contract.AskPrice <= 0:
                return False
            
            # Check spread using combined threshold
            mid_price = (contract.BidPrice + contract.AskPrice) / 2 if (contract.BidPrice and contract.AskPrice) else 0
            spread_abs = abs(contract.AskPrice - contract.BidPrice)
            spread_pct = (spread_abs / mid_price) if mid_price > 0 else 1.0
            max_allowed_spread = max(self.algorithm.entry_max_spread_pct * mid_price,
                                     getattr(self.algorithm, 'entry_abs_spread_min', 0.0))
            if spread_abs > max_allowed_spread:
                return False
            
            # Delta check (if available)
            if delta is not None:
                # For short puts, we want negative delta (put options)
                if delta > 0:  # This would be a call option
                    return False
                    
            return True
            
        except Exception as e:
            # Error checking tradability
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Error checking tradability: {e}")
            return False
