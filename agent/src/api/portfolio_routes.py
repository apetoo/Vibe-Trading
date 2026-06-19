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
import math
import re
import time
from typing import Any, Callable, Optional

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel, Field

from src.trading import service as trading_service

logger = logging.getLogger(__name__)

AuthDep = Callable[..., Any]

# Broker SDK exception messages can embed credentials (e.g. ccxt
# "AuthenticationError apiKey AK-... is invalid"). ``redact_payload`` only
# scrubs dict VALUES whose KEYS are sensitive; it does not scan free-text
# string values, so logging ``str(exc)`` directly can leak secrets. These
# patterns catch common credential shapes inline before logging.
_CRED_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"(?i)(api[_-]?key|access[_-]?token|secret|bearer|authorization)[\s:=\"]+[A-Za-z0-9_\-\.]{8,}",
        r"(?i)sk[_-][A-Za-z0-9]{16,}",
        r"(?i)AKIA[0-9A-Z]{16}",
    )
)


def _redact_text(text: str) -> str:
    """Mask credential-like substrings in a free-text string (exception msgs).

    ``redact_payload`` is key-based and does not scan string values, so it is
    the wrong tool for logging ``str(exc)``. Use this instead.
    """
    redacted = text
    for pat in _CRED_PATTERNS:
        redacted = pat.sub("[redacted]", redacted)
    return redacted

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
        f = float(value)
    except (TypeError, ValueError):
        return None
    # Reject NaN/Infinity: some brokers stringify these ("NaN", "Infinity"),
    # and Pydantic v2 float fields accept them by default, which would render
    # as "NaN"/"∞" in the UI. Treat as missing.
    if not math.isfinite(f):
        return None
    return f


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


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

def _disconnected(error: str, profile: Optional[str] = None,
                  is_paper: Optional[bool] = None) -> HoldingsResponse:
    return HoldingsResponse(
        connected=False,
        profile=profile,
        is_paper=is_paper,
        holdings=[],
        summary=PortfolioSummary(),
        error=error,
    )


async def _read_holdings(profile_id: Optional[str]) -> HoldingsResponse:
    """Fetch + normalize positions off the event loop. Never raises to the route."""
    try:
        positions_payload = await asyncio.to_thread(trading_service.get_positions, profile_id)
    except ImportError:
        # Log the (redacted) detail; keep the client message generic so we do
        # not leak internal module paths from importlib error messages.
        logger.warning("portfolio get_positions: connector SDK not installed (profile_id=%s)", profile_id)
        return _disconnected("连接器 SDK 未安装，请联系管理员")
    except ValueError:
        logger.warning("portfolio get_positions: profile not found / config error (profile_id=%s)", profile_id)
        return _disconnected("未找到交易连接配置，请在设置中授权连接器")
    except (TimeoutError, ConnectionError, OSError):
        logger.warning("portfolio get_positions: broker timeout/network (profile_id=%s)", profile_id)
        return _disconnected("券商连接超时，请稍后重试")
    except Exception as exc:  # last resort — log the (redacted) type, generic message
        logger.error("portfolio get_positions failed (profile_id=%s): %s",
                     profile_id, _redact_text(str(exc)))
        return _disconnected("读取持仓失败，请稍后重试")

    profile = positions_payload.get("profile") if isinstance(positions_payload, dict) else None
    is_paper = positions_payload.get("is_paper") if isinstance(positions_payload, dict) else None
    rows = positions_payload.get("positions", []) if isinstance(positions_payload, dict) else []
    holdings = [_normalize_row(r) for r in rows if isinstance(r, dict)]

    account: Optional[dict[str, Any]] = None
    try:
        account = await asyncio.to_thread(trading_service.get_account, profile_id)
    except Exception as exc:
        # Non-fatal: positions already succeeded. Log the (redacted) detail so
        # cash degrading to None is debuggable; keep returning positions.
        logger.warning("portfolio get_account failed (positions still returned, profile_id=%s): %s",
                       profile_id, _redact_text(str(exc)))

    return HoldingsResponse(
        connected=True,
        profile=profile,
        is_paper=is_paper,
        holdings=holdings,
        summary=_build_summary(holdings, account),
    )


def register_portfolio_routes(app: FastAPI, require_auth: AuthDep | None = None) -> None:
    """Mount the portfolio holdings routes onto ``app``.

    Mirrors ``register_alpha_routes``: when ``require_auth`` is not passed
    explicitly, resolve it from the host ``api_server`` module via
    ``sys.modules``.
    """
    if require_auth is None:
        import sys as _sys
        host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        if host is None:  # pragma: no cover
            raise RuntimeError(
                "register_portfolio_routes: api_server module not in sys.modules; "
                "pass require_auth explicitly"
            )
        require_auth = host.require_auth

    @app.get("/portfolio/holdings", dependencies=[Depends(require_auth)])
    async def get_holdings(
        profile_id: Optional[str] = Query(None, max_length=128),
        force: Optional[str] = Query(None),
    ) -> HoldingsResponse:
        cache_key = profile_id
        if not (force == "1" or force == "true"):
            cached = _positions_cache.get(cache_key)
            if cached and cached[0] > time.monotonic():
                return HoldingsResponse(**cached[1])

        response = await _read_holdings(profile_id)
        # Cache only successful reads; disconnected/error states stay fresh.
        if response.connected:
            _positions_cache[cache_key] = (
                time.monotonic() + _CACHE_TTL_SECONDS,
                response.model_dump(),
            )
        return response
