"""
Strategy plug-in interface and intent/context types for the Theta Engine.
"""

from AlgorithmImports import *  # noqa: F401
from dataclasses import dataclass
from typing import List, Optional, Any, Dict


@dataclass
class StrategyContext:
    algorithm: Any
    time: datetime
    portfolio_value: float
    underlying_symbol: Symbol
    config: Dict[str, Any]


@dataclass
class EntryIntent:
    # Candidate is a dict shaped like PositionManager.find_tradable_options output
    candidate: Dict[str, Any]


@dataclass
class ExitIntent:
    position_id: str
    reason: str


@dataclass
class HedgePolicy:
    # Placeholder for future policy fields (mode, targets, bands)
    sizing_mode: Optional[str] = None


class StrategyBase:
    def __init__(self, algorithm: Any) -> None:
        self.algorithm = algorithm

    def select_entries(self, option_chain, ctx: StrategyContext) -> List[EntryIntent]:
        # Allow strategies to record last selected symbols for caching
        self.algorithm._last_selected_symbols = []
        return []

    def manage_positions(self, ctx: StrategyContext) -> List[ExitIntent]:
        return []

    def desired_delta_policy(self, ctx: StrategyContext) -> Optional[HedgePolicy]:
        return None


