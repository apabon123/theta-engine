"""
MarketDataManager

Centralized market data retrieval with proper fallback hierarchy and logging.
Provides consistent bid/ask price access across the entire algorithm.

Data Source Hierarchy:
1) OPTION_CHAIN: Fresh option chain data (preferred - most current)
2) SECURITIES: Securities collection fallback (persistent but potentially stale)
3) ERROR: Log when fallback occurs and data is missing

Usage:
    market_data = MarketDataManager(algorithm)
    bid, ask, source = market_data.get_bid_ask(symbol, option_data)
    if bid and ask:
        # Use prices with confidence
    else:
        # Handle missing data
"""

from AlgorithmImports import *
from typing import Optional, Tuple


class MarketDataManager:
    """
    Centralized market data retrieval with proper fallback hierarchy.
    
    Ensures consistent data source usage and logs when fallbacks occur.
    """
    
    def __init__(self, algorithm):
        self.algorithm = algorithm
        self.debug_mode = getattr(algorithm, 'debug_mode', False)
        
    def get_bid_ask(self, symbol: Symbol, option_data: dict = None) -> Tuple[Optional[float], Optional[float], str]:
        """
        Get bid/ask prices with proper fallback hierarchy and logging.
        
        Args:
            symbol: Option symbol to get prices for
            option_data: Optional option chain data (preferred source)
            
        Returns:
            (bid, ask, source) where source indicates data origin
        """
        current_time = self.algorithm.Time.strftime("%H:%M:%S")
        
        # 1) Try option chain data first (most fresh)
        if option_data:
            bid = self._safe_float(option_data.get('bid_price'))
            ask = self._safe_float(option_data.get('ask_price'))
            
            if bid and ask and bid > 0 and ask > 0:
                if self.debug_mode:
                    self.algorithm.Debug(f"MARKET DATA [{current_time}]: {symbol} using OPTION_CHAIN data: ${bid:.2f}/${ask:.2f}")
                return bid, ask, "OPTION_CHAIN"
        
        # 2) Fallback to Securities collection
        try:
            security = self.algorithm.Securities[symbol]
            bid = self._safe_float(security.BidPrice)
            ask = self._safe_float(security.AskPrice)
            
            if bid and ask and bid > 0 and ask > 0:
                # Log the fallback with timing context
                if self.debug_mode:
                    self.algorithm.Debug(f"MARKET DATA [{current_time}]: {symbol} FALLBACK to SECURITIES (no OnData at {current_time}): ${bid:.2f}/${ask:.2f}")
                return bid, ask, "SECURITIES"
        except Exception as e:
            if self.debug_mode:
                self.algorithm.Debug(f"MARKET DATA [{current_time}]: {symbol} Securities lookup failed: {e}")
        
        # 3) No valid data available
        if self.debug_mode:
            self.algorithm.Debug(f"MARKET DATA [{current_time}]: {symbol} NO VALID DATA - bid/ask unavailable")
        return None, None, "ERROR"
    
    def get_mid_price(self, symbol: Symbol, option_data: dict = None) -> Tuple[Optional[float], str]:
        """
        Get mid price with proper fallback hierarchy.
        
        Returns:
            (mid_price, source) where source indicates data origin
        """
        bid, ask, source = self.get_bid_ask(symbol, option_data)
        if bid and ask:
            mid = (bid + ask) / 2.0
            return mid, source
        return None, source
    
    def get_spread_info(self, symbol: Symbol, option_data: dict = None) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
        """
        Get comprehensive spread information.
        
        Returns:
            (bid, ask, spread, source) where spread = ask - bid
        """
        bid, ask, source = self.get_bid_ask(symbol, option_data)
        if bid and ask:
            spread = ask - bid
            return bid, ask, spread, source
        return None, None, None, source
    
    def _safe_float(self, value) -> Optional[float]:
        """Safely convert value to float, handling None and invalid cases."""
        if value is None:
            return None
        try:
            result = float(value)
            return result if result > 0 else None
        except (ValueError, TypeError):
            return None
    
    def log_data_source_usage(self, symbol: Symbol, source: str, bid: Optional[float], ask: Optional[float]):
        """
        Log when different data sources are used for debugging.
        
        This helps identify when fallbacks occur and why.
        """
        if not self.debug_mode:
            return
            
        if source == "OPTION_CHAIN":
            self.algorithm.Debug(f"MARKET DATA: {symbol} using fresh option chain data")
        elif source == "SECURITIES":
            self.algorithm.Debug(f"MARKET DATA: {symbol} FALLBACK to Securities collection")
        elif source == "ERROR":
            self.algorithm.Debug(f"MARKET DATA: {symbol} NO DATA AVAILABLE from any source")
        
        if bid and ask:
            spread = ask - bid
            spread_pct = (spread / ((bid + ask) / 2)) * 100 if (bid + ask) / 2 > 0 else 0
            self.algorithm.Debug(f"MARKET DATA: {symbol} ${bid:.2f}/${ask:.2f} (spread: ${spread:.2f}, {spread_pct:.1f}%)")
