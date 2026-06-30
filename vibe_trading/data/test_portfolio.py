"""Tests for portfolio data layer."""
import pytest
from vibe_trading.data.portfolio import HoldingItem, PortfolioSummary, get_portfolio_summary


class TestHoldingItem:
    def test_create_holding(self):
        """Test creating a holding item with all fields."""
        h = HoldingItem(
            symbol="AAPL",
            name="Apple Inc.",
            quantity=100,
            cost_price=150.0,
            current_price=175.5,
            market_value=17550.0,
            pnl=2550.0,
            pnl_percent=17.0,
        )
        assert h.symbol == "AAPL"
        assert h.name == "Apple Inc."
        assert h.quantity == 100
        assert h.cost_price == 150.0
        assert h.current_price == 175.5
        assert h.market_value == 17550.0
        assert h.pnl == 2550.0
        assert h.pnl_percent == 17.0

    def test_holding_with_zero_quantity(self):
        """Test holding with zero quantity."""
        h = HoldingItem(
            symbol="AAPL", name="Apple Inc.", quantity=0,
            cost_price=150.0, current_price=175.5,
            market_value=0.0, pnl=0.0, pnl_percent=0.0,
        )
        assert h.market_value == 0.0
        assert h.pnl == 0.0

    def test_holding_with_negative_pnl(self):
        """Test holding with negative P&L."""
        h = HoldingItem(
            symbol="TSLA", name="Tesla", quantity=10,
            cost_price=300.0, current_price=250.0,
            market_value=2500.0, pnl=-500.0, pnl_percent=-16.67,
        )
        assert h.pnl < 0
        assert h.pnl_percent < 0

    def test_holding_with_positive_pnl(self):
        """Test holding with positive P&L."""
        h = HoldingItem(
            symbol="NVDA", name="NVIDIA", quantity=5,
            cost_price=200.0, current_price=400.0,
            market_value=2000.0, pnl=1000.0, pnl_percent=100.0,
        )
        assert h.pnl > 0
        assert h.pnl_percent > 0


class TestPortfolioSummary:
    def test_summary_single_holding(self):
        """Test summary calculation with single holding."""
        holdings = [
            HoldingItem("AAPL", "Apple Inc.", 100, 150.0, 175.5, 17550.0, 2550.0, 17.0),
        ]
        summary = get_portfolio_summary(holdings)
        assert summary.total_market_value == 17550.0
        assert summary.total_cost == 15000.0
        assert summary.total_pnl == 2550.0

    def test_summary_multiple_holdings(self):
        """Test summary calculation with multiple holdings."""
        holdings = [
            HoldingItem("AAPL", "Apple Inc.", 100, 150.0, 175.5, 17550.0, 2550.0, 17.0),
            HoldingItem("TSLA", "Tesla", 10, 300.0, 250.0, 2500.0, -500.0, -16.67),
            HoldingItem("NVDA", "NVIDIA", 5, 200.0, 400.0, 2000.0, 1000.0, 100.0),
        ]
        summary = get_portfolio_summary(holdings)
        assert summary.total_market_value == 22050.0  # 17550 + 2500 + 2000
        assert summary.total_cost == 19000.0  # 15000 + 3000 + 1000
        assert summary.total_pnl == 3050.0  # 2550 - 500 + 1000

    def test_summary_empty_holdings(self):
        """Test summary with empty holdings list."""
        summary = get_portfolio_summary([])
        assert summary.total_market_value == 0.0
        assert summary.total_cost == 0.0
        assert summary.total_pnl == 0.0

    def test_summary_all_negative(self):
        """Test summary when all holdings are losing."""
        holdings = [
            HoldingItem("A", "A", 10, 100.0, 50.0, 500.0, -500.0, -50.0),
            HoldingItem("B", "B", 5, 200.0, 100.0, 500.0, -500.0, -50.0),
        ]
        summary = get_portfolio_summary(holdings)
        assert summary.total_pnl < 0
        assert summary.total_market_value == 1000.0


class TestGetHoldings:
    def test_get_holdings_returns_list(self):
        """Test that get_holdings returns a list."""
        from vibe_trading.data.portfolio import get_holdings
        holdings = get_holdings()
        assert isinstance(holdings, list)
        for h in holdings:
            assert isinstance(h, HoldingItem)

    def test_get_holdings_with_valid_data(self):
        """Test get_holdings returns valid holdings with all required fields."""
        from vibe_trading.data.portfolio import get_holdings
        holdings = get_holdings()
        for h in holdings:
            assert h.symbol
            assert h.name
            assert h.quantity >= 0
            assert h.cost_price >= 0
            assert h.current_price >= 0
            assert h.market_value >= 0
