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

    def compute_delta_groups(self):
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
        groups = defaultdict(lambda: {'units': 0.0, 'notional': 0.0, 'price': 0.0, 'mult': 1.0, 'kind': None})

        # PERFORMANCE OPTIMIZATION: Only process underlyings we actually hedge
        # Build set of relevant underlyings from ACTIVE positions and known underlying
        relevant_underlyings = set()

        # Always include the main underlying
        relevant_underlyings.add(self.algorithm.underlying_symbol)

        # Include underlyings from ACTIVE option positions only
        active_option_positions = [pos for pos_id, pos in self.algorithm.positions.items()
                                   if pos.get('quantity', 0) != 0 and not pos.get('is_hedge', False)]
        for position in active_option_positions:
            if position.get('symbol'):  # Skip hedge positions
                opt_sym = position['symbol']
                und_sym = self._get_underlying_symbol(opt_sym)
                relevant_underlyings.add(und_sym)

        # 1) Include underlying holdings (delta = +1 per unit) - ONLY RELEVANT ONES
        for und_sym in relevant_underlyings:
            if und_sym not in self.algorithm.Securities:
                continue

            # Only check portfolio if we actually have this symbol invested
            if und_sym in self.algorithm.Portfolio and self.algorithm.Portfolio[und_sym].Invested:
                sec = self.algorithm.Securities[und_sym]
                kind = self._asset_kind(und_sym)
                price = sec.Price
                mult = self._fut_multiplier(und_sym) if kind == 'future' else 1.0
                units = self.algorithm.Portfolio[und_sym].Quantity  # shares or contracts

                groups[und_sym]['units'] += units
                groups[und_sym]['notional'] += units * (price if kind == 'equity' else price * mult)
                groups[und_sym]['price'] = price
                groups[und_sym]['mult'] = mult
                groups[und_sym]['kind'] = kind

        # 2) Add each ACTIVE option position's delta contribution
        for position in active_option_positions:
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

            # Get delta (actual or estimated)
            if hasattr(opt_sec, 'Greeks') and opt_sec.Greeks is not None and opt_sec.Greeks.Delta is not None:
                d = float(opt_sec.Greeks.Delta)
            else:
                d = float(self.algorithm.EstimatePutDelta(position['strike'], price, position['expiration']))

            # Units-equivalent per contract:
            # Equity options: 100 shares per 1Δ
            # Futures options: 1 futures contract per 1Δ
            units_per_contract = 100.0 if kind == 'equity' else 1.0
            units_contrib = d * qty * units_per_contract

            # USD notional contribution
            notional_contrib = units_contrib * (price if kind == 'equity' else price * mult)

            g = groups[und_sym]
            g['units'] += units_contrib
            g['notional'] += notional_contrib
            g['price'] = price
            g['mult'] = mult
            g['kind'] = kind

        return groups

    def _nav_target_and_band(self, kind):
        """Get NAV-based target and tolerance band"""
        if kind == 'equity':
            tgt = self.algorithm.Portfolio.TotalPortfolioValue * self.algorithm.delta_target_nav_pct_equity
            tol = self.algorithm.Portfolio.TotalPortfolioValue * self.algorithm.delta_tol_nav_pct_equity
        else:
            tgt = self.algorithm.Portfolio.TotalPortfolioValue * self.algorithm.delta_target_nav_pct_future
            tol = self.algorithm.Portfolio.TotalPortfolioValue * self.algorithm.delta_tol_nav_pct_future
        return tgt, (tgt - tol, tgt + tol)

    def _points_target_and_band(self, kind):
        """Get points-based target and tolerance band"""
        if kind == 'equity':
            tgt_units = 100.0 * self.algorithm.equity_delta_target_points
            tol_units = 100.0 * self.algorithm.equity_delta_tol_points
        else:  # futures
            tgt_units = float(self.algorithm.futures_delta_target_contracts)
            tol_units = float(self.algorithm.futures_delta_tol_contracts)
        return tgt_units, (tgt_units - tol_units, tgt_units + tol_units)

    def execute_delta_hedge_universal(self):
        """
        Universal delta hedging for equity options and futures options.
        Hedges each underlying independently using configurable sizing.
        Only considers active positions (quantity != 0).
        """
        # Get active positions only (quantity != 0)
        active_positions = [pos for pos_id, pos in self.algorithm.positions.items() if pos.get('quantity', 0) != 0]

        # CRITICAL FIX: If no active option positions remain, clear any existing hedge
        if not active_positions:
            underlying_symbol = self.algorithm.underlying_symbol
            if underlying_symbol in self.algorithm.Securities:
                current_qty = self.algorithm.Portfolio[underlying_symbol].Quantity
                if current_qty != 0:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"HEDGE CLEAR: No active option positions, liquidating {current_qty} shares")

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
        
        groups = self.compute_delta_groups()
        did_trade = False

        for und_sym, g in groups.items():
            kind = g['kind']
            price = g['price']
            mult = g['mult']

            if price <= 0 or kind is None:
                continue

            # Current exposure
            cur_units = g['units']      # shares or contracts
            cur_notional = g['notional']  # USD

            # Get target and band based on sizing mode
            if self.algorithm.delta_sizing_mode.upper() == "NAV":
                target_notional, (lo_notional, hi_notional) = self._nav_target_and_band(kind)

                # Check if outside band
                if lo_notional <= cur_notional <= hi_notional:
                    continue

                # Determine desired notional
                if self.algorithm.delta_revert_mode.upper() == "TARGET":
                    desired_notional = target_notional
                else:  # BAND
                    desired_notional = lo_notional if cur_notional < lo_notional else hi_notional

                delta_notional = desired_notional - cur_notional

                # Convert notional gap to trade units
                denom = price if kind == 'equity' else price * mult
                units_to_trade = int(round(delta_notional / denom))

            else:  # POINTS mode
                target_units, (lo_units, hi_units) = self._points_target_and_band(kind)

                # Check if outside band
                if lo_units <= cur_units <= hi_units:
                    continue

                # Determine desired units
                if self.algorithm.delta_revert_mode.upper() == "TARGET":
                    desired_units = target_units
                else:  # BAND
                    desired_units = lo_units if cur_units < lo_units else hi_units

                units_to_trade = int(round(desired_units - cur_units))

            if units_to_trade == 0:
                continue

            # CRITICAL FIX: Net out any existing open orders to avoid double hedging
            open_qty = 0
            for order_ticket in self.algorithm.Transactions.GetOpenOrders(und_sym):
                # For open orders, assume full quantity is still pending
                # (QuantConnect's order tickets don't have QuantityFilled property)
                open_qty += order_ticket.Quantity

            units_to_trade -= int(open_qty)

            # Guard against zero-quantity orders after netting
            if units_to_trade == 0:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"HEDGE SKIP: {und_sym} - existing open orders net to zero additional hedge needed")
                continue

            # Final guard: don't submit zero-quantity orders
            if units_to_trade == 0:
                continue

            # Place the hedge order
            try:
                if not self.algorithm.intraday_hedging:
                    # EOD: use close price limit orders
                    close_price = self.algorithm.Securities[und_sym].Close
                    if close_price is None or close_price == 0:
                        close_price = price
                    close_price = round(close_price, 2)

                    ticket = self.algorithm.LimitOrder(und_sym, units_to_trade, close_price)
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"EOD HEDGE UNIVERSAL: {und_sym} {units_to_trade:+d} "
                                          f"{'shares' if kind=='equity' else 'contracts'} @ ${close_price:.2f}")
                else:
                    # Intraday: market orders
                    ticket = self.algorithm.MarketOrder(und_sym, units_to_trade)

                if ticket.Status in (OrderStatus.Submitted, OrderStatus.Filled):
                    did_trade = True

                    # Enhanced logging
                    if self.algorithm.delta_sizing_mode.upper() == "NAV":
                        self.algorithm.Log(f"UNIVERSAL HEDGE {und_sym}: {units_to_trade:+d} "
                                        f"{'shares' if kind=='equity' else 'contracts'} | "
                                        f"cur_notional=${cur_notional:,.0f} → "
                                        f"target=${target_notional:,.0f} "
                                        f"(band [${lo_notional:,.0f}, ${hi_notional:,.0f}])")
                    else:
                        delta_pts = cur_units / 100.0 if kind == 'equity' else cur_units
                        target_pts = target_units / 100.0 if kind == 'equity' else target_units
                        self.algorithm.Log(f"UNIVERSAL HEDGE {und_sym}: {units_to_trade:+d} "
                                        f"{'shares' if kind=='equity' else 'contracts'} | "
                                        f"cur={cur_units:.1f} (~{delta_pts:.2f} Δ pts) → "
                                        f"target={target_units:.1f} (~{target_pts:.2f} Δ pts)")

            except Exception as e:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"Universal delta hedge error on {und_sym}: {e}")

        return did_trade
