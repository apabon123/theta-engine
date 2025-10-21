"""
Intraday Risk Monitor Module

Handles real-time risk monitoring during market hours to prevent margin calls.
Monitors margin utilization, portfolio loss, and triggers emergency exits when needed.
"""

from AlgorithmImports import *
from config import (
    INTRADAY_RISK_MONITORING_ENABLED, RISK_CHECK_INTERVAL_MINUTES, MARGIN_CALL_THRESHOLD,
    PORTFOLIO_LOSS_THRESHOLD, EMERGENCY_EXIT_THRESHOLD, RISK_ALERT_COOLDOWN_MINUTES,
    RISK_REDUCTION_ENABLED, RISK_REDUCTION_THRESHOLD, RISK_REDUCTION_TARGET, RISK_REDUCTION_COOLDOWN_MINUTES
)


class IntradayRiskMonitor:
    """
    Monitors intraday risk metrics to prevent margin calls.
    
    Features:
    - Real-time margin utilization monitoring
    - Portfolio loss tracking from start of day
    - Margin call buffer calculation
    - Emergency exit mechanism
    - Alert system with cooldown protection
    """
    
    def __init__(self, algorithm):
        self.algorithm = algorithm
        
        # Risk monitoring configuration (imported directly from config)
        self.enabled = INTRADAY_RISK_MONITORING_ENABLED
        self.check_interval_minutes = RISK_CHECK_INTERVAL_MINUTES
        self.margin_call_threshold = MARGIN_CALL_THRESHOLD
        self.portfolio_loss_threshold = PORTFOLIO_LOSS_THRESHOLD
        self.emergency_exit_threshold = EMERGENCY_EXIT_THRESHOLD
        self.alert_cooldown_minutes = RISK_ALERT_COOLDOWN_MINUTES
        
        # Risk reduction configuration
        self.risk_reduction_enabled = RISK_REDUCTION_ENABLED
        self.risk_reduction_threshold = RISK_REDUCTION_THRESHOLD
        self.risk_reduction_target = RISK_REDUCTION_TARGET
        self.risk_reduction_cooldown_minutes = RISK_REDUCTION_COOLDOWN_MINUTES
        
        # Risk monitoring state
        self.last_risk_check_time = None
        self.last_risk_alert_time = None
        self.portfolio_start_value = None
        self.risk_alerts_sent = set()  # Track which alerts have been sent
        self.last_hourly_log_time = None  # Track hourly logging
        self.last_risk_reduction_time = None  # Track risk reduction cooldown
        
        if self.enabled:
            self.algorithm.Log("Intraday Risk Monitor initialized")
    
    def check_risk(self):
        """
        Check intraday risk metrics to prevent margin calls.
        Runs every 30 minutes during market hours.
        """
        if not self.enabled:
            return
            
        try:
            current_time = self.algorithm.Time
            current_time_only = current_time.time()
            
            # Only check during market hours (9:30 AM - 4:00 PM ET)
            if not (9 <= current_time_only.hour <= 16):
                return
            
            # Check if enough time has passed since last risk check
            if self.last_risk_check_time:
                time_since_last = (current_time - self.last_risk_check_time).total_seconds() / 60
                if time_since_last < self.check_interval_minutes:
                    return
            
            # Update last check time
            self.last_risk_check_time = current_time
            
            # Initialize portfolio start value if not set
            if self.portfolio_start_value is None:
                self.portfolio_start_value = self.algorithm.Portfolio.TotalPortfolioValue
            
            # Calculate current risk metrics
            risk_metrics = self._calculate_risk_metrics()
            
            # Check for risk alerts
            alerts_triggered = self._check_risk_alerts(risk_metrics)
            
            # Send alerts if any triggered and cooldown has passed
            if alerts_triggered:
                self._send_risk_alerts(alerts_triggered, risk_metrics, current_time)
            
            # Risk reduction: Exit highest margin position if utilization > 95%
            if self.risk_reduction_enabled:
                self._check_risk_reduction(risk_metrics, current_time)
            
            # Smart logging: Only log hourly or when margin utilization > 90%
            self._smart_logging(risk_metrics, current_time)
                
        except Exception as e:
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Intraday risk check error: {e}")
    
    def _calculate_risk_metrics(self):
        """Calculate current risk metrics"""
        portfolio_value = self.algorithm.Portfolio.TotalPortfolioValue
        margin_used = self.algorithm.Portfolio.TotalMarginUsed
        margin_remaining = self.algorithm.Portfolio.MarginRemaining
        
        # Calculate margin utilization percentage
        margin_utilization_pct = (margin_used / portfolio_value) if portfolio_value > 0 else 0
        
        # Calculate portfolio loss from start of day
        portfolio_loss_pct = ((self.portfolio_start_value - portfolio_value) / self.portfolio_start_value) if self.portfolio_start_value > 0 else 0
        
        # Calculate margin call buffer (how much loss before margin call)
        margin_call_buffer_pct = (margin_remaining / portfolio_value) if portfolio_value > 0 else 0
        
        return {
            'portfolio_value': portfolio_value,
            'margin_used': margin_used,
            'margin_remaining': margin_remaining,
            'margin_utilization_pct': margin_utilization_pct,
            'portfolio_loss_pct': portfolio_loss_pct,
            'margin_call_buffer_pct': margin_call_buffer_pct
        }
    
    def _check_risk_alerts(self, risk_metrics):
        """Check for risk alert conditions"""
        alerts_triggered = []
        
        # 1. Margin utilization alert
        if risk_metrics['margin_utilization_pct'] >= self.margin_call_threshold:
            alerts_triggered.append(f"MARGIN CALL RISK: {risk_metrics['margin_utilization_pct']:.1%} utilization "
                                   f"(threshold: {self.margin_call_threshold:.1%})")
        
        # 2. Portfolio loss alert
        if risk_metrics['portfolio_loss_pct'] >= self.portfolio_loss_threshold:
            alerts_triggered.append(f"PORTFOLIO LOSS: {risk_metrics['portfolio_loss_pct']:.1%} loss "
                                   f"(threshold: {self.portfolio_loss_threshold:.1%})")
        
        # 3. Emergency exit threshold
        if risk_metrics['portfolio_loss_pct'] >= self.emergency_exit_threshold:
            alerts_triggered.append(f"EMERGENCY EXIT: {risk_metrics['portfolio_loss_pct']:.1%} loss "
                                   f"(threshold: {self.emergency_exit_threshold:.1%})")
            # Trigger emergency exit
            self._trigger_emergency_exit()
        
        return alerts_triggered
    
    def _send_risk_alerts(self, alerts_triggered, risk_metrics, current_time):
        """Send risk alerts with cooldown protection"""
        current_time_str = current_time.strftime("%H:%M:%S")
        
        # Check cooldown
        can_send_alert = True
        if self.last_risk_alert_time:
            time_since_alert = (current_time - self.last_risk_alert_time).total_seconds() / 60
            can_send_alert = time_since_alert >= self.alert_cooldown_minutes
        
        if can_send_alert:
            self.algorithm.Log(f"INTRADAY RISK ALERT [{current_time_str}]:")
            for alert in alerts_triggered:
                self.algorithm.Log(f"   - {alert}")
            
            self.algorithm.Log(f"   RISK METRICS:")
            self.algorithm.Log(f"      - Portfolio: ${risk_metrics['portfolio_value']:,.0f} "
                             f"(Loss: {risk_metrics['portfolio_loss_pct']:.1%})")
            self.algorithm.Log(f"      - Margin Used: ${risk_metrics['margin_used']:,.0f} "
                             f"({risk_metrics['margin_utilization_pct']:.1%})")
            self.algorithm.Log(f"      - Margin Remaining: ${risk_metrics['margin_remaining']:,.0f} "
                             f"({risk_metrics['margin_call_buffer_pct']:.1%})")
            self.algorithm.Log(f"      - Margin Call Buffer: {risk_metrics['margin_call_buffer_pct']:.1%} loss tolerance")
            
            self.last_risk_alert_time = current_time
    
    def _smart_logging(self, risk_metrics, current_time):
        """
        Smart logging strategy:
        - Log once per hour for routine monitoring
        - Log immediately when margin utilization > 90%
        - Log immediately when portfolio loss > 15%
        """
        should_log = False
        log_reason = ""
        
        # Check if we should log based on time (hourly)
        if self.last_hourly_log_time is None:
            should_log = True
        else:
            time_since_hourly = (current_time - self.last_hourly_log_time).total_seconds() / 3600
            if time_since_hourly >= 1.0:  # 1 hour has passed
                should_log = True
        
        # Check if we should log based on risk thresholds
        if risk_metrics['margin_utilization_pct'] >= 0.90:  # 90% margin utilization
            should_log = True
        
        if risk_metrics['portfolio_loss_pct'] >= 0.15:  # 15% portfolio loss
            should_log = True
        
        # Log if conditions are met
        if should_log:
            current_time_str = current_time.strftime("%H:%M:%S")
            self.algorithm.Log(f"RISK [{current_time_str}]: ${risk_metrics['portfolio_value']:,.0f} "
                             f"(-{risk_metrics['portfolio_loss_pct']:.1%}) | "
                             f"Margin: {risk_metrics['margin_utilization_pct']:.1%} "
                             f"(${risk_metrics['margin_used']:,.0f}/${risk_metrics['margin_remaining']:,.0f})")
            
            # Update hourly log time
            self.last_hourly_log_time = current_time
    
    def _check_risk_reduction(self, risk_metrics, current_time):
        """
        Check if risk reduction is needed and execute if necessary.
        Partially exits the highest margin position to reduce utilization to target level.
        """
        try:
            # Check if margin utilization exceeds threshold
            if risk_metrics['margin_utilization_pct'] < self.risk_reduction_threshold:
                return  # No action needed
            
            # Check cooldown
            if self.last_risk_reduction_time:
                time_since_reduction = (current_time - self.last_risk_reduction_time).total_seconds() / 60
                if time_since_reduction < self.risk_reduction_cooldown_minutes:
                    return  # Still in cooldown
            
            # Skip risk reduction during execution phases to avoid conflicts
            # Execution phases: P0 (15:45), P1 (15:50), P2 (15:55)
            # Stop risk reduction at 15:40 to avoid interfering with execution
            current_time_only = current_time.time()
            if (current_time_only.hour == 15 and current_time_only.minute >= 40) or \
               (current_time_only.hour == 16 and current_time_only.minute == 0):
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"RISK REDUCTION SKIPPED: Execution phases in progress (Time={current_time.strftime('%H:%M:%S')})")
                return  # Skip during execution phases
            
            # Additional check: If algorithm has phase detection, use it
            if hasattr(self.algorithm, '_get_current_execution_phase'):
                try:
                    phase_0_allowed, phase_1_allowed, phase_2_allowed = self.algorithm._get_current_execution_phase()
                    if phase_0_allowed or phase_1_allowed or phase_2_allowed:
                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"RISK REDUCTION SKIPPED: Execution phase active (P0={phase_0_allowed}, P1={phase_1_allowed}, P2={phase_2_allowed})")
                        return  # Skip during any execution phase
                except Exception:
                    pass  # Fall back to time-based check
            
            # Find the highest margin position
            highest_margin_position = self._find_highest_margin_position()
            if not highest_margin_position:
                return  # No positions to exit
            
            # Calculate how much margin we need to free up
            current_margin_used = risk_metrics['margin_used']
            portfolio_value = risk_metrics['portfolio_value']
            target_margin_used = portfolio_value * self.risk_reduction_target
            margin_to_free = current_margin_used - target_margin_used
            
            # Calculate total margin freed (option + hedge)
            option_margin = highest_margin_position['estimated_margin']
            delta = highest_margin_position['delta']
            quantity = abs(highest_margin_position['quantity'])
            
            # Estimate hedge margin freed (hedge uses ~50% margin of underlying value)
            hedge_shares = int(quantity * abs(delta) * 100)
            und_price = self.algorithm.Securities[self.algorithm.underlying_symbol].Price
            hedge_margin = hedge_shares * und_price * 0.50  # 50% margin requirement for stock
            
            total_margin_freed_per_contract = (option_margin / quantity) + (hedge_margin / quantity)
            
            # Check if this position has enough margin to make a difference
            if total_margin_freed_per_contract * quantity < margin_to_free * 0.5:  # At least 50% of needed reduction
                return  # Position too small to make meaningful difference
            
            # Calculate partial reduction needed (considering both option and hedge margin)
            reduction_ratio = min(1.0, margin_to_free / (total_margin_freed_per_contract * quantity))
            
            # Execute partial risk reduction
            self._execute_partial_risk_reduction(highest_margin_position, reduction_ratio, current_time)
            
        except Exception as e:
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Risk reduction check error: {e}")
    
    def _find_highest_margin_position(self):
        """
        Find the option position with the highest margin usage.
        Returns position info including symbol, quantity, and estimated margin.
        """
        try:
            highest_margin_position = None
            highest_margin = 0
            
            for pos_id, position in self.algorithm.positions.items():
                # Skip hedge positions
                if position.get('is_hedge', False):
                    continue
                
                # Skip zero quantity positions
                if abs(position.get('quantity', 0)) == 0:
                    continue
                
                # Calculate estimated margin for this position
                symbol = position['symbol']
                quantity = abs(position['quantity'])
                strike = position.get('strike')
                
                if strike is None:
                    continue
                
                # Use the same margin calculation as the risk manager
                und_px = self.algorithm.Securities[self.algorithm.underlying_symbol].Price
                otm = max(0.0, und_px - strike)  # Out-of-the-money amount
                
                # Reg-T style margin estimation
                estimate1 = 0.20 * und_px * 100 - otm * 100  # 20% underlying - OTM
                estimate2 = 0.10 * und_px * 100              # 10% underlying
                pct_floor = 0.10 * strike * 100              # 10% strike floor
                
                estimated_margin_per_contract = max(estimate1, estimate2, pct_floor)
                estimated_margin_per_contract = max(500, estimated_margin_per_contract)  # Small hard floor
                
                total_estimated_margin = estimated_margin_per_contract * quantity
                
                if total_estimated_margin > highest_margin:
                    highest_margin = total_estimated_margin
                    highest_margin_position = {
                        'pos_id': pos_id,
                        'symbol': symbol,
                        'quantity': position['quantity'],
                        'strike': strike,
                        'estimated_margin': total_estimated_margin,
                        'delta': self._get_position_delta(symbol)
                    }
            
            return highest_margin_position
            
        except Exception as e:
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Error finding highest margin position: {e}")
            return None
    
    def _get_position_delta(self, symbol):
        """Get current delta for a position symbol"""
        try:
            if hasattr(self.algorithm, 'greeks_provider') and self.algorithm.greeks_provider:
                delta, _ = self.algorithm.greeks_provider.get_delta(symbol, None, None, None)
                return float(delta) if delta is not None else -0.25
            else:
                # Simple approximation fallback
                return -0.25
        except Exception:
            return -0.25
    
    def _execute_partial_risk_reduction(self, position_info, reduction_ratio, current_time):
        """
        Execute partial risk reduction by closing a portion of the highest margin position
        and undoing its associated hedge proportionally.
        """
        try:
            pos_id = position_info['pos_id']
            symbol = position_info['symbol']
            quantity = position_info['quantity']
            delta = position_info['delta']
            estimated_margin = position_info['estimated_margin']
            
            # Calculate partial quantities
            partial_quantity = int(abs(quantity) * reduction_ratio)
            if partial_quantity == 0:
                return  # No reduction needed
            
            # Determine order direction based on position type
            if quantity > 0:  # Long position - sell to close
                order_quantity = -partial_quantity
            else:  # Short position - buy to close
                order_quantity = partial_quantity
            
            current_time_str = current_time.strftime("%H:%M:%S")
            self.algorithm.Log(f"RISK REDUCTION [{current_time_str}] - Partial position reduction")
            # Calculate the new quantity correctly: for short positions, order_quantity is positive (buy to close)
            new_quantity = quantity + order_quantity
            self.algorithm.Log(f"   - Position: {pos_id} | {symbol} | Qty: {quantity} -> {new_quantity}")
            self.algorithm.Log(f"   - Reduction: {partial_quantity} contracts ({reduction_ratio:.1%} of position)")
            self.algorithm.Log(f"   - Option Margin: ${estimated_margin:,.0f} | Delta: {delta:.3f}")
            
            # Calculate and log total margin freed (option + hedge)
            hedge_shares = int(partial_quantity * abs(delta) * 100)
            und_price = self.algorithm.Securities[self.algorithm.underlying_symbol].Price
            hedge_margin_freed = hedge_shares * und_price * 0.50
            option_margin_freed = (estimated_margin / abs(quantity)) * partial_quantity
            total_margin_freed = option_margin_freed + hedge_margin_freed
            self.algorithm.Log(f"   - Total Margin Freed: ${total_margin_freed:,.0f} (Option: ${option_margin_freed:,.0f} + Hedge: ${hedge_margin_freed:,.0f})")
            
            # Close partial option position using LIMIT order with proper pricing
            # Get current bid/ask quotes
            sec = self.algorithm.Securities[symbol]
            bid = float(getattr(sec, "BidPrice", 0) or 0)
            ask = float(getattr(sec, "AskPrice", 0) or 0)
            
            if bid > 0 and ask > 0:
                # Calculate limit price using same logic as fill model
                haircut_fraction = self.algorithm.mid_haircut_fraction
                mid = (bid + ask) / 2
                spread = ask - bid
                
                if order_quantity > 0:  # Buying back (closing short position)
                    limit_price = mid + haircut_fraction * spread
                    limit_price = min(max(limit_price, bid), ask)  # Clamp to book
                else:  # Selling (closing long position)
                    limit_price = mid - haircut_fraction * spread
                    limit_price = min(max(limit_price, bid), ask)  # Clamp to book
                
                self.algorithm.LimitOrder(symbol, order_quantity, round(limit_price, 2), tag=f"MARGIN_{pos_id}")
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"   - MARGIN limit order: {symbol} {order_quantity:+d} @ ${limit_price:.2f} (bid={bid}, ask={ask})")
            else:
                # Fallback to market order only if no quotes available
                self.algorithm.MarketOrder(symbol, order_quantity, tag=f"MARGIN_{pos_id}")
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"   - MARGIN fallback market order: {symbol} {order_quantity:+d} (no quotes)")
            
            # Undo the associated hedge proportionally
            hedge_quantity = int(order_quantity * delta * 100)  # Convert to shares
            if hedge_quantity != 0:
                hedge_symbol = self.algorithm.underlying_symbol
                self.algorithm.MarketOrder(hedge_symbol, -hedge_quantity, tag=f"MARGIN_HEDGE_{pos_id}")
                self.algorithm.Log(f"   - Hedge Adjustment: {hedge_symbol} | Qty: {-hedge_quantity} | Delta: {delta:.3f}")
            
            # Update cooldown
            self.last_risk_reduction_time = current_time
            
            self.algorithm.Log(f"   - Partial risk reduction executed successfully")
            
        except Exception as e:
            self.algorithm.Log(f"Partial risk reduction execution error: {e}")
    
    def _execute_risk_reduction(self, position_info, current_time):
        """
        Execute full risk reduction by closing the entire highest margin position
        and undoing its associated hedge. (Legacy method for emergency exits)
        """
        try:
            pos_id = position_info['pos_id']
            symbol = position_info['symbol']
            quantity = position_info['quantity']
            delta = position_info['delta']
            estimated_margin = position_info['estimated_margin']
            
            current_time_str = current_time.strftime("%H:%M:%S")
            self.algorithm.Log(f"RISK REDUCTION [{current_time_str}] - Closing highest margin position")
            self.algorithm.Log(f"   - Position: {pos_id} | {symbol} | Qty: {quantity}")
            self.algorithm.Log(f"   - Estimated Margin: ${estimated_margin:,.0f} | Delta: {delta:.3f}")
            
            # Close the option position using LIMIT order with proper pricing
            order_quantity = -quantity if quantity > 0 else abs(quantity)
            
            # Get current bid/ask quotes
            sec = self.algorithm.Securities[symbol]
            bid = float(getattr(sec, "BidPrice", 0) or 0)
            ask = float(getattr(sec, "AskPrice", 0) or 0)
            
            if bid > 0 and ask > 0:
                # Calculate limit price using same logic as fill model
                haircut_fraction = self.algorithm.mid_haircut_fraction
                mid = (bid + ask) / 2
                spread = ask - bid
                
                if order_quantity > 0:  # Buying back (closing short position)
                    limit_price = mid + haircut_fraction * spread
                    limit_price = min(max(limit_price, bid), ask)  # Clamp to book
                else:  # Selling (closing long position)
                    limit_price = mid - haircut_fraction * spread
                    limit_price = min(max(limit_price, bid), ask)  # Clamp to book
                
                self.algorithm.LimitOrder(symbol, order_quantity, round(limit_price, 2), tag=f"MARGIN_{pos_id}")
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"   - MARGIN limit order: {symbol} {order_quantity:+d} @ ${limit_price:.2f} (bid={bid}, ask={ask})")
            else:
                # Fallback to market order only if no quotes available
                if quantity > 0:  # Long position - sell to close
                    self.algorithm.MarketOrder(symbol, -quantity, tag=f"MARGIN_{pos_id}")
                else:  # Short position - buy to close
                    self.algorithm.MarketOrder(symbol, abs(quantity), tag=f"MARGIN_{pos_id}")
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"   - MARGIN fallback market order: {symbol} {order_quantity:+d} (no quotes)")
            
            # Undo the associated hedge using current delta
            hedge_quantity = int(quantity * delta * 100)  # Convert to shares
            if hedge_quantity != 0:
                hedge_symbol = self.algorithm.underlying_symbol
                self.algorithm.MarketOrder(hedge_symbol, -hedge_quantity, tag=f"MARGIN_HEDGE_{pos_id}")
                self.algorithm.Log(f"   - Hedge Adjustment: {hedge_symbol} | Qty: {-hedge_quantity} | Delta: {delta:.3f}")
            
            # Update cooldown
            self.last_risk_reduction_time = current_time
            
            self.algorithm.Log(f"   - Risk reduction executed successfully")
            
        except Exception as e:
            self.algorithm.Log(f"Risk reduction execution error: {e}")
    
    def _trigger_emergency_exit(self):
        """
        Trigger emergency exit when portfolio loss exceeds emergency threshold.
        This is a safety mechanism to prevent margin calls.
        """
        try:
            self.algorithm.Log("EMERGENCY EXIT TRIGGERED - Closing all positions to prevent margin call")
            
            # Close all option positions
            positions_to_close = []
            for pos_id, position in self.algorithm.positions.items():
                if not position.get('is_hedge', False) and abs(position.get('quantity', 0)) > 0:
                    positions_to_close.append((pos_id, position))
            
            if positions_to_close:
                self.algorithm.Log(f"EMERGENCY EXIT: Closing {len(positions_to_close)} positions")
                
                for pos_id, position in positions_to_close:
                    symbol = position['symbol']
                    quantity = position['quantity']
                    
                    # Close position using LIMIT order with proper pricing
                    order_quantity = -quantity if quantity > 0 else abs(quantity)
                    
                    # Get current bid/ask quotes
                    sec = self.algorithm.Securities[symbol]
                    bid = float(getattr(sec, "BidPrice", 0) or 0)
                    ask = float(getattr(sec, "AskPrice", 0) or 0)
                    
                    if bid > 0 and ask > 0:
                        # Calculate limit price using same logic as fill model
                        haircut_fraction = self.algorithm.mid_haircut_fraction
                        mid = (bid + ask) / 2
                        spread = ask - bid
                        
                        if order_quantity > 0:  # Buying back (closing short position)
                            limit_price = mid + haircut_fraction * spread
                            limit_price = min(max(limit_price, bid), ask)  # Clamp to book
                        else:  # Selling (closing long position)
                            limit_price = mid - haircut_fraction * spread
                            limit_price = min(max(limit_price, bid), ask)  # Clamp to book
                        
                        self.algorithm.LimitOrder(symbol, order_quantity, round(limit_price, 2), tag=f"EMERGENCY_EXIT_{pos_id}")
                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"   - EMERGENCY limit order: {symbol} {order_quantity:+d} @ ${limit_price:.2f} (bid={bid}, ask={ask})")
                    else:
                        # Fallback to market order only if no quotes available
                        if quantity > 0:  # Long position - sell to close
                            self.algorithm.MarketOrder(symbol, -quantity, tag=f"EMERGENCY_EXIT_{pos_id}")
                        else:  # Short position - buy to close
                            self.algorithm.MarketOrder(symbol, abs(quantity), tag=f"EMERGENCY_EXIT_{pos_id}")
                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"   - EMERGENCY fallback market order: {symbol} {order_quantity:+d} (no quotes)")
                    
                    self.algorithm.Log(f"EMERGENCY EXIT: {pos_id} | {symbol} | Qty: {quantity}")
            else:
                self.algorithm.Log("EMERGENCY EXIT: No positions to close")
                
        except Exception as e:
            self.algorithm.Log(f"Emergency exit error: {e}")
    
    def get_risk_summary(self):
        """Get current risk summary for reporting"""
        if not self.enabled:
            return "Intraday risk monitoring disabled"
        
        try:
            risk_metrics = self._calculate_risk_metrics()
            return {
                'margin_utilization_pct': risk_metrics['margin_utilization_pct'],
                'portfolio_loss_pct': risk_metrics['portfolio_loss_pct'],
                'margin_call_buffer_pct': risk_metrics['margin_call_buffer_pct'],
                'last_check_time': self.last_risk_check_time,
                'portfolio_start_value': self.portfolio_start_value
            }
        except Exception as e:
            return f"Risk summary error: {e}"
    
    def reset_daily(self):
        """Reset daily tracking values"""
        self.portfolio_start_value = None
        self.risk_alerts_sent.clear()
        if self.enabled:
            self.algorithm.Log("Intraday Risk Monitor: Daily reset completed")
