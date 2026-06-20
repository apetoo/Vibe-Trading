"""Manage manual portfolio holdings via agent conversation.

The user maintains current holdings without a broker connection. Three ways
to keep it populated, all converging on ``~/.vibe-trading/portfolio.json``:

  - CSV import (``analyze_trade_journal``): bulk replace from a journal.
  - This tool (``manage_portfolio``): targeted edits via conversation.
  - Settings table UI (``PUT/DELETE /portfolio/holdings`` REST routes).

The agent calls this tool when the user says things like:

  "I bought 100 shares of AAPL at 150"  -> action=add_lot, qty=100, price=150
  "Sold 50 TSLA at 250"                 -> action=add_lot, qty=-50, price=250
  "Set my AAPL holding to 200 @ 155"    -> action=set, qty=200, cost=155
  "Remove NVDA from my portfolio"       -> action=delete
  "Show me my holdings"                 -> action=list
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

from src.agent.tools import BaseTool
from src.portfolio.manual_holdings import (
    add_lot,
    delete_holding,
    list_holdings,
    set_holding,
)

logger = logging.getLogger(__name__)


def _holding_dict(h) -> dict[str, Any]:
    return {
        "symbol": h.symbol,
        "name": h.name,
        "quantity": h.quantity,
        "average_cost": h.average_cost,
    }


def _err(message: str) -> str:
    return json.dumps({"status": "error", "error": message}, ensure_ascii=False)


def _ok(**payload: Any) -> str:
    return json.dumps({"status": "ok", **payload}, ensure_ascii=False, default=str)


class ManagePortfolioTool(BaseTool):
    """Add / update / delete / list manual portfolio holdings."""

    name = "manage_portfolio"
    description = (
        "Manage the user's manual portfolio holdings stored at "
        "~/.vibe-trading/portfolio.json. The sidebar holdings menu reads from "
        "this file. Use this tool when the user mentions buying, selling, or "
        "adjusting a position in conversation, or asks to see their current "
        "holdings.\n"
        "\n"
        "Actions:\n"
        "  - add_lot: append a buy (qty > 0) or sell (qty < 0). For buys this "
        "    recomputes the weighted-average cost. For sells qty larger than "
        "    the held quantity is clamped to zero (the holding is removed).\n"
        "  - set: overwrite a holding's absolute quantity + average_cost (use "
        "    when the user says 'I have 100 AAPL at 150' as a snapshot).\n"
        "  - delete: remove a symbol from the portfolio.\n"
        "  - list: return all current holdings."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add_lot", "set", "delete", "list"],
                "description": "Operation to perform.",
            },
            "symbol": {
                "type": "string",
                "description": (
                    "Trading symbol (case-insensitive; stored as uppercase). "
                    "Required for add_lot, set, delete."
                ),
            },
            "quantity": {
                "type": "number",
                "description": (
                    "For add_lot: the buy quantity (positive) or sell quantity "
                    "(negative, e.g. -50 for a sale of 50 shares). For set: the "
                    "absolute new quantity (must be > 0)."
                ),
            },
            "price": {
                "type": "number",
                "description": (
                    "For add_lot only: the per-share price at the buy/sell. "
                    "Used to recompute weighted-average cost on buys; ignored "
                    "on sells (cost basis stays)."
                ),
            },
            "average_cost": {
                "type": "number",
                "description": (
                    "For set only: the per-share average cost across all "
                    "currently-held units."
                ),
            },
            "name": {
                "type": "string",
                "description": (
                    "Optional display name (e.g. 'Apple Inc.'). Used as a "
                    "label only; matching keys off symbol."
                ),
                "default": "",
            },
        },
        "required": ["action"],
    }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action")

        if action == "list":
            holdings = list_holdings()
            return _ok(
                count=len(holdings),
                holdings=[_holding_dict(h) for h in holdings],
            )

        symbol = kwargs.get("symbol") or ""
        if not symbol:
            return _err("symbol is required for add_lot/set/delete")

        if action == "delete":
            delete_holding(symbol)
            return _ok(deleted=str(symbol).upper())

        if action == "add_lot":
            qty = kwargs.get("quantity")
            price = kwargs.get("price")
            if qty is None or price is None:
                return _err("add_lot requires quantity and price")
            try:
                h = add_lot(symbol, float(qty), float(price), kwargs.get("name", ""))
            except (TypeError, ValueError) as exc:
                return _err(f"invalid numeric input: {exc}")
            return _ok(holding=_holding_dict(h) if h else None)

        if action == "set":
            qty = kwargs.get("quantity")
            cost = kwargs.get("average_cost")
            if qty is None or cost is None:
                return _err("set requires quantity and average_cost")
            try:
                qty_f = float(qty)
                cost_f = float(cost)
            except (TypeError, ValueError) as exc:
                return _err(f"invalid numeric input: {exc}")
            if qty_f <= 0:
                return _err("quantity must be > 0 for set (use action=delete to remove)")
            if cost_f < 0:
                return _err("average_cost must be >= 0")
            h = set_holding(symbol, qty_f, cost_f, kwargs.get("name", ""))
            return _ok(holding=_holding_dict(h) if h else None)

        return _err(f"unknown action: {action}")
