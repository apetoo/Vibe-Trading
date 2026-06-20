"""Tests for the manual portfolio holdings store.

The store is a small file-backed model the user maintains manually (or via
trade_journal CSV import / agent conversation). It is the *source of truth*
for the holdings menu when no broker is connected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from src.portfolio.manual_holdings import (  # noqa: E402
    ManualHolding,
    add_lot,
    delete_holding,
    list_holdings,
    replace_all,
    set_holding,
)


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    """Point the store at a tmp_path file so tests don't touch ~/.vibe-trading."""
    target = tmp_path / "portfolio.json"
    monkeypatch.setenv("VIBE_TRADING_PORTFOLIO_PATH", str(target))
    yield target


def test_list_empty_when_no_file(tmp_store):
    assert list_holdings() == []


def test_set_holding_creates_file(tmp_store):
    set_holding("AAPL", quantity=100, average_cost=150.0, name="Apple Inc.")
    holdings = list_holdings()
    assert len(holdings) == 1
    h = holdings[0]
    assert h.symbol == "AAPL"
    assert h.quantity == 100.0
    assert h.average_cost == 150.0
    assert h.name == "Apple Inc."
    assert tmp_store.exists()


def test_set_holding_updates_existing(tmp_store):
    set_holding("AAPL", quantity=100, average_cost=150.0)
    set_holding("AAPL", quantity=50, average_cost=200.0)
    holdings = list_holdings()
    assert len(holdings) == 1
    assert holdings[0].quantity == 50.0
    assert holdings[0].average_cost == 200.0


def test_delete_holding(tmp_store):
    set_holding("AAPL", quantity=100, average_cost=150.0)
    set_holding("TSLA", quantity=50, average_cost=200.0)
    delete_holding("AAPL")
    holdings = list_holdings()
    assert len(holdings) == 1
    assert holdings[0].symbol == "TSLA"


def test_delete_missing_holding_no_error(tmp_store):
    set_holding("AAPL", quantity=100, average_cost=150.0)
    delete_holding("NOT_THERE")  # should be a no-op, not raise
    assert len(list_holdings()) == 1


def test_add_lot_to_existing_recomputes_avg_cost(tmp_store):
    """Adding 100 @ 150 then 50 @ 180 -> 150 @ 160 (weighted avg)."""
    set_holding("AAPL", quantity=100, average_cost=150.0)
    add_lot("AAPL", quantity=50, price=180.0)
    holdings = list_holdings()
    assert len(holdings) == 1
    h = holdings[0]
    assert h.quantity == 150.0
    assert h.average_cost == pytest.approx(160.0, abs=0.01)  # (100*150 + 50*180)/150


def test_add_lot_creates_new_holding(tmp_store):
    add_lot("NEWCO", quantity=42, price=10.0)
    holdings = list_holdings()
    assert len(holdings) == 1
    assert holdings[0].symbol == "NEWCO"
    assert holdings[0].quantity == 42.0
    assert holdings[0].average_cost == 10.0


def test_add_lot_negative_quantity_reduces(tmp_store):
    """Negative qty represents a sale; avg cost stays, qty drops."""
    set_holding("AAPL", quantity=100, average_cost=150.0)
    add_lot("AAPL", quantity=-30, price=200.0)  # sell 30 at 200
    holdings = list_holdings()
    assert holdings[0].quantity == 70.0
    assert holdings[0].average_cost == 150.0  # cost basis unchanged on sells


def test_add_lot_sells_all_removes_holding(tmp_store):
    set_holding("AAPL", quantity=100, average_cost=150.0)
    add_lot("AAPL", quantity=-100, price=200.0)
    assert list_holdings() == []


def test_add_lot_oversell_clamps_to_zero(tmp_store):
    """Selling more than held: clamp to 0 and remove (don't go negative)."""
    set_holding("AAPL", quantity=10, average_cost=150.0)
    add_lot("AAPL", quantity=-50, price=200.0)
    assert list_holdings() == []


def test_replace_all_overwrites(tmp_store):
    set_holding("AAPL", quantity=100, average_cost=150.0)
    replace_all([
        ManualHolding(symbol="TSLA", quantity=50, average_cost=200.0, name="Tesla"),
        ManualHolding(symbol="NVDA", quantity=10, average_cost=400.0, name=""),
    ])
    holdings = list_holdings()
    assert len(holdings) == 2
    assert {h.symbol for h in holdings} == {"TSLA", "NVDA"}


def test_replace_all_empty_clears(tmp_store):
    set_holding("AAPL", quantity=100, average_cost=150.0)
    replace_all([])
    assert list_holdings() == []


def test_symbol_normalized_to_uppercase(tmp_store):
    set_holding("aapl", quantity=100, average_cost=150.0)
    holdings = list_holdings()
    assert holdings[0].symbol == "AAPL"


def test_corrupt_file_returns_empty(tmp_store):
    """A malformed JSON file should not crash callers."""
    tmp_store.write_text("{not valid json", encoding="utf-8")
    assert list_holdings() == []


def test_set_holding_zero_quantity_removes(tmp_store):
    set_holding("AAPL", quantity=100, average_cost=150.0)
    set_holding("AAPL", quantity=0, average_cost=150.0)
    assert list_holdings() == []


