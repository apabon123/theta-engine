"""
Execution Modes Module for Theta Engine

This module handles the different execution modes: EOD (End of Day) vs Intraday.
Manages data subscriptions, timing, and order execution strategies.
"""

from AlgorithmImports import *


class ExecutionModeManager:
    """Manages EOD vs Intraday execution modes"""

    def __init__(self, algorithm):
        self.algorithm = algorithm

    def setup_execution_mode(self):
        """Setup data subscriptions and scheduling based on execution mode"""
        self.algorithm.hedge_frequency = self.algorithm.hedge_frequency.upper()

        if self.algorithm.hedge_frequency == "INTRADAY":
            self._setup_intraday_mode()
        else:  # EOD
            self._setup_eod_mode()

    def _setup_intraday_mode(self):
        """Setup for intraday execution with real-time data"""
        self.algorithm.intraday_hedging = True

        # Subscribe to minute-resolution data
        self.algorithm.underlying = self.algorithm.AddEquity(
            self.algorithm.underlying_symbol,
            Resolution.Minute
        )
        self.algorithm.option = self.algorithm.AddOption(
            self.algorithm.underlying_symbol,
            Resolution.Minute
        )

        # Enable pricing model for Greeks
        self.algorithm.option.PriceModel = OptionPriceModels.BlackScholes()

        # Warm up data
        self.algorithm.SetWarmUp(self.algorithm.warmup_days, Resolution.Minute)

        self.algorithm.Debug("Intraday mode: Real-time hedging with actual Greeks")

    def _setup_eod_mode(self):
        """Setup for EOD execution with daily data"""
        self.algorithm.intraday_hedging = False

        # Subscribe to daily data for faster backtests
        self.algorithm.underlying = self.algorithm.AddEquity(
            self.algorithm.underlying_symbol,
            Resolution.Daily
        )
        self.algorithm.option = self.algorithm.AddOption(
            self.algorithm.underlying_symbol,
            Resolution.Daily
        )

        # Schedule atomic EOD operations
        self.algorithm.Schedule.On(
            self.algorithm.DateRules.Every(DayOfWeek.Monday, DayOfWeek.Tuesday, DayOfWeek.Wednesday,
                                         DayOfWeek.Thursday, DayOfWeek.Friday),
            self.algorithm.TimeRules.AfterMarketClose(self.algorithm.underlying_symbol, 0),
            self._schedule_atomic_eod
        )

        # Setup custom fill model for accurate EOD fills (fill model is defined in main.py)
        self.algorithm.underlying.SetFillModel(self.algorithm.close_fill_model)
        self.algorithm.option.SetFillModel(self.algorithm.close_fill_model)

        # Setup security initializer for new option contracts
        self.algorithm.SetSecurityInitializer(self._initialize_security)

        self.algorithm.Debug("EOD mode: Daily resolution with close-price fills")

    def _initialize_security(self, security):
        """Initialize new securities with appropriate fill models"""
        if hasattr(self.algorithm, 'close_fill_model'):
            security.SetFillModel(self.algorithm.close_fill_model)

    def _schedule_atomic_eod(self):
        """Schedule atomic EOD execution through main algorithm."""
        try:
            # Clean up stale orders first
            self._cleanup_stale_orders()

            # Clean up unfilled positions
            self._cleanup_unfilled_positions()

            # Run atomic EOD execution through main algorithm
            self.algorithm._run_atomic_eod_execution()

        except Exception as e:
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Atomic EOD scheduling error: {e}")

    def _process_eod_option_chains(self):
        """Process option chains for EOD operations"""
        if not hasattr(self.algorithm, '_current_option_chain') or not self.algorithm._current_option_chain:
            return

        # Process the current option chain for position management
        self._manage_positions_eod()

    def _manage_positions_eod(self):
        """Manage positions at end of day"""
        try:
            # Look for new position opportunities
            if hasattr(self.algorithm, '_current_option_chain') and self.algorithm._current_option_chain:
                candidates = self.algorithm.position_manager.find_tradable_options(self.algorithm._current_option_chain)
                
                if candidates:
                    best_option = self.algorithm.position_manager.select_best_option(candidates)
                    if best_option:
                        success = self.algorithm.position_manager.try_enter_position(best_option)
                        self.algorithm.position_manager.track_entry_attempt(success)
                        
                        if not success:
                            self.algorithm.position_manager.update_adaptive_constraints()

        except Exception as e:
            self.algorithm.Debug(f"Error managing EOD positions: {e}")

    def handle_data(self, data):
        """Handle incoming data based on execution mode"""
        try:
            # Store option chains for processing
            if data.OptionChains:
                for kvp in data.OptionChains:
                    symbol = kvp.Key
                    chain = kvp.Value
                    if symbol == self.algorithm.option.Symbol:
                        self.algorithm._current_option_chain = chain

                        # PERFORMANCE OPTIMIZATION: Build EOD price cache for O(1) lookups
                        self.algorithm._eod_price_cache = {}
                        for contract in chain:
                            if contract.BidPrice > 0 and contract.AskPrice > 0:
                                mid_price = (contract.BidPrice + contract.AskPrice) / 2
                            else:
                                mid_price = 0.0
                            self.algorithm._eod_price_cache[contract.Symbol] = mid_price

                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"Stored option chain: {len(chain)} contracts (cache built)")
                        
                        # For intraday mode, process immediately
                        if self.algorithm.intraday_hedging:
                            self._process_intraday_data(chain)
                        else:
                            # For EOD mode, process when we receive option chain data
                            # (Data is only received during market hours anyway)
                            if self.algorithm.debug_mode:
                                self.algorithm.Debug("Processing EOD option chain data")
                            self._process_eod_option_chain_data(chain)

        except Exception as e:
            self.algorithm.Debug(f"Error handling data: {e}")

    def _process_eod_option_chain_data(self, option_chain):
        """Process option chain data for EOD mode during market hours - NO HEDGING"""
        try:
            # Check exit conditions for existing positions
            if self.algorithm.exit_rules:
                self.algorithm.exit_rules.check_exit_conditions()
            
            # Look for new position opportunities - NO HEDGING HERE
            if len(self.algorithm.positions) < self.algorithm.max_positions:
                candidates = self.algorithm.position_manager.find_tradable_options(option_chain)
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"Found {len(candidates)} tradable option candidates")
                
                if candidates:
                    best_option = self.algorithm.position_manager.select_best_option(candidates)
                    if best_option:
                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"Attempting to enter position: {best_option['symbol']}")
                        success = self.algorithm.position_manager.try_enter_position(best_option)
                        self.algorithm.position_manager.track_entry_attempt(success)

                        if not success:
                            self.algorithm.position_manager.update_adaptive_constraints()
                else:
                    if self.algorithm.debug_mode:
                        self.algorithm.Debug("No suitable option candidates found")
            
            # NO HEDGING HERE - Only hedge once at EOD in scheduled operation
                
        except Exception as e:
            self.algorithm.Debug(f"Error processing EOD option chain data: {e}")

    def _process_intraday_data(self, option_chain):
        """Process option chain data for intraday execution"""
        try:
            # Check exit conditions for existing positions
            if self.algorithm.exit_rules:
                self.algorithm.exit_rules.check_exit_conditions()

            # Look for new position opportunities
            candidates = self.algorithm.position_manager.find_tradable_options(option_chain)
            
            if candidates:
                best_option = self.algorithm.position_manager.select_best_option(candidates)
                if best_option:
                    success = self.algorithm.position_manager.try_enter_position(best_option)
                    self.algorithm.position_manager.track_entry_attempt(success)
                    
                    if not success:
                        self.algorithm.position_manager.update_adaptive_constraints()

            # NOTE: Delta hedging is now event-driven (happens after option fills)
            # No need to hedge here - hedge adjusts automatically when positions change

        except Exception as e:
            self.algorithm.Debug(f"Error processing intraday data: {e}")

    def handle_order_events(self, order_event):
        """Handle order events based on execution mode"""
        try:
            # Update position tracking
            if order_event.Status == OrderStatus.Filled:
                self._update_position_on_fill(order_event)

                # Execute post-fill delta hedge for ALL option fills (but skip during EOD atomic execution)
                # During EOD phase, hedging is handled atomically at the end of the batch
                if (hasattr(order_event, 'Symbol') and
                    order_event.Symbol.SecurityType == SecurityType.Option and
                    order_event.FillQuantity != 0 and
                    not getattr(self.algorithm, 'eod_phase', False)):  # Skip during EOD atomic execution

                    if getattr(self.algorithm, '_last_hedge_time', None) == self.algorithm.Time:
                        # Already hedged on this bar
                        return

                    if order_event.FillQuantity < 0:  # Short option entry
                        self.algorithm.Log(f"Option ENTRY filled - executing post-fill delta hedge: {order_event.Symbol}")
                    else:  # Option exit
                        self.algorithm.Log(f"Option EXIT filled - adjusting delta hedge: {order_event.Symbol}")

                    if self.algorithm.delta_hedger:
                        self.algorithm._last_hedge_time = self.algorithm.Time
                        self.algorithm.delta_hedger.execute_delta_hedge_universal()

        except Exception as e:
            self.algorithm.Debug(f"Order event handling error: {e}")

    def _update_position_on_fill(self, order_event):
        """Update position tracking when orders are filled"""
        try:
            symbol = order_event.Symbol
            fill_price = order_event.FillPrice
            fill_quantity = order_event.FillQuantity

            # Find and update position
            updated = False
            for pos_id, position in list(self.algorithm.positions.items()):
                if position['symbol'] == symbol:
                    # Update entry price with actual fill price
                    if position['quantity'] == 0:  # New position
                        position['entry_price'] = fill_price
                        position['quantity'] = fill_quantity
                    else:
                        # Average fill price for partial fills
                        total_quantity = position['quantity'] + fill_quantity
                        if total_quantity != 0:
                            position['entry_price'] = (
                                (position['entry_price'] * position['quantity']) +
                                (fill_price * fill_quantity)
                            ) / total_quantity
                        position['quantity'] = total_quantity

                    # Update credit received for option positions
                    if symbol.SecurityType == SecurityType.Option and fill_quantity < 0:
                        credit = -fill_price * abs(fill_quantity) * 100
                        position['credit_received'] = position.get('credit_received', 0) + credit

                    self.algorithm.Log(f"POSITION FILLED: {pos_id} | "
                                     f"Quantity: {position['quantity']} | "
                                     f"Entry: ${position['entry_price']:.2f} | "
                                     f"Credit: ${position.get('credit_received', 0):.0f}")

                    # Remove fully closed positions
                    if abs(position['quantity']) < 1e-6:
                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"POSITION CLOSED: Removing {pos_id}")
                        del self.algorithm.positions[pos_id]

                    updated = True
                    break

            # Handle equity hedge fills (track in ledger for consistency)
            if not updated and abs(fill_quantity) > 0 and symbol.SecurityType == SecurityType.Equity:
                # This is an equity hedge fill - track it in our ledger
                hedge_id = f"hedge_{symbol}_{self.algorithm.Time.strftime('%Y%m%d_%H%M%S')}"

                # Calculate hedge direction and purpose
                is_hedge_entry = (symbol == self.algorithm.underlying_symbol)

                self.algorithm.positions[hedge_id] = {
                    'symbol': symbol,
                    'quantity': fill_quantity,
                    'entry_price': fill_price,
                    'credit_received': 0.0,  # No credit for equity hedges
                    'expiration': None,      # No expiration for equities
                    'strike': None,          # No strike for equities
                    'timestamp': self.algorithm.Time,
                    'target_contracts': None,
                    'is_hedge': True         # Mark as hedge position
                }

                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"Tracked hedge fill: {hedge_id} | Qty: {fill_quantity} | Price: ${fill_price:.2f}")

                updated = True

            if not updated and abs(fill_quantity) > 0:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"WARNING: Fill received for untracked position: {symbol} | Quantity: {fill_quantity}")

        except Exception as e:
            self.algorithm.Debug(f"Error updating position on fill: {e}")

    def should_process_data(self, data):
        """Determine if data should be processed based on execution mode"""
        if self.algorithm.intraday_hedging:
            # Intraday: process on every bar
            return True
        else:
            # EOD: only process when we have option chains
            return (data.OptionChains and 
                   self.algorithm.option.Symbol in data.OptionChains)

    def get_option_price_for_mode(self, symbol):
        """Get appropriate option price based on execution mode"""
        if self.algorithm.intraday_hedging:
            # Intraday: use current market price
            return self.algorithm.Securities[symbol].Price
        else:
            # EOD: use BBO mid from current chain
            return self.algorithm.GetOptionEodPrice(symbol)

    def _cleanup_unfilled_positions(self):
        """Remove positions that were submitted but never filled"""
        try:
            positions_to_remove = []
            
            for pos_id, position in self.algorithm.positions.items():
                # If position has zero quantity, it means the order never filled
                if position.get('quantity', 0) == 0:
                    # Check if there are any open orders for this symbol
                    symbol = position['symbol']
                    open_orders = self.algorithm.Transactions.GetOpenOrders(symbol)
                    
                    if not open_orders:
                        # No open orders and no filled quantity = failed order
                        self.algorithm.Debug(f"CLEANUP: Removing unfilled position {pos_id} for {symbol}")
                        positions_to_remove.append(pos_id)
            
            # Remove unfilled positions
            for pos_id in positions_to_remove:
                del self.algorithm.positions[pos_id]
                
        except Exception as e:
            self.algorithm.Debug(f"Error cleaning up unfilled positions: {e}")

    def _cleanup_stale_orders(self):
        """Clean up stale open orders to prevent accumulation over time"""
        try:
            canceled_count = 0

            # Cancel stale underlying orders
            underlying_symbol = self.algorithm.underlying_symbol
            if underlying_symbol in self.algorithm.Securities:
                open_underlying_orders = self.algorithm.Transactions.GetOpenOrders(underlying_symbol)
                for order in open_underlying_orders:
                    # Cancel if order is more than 1 day old (stale)
                    # Handle timezone-aware vs timezone-naive datetime comparison
                    try:
                        # Try direct subtraction first
                        time_diff = self.algorithm.Time - order.Time
                        is_stale = time_diff.days >= 1
                    except TypeError:
                        # Handle timezone mismatch by converting to UTC and making naive
                        try:
                            # Convert algorithm time to UTC if timezone-aware
                            if hasattr(self.algorithm.Time, 'tzinfo') and self.algorithm.Time.tzinfo is not None:
                                current_time = self.algorithm.Time.astimezone(self.algorithm.Time.tzinfo).replace(tzinfo=None)
                            else:
                                current_time = self.algorithm.Time

                            # Convert order time to naive if timezone-aware
                            if hasattr(order.Time, 'tzinfo') and order.Time.tzinfo is not None:
                                order_time = order.Time.astimezone(order.Time.tzinfo).replace(tzinfo=None)
                            else:
                                order_time = order.Time

                            time_diff = current_time - order_time
                            is_stale = time_diff.days >= 1
                        except:
                            # Fallback: if all else fails, cancel orders older than 2 days ago
                            is_stale = True

                    if is_stale:
                        self.algorithm.Transactions.CancelOrder(order.Id, "EOD cleanup: stale underlying order")
                        canceled_count += 1
                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"Canceled stale underlying order: {order.Id}")

            # Cancel stale option orders
            all_open_orders = self.algorithm.Transactions.GetOpenOrders()
            for order in all_open_orders:
                # Check if it's an option order and is stale
                if hasattr(order, 'Symbol') and order.Symbol.SecurityType == SecurityType.Option:
                    # Handle timezone-aware vs timezone-naive datetime comparison
                    try:
                        # Try direct subtraction first
                        time_diff = self.algorithm.Time - order.Time
                        is_stale = time_diff.days >= 1
                    except TypeError:
                        # Handle timezone mismatch by converting to UTC and making naive
                        try:
                            # Convert algorithm time to UTC if timezone-aware
                            if hasattr(self.algorithm.Time, 'tzinfo') and self.algorithm.Time.tzinfo is not None:
                                current_time = self.algorithm.Time.astimezone(self.algorithm.Time.tzinfo).replace(tzinfo=None)
                            else:
                                current_time = self.algorithm.Time

                            # Convert order time to naive if timezone-aware
                            if hasattr(order.Time, 'tzinfo') and order.Time.tzinfo is not None:
                                order_time = order.Time.astimezone(order.Time.tzinfo).replace(tzinfo=None)
                            else:
                                order_time = order.Time

                            time_diff = current_time - order_time
                            is_stale = time_diff.days >= 1
                        except:
                            # Fallback: if all else fails, cancel orders older than 2 days ago
                            is_stale = True

                    if is_stale:
                        self.algorithm.Transactions.CancelOrder(order.Id, "EOD cleanup: stale option order")
                        canceled_count += 1
                        if self.algorithm.debug_mode:
                            self.algorithm.Debug(f"Canceled stale option order: {order.Id}")

            if canceled_count > 0:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"EOD cleanup: canceled {canceled_count} stale orders")

        except Exception as e:
            if self.algorithm.debug_mode:
                self.algorithm.Debug(f"Error cleaning up stale orders: {e}")
