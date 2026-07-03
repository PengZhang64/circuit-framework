"""Paper trading persistence and simulated execution for Circuit Framework."""

from tradingagents.paper.database import PaperDatabase
from tradingagents.paper.execution import PaperExecutor
from tradingagents.paper.performance import compute_performance
from tradingagents.paper.portfolio import PaperPortfolio
from tradingagents.paper.schemas import (
    EquitySnapshot,
    FillRecord,
    OrderRecord,
    PerformanceMetrics,
    PortfolioRecord,
    PositionRecord,
    StrategyRunRecord,
)

__all__ = [
    "EquitySnapshot",
    "FillRecord",
    "OrderRecord",
    "PaperDatabase",
    "PaperExecutor",
    "PaperPortfolio",
    "PerformanceMetrics",
    "PortfolioRecord",
    "PositionRecord",
    "StrategyRunRecord",
    "compute_performance",
]
