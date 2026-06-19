"""Unit tests for the portfolio holdings menu (normalization + summary + route).

Loopback ``TestClient`` (127.0.0.1) bypasses dev-mode auth, matching
``test_alpha_compare_api.py`` / ``test_security_auth_api.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit

from src.api.portfolio_routes import (  # noqa: E402
    Holding,
    _build_summary,
    _normalize_row,
)


def _alpaca_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "symbol": "AAPL",
        "side": "long",
        "quantity": 100,
        "average_cost": 150.0,
        "current_price": 175.5,
        "market_value": 17550.0,
        "unrealized_pnl": 2550.0,
        "cost_basis": 15000.0,
    }
    row.update(over)
    return row


def test_normalize_row_full() -> None:
    h = _normalize_row(_alpaca_row())
    assert h.symbol == "AAPL"
    assert h.quantity == 100.0
    assert h.average_cost == 150.0
    assert h.current_price == 175.5
    assert h.market_value == 17550.0
    assert h.unrealized_pnl == 2550.0
    assert h.pnl_percent == pytest.approx(17.0, abs=0.01)


def test_normalize_row_dhan_aliases() -> None:
    """dhan uses netQty/costPrice/currentPrice/realizedProfit + tradingSymbol."""
    row = {
        "tradingSymbol": "RELIANCE",
        "netQty": 50,
        "costPrice": 220.0,
        "currentPrice": 245.0,
        "realizedProfit": 1250.0,
    }
    h = _normalize_row(row)
    assert h.symbol == "RELIANCE"
    assert h.quantity == 50.0
    assert h.average_cost == 220.0
    assert h.current_price == 245.0


def test_normalize_row_missing_cost_basis() -> None:
    """No average_cost AND no cost_basis -> pnl_percent is None (degrade to —)."""
    row = {"symbol": "TSLA", "quantity": 10, "current_price": 245.0}
    h = _normalize_row(row)
    assert h.average_cost is None
    assert h.pnl_percent is None


def test_normalize_row_negative_pnl() -> None:
    row = _alpaca_row(average_cost=300.0, current_price=245.0, cost_basis=3000.0,
                      market_value=2450.0, unrealized_pnl=-550.0)
    h = _normalize_row(row)
    assert h.unrealized_pnl == -550.0
    assert h.pnl_percent == pytest.approx(-18.33, abs=0.01)


def test_normalize_row_zero_quantity() -> None:
    h = _normalize_row(_alpaca_row(quantity=0, average_cost=0, current_price=0,
                                   market_value=0, unrealized_pnl=0, cost_basis=0))
    assert h.quantity == 0.0
    assert h.pnl_percent is None  # cost_basis 0 -> None, avoid div-by-zero


def test_build_summary_aggregation() -> None:
    holdings = [
        _normalize_row(_alpaca_row()),  # mv 17550, cost 15000, pnl 2550
        _normalize_row(_alpaca_row(symbol="TSLA", quantity=50, average_cost=220.0,
                                   current_price=245.0, market_value=12250.0,
                                   unrealized_pnl=1250.0, cost_basis=11000.0)),
    ]
    summary = _build_summary(holdings, account={"cash": 5000.0})
    assert summary.market_value == pytest.approx(29800.0, abs=0.01)
    assert summary.cost_basis == pytest.approx(26000.0, abs=0.01)
    assert summary.unrealized_pnl == pytest.approx(3800.0, abs=0.01)
    assert summary.pnl_percent == pytest.approx(14.615, abs=0.01)
    assert summary.cash == 5000.0


def test_build_summary_empty() -> None:
    summary = _build_summary([], None)
    assert summary.market_value == 0.0
    assert summary.cost_basis == 0.0
    assert summary.unrealized_pnl == 0.0
    assert summary.pnl_percent is None
    assert summary.cash is None
