"""
Order Event Handler

Handles order events and position updates for the theta engine.
Extracted from main.py to reduce file size.
"""

from AlgorithmImports import *


class OrderEventHandler:
    """Handles order events and position updates"""
    
    def __init__(self, algorithm):
        self.algorithm = algorithm
    
    def handle_order_event(self, order_event):
        """
        Order event handler - delegates to execution manager.
        """
        # Update position tracking on fills
        if order_event.Status == OrderStatus.Filled:
            try:
                symbol = order_event.Symbol
                fill_price = order_event.FillPrice
                fill_quantity = order_event.FillQuantity
                
                # Update position tracking
                if symbol in self.algorithm.positions:
                    position = self.algorithm.positions[symbol]
                    old_quantity = position.get('quantity', 0)
                    position['quantity'] = old_quantity + fill_quantity
                    
                    # Update entry price for new positions
                    if old_quantity == 0 and fill_quantity != 0:
                        position['entry_price'] = fill_price
                        if fill_quantity < 0:  # Short position
                            position['credit_received'] = abs(fill_quantity) * fill_price * 100
                    
                    # Check if this is a hedge position
                    is_hedge_position = symbol == self.algorithm.underlying_symbol
                    pos_id = f"hedge_{symbol}_{self.algorithm.Time.strftime('%Y%m%d_%H%M%S')}" if is_hedge_position else f"{symbol}_{self.algorithm.Time.strftime('%Y%m%d_%H%M%S')}"
                    
                    if is_hedge_position:
                        self.algorithm.Log(f"POSITION FILLED: {pos_id} | Quantity: {position['quantity']} | "
                                         f"Credit: ${position.get('credit_received', 0):.0f}")
                    else:
                        self.algorithm.Log(f"POSITION FILLED: {pos_id} | Quantity: {position['quantity']} | "
                                         f"Entry: ${position['entry_price']:.2f} | "
                                         f"Credit: ${position.get('credit_received', 0):.0f}")
                    
                    # Debug logging for option fills
                    if (hasattr(order_event, 'Symbol') and
                        order_event.Symbol.SecurityType == SecurityType.Option and
                        order_event.FillQuantity != 0 and
                        self.algorithm.debug_mode):
                        # Single consolidated log entry for option fills
                        self._log_consolidated_option_fill(order_event)
                        
            except Exception as e:
                if self.algorithm.debug_mode:
                    self.algorithm.Debug(f"OnOrderEvent update error: {e}")
    
    def _log_consolidated_option_fill(self, order_event):
        """
        Single consolidated log entry for option fills with all essential information.
        Replaces multiple redundant log entries with one comprehensive line.
        """
        try:
            symbol = order_event.Symbol
            current_time = self.algorithm.Time.strftime("%H:%M:%S")
            
            # Log OnData timing for fills
            self.algorithm.Debug(f"OnData FILL: Processing fill at {current_time} for {symbol}")
            
            # Check if we have current option chain data for this symbol
            option_chain_bid = None
            option_chain_ask = None
            if hasattr(self.algorithm, 'current_chain') and self.algorithm.current_chain:
                for contract in self.algorithm.current_chain:
                    if contract.Symbol == symbol:
                        option_chain_bid = contract.BidPrice if contract.BidPrice and contract.BidPrice > 0 else None
                        option_chain_ask = contract.AskPrice if contract.AskPrice and contract.AskPrice > 0 else None
                        break
            
            # Log option chain data if available
            if option_chain_bid and option_chain_ask:
                chain_spread = option_chain_ask - option_chain_bid
                chain_spread_pct = (chain_spread / ((option_chain_bid + option_chain_ask) / 2)) * 100 if (option_chain_bid + option_chain_ask) / 2 > 0 else 0
                self.algorithm.Debug(f"OnData CHAIN: {symbol} bid/ask from option chain: ${option_chain_bid:.2f}/${option_chain_ask:.2f} (${chain_spread:.2f}, {chain_spread_pct:.1f}%)")
            else:
                self.algorithm.Debug(f"OnData CHAIN: {symbol} no option chain data available")
            
            # Use centralized market data manager for consistent data source
            bid, ask, source = self.algorithm.market_data.get_bid_ask(symbol)
            
            direction = "SELL" if order_event.FillQuantity < 0 else "BUY"
            
            if bid and ask:
                spread = ask - bid
                spread_pct = (spread / ((bid + ask) / 2)) * 100 if (bid + ask) / 2 > 0 else 0
                source_label = f" [{source}]" if source != "OPTION_CHAIN" else ""
                
                # Single comprehensive log entry with data source info
                self.algorithm.Debug(f"OPTION FILL: {symbol} {direction} {abs(order_event.FillQuantity)} @ ${order_event.FillPrice:.2f} | Market: ${bid:.2f}/${ask:.2f} (${spread:.2f}, {spread_pct:.1f}%){source_label}")
            else:
                self.algorithm.Debug(f"OPTION FILL: {symbol} {direction} {abs(order_event.FillQuantity)} @ ${order_event.FillPrice:.2f} | Market: No quotes")
                
        except Exception as e:
            direction = "SELL" if order_event.FillQuantity < 0 else "BUY"
            self.algorithm.Debug(f"OPTION FILL: {order_event.Symbol} {direction} {abs(order_event.FillQuantity)} @ ${order_event.FillPrice:.2f} | Market: Error getting quotes")
