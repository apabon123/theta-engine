"""
Greeks Provider

Unified interface for accessing option Greeks with fallback logic.
Consolidates OptionsDataManager functionality with additional fallbacks.
"""

from AlgorithmImports import *  # noqa: F401
from typing import Tuple, Optional


class GreeksProvider:
    def __init__(self, algorithm, iv_surface=None):
        self.algorithm = algorithm
        self.iv_surface = iv_surface  # Optional placeholder for future model IV

    def _qc_greeks(self, symbol) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        # Use centralized manager; no direct Security access here to keep single source of truth
        try:
            if hasattr(self.algorithm, 'options_data') and self.algorithm.options_data is not None:
                d, _ = self.algorithm.options_data.get_delta(symbol)
                g, _ = self.algorithm.options_data.get_gamma(symbol)
                t, _ = self.algorithm.options_data.get_theta(symbol)
                return d, g, t
        except Exception:
            return None, None, None

    def get_delta(self, symbol, strike: float, und_price: float, expiry) -> Tuple[float, str]:
        # 1) Try QC Greeks from Security
        d, _, _ = self._qc_greeks(symbol)
        if d is not None:
            return d, "QC"
        # 2) Try cached QC Greeks from chain (same-day)
        try:
            if hasattr(self.algorithm, 'greeks_cache') and symbol in self.algorithm.greeks_cache:
                (dval, _g, _t), ts = self.algorithm.greeks_cache[symbol]
                if getattr(self.algorithm, 'Time', None) and ts and ts.date() == self.algorithm.Time.date():
                    return float(dval), "QC-CACHED"
                # If stale, still use last cached but warn once per call
                if dval is not None:
                    try:
                        if getattr(self.algorithm, 'debug_mode', False):
                            age_min = None
                            if getattr(self.algorithm, 'Time', None) and ts:
                                age_min = int((self.algorithm.Time - ts).total_seconds() // 60)
                            self.algorithm.Debug(f"Using STALE cached delta for {symbol}: {dval:.4f} (age={age_min} min)")
                    except Exception:
                        pass
                    return float(dval), "QC-CACHED-STALE"
        except Exception:
            pass
        # 3) Non-zero fallback to avoid instability when QC data unavailable
        is_put = True
        try:
            right = symbol.ID.OptionRight if hasattr(symbol, 'ID') else None
            from AlgorithmImports import OptionRight  # type: ignore
            if right is not None:
                is_put = (right == OptionRight.Put)
        except Exception:
            pass
        fallback = -0.25 if is_put else 0.25
        return float(fallback), "FALLBACK"

    def get_gamma(self, symbol, strike: float, und_price: float, expiry) -> Tuple[float, str]:
        _, g, _ = self._qc_greeks(symbol)
        if g is not None:
            return g, "QC"
        try:
            if hasattr(self.algorithm, 'greeks_cache') and symbol in self.algorithm.greeks_cache:
                (dval, gval, _t), ts = self.algorithm.greeks_cache[symbol]
                if ts and getattr(self.algorithm, 'Time', None) and ts.date() == self.algorithm.Time.date() and gval is not None:
                    return float(gval), "QC-CACHED"
                if gval is not None:
                    if getattr(self.algorithm, 'debug_mode', False):
                        age_min = int((self.algorithm.Time - ts).total_seconds() // 60) if ts else None
                        self.algorithm.Debug(f"Using STALE cached gamma for {symbol}: {gval:.6f} (age={age_min} min)")
                    return float(gval), "QC-CACHED-STALE"
        except Exception:
            pass
        return 0.0, "QC-NONE"

    def get_theta(self, symbol, strike: float, und_price: float, expiry, option_type: str = 'put') -> Tuple[float, str]:
        _, _, t = self._qc_greeks(symbol)
        if t is not None:
            return t, "QC"
        try:
            if hasattr(self.algorithm, 'greeks_cache') and symbol in self.algorithm.greeks_cache:
                (_d, _g, tval), ts = self.algorithm.greeks_cache[symbol]
                if ts and getattr(self.algorithm, 'Time', None) and ts.date() == self.algorithm.Time.date() and tval is not None:
                    return float(tval), "QC-CACHED"
                if tval is not None:
                    if getattr(self.algorithm, 'debug_mode', False):
                        age_min = int((self.algorithm.Time - ts).total_seconds() // 60) if ts else None
                        self.algorithm.Debug(f"Using STALE cached theta for {symbol}: {tval:.6f} (age={age_min} min)")
                    return float(tval), "QC-CACHED-STALE"
        except Exception:
            pass
        return 0.0, "QC-NONE"

    def model_iv(self, dte_days: int, und_price: float, strike: float) -> Optional[float]:
        # Placeholder for future model IV integration (e.g., SSVI). Currently unused.
        return None
