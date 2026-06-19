"""Unit tests for the portfolio holdings menu (normalization + summary + route).

Loopback ``TestClient`` (127.0.0.1) bypasses dev-mode auth, matching
``test_alpha_compare_api.py`` / ``test_security_auth_api.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit

import api_server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.trading import service as trading_service  # noqa: E402

from src.api.portfolio_routes import (  # noqa: E402
    Holding,
    _build_summary,
    _normalize_row,
    _positions_cache,
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


# ---------------------------------------------------------------------------
# Route tests (GET /portfolio/holdings)
# ---------------------------------------------------------------------------

def _client() -> TestClient:
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.fixture(autouse=True)
def _clear_cache():
    _positions_cache.clear()
    yield
    _positions_cache.clear()


def _positions_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"status": "ok", "profile": "alpaca-paper", "is_paper": True, "positions": rows}


def test_route_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch_positions(monkeypatch, _alpaca_row(), cash=5000.0)
    with _client() as c:
        r = c.get("/portfolio/holdings")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is True
    assert body["profile"] == "alpaca-paper"
    assert body["is_paper"] is True
    assert body["holdings"][0]["symbol"] == "AAPL"
    assert body["holdings"][0]["pnl_percent"] == pytest.approx(17.0, abs=0.01)
    assert body["summary"]["cash"] == 5000.0


def test_route_disconnected_on_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch_positions(monkeypatch, raises=ImportError("alpaca-py not installed"))
    with _client() as c:
        r = c.get("/portfolio/holdings")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert "SDK" in body["error"] or "not installed" in body["error"]
    assert body["holdings"] == []


def test_route_disconnected_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch_positions(monkeypatch, raises=TimeoutError("broker timed out"))
    with _client() as c:
        r = c.get("/portfolio/holdings")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert "超时" in body["error"] or "timeout" in body["error"].lower()


def test_route_disconnected_on_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch_positions(monkeypatch, raises=ValueError("unknown profile id"))
    with _client() as c:
        r = c.get("/portfolio/holdings")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False


def test_route_disconnected_on_generic_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch_positions(monkeypatch, raises=RuntimeError("unexpected"))
    with _client() as c:
        r = c.get("/portfolio/holdings")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert "读取持仓失败" in body["error"]


def test_route_empty_holdings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch_positions(monkeypatch, *[], cash=0.0)
    with _client() as c:
        r = c.get("/portfolio/holdings")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is True
    assert body["holdings"] == []
    assert body["summary"]["market_value"] == 0.0


def test_route_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = monkeypatch_positions(monkeypatch, _alpaca_row(), cash=1.0, count_calls=True)
    with _client() as c:
        c.get("/portfolio/holdings")
        c.get("/portfolio/holdings")
    assert calls["n"] == 1, "second call within TTL must hit cache, not the broker"


def test_route_force_bypasses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = monkeypatch_positions(monkeypatch, _alpaca_row(), cash=1.0, count_calls=True)
    with _client() as c:
        c.get("/portfolio/holdings")
        c.get("/portfolio/holdings?force=1")
    assert calls["n"] == 2


def test_route_profile_id_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def _get(profile_id=None, **o):
        seen["profile_id"] = profile_id
        return _positions_payload([])

    monkeypatch_positions_fn(monkeypatch, _get, cash=0.0)
    with _client() as c:
        c.get("/portfolio/holdings?profile_id=futu-live")
    assert seen["profile_id"] == "futu-live"


def test_route_account_failure_keeps_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_positions succeeds but get_account raises -> still connected, cash=None."""
    import src.api.portfolio_routes as pr

    monkeypatch.setattr(pr.trading_service, "get_positions",
                        lambda profile_id=None, **o: _positions_payload([_alpaca_row()]))

    def _account_boom(profile_id=None, **o):
        raise TimeoutError("account endpoint timed out")

    monkeypatch.setattr(pr.trading_service, "get_account", _account_boom)
    with _client() as c:
        r = c.get("/portfolio/holdings")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is True
    assert body["holdings"][0]["symbol"] == "AAPL"
    assert body["summary"]["cash"] is None  # account failed -> cash degrades


# ---------------------------------------------------------------------------
# Helpers for monkeypatching trading.service
# ---------------------------------------------------------------------------

def monkeypatch_positions(
    monkeypatch: pytest.MonkeyPatch,
    *rows: dict[str, Any],
    cash: float = 0.0,
    raises: BaseException | None = None,
    count_calls: bool = False,
) -> dict[str, int]:
    """Patch trading.service.get_positions/get_account via monkeypatch (auto-cleanup).

    Returns a {"n": int} counter when count_calls=True so callers can assert
    call counts (cache behavior).
    """
    counter = {"n": 0}

    def _get(profile_id=None, **o):
        if count_calls:
            counter["n"] += 1
        if raises is not None:
            raise raises
        return _positions_payload(list(rows))

    monkeypatch_positions_fn(monkeypatch, _get, cash=cash)
    return counter


def monkeypatch_positions_fn(monkeypatch: pytest.MonkeyPatch, get_fn, *, cash: float = 0.0) -> None:
    """Patch with caller-supplied get_positions; account returns a fixed cash.

    Uses ``monkeypatch.setattr`` so the real ``trading_service`` functions are
    restored after each test (no stale-patch leakage between tests).
    """
    import src.api.portfolio_routes as pr

    monkeypatch.setattr(pr.trading_service, "get_positions", get_fn)
    monkeypatch.setattr(pr.trading_service, "get_account",
                        lambda profile_id=None, **o: {"cash": cash})



# ---------------------------------------------------------------------------
# Adversarial-review hardening (NaN rejection, credential redaction in logs)
# ---------------------------------------------------------------------------

def test_normalize_row_rejects_nan_and_infinity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Broker stringified NaN/Infinity must degrade to None, not propagate."""
    h = _normalize_row({
        "symbol": "X", "quantity": "NaN", "current_price": "Infinity",
        "average_cost": "-Infinity",
    })
    assert h.quantity == 0.0  # NaN quantity -> _first returns None -> `or 0.0`
    assert h.current_price is None
    assert h.average_cost is None


def test_route_redacts_credential_in_exception_log(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """A broker SDK exception embedding an API key must not reach the log verbatim."""
    import src.api.portfolio_routes as pr
    import logging as _logging

    def _boom(profile_id=None, **o):
        raise RuntimeError("AuthenticationError apiKey AKIAIOSFODNN7EXAMPLE is invalid")

    monkeypatch.setattr(pr.trading_service, "get_positions", _boom)
    monkeypatch.setattr(pr.trading_service, "get_account", lambda profile_id=None, **o: {})
    with caplog.at_level(_logging.ERROR):
        with _client() as c:
            c.get("/portfolio/holdings")
    joined = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "AKIAIOSFODNN7EXAMPLE" not in joined, "API key leaked into log"
    assert "[redacted]" in joined
