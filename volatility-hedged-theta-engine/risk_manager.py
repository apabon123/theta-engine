"""
Risk Manager Module

Handles position sizing, margin calculations, and risk management.
Extracted from position_management.py to provide clean separation of concerns.
"""

from AlgorithmImports import *


class RiskManager:
    """Manages position sizing and risk calculations"""

    def __init__(self, algorithm):
        self.algorithm = algorithm
        self.exit_rules = None  # Will be set by main.py

    def set_exit_rules_manager(self, exit_rules_manager):
        """Set the exit rules manager for delegation"""
        self.exit_rules = exit_rules_manager

    def calculate_position_size(self, option_price, strike):
        """Calculate position size using realistic Reg-T margin estimation with dynamic scaling"""
        try:
            portfolio_value = self.algorithm.Portfolio.TotalPortfolioValue

            # Target margin utilization (80% of portfolio)
            target_margin = portfolio_value * self.algorithm.target_margin_use

            # Get current buying power and margin used
            current_margin_used = self.algorithm.Portfolio.TotalMarginUsed
            free_buying_power = self.algorithm.Portfolio.MarginRemaining

            # Calculate current margin utilization percentage
            margin_utilization_pct = (current_margin_used / portfolio_value) if portfolio_value > 0 else 0

            # Available margin for new positions (up to our 80% target)
            available_margin = target_margin - current_margin_used
            available_margin = max(0, available_margin)

            # Also respect QuantConnect's available buying power
            available_margin = min(available_margin, free_buying_power)

            # Calculate dynamic scaling factor based on margin utilization
            scaling_factor = self._calculate_dynamic_scaling_factor(margin_utilization_pct)
            
            # Calculate how much margin to use per position with dynamic scaling
            base_max_margin_per_trade = portfolio_value * self.algorithm.max_margin_per_trade_pct
            max_margin_per_trade = base_max_margin_per_trade * scaling_factor

            # Use the smaller of: available margin or our per-trade cap
            margin_per_position = min(available_margin, max_margin_per_trade)

            if self.algorithm.debug_mode:
                margin_used_pct = (current_margin_used / portfolio_value * 100) if portfolio_value > 0 else 0
                self.algorithm.Debug(f"Margin: Portfolio=${portfolio_value:,.0f}, Used={margin_used_pct:.1f}%, "
                                   f"Available=${available_margin:,.0f}, Scaling={scaling_factor:.2f}x, "
                                   f"Per-trade cap=${max_margin_per_trade:,.0f}")
                
                # Concise scaling logging
                if scaling_factor > 1.0:
                    self.algorithm.Debug(f"SCALING: {scaling_factor:.1f}x (margin {margin_utilization_pct:.1%})")
                elif margin_utilization_pct < self.algorithm.low_margin_threshold:
                    self.algorithm.Debug(f"SCALING: Disabled (margin {margin_utilization_pct:.1%})")

            # REALISTIC Reg-T style margin estimation for short puts
            und_px = self.algorithm.Securities[self.algorithm.underlying_symbol].Price
            otm = max(0.0, und_px - strike)  # Out-of-the-money amount

            # Two common Reg-T floors
            estimate1 = 0.20 * und_px * 100 - otm * 100 + option_price * 100  # 20% underlying - OTM + premium
            estimate2 = 0.10 * und_px * 100 + option_price * 100              # 10% underlying + premium
            pct_floor = self.algorithm.estimated_margin_pct * strike * 100     # Config percentage floor

            estimated_margin_per_contract = max(estimate1, estimate2, pct_floor)
            estimated_margin_per_contract = max(500, estimated_margin_per_contract)  # Small hard floor

            # Calculate contracts based on available margin for this position
            # Return 0 if insufficient margin, otherwise the computed integer
            if margin_per_position < estimated_margin_per_contract:
                contracts = 0
            else:
                contracts = int(margin_per_position / estimated_margin_per_contract)

            # Apply the portfolio-relative scaling from config
            max_contracts_for_portfolio = max(1, int((portfolio_value / 100000) * self.algorithm.max_contracts_per_100k))
            contracts = min(contracts, max_contracts_for_portfolio)

            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"SIZING: Strike ${strike:,.0f} → {contracts} contracts (${margin_per_position:,.0f} margin)")

            return contracts

        except Exception as e:
            self.algorithm.Debug(f"Error calculating position size: {e}")
            return 1

    def check_margin_capacity(self):
        """Check if we have capacity for new positions"""
        try:
            portfolio_value = self.algorithm.Portfolio.TotalPortfolioValue
            current_margin_used = self.algorithm.Portfolio.TotalMarginUsed
            free_buying_power = self.algorithm.Portfolio.MarginRemaining

            # Target margin utilization
            target_margin = portfolio_value * self.algorithm.target_margin_use

            # Available margin for new positions
            available_margin = target_margin - current_margin_used
            available_margin = max(0, available_margin)

            # Also respect QuantConnect's available buying power
            available_margin = min(available_margin, free_buying_power)

            # Check minimum buying power requirement
            has_capacity = available_margin >= self.algorithm.min_buying_power

            if self.algorithm.debug_mode:
                margin_used_pct = (current_margin_used / portfolio_value * 100) if portfolio_value > 0 else 0
                self.algorithm.Debug(f"MARGIN ANALYSIS: Portfolio=${portfolio_value:,.0f}, Used={margin_used_pct:.1f}%, "
                                   f"Available=${available_margin:,.0f}, Per-trade limit=${portfolio_value * self.algorithm.max_margin_per_trade_pct:,.0f}")

            return has_capacity, available_margin

        except Exception as e:
            self.algorithm.Debug(f"Error checking margin capacity: {e}")
            return False, 0

    def get_portfolio_risk_metrics(self):
        """Calculate portfolio-level risk metrics including dynamic scaling info"""
        try:
            portfolio_value = self.algorithm.Portfolio.TotalPortfolioValue
            current_margin_used = self.algorithm.Portfolio.TotalMarginUsed
            margin_utilization = (current_margin_used / portfolio_value) if portfolio_value > 0 else 0
            
            # Calculate current dynamic scaling factor
            scaling_factor = self._calculate_dynamic_scaling_factor(margin_utilization)
            
            # Determine if dynamic scaling is active
            is_scaling_active = scaling_factor > 1.0
            scaling_reason = "None"
            if is_scaling_active:
                if margin_utilization <= getattr(self.algorithm, 'scaling_min_threshold', 0.30):
                    scaling_reason = "Full scaling (very low utilization)"
                elif margin_utilization <= getattr(self.algorithm, 'scaling_max_threshold', 0.50):
                    scaling_reason = "Gradual scaling (low utilization)"
                else:
                    scaling_reason = "Binary scaling (below threshold)"

            return {
                'portfolio_value': portfolio_value,
                'margin_used': current_margin_used,
                'margin_utilization_pct': margin_utilization * 100,
                'margin_remaining': self.algorithm.Portfolio.MarginRemaining,
                'target_margin_use': self.algorithm.target_margin_use * 100,
                'max_margin_per_trade_pct': self.algorithm.max_margin_per_trade_pct * 100,
                'dynamic_scaling_enabled': getattr(self.algorithm, 'dynamic_sizing_enabled', True),
                'current_scaling_factor': scaling_factor,
                'is_scaling_active': is_scaling_active,
                'scaling_reason': scaling_reason,
                'low_margin_threshold': getattr(self.algorithm, 'low_margin_threshold', 0.50) * 100
            }
        except Exception as e:
            self.algorithm.Debug(f"Error calculating portfolio risk metrics: {e}")
            return {}

    def manage_exits(self):
        """Delegate exit management to exit rules manager"""
        if self.exit_rules:
            self.exit_rules.check_exit_conditions()
        else:
            self.algorithm.Debug("Exit rules manager not available for risk management")

    def _calculate_dynamic_scaling_factor(self, margin_utilization_pct):
        """
        Calculate dynamic scaling factor based on current margin utilization.
        
        When margin utilization is low (underutilized), increase position sizes
        to improve performance while staying within risk limits.
        
        Args:
            margin_utilization_pct: Current margin utilization as decimal (0.0 to 1.0)
            
        Returns:
            float: Scaling factor to apply to position sizes (1.0 = no scaling, 2.0 = double)
        """
        if not getattr(self.algorithm, 'dynamic_sizing_enabled', True):
            return 1.0
            
        # If margin utilization is above our threshold, no scaling needed
        if margin_utilization_pct >= getattr(self.algorithm, 'low_margin_threshold', 0.50):
            return 1.0
            
        # Check if gradual scaling is enabled
        if getattr(self.algorithm, 'scaling_gradual_enabled', True):
            # Gradual scaling between min and max thresholds
            min_threshold = getattr(self.algorithm, 'scaling_min_threshold', 0.30)
            max_threshold = getattr(self.algorithm, 'scaling_max_threshold', 0.50)
            
            if margin_utilization_pct <= min_threshold:
                # Full scaling when utilization is very low
                scaling_factor = getattr(self.algorithm, 'position_scaling_factor', 2.0)
            elif margin_utilization_pct <= max_threshold:
                # Gradual scaling between thresholds
                max_scaling = getattr(self.algorithm, 'position_scaling_factor', 2.0)
                scale_range = max_threshold - min_threshold
                utilization_in_range = margin_utilization_pct - min_threshold
                scaling_factor = 1.0 + (max_scaling - 1.0) * (1.0 - utilization_in_range / scale_range)
            else:
                # No scaling when above max threshold
                scaling_factor = 1.0
        else:
            # Binary scaling: either full scaling or no scaling
            scaling_factor = getattr(self.algorithm, 'position_scaling_factor', 2.0)
            
        # Cap the scaling factor to prevent excessive position sizes
        max_scaling = getattr(self.algorithm, 'position_scaling_factor', 2.0)
        scaling_factor = min(scaling_factor, max_scaling)
        
        if self.algorithm.debug_mode and scaling_factor > 1.0:
            self.algorithm.Debug(f"Dynamic Scaling: Margin util={margin_utilization_pct:.1%}, "
                               f"Scaling factor={scaling_factor:.2f}x")
                               
        return scaling_factor