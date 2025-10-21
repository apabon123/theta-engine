"""
Exit Rules Module for Theta Engine

This module handles all exit conditions, profit targets, stop losses, and position management.
Includes configurable time stops and adaptive exit logic.
"""

from AlgorithmImports import *


class ExitRulesManager:
    """Manages all exit rules and position closing logic"""

    def __init__(self, algorithm):
        self.algorithm = algorithm

    def check_exit_conditions(self):
        """Check exit conditions for all positions"""
        if not self.algorithm.positions:
            return

        # CRITICAL FIX: Don't check exits during warmup
        if self.algorithm.IsWarmingUp:
            return

        positions_to_close = []

        for pos_id, position in self.algorithm.positions.items():
            symbol = position['symbol']

            # FIX: Skip hedge positions - they don't have expirations and are rebalanced elsewhere
            if position.get('is_hedge', False):
                continue

            # EARLY GUARD: Skip zero-quantity placeholders
            if abs(position.get('quantity', 0)) == 0:
                continue

            if symbol not in self.algorithm.Securities:
                self.algorithm.Debug(f"Position {pos_id} no longer in securities, forcing close")
                positions_to_close.append((pos_id, "Symbol Removed", 0))
                continue

            # Use real market price from Security at minute resolution
            current_price = self.algorithm.Securities[symbol].Price
            if current_price <= 0:
                self.algorithm.Debug(f"Skip exit: no valid price for {symbol}")
                continue

            entry_price = position['entry_price']

            # FIX: Only multiply by 100 for options, not equities
            is_option = (symbol.SecurityType == SecurityType.Option)
            mult = 100 if is_option else 1
            pnl_per_contract = entry_price - current_price
            total_pnl = pnl_per_contract * abs(position['quantity']) * mult
            credit_received = position['credit_received']

            try:
                if hasattr(position['expiration'], 'date'):
                    expiry_date = position['expiration'].date()
                else:
                    expiry_date = position['expiration']

                dte = (expiry_date - self.algorithm.Time.date()).days
            except:
                self.algorithm.Debug(f"Error calculating DTE for position {pos_id}, forcing close")
                positions_to_close.append((pos_id, "DTE Error", total_pnl))
                continue

            exit_reason = None

            # FIX: Use absolute value of credit_received to handle negative credits properly
            credit_abs = abs(credit_received)

            # Exit conditions (in priority order)
            if dte <= 2 and current_price <= entry_price * self.algorithm.let_expire_threshold:
                exit_reason = "Let Expire"
            elif total_pnl >= credit_abs * self.algorithm.quick_profit_target and dte > self.algorithm.quick_profit_min_dte:
                exit_reason = f"Quick Profit ({self.algorithm.quick_profit_target:.0%})"
            elif total_pnl >= credit_abs * self.algorithm.normal_profit_target:
                exit_reason = f"Profit Target ({self.algorithm.normal_profit_target:.0%})"
            elif total_pnl <= -credit_abs * self.algorithm.stop_loss_multiplier:
                exit_reason = f"Stop Loss ({self.algorithm.stop_loss_multiplier:.0%})"
            elif dte < self.algorithm.time_stop_dte and total_pnl < credit_abs * self.algorithm.quick_profit_target:
                # Time stop: if <15 DTE and not at quick profit target, reduce risk
                if self.algorithm.time_stop_action == "ROLL":
                    exit_reason = f"Time Stop (<{self.algorithm.time_stop_dte} DTE, rolling)"
                else:  # CLOSE
                    exit_reason = f"Time Stop (<{self.algorithm.time_stop_dte} DTE, closing)"
            elif dte <= self.algorithm.min_dte:
                exit_reason = "Rolling"

            if exit_reason:
                # Calculate expected P&L based on exit reason
                if "Profit" in exit_reason:
                    # For profit exits, expected P&L is positive (we made money)
                    expected_pnl = credit_abs * (1 if "Quick" in exit_reason else 1)  # Both quick and normal are positive
                elif "Stop Loss" in exit_reason:
                    # For stop losses, expected P&L is negative (we lost money)
                    expected_pnl = -credit_abs * self.algorithm.stop_loss_multiplier
                elif "Time Stop" in exit_reason:
                    # For time stops, expected P&L depends on current profit level
                    current_profit_pct = total_pnl / credit_abs if credit_abs > 0 else 0
                    expected_pnl = credit_abs * current_profit_pct
                elif "Let Expire" in exit_reason:
                    # For let expire, expected P&L is current profit/loss
                    expected_pnl = total_pnl
                else:
                    # Default: use the credit received as positive for shorts
                    expected_pnl = credit_abs if position.get('quantity', 0) < 0 else -credit_abs

                positions_to_close.append((pos_id, exit_reason, expected_pnl))

        for pos_id, reason, expected_pnl in positions_to_close:
            self.close_position(pos_id, reason, expected_pnl)

    def close_position(self, position_id, reason, expected_pnl):
        """Close position and track performance"""
        if position_id not in self.algorithm.positions:
            return

        position = self.algorithm.positions[position_id]
        symbol = position['symbol']

        try:
            # Use real market price from Security for logging and P&L
            exit_price = self.algorithm.Securities[symbol].Price if symbol in self.algorithm.Securities else 0.0

            # Guard against zero prices - refuse to send order at $0.00
            if exit_price <= 0:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"Abort close: no valid exit price for {symbol}")
                return

            exit_price = round(exit_price, 2)

            # CRITICAL FIX: Check if security is tradable before placing order
            if symbol in self.algorithm.Securities and not self.algorithm.Securities[symbol].IsTradable:
                # Implement retry logic instead of immediate deletion
                retry_count = position.get('close_retry_count', 0) + 1
                position['close_retry_count'] = retry_count

                retry_limit = self.algorithm.nontradable_retry_limit
                if retry_count >= retry_limit:  # Allow configurable retries before giving up
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"Close failed {retry_limit}x: removing non-tradable {symbol} from tracking")
                    # Remove from tracking since we can't close it after multiple attempts
                    if position_id in self.algorithm.positions:
                        del self.algorithm.positions[position_id]
                    return
                else:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"Close retry {retry_count}/{retry_limit}: {symbol} not tradable, will retry later")
                    return

            # FIX: Calculate actual P&L with correct multiplier
            is_option = (symbol.SecurityType == SecurityType.Option)
            mult = 100 if is_option else 1
            pnl_per_contract = position['entry_price'] - exit_price
            actual_pnl = pnl_per_contract * abs(position['quantity']) * mult

            # CRITICAL FIX: Validate that the position actually exists and has non-zero quantity
            if abs(position['quantity']) < 1e-6:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"Abort close: position {position_id} has zero quantity, removing from tracking")
                del self.algorithm.positions[position_id]
                return
            
            # Calculate close quantity (opposite of current position)
            close_quantity = -position['quantity']
            if abs(close_quantity) < 1e-6:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"Abort close: calculated close quantity is zero for {symbol}")
                return

            # Place closing limit order using current bid/ask quotes
            try:
                qty = int(round(close_quantity))
                if qty == 0:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"Abort close: rounded to zero quantity for {symbol}")
                    del self.algorithm.positions[position_id]
                    return

                # Get current quotes from security
                sec = self.algorithm.Securities[symbol]
                bid = float(getattr(sec, "BidPrice", 0) or 0)
                ask = float(getattr(sec, "AskPrice", 0) or 0)

                # Validate quotes with retry logic
                quote_retry_count = position.get('quote_retry_count', 0)

                if bid <= 0 or ask <= 0:
                    quote_retry_count += 1
                    position['quote_retry_count'] = quote_retry_count

                    retry_limit = self.algorithm.quote_retry_limit
                    if quote_retry_count >= retry_limit:  # Allow configurable retries for bad quotes
                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"Close abandoned after {quote_retry_count} quote failures: {symbol}")
                        return
                    else:
                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"Quote retry {quote_retry_count}/{retry_limit}: {symbol} missing quotes, will retry next cycle")
                        return

                # Check for unreasonably wide spreads
                mid = (bid + ask) / 2
                spread_pct = abs(ask - bid) / mid if mid > 0 else 1.0
                if spread_pct > self.algorithm.exit_max_spread_pct:  # Configurable spread threshold
                    quote_retry_count += 1
                    position['quote_retry_count'] = quote_retry_count

                    retry_limit = self.algorithm.spread_retry_limit
                    if quote_retry_count >= retry_limit:  # Allow configurable retries for wide spreads
                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"Close abandoned after {quote_retry_count} wide spread failures: {symbol} ({spread_pct:.1%})")
                        return
                    else:
                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"Spread retry {quote_retry_count}/{retry_limit}: {symbol} wide spread ({spread_pct:.1%}), will retry next cycle")
                        return

                # Reset retry count on successful quote validation
                position['quote_retry_count'] = 0

                # Calculate limit price using same logic as MidHaircutFillModel for consistency
                # This ensures limit price matches expected fill price (mid ± haircut*spread)
                haircut_fraction = self.algorithm.mid_haircut_fraction  # Same as fill model
                spread = ask - bid
                
                if qty > 0:  # Buying back (closing short position)
                    # Use mid + haircut*spread (same as fill model for buys)
                    limit_price = mid + haircut_fraction * spread
                    # Clamp to book bounds for realism
                    limit_price = min(max(limit_price, bid), ask)
                else:  # Selling (closing long position)
                    # Use mid - haircut*spread (same as fill model for sells)
                    limit_price = mid - haircut_fraction * spread
                    # Clamp to book bounds for realism
                    limit_price = min(max(limit_price, bid), ask)

                # Final validation
                if limit_price <= 0:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"Skip close {symbol}: invalid limit price {limit_price}")
                    return

                # Place limit order with EXIT tag for identification
                ticket = self.algorithm.LimitOrder(symbol, qty, round(limit_price, 2), tag=self.algorithm.EXIT_TAG)
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"EXIT limit order: {symbol} {qty:+d} @ ${limit_price:.2f} (bid={bid}, ask={ask})")
                
                # CRITICAL FIX: Execute delta hedge immediately when exit order is placed
                # This is cleaner than waiting for the fill and avoids double-counting
                self.algorithm._execute_exit_delta_hedge(symbol, qty, reason)
            except Exception as e:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"Error placing close order for {symbol}: {e}")
                return


            if ticket.Status in (OrderStatus.Submitted, OrderStatus.Filled):
                # Update performance tracking
                self.algorithm.total_trades += 1
                if actual_pnl > 0:
                    self.algorithm.winning_trades += 1
                    self.algorithm.total_win_pnl += actual_pnl
                else:
                    self.algorithm.losing_trades += 1
                    self.algorithm.total_loss_pnl += actual_pnl

                # Log the exit
                try:
                    expiry_date = position['expiration'].date() if hasattr(position['expiration'], 'date') else position['expiration']
                    current_date = self.algorithm.Time.date() if hasattr(self.algorithm.Time, 'date') else self.algorithm.Time
                    dte_for_log = (expiry_date - current_date).days
                except:
                    dte_for_log = "N/A"
                
                # expected_pnl is already calculated in check_exit_conditions and passed as parameter

                self.algorithm.Log(f"POSITION EXIT: {symbol} | {reason} | "
                                f"Entry: ${position['entry_price']:.2f} | "
                                f"Exit: ${exit_price:.2f} | "
                                f"Actual P&L: ${actual_pnl:.2f} | "
                                f"DTE: {dte_for_log}")

                # CRITICAL FIX: Don't delete position until order actually fills
                # Position will be updated when the order fills in OnOrderEvent
                # Only delete if order failed to submit
                if ticket.Status == OrderStatus.Invalid:
                    if position_id in self.algorithm.positions:
                        del self.algorithm.positions[position_id]

            else:
                self.algorithm.Debug(f"Position close failed for {symbol}: {ticket.Status}")

        except Exception as e:
            self.algorithm.Debug(f"Error closing position {position_id}: {e}")
            # Still remove from tracking even if close failed
            del self.algorithm.positions[position_id]

    def should_roll_position(self, position, current_price):
        """
        Determine if a position should be rolled (closed and reopened)
        Returns (should_roll, reason)
        """
        try:
            entry_price = position['entry_price']
            credit_received = position['credit_received']
            pnl_per_contract = entry_price - current_price
            total_pnl = pnl_per_contract * abs(position['quantity']) * 100

            # Safe datetime calculation
            expiry_date = position['expiration'].date() if hasattr(position['expiration'], 'date') else position['expiration']
            current_date = self.algorithm.Time.date() if hasattr(self.algorithm.Time, 'date') else self.algorithm.Time
            dte = (expiry_date - current_date).days

            # FIX: Use absolute value for credit comparisons
            credit_abs = abs(credit_received)

            # Roll conditions
            if dte <= self.algorithm.min_dte:
                return True, "Minimum DTE reached"
            elif dte < self.algorithm.time_stop_dte and total_pnl < credit_abs * self.algorithm.quick_profit_target:
                return True, f"Time stop at {dte} DTE"
            elif total_pnl <= -credit_abs * self.algorithm.stop_loss_multiplier * 0.5:
                return True, "Partial stop loss - rolling to cut risk"

            return False, ""

        except Exception as e:
            self.algorithm.Debug(f"Error checking roll conditions: {e}")
            return False, "Error"

    def calculate_position_metrics(self, position, current_price):
        """
        Calculate various position metrics for monitoring
        """
        try:
            entry_price = position['entry_price']
            quantity = position['quantity']
            credit_received = position['credit_received']
            # Safe datetime calculation
            expiry_date = position['expiration'].date() if hasattr(position['expiration'], 'date') else position['expiration']
            current_date = self.algorithm.Time.date() if hasattr(self.algorithm.Time, 'date') else self.algorithm.Time
            dte = (expiry_date - current_date).days

            # FIX: P&L calculations with correct multiplier
            is_option = (position['symbol'].SecurityType == SecurityType.Option)
            mult = 100 if is_option else 1
            pnl_per_contract = entry_price - current_price
            total_pnl = pnl_per_contract * abs(quantity) * mult
            # FIX: Use absolute value for credit comparisons
            credit_abs = abs(credit_received)
            pnl_pct = total_pnl / credit_abs if credit_abs > 0 else 0

            # Risk metrics
            max_loss = credit_abs * self.algorithm.stop_loss_multiplier
            current_loss_pct = -total_pnl / max_loss if max_loss > 0 else 0

            # Profit targets
            quick_profit_level = credit_abs * self.algorithm.quick_profit_target
            normal_profit_level = credit_abs * self.algorithm.normal_profit_target

            return {
                'pnl_total': total_pnl,
                'pnl_pct': pnl_pct,
                'dte': dte,
                'quick_profit_level': quick_profit_level,
                'normal_profit_level': normal_profit_level,
                'max_loss': max_loss,
                'current_loss_pct': current_loss_pct,
                'is_quick_profit': total_pnl >= quick_profit_level,
                'is_normal_profit': total_pnl >= normal_profit_level,
                'is_stop_loss': total_pnl <= -max_loss,
                'time_stop_triggered': dte < self.algorithm.time_stop_dte and total_pnl < quick_profit_level
            }

        except Exception as e:
            self.algorithm.Debug(f"Error calculating position metrics: {e}")
            return {}
