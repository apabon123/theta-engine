"""
Black-Scholes Module for Theta Engine

This module provides Black-Scholes calculations for option pricing and Greeks estimation.
Used when actual Greeks are not available from the data provider.
"""

from AlgorithmImports import *
import math


class BlackScholesCalculator:
    """Black-Scholes calculations for options pricing and Greeks"""

    def __init__(self, algorithm):
        self.algorithm = algorithm

    def estimate_put_delta(self, strike, underlying_price, expiration_date):
        """
        Enhanced delta estimation for put options using Black-Scholes approximation
        when actual Greeks are not available.
        """
        try:
            # Calculate time to expiration in years - safe datetime handling
            expiry_date = expiration_date.date() if hasattr(expiration_date, 'date') else expiration_date
            current_date = self.algorithm.Time.date() if hasattr(self.algorithm.Time, 'date') else self.algorithm.Time
            dte = (expiry_date - current_date).days
            if dte <= 0:
                return 0.0

            time_to_expiry = dte / 365.0

            # Calculate moneyness ratio
            moneyness_ratio = strike / underlying_price

            # Estimate implied volatility based on moneyness and time to expiry
            # This is a rough approximation - in practice you'd use market data
            atm_iv = 0.25  # Base ATM implied volatility
            vol_adjustment = 0.05 * abs(math.log(moneyness_ratio))  # Higher for OTM options
            time_adjustment = 0.02 * math.sqrt(time_to_expiry)  # Higher for longer dated options
            estimated_iv = atm_iv + vol_adjustment + time_adjustment

            # Black-Scholes approximation for put delta
            # d1 = [ln(S/K) + (r + σ²/2)T] / (σ√T)
            # Put delta = -N(-d1)

            # Estimate risk-free rate (could be made more sophisticated)
            risk_free_rate = 0.045  # 4.5% as default

            # Calculate d1
            ln_ratio = math.log(underlying_price / strike)
            numerator = ln_ratio + (risk_free_rate + 0.5 * estimated_iv**2) * time_to_expiry
            denominator = estimated_iv * math.sqrt(time_to_expiry)

            if denominator == 0:
                return 0.0

            d1 = numerator / denominator

            # Standard normal CDF approximation for put delta
            # Put delta = -N(-d1) = -[1 - N(d1)]
            put_delta = -self._normal_cdf(-d1)

            # Apply bounds and sanity checks
            put_delta = max(-1.0, min(0.0, put_delta))  # Put delta should be between -1 and 0

            return put_delta

        except Exception as e:
            self.algorithm.Debug(f"Error in Black-Scholes delta estimation: {e}")
            return 0.0

    def _normal_cdf(self, x):
        """Abramowitz & Stegun approximation for standard normal CDF"""
        if x < 0:
            cdf = 1.0 - self._normal_cdf(-x)
        else:
            # Constants for approximation
            a1 =  0.254829592
            a2 = -0.284496736
            a3 =  1.421413741
            a4 = -1.453152027
            a5 =  1.061405429
            p  =  0.3275911

            # A&S formula 7.1.26
            t = 1.0 / (1.0 + p * x)
            cdf = 1.0 - (a1*t + a2*t*t + a3*t*t*t + a4*t*t*t*t + a5*t*t*t*t*t) * math.exp(-x*x/2.0)

        return cdf

    def calculate_option_price(self, strike, underlying_price, expiration_date, option_type='put'):
        """
        Calculate theoretical option price using Black-Scholes
        """
        try:
            # Time to expiration in years - safe datetime handling
            expiry_date = expiration_date.date() if hasattr(expiration_date, 'date') else expiration_date
            current_date = self.algorithm.Time.date() if hasattr(self.algorithm.Time, 'date') else self.algorithm.Time
            dte = (expiry_date - current_date).days
            time_to_expiry = max(dte / 365.0, 0.001)

            # Risk-free rate and volatility (simplified)
            risk_free_rate = 0.045
            volatility = 0.25

            # Black-Scholes calculations
            ln_ratio = math.log(underlying_price / strike)
            d1 = (ln_ratio + (risk_free_rate + 0.5 * volatility**2) * time_to_expiry) / (volatility * math.sqrt(time_to_expiry))
            d2 = d1 - volatility * math.sqrt(time_to_expiry)

            if option_type.lower() == 'call':
                price = underlying_price * self._normal_cdf(d1) - strike * math.exp(-risk_free_rate * time_to_expiry) * self._normal_cdf(d2)
            else:  # put
                price = strike * math.exp(-risk_free_rate * time_to_expiry) * self._normal_cdf(-d2) - underlying_price * self._normal_cdf(-d1)

            return max(price, 0.0)

        except Exception as e:
            self.algorithm.Debug(f"Error calculating option price: {e}")
            return 0.0

    def estimate_gamma(self, strike, underlying_price, expiration_date):
        """
        Estimate option gamma using Black-Scholes
        """
        try:
            # Safe datetime handling
            expiry_date = expiration_date.date() if hasattr(expiration_date, 'date') else expiration_date
            current_date = self.algorithm.Time.date() if hasattr(self.algorithm.Time, 'date') else self.algorithm.Time
            dte = (expiry_date - current_date).days
            time_to_expiry = max(dte / 365.0, 0.001)
            volatility = 0.25
            risk_free_rate = 0.045

            ln_ratio = math.log(underlying_price / strike)
            d1 = (ln_ratio + (risk_free_rate + 0.5 * volatility**2) * time_to_expiry) / (volatility * math.sqrt(time_to_expiry))

            # Gamma formula: N'(d1) / (S * σ * √T)
            gamma = self._normal_pdf(d1) / (underlying_price * volatility * math.sqrt(time_to_expiry))

            return gamma

        except Exception as e:
            self.algorithm.Debug(f"Error estimating gamma: {e}")
            return 0.0

    def _normal_pdf(self, x):
        """Standard normal probability density function"""
        return math.exp(-x*x/2.0) / math.sqrt(2.0 * math.pi)
