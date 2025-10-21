"""
Delta Hedging Module for Theta Engine

This module handles universal delta hedging for both equity options and futures options.
Supports NAV-based and points-based sizing modes.
"""

from AlgorithmImports import *
from collections import defaultdict


class DeltaHedger:
    """Universal delta hedging functionality"""

    def __init__(self, algorithm):
        self.algorithm = algorithm

    def _get_underlying_symbol(self, opt_symbol):
        """Get underlying symbol for an option (works for equity and futures options)"""
        try:
            return opt_symbol.Underlying
        except:
            # Fallback: use known underlying if mapping not available
            return self.algorithm.underlying_symbol

    def _fut_multiplier(self, und_sym):
        """Get futures multiplier ($ per 1 point move for a single futures contract)"""
        try:
            return self.algorithm.Securities[und_sym].SymbolProperties.ContractMultiplier or 1.0
        except:
            return 1.0

    def _asset_kind(self, und_sym):
        """Determine if underlying is equity or future"""
        try:
            st = und_sym.SecurityType
        except:
            try:
                st = self.algorithm.Securities[und_sym].Symbol.SecurityType
            except:
                return "equity"  # Default assumption
        return "equity" if st == SecurityType.Equity else "future"

    def get_all_filled_option_positions(self):
        """
        Get all filled option positions from QC Portfolio.
        This is the source of truth for what's actually in the portfolio.
        Returns list of (symbol, quantity, strike, expiration) tuples.
        """
        filled_positions = []
        
        # Query QC Portfolio for all option positions
        for symbol, holding in self.algorithm.Portfolio.items():
            if (symbol.SecurityType == SecurityType.Option and 
                holding.Invested and 
                abs(holding.Quantity) > 0):
                
                # Try to get option contract details from current option chain
                strike = None
                expiration = None
                
                # First try to get from current option chain
                if hasattr(self.algorithm, 'current_chain') and self.algorithm.current_chain:
                    for contract in self.algorithm.current_chain:
                        if contract.Symbol == symbol:
                            strike = contract.Strike
                            expiration = contract.Expiry
                            break
                
                # If not found in current chain, try to get from symbol ID
                if strike is None or expiration is None:
                    try:
                        # Try different ways to access option contract info
                        if hasattr(symbol, 'ID') and hasattr(symbol.ID, 'OptionContract'):
                            option_contract = symbol.ID.OptionContract
                            strike = option_contract.Strike
                            expiration = option_contract.Expiry
                        elif hasattr(symbol, 'ID') and hasattr(symbol.ID, 'OptionRight'):
                            # For now, use fallback values if we can't get exact details
                            # This is a limitation - we need the contract details for proper delta calculation
                            strike = 0.0  # Will be updated when we find the contract
                            expiration = None
                    except Exception as e:
                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"Could not get option contract details for {symbol}: {e}")
                        continue
                
                # Only add if we have valid contract details
                if strike is not None and expiration is not None:
                    filled_positions.append({
                        'symbol': symbol,
                        'quantity': holding.Quantity,
                        'strike': strike,
                        'expiration': expiration,
                        'entry_price': holding.AveragePrice
                    })
        
        return filled_positions

    def compute_delta_groups(self, pending: list = None):
        """
        Aggregate delta by underlying for universal hedging.
        Returns groups[underlying] = {
            'units': units-equivalent delta (shares or contracts),
            'notional': delta-notional in USD,
            'price': underlying price,
            'mult': futures multiplier ($/pt) or 1 for equities,
            'kind': 'equity' or 'future'
        }
        """
        groups = defaultdict(lambda: {'units': 0.0, 'notional': 0.0, 'price': 0.0, 'mult': 1.0, 'kind': None, 'dollar_delta': 0.0, 'option_delta': 0.0, 'hedge_delta': 0.0})

        # PERFORMANCE OPTIMIZATION: Only process underlyings we actually hedge
        # Build set of relevant underlyings from ACTIVE positions and known underlying
        relevant_underlyings = set()

        # Always include the main underlying
        relevant_underlyings.add(self.algorithm.underlying_symbol)

        # CRITICAL FIX: Get ALL filled option positions from QC Portfolio (source of truth)
        filled_option_positions = self.get_all_filled_option_positions()
        if self.algorithm.debug_mode and filled_option_positions:
            # Reduced logging - only show count, not individual positions
            self.algorithm.Debug(f"DELTA GROUPS: Found {len(filled_option_positions)} filled option positions from QC Portfolio")
            for pos in filled_option_positions:
                opt_sym = pos['symbol']
                und_sym = self._get_underlying_symbol(opt_sym)
                
                # Get current option price and Greeks
                option_price = 0.0
                delta_val = 0.0
                gamma_val = 0.0
                theta_val = 0.0
                
                if opt_sym in self.algorithm.Securities:
                    opt_sec = self.algorithm.Securities[opt_sym]
                    option_price = opt_sec.Price
                    
                    # Get Greeks via vol model abstraction
                    if und_sym in self.algorithm.Securities:
                        und_sec = self.algorithm.Securities[und_sym]
                        underlying_price = und_sec.Price
                        
                        try:
                            delta_val, _ = self.algorithm.greeks_provider.get_delta(opt_sym, pos['strike'], underlying_price, pos['expiration'])
                            gamma_val, _ = self.algorithm.greeks_provider.get_gamma(opt_sym, pos['strike'], underlying_price, pos['expiration'])
                            theta_val, _ = self.algorithm.greeks_provider.get_theta(opt_sym, pos['strike'], underlying_price, pos['expiration'])
                        except Exception as e:
                            # Reduced error logging
                            pass
                
                # Individual position details removed to reduce logging
        
        for position in filled_option_positions:
            opt_sym = position['symbol']
            und_sym = self._get_underlying_symbol(opt_sym)
            relevant_underlyings.add(und_sym)

        # Include underlyings from ACTIVE option positions in positions dictionary (for pending trades)
        active_option_positions = [pos for pos_id, pos in self.algorithm.positions.items()
                                   if pos.get('quantity', 0) != 0 and not pos.get('is_hedge', False)]
        for position in active_option_positions:
            if position.get('symbol'):  # Skip hedge positions
                opt_sym = position['symbol']
                und_sym = self._get_underlying_symbol(opt_sym)
                relevant_underlyings.add(und_sym)

        # Include underlyings from pending option trades
        if pending:
            for item in pending:
                try:
                    if len(item) >= 2:
                        opt_symbol = item[0]
                        und_sym = self._get_underlying_symbol(opt_symbol)
                        relevant_underlyings.add(und_sym)
                except Exception:
                    pass

        # Include underlying holdings (avoid double counting with positions dictionary)
        for und_sym in relevant_underlyings:
            if und_sym not in self.algorithm.Securities:
                continue

            # Only check portfolio if we actually have this symbol invested
            if und_sym in self.algorithm.Portfolio and self.algorithm.Portfolio[und_sym].Invested:
                sec = self.algorithm.Securities[und_sym]
                kind = self._asset_kind(und_sym)
                price = sec.Price
                mult = self._fut_multiplier(und_sym) if kind == 'future' else 1.0
                portfolio_qty = self.algorithm.Portfolio[und_sym].Quantity

                # Check if this position is already tracked in our positions dictionary
                # Look for hedge positions by position ID pattern, not exact quantity match
                already_tracked = False
                for pos_id, pos in self.algorithm.positions.items():
                    if (pos.get('symbol') == und_sym and
                        pos_id.startswith('hedge_') and  # This is a hedge position
                        pos.get('is_hedge', False)):    # Confirm it's marked as hedge
                        already_tracked = True
                        # Skip existing hedge positions to avoid double-counting
                        break

                if not already_tracked:
                    # Include Portfolio position in delta calculation
                    groups[und_sym]['units'] += portfolio_qty
                    groups[und_sym]['notional'] += portfolio_qty * (price if kind == 'equity' else price * mult)
                    groups[und_sym]['price'] = price
                    groups[und_sym]['mult'] = mult
                    groups[und_sym]['kind'] = kind

        # CRITICAL FIX: Add each FILLED option position's delta contribution from QC Portfolio
        for position in filled_option_positions:
            opt_sym = position['symbol']
            if opt_sym not in self.algorithm.Securities:
                continue

            opt_sec = self.algorithm.Securities[opt_sym]
            und_sym = self._get_underlying_symbol(opt_sym)
            if und_sym not in self.algorithm.Securities:
                continue

            und_sec = self.algorithm.Securities[und_sym]
            price = und_sec.Price
            kind = self._asset_kind(und_sym)
            mult = self._fut_multiplier(und_sym) if kind == 'future' else 1.0
            qty = position['quantity']

            # Get delta via vol model abstraction
            d, delta_source = self.algorithm.greeks_provider.get_delta(opt_sym, position['strike'], price, position['expiration'])

            # Units-equivalent per contract (QC delta is per contract):
            # Equity options: 100 shares per 1Δ; futures options: 1 futures contract per 1Δ
            units_per_contract = 100.0 if kind == 'equity' else 1.0
            units_contrib = d * qty * units_per_contract

            # CRITICAL FIX: Calculate option dollar delta properly
            # Option dollar delta = delta × contracts × 100 × underlying_price
            option_dollar_delta = d * qty * units_per_contract * price

            # For delta bands, use notional value (contracts * 100 * spot price) instead of dollar delta
            if kind == 'equity':
                # For options: notional = abs(contracts) * 100 * spot price (always positive)
                notional_contrib = abs(qty) * 100.0 * price
            else:
                # For futures: use dollar delta as before
                notional_contrib = units_contrib * price * mult

            # Removed verbose OPTION DELTA logging

            g = groups[und_sym]
            g['units'] += units_contrib
            g['notional'] += notional_contrib
            g['dollar_delta'] += option_dollar_delta
            g['option_delta'] += option_dollar_delta
            g['price'] = price
            g['mult'] = mult
            g['kind'] = kind

        # Add each ACTIVE option position's delta contribution from positions dictionary (for pending trades)
        for position in active_option_positions:
            opt_sym = position['symbol']
            if opt_sym not in self.algorithm.Securities:
                continue

            # Skip if this position is already accounted for in filled_option_positions
            already_accounted = False
            for filled_pos in filled_option_positions:
                if filled_pos['symbol'] == opt_sym:
                    already_accounted = True
                    break
            
            if already_accounted:
                continue

            opt_sec = self.algorithm.Securities[opt_sym]
            und_sym = self._get_underlying_symbol(opt_sym)
            if und_sym not in self.algorithm.Securities:
                continue

            und_sec = self.algorithm.Securities[und_sym]
            price = und_sec.Price
            kind = self._asset_kind(und_sym)
            mult = self._fut_multiplier(und_sym) if kind == 'future' else 1.0
            qty = position['quantity']

            # Get delta via vol model abstraction
            d, delta_source = self.algorithm.greeks_provider.get_delta(opt_sym, position['strike'], price, position['expiration'])

            # Units-equivalent per contract (QC delta is per contract):
            # Equity options: 100 shares per 1Δ; futures options: 1 futures contract per 1Δ
            units_per_contract = 100.0 if kind == 'equity' else 1.0
            units_contrib = d * qty * units_per_contract

            # CRITICAL FIX: Calculate option dollar delta properly
            # Option dollar delta = delta × contracts × 100 × underlying_price
            option_dollar_delta = d * qty * units_per_contract * price

            # For delta bands, use notional value (contracts * 100 * spot price) instead of dollar delta
            if kind == 'equity':
                # For options: notional = abs(contracts) * 100 * spot price (always positive)
                notional_contrib = abs(qty) * 100.0 * price
            else:
                # For futures: use dollar delta as before
                notional_contrib = units_contrib * price * mult

            # Removed verbose OPTION DELTA logging

            g = groups[und_sym]
            g['units'] += units_contrib
            g['notional'] += notional_contrib
            g['dollar_delta'] += option_dollar_delta
            g['option_delta'] += option_dollar_delta
            g['price'] = price
            g['mult'] = mult
            g['kind'] = kind

        # Include hedge positions from the positions dictionary
        hedge_positions_found = []
        for pos_id, position in self.algorithm.positions.items():
            if pos_id.startswith('hedge_'):
                hedge_positions_found.append(f"{pos_id}: qty={position.get('quantity', 0)}, is_hedge={position.get('is_hedge', False)}")

            if (pos_id.startswith('hedge_') and
                position.get('is_hedge', False) and
                position.get('quantity', 0) != 0):

                und_sym = position['symbol']
                if und_sym not in self.algorithm.Securities:
                    continue

                sec = self.algorithm.Securities[und_sym]
                price = sec.Price
                kind = self._asset_kind(und_sym)
                mult = self._fut_multiplier(und_sym) if kind == 'future' else 1.0
                qty = position['quantity']

                # Hedge positions are equity positions, so delta = 1.0 per unit
                # CRITICAL FIX: Hedge positions contribute dollar delta directly
                hedge_dollar_delta = qty * price  # Equity dollar delta = shares × price
                # For delta bands, hedge positions should NOT contribute to notional
                # We only want to track option notional for delta bands
                hedge_notional = 0  # Don't count hedge notional for delta bands

                if und_sym not in groups:
                    groups[und_sym] = {
                        'units': 0,
                        'notional': 0,
                        'price': price,
                        'mult': mult,
                        'kind': kind,
                        'dollar_delta': 0,  # Add separate dollar delta tracking
                        'option_delta': 0,
                        'hedge_delta': 0
                    }

                groups[und_sym]['dollar_delta'] += hedge_dollar_delta
                groups[und_sym]['hedge_delta'] += hedge_dollar_delta
                # Don't add hedge notional to the total - we only want option notional for delta bands
                # groups[und_sym]['notional'] += hedge_notional
                groups[und_sym]['price'] = price
                groups[und_sym]['mult'] = mult
                groups[und_sym]['kind'] = kind

                # Hedge position included in delta calculation

        # Removed verbose DELTA HEDGE SCAN logging

        # Include any pending option fills (symbol, quantity, cached_delta) not yet reflected in positions
        if pending:
            for item in pending:
                if len(item) == 3:
                    opt_symbol, qty, cached_delta = item
                else:
                    opt_symbol, qty = item
                    cached_delta = 0.0
                try:
                    # Check if this trade is already filled to avoid double-counting
                    already_filled = False
                    for pos in self.algorithm.positions.values():
                        if (pos.get('quantity', 0) != 0 and 
                            not pos.get('is_hedge', False) and 
                            pos['symbol'] == opt_symbol):
                            already_filled = True
                            break

                    if already_filled:
                        continue

                    if opt_symbol not in self.algorithm.Securities:
                        continue
                    und_sym = self._get_underlying_symbol(opt_symbol)
                    if und_sym not in self.algorithm.Securities:
                        continue
                    und_sec = self.algorithm.Securities[und_sym]
                    price = und_sec.Price
                    kind = self._asset_kind(und_sym)
                    mult = self._fut_multiplier(und_sym) if kind == 'future' else 1.0

                    # Try QC Greeks first, fall back to cached delta
                    d = cached_delta
                    delta_source = "CACHED"
                    
                    # Check if QC Greeks are available for this symbol
                    if opt_symbol in self.algorithm.Securities:
                        security = self.algorithm.Securities[opt_symbol]
                        greeks = getattr(security, 'Greeks', None)
                        if greeks and greeks.Delta is not None:
                            d = float(greeks.Delta)
                            delta_source = "QC"
                    
                    units_per_contract = 100.0 if kind == 'equity' else 1.0
                    units_contrib = d * float(qty) * units_per_contract
                    
                    # CRITICAL FIX: Calculate option dollar delta properly for pending trades
                    # Option dollar delta = delta × contracts × 100 × underlying_price
                    option_dollar_delta = d * float(qty) * units_per_contract * price
                    
                    # For delta bands, use notional value (contracts * 100 * spot price) instead of dollar delta
                    if kind == 'equity':
                        # For options: notional = abs(contracts) * 100 * spot price (always positive)
                        notional_contrib = abs(float(qty)) * 100.0 * price
                    else:
                        # For futures: use dollar delta as before
                        notional_contrib = units_contrib * price * mult

                    if und_sym not in groups:
                        groups[und_sym] = {'units': 0.0, 'notional': 0.0, 'price': price, 'mult': mult, 'kind': kind, 'dollar_delta': 0.0, 'option_delta': 0.0, 'hedge_delta': 0.0}

                    g = groups[und_sym]
                    g['units'] += units_contrib
                    g['dollar_delta'] += option_dollar_delta
                    g['option_delta'] += option_dollar_delta
                    # Don't add pending trade notional to avoid double-counting - it's already in existing positions
                    # g['notional'] += notional_contrib

                except Exception as e:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"PENDING DELTA ERROR: {opt_symbol}: {e}")

        return groups

    def _nav_target_and_band(self, kind):
        """Get NAV-based target and tolerance band with hysteresis"""
        if kind == 'equity':
            tgt = self.algorithm.Portfolio.TotalPortfolioValue * self.algorithm.delta_target_nav_pct_equity
            tol = self.algorithm.Portfolio.TotalPortfolioValue * self.algorithm.delta_tol_nav_pct_equity
            # Add hysteresis buffer to prevent oscillation (5% of tolerance)
            hysteresis_buffer = tol * 0.05
        else:
            tgt = self.algorithm.Portfolio.TotalPortfolioValue * self.algorithm.delta_target_nav_pct_future
            tol = self.algorithm.Portfolio.TotalPortfolioValue * self.algorithm.delta_tol_nav_pct_future
            hysteresis_buffer = tol * 0.05

        # Apply hysteresis: widen the "no-action" zone slightly
        lo_band = tgt - tol - hysteresis_buffer
        hi_band = tgt + tol + hysteresis_buffer
        return tgt, (lo_band, hi_band)

    def _points_target_and_band(self, kind):
        """Get points-based target and tolerance band with hysteresis"""
        if kind == 'equity':
            tgt_units = 100.0 * self.algorithm.equity_delta_target_points
            tol_units = 100.0 * self.algorithm.equity_delta_tol_points
            # Add hysteresis buffer to prevent oscillation (10% of tolerance)
            hysteresis_buffer = tol_units * 0.1
        else:  # futures
            tgt_units = float(self.algorithm.futures_delta_target_contracts)
            tol_units = float(self.algorithm.futures_delta_tol_contracts)
            hysteresis_buffer = tol_units * 0.1

        # Apply hysteresis: widen the "no-action" zone slightly
        lo_band = tgt_units - tol_units - hysteresis_buffer
        hi_band = tgt_units + tol_units + hysteresis_buffer
        return tgt_units, (lo_band, hi_band)

    def execute_delta_hedge_universal(self, pending: list = None):
        """
        Universal delta hedging for equity options and futures options.
        Hedges each underlying independently using configurable sizing.
        Only considers active positions (quantity != 0).
        
        NEW HOLISTIC P2 LOGIC:
        1. Determine margin left
        2. Determine if rebalancing needed
        3. Check if underlying hedge would exceed overnight margin max
        4. Hedge with underlying if margin allows
        5. Reduce option positions if margin doesn't allow
        """
        # Get active positions only (quantity != 0)
        active_positions = [pos for pos_id, pos in self.algorithm.positions.items() if pos.get('quantity', 0) != 0]

        # Only clear hedges if there are NO option positions anywhere (active or pending)
        option_positions_exist = any(
            pos.get('symbol', '').SecurityType == SecurityType.Option and pos.get('quantity', 0) != 0
            for pos in active_positions
        )

        # Also check for pending option trades that would create positions
        pending_options = getattr(self.algorithm, 'todays_new_trades', [])
        has_pending_options = len(pending_options) > 0

        if not option_positions_exist and not has_pending_options:
            underlying_symbol = self.algorithm.underlying_symbol
            if underlying_symbol in self.algorithm.Securities:
                current_qty = self.algorithm.Portfolio[underlying_symbol].Quantity
                if current_qty != 0:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"HEDGE CLEAR: No option positions (active or pending), liquidating {current_qty} shares")

                    # Clear hedge positions from our ledger
                    hedge_positions_to_remove = []
                    for pos_id, position in self.algorithm.positions.items():
                        if (position.get('is_hedge', False) and
                            position['symbol'] == underlying_symbol):
                            hedge_positions_to_remove.append(pos_id)

                    for pos_id in hedge_positions_to_remove:
                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"Removing hedge position {pos_id} from ledger")
                        del self.algorithm.positions[pos_id]

                    self.algorithm.Liquidate(underlying_symbol, tag="No active options, clearing hedge")
                    return True
            return False
        
        groups = self.compute_delta_groups(pending)
        did_trade = False

        # HOLISTIC P2 LOGIC: Check margin constraints before hedging
        for und_sym, g in groups.items():
            # Skip if no positions for this underlying
            if g['dollar_delta'] == 0:
                continue
                
            # 1. Determine margin left
            try:
                # Get margin information from Portfolio
                current_margin_used = float(self.algorithm.Portfolio.TotalMarginUsed)
                current_margin_remaining = float(self.algorithm.Portfolio.MarginRemaining)
                portfolio_value = float(self.algorithm.Portfolio.TotalPortfolioValue)
                current_margin_utilization = current_margin_used / portfolio_value if portfolio_value > 0 else 0
            except AttributeError:
                # Fallback: estimate margin usage from positions
                current_margin_used = 0.0
                current_margin_remaining = float(self.algorithm.Portfolio.TotalPortfolioValue)
                portfolio_value = float(self.algorithm.Portfolio.TotalPortfolioValue)
                current_margin_utilization = 0.0
                
                # Estimate margin from option positions
                for pos in self.algorithm.positions.values():
                    if pos.get('estimated_margin', 0) > 0:
                        current_margin_used += pos['estimated_margin']
                
                current_margin_remaining = portfolio_value - current_margin_used
                current_margin_utilization = current_margin_used / portfolio_value if portfolio_value > 0 else 0
            
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"P2 MARGIN CHECK: Used=${current_margin_used:,.0f}, Remaining=${current_margin_remaining:,.0f}, Util={current_margin_utilization:.1%}")
            
            # 2. Determine if rebalancing needed
            cur_dollar_delta = g['dollar_delta']
            kind = g['kind']
            price = g['price']
            mult = g['mult']
            
            # Use configured delta band mode (TRADE or NAV)
            if getattr(self.algorithm, 'delta_band_mode', 'TRADE').upper() == 'NAV':
                target_notional, (lo_notional, hi_notional) = self._nav_target_and_band(kind)
                base_notional = None  # Not used in NAV mode, only for TRADE mode logging
            else:
                # TRADE mode: use trade notional
                base_notional = self._trade_base_notional(und_sym, kind, price, mult, pending)
                target_notional, (lo_notional, hi_notional) = self._trade_target_and_band(kind, base_notional)
            
            # Check if within tolerance band
            in_band = lo_notional <= cur_dollar_delta <= hi_notional
            
            if self.algorithm.debug_mode:
                is_outside = cur_dollar_delta < lo_notional or cur_dollar_delta > hi_notional
                self.algorithm.Debug(f"DELTA BANDS {und_sym}: "
                                   f"current=${cur_dollar_delta:,.0f}, target=${target_notional:,.0f}, "
                                   f"band=[${lo_notional:,.0f}, ${hi_notional:,.0f}], "
                                   f"outside_band={is_outside}")
            
            if in_band:
                continue  # No rebalancing needed
            
            # 3. Check if underlying hedge would exceed overnight margin max
            # Determine desired dollar delta (TARGET = midpoint, BAND = nearest boundary)
            if self.algorithm.delta_revert_mode.upper() == "TARGET":
                desired_dollar_delta = target_notional
                revert_label = "target"
            else:  # BAND
                desired_dollar_delta = lo_notional if cur_dollar_delta < lo_notional else hi_notional
                revert_label = "boundary"
            
            delta_dollar_delta = desired_dollar_delta - cur_dollar_delta
            units_to_trade = int(round(delta_dollar_delta / (price if kind == 'equity' else price * mult)))
            
            if units_to_trade == 0:
                continue
            
            # Calculate projected margin if we execute the hedge
            # For shorting shares, we need to account for margin requirements
            hedge_cost = abs(units_to_trade) * price
            # Shorting shares typically requires 50% margin
            hedge_margin_requirement = hedge_cost * 0.5 if units_to_trade < 0 else 0
            projected_margin_used = current_margin_used + hedge_margin_requirement
            projected_margin_utilization = projected_margin_used / portfolio_value if portfolio_value > 0 else 0
            
            overnight_margin_max = getattr(self.algorithm, 'overnight_margin_max', 0.95)
            
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"P2 HEDGE ANALYSIS: Need {units_to_trade:+d} shares, cost=${hedge_cost:,.0f}")
                self.algorithm.Debug(f"P2 MARGIN PROJECTION: Current={current_margin_utilization:.1%}, Projected={projected_margin_utilization:.1%}, Max={overnight_margin_max:.1%}")
            
            # 4. Hedge with underlying if margin allows
            if (projected_margin_utilization <= overnight_margin_max and 
                getattr(self.algorithm, 'p2_underlying_hedge_enabled', True)):
                
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"P2 UNDERLYING HEDGE: {und_sym} {units_to_trade:+d} shares | Δ${delta_dollar_delta:,.0f} (to {revert_label})")
                
                # Execute underlying hedge (existing logic)
                success = self._execute_underlying_hedge(und_sym, units_to_trade, kind, price, cur_dollar_delta, desired_dollar_delta, revert_label, base_notional, lo_notional, hi_notional)
                if success:
                    did_trade = True
                    
            # 5. Reduce option positions if margin doesn't allow
            elif (projected_margin_utilization > overnight_margin_max and 
                  getattr(self.algorithm, 'p2_option_reduction_enabled', True)):
                
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"P2 OPTION REDUCTION: Margin would exceed {overnight_margin_max:.1%}, reducing option positions instead")
                
                # Execute option position reduction
                success = self._execute_option_position_reduction(und_sym, delta_dollar_delta, cur_dollar_delta, desired_dollar_delta, revert_label)
                if success:
                    did_trade = True

        return did_trade

    def _execute_underlying_hedge(self, und_sym, units_to_trade, kind, price, cur_dollar_delta, desired_dollar_delta, revert_label, base_notional, lo_notional, hi_notional):
        """Execute underlying hedge with existing logic"""
        try:
            # Net out any existing open orders to avoid double hedging
            open_qty = 0
            for order_ticket in self.algorithm.Transactions.GetOpenOrders(und_sym):
                open_qty += order_ticket.Quantity

            units_to_trade -= int(open_qty)

            # Guard against zero-quantity orders after netting
            if units_to_trade == 0:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"P2 HEDGE SKIP: {und_sym} - existing open orders net to zero additional hedge needed")
                return False

            # Skip if market closed for underlying
            try:
                if not self.algorithm.IsMarketOpen(und_sym):
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"P2 HEDGE SKIP: {und_sym} - market closed")
                    return False
            except Exception:
                pass

            # Final guard: don't submit zero-quantity orders
            if units_to_trade == 0:
                return False

            # Place the hedge order
            if not self.algorithm.intraday_hedging:
                # EOD: use close price limit orders
                close_price = self.algorithm.Securities[und_sym].Close
                if close_price is None or close_price == 0:
                    close_price = price
                close_price = round(close_price, 2)

                qty = int(units_to_trade)
                price = float(close_price)
                ticket = self.algorithm.LimitOrder(und_sym, qty, price, tag=self.algorithm.HEDGE_TAG)
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"P2 EOD HEDGE: {und_sym} {units_to_trade:+d} "
                                      f"{'shares' if kind=='equity' else 'contracts'} @ ${close_price:.2f}")
            else:
                # Intraday: market orders
                qty = int(units_to_trade)
                ticket = self.algorithm.MarketOrder(und_sym, qty, tag=self.algorithm.HEDGE_TAG)

            if ticket.Status in (OrderStatus.Submitted, OrderStatus.Filled):
                # Enhanced logging - handle NAV mode (base_notional is None) vs TRADE mode
                if base_notional is not None:
                    # TRADE mode: show base notional
                    self.algorithm.Log(
                        f"P2 PORTFOLIO REBALANCE {und_sym}: {units_to_trade:+d} "
                        f"{'shares' if kind=='equity' else 'contracts'} | "
                        f"cur_delta=${cur_dollar_delta:,.0f} → "
                        f"{revert_label}=${desired_dollar_delta:,.0f} "
                        f"(trade_base=${base_notional:,.0f}, band [${lo_notional:,.0f}, ${hi_notional:,.0f}])"
                    )
                else:
                    # NAV mode: no base notional
                    self.algorithm.Log(
                        f"P2 PORTFOLIO REBALANCE {und_sym}: {units_to_trade:+d} "
                        f"{'shares' if kind=='equity' else 'contracts'} | "
                        f"cur_delta=${cur_dollar_delta:,.0f} → "
                        f"{revert_label}=${desired_dollar_delta:,.0f} "
                        f"(NAV mode, band [${lo_notional:,.0f}, ${hi_notional:,.0f}])"
                    )
                return True

        except Exception as e:
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"P2 underlying hedge error on {und_sym}: {e}")
        
        return False

    def _calculate_current_margin_per_contract(self, strike, option_price, underlying_price):
        """
        Calculate current estimated margin per contract using Reg-T style estimation.
        This matches the same calculation used in risk_manager.py but with current prices.
        """
        try:
            # Reg-T style margin estimation for short puts
            otm = max(0.0, underlying_price - strike)  # Out-of-the-money amount
            
            # Two common Reg-T floors
            estimate1 = 0.20 * underlying_price * 100 - otm * 100 + option_price * 100  # 20% underlying - OTM + premium
            estimate2 = 0.10 * underlying_price * 100 + option_price * 100              # 10% underlying + premium
            pct_floor = getattr(self.algorithm, 'estimated_margin_pct', 0.10) * strike * 100  # Config percentage floor
            
            estimated_margin_per_contract = max(estimate1, estimate2, pct_floor)
            estimated_margin_per_contract = max(500, estimated_margin_per_contract)  # Small hard floor
            
            return estimated_margin_per_contract
        except Exception as e:
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Error calculating current margin per contract: {e}")
            return 1000.0  # Fallback margin estimate

    def _execute_option_position_reduction(self, und_sym, delta_dollar_delta, cur_dollar_delta, desired_dollar_delta, revert_label):
        """Execute option position reduction using hybrid approach"""
        try:
            # Get all option positions for this underlying
            option_positions = []
            for pos_id, pos in self.algorithm.positions.items():
                if (pos.get('quantity', 0) != 0 and 
                    not pos.get('is_hedge', False) and 
                    pos.get('symbol') and 
                    pos['symbol'].SecurityType == SecurityType.Option):
                    
                    # Check if this option is for the current underlying
                    try:
                        opt_und_sym = self._get_underlying_symbol(pos['symbol'])
                        if opt_und_sym == und_sym:
                            option_positions.append({
                                'pos_id': pos_id,
                                'symbol': pos['symbol'],
                                'quantity': pos['quantity'],
                                'delta': pos.get('delta', 0.0),
                                'strike': pos.get('strike', 0.0),
                                'expiration': pos.get('expiration'),
                                'entry_price': pos.get('entry_price', 0.0),
                                'estimated_margin': pos.get('estimated_margin', 0.0)
                            })
                    except Exception:
                        continue
            
            if not option_positions:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"P2 OPTION REDUCTION: No option positions found for {und_sym}")
                return False
            
            # Calculate hybrid scores for position selection
            underlying_price = float(self.algorithm.Securities[und_sym].Price)
            
            for pos in option_positions:
                # Get current option price and Greeks
                current_price = 0.0
                current_delta = 0.0
                if pos['symbol'] in self.algorithm.Securities:
                    current_price = float(self.algorithm.Securities[pos['symbol']].Price)
                    # Get current delta using greeks_provider
                    current_delta, _ = self.algorithm.greeks_provider.get_delta(
                        pos['symbol'], 
                        pos.get('strike', 0), 
                        underlying_price, 
                        pos.get('expiration', None)
                    )
                
                # Use current delta instead of cached delta
                pos['delta'] = current_delta
                
                # Reduced debug logging for position data (using current delta)
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(
                        f"P2 POSITION: {pos['symbol']} qty={pos['quantity']} Δ={current_delta:.3f} margin=${pos.get('estimated_margin', 0.0):,.0f}"
                    )
                
                # Calculate CURRENT estimated margin (not cached from entry)
                current_estimated_margin_per_contract = self._calculate_current_margin_per_contract(
                    pos.get('strike', 0), 
                    current_price, 
                    underlying_price
                )
                current_estimated_margin = current_estimated_margin_per_contract * abs(pos['quantity'])
                pos['estimated_margin'] = current_estimated_margin
                
                # Calculate efficiency metrics
                delta_contribution = abs(pos['delta'] * pos['quantity'] * 100)
                margin_per_contract = current_estimated_margin_per_contract
                
                # Delta efficiency (delta per margin dollar)
                pos['delta_efficiency'] = delta_contribution / current_estimated_margin if current_estimated_margin > 0 else 0
                
                # Reduced debug logging for efficiency metrics
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(
                        f"P2 EFFICIENCY: {pos['symbol']} Δ={current_delta:.3f} eff={pos['delta_efficiency']:.4f} contrib={delta_contribution:,.0f}"
                    )
                
                # Size factor (prefer larger positions for reduction)
                pos['size_factor'] = min(abs(pos['quantity']) / 50, 1.0)  # Normalize to 50 contracts
                
                # DTE factor (prefer reducing near-expiration)
                if pos['expiration']:
                    try:
                        dte = (pos['expiration'] - self.algorithm.Time).days
                        pos['dte_factor'] = max(0, (30 - dte) / 30) if dte < 30 else 0
                    except:
                        pos['dte_factor'] = 0
                else:
                    pos['dte_factor'] = 0
                
                # P&L factor (prefer reducing losing positions)
                if pos['entry_price'] > 0 and current_price > 0:
                    pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
                    pos['pnl_factor'] = max(0, -pnl_pct)  # Positive for losing positions
                else:
                    pos['pnl_factor'] = 0
                
                # Combined score using config weights
                delta_weight = getattr(self.algorithm, 'p2_delta_efficiency_weight', 0.4)
                size_weight = getattr(self.algorithm, 'p2_size_factor_weight', 0.2)
                dte_weight = getattr(self.algorithm, 'p2_dte_factor_weight', 0.2)
                pnl_weight = getattr(self.algorithm, 'p2_pnl_factor_weight', 0.2)
                
                pos['reduction_score'] = (
                    pos['delta_efficiency'] * delta_weight +
                    pos['size_factor'] * size_weight +
                    pos['dte_factor'] * dte_weight +
                    pos['pnl_factor'] * pnl_weight
                )
            
            # Sort by combined score (highest first)
            option_positions.sort(key=lambda p: p['reduction_score'], reverse=True)
            
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"P2 REDUCTION: {len(option_positions)} positions, need ${delta_dollar_delta:,.0f} delta reduction")
                # Show top 3 positions in compact format
                for i, pos in enumerate(option_positions[:3]):
                    self.algorithm.Debug(f"  {i+1}. {pos['symbol']}: score={pos['reduction_score']:.3f} eff={pos['delta_efficiency']:.3f}")
            
            # Reduce positions until we achieve target delta reduction (in dollar-delta terms)
            total_delta_reduced = 0.0
            positions_reduced_count = 0
            max_reduction_pct = getattr(self.algorithm, 'p2_option_reduction_max_pct', 0.20)
            
            for pos in option_positions:
                if total_delta_reduced >= abs(delta_dollar_delta):
                    break
                
                # Calculate how much to reduce this position
                position_delta = pos['delta'] * pos['quantity'] * 100
                
                # Calculate remaining delta needed
                remaining_delta_needed = abs(delta_dollar_delta) - total_delta_reduced
                if remaining_delta_needed <= 0:
                    break
                
                # Calculate exactly how many contracts needed to hit the target
                delta_per_contract = abs(pos['delta']) * 100 * underlying_price
                if delta_per_contract <= 0:
                    continue
                
                contracts_needed = int(remaining_delta_needed / delta_per_contract)
                
                # Use the smaller of: contracts needed for target, max percentage, or full position
                max_reduction_contracts = int(abs(pos['quantity']) * max_reduction_pct)
                max_reduction_contracts = min(contracts_needed, max_reduction_contracts, int(abs(pos['quantity'])))
                
                if max_reduction_contracts == 0:
                    continue
                
                # Calculate dollar-delta reduction from this position
                # Option dollar-delta = delta × contracts × 100 × underlying_price
                # We accumulate absolute reduction towards the target
                reduction_delta_dollar = abs(pos['delta']) * max_reduction_contracts * 100 * underlying_price
                
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(
                        f"P2 REDUCING: {pos['symbol']} -{max_reduction_contracts} contracts, Δ${reduction_delta_dollar:,.0f}"
                    )
                
                # Execute the reduction
                # If currently long (>0), sell (negative) to reduce; if short (<0), buy (positive) to reduce
                reduction_qty = -max_reduction_contracts if pos['quantity'] > 0 else max_reduction_contracts
                
                # Place limit order to close partial position using proper pricing
                symbol = pos['symbol']
                sec = self.algorithm.Securities[symbol]
                bid = float(getattr(sec, "BidPrice", 0) or 0)
                ask = float(getattr(sec, "AskPrice", 0) or 0)
                
                if bid > 0 and ask > 0:
                    # Calculate limit price using same logic as fill model
                    haircut_fraction = self.algorithm.mid_haircut_fraction
                    mid = (bid + ask) / 2
                    spread = ask - bid
                    
                    if reduction_qty > 0:  # Buying back (closing short position)
                        limit_price = mid + haircut_fraction * spread
                        limit_price = min(max(limit_price, bid), ask)  # Clamp to book
                    else:  # Selling (closing long position)
                        limit_price = mid - haircut_fraction * spread
                        limit_price = min(max(limit_price, bid), ask)  # Clamp to book
                    
                    ticket = self.algorithm.LimitOrder(symbol, reduction_qty, round(limit_price, 2), tag=f"P2_REDUCTION_{pos['pos_id']}")
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"   - P2 REDUCTION limit order: {symbol} {reduction_qty:+d} @ ${limit_price:.2f} (bid={bid}, ask={ask})")
                else:
                    # Fallback to market order only if no quotes available
                    ticket = self.algorithm.MarketOrder(pos['symbol'], reduction_qty, tag=f"P2_REDUCTION_{pos['pos_id']}")
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"   - P2 REDUCTION fallback market order: {symbol} {reduction_qty:+d} (no quotes)")
                
                if ticket.Status in (OrderStatus.Submitted, OrderStatus.Filled):
                    total_delta_reduced += reduction_delta_dollar
                    positions_reduced_count += 1
                    
                    self.algorithm.Log(
                        f"P2 OPTION REDUCTION: {pos['symbol']} {reduction_qty:+d} contracts | "
                        f"Δ${reduction_delta_dollar:,.0f} | Score={pos['reduction_score']:.3f} | "
                        f"Total reduced=${total_delta_reduced:,.0f}"
                    )
            
            if total_delta_reduced > 0:
                self.algorithm.Log(
                    f"P2 OPTION REDUCTION COMPLETE: Reduced ${total_delta_reduced:,.0f} delta "
                    f"from {positions_reduced_count} positions"
                )
                return True
            
        except Exception as e:
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"P2 option position reduction error: {e}")
        
        return False

    def execute_delta_hedge_for_trade(self, option_symbol: Symbol, position_quantity: int) -> bool:
        """Per-trade hedge: hedge only the just-filled option exposure to the trade target (percent of base).
        Uses TRADE sizing config for equities; does nothing if symbol/underlying missing.
        """
        try:
            if option_symbol not in self.algorithm.Securities:
                return False
            und_sym = self._get_underlying_symbol(option_symbol)
            if und_sym not in self.algorithm.Securities:
                return False

            # Determine kind and price
            kind = self._asset_kind(und_sym)
            price = float(self.algorithm.Securities[und_sym].Price)
            if price <= 0:
                return False
            mult = self._fut_multiplier(und_sym) if kind == 'future' else 1.0

            # Compute delta for this option only
            # Get position details
            qty = float(position_quantity)
            pos = None
            for p in self.algorithm.positions.values():
                if p.get('symbol') == option_symbol:
                    pos = p
                    break
            if pos is None:
                # Fallback to provided quantity
                pass

            # Try to get delta from position data first (more reliable for immediate hedging)
            if pos and 'delta' in pos:
                d = float(pos['delta'])
                delta_source = "POSITION"
            else:
                d, delta_source = self.algorithm.greeks_provider.get_delta(option_symbol, pos['strike'] if pos else None,
                                                                     price, pos['expiration'] if pos else None)
            units_per_contract = 100.0 if kind == 'equity' else 1.0
            units_contrib = d * qty * units_per_contract
            notional_contrib = units_contrib * (price if kind == 'equity' else price * mult)
            
            # Debug the delta calculation
            # Removed verbose HEDGE DEBUG logging

            # Base notional for this trade = abs(qty) * units_per_contract * underlying price
            base_notional = abs(qty) * units_per_contract * (price if kind == 'equity' else price * mult)
            target_notional = (base_notional *
                               (self.algorithm.delta_target_trade_pct_equity if kind == 'equity'
                                else self.algorithm.delta_target_trade_pct_future))

            # For per-trade hedging, we ignore existing hedge positions and hedge only this trade
            # This ensures each new trade gets its own independent hedge in Phase 1
            # Existing hedges are handled separately in Phase 2 portfolio rebalancing
            
            # Desired exposure for this trade only = target_notional
            # We hedge only the gap between desired and this trade's contribution
            delta_notional = target_notional - notional_contrib
            denom = price if kind == 'equity' else price * mult
            units_to_trade = int(round(delta_notional / denom))
            
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"HEDGE: {und_sym} {units_to_trade} units | base ${base_notional/1000:.0f}K|target ${target_notional/1000:.0f}K|contrib ${notional_contrib/1000:.0f}K|delta ${delta_notional/1000:.0f}K")

            if units_to_trade == 0:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"HEDGE SKIP (PER-TRADE): {und_sym} - delta_notional=${delta_notional:.0f} results in 0 units")
                return False

            # Net out open orders
            open_qty = 0
            for order_ticket in self.algorithm.Transactions.GetOpenOrders(und_sym):
                open_qty += order_ticket.Quantity
            units_to_trade -= int(open_qty)
            if units_to_trade == 0:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"HEDGE SKIP (PER-TRADE): {und_sym} - existing open orders net to zero")
                return False

            # Buying power guard for equities
            if kind == 'equity':
                try:
                    remaining = float(self.algorithm.Portfolio.MarginRemaining)
                    est_cost = abs(units_to_trade) * float(price)
                    if est_cost > remaining * 0.9 and price > 0:
                        max_units = int((remaining * 0.9) / float(price))
                        units_to_trade = int(max_units if units_to_trade > 0 else -max_units)
                        if units_to_trade == 0:
                            if self.algorithm.debug_mode:
                                self.algorithm.Debug(f"HEDGE SKIP (PER-TRADE): {und_sym} - insufficient buying power")
                            return False
                except Exception:
                    pass

            qty_to_send = int(units_to_trade)
            # Create a unique hedge tag that includes the option symbol for per-trade hedging
            hedge_tag = f"{self.algorithm.HEDGE_TAG}_{option_symbol}"
            ticket = self.algorithm.MarketOrder(und_sym, qty_to_send, tag=hedge_tag)
            if ticket.Status in (OrderStatus.Submitted, OrderStatus.Filled):
                return True
        except Exception as e:
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Per-trade hedge error: {e}")
        return False


    def _trade_target_and_band(self, kind, base_notional):
        """Calculate target and tolerance band for TRADE mode"""
        try:
            if kind == 'equity':
                target_pct = self.algorithm.delta_target_trade_pct_equity
                tolerance_pct = self.algorithm.delta_tol_trade_pct_equity
            else:
                target_pct = self.algorithm.delta_target_trade_pct_future
                tolerance_pct = self.algorithm.delta_tol_trade_pct_future
                
            target_notional = base_notional * target_pct
            tolerance_notional = base_notional * tolerance_pct
            
            lo_notional = target_notional - tolerance_notional
            hi_notional = target_notional + tolerance_notional
            
            return target_notional, (lo_notional, hi_notional)
            
        except Exception as e:
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Trade target and band calculation error: {e}")
            return 0.0, (0.0, 0.0)

    def execute_delta_hedge_simple(self):
        """Simple delta hedge using actual option Greeks and market orders."""
        try:
            portfolio_delta = 0.0

            for position in self.algorithm.positions.values():
                if position.get('is_hedge', False):
                    continue
                sym = position.get('symbol')
                if sym is None:
                    continue
                if sym.SecurityType != SecurityType.Option:
                    continue
                if sym not in self.algorithm.Securities:
                    continue
                sec = self.algorithm.Securities[sym]
                if hasattr(sec, 'Greeks') and sec.Greeks is not None and sec.Greeks.Delta is not None:
                    actual_delta = float(sec.Greeks.Delta)
                    portfolio_delta += actual_delta * float(position.get('quantity', 0)) * 100.0

            hedge_shares = self.algorithm.target_delta - portfolio_delta
            if abs(hedge_shares) > self.algorithm.delta_tolerance:
                qty = int(hedge_shares)
                if qty != 0:
                    self.algorithm.MarketOrder(self.algorithm.underlying_symbol, qty, tag=self.algorithm.HEDGE_TAG)
                    return True
        except Exception as e:
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Simple delta hedge error: {e}")
        return False


    def _trade_base_notional(self, und_sym, kind, price, mult, pending=None):
        """Calculate base notional for TRADE mode as underlying notional of option positions:
        sum(|contracts| * units_per_contract * underlying_price).
        Includes both filled positions and pending trades.
        Excludes hedge holdings; uses current underlying price for accuracy.
        """
        units_per_contract = 100.0 if kind == 'equity' else 1.0
        base = 0.0

        if self.algorithm.debug_mode:
            self.algorithm.Debug(f"_TRADE_BASE_NOTIONAL: und_sym={und_sym}, pending={pending}")

        # Include filled option positions
        for pos in [p for p in self.algorithm.positions.values()
                    if p.get('quantity', 0) != 0 and not p.get('is_hedge', False)]:
            try:
                if self._get_underlying_symbol(pos['symbol']) != und_sym:
                    continue
            except Exception:
                continue
            base += abs(pos['quantity']) * units_per_contract * (price if kind == 'equity' else price * mult)
                # Added filled position to base notional calculation

        # Include pending option trades (only if not already filled)
        if pending:
            for item in pending:
                if len(item) >= 2:
                    opt_symbol, qty = item[0], item[1]
                try:
                    if self._get_underlying_symbol(opt_symbol) != und_sym:
                        continue
                except Exception:
                    continue
                
                # Check if this trade is already filled to avoid double-counting
                already_filled = False
                for pos in self.algorithm.positions.values():
                    if (pos.get('quantity', 0) != 0 and 
                        not pos.get('is_hedge', False) and 
                        pos['symbol'] == opt_symbol):
                        already_filled = True
                        break
                
                if not already_filled:
                    contrib = abs(qty) * units_per_contract * (price if kind == 'equity' else price * mult)
                    base += contrib
                    # Added pending trade to base notional calculation
                # else: skipped already filled pending trade

        # Final base notional calculated

        return base
