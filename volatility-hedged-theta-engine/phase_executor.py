"""
Phase Executor - Handles P0/P1/P2 execution flow

This module extracts the phase execution logic from main.py to keep
the main algorithm file focused on orchestration only.
"""

from strategy_base import StrategyContext


class PhaseExecutor:
    """Handles the execution of P0 (Exits), P1 (New Trades + Hedges), and P2 (Portfolio Rebalancing)"""
    
    def __init__(self, algorithm):
        """
        Initialize the phase executor
        
        Args:
            algorithm: The main QCAlgorithm instance
        """
        self.algorithm = algorithm
        self.debug_mode = algorithm.debug_mode
    
    def execute_phase_0_exits(self):
        """
        PHASE 0 (15:45): Process exits to free up margin before new trades
        Always manage risk before taking new positions
        """
        if self.debug_mode:
            self.algorithm.Debug("=== P0: EXITS ===")
        
        # Handle exits first - always manage risk before new positions
        if self.algorithm.risk_manager:
            self.algorithm.risk_manager.manage_exits()
        
        if self.debug_mode:
            self.algorithm.Debug("P0 COMPLETE")
    
    def execute_phase_1_trades_and_hedges(self):
        """
        PHASE 1 (15:50): Strategy evaluation, new trades, and per-trade hedges
        
        Subdivided into:
        - P1A: Strategy evaluation and candidate selection
        - P1B: Margin analysis and capacity check
        - P1C: Execute new option trades
        - P1D: Execute per-trade hedges (if TRADE bands enabled)
        """
        # Clear today's new trades cache at start of phase 1
        self.algorithm.todays_new_trades = []
        self.algorithm.todays_new_trade_deltas = []
        
        # === P1A: STRATEGY EVALUATION ===
        if self.debug_mode:
            self.algorithm.Debug("=== P1A: STRATEGY EVAL ===")
        
        new_trade_intents = self._evaluate_strategy()
        
        if self.debug_mode:
            self.algorithm.Debug(f"P1A: Strategy selected {len(new_trade_intents)} BEST option(s) from filtered candidates")
        
        # === P1B: MARGIN ANALYSIS ===
        if self.debug_mode:
            self.algorithm.Debug("=== P1B: MARGIN ANALYSIS ===")
        
        self.algorithm._refresh_margin_values()
        can_add_positions = self.algorithm._analyze_margin_capacity()
        
        # === P1C: NEW OPTION TRADES ===
        if self.debug_mode:
            self.algorithm.Debug("=== P1C: NEW OPTION TRADES ===")
        
        new_trades_executed = self._execute_new_trades(new_trade_intents, can_add_positions)
        
        # === P1D: PER-TRADE HEDGES ===
        if self.debug_mode:
            self.algorithm.Debug("=== P1D: HEDGES ===")
        
        if new_trades_executed:
            self.algorithm.todays_new_trades.extend(new_trades_executed)
            self.algorithm._execute_new_trade_hedges(new_trades_executed)
            if self.debug_mode:
                self.algorithm.Debug(f"P1 COMPLETE: {len(new_trades_executed)} trades + hedges")
    
    def execute_phase_2_portfolio_rebalancing(self):
        """
        PHASE 2 (15:55): Portfolio-wide delta rebalancing
        
        Subdivided into:
        - P2A: Portfolio state analysis and delta calculation
        - P2B: Portfolio rebalancing (hedge underlying or reduce options)
        """
        if self.debug_mode:
            self.algorithm.Debug("=== P2: PORTFOLIO REBALANCING ===")
        
        # === PHASE 2A: PORTFOLIO ANALYSIS ===
        self.algorithm._analyze_portfolio_state()
        
        # === PHASE 2B: PORTFOLIO REBALANCING ===
        self.algorithm._execute_portfolio_rebalancing()
        
        if self.debug_mode:
            self.algorithm.Debug("P2 COMPLETE")
    
    def _evaluate_strategy(self):
        """
        P1A: Run strategy evaluation to select entry candidates
        
        Returns:
            List of EntryIntent objects from the strategy
        """
        new_trade_intents = []
        
        if (hasattr(self.algorithm, 'current_chain') and 
            self.algorithm.current_chain is not None and 
            self.algorithm.strategy):
            
            ctx = StrategyContext(
                algorithm=self.algorithm,
                time=self.algorithm.Time,
                portfolio_value=self.algorithm.Portfolio.TotalPortfolioValue,
                underlying_symbol=self.algorithm.underlying_symbol,
                config={}
            )
            new_trade_intents = self.algorithm.strategy.select_entries(
                self.algorithm.current_chain, ctx
            )
        
        return new_trade_intents
    
    def _execute_new_trades(self, new_trade_intents, can_add_positions):
        """
        P1C: Execute new option trades
        
        Args:
            new_trade_intents: List of EntryIntent objects from strategy
            can_add_positions: Boolean indicating if margin allows new positions
        
        Returns:
            List of successfully executed EntryIntent objects
        """
        new_trades_executed = []
        
        if not can_add_positions or not new_trade_intents:
            return new_trades_executed
        
        # Count active option positions (exclude hedges)
        active_positions = sum(
            1 for p in self.algorithm.positions.values()
            if abs(p.get('quantity', 0)) != 0 and not p.get('is_hedge', False)
        )
        
        if active_positions < self.algorithm.max_positions:
            for intent in new_trade_intents:
                # Log OPTION SELECTED in P1C section BEFORE execution
                self.algorithm._log_option_selected_from_intent(intent)
                
                if self.algorithm.order_manager:
                    result = self.algorithm._execute_single_trade(intent)
                    if result:
                        new_trades_executed.append(intent)
        else:
            if self.debug_mode:
                self.algorithm.Debug(
                    f"P1C: Max positions reached ({active_positions}/{self.algorithm.max_positions})"
                )
        
        return new_trades_executed

