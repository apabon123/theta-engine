"""
PnL Explainer Module

Provides detailed PnL attribution analysis for options and hedge positions.
Compares internal calculations with QuantConnect's portfolio values.

Features:
- Option PnL breakdown by Greeks (Delta, Gamma, Theta, Vega)
- Hedge PnL breakdown by price movement
- QuantConnect reconciliation and variance analysis
- Daily PnL attribution and performance metrics
"""

from AlgorithmImports import *
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta
import pandas as pd


class PnLExplainer:
    """
    Comprehensive PnL attribution and explanation system.
    
    Analyzes daily PnL for:
    1. Option positions (Greeks-based attribution)
    2. Hedge positions (price movement attribution) 
    3. QuantConnect reconciliation
    4. Performance metrics and variance analysis
    """
    
    def __init__(self, algorithm):
        self.algorithm = algorithm
        self.daily_pnl_history = []
        self.position_snapshots = {}
        
    def explain_daily_pnl(self, date: datetime, option_positions: List[Dict], 
                         hedge_positions: List[Dict], qc_portfolio_value: float) -> Dict:
        """
        Generate comprehensive PnL explanation for a given date.
        
        Args:
            date: Trading date
            option_positions: List of option position dictionaries
            hedge_positions: List of hedge position dictionaries  
            qc_portfolio_value: QuantConnect portfolio value
            
        Returns:
            Dictionary with detailed PnL attribution
        """
        
        explanation = {
            'date': date,
            'qc_portfolio_value': qc_portfolio_value,
            'option_pnl': self._analyze_option_pnl(option_positions),
            'hedge_pnl': self._analyze_hedge_pnl(hedge_positions),
            'total_attributed_pnl': 0.0,
            'qc_reconciliation': {},
            'performance_metrics': {}
        }
        
        # Calculate total attributed PnL
        explanation['total_attributed_pnl'] = (
            explanation['option_pnl']['total_pnl'] + 
            explanation['hedge_pnl']['total_pnl']
        )
        
        # Reconcile with QuantConnect
        explanation['qc_reconciliation'] = self._reconcile_with_qc(
            explanation['total_attributed_pnl'], 
            qc_portfolio_value,
            date
        )
        
        # Calculate performance metrics
        explanation['performance_metrics'] = self._calculate_performance_metrics(
            explanation, date
        )
        
        # Store for historical analysis
        self.daily_pnl_history.append(explanation)
        
        return explanation
    
    def _analyze_option_pnl(self, option_positions: List[Dict]) -> Dict:
        """
        Analyze option PnL using Greeks attribution.
        
        For each option position:
        - Delta PnL: Change in underlying price × delta × quantity
        - Gamma PnL: 0.5 × (price_change)² × gamma × quantity  
        - Theta PnL: Time decay × theta × quantity
        - Vega PnL: Volatility change × vega × quantity
        """
        
        option_analysis = {
            'positions': [],
            'total_delta_pnl': 0.0,
            'total_gamma_pnl': 0.0, 
            'total_theta_pnl': 0.0,
            'total_vega_pnl': 0.0,
            'total_pnl': 0.0,
            'summary': {}
        }
        
        for pos in option_positions:
            symbol = pos['symbol']
            qty = pos['quantity']
            entry_price = pos.get('entry_price', 0)
            current_price = self._get_current_option_price(symbol)
            
            # Get Greeks from position data
            delta = pos.get('delta_usd', 0) / (qty * 100) if qty != 0 else 0
            gamma = pos.get('gamma_usd', 0) / (qty * 100) if qty != 0 else 0
            theta = pos.get('theta_usd', 0) / qty if qty != 0 else 0
            vega = pos.get('vega_usd', 0) / qty if qty != 0 else 0
            
            # Calculate price changes
            price_change = current_price - entry_price if entry_price > 0 else 0
            
            # Greeks attribution
            delta_pnl = self._calculate_delta_pnl(delta, qty, price_change)
            gamma_pnl = self._calculate_gamma_pnl(gamma, qty, price_change)
            theta_pnl = self._calculate_theta_pnl(theta, qty)
            vega_pnl = self._calculate_vega_pnl(vega, qty)
            
            position_pnl = delta_pnl + gamma_pnl + theta_pnl + vega_pnl
            
            position_analysis = {
                'symbol': symbol,
                'quantity': qty,
                'entry_price': entry_price,
                'current_price': current_price,
                'price_change': price_change,
                'delta_pnl': delta_pnl,
                'gamma_pnl': gamma_pnl,
                'theta_pnl': theta_pnl,
                'vega_pnl': vega_pnl,
                'total_pnl': position_pnl,
                'greeks': {
                    'delta': delta,
                    'gamma': gamma,
                    'theta': theta,
                    'vega': vega
                }
            }
            
            option_analysis['positions'].append(position_analysis)
            option_analysis['total_delta_pnl'] += delta_pnl
            option_analysis['total_gamma_pnl'] += gamma_pnl
            option_analysis['total_theta_pnl'] += theta_pnl
            option_analysis['total_vega_pnl'] += vega_pnl
            option_analysis['total_pnl'] += position_pnl
        
        # Generate summary
        option_analysis['summary'] = {
            'total_positions': len(option_positions),
            'net_delta_exposure': sum(pos['delta_usd'] for pos in option_positions),
            'net_gamma_exposure': sum(pos['gamma_usd'] for pos in option_positions),
            'net_theta_exposure': sum(pos['theta_usd'] for pos in option_positions),
            'net_vega_exposure': sum(pos['vega_usd'] for pos in option_positions),
            'largest_contributor': self._find_largest_pnl_contributor(option_analysis['positions']),
            'theta_decay_benefit': option_analysis['total_theta_pnl'] > 0
        }
        
        return option_analysis
    
    def _analyze_hedge_pnl(self, hedge_positions: List[Dict]) -> Dict:
        """
        Analyze hedge PnL using price movement attribution.
        
        For each hedge position:
        - Price PnL: Change in underlying price × quantity
        - Dividend PnL: Dividend payments (if applicable)
        - Borrowing costs: Short selling costs (if applicable)
        """
        
        hedge_analysis = {
            'positions': [],
            'total_price_pnl': 0.0,
            'total_dividend_pnl': 0.0,
            'total_borrowing_cost': 0.0,
            'total_pnl': 0.0,
            'summary': {}
        }
        
        for pos in hedge_positions:
            symbol = pos['symbol']
            qty = pos['quantity']
            entry_price = pos.get('entry_price', 0)
            current_price = self._get_current_underlying_price(symbol)
            
            # Calculate price-based PnL
            price_change = current_price - entry_price if entry_price > 0 else 0
            price_pnl = price_change * qty
            
            # Calculate additional costs/benefits
            dividend_pnl = self._calculate_dividend_pnl(symbol, qty)
            borrowing_cost = self._calculate_borrowing_cost(symbol, qty)
            
            position_pnl = price_pnl + dividend_pnl - borrowing_cost
            
            position_analysis = {
                'symbol': symbol,
                'quantity': qty,
                'entry_price': entry_price,
                'current_price': current_price,
                'price_change': price_change,
                'price_pnl': price_pnl,
                'dividend_pnl': dividend_pnl,
                'borrowing_cost': borrowing_cost,
                'total_pnl': position_pnl
            }
            
            hedge_analysis['positions'].append(position_analysis)
            hedge_analysis['total_price_pnl'] += price_pnl
            hedge_analysis['total_dividend_pnl'] += dividend_pnl
            hedge_analysis['total_borrowing_cost'] += borrowing_cost
            hedge_analysis['total_pnl'] += position_pnl
        
        # Generate summary
        hedge_analysis['summary'] = {
            'total_positions': len(hedge_positions),
            'net_exposure': sum(pos['quantity'] for pos in hedge_positions),
            'hedge_effectiveness': self._calculate_hedge_effectiveness(hedge_analysis),
            'largest_contributor': self._find_largest_pnl_contributor(hedge_analysis['positions'])
        }
        
        return hedge_analysis
    
    def _reconcile_with_qc(self, attributed_pnl: float, qc_value: float, date: datetime) -> Dict:
        """
        Reconcile attributed PnL with QuantConnect's portfolio value.
        
        Calculates:
        - Variance between attributed and QC values
        - Percentage difference
        - Historical variance trends
        - Potential sources of discrepancy
        """
        
        # Get previous day's QC value for comparison
        previous_qc_value = self._get_previous_qc_value(date)
        qc_daily_pnl = qc_value - previous_qc_value if previous_qc_value else 0
        
        variance = attributed_pnl - qc_daily_pnl
        variance_pct = (variance / abs(qc_daily_pnl) * 100) if qc_daily_pnl != 0 else 0
        
        reconciliation = {
            'qc_daily_pnl': qc_daily_pnl,
            'attributed_pnl': attributed_pnl,
            'variance': variance,
            'variance_pct': variance_pct,
            'qc_portfolio_value': qc_value,
            'previous_qc_value': previous_qc_value,
            'reconciliation_quality': self._assess_reconciliation_quality(variance_pct),
            'potential_discrepancies': self._identify_discrepancy_sources(variance, date)
        }
        
        return reconciliation
    
    def _calculate_performance_metrics(self, explanation: Dict, date: datetime) -> Dict:
        """
        Calculate performance metrics and attribution quality.
        
        Metrics:
        - Attribution accuracy (how well Greeks explain PnL)
        - Hedge effectiveness (correlation with option delta)
        - Risk-adjusted returns
        - Greeks utilization efficiency
        """
        
        metrics = {
            'attribution_accuracy': self._calculate_attribution_accuracy(explanation),
            'hedge_effectiveness': self._calculate_hedge_effectiveness_metrics(explanation),
            'risk_metrics': self._calculate_risk_metrics(explanation),
            'greeks_efficiency': self._calculate_greeks_efficiency(explanation),
            'daily_performance': self._calculate_daily_performance(explanation, date)
        }
        
        return metrics
    
    # Helper methods for PnL calculations
    
    def _calculate_delta_pnl(self, delta: float, qty: int, price_change: float) -> float:
        """Calculate delta PnL: price_change × delta × quantity × 100"""
        return price_change * delta * qty * 100
    
    def _calculate_gamma_pnl(self, gamma: float, qty: int, price_change: float) -> float:
        """Calculate gamma PnL: 0.5 × (price_change)² × gamma × quantity × 100"""
        return 0.5 * (price_change ** 2) * gamma * qty * 100
    
    def _calculate_theta_pnl(self, theta: float, qty: int) -> float:
        """Calculate theta PnL: time_decay × theta × quantity"""
        # Assume 1 day of time decay
        return theta * qty
    
    def _calculate_vega_pnl(self, vega: float, qty: int) -> float:
        """Calculate vega PnL: vol_change × vega × quantity"""
        # This would need actual volatility change data
        # For now, return 0 as we don't have vol change tracking
        return 0.0
    
    def _get_current_option_price(self, symbol) -> float:
        """Get current option price from QuantConnect"""
        try:
            if symbol in self.algorithm.Securities:
                return float(self.algorithm.Securities[symbol].Price)
        except Exception:
            pass
        return 0.0
    
    def _get_current_underlying_price(self, symbol) -> float:
        """Get current underlying price from QuantConnect"""
        try:
            if symbol in self.algorithm.Securities:
                return float(self.algorithm.Securities[symbol].Price)
        except Exception:
            pass
        return 0.0
    
    def _get_previous_qc_value(self, date: datetime) -> Optional[float]:
        """Get previous day's QuantConnect portfolio value"""
        # This would need to be stored from previous days
        # For now, return None
        return None
    
    def _calculate_dividend_pnl(self, symbol, qty: int) -> float:
        """Calculate dividend PnL for hedge positions"""
        # This would need dividend data
        return 0.0
    
    def _calculate_borrowing_cost(self, symbol, qty: int) -> float:
        """Calculate borrowing costs for short positions"""
        # This would need borrowing rate data
        return 0.0
    
    def _find_largest_pnl_contributor(self, positions: List[Dict]) -> Dict:
        """Find the position with largest PnL contribution"""
        if not positions:
            return {}
        
        largest = max(positions, key=lambda p: abs(p.get('total_pnl', 0)))
        return {
            'symbol': largest.get('symbol', ''),
            'pnl': largest.get('total_pnl', 0),
            'pnl_pct': largest.get('total_pnl', 0) / sum(abs(p.get('total_pnl', 0)) for p in positions) * 100 if positions else 0
        }
    
    def _calculate_hedge_effectiveness(self, hedge_analysis: Dict) -> float:
        """Calculate hedge effectiveness (correlation with option delta)"""
        # This would need historical correlation analysis
        return 0.0
    
    def _assess_reconciliation_quality(self, variance_pct: float) -> str:
        """Assess quality of reconciliation with QC"""
        if abs(variance_pct) < 1:
            return "EXCELLENT"
        elif abs(variance_pct) < 5:
            return "GOOD"
        elif abs(variance_pct) < 10:
            return "FAIR"
        else:
            return "POOR"
    
    def _identify_discrepancy_sources(self, variance: float, date: datetime) -> List[str]:
        """Identify potential sources of PnL discrepancies"""
        sources = []
        
        if abs(variance) > 1000:  # Large variance
            sources.append("Large variance suggests missing attribution factors")
        
        if variance > 0:
            sources.append("Attributed PnL higher than QC - possible double counting")
        else:
            sources.append("Attributed PnL lower than QC - possible missing factors")
        
        return sources
    
    def _calculate_attribution_accuracy(self, explanation: Dict) -> float:
        """Calculate how well Greeks explain the PnL"""
        # This would need historical analysis
        return 0.0
    
    def _calculate_hedge_effectiveness_metrics(self, explanation: Dict) -> Dict:
        """Calculate hedge effectiveness metrics"""
        return {
            'delta_hedge_ratio': 0.0,
            'correlation': 0.0,
            'effectiveness_score': 0.0
        }
    
    def _calculate_risk_metrics(self, explanation: Dict) -> Dict:
        """Calculate risk-adjusted performance metrics"""
        return {
            'var_95': 0.0,
            'max_drawdown': 0.0,
            'sharpe_ratio': 0.0
        }
    
    def _calculate_greeks_efficiency(self, explanation: Dict) -> Dict:
        """Calculate Greeks utilization efficiency"""
        return {
            'theta_efficiency': 0.0,
            'vega_efficiency': 0.0,
            'gamma_efficiency': 0.0
        }
    
    def _calculate_daily_performance(self, explanation: Dict, date: datetime) -> Dict:
        """Calculate daily performance metrics"""
        return {
            'total_return': 0.0,
            'attributed_return': 0.0,
            'unattributed_return': 0.0
        }
    
    def generate_pnl_report(self, date: datetime) -> str:
        """
        Generate a comprehensive PnL explanation report.
        
        Returns:
            Formatted string with detailed PnL attribution
        """
        
        # Find the explanation for the given date
        explanation = None
        for exp in self.daily_pnl_history:
            if exp['date'].date() == date.date():
                explanation = exp
                break
        
        if not explanation:
            return f"No PnL explanation found for {date.date()}"
        
        report = []
        report.append("=" * 80)
        report.append(f"PnL EXPLANATION REPORT - {date.strftime('%Y-%m-%d')}")
        report.append("=" * 80)
        
        # QC Reconciliation
        qc_rec = explanation['qc_reconciliation']
        report.append(f"\n📊 QUANTCONNECT RECONCILIATION:")
        report.append(f"  QC Portfolio Value: ${qc_rec['qc_portfolio_value']:,.2f}")
        report.append(f"  QC Daily PnL: ${qc_rec['qc_daily_pnl']:,.2f}")
        report.append(f"  Attributed PnL: ${qc_rec['attributed_pnl']:,.2f}")
        report.append(f"  Variance: ${qc_rec['variance']:,.2f} ({qc_rec['variance_pct']:.1f}%)")
        report.append(f"  Quality: {qc_rec['reconciliation_quality']}")
        
        # Option PnL Breakdown
        opt_pnl = explanation['option_pnl']
        report.append(f"\n📈 OPTION PnL BREAKDOWN:")
        report.append(f"  Total Option PnL: ${opt_pnl['total_pnl']:,.2f}")
        report.append(f"  Delta PnL: ${opt_pnl['total_delta_pnl']:,.2f}")
        report.append(f"  Gamma PnL: ${opt_pnl['total_gamma_pnl']:,.2f}")
        report.append(f"  Theta PnL: ${opt_pnl['total_theta_pnl']:,.2f}")
        report.append(f"  Vega PnL: ${opt_pnl['total_vega_pnl']:,.2f}")
        
        # Individual Option Positions
        if opt_pnl['positions']:
            report.append(f"\n  Individual Option Positions:")
            for pos in opt_pnl['positions']:
                report.append(f"    {pos['symbol']}: ${pos['total_pnl']:,.2f}")
                report.append(f"      Delta: ${pos['delta_pnl']:,.2f}, Gamma: ${pos['gamma_pnl']:,.2f}")
                report.append(f"      Theta: ${pos['theta_pnl']:,.2f}, Vega: ${pos['vega_pnl']:,.2f}")
        
        # Hedge PnL Breakdown
        hedge_pnl = explanation['hedge_pnl']
        report.append(f"\n🛡️ HEDGE PnL BREAKDOWN:")
        report.append(f"  Total Hedge PnL: ${hedge_pnl['total_pnl']:,.2f}")
        report.append(f"  Price PnL: ${hedge_pnl['total_price_pnl']:,.2f}")
        report.append(f"  Dividend PnL: ${hedge_pnl['total_dividend_pnl']:,.2f}")
        report.append(f"  Borrowing Cost: ${hedge_pnl['total_borrowing_cost']:,.2f}")
        
        # Individual Hedge Positions
        if hedge_pnl['positions']:
            report.append(f"\n  Individual Hedge Positions:")
            for pos in hedge_pnl['positions']:
                report.append(f"    {pos['symbol']}: ${pos['total_pnl']:,.2f}")
                report.append(f"      Price PnL: ${pos['price_pnl']:,.2f}")
        
        # Performance Metrics
        metrics = explanation['performance_metrics']
        report.append(f"\n📊 PERFORMANCE METRICS:")
        report.append(f"  Attribution Accuracy: {metrics['attribution_accuracy']:.1f}%")
        report.append(f"  Hedge Effectiveness: {metrics['hedge_effectiveness']['effectiveness_score']:.1f}%")
        
        # Summary
        report.append(f"\n📋 SUMMARY:")
        report.append(f"  Total Attributed PnL: ${explanation['total_attributed_pnl']:,.2f}")
        report.append(f"  Option Contribution: {opt_pnl['total_pnl']/explanation['total_attributed_pnl']*100:.1f}%")
        report.append(f"  Hedge Contribution: {hedge_pnl['total_pnl']/explanation['total_attributed_pnl']*100:.1f}%")
        
        report.append("=" * 80)
        
        return "\n".join(report)
