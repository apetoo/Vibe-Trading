"""Portfolio data models and functions."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Try to import from data sources for real price data
try:
    from vibe_trading.data.data_source import DataSource
    _has_data_source = True
except ImportError:
    _has_data_source = False


@dataclass
class HoldingItem:
    """Represents a single holding position."""

    symbol: str
    name: str
    quantity: float
    cost_price: float
    current_price: float
    market_value: float
    pnl: float
    pnl_percent: float


@dataclass
class PortfolioSummary:
    """Aggregated portfolio summary."""

    total_market_value: float = 0.0
    total_cost: float = 0.0
    total_pnl: float = 0.0


def get_portfolio_summary(holdings: List[HoldingItem]) -> PortfolioSummary:
    """Calculate portfolio summary from holdings list."""
    total_market_value = sum(h.market_value for h in holdings)
    total_cost = sum(h.quantity * h.cost_price for h in holdings)
    total_pnl = sum(h.pnl for h in holdings)
    return PortfolioSummary(
        total_market_value=round(total_market_value, 2),
        total_cost=round(total_cost, 2),
        total_pnl=round(total_pnl, 2),
    )


def _get_config_path() -> Path:
    """Get the path to the holdings config file."""
    # Look in project root, then in config directory
    candidates = [
        Path.cwd() / "holdings.json",
        Path(__file__).parent.parent.parent / "holdings.json",
        Path(__file__).parent.parent.parent / "config" / "holdings.json",
        Path(__file__).parent.parent.parent / "holdings.yaml",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def _load_from_config(path: Optional[Path] = None) -> List[HoldingItem]:
    """Load holdings from configuration file (JSON format)."""
    config_path = path or _get_config_path()

    if not config_path.exists():
        return _get_default_holdings()

    try:
        if config_path.suffix == ".json":
            with open(config_path) as f:
                data = json.load(f)
        elif config_path.suffix in (".yaml", ".yml"):
            try:
                import yaml
                with open(config_path) as f:
                    data = yaml.safe_load(f)
            except ImportError:
                return _get_default_holdings()
        else:
            return _get_default_holdings()

        holdings_raw = data if isinstance(data, list) else data.get("holdings", [])
        holdings = []
        for item in holdings_raw:
            quantity = float(item.get("quantity", 0))
            cost_price = float(item.get("cost_price", 0))
            current_price = float(item.get("current_price", cost_price))
            market_value = round(quantity * current_price, 2)
            cost_total = quantity * cost_price
            pnl = round(market_value - cost_total, 2)
            pnl_percent = round((pnl / cost_total * 100), 2) if cost_total > 0 else 0.0

            holdings.append(HoldingItem(
                symbol=str(item.get("symbol", "")),
                name=str(item.get("name", "")),
                quantity=quantity,
                cost_price=cost_price,
                current_price=current_price,
                market_value=market_value,
                pnl=pnl,
                pnl_percent=pnl_percent,
            ))
        return holdings
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return _get_default_holdings()


def _get_default_holdings() -> List[HoldingItem]:
    """Return default demo holdings when no config file exists."""
    return [
        HoldingItem(
            symbol="AAPL",
            name="Apple Inc.",
            quantity=100,
            cost_price=150.00,
            current_price=175.50,
            market_value=17550.00,
            pnl=2550.00,
            pnl_percent=17.00,
        ),
        HoldingItem(
            symbol="TSLA",
            name="Tesla Inc.",
            quantity=50,
            cost_price=220.00,
            current_price=245.00,
            market_value=12250.00,
            pnl=1250.00,
            pnl_percent=11.36,
        ),
        HoldingItem(
            symbol="NVDA",
            name="NVIDIA Corp.",
            quantity=10,
            cost_price=400.00,
            current_price=450.00,
            market_value=4500.00,
            pnl=500.00,
            pnl_percent=12.50,
        ),
    ]


def get_holdings() -> List[HoldingItem]:
    """Get current holdings.

    Priority:
    1. From data source (real-time)
    2. From local config file
    3. Default demo holdings
    """
    holdings = _load_from_config()
    return holdings
