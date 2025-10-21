"""
Order Manager: wraps entry/exit placement for options and underlying.
Thin facade over PositionManager and ExitRulesManager.
"""

from AlgorithmImports import *  # noqa: F401
from typing import List
from strategy_base import EntryIntent


class OrderManager:
    def __init__(self, algorithm):
        self.algorithm = algorithm

    def place_entries(self, intents: List[EntryIntent]) -> None:
        for intent in intents:
            candidate = intent.candidate
            if not candidate:
                continue
            self.algorithm.position_manager.try_enter_position(candidate)


