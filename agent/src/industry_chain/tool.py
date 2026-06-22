"""Read-only tool: query industry chain context for a stock.

Wraps IndustryChainStore and exposes its query methods as a
BaseTool-compatible tool that agents can invoke.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.agent.tools import BaseTool
from src.industry_chain.store import IndustryChainStore

logger = logging.getLogger(__name__)


class IndustryChainQueryTool(BaseTool):
    """Query a stock's position in the industry chain knowledge graph.

    Wraps IndustryChainStore.get_stock_context() to return the stock's
    industry chain path, competitors, financials, and other metadata.
    """

    name = "get_industry_chain_context"
    description = (
        "Query a stock's position in the industry chain knowledge graph. "
        "Returns the stock's industry chain: which track (赛道), segment (技术方向), "
        "and link (环节) it belongs to, plus key data like localization rate (国产化率), "
        "gross margin (毛利率中枢), market size (市场规模), main competitors, "
        "and financial highlights. Call this BEFORE analyzing a stock so you have "
        "industry chain context. "
        "Returns null/empty if the stock is not yet in the graph."
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Stock code, e.g. 300308.SZ / 600519.SH / AAPL",
            },
        },
        "required": ["code"],
    }
    repeatable = True
    is_readonly = True

    def __init__(self, store: IndustryChainStore | None = None) -> None:
        super().__init__()
        self._store = store

    def execute(self, **kwargs: Any) -> str:
        """Query the industry chain context for a stock code.

        Args:
            **kwargs: Must include ``code`` (stock code string).

        Returns:
            JSON string with stock context or error envelope.
        """
        code = kwargs.get("code", "")
        if not code:
            return json.dumps(
                {"error": "Parameter 'code' is required", "found": False},
                ensure_ascii=False,
            )

        store = self._store
        if store is None:
            try:
                store = IndustryChainStore()
            except Exception as exc:
                logger.warning("IndustryChainQueryTool: failed to create store: %s", exc)
                return json.dumps(
                    {"error": f"Store not available: {exc}", "found": False},
                    ensure_ascii=False,
                )

        try:
            ctx = store.get_stock_context(code)
            if ctx is None:
                return json.dumps(
                    {"error": f"Stock {code} not found in industry chain", "found": False},
                    ensure_ascii=False,
                )
            return json.dumps(ctx, ensure_ascii=False)
        except Exception as exc:
            logger.warning("IndustryChainQueryTool failed: %s", exc)
            return json.dumps(
                {"error": str(exc), "found": False}, ensure_ascii=False
            )
