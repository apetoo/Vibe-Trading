"""Manual portfolio holdings store — file-backed source of truth.

The user maintains current holdings here when they don't have (or don't want)
a live broker connection. Three entry points keep it populated:
    1. CSV import via ``trade_journal_tool``: after the FIFO buy/sell pairing,
       the unmatched buys (= still-held lots) are aggregated and written here.
    2. Agent conversation via ``manage_portfolio_tool``: the user tells the
       agent "I bought 100 AAPL at 150" and the agent calls ``add_lot``.
    3. Direct table editing in the Web UI Settings page (``replace_all``).

Storage shape (``~/.vibe-trading/portfolio.json``):
    {
        "version": 1,
        "holdings": [
            {"symbol": "AAPL", "name": "Apple Inc.",
             "quantity": 100.0, "average_cost": 150.0},
            ...
        ]
    }

The store is intentionally small and dependency-free: no DB, no migrations,
no locking. A single user editing from one host. ``portfolio_routes`` reads
this file as the primary source for ``GET /portfolio/holdings``; the broker
path becomes a strict fallback (DESIGN.md §2 revised).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

_STORE_VERSION = 1
_ENV_PATH = "VIBE_TRADING_PORTFOLIO_PATH"


@dataclass
class ManualHolding:
    """A single user-maintained position."""

    symbol: str
    quantity: float
    average_cost: float
    name: str = ""

    def __post_init__(self) -> None:
        # Normalize symbol so 'aapl' and 'AAPL' collapse to one row.
        self.symbol = str(self.symbol).strip().upper()
        self.quantity = float(self.quantity)
        self.average_cost = float(self.average_cost)
        self.name = str(self.name or "")


def _store_path() -> Path:
    override = os.environ.get(_ENV_PATH)
    if override:
        return Path(override)
    return Path.home() / ".vibe-trading" / "portfolio.json"


def _load_raw() -> dict:
    path = _store_path()
    if not path.exists():
        return {"version": _STORE_VERSION, "holdings": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "holdings" not in data:
            logger.warning("portfolio store at %s has unexpected shape; treating as empty", path)
            return {"version": _STORE_VERSION, "holdings": []}
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("portfolio store at %s unreadable (%s); treating as empty", path, exc)
        return {"version": _STORE_VERSION, "holdings": []}


def _atomic_write(payload: dict) -> None:
    """Write JSON atomically: tmp file in same dir, then rename.

    Prevents the holdings file from being half-written if the process is
    interrupted mid-write.
    """
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".portfolio-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup of the tmp file if rename failed.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def list_holdings() -> list[ManualHolding]:
    """Return all current holdings (zero-quantity rows are excluded)."""
    raw = _load_raw()
    out: list[ManualHolding] = []
    for row in raw.get("holdings", []):
        if not isinstance(row, dict):
            continue
        try:
            h = ManualHolding(
                symbol=row.get("symbol", ""),
                quantity=row.get("quantity", 0),
                average_cost=row.get("average_cost", 0),
                name=row.get("name", ""),
            )
        except (TypeError, ValueError):
            continue
        if h.symbol and h.quantity > 0:
            out.append(h)
    return out


def _save_holdings(holdings: Iterable[ManualHolding]) -> None:
    payload = {
        "version": _STORE_VERSION,
        "holdings": [asdict(h) for h in holdings if h.quantity > 0],
    }
    _atomic_write(payload)


def set_holding(symbol: str, quantity: float, average_cost: float,
                name: str = "") -> Optional[ManualHolding]:
    """Set the absolute quantity + cost for a symbol (overwrites existing).

    Quantity 0 removes the holding. Returns the new ManualHolding, or None
    when the row was deleted.
    """
    holdings = list_holdings()
    new_holding = ManualHolding(
        symbol=symbol, quantity=quantity, average_cost=average_cost, name=name,
    )
    holdings = [h for h in holdings if h.symbol != new_holding.symbol]
    if new_holding.quantity > 0:
        holdings.append(new_holding)
        _save_holdings(holdings)
        return new_holding
    _save_holdings(holdings)
    return None


def add_lot(symbol: str, quantity: float, price: float,
            name: str = "") -> Optional[ManualHolding]:
    """Append a buy (or sell, with negative quantity) to a holding.

    For buys (qty > 0): combine quantities and recompute the weighted-average
    cost so the per-row P&L stays correct on subsequent fetches.

    For sells (qty < 0): reduce quantity, leave avg_cost unchanged. If the
    sell would drive quantity to <=0, remove the holding (overselling clamps,
    we don't allow negative positions in the manual store).

    Returns the resulting ManualHolding, or None when the holding was removed.
    """
    sym = str(symbol).strip().upper()
    if not sym:
        raise ValueError("symbol is required")
    qty = float(quantity)
    price = float(price)
    if qty == 0:
        return None  # nothing to do

    holdings = list_holdings()
    existing = next((h for h in holdings if h.symbol == sym), None)
    others = [h for h in holdings if h.symbol != sym]

    if existing is None:
        if qty < 0:
            # selling something we don't hold: ignore (manual store stays >=0)
            return None
        new_h = ManualHolding(symbol=sym, quantity=qty, average_cost=price, name=name)
        others.append(new_h)
        _save_holdings(others)
        return new_h

    if qty > 0:
        # Buy: weighted average cost.
        total_qty = existing.quantity + qty
        new_cost = ((existing.average_cost * existing.quantity) + (price * qty)) / total_qty
        new_h = ManualHolding(
            symbol=sym,
            quantity=round(total_qty, 6),
            average_cost=round(new_cost, 4),
            name=name or existing.name,
        )
        others.append(new_h)
        _save_holdings(others)
        return new_h

    # Sell (qty < 0): reduce, never below zero.
    remaining = existing.quantity + qty  # qty is negative
    if remaining <= 0:
        _save_holdings(others)  # holding fully closed (or oversold)
        return None
    new_h = ManualHolding(
        symbol=sym,
        quantity=round(remaining, 6),
        average_cost=existing.average_cost,
        name=existing.name,
    )
    others.append(new_h)
    _save_holdings(others)
    return new_h


def delete_holding(symbol: str) -> None:
    """Remove a symbol from the store. No-op if the symbol isn't held."""
    sym = str(symbol).strip().upper()
    holdings = [h for h in list_holdings() if h.symbol != sym]
    _save_holdings(holdings)


def replace_all(holdings: Iterable[ManualHolding]) -> None:
    """Overwrite the entire holdings list (used by the Settings table UI)."""
    _save_holdings(list(holdings))


# ---------------------------------------------------------------------------
# CSV-import flow (called from trade_journal_tool after FIFO pairing)
# ---------------------------------------------------------------------------

def compute_holdings_from_journal(df) -> list[ManualHolding]:  # pandas DF
    """FIFO-pair the journal and return ManualHolding rows for unmatched buys.

    Re-implements the FIFO loop from ``trade_journal_tool.pair_trades_fifo``
    but RETURNS the leftover queues instead of discarding them. Aggregates
    per-symbol leftover lots into one ManualHolding using a weighted average
    of the remaining buy prices.

    Mirrors the existing tool behaviour (sort by datetime, FIFO oldest-first
    matching, no fee adjustment to cost basis), so importing the same CSV
    twice yields the same holdings.
    """
    from collections import defaultdict, deque

    if df is None or len(df) == 0:
        return []

    queues: dict[str, deque] = defaultdict(deque)

    for row in df.itertuples(index=False):
        side = getattr(row, "side", None)
        symbol = getattr(row, "symbol", None)
        if not symbol or side not in ("buy", "sell"):
            continue
        qty = float(getattr(row, "quantity", 0) or 0)
        price = float(getattr(row, "price", 0) or 0)
        if qty <= 0:
            continue

        if side == "buy":
            queues[symbol].append({"qty": qty, "price": price})
            continue

        # sell: consume oldest buys first (FIFO)
        remaining = qty
        q = queues[symbol]
        while remaining > 1e-9 and q:
            lot = q[0]
            take = min(lot["qty"], remaining)
            lot["qty"] -= take
            remaining -= take
            if lot["qty"] <= 1e-9:
                q.popleft()

    holdings: list[ManualHolding] = []
    for symbol, q in queues.items():
        if not q:
            continue
        total_qty = sum(lot["qty"] for lot in q)
        if total_qty <= 1e-9:
            continue
        weighted_cost = sum(lot["qty"] * lot["price"] for lot in q) / total_qty
        holdings.append(ManualHolding(
            symbol=symbol,
            quantity=round(total_qty, 6),
            average_cost=round(weighted_cost, 4),
            name="",
        ))
    holdings.sort(key=lambda h: h.symbol)
    return holdings