# ---------------------------------------------------------------------------
# CSV-import flow (trade_journal -> manual_holdings)
# ---------------------------------------------------------------------------

def test_compute_holdings_from_unmatched_buys():
    """FIFO leaves unmatched buys; aggregate them into ManualHolding rows.

    Bought 100 AAPL @ 150, then 50 @ 180. Sold 50 @ 200 (matches first lot).
    Remaining: 50 AAPL @ 150 (rest of first lot) + 50 AAPL @ 180 = 100 @ 165.
    """
    import pandas as pd
    from src.portfolio.manual_holdings import compute_holdings_from_journal

    df = pd.DataFrame([
        {"symbol": "AAPL", "side": "buy", "quantity": 100, "price": 150.0,
         "fee": 0.0, "datetime": pd.Timestamp("2024-01-01")},
        {"symbol": "AAPL", "side": "buy", "quantity": 50, "price": 180.0,
         "fee": 0.0, "datetime": pd.Timestamp("2024-02-01")},
        {"symbol": "AAPL", "side": "sell", "quantity": 50, "price": 200.0,
         "fee": 0.0, "datetime": pd.Timestamp("2024-03-01")},
    ]).sort_values("datetime").reset_index(drop=True)

    holdings = compute_holdings_from_journal(df)
    assert len(holdings) == 1
    h = holdings[0]
    assert h.symbol == "AAPL"
    assert h.quantity == 100.0
    # 50 left from first lot @ 150 + 50 from second lot @ 180 -> avg 165
    assert h.average_cost == pytest.approx(165.0, abs=0.01)


def test_compute_holdings_fully_closed_position(tmp_store):
    """Buy then sell same quantity -> no remaining holding."""
    import pandas as pd
    from src.portfolio.manual_holdings import compute_holdings_from_journal

    df = pd.DataFrame([
        {"symbol": "AAPL", "side": "buy", "quantity": 100, "price": 150.0,
         "fee": 0.0, "datetime": pd.Timestamp("2024-01-01")},
        {"symbol": "AAPL", "side": "sell", "quantity": 100, "price": 200.0,
         "fee": 0.0, "datetime": pd.Timestamp("2024-02-01")},
    ]).sort_values("datetime").reset_index(drop=True)

    assert compute_holdings_from_journal(df) == []


def test_compute_holdings_multiple_symbols(tmp_store):
    """Independent FIFO per symbol; only unmatched lots become holdings."""
    import pandas as pd
    from src.portfolio.manual_holdings import compute_holdings_from_journal

    df = pd.DataFrame([
        {"symbol": "AAPL", "side": "buy", "quantity": 100, "price": 150.0,
         "fee": 0.0, "datetime": pd.Timestamp("2024-01-01")},
        {"symbol": "TSLA", "side": "buy", "quantity": 20, "price": 250.0,
         "fee": 0.0, "datetime": pd.Timestamp("2024-01-02")},
        {"symbol": "TSLA", "side": "sell", "quantity": 20, "price": 300.0,
         "fee": 0.0, "datetime": pd.Timestamp("2024-02-01")},
    ]).sort_values("datetime").reset_index(drop=True)

    holdings = compute_holdings_from_journal(df)
    assert len(holdings) == 1
    assert holdings[0].symbol == "AAPL"
    assert holdings[0].quantity == 100.0
    assert holdings[0].average_cost == 150.0


def test_compute_holdings_empty_dataframe(tmp_store):
    import pandas as pd
    from src.portfolio.manual_holdings import compute_holdings_from_journal

    assert compute_holdings_from_journal(pd.DataFrame()) == []


# ---------------------------------------------------------------------------
# Integration: trade_journal_tool wires into the manual store
# ---------------------------------------------------------------------------

def test_analyze_trade_journal_populates_holdings(tmp_path, tmp_store, monkeypatch):
    """End-to-end: a CSV with unmatched buys -> portfolio.json gets them."""
    csv_path = tmp_path / "trades.csv"
    csv_path.write_text(
        "成交时间,证券代码,操作,成交数量,成交价格\n"
        "2024-01-01 09:30:00,600519,买入,100,1500\n"
        "2024-02-01 10:00:00,600519,卖出,50,1700\n",
        encoding="utf-8",
    )

    # Permit the tmp uploads root for safe_user_path
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))

    from src.tools.trade_journal_tool import analyze_trade_journal

    result_json = analyze_trade_journal(str(csv_path), analysis_type="profile")
    import json as _json
    result = _json.loads(result_json)
    assert result["status"] == "ok", result

    holdings = list_holdings()
    assert len(holdings) == 1
    h = holdings[0]
    assert h.symbol.endswith("600519.SH")
    assert h.quantity == 50.0
    assert h.average_cost == pytest.approx(1500.0, abs=0.01)


def test_analyze_trade_journal_opt_out(tmp_path, tmp_store, monkeypatch):
    """update_holdings=False leaves portfolio.json untouched."""
    csv_path = tmp_path / "trades.csv"
    csv_path.write_text(
        "成交时间,证券代码,操作,成交数量,成交价格\n"
        "2024-01-01 09:30:00,600519,买入,100,1500\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))

    from src.tools.trade_journal_tool import analyze_trade_journal

    analyze_trade_journal(str(csv_path), analysis_type="profile", update_holdings=False)
    assert list_holdings() == []
