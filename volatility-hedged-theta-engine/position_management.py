"""
Position Management Module for Theta Engine

This module handles position sizing, entry logic, risk management, and adaptive constraints.
Includes margin-based sizing and position tracking.
"""

from AlgorithmImports import *


class PositionManager:
    """Manages position sizing, entry, and risk management"""

    def __init__(self, algorithm):
        self.algorithm = algorithm

    def calculate_position_size(self, option_price, strike):
        """Calculate position size using realistic Reg-T margin estimation"""
        try:
            portfolio_value = self.algorithm.Portfolio.TotalPortfolioValue
            
            # Target margin utilization (80% of portfolio)
            target_margin = portfolio_value * self.algorithm.target_margin_use
            
            # Get current buying power and margin used
            current_margin_used = self.algorithm.Portfolio.TotalMarginUsed
            free_buying_power = self.algorithm.Portfolio.MarginRemaining
            
            # Available margin for new positions (up to our 80% target)
            available_margin = target_margin - current_margin_used
            available_margin = max(0, available_margin)
            
            # Also respect QuantConnect's available buying power
            available_margin = min(available_margin, free_buying_power)
            
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Margin Info: Portfolio=${portfolio_value:,.0f}, "
                                   f"Target Margin (80%)=${target_margin:,.0f}, "
                                   f"Current Used=${current_margin_used:,.0f}, "
                                   f"QC Free Margin=${free_buying_power:,.0f}, "
                                   f"Available for new=${available_margin:,.0f}")

            # Calculate how much margin to use per position
            # Cap per-trade allocation to prevent huge position sizes that spike margin usage
            max_margin_per_trade = portfolio_value * self.algorithm.max_margin_per_trade_pct

            # Use the smaller of: available margin or our per-trade cap
            margin_per_position = min(available_margin, max_margin_per_trade)

            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Margin allocation: Available=${available_margin:,.0f}, "
                                   f"Per-trade cap ({self.algorithm.max_margin_per_trade_pct:.1%} NAV)=${max_margin_per_trade:,.0f}, "
                                   f"Using=${margin_per_position:,.0f}")
            
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
            contracts = max(1, int(margin_per_position / estimated_margin_per_contract))
            
            # Apply the portfolio-relative scaling from config
            max_contracts_for_portfolio = max(1, int((portfolio_value / 100000) * self.algorithm.max_contracts_per_100k))
            contracts = min(contracts, max_contracts_for_portfolio)
            
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Position sizing: Margin per position=${margin_per_position:,.0f}, "
                                   f"Reg-T margin per contract=${estimated_margin_per_contract:,.0f} "
                                   f"(Strike=${strike:.2f}, Underlying=${und_px:.2f}, OTM=${otm:.2f}), "
                                   f"Calculated contracts={contracts}")
            
            return max(1, contracts)

        except Exception as e:
            self.algorithm.Debug(f"Error calculating position size: {e}")
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

    def find_tradable_options(self, option_chain):
        """Find tradable options based on criteria"""
        candidates = []

        try:
            underlying_price = self.algorithm.Securities[self.algorithm.underlying_symbol].Price
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Finding tradable options. Underlying price: ${underlying_price:.2f}")
                min_premium_required = underlying_price * self.algorithm.min_premium_pct_of_spot
                self.algorithm.Debug(f"Filter criteria: Moneyness [{self.algorithm.min_moneyness:.2f}-{self.algorithm.max_moneyness:.2f}], "
                                   f"DTE [{self.algorithm.min_target_dte}-{self.algorithm.max_target_dte}], "
                                   f"Min premium: ${min_premium_required:.2f} ({self.algorithm.min_premium_pct_of_spot:.1%} of ${underlying_price:.2f})")

            # QuantConnect OptionChain iteration - iterate through contracts directly
            total_contracts = 0
            puts_found = 0
            moneyness_filtered = 0
            dte_filtered = 0
            premium_filtered = 0
            spread_filtered = 0
            
            for contract in option_chain:
                total_contracts += 1
                symbol = contract.Symbol

                # Basic filters
                if contract.Right != OptionRight.Put:
                    continue
                puts_found += 1

                moneyness = contract.Strike / underlying_price
                if not (self.algorithm.min_moneyness <= moneyness <= self.algorithm.max_moneyness):
                    moneyness_filtered += 1
                    continue

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
                    self.algorithm.Debug(f"Error calculating DTE for {symbol}: {e}")
                    continue
                if not (self.algorithm.min_target_dte <= dte <= self.algorithm.max_target_dte):
                    dte_filtered += 1
                    continue

                # Premium filter
                bid_price = contract.BidPrice
                ask_price = contract.AskPrice
                if bid_price <= 0 or ask_price <= 0:
                    premium_filtered += 1
                    continue

                premium = (bid_price + ask_price) / 2
                # Use percentage-based premium filter relative to underlying price
                min_premium_required = underlying_price * self.algorithm.min_premium_pct_of_spot
                if premium < min_premium_required:
                    premium_filtered += 1
                    continue

                # Liquidity filter
                spread_pct = abs(ask_price - bid_price) / ((bid_price + ask_price) / 2)
                if spread_pct > 0.10:  # 10% max spread
                    spread_filtered += 1
                    continue

                # Greeks validation (if available)
                delta = None
                if hasattr(contract, 'Greeks') and contract.Greeks is not None:
                    delta = contract.Greeks.Delta

                # Check tradability
                is_tradable = self._is_option_tradable(contract, delta)

                if is_tradable:
                    candidates.append({
                        'symbol': symbol,
                        'contract': contract,
                        'premium': premium,
                        'bid_price': bid_price,
                        'ask_price': ask_price,
                        'delta': delta,
                        'dte': dte,
                        'moneyness': moneyness,
                        'spread_pct': spread_pct
                    })

            # Debug filtering results
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Option filtering: Total={total_contracts}, Puts={puts_found}, "
                                   f"Moneyness filtered={moneyness_filtered}, DTE filtered={dte_filtered}, "
                                   f"Premium filtered={premium_filtered}, Spread filtered={spread_filtered}")

        except Exception as e:
            self.algorithm.Debug(f"Error finding tradable options: {e}")

        if self.algorithm.debug_mode:
            self.algorithm.Debug(f"Found {len(candidates)} tradable option candidates")
        
        # If no candidates found, track for aggressive adaptation
        if len(candidates) == 0:
            if not hasattr(self.algorithm, '_no_candidates_streak'):
                self.algorithm._no_candidates_streak = 0
            self.algorithm._no_candidates_streak += 1
            
            # After 10 consecutive days with no candidates, aggressively relax filters
            if self.algorithm._no_candidates_streak >= 10:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"AGGRESSIVE ADAPTATION: {self.algorithm._no_candidates_streak} days with no candidates")
                # More aggressive relaxation
                self.algorithm.min_premium_pct_of_spot = max(0.0005, self.algorithm.min_premium_pct_of_spot * 0.5)
                self.algorithm.min_moneyness = max(0.2, self.algorithm.min_moneyness - 0.1)
                self.algorithm.min_target_dte = max(5, self.algorithm.min_target_dte - 5)
                self.algorithm._no_candidates_streak = 0  # Reset
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"Aggressively relaxed filters: Premium {self.algorithm.min_premium_pct_of_spot:.1%}, "
                                       f"Moneyness {self.algorithm.min_moneyness:.2f}, DTE {self.algorithm.min_target_dte}")
        else:
            # Reset streak when we find candidates
            self.algorithm._no_candidates_streak = 0
        
        return candidates

    def _is_option_tradable(self, contract, delta=None):
        """Check if option is tradable based on various criteria"""
        try:
            # Must have valid bid/ask
            if contract.BidPrice <= 0 or contract.AskPrice <= 0:
                return False

            # Must be in securities collection
            if contract.Symbol not in self.algorithm.Securities:
                # For EOD mode, allow if we have bid/ask from chain
                if not self.algorithm.intraday_hedging:
                    return contract.BidPrice > 0 and contract.AskPrice > 0
                return False

            # Greeks validation for intraday mode
            if self.algorithm.intraday_hedging:
                security = self.algorithm.Securities[contract.Symbol]
                if hasattr(security, 'Greeks') and security.Greeks is not None:
                    actual_delta = security.Greeks.Delta
                    # Prefer delta between 0.15 and 0.35 for short puts
                    if actual_delta is not None and not (0.15 <= actual_delta <= 0.35):
                        return False
                else:
                    return False

            return True

        except Exception as e:
            self.algorithm.Debug(f"Error checking option tradability: {e}")
            return False

    def select_best_option(self, candidates):
        """Select the best option from candidates using premium-per-margin ranking"""
        if not candidates:
            return None

        try:
            best_option = None
            best_score = float('-inf')

            for candidate in candidates:
                # Calculate premium-per-margin score using STRIKE-based margin
                premium = candidate['premium']
                strike = candidate['contract'].Strike
                margin_req = strike * 100 * self.algorithm.estimated_margin_pct

                if margin_req > 0:
                    ppm_score = premium / margin_req
                else:
                    ppm_score = 0

                # Adjust score based on delta preference
                if candidate['delta'] is not None:
                    delta = candidate['delta']
                    # Prefer deltas around 0.25 for short puts (good theta, manageable risk)
                    delta_score = 1.0 - abs(delta - 0.25) / 0.25
                    ppm_score *= (0.7 + 0.3 * delta_score)

                # Prefer shorter DTE for faster theta collection
                dte_score = 1.0 - (candidate['dte'] - self.algorithm.min_target_dte) / (self.algorithm.max_target_dte - self.algorithm.min_target_dte)
                ppm_score *= (0.8 + 0.2 * dte_score)

                if ppm_score > best_score:
                    best_score = ppm_score
                    best_option = candidate

            return best_option

        except Exception as e:
            self.algorithm.Debug(f"Error selecting best option: {e}")
            return candidates[0] if candidates else None

    def try_enter_position(self, option_data):
        """Attempt to enter a new position"""
        try:
            symbol = option_data['symbol']
            contract = option_data['contract']
            premium = option_data['premium']

            # Check MIN_BUYING_POWER gate before entries
            if self.algorithm.Portfolio.MarginRemaining < self.algorithm.min_buying_power:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug("Skip entry: below MIN_BUYING_POWER cushion")
                return False

            # Prevent duplicate entries on same symbol while an active position exists
            for _pos_id, _pos in self.algorithm.positions.items():
                if _pos.get('symbol') == symbol and abs(_pos.get('quantity', 0)) > 0:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"Already have position in {symbol}, skipping duplicate entry")
                    return False

            # Pre-validate that the security is tradable before calculating position size
            if symbol not in self.algorithm.Securities:
                # For EOD mode, we need to add the contract first
                if not self.algorithm.intraday_hedging:
                    try:
                        # Add contract to make it tradable
                        self.algorithm.AddOptionContract(contract, Resolution.Daily)

                        # During EOD phase, use the EOD fill model for immediate fills
                        if getattr(self.algorithm, 'eod_phase', False):
                            if hasattr(self.algorithm, 'eod_fill_model'):
                                self.algorithm.Securities[symbol].SetFillModel(self.algorithm.eod_fill_model)
                        else:
                            # Use regular fill model
                            if hasattr(self.algorithm, 'close_fill_model'):
                                self.algorithm.Securities[symbol].SetFillModel(self.algorithm.close_fill_model)

                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"Added contract {symbol} for trading")

                    except Exception as e:
                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"Failed to add contract {symbol}: {e}")
                        return False
                else:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"Intraday mode: Contract {symbol} not available")
                    return False

            # Calculate position size using realistic Reg-T margin estimation
            contracts = self.calculate_position_size(premium, contract.Strike)

            if contracts <= 0:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"Insufficient margin for {symbol}")
                return False

            # Check position limits (count only active positions)
            active_positions = sum(1 for p in self.algorithm.positions.values() if abs(p.get('quantity', 0)) > 0)
            if active_positions >= self.algorithm.max_positions:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"Maximum active positions ({self.algorithm.max_positions}) reached")
                return False

            # Place the order
            success = self._place_entry_order(symbol, contract, contracts, premium)

            if success:
                # Track the position - but quantity will be updated when order actually fills
                # If a pending zero-qty tracker already exists for the symbol, reuse it
                existing_id = None
                for pid, p in self.algorithm.positions.items():
                    if p.get('symbol') == symbol and abs(p.get('quantity', 0)) == 0:
                        existing_id = pid
                        break

                if existing_id is None:
                    pos_id = f"{symbol}_{self.algorithm.Time.strftime('%Y%m%d_%H%M%S')}"
                else:
                    pos_id = existing_id

                self.algorithm.positions[pos_id] = {
                    'symbol': symbol,
                    'quantity': self.algorithm.positions.get(pos_id, {}).get('quantity', 0),  # preserve if existed
                    'entry_price': premium,
                    'credit_received': self.algorithm.positions.get(pos_id, {}).get('credit_received', 0),
                    'expiration': contract.Expiry,
                    'strike': contract.Strike,
                    'timestamp': self.algorithm.Time,
                    'target_contracts': -contracts  # Track what we intended
                }

                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"POSITION ORDER SUBMITTED: {pos_id} | "
                                       f"Target: {contracts} contracts | "
                                       f"Premium: ${premium:.2f}")

                return True

            return False

        except Exception as e:
            self.algorithm.Debug(f"Error entering position: {e}")
            return False

    def _place_entry_order(self, symbol, contract, contracts, premium):
        """Place the entry order based on execution mode"""
        try:
            quantity = -contracts  # Negative for short position

            if not self.algorithm.intraday_hedging:
                # EOD: use limit order at BBO mid
                limit_price = round((contract.BidPrice + contract.AskPrice) / 2, 2)
                ticket = self.algorithm.LimitOrder(symbol, quantity, limit_price)
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"EOD ENTRY: {symbol} LIMIT {quantity} @ ${limit_price:.2f}")
            else:
                # Intraday: market order
                ticket = self.algorithm.MarketOrder(symbol, quantity)

            return ticket.Status in (OrderStatus.Submitted, OrderStatus.Filled)

        except Exception as e:
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Error placing entry order: {e}")
            return False

    def update_adaptive_constraints(self):
        """Update adaptive constraints based on recent performance"""
        try:
            # Check consecutive failures
            recent_attempts = getattr(self.algorithm, '_recent_entry_attempts', [])
            recent_failures = [attempt for attempt in recent_attempts[-10:] if not attempt]

            if len(recent_failures) >= 5:
                # Relax constraints
                old_min_premium_pct = self.algorithm.min_premium_pct_of_spot
                old_min_moneyness = self.algorithm.min_moneyness
                old_min_dte = self.algorithm.min_target_dte

                # Reduce minimum premium percentage requirement
                self.algorithm.min_premium_pct_of_spot = max(0.001, self.algorithm.min_premium_pct_of_spot * 0.8)
                # Expand moneyness range (allow deeper OTM)
                self.algorithm.min_moneyness = max(0.3, self.algorithm.min_moneyness - 0.05)
                # Reduce minimum DTE to find more candidates
                self.algorithm.min_target_dte = max(7, self.algorithm.min_target_dte - 2)

                if old_min_premium_pct != self.algorithm.min_premium_pct_of_spot:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"Adaptive: Reduced min premium {old_min_premium_pct:.1%} → {self.algorithm.min_premium_pct_of_spot:.1%} of spot")

                if old_min_moneyness != self.algorithm.min_moneyness:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"Adaptive: Expanded moneyness {old_min_moneyness:.2f} → {self.algorithm.min_moneyness:.2f}")

                if old_min_dte != self.algorithm.min_target_dte:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug(f"Adaptive: Reduced min DTE {old_min_dte} → {self.algorithm.min_target_dte} days")

                # Reset failure counter
                self.algorithm._recent_entry_attempts = []

        except Exception as e:
            self.algorithm.Debug(f"Error updating adaptive constraints: {e}")

    def track_entry_attempt(self, success):
        """Track entry attempt for adaptive constraints"""
        if not hasattr(self.algorithm, '_recent_entry_attempts'):
            self.algorithm._recent_entry_attempts = []

        self.algorithm._recent_entry_attempts.append(success)

        # Keep only last 10 attempts
        if len(self.algorithm._recent_entry_attempts) > 10:
            self.algorithm._recent_entry_attempts = self.algorithm._recent_entry_attempts[-10:]
