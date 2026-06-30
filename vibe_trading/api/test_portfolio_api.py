"""Tests for portfolio API endpoints."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create test client for the FastAPI app."""
    from vibe_trading.api.main import app
    return TestClient(app)


class TestPortfolioAPI:
    def test_get_holdings_success(self, client):
        """Test that holdings endpoint returns 200 with correct structure."""
        response = client.get("/api/portfolio/holdings")
        assert response.status_code == 200
        data = response.json()
        assert "holdings" in data
        assert "summary" in data
        assert isinstance(data["holdings"], list)
        assert isinstance(data["summary"], dict)

    def test_holdings_item_structure(self, client):
        """Test that each holding item has all required fields."""
        response = client.get("/api/portfolio/holdings")
        data = response.json()
        required_fields = {"symbol", "name", "quantity", "cost_price",
                          "current_price", "market_value", "pnl", "pnl_percent"}
        for item in data["holdings"]:
            assert required_fields.issubset(item.keys()), f"Missing fields in {item}"

    def test_summary_structure(self, client):
        """Test that summary has all required fields."""
        response = client.get("/api/portfolio/holdings")
        data = response.json()
        summary = data["summary"]
        assert "total_market_value" in summary
        assert "total_cost" in summary
        assert "total_pnl" in summary

    def test_holdings_values_positive(self, client):
        """Test that holdings values are non-negative where expected."""
        response = client.get("/api/portfolio/holdings")
        data = response.json()
        for item in data["holdings"]:
            assert item["quantity"] >= 0
            assert item["cost_price"] >= 0
            assert item["current_price"] >= 0
            assert item["market_value"] >= 0

    def test_summary_calculation(self, client):
        """Test that summary calculations are correct."""
        response = client.get("/api/portfolio/holdings")
        data = response.json()
        summary = data["summary"]

        # Verify that summary matches individual items
        expected_market_value = sum(h["market_value"] for h in data["holdings"])
        expected_pnl = sum(h["pnl"] for h in data["holdings"])

        assert summary["total_market_value"] == pytest.approx(expected_market_value, rel=1e-2)
        assert summary["total_pnl"] == pytest.approx(expected_pnl, rel=1e-2)

    def test_empty_holdings_scenario(self, client, monkeypatch):
        """Test that endpoint handles empty holdings gracefully."""
        from vibe_trading.data import portfolio as portfolio_module

        def mock_empty():
            return []

        monkeypatch.setattr(portfolio_module, "get_holdings", mock_empty)
        response = client.get("/api/portfolio/holdings")
        assert response.status_code == 200
        data = response.json()
        assert data["holdings"] == []
        assert data["summary"]["total_market_value"] == 0.0
        assert data["summary"]["total_pnl"] == 0.0
