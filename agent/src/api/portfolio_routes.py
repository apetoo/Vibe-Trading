"""Portfolio holdings HTTP route for the Web UI.

Mounted by ``agent/api_server.py`` via ``register_portfolio_routes(app)``.
Surfaces real broker positions from ``src.trading.service`` (the 9 trading
connectors) as a read-only ``GET /portfolio/holdings`` endpoint consumed by the
sidebar portfolio popover.

Design notes (see DESIGN.md §4-§5, §13):
- ``get_positions`` / ``get_account`` are synchronous blocking SDK/HTTP calls.
  The route is ``async def`` and offloads them to ``asyncio.to_thread`` so a
  slow broker never stalls the FastAPI event loop.
- Connector position rows use inconsistent field names (alpaca: ``qty``/
  ``avg_entry_price``; dhan: ``netQty``/``costPrice``). ``_normalize_row`` maps
  the common aliases and degrades missing cost basis to ``None`` (UI shows ``—``)
  rather than fabricating a P&L. This intentionally does NOT reuse
  ``src.live.runtime.reconcile`` private helpers, to keep the read-only menu
  decoupled from the live-enforcement runtime.
- Position data is sensitive; logs are scrubbed with ``redact_payload``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel, Field

from src.tools.redaction import redact_payload
from src.trading import service as trading_service

logger = logging.getLogger(__name__)

AuthDep = Callable[..., Any]

# Per-profile in-memory cache: {profile_id|None: (expires_at_epoch, payload)}.
# 30s TTL avoids hammering broker rate limits when the popover is opened often.
_CACHE_TTL_SECONDS = 30.0
_positions_cache: dict[Any, tuple[float, dict[str, Any]]] = {}


class Holding(BaseModel):
    """A single normalized position row."""

    symbol: str
    name: str = ""
    quantity: float
    average_cost: Optional[float] = None
    current_price: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    # Total cost basis used to compute pnl_percent (explicit connector total
    # preferred, else average_cost * quantity). Carried on the model so
    # _build_summary aggregates the SAME denominator per-holding pnl_percent
    # used — avoiding a silent divergence when a connector's total cost_basis
    # differs from average_cost * quantity (wash-sale adjustments, lot
    # liquidations, corporate actions).
    cost_basis_total: Optional[float] = None
    side: str = ""


class PortfolioSummary(BaseModel):
    """Aggregated portfolio totals."""

    market_value: float = 0.0
    cost_basis: float = 0.0
    unrealized_pnl: float = 0.0
    pnl_percent: Optional[float] = None
    cash: Optional[float] = None


class HoldingsResponse(BaseModel):
    """Envelope returned by ``GET /portfolio/holdings``."""

    connected: bool = Field(..., description="True when a broker was reached successfully")
    profile: Optional[str] = None
    is_paper: Optional[bool] = None
    holdings: list[Holding] = []
    summary: PortfolioSummary = PortfolioSummary()
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Normalization (pure, unit-tested in isolation)
# ---------------------------------------------------------------------------

def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Optional[float]:
    for key in keys:
        if key in row and row[key] is not None:
            parsed = _as_float(row[key])
            if parsed is not None:
                return parsed
    return None


def _normalize_row(row: dict[str, Any]) -> Holding:
    """Map a connector position row to a Holding with P&L where computable."""
    symbol = str(row.get("symbol") or row.get("ticker") or row.get("tradingSymbol") or "")
    quantity = _first(row, ("quantity", "qty", "netQty", "position")) or 0.0
    # Per-share average cost. NOTE: ``cost_basis`` is a TOTAL dollar amount
    # (alpaca), not per-share — it is handled separately below.
    average_cost = _first(row, ("average_cost", "avg_cost", "avg_entry_price",
                                "costPrice", "avg_price"))
    current_price = _first(row, ("current_price", "last_price", "market_price", "currentPrice"))
    market_value = _first(row, ("market_value", "marketValue", "mv", "value"))
    unrealized_pnl = _first(row, ("unrealized_pnl", "unrealized_pl", "unrealizedPnl",
                                  "realizedProfit", "pnl"))
    side = str(row.get("side") or "")

    # Total cost basis: prefer an explicit total field, else derive per-share.
    explicit_cost_basis = _first(row, ("cost_basis", "costAmount"))
    if explicit_cost_basis is not None:
        cost_basis_total: Optional[float] = explicit_cost_basis
    elif average_cost is not None:
        cost_basis_total = average_cost * quantity
    else:
        cost_basis_total = None
    pnl_percent: Optional[float] = None
    if cost_basis_total is not None and cost_basis_total > 0 and unrealized_pnl is not None:
        pnl_percent = round(unrealized_pnl / cost_basis_total * 100, 2)

    return Holding(
        symbol=symbol,
        quantity=round(quantity, 6),
        average_cost=average_cost,
        current_price=current_price,
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
        pnl_percent=pnl_percent,
        cost_basis_total=cost_basis_total,
        side=side,
    )


def _build_summary(holdings: list[Holding], account: Optional[dict[str, Any]]) -> PortfolioSummary:
    """Aggregate holdings; cash pulled from the account snapshot when present.

    Uses each holding's ``cost_basis_total`` (the same denominator
    ``_normalize_row`` used for its ``pnl_percent``) so the summary P&L% is
    consistent with the per-row P&L%. Falls back to ``average_cost * quantity``
    when no total is known.
    """
    market_value = sum(h.market_value or 0.0 for h in holdings)
    cost_basis = sum(
        h.cost_basis_total if h.cost_basis_total is not None
        else (h.average_cost or 0.0) * h.quantity
        for h in holdings
    )
    unrealized_pnl = sum(h.unrealized_pnl or 0.0 for h in holdings)
    pnl_percent: Optional[float] = None
    if cost_basis > 0:
        pnl_percent = round(unrealized_pnl / cost_basis * 100, 2)

    cash: Optional[float] = None
    if account:
        cash = _first(account, ("cash", "cash_balance", "buying_power", "buyingPower"))

    return PortfolioSummary(
        market_value=round(market_value, 2),
        cost_basis=round(cost_basis, 2),
        unrealized_pnl=round(unrealized_pnl, 2),
        pnl_percent=pnl_percent,
        cash=cash,
    )
