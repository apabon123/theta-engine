"""
Custom Fill Models for Theta Engine - QuantConnect Lean

This module contains custom fill models that provide more realistic execution
for options trading, based on bid/ask quotes rather than stale prices.
"""

from AlgorithmImports import *
from QuantConnect.Orders.Fills import ImmediateFillModel
from QuantConnect.Orders import OrderStatus, OrderDirection, OrderEvent
from QuantConnect import SecurityType


class MidHaircutFillModel(ImmediateFillModel):
    """
    Mid±Haircut Fill Model for options (minute resolution friendly)

    Provides realistic fills based on current bid/ask quotes:
    - Sells at mid - haircut*spread (buys at mid + haircut*spread)
    - Clamps prices inside the book [bid, ask]
    - Honors limit prices (never worse than your limit)
    - Fills immediately on the bar with quote validation
    """

    def __init__(self, algo, haircut=0.25, max_spread_pct=0.25, clamp_to_book=True, force_fills=False, force_exact_limit=False):
        """
        Initialize the MidHaircutFillModel

        Args:
            algo: The QCAlgorithm instance
            haircut: Fraction of spread taken against you (0.25 = 25% of spread)
            max_spread_pct: Skip fill if spread/price > this (e.g., 25%)
            clamp_to_book: Whether to clamp prices inside [bid, ask]
            force_fills: Force limit order fills even if limit price not met (models spread trading)
        """
        super().__init__()
        self.algo = algo
        self.haircut = float(haircut)
        self.max_spread_pct = float(max_spread_pct)
        self.clamp_to_book = clamp_to_book
        self.force_fills = force_fills
        self.force_exact_limit = force_exact_limit

    def _quote(self, asset):
        """Get current bid/ask quotes and derived values"""
        bid = float(asset.BidPrice) if asset.BidPrice is not None and asset.BidPrice > 0 else None
        ask = float(asset.AskPrice) if asset.AskPrice is not None and asset.AskPrice > 0 else None

        # If requiring both sides of book and either is missing, return None values
        if self.algo.require_bid_ask and (bid is None or ask is None):
            return None, None, None, None  # caller will refuse to fill

        # Graceful fallback to last price only if allowed and needed
        bid = bid if bid is not None else float(asset.Price)
        ask = ask if ask is not None else float(asset.Price)
        mid = (bid + ask) / 2.0
        spread = max(ask - bid, 0.0)
        return bid, ask, mid, spread

    def _px(self, direction, bid, ask, mid, spread, limit=None):
        """
        Calculate fill price based on direction and constraints

        Args:
            direction: OrderDirection.Sell or OrderDirection.Buy
            bid, ask, mid, spread: Current quote values
            limit: Optional limit price to honor

        Returns:
            Fill price respecting all constraints
        """
        # If force_fills is enabled and we have a limit, fill at the limit path first
        if self.force_fills and limit is not None:
            if self.force_exact_limit:
                px = limit
            # FORCE FILL: exact limit execution (no separate logging needed)
            return px
            # Otherwise clamp to the book if requested
            if self.clamp_to_book:
                px = min(max(limit, bid), ask)
            else:
                px = limit
            # FORCE FILL: clamped to book (no separate logging needed)
            return px

        # Normal pricing logic: mid ± k*spread
        px = mid - self.haircut * spread if direction == OrderDirection.Sell else mid + self.haircut * spread

        # Clamp to book if enabled
        if self.clamp_to_book:
            px = min(max(px, bid), ask)

        # Honor limit price if provided (but not forcing fills)
        if limit is not None:
            if direction == OrderDirection.Sell:
                px = max(px, limit)  # Selling: never take less credit than your limit
            else:
                px = min(px, limit)  # Buying: never pay more than your limit

        return px

    def _should_fill_now(self, asset):
        """
        Check if we should fill based on quote sanity and spread constraints

        Returns:
            (should_fill, (bid, ask, mid, spread))
        """
        bid, ask, mid, spread = self._quote(asset)

        # Check if quotes are completely missing (None values returned)
        if bid is None or ask is None:
            if hasattr(self.algo, 'debug_mode') and self.algo.debug_mode:
                self.algo.Debug("NO FILL: missing bid/ask quotes")
            return False, (0.0, 0.0, 0.0, 0.0)

        # Stricter quote sanity - require both sides present and valid
        if bid <= 0 or ask <= 0:
            if hasattr(self.algo, 'debug_mode') and self.algo.debug_mode:
                self.algo.Debug(f"NO FILL: non-positive quotes bid={bid}, ask={ask}")
            return False, (bid, ask, mid, spread)

        if ask < bid:  # Crossed quotes
            if hasattr(self.algo, 'debug_mode') and self.algo.debug_mode:
                self.algo.Debug(f"NO FILL: crossed quotes bid={bid:.2f} > ask={ask:.2f}")
            return False, (bid, ask, mid, spread)

        if mid <= 0:  # Invalid mid calculation
            if hasattr(self.algo, 'debug_mode') and self.algo.debug_mode:
                self.algo.Debug(f"NO FILL: invalid mid={mid}")
            return False, (bid, ask, mid, spread)

        # Check spread isn't absurdly wide relative to price
        if spread / mid > self.max_spread_pct:
            if hasattr(self.algo, 'debug_mode') and self.algo.debug_mode:
                self.algo.Debug(f"NO FILL: spread too wide spread={spread:.2f} mid={mid:.2f} pct={(spread/mid):.2%} > max={self.max_spread_pct:.0%}")
            return False, (bid, ask, mid, spread)

        return True, (bid, ask, mid, spread)

    def MarketFill(self, asset, order):
        """
        Fill market orders at mid ± haircut price

        Args:
            asset: The security being traded
            order: The market order

        Returns:
            List of OrderEvent objects with fill prices
        """
        base = super().MarketFill(asset, order)  # Gets qty/status/timestamps

        ok, q = self._should_fill_now(asset)
        if not ok or not self.algo.fill_on_submission_bar:
            return base  # fall back to Lean behavior

        bid, ask, mid, spread = q
        px = self._px(order.Direction, bid, ask, mid, spread)

        # Normalize base to derive return type and modify in-place
        base_is_list = isinstance(base, list)
        events = base if base_is_list else [base]
        if events and len(events) > 0:
            fill = events[0]
            fill.FillPrice = px
            fill.Status = OrderStatus.Filled
            # Ensure a non-zero filled quantity is recorded
            fill.FillQuantity = order.Quantity
        # Return with same type as base
        return events if base_is_list else events[0]

    def LimitFill(self, asset, order):
        """
        Fill limit orders at mid ± haircut price, but never violate limit

        Args:
            asset: The security being traded
            order: The limit order

        Returns:
            List of OrderEvent objects with fill prices, or empty list if limit violated
        """
        # Always get a base "shell" so qty/fees/timestamp are well-formed
        base = super().LimitFill(asset, order)

        ok, q = self._should_fill_now(asset)
        if not ok or not self.algo.fill_on_submission_bar:
            if hasattr(self.algo, 'debug_mode') and self.algo.debug_mode:
                self.algo.Debug("LIMIT FILL: falling back to Lean base behavior (no immediate fill)")
            return base  # fall back to Lean behavior

        bid, ask, mid, spread = q
        px = self._px(order.Direction, bid, ask, mid, spread, order.LimitPrice)
        # Consolidated fill logging - only show if not already logged by position entry

        # Honor the user's limit & only fill if our computed px is not worse than the limit
        # UNLESS force_fills is enabled (for spread trading simulation)
        if not self.force_fills:
            if order.Direction == OrderDirection.Sell and px + 1e-6 < order.LimitPrice:
                if hasattr(self.algo, 'debug_mode') and self.algo.debug_mode:
                    self.algo.Debug(f"LIMIT FILL: not marketable vs limit (sell) px={px:.2f} < limit={order.LimitPrice:.2f} -> no fill")
                return base  # not marketable relative to limit -> leave resting
            if order.Direction == OrderDirection.Buy and px - 1e-6 > order.LimitPrice:
                if hasattr(self.algo, 'debug_mode') and self.algo.debug_mode:
                    self.algo.Debug(f"LIMIT FILL: not marketable vs limit (buy) px={px:.2f} > limit={order.LimitPrice:.2f} -> no fill")
                return base  # not marketable relative to limit -> leave resting

        # Normalize base to derive return type and modify in-place
        base_is_list = isinstance(base, list)
        events = base if base_is_list else [base]
        if events and len(events) > 0:
            fill = events[0]
            fill.FillPrice = px
            fill.Status = OrderStatus.Filled
            # Ensure a non-zero filled quantity is recorded
            fill.FillQuantity = order.Quantity
        # Return with same type as base
        return events if base_is_list else events[0]


# Factory function for easy instantiation
def create_mid_haircut_fill_model(algo, haircut=0.25, max_spread_pct=0.30, force_fills=False):
    """
    Create a MidHaircutFillModel with sensible defaults

    Args:
        algo: The QCAlgorithm instance
        haircut: Spread haircut fraction (default 0.25 = 25%)
        max_spread_pct: Max spread percentage (default 0.30 = 30%)
        force_fills: Force limit order fills even if limit price not met (default False)

    Returns:
        Configured MidHaircutFillModel instance
    """
    return MidHaircutFillModel(algo, haircut=haircut, max_spread_pct=max_spread_pct, force_fills=force_fills)
