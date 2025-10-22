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
        self.underlying_prices = {}  # Track underlying prices by date
        
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
        
        # Get underlying price information
        underlying_info = self._get_underlying_price_info(option_positions, hedge_positions)
        
        explanation = {
            'date': date,
            'qc_portfolio_value': qc_portfolio_value,
            'underlying_info': underlying_info,
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
            
            # Get Greeks from position data (calculated/attributed greeks)
            delta = pos.get('delta_usd', 0) / (qty * 100) if qty != 0 else 0
            gamma = pos.get('gamma_usd', 0) / (qty * 100) if qty != 0 else 0
            theta = pos.get('theta_usd', 0) / qty if qty != 0 else 0
            vega = pos.get('vega_usd', 0) / qty if qty != 0 else 0
            
            # Get QC raw greeks for comparison
            qc_raw_greeks = self._get_qc_raw_greeks(symbol)
            
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
                },
                'qc_raw_greeks': qc_raw_greeks
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
    
    def _get_underlying_price_info(self, option_positions: List[Dict], hedge_positions: List[Dict]) -> Dict:
        """
        Get underlying price information including current price, previous day price, change, and change %.
        
        Returns:
            Dictionary with underlying price information by symbol
        """
        underlying_info = {}
        
        # Get underlyings from option positions
        for pos in option_positions:
            symbol = pos['symbol']
            if hasattr(symbol, 'Underlying'):
                underlying_symbol = symbol.Underlying
            else:
                # Try to extract underlying from hedge positions or algorithm
                continue
                
            if underlying_symbol not in underlying_info:
                current_price = self._get_current_underlying_price(underlying_symbol)
                previous_price = self._get_previous_underlying_price(underlying_symbol)
                
                price_change = current_price - previous_price if previous_price > 0 else 0
                price_change_pct = (price_change / previous_price * 100) if previous_price > 0 else 0
                
                underlying_info[underlying_symbol] = {
                    'current_price': current_price,
                    'previous_price': previous_price,
                    'price_change': price_change,
                    'price_change_pct': price_change_pct
                }
                
                # Store current price for next day
                date_key = self.algorithm.Time.date()
                if underlying_symbol not in self.underlying_prices:
                    self.underlying_prices[underlying_symbol] = {}
                self.underlying_prices[underlying_symbol][date_key] = current_price
        
        # Get underlyings from hedge positions
        for pos in hedge_positions:
            symbol = pos['symbol']
            if symbol not in underlying_info:
                current_price = self._get_current_underlying_price(symbol)
                previous_price = self._get_previous_underlying_price(symbol)
                
                price_change = current_price - previous_price if previous_price > 0 else 0
                price_change_pct = (price_change / previous_price * 100) if previous_price > 0 else 0
                
                underlying_info[symbol] = {
                    'current_price': current_price,
                    'previous_price': previous_price,
                    'price_change': price_change,
                    'price_change_pct': price_change_pct
                }
                
                # Store current price for next day
                date_key = self.algorithm.Time.date()
                if symbol not in self.underlying_prices:
                    self.underlying_prices[symbol] = {}
                self.underlying_prices[symbol][date_key] = current_price
        
        return underlying_info
    
    def _get_previous_underlying_price(self, symbol) -> float:
        """Get previous day's underlying price"""
        try:
            date_key = self.algorithm.Time.date()
            if symbol in self.underlying_prices:
                # Get the most recent price before today
                prices = self.underlying_prices[symbol]
                sorted_dates = sorted([d for d in prices.keys() if d < date_key], reverse=True)
                if sorted_dates:
                    return prices[sorted_dates[0]]
        except Exception:
            pass
        return 0.0
    
    # Helper methods for PnL calculations
    
    def _calculate_delta_pnl(self, delta: float, qty: int, price_change: float) -> float:
        """Calculate delta PnL: price_change × delta × quantity × 100"""
        if qty == 0:
            return 0.0
        return price_change * delta * qty * 100
    
    def _calculate_gamma_pnl(self, gamma: float, qty: int, price_change: float) -> float:
        """Calculate gamma PnL: 0.5 × (price_change)² × gamma × quantity × 100"""
        if qty == 0:
            return 0.0
        return 0.5 * (price_change ** 2) * gamma * qty * 100
    
    def _calculate_theta_pnl(self, theta: float, qty: int) -> float:
        """Calculate theta PnL: time_decay × theta × quantity"""
        # Assume 1 day of time decay
        if qty == 0:
            return 0.0
        return theta * qty
    
    def _calculate_vega_pnl(self, vega: float, qty: int) -> float:
        """Calculate vega PnL: vol_change × vega × quantity"""
        # This would need actual volatility change data
        # For now, return 0 as we don't have vol change tracking
        if qty == 0:
            return 0.0
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
    
    def _get_qc_raw_greeks(self, symbol) -> Dict:
        """
        Get QC raw greeks for comparison with calculated greeks.
        
        Returns:
            Dictionary with QC raw greeks and source information
        """
        try:
            # Try to get from Securities first (most direct QC source)
            if symbol in self.algorithm.Securities:
                security = self.algorithm.Securities[symbol]
                if hasattr(security, 'Greeks') and security.Greeks is not None:
                    greeks = security.Greeks
                    return {
                        'delta': float(greeks.Delta) if greeks.Delta is not None else 0.0,
                        'gamma': float(greeks.Gamma) if greeks.Gamma is not None else 0.0,
                        'theta': float(greeks.Theta) if greeks.Theta is not None else 0.0,
                        'vega': float(greeks.Vega) if hasattr(greeks, 'Vega') and greeks.Vega is not None else 0.0,
                        'source': 'QC-SECURITY'
                    }
            
            # Try cached greeks from options data manager
            if hasattr(self.algorithm, 'greeks_cache') and symbol in self.algorithm.greeks_cache:
                cached_data = self.algorithm.greeks_cache[symbol]
                if len(cached_data) >= 2:
                    greeks_tuple, timestamp = cached_data
                    if len(greeks_tuple) >= 4:
                        delta, gamma, theta, vega = greeks_tuple
                        return {
                            'delta': float(delta) if delta is not None else 0.0,
                            'gamma': float(gamma) if gamma is not None else 0.0,
                            'theta': float(theta) if theta is not None else 0.0,
                            'vega': float(vega) if vega is not None else 0.0,
                            'source': 'QC-CACHED'
                        }
                    elif len(greeks_tuple) >= 3:
                        delta, gamma, theta = greeks_tuple
                        return {
                            'delta': float(delta) if delta is not None else 0.0,
                            'gamma': float(gamma) if gamma is not None else 0.0,
                            'theta': float(theta) if theta is not None else 0.0,
                            'vega': 0.0,
                            'source': 'QC-CACHED'
                        }
            
            # Try options data manager if available
            if hasattr(self.algorithm, 'options_data'):
                try:
                    delta, delta_source = self.algorithm.options_data.get_delta(symbol)
                    gamma, gamma_source = self.algorithm.options_data.get_gamma(symbol)
                    theta, theta_source = self.algorithm.options_data.get_theta(symbol)
                    vega, vega_source = self.algorithm.options_data.get_vega(symbol)
                    
                    return {
                        'delta': float(delta) if delta is not None else 0.0,
                        'gamma': float(gamma) if gamma is not None else 0.0,
                        'theta': float(theta) if theta is not None else 0.0,
                        'vega': float(vega) if vega is not None else 0.0,
                        'source': f'QC-{delta_source}'
                    }
                except Exception:
                    pass
                    
        except Exception:
            pass
        
        # Return zeros if no QC greeks available
        return {
            'delta': 0.0,
            'gamma': 0.0,
            'theta': 0.0,
            'vega': 0.0,
            'source': 'QC-NONE'
        }
    
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
        total_abs_pnl = sum(abs(p.get('total_pnl', 0)) for p in positions)
        
        return {
            'symbol': largest.get('symbol', ''),
            'pnl': largest.get('total_pnl', 0),
            'pnl_pct': (largest.get('total_pnl', 0) / total_abs_pnl * 100) if total_abs_pnl > 0 else 0
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
        report.append("=" * 60)
        report.append(f"PnL EXPLANATION REPORT - {date.strftime('%Y-%m-%d')}")
        report.append("=" * 60)
        
        # Underlying price information
        underlying_info = explanation.get('underlying_info', {})
        if underlying_info:
            for symbol, info in underlying_info.items():
                symbol_str = str(symbol) if hasattr(symbol, '__str__') else 'QQQ'
                current = info['current_price']
                previous = info['previous_price']
                change = info['price_change']
                change_pct = info['price_change_pct']
                report.append(f"UNDERLYING {symbol_str}: ${current:.2f} | Prev: ${previous:.2f} | Change: ${change:+.2f} ({change_pct:+.2f}%)")
        
        # QC Reconciliation (condensed)
        qc_rec = explanation['qc_reconciliation']
        report.append(f"QC: ${qc_rec['qc_portfolio_value']:,.0f} | Attributed: ${qc_rec['attributed_pnl']:,.0f} | Var: ${qc_rec['variance']:,.0f} ({qc_rec['variance_pct']:.1f}%) | {qc_rec['reconciliation_quality']}")
        
        # Option PnL breakdown (condensed with prices)
        opt_pnl = explanation['option_pnl']
        report.append(f"OPTIONS: Total=${opt_pnl['total_pnl']:,.0f} | Δ=${opt_pnl['total_delta_pnl']:,.0f} | Γ=${opt_pnl['total_gamma_pnl']:,.0f} | Θ=${opt_pnl['total_theta_pnl']:,.0f} | ν=${opt_pnl['total_vega_pnl']:,.0f}")
        
        # Individual option positions with entry/current prices and QC raw greeks
        if opt_pnl['positions']:
            for pos in opt_pnl['positions']:
                entry_price = pos.get('entry_price', 0)
                current_price = pos.get('current_price', 0)
                price_change = pos.get('price_change', 0)
                
                # Get QC raw greeks for comparison
                qc_raw = pos.get('qc_raw_greeks', {})
                qc_delta = qc_raw.get('delta', 0.0)
                qc_gamma = qc_raw.get('gamma', 0.0)
                qc_theta = qc_raw.get('theta', 0.0)
                qc_vega = qc_raw.get('vega', 0.0)
                qc_source = qc_raw.get('source', 'N/A')
                
                # Get calculated greeks for comparison
                calc_delta = pos.get('greeks', {}).get('delta', 0.0)
                calc_gamma = pos.get('greeks', {}).get('gamma', 0.0)
                calc_theta = pos.get('greeks', {}).get('theta', 0.0)
                calc_vega = pos.get('greeks', {}).get('vega', 0.0)
                
                report.append(f"  {pos['symbol']}: ${pos['total_pnl']:,.0f} | Entry: ${entry_price:.2f} → Current: ${current_price:.2f} (Δ${price_change:.2f}) | Δ=${pos['delta_pnl']:,.0f} Γ=${pos['gamma_pnl']:,.0f} Θ=${pos['theta_pnl']:,.0f}")
                report.append(f"    QC Raw: Δ={qc_delta:.4f} Γ={qc_gamma:.6f} Θ={qc_theta:.6f} ν={qc_vega:.6f} ({qc_source})")
                report.append(f"    Calc'd: Δ={calc_delta:.4f} Γ={calc_gamma:.6f} Θ={calc_theta:.6f} ν={calc_vega:.6f}")
        
        # Hedge PnL breakdown (condensed)
        hedge_pnl = explanation['hedge_pnl']
        if hedge_pnl['total_pnl'] != 0 or hedge_pnl['positions']:
            report.append(f"HEDGES: Total=${hedge_pnl['total_pnl']:,.0f} | Price=${hedge_pnl['total_price_pnl']:,.0f} | Div=${hedge_pnl['total_dividend_pnl']:,.0f} | Cost=${hedge_pnl['total_borrowing_cost']:,.0f}")
            
            # Individual hedge positions with entry/current prices
            if hedge_pnl['positions']:
                for pos in hedge_pnl['positions']:
                    entry_price = pos.get('entry_price', 0)
                    current_price = pos.get('current_price', 0)
                    price_change = pos.get('price_change', 0)
                    report.append(f"  {pos['symbol']}: ${pos['total_pnl']:,.0f} | Entry: ${entry_price:.2f} → Current: ${current_price:.2f} (Δ${price_change:.2f}) | Price=${pos['price_pnl']:,.0f}")
        
        # Summary (condensed)
        total_attributed = explanation['total_attributed_pnl']
        
        if abs(total_attributed) > 0.01:
            opt_contrib = opt_pnl['total_pnl'] / total_attributed * 100
            hedge_contrib = hedge_pnl['total_pnl'] / total_attributed * 100
            report.append(f"TOTAL: ${total_attributed:,.0f} | Options: {opt_contrib:.0f}% | Hedges: {hedge_contrib:.0f}%")
        else:
            report.append(f"TOTAL: ${total_attributed:,.0f} | No PnL attribution")
        
        report.append("=" * 60)
        
        return "\n".join(report)
