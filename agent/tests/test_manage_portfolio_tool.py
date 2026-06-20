"""Tests for the manage_portfolio agent tool."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.unit

from src.tools.manage_portfolio_tool import ManagePortfolioTool  # noqa: E402


@pytest.fixture
def tool(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_PORTFOLIO_PATH", str(tmp_path / "portfolio.json"))
    return ManagePortfolioTool()


def _exec(tool, **kw):
    return json.loads(tool.execute(**kw))


def test_list_empty(tool):
    res = _exec(tool, action="list")
    assert res["status"] == "ok"
    assert res["count"] == 0
    assert res["holdings"] == []


def test_add_lot_creates_holding(tool):
    res = _exec(tool, action="add_lot", symbol="AAPL", quantity=100, price=150.0)
    assert res["status"] == "ok"
    h = res["holding"]
    assert h["symbol"] == "AAPL"
    assert h["quantity"] == 100.0
    assert h["average_cost"] == 150.0


def test_add_lot_recomputes_avg_cost(tool):
    _exec(tool, action="add_lot", symbol="AAPL", quantity=100, price=150.0)
    res = _exec(tool, action="add_lot", symbol="AAPL", quantity=50, price=180.0)
    h = res["holding"]
    assert h["quantity"] == 150.0
    # (100*150 + 50*180) / 150 = 160
    assert h["average_cost"] == pytest.approx(160.0, abs=0.01)


def test_add_lot_sells(tool):
    _exec(tool, action="add_lot", symbol="AAPL", quantity=100, price=150.0)
    res = _exec(tool, action="add_lot", symbol="AAPL", quantity=-30, price=200.0)
    h = res["holding"]
    assert h["quantity"] == 70.0
    assert h["average_cost"] == 150.0  # unchanged on sells


def test_add_lot_oversell_clamps(tool):
    _exec(tool, action="add_lot", symbol="AAPL", quantity=10, price=150.0)
    res = _exec(tool, action="add_lot", symbol="AAPL", quantity=-50, price=200.0)
    assert res["status"] == "ok"
    assert res["holding"] is None
    assert _exec(tool, action="list")["count"] == 0


def test_set_holding(tool):
    res = _exec(tool, action="set", symbol="AAPL", quantity=200, average_cost=155.0)
    assert res["status"] == "ok"
    assert res["holding"]["quantity"] == 200.0
    assert res["holding"]["average_cost"] == 155.0


def test_set_zero_qty_rejected(tool):
    res = _exec(tool, action="set", symbol="AAPL", quantity=0, average_cost=150.0)
    assert res["status"] == "error"
    assert "delete" in res["error"]


def test_delete_holding(tool):
    _exec(tool, action="add_lot", symbol="AAPL", quantity=100, price=150.0)
    res = _exec(tool, action="delete", symbol="AAPL")
    assert res["status"] == "ok"
    assert res["deleted"] == "AAPL"
    assert _exec(tool, action="list")["count"] == 0


def test_delete_missing_no_error(tool):
    res = _exec(tool, action="delete", symbol="DOES_NOT_EXIST")
    assert res["status"] == "ok"


def test_missing_symbol_for_add_lot(tool):
    res = _exec(tool, action="add_lot", quantity=10, price=5.0)
    assert res["status"] == "error"
    assert "symbol" in res["error"]


def test_unknown_action(tool):
    res = _exec(tool, action="frobnicate")
    assert res["status"] == "error"


def test_add_lot_string_numbers(tool):
    """Tolerate stringified numbers from the LLM."""
    res = _exec(tool, action="add_lot", symbol="AAPL", quantity="100", price="150.0")
    assert res["status"] == "ok"
    assert res["holding"]["quantity"] == 100.0


def test_symbol_uppercased(tool):
    _exec(tool, action="add_lot", symbol="aapl", quantity=10, price=150.0)
    holdings = _exec(tool, action="list")["holdings"]
    assert holdings[0]["symbol"] == "AAPL"
