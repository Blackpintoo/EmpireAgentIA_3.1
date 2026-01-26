# agents/__init__.py
"""
Exports des agents de trading pour EmpireAgentIA.
"""

from .scalping import ScalpingAgent
from .swing import SwingAgent
from .technical import TechnicalAgent
from .structure import StructureAgent
from .smart_money import SmartMoneyAgent
from .news import NewsAgent
from .sentiment import SentimentAgent
from .fundamental import FundamentalAgent
from .macro import MacroAgent
from .price_action import PriceActionAgent
from .whale_agent import WhaleAgent

__all__ = [
    "ScalpingAgent",
    "SwingAgent",
    "TechnicalAgent",
    "StructureAgent",
    "SmartMoneyAgent",
    "NewsAgent",
    "SentimentAgent",
    "FundamentalAgent",
    "MacroAgent",
    "PriceActionAgent",
    "WhaleAgent",
]
