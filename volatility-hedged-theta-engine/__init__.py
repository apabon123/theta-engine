"""
Theta Engine Modules Package

This package contains modular components for the Theta Engine strategy:
- delta_hedging: Universal delta hedging for equity and futures options
- black_scholes: Black-Scholes calculations and Greeks estimation
- exit_rules: Exit conditions and position management
- execution_modes: EOD vs Intraday execution logic
- position_management: Position sizing and entry logic
"""

from .delta_hedging import DeltaHedger
from .black_scholes import BlackScholesCalculator
from .exit_rules import ExitRulesManager
from .execution_modes import ExecutionModeManager
from .position_management import PositionManager

__all__ = [
    'DeltaHedger',
    'BlackScholesCalculator',
    'ExitRulesManager',
    'ExecutionModeManager',
    'PositionManager'
]
