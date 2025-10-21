"""
Lightweight SSVI-inspired model without SciPy dependencies.
Fits per-expiry parameters using coarse grid search on (a, b, rho),
with m=0 and sigma=0.1 fixed to keep computation tractable in QC.
"""

import math
from typing import Dict, List, Tuple


class SSVISimpleModel:
    def __init__(self) -> None:
        self.params_by_dte: Dict[int, Dict[str, float]] = {}

    def _ssvi_iv(self, k: float, t: float, a: float, b: float, rho: float, m: float = 0.0, sigma: float = 0.1) -> float:
        # Adjust log-moneyness for shift
        k_adj = k - m
        theta = a * t
        # Core SSVI variance (Gatheral-Jacquier form)
        w_k = theta * (1 + b * rho * k_adj + b * math.sqrt((k_adj + rho) ** 2 + (1 - rho ** 2)))
        if w_k <= 0 or t <= 0:
            return float('nan')
        w_k *= (1 + sigma * k_adj * k_adj)
        iv = math.sqrt(max(w_k / t, 0.0))
        return iv

    def fit_single_expiry(self, rows: List[Tuple[float, float, float]], t: float) -> Dict[str, float]:
        """
        Fit simple (a,b,rho) by minimizing squared IV error on a coarse grid.
        rows: list of (k=ln(K/S), market_iv, dte_int)
        t: time to expiry in years
        """
        if t <= 0 or not rows:
            return {}

        # Set a around median IV level to reduce grid size; scan small band
        ivs = [iv for _, iv, _ in rows if iv is not None and iv > 0]
        if not ivs:
            return {}
        atm = sorted(ivs)[len(ivs) // 2]

        a_grid = [max(0.05, atm * f) for f in [0.6, 0.8, 1.0, 1.2, 1.5]]
        b_grid = [0.02, 0.05, 0.1, 0.15, 0.2]
        rho_grid = [-0.8, -0.6, -0.4, -0.2, 0.0, 0.2]

        best_err = float('inf')
        best = None

        for a in a_grid:
            for b in b_grid:
                for rho in rho_grid:
                    if b * (1 + abs(rho)) >= 1.0:  # No-arbitrage guard
                        continue
                    se = 0.0
                    ok = True
                    for k, mkt_iv, _ in rows:
                        mdl = self._ssvi_iv(k, t, a, b, rho)
                        if math.isnan(mdl) or mdl <= 0:
                            ok = False
                            break
                        d = mdl - mkt_iv
                        se += d * d
                    if ok and se < best_err:
                        best_err = se
                        best = (a, b, rho)

        if not best:
            return {}
        a, b, rho = best
        return {'a': a, 'b': b, 'rho': rho, 'm': 0.0, 'sigma': 0.1, 'time_to_expiry': t}

    def fit(self, data: List[Tuple[int, float, float, float]]) -> None:
        """
        Fit parameters per DTE.
        data rows: (dte_days, underlying_price, strike, iv)
        """
        # Group by DTE
        by_dte: Dict[int, List[Tuple[float, float, int]]] = {}
        for dte, s, k, iv in data:
            if iv is None or iv <= 0 or s <= 0 or k <= 0:
                continue
            t = max(dte / 365.0, 1e-6)
            ln_m = math.log(k / s)
            by_dte.setdefault(dte, []).append((ln_m, iv, dte))

        params: Dict[int, Dict[str, float]] = {}
        for dte, rows in by_dte.items():
            t = max(dte / 365.0, 1e-6)
            p = self.fit_single_expiry(rows, t)
            if p:
                params[dte] = p

        self.params_by_dte = params

    def model_iv(self, dte: int, s: float, k: float) -> float:
        if dte not in self.params_by_dte or s <= 0 or k <= 0:
            return float('nan')
        p = self.params_by_dte[dte]
        t = max(dte / 365.0, 1e-6)
        klog = math.log(k / s)
        return self._ssvi_iv(klog, t, p['a'], p['b'], p['rho'], p['m'], p['sigma'])


