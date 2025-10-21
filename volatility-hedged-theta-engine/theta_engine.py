"""
Theta Engine strategy plug-in (default): systematic short OTM puts.

This strategy maximizes premium-per-day efficiency while targeting:
- Delta: 18-25Δ (optimal theta/risk balance)
- DTE: 30-45 days (sweet spot for time decay)
- Spread quality: Tight spreads for good execution
"""

from AlgorithmImports import *  # noqa: F401
from typing import List, Dict, Any
from strategy_base import StrategyBase, StrategyContext, EntryIntent, ExitIntent, HedgePolicy


class ThetaEngineStrategy(StrategyBase):
    """
    Theta decay strategy: Sell OTM puts, collect premium, hedge delta.
    
    Scoring: Maximize daily return on capital (premium / margin / DTE)
    while staying within target delta/DTE bands.
    """
    
    def select_entries(self, option_chain, ctx: StrategyContext) -> List[EntryIntent]:
        """Find and score candidates using theta-specific criteria"""
        # Get infrastructure-filtered candidates (liquidity, spreads, etc.)
        candidates = []
        if option_chain is not None:
            try:
                candidates = ctx.algorithm.position_manager.find_tradable_options(option_chain)
            except Exception:
                candidates = []
        
        if not candidates:
            return []

        # STRATEGY-SPECIFIC: Score and select best option
        best = self._score_and_select(candidates, ctx)
        
        # Log selection for clarity
        if ctx.algorithm.debug_mode and best:
            ctx.algorithm.Debug(f"  Scoring: Selected BEST option from {len(candidates)} candidates (premium-per-day efficiency)")
        
        intents = [EntryIntent(candidate=best)] if best else []
        
        # Record selected symbol for caching
        try:
            ctx.algorithm._last_selected_symbols = [best['symbol']] if best else []
        except Exception:
            pass
        
        return intents
    
    def _score_and_select(self, candidates: List[Dict[str, Any]], ctx: StrategyContext) -> Dict[str, Any]:
        """
        THETA STRATEGY SCORING: Premium-per-day efficiency with target bands.
        
        This is the core strategy logic - when you plug in SSVI or other strategies,
        they would have completely different scoring methods.
        """
        best_option = None
        best_score = float('-inf')
        
        for candidate in candidates:
            # Base score: Premium per margin per day (daily return on capital)
            # This is more stable than theta-based scoring and naturally time-normalized
            premium = candidate['premium']
            dte = candidate['dte']
            strike = candidate['contract'].Strike
            margin_req = strike * 100 * ctx.algorithm.estimated_margin_pct
            
            if margin_req > 0 and dte > 0 and premium > 0:
                # Daily return on capital: premium / (margin * days)
                premium_per_day = premium / (margin_req * dte)
            else:
                premium_per_day = 0
            
            # Delta targeting: Strong preference for 18-25Δ range
            delta = abs(candidate.get('delta', 0.20))
            if 0.18 <= delta <= 0.25:
                delta_multiplier = 1.0  # Perfect range
            elif 0.15 <= delta < 0.18 or 0.25 < delta <= 0.28:
                delta_multiplier = 0.85  # Acceptable but not ideal
            else:
                delta_multiplier = 0.50  # Penalize heavily outside target
            
            # DTE targeting: Prefer 30-45 DTE range
            if 30 <= dte <= 45:
                dte_multiplier = 1.0  # Sweet spot
            elif 21 <= dte < 30 or 45 < dte <= 60:
                dte_multiplier = 0.90  # Acceptable
            else:
                dte_multiplier = 0.70  # Too short or too long
            
            # Spread quality: Penalize wide spreads (execution friction)
            spread_pct = candidate.get('spread_pct', 0)
            if spread_pct <= 0.05:
                spread_multiplier = 1.0
            elif spread_pct <= 0.10:
                spread_multiplier = 0.95
            else:
                spread_multiplier = 0.85
            
            # Expiry diversification: Mild penalty for crowded expiries
            book = ctx.algorithm.position_manager._positions_by_expiry()
            exp_key = candidate['contract'].Expiry.date() if hasattr(candidate['contract'].Expiry, 'date') else candidate['contract'].Expiry
            expiry_multiplier = 0.95 if len(book.get(exp_key, [])) > 0 else 1.0
            
            # Final score: Base efficiency × target matching
            final_score = (premium_per_day * 
                          delta_multiplier * 
                          dte_multiplier * 
                          spread_multiplier * 
                          expiry_multiplier)
            
            if final_score > best_score:
                best_score = final_score
                best_option = candidate
        
        return best_option

    def manage_positions(self, ctx: StrategyContext) -> List[ExitIntent]:
        """Theta strategy doesn't actively manage positions (uses exit rules)"""
        return []

    def desired_delta_policy(self, ctx: StrategyContext) -> HedgePolicy:
        """Theta strategy uses standard delta hedging"""
        return HedgePolicy(sizing_mode=ctx.algorithm.delta_sizing_mode)


