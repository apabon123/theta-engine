from AlgorithmImports import *
import numpy as np
from datetime import datetime, timedelta
from config import *

class DeltaHedgedThetaEngine(QCAlgorithm):
    
    def Initialize(self):
        # Test period
        self.SetStartDate(*BACKTEST_START_DATE)
        self.SetEndDate(*BACKTEST_END_DATE)
        self.SetCash(INITIAL_CASH)
        
        # Set QQQ as benchmark for performance comparison
        self.SetBenchmark(BENCHMARK_SYMBOL)
        
        # ALL STRATEGY PARAMETERS - IMPORTED FROM CONFIG
        self.strikes_below = STRIKES_BELOW
        self.strikes_above = STRIKES_ABOVE
        self.min_target_dte = MIN_TARGET_DTE
        self.max_target_dte = MAX_TARGET_DTE
        self.min_moneyness = MIN_MONEYNESS
        self.max_moneyness = MAX_MONEYNESS
        self.min_premium = MIN_PREMIUM
        self.min_buying_power = MIN_BUYING_POWER
        self.min_contracts = MIN_CONTRACTS
        self.max_contracts = MAX_CONTRACTS
        self.min_margin_per_position_pct = MIN_MARGIN_PER_POSITION_PCT
        self.margin_safety_factor = MARGIN_SAFETY_FACTOR
        self.estimated_margin_pct = ESTIMATED_MARGIN_PCT
        self.target_margin_use = TARGET_MARGIN_USE
        self.max_positions = MAX_POSITIONS
        self.margin_buffer = MARGIN_BUFFER
        self.target_portfolio_delta = TARGET_PORTFOLIO_DELTA
        self.delta_tolerance = DELTA_TOLERANCE
        self.hedge_ratio = HEDGE_RATIO
        self.quick_profit_target = QUICK_PROFIT_TARGET
        self.normal_profit_target = NORMAL_PROFIT_TARGET
        self.let_expire_threshold = LET_EXPIRE_THRESHOLD
        self.stop_loss_multiplier = STOP_LOSS_MULTIPLIER
        self.min_dte = MIN_DTE
        self.quick_profit_min_dte = QUICK_PROFIT_MIN_DTE
        self.market_open_minutes = MARKET_OPEN_MINUTES
        
        # QQQ setup
        self.underlying_symbol = UNDERLYING_SYMBOL
        self.underlying = self.AddEquity(self.underlying_symbol, Resolution.Daily)
        self.underlying.SetDataNormalizationMode(DataNormalizationMode.Raw)
        
        # Add QQQ options with more flexible settings
        self.option = self.AddOption(self.underlying_symbol, Resolution.Daily)
        self.option.SetFilter(self.OptionFilter)
        
        # Use simpler pricing model for better performance
        # self.option.PriceModel = OptionPriceModels.CrankNicolsonFD()
        
        # Warmup
        self.SetWarmUp(WARMUP_DAYS, Resolution.Daily)
        
        # Position tracking
        self.positions = {}
        self.total_credit = 0
        self.total_pnl = 0
        self.trades_count = 0
        self.winning_trades = 0
        
        # Delta tracking
        self.current_portfolio_delta = 0.0
        self.last_hedge_delta = 0.0
        self.hedge_trades = 0
        
        # Track option chains
        self._current_option_chain = None
        
        # Daily position management
        self.Schedule.On(self.DateRules.EveryDay(), 
                        self.TimeRules.AfterMarketOpen(self.underlying_symbol, self.market_open_minutes), 
                        self.ManagePositions)
        
        # Debug flags
        self.debug_mode = DEBUG_MODE
        self.last_debug_date = None
        self.first_live_day = True
        
        # Track failures for better debugging
        self.consecutive_failures = 0
        self.max_consecutive_failures = MAX_CONSECUTIVE_FAILURES
    
    def OptionFilter(self, universe):
        return (universe.PutsOnly()
                       .Strikes(-self.strikes_below, self.strikes_above)
                       .Expiration(self.min_target_dte, self.max_target_dte))
                       # Removed OnlyApplyFilterAtMarketOpen to get more options
    
    def OnData(self, data):
        if self.IsWarmingUp:
            return
        
        if self.first_live_day:
            self.Debug(f"=== FIRST LIVE DAY: {self.Time.date()} ===")
            self.Debug(f"Warmup completed successfully!")
            self.Debug(f"Account Value: ${self.Portfolio.TotalPortfolioValue:,.0f}")
            self.first_live_day = False
        
        if self.option.Symbol in data.OptionChains:
            self._current_option_chain = data.OptionChains[self.option.Symbol]
            
            if self.debug_mode and self.last_debug_date != self.Time.date():
                self.Debug(f"Option chain received: {len(self._current_option_chain)} contracts")
                self.last_debug_date = self.Time.date()
    
    def CalculatePortfolioDelta(self):
        """Calculate total portfolio delta from actual option Greeks"""
        total_options_delta = 0
        delta_breakdown = {}
        
        underlying_price = self.Securities[self.underlying_symbol].Price
        
        for pos_id, position in self.positions.items():
            symbol = position['symbol']
            if symbol in self.Securities:
                option_security = self.Securities[symbol]
                
                # Use actual Greeks from QC's pricing model
                if hasattr(option_security, 'Greeks') and option_security.Greeks is not None:
                    actual_delta = option_security.Greeks.Delta
                    position_delta = actual_delta * position['quantity']
                    total_options_delta += position_delta
                    
                    delta_breakdown[pos_id] = {
                        'strike': position['strike'],
                        'actual_delta_per_contract': actual_delta,
                        'total_position_delta': position_delta,
                        'using_actual_greeks': True
                    }
                else:
                    # Fallback to estimation only if Greeks not available
                    strike = position['strike']
                    dte = (position['expiration'] - self.Time.date()).days
                    
                    moneyness = strike / underlying_price
                    time_factor = max(0.1, min(1.0, dte / 30.0))
                    
                    if moneyness < 0.90:
                        estimated_delta = -0.15 * time_factor
                    elif moneyness < 0.95:
                        estimated_delta = -0.25 * time_factor
                    elif moneyness < 1.00:
                        estimated_delta = -0.40 * time_factor
                    else:
                        estimated_delta = -0.60 * time_factor
                    
                    position_delta = estimated_delta * position['quantity']
                    total_options_delta += position_delta
                    
                    delta_breakdown[pos_id] = {
                        'strike': position['strike'],
                        'estimated_delta_per_contract': estimated_delta,
                        'total_position_delta': position_delta,
                        'using_actual_greeks': False
                    }
                    
                    if self.debug_mode:
                        self.Debug(f"Using delta estimation for {symbol} - Greeks not available")
        
        # Add stock position delta
        stock_shares = self.Portfolio[self.underlying_symbol].Quantity
        stock_delta = stock_shares * 1.0
        
        total_portfolio_delta = total_options_delta + stock_delta
        
        return total_portfolio_delta, total_options_delta, stock_delta, delta_breakdown
    
    def ExecuteDeltaHedge(self):
        """Execute delta hedge to maintain target portfolio delta"""
        portfolio_delta, options_delta, stock_delta, breakdown = self.CalculatePortfolioDelta()
        
        delta_difference = portfolio_delta - self.target_portfolio_delta
        
        if abs(delta_difference) < self.delta_tolerance:
            return False
        
        shares_to_trade = -int(delta_difference * self.hedge_ratio)
        
        if shares_to_trade == 0:
            return False
        
        try:
            ticket = self.MarketOrder(self.underlying_symbol, shares_to_trade)
            
            if ticket.Status == OrderStatus.Filled:
                self.hedge_trades += 1
                self.last_hedge_delta = portfolio_delta
                
                new_stock_delta = stock_delta + shares_to_trade
                self.current_portfolio_delta = options_delta + new_stock_delta
                
                self.Log(f"DELTA HEDGE: {shares_to_trade:+d} shares, "
                        f"Portfolio Δ: {portfolio_delta:.1f} → {self.current_portfolio_delta:.1f}, "
                        f"Target: {self.target_portfolio_delta}")
                
                return True
            else:
                self.Debug(f"Delta hedge order failed: {ticket.Status}")
                return False
                
        except Exception as e:
            self.Debug(f"Delta hedge execution failed: {str(e)}")
            return False
    
    def ManagePositions(self):
        """Main position management with delta hedging"""
        if self.IsWarmingUp:
            self.Debug(f"Still warming up on {self.Time.date()}")
            return
        
        # Calculate current portfolio delta
        portfolio_delta, options_delta, stock_delta, delta_breakdown = self.CalculatePortfolioDelta()
        self.current_portfolio_delta = portfolio_delta
        
        current_margin_use = self.CalculateCurrentMarginUse()
        active_positions = len(self.positions)
        underlying_price = self.Securities[self.underlying_symbol].Price
        
        self.Debug(f"=== POSITION MANAGEMENT {self.Time.date()} ===")
        self.Debug(f"Margin Use: {current_margin_use:.1%}, Target: {self.target_margin_use:.1%}")
        self.Debug(f"QC Margin Used: ${self.Portfolio.TotalMarginUsed:,.0f}")
        self.Debug(f"QC Buying Power: ${self.Portfolio.MarginRemaining:,.0f}")
        self.Debug(f"Positions: {active_positions}, Max: {self.max_positions}")
        self.Debug(f"Underlying Price: ${underlying_price:.2f}")
        self.Debug(f"Portfolio Δ: {portfolio_delta:.1f} (Options: {options_delta:.1f}, Stock: {stock_delta:.1f})")
        self.Debug(f"Target Δ: {self.target_portfolio_delta}, Tolerance: ±{self.delta_tolerance}")
        self.Debug(f"Account Value: ${self.Portfolio.TotalPortfolioValue:,.0f}")
        
        # Check exits first
        self.CheckExitConditions()
        
        # Execute delta hedge after position changes
        hedge_executed = self.ExecuteDeltaHedge()
        
        # Recalculate after exits and hedging
        current_margin_use = self.CalculateCurrentMarginUse()
        active_positions = len(self.positions)
        
        # Try to enter new position if we have margin capacity
        margin_available = self.target_margin_use - current_margin_use
        available_buying_power = self.Portfolio.MarginRemaining
        
        if (active_positions < self.max_positions and 
            margin_available > self.margin_buffer and 
            available_buying_power > self.min_buying_power):
            self.Debug(f"Attempting to enter new position... Available margin: {margin_available:.1%}, "
                      f"Buying Power: ${available_buying_power:,.0f}")
            success = self.TryEnterPosition(margin_available)
            
            if success:
                self.consecutive_failures = 0  # Reset failure counter
                self.ExecuteDeltaHedge()
            else:
                self.consecutive_failures += 1
                self.Debug(f"Failed to enter position ({self.consecutive_failures}/{self.max_consecutive_failures}) - investigating...")
                self.DiagnoseEntryFailure()
                
                # If too many failures, try relaxing constraints
                if self.consecutive_failures >= self.max_consecutive_failures:
                    self.Debug("Too many consecutive failures, relaxing constraints...")
                    self.RelaxConstraints()
        else:
            if active_positions >= self.max_positions:
                self.Debug(f"Skipping entry: Hit max positions {active_positions}/{self.max_positions}")
            elif margin_available <= self.margin_buffer:
                self.Debug(f"Skipping entry: Low margin available {margin_available:.1%}")
            elif available_buying_power <= self.min_buying_power:
                self.Debug(f"Skipping entry: Low buying power ${available_buying_power:,.0f} (min: ${self.min_buying_power:,.0f})")
    
    def RelaxConstraints(self):
        """Relax constraints when having trouble finding tradable options"""
        original_min_premium = self.min_premium
        original_min_moneyness = self.min_moneyness
        
        # Reduce minimum premium requirement
        self.min_premium = max(5, self.min_premium * 0.5)
        # Expand moneyness range
        self.min_moneyness = max(0.60, self.min_moneyness - 0.05)
        
        self.Debug(f"RELAXED CONSTRAINTS: Min premium ${original_min_premium} → ${self.min_premium}, "
                  f"Min moneyness {original_min_moneyness:.2f} → {self.min_moneyness:.2f}")
        
        # Reset failure counter
        self.consecutive_failures = 0
    
    def CalculateCurrentMarginUse(self):
        """Calculate current margin utilization using QC's margin requirements only"""
        total_portfolio_value = self.Portfolio.TotalPortfolioValue
        total_margin_used = self.Portfolio.TotalMarginUsed
        
        if total_portfolio_value <= 0:
            return 0.0
            
        margin_utilization = total_margin_used / total_portfolio_value
        return margin_utilization
    
    def TryEnterPosition(self, available_margin_pct):
        """Enter position sized to use available margin efficiently"""
        
        if not self._current_option_chain or len(self._current_option_chain) == 0:
            self.Debug("No option chain available")
            return False
        
        self.Debug(f"Processing {len(self._current_option_chain)} option contracts")
        
        underlying_price = self.Securities[self.underlying_symbol].Price
        if underlying_price == 0:
            self.Debug("Underlying price is zero")
            return False
        
        target_put = self.FindSuitablePut(self._current_option_chain, underlying_price)
        
        if not target_put:
            self.Debug("No suitable put found")
            return False
        
        # Simplified tradability check - just verify the option exists and has a price
        if not self.IsOptionTradableSimple(target_put['symbol']):
            self.Debug(f"Option {target_put['symbol']} is not tradable")
            return False
        
        position_size = self.CalculateMarginBasedSize(target_put, available_margin_pct)
        
        if position_size == 0:
            self.Debug("Position size calculated as zero")
            return False
        
        try:
            ticket = self.MarketOrder(target_put['symbol'], -position_size)
            
            if ticket.Status == OrderStatus.Filled:
                position_id = f"PUT_{self.Time.strftime('%Y%m%d_%H%M%S')}"
                self.positions[position_id] = {
                    'symbol': target_put['symbol'],
                    'quantity': -position_size,
                    'entry_price': target_put['bid'],
                    'entry_date': self.Time,
                    'credit_received': target_put['bid'] * position_size * 100,
                    'strike': target_put['strike'],
                    'expiration': target_put['expiration']
                }
                
                self.total_credit += target_put['bid'] * position_size * 100
                self.trades_count += 1
                
                self.Log(f"SUCCESS: Sold {position_size} puts at ${target_put['strike']}, "
                        f"Credit: ${target_put['bid'] * position_size * 100:,.0f}, "
                        f"DTE: {target_put['dte']}")
                
                return True
            else:
                self.Debug(f"Order not filled: {ticket.Status}")
                return False
            
        except Exception as e:
            self.Debug(f"Trade execution failed: {str(e)}")
            return False
    
    def IsOptionTradableSimple(self, option_symbol):
        """Simplified tradability check"""
        try:
            if option_symbol not in self.Securities:
                return False
            
            security = self.Securities[option_symbol]
            
            # Just check if we have a valid price
            if security.Price == 0:
                return False
            
            return True
            
        except Exception as e:
            self.Debug(f"Error checking tradability for {option_symbol}: {str(e)}")
            return False
    
    def IsOptionTradable(self, option_symbol):
        """More thorough tradability check for debugging"""
        try:
            if option_symbol not in self.Securities:
                self.Debug(f"Option {option_symbol} not in securities")
                return False
            
            security = self.Securities[option_symbol]
            
            # Check various tradability conditions
            if hasattr(security, 'IsTradable') and not security.IsTradable:
                self.Debug(f"Option {option_symbol} marked as non-tradable")
                return False
            
            if security.Price == 0:
                self.Debug(f"Option {option_symbol} has zero price")
                return False
            
            # Check if option has expired
            if hasattr(security, 'Expiry'):
                if security.Expiry.date() <= self.Time.date():
                    self.Debug(f"Option {option_symbol} has expired")
                    return False
            
            return True
            
        except Exception as e:
            self.Debug(f"Error checking tradability for {option_symbol}: {str(e)}")
            return False
    
    def CalculateMarginBasedSize(self, target_put, available_margin_pct):
        """Calculate position size based on QC's actual margin requirements"""
        account_value = self.Portfolio.TotalPortfolioValue
        available_margin_dollars = account_value * available_margin_pct
        
        current_buying_power = self.Portfolio.MarginRemaining
        max_margin_to_use = min(available_margin_dollars, current_buying_power * self.margin_safety_factor)
        
        strike_price = target_put['strike']
        estimated_margin_per_contract = strike_price * 100 * self.estimated_margin_pct
        
        if estimated_margin_per_contract <= 0:
            return 0
            
        max_contracts_by_margin = int(max_margin_to_use / estimated_margin_per_contract)
        
        position_size = min(self.max_contracts, max(self.min_contracts, max_contracts_by_margin))
        
        min_margin_per_position = account_value * self.min_margin_per_position_pct
        if estimated_margin_per_contract < min_margin_per_position:
            min_contracts = int(min_margin_per_position / estimated_margin_per_contract)
            position_size = max(position_size, min_contracts)
        
        estimated_margin_used = position_size * estimated_margin_per_contract
        estimated_margin_pct = estimated_margin_used / account_value
        
        self.Debug(f"Margin sizing: Available BP ${max_margin_to_use:,.0f}, "
                  f"Est. margin/contract ${estimated_margin_per_contract:,.0f}, "
                  f"Size: {position_size} contracts (est. {estimated_margin_pct:.1%})")
        
        return position_size
    
    def FindSuitablePut(self, option_chain, underlying_price):
        """Find suitable put with enhanced filtering and better error handling"""
        
        candidates = []
        put_count = 0
        dte_filtered = 0
        moneyness_filtered = 0
        price_filtered = 0
        tradability_filtered = 0
        premium_filtered = 0
        
        for contract in option_chain:
            if contract.Right != OptionRight.Put:
                continue
                
            put_count += 1
            
            # Check for valid pricing
            if contract.BidPrice <= 0 or contract.AskPrice <= 0:
                price_filtered += 1
                continue
            
            # Basic tradability check during filtering
            if not self.IsOptionTradableSimple(contract.Symbol):
                tradability_filtered += 1
                continue
                
            # Calculate DTE
            try:
                if hasattr(contract.Expiry, 'date'):
                    expiry_date = contract.Expiry.date()
                else:
                    expiry_date = contract.Expiry
                    
                dte = (expiry_date - self.Time.date()).days
            except:
                self.Debug(f"Error calculating DTE for {contract.Symbol}")
                dte_filtered += 1
                continue
            
            if dte < self.min_target_dte or dte > self.max_target_dte:
                dte_filtered += 1
                continue
                
            moneyness = contract.Strike / underlying_price
            if moneyness < self.min_moneyness or moneyness > self.max_moneyness:
                moneyness_filtered += 1
                continue
                
            premium_per_contract = contract.BidPrice * 100
            
            if premium_per_contract < self.min_premium:
                premium_filtered += 1
                continue
                
            candidates.append({
                'symbol': contract.Symbol,
                'strike': contract.Strike,
                'expiration': expiry_date,
                'bid': contract.BidPrice,
                'ask': contract.AskPrice,
                'moneyness': moneyness,
                'dte': dte,
                'premium': premium_per_contract,
                'spread': contract.AskPrice - contract.BidPrice
            })
        
        self.Debug(f"Put analysis: {put_count} puts total")
        self.Debug(f"Filtered - Price: {price_filtered}, DTE: {dte_filtered}, "
                  f"Moneyness: {moneyness_filtered}, Tradability: {tradability_filtered}, Premium: {premium_filtered}")
        self.Debug(f"DTE Range: {self.min_target_dte}-{self.max_target_dte}, "
                  f"Moneyness: {self.min_moneyness:.0%}-{self.max_moneyness:.0%}, "
                  f"Min Premium: ${self.min_premium}")
        self.Debug(f"Final candidates: {len(candidates)}")
        
        if not candidates:
            self.Debug(f"No candidates found. Underlying: ${underlying_price:.2f}")
            return None
        
        # Sort by premium descending (highest premium first)
        candidates.sort(key=lambda x: x['premium'], reverse=True)
        
        selected = candidates[0]
        self.Debug(f"Selected: Strike ${selected['strike']}, Premium ${selected['premium']:.0f}, "
                  f"DTE {selected['dte']}, Moneyness {selected['moneyness']:.3f}")
        
        return selected
    
    def CheckExitConditions(self):
        """Check exit conditions for all positions"""
        if not self.positions:
            return
        
        positions_to_close = []
        
        for pos_id, position in self.positions.items():
            symbol = position['symbol']
            
            if symbol not in self.Securities:
                self.Debug(f"Position {pos_id} no longer in securities, forcing close")
                positions_to_close.append((pos_id, "Symbol Removed", 0))
                continue
                
            current_price = self.Securities[symbol].Price
            if current_price == 0:
                self.Debug(f"Position {pos_id} has zero price, forcing close")
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
                    
                dte = (expiry_date - self.Time.date()).days
            except:
                self.Debug(f"Error calculating DTE for position {pos_id}, forcing close")
                positions_to_close.append((pos_id, "DTE Error", total_pnl))
                continue
            
            exit_reason = None
            
            # Exit conditions
            if dte <= 2 and current_price <= entry_price * self.let_expire_threshold:
                exit_reason = "Let Expire"
            elif total_pnl >= credit_received * self.quick_profit_target and dte > self.quick_profit_min_dte:
                exit_reason = f"Quick Profit ({self.quick_profit_target:.0%})"
            elif total_pnl >= credit_received * self.normal_profit_target:
                exit_reason = f"Profit Target ({self.normal_profit_target:.0%})"
            elif total_pnl <= -credit_received * self.stop_loss_multiplier:
                exit_reason = f"Stop Loss ({self.stop_loss_multiplier:.0%})"
            elif dte <= self.min_dte:
                exit_reason = "Rolling"
            
            if exit_reason:
                positions_to_close.append((pos_id, exit_reason, total_pnl))
        
        for pos_id, reason, pnl in positions_to_close:
            self.ClosePosition(pos_id, reason, pnl)
    
    def ClosePosition(self, position_id, reason, expected_pnl):
        """Close position and track performance"""
        if position_id not in self.positions:
            return
            
        position = self.positions[position_id]
        symbol = position['symbol']
        
        try:
            ticket = self.MarketOrder(symbol, -position['quantity'])
            
            if symbol in self.Securities:
                exit_price = self.Securities[symbol].Price
                actual_pnl = (position['entry_price'] - exit_price) * abs(position['quantity']) * 100
                self.total_pnl += actual_pnl
                
                if actual_pnl > 0:
                    self.winning_trades += 1
                
                self.Log(f"CLOSED: {reason}, P&L: ${actual_pnl:,.0f}, "
                        f"Strike: ${position['strike']}")
            
            del self.positions[position_id]
            
        except Exception as e:
            self.Debug(f"Error closing position {position_id}: {str(e)}")
            # Still remove from tracking even if close failed
            del self.positions[position_id]
    
    def DiagnoseEntryFailure(self):
        """Diagnose why we can't enter positions"""
        self.Debug("=== ENTRY FAILURE DIAGNOSIS ===")
        
        if not self._current_option_chain:
            self.Debug("❌ No option chain data")
            return
        
        chain_size = len(self._current_option_chain)
        self.Debug(f"✓ Option chain size: {chain_size}")
        
        underlying_price = self.Securities[self.underlying_symbol].Price
        self.Debug(f"✓ Underlying price: ${underlying_price:.2f}")
        
        puts = [c for c in self._current_option_chain if c.Right == OptionRight.Put]
        valid_puts = [c for c in puts if c.BidPrice > 0]
        tradable_puts = [c for c in valid_puts if self.IsOptionTradableSimple(c.Symbol)]
        
        self.Debug(f"✓ Total puts: {len(puts)}")
        self.Debug(f"✓ Valid bid puts: {len(valid_puts)}")
        self.Debug(f"✓ Tradable puts: {len(tradable_puts)}")
        
        if len(tradable_puts) == 0:
            self.Debug("❌ No tradable puts found!")
            # Show some sample puts for debugging
            for i, put in enumerate(puts[:3]):
                try:
                    dte = (put.Expiry.date() - self.Time.date()).days
                    moneyness = put.Strike / underlying_price
                    premium = put.BidPrice * 100
                    tradable = self.IsOptionTradableSimple(put.Symbol)
                    self.Debug(f"Sample put {i+1}: Strike ${put.Strike}, "
                              f"Bid ${put.BidPrice:.2f}, Premium ${premium:.0f}, "
                              f"DTE {dte}, Moneyness {moneyness:.3f}, Tradable: {tradable}")
                except Exception as e:
                    self.Debug(f"Error analyzing sample put {i+1}: {str(e)}")
        else:
            # Show some tradable puts for debugging
            for i, put in enumerate(tradable_puts[:3]):
                try:
                    dte = (put.Expiry.date() - self.Time.date()).days
                    moneyness = put.Strike / underlying_price
                    premium = put.BidPrice * 100
                    self.Debug(f"Tradable put {i+1}: Strike ${put.Strike}, "
                              f"Bid ${put.BidPrice:.2f}, Premium ${premium:.0f}, "
                              f"DTE {dte}, Moneyness {moneyness:.3f}")
                except Exception as e:
                    self.Debug(f"Error analyzing tradable put {i+1}: {str(e)}")
    
    def OnEndOfAlgorithm(self):
        """Final performance report with delta hedging stats"""
        self.Log(f"=== DELTA-HEDGED STRATEGY RESULTS ===")
        self.Log(f"Total Credit: ${self.total_credit:,.0f}")
        self.Log(f"Total P&L: ${self.total_pnl:,.0f}")
        self.Log(f"Final Value: ${self.Portfolio.TotalPortfolioValue:,.0f}")
        
        initial_value = 1000000
        total_return = ((self.Portfolio.TotalPortfolioValue / initial_value) - 1) * 100
        annual_return = (total_return / 10)  # 10-year period
        
        self.Log(f"Total Return: {total_return:.2f}%")
        self.Log(f"Annualized Return: {annual_return:.2f}%")
        
        if self.trades_count > 0:
            win_rate = (self.winning_trades / self.trades_count) * 100
            self.Log(f"Win Rate: {win_rate:.1f}% ({self.winning_trades}/{self.trades_count})")
            
            avg_pnl_per_trade = self.total_pnl / self.trades_count
            self.Log(f"Average P&L per Trade: ${avg_pnl_per_trade:,.0f}")
        
        if self.total_credit > 0:
            efficiency = (self.total_pnl / self.total_credit) * 100
            self.Log(f"P&L Efficiency: {efficiency:.2f}%")
        
        final_portfolio_delta, final_options_delta, final_stock_delta, _ = self.CalculatePortfolioDelta()
        self.Log(f"=== DELTA HEDGING PERFORMANCE ===")
        self.Log(f"Target Portfolio Delta: {self.target_portfolio_delta}")
        self.Log(f"Final Portfolio Delta: {final_portfolio_delta:.1f}")
        self.Log(f"Final Stock Position: {self.Portfolio[self.underlying_symbol].Quantity} shares")
        self.Log(f"Total Hedge Trades: {self.hedge_trades}")
        
        stock_pnl = self.Portfolio[self.underlying_symbol].UnrealizedProfit
        self.Log(f"Stock P&L: ${stock_pnl:,.0f}")
        self.Log(f"Options P&L: ${self.total_pnl:,.0f}")
        self.Log(f"Combined P&L: ${self.total_pnl + stock_pnl:,.0f}")
        
        risk_free_rate = 4.5
        excess_return = annual_return - risk_free_rate
        
        self.Log(f"=== PERFORMANCE VERDICT ===")
        self.Log(f"Risk-Free Rate: {risk_free_rate}%")
        self.Log(f"Excess Return: {excess_return:.2f}%")
        
        if self.trades_count == 0:
            self.Log(" CRITICAL FAILURE: No trades executed!")
        elif annual_return < 0:
            self.Log(" NEGATIVE RETURNS: Strategy lost money")
        elif annual_return < risk_free_rate:
            self.Log(" UNDERPERFORMED: Below risk-free rate")
        elif annual_return < 8:
            self.Log("  MARGINAL: Low returns for options risk")
        elif annual_return < 12:
            self.Log(" DECENT: Reasonable returns")
        else:
            self.Log(" EXCELLENT: High returns justify complexity")
        
        self.Log(f"=== DELTA-NEUTRAL EFFICIENCY ===")
        self.Log(f"• Target +{self.target_portfolio_delta} delta maintained")
        self.Log(f"• Portfolio margin with stock hedges")
        self.Log(f"• Reduced directional risk vs naked puts")
        if self.hedge_trades > 0:
            hedge_frequency = self.hedge_trades / ((self.EndDate - self.StartDate).days / 7)
            self.Log(f"• Hedge frequency: {hedge_frequency:.1f} trades per week")