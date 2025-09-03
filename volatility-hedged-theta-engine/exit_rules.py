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

        positions_to_close = []

        for pos_id, position in self.algorithm.positions.items():
            symbol = position['symbol']

            if symbol not in self.algorithm.Securities:
                self.algorithm.Debug(f"Position {pos_id} no longer in securities, forcing close")
                positions_to_close.append((pos_id, "Symbol Removed", 0))
                continue

            # Use BBO mid for options to avoid zero prices in Daily mode
            if symbol.SecurityType == SecurityType.Option:
                current_price = self.algorithm.GetOptionEodPrice(symbol)
                if current_price <= 0:
                    # Skip this position for now; don't force-close on missing mid
                    self.algorithm.Debug(f"Skip exit: no EOD mid for {symbol}")
                    continue
            else:
                current_price = self.algorithm.Securities[symbol].Price
                if current_price == 0:
                    self.algorithm.Debug(f"Position {pos_id} has zero price, forcing close")
                    positions_to_close.append((pos_id, "Zero Price", 0))
                    continue

            entry_price = position['entry_price']

            pnl_per_contract = entry_price - current_price
            total_pnl = pnl_per_contract * abs(position['quantity']) * 100
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

            # Exit conditions (in priority order)
            if dte <= 2 and current_price <= entry_price * self.algorithm.let_expire_threshold:
                exit_reason = "Let Expire"
            elif total_pnl >= credit_received * self.algorithm.quick_profit_target and dte > self.algorithm.quick_profit_min_dte:
                exit_reason = f"Quick Profit ({self.algorithm.quick_profit_target:.0%})"
            elif total_pnl >= credit_received * self.algorithm.normal_profit_target:
                exit_reason = f"Profit Target ({self.algorithm.normal_profit_target:.0%})"
            elif total_pnl <= -credit_received * self.algorithm.stop_loss_multiplier:
                exit_reason = f"Stop Loss ({self.algorithm.stop_loss_multiplier:.0%})"
            elif dte < self.algorithm.time_stop_dte and total_pnl < credit_received * self.algorithm.quick_profit_target:
                # Time stop: if <15 DTE and not at quick profit target, reduce risk
                if self.algorithm.time_stop_action == "ROLL":
                    exit_reason = f"Time Stop (<{self.algorithm.time_stop_dte} DTE, rolling)"
                else:  # CLOSE
                    exit_reason = f"Time Stop (<{self.algorithm.time_stop_dte} DTE, closing)"
            elif dte <= self.algorithm.min_dte:
                exit_reason = "Rolling"

            if exit_reason:
                positions_to_close.append((pos_id, exit_reason, total_pnl))

        for pos_id, reason, pnl in positions_to_close:
            self.close_position(pos_id, reason, pnl)

    def close_position(self, position_id, reason, expected_pnl):
        """Close position and track performance"""
        if position_id not in self.algorithm.positions:
            return

        position = self.algorithm.positions[position_id]
        symbol = position['symbol']

        try:
            # Use BBO mid for option exits
            if symbol.SecurityType == SecurityType.Option:
                exit_price = self.algorithm.GetOptionEodPrice(symbol)
            else:
                exit_price = self.algorithm.Securities[symbol].Price if symbol in self.algorithm.Securities else 0.0

            # Guard against zero prices - refuse to send order at $0.00
            if exit_price <= 0:
                self.algorithm.Debug(f"Abort close: no valid exit price for {symbol}")
                return

            exit_price = round(exit_price, 2)

            # Calculate actual P&L
            pnl_per_contract = position['entry_price'] - exit_price
            actual_pnl = pnl_per_contract * abs(position['quantity']) * 100

            # Place closing order
            if not self.algorithm.intraday_hedging:
                # EOD: use limit orders
                ticket = self.algorithm.LimitOrder(symbol, -position['quantity'], exit_price)
                self.algorithm.Debug(f"EOD CLOSE: {symbol} LIMIT @ ${exit_price:.2f}")
            else:
                # Intraday: market orders
                ticket = self.algorithm.MarketOrder(symbol, -position['quantity'])

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
                
                self.algorithm.Log(f"POSITION EXIT: {symbol} | {reason} | "
                                f"Entry: ${position['entry_price']:.2f} | "
                                f"Exit: ${exit_price:.2f} | "
                                f"P&L: ${actual_pnl:.2f} | "
                                f"DTE: {dte_for_log}")

                # Remove from tracking
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

            # Roll conditions
            if dte <= self.algorithm.min_dte:
                return True, "Minimum DTE reached"
            elif dte < self.algorithm.time_stop_dte and total_pnl < credit_received * self.algorithm.quick_profit_target:
                return True, f"Time stop at {dte} DTE"
            elif total_pnl <= -credit_received * self.algorithm.stop_loss_multiplier * 0.5:
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

            # P&L calculations
            pnl_per_contract = entry_price - current_price
            total_pnl = pnl_per_contract * abs(quantity) * 100
            pnl_pct = total_pnl / credit_received if credit_received > 0 else 0

            # Risk metrics
            max_loss = credit_received * self.algorithm.stop_loss_multiplier
            current_loss_pct = -total_pnl / max_loss if max_loss > 0 else 0

            # Profit targets
            quick_profit_level = credit_received * self.algorithm.quick_profit_target
            normal_profit_level = credit_received * self.algorithm.normal_profit_target

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
