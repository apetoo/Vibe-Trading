"""Tests for IndustryChainQueryTool."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.agent.tools import BaseTool
from src.industry_chain.tool import IndustryChainQueryTool


class TestIndustryChainQueryToolInit:
    """Verify the tool initialises correctly."""

    def test_is_basetool_subclass(self):
        """Tool must be a subclass of the project's BaseTool."""
        store = MagicMock()
        tool = IndustryChainQueryTool(store=store)
        assert isinstance(tool, BaseTool)

    def test_name_and_description(self):
        """Tool should have sensible defaults."""
        store = MagicMock()
        tool = IndustryChainQueryTool(store=store)
        assert tool.name == "get_industry_chain_context"
        assert tool.description
        assert "industry" in tool.description.lower() or "产业链" in tool.description

    def test_readonly_default(self):
        """Tool should be read-only by default."""
        store = MagicMock()
        tool = IndustryChainQueryTool(store=store)
        assert tool.is_readonly is True

    def test_parameters_schema(self):
        """Tool should have a parameters JSON Schema with code."""
        store = MagicMock()
        tool = IndustryChainQueryTool(store=store)
        assert "properties" in tool.parameters
        assert "code" in tool.parameters["properties"]
        assert tool.parameters["properties"]["code"]["type"] == "string"


class TestIndustryChainQueryToolExecute:
    """Functional tests for the execute method."""

    def test_returns_context_for_known_stock(self):
        """execute returns JSON with stock context when found."""
        store = MagicMock()
        store.get_stock_context.return_value = {
            "stock_name": "中际旭创",
            "stock_code": "300308.SZ",
            "stock_summary": "光模块龙头",
            "path": [
                {"name": "AI 算力", "node_type": "track"},
                {"name": "CPO", "node_type": "segment"},
            ],
            "competitors": [],
        }

        tool = IndustryChainQueryTool(store=store)
        result = tool.execute(code="300308.SZ")

        store.get_stock_context.assert_called_once_with("300308.SZ")
        parsed = json.loads(result)
        assert parsed["stock_name"] == "中际旭创"
        assert parsed["stock_summary"] == "光模块龙头"

    def test_returns_not_found_for_unknown_stock(self):
        """execute returns a JSON error when stock is not in the graph."""
        store = MagicMock()
        store.get_stock_context.return_value = None

        tool = IndustryChainQueryTool(store=store)
        result = tool.execute(code="000000.SZ")

        parsed = json.loads(result)
        assert parsed.get("found") is False
        assert "not found" in parsed.get("error", "").lower()

    def test_handles_store_exception(self):
        """execute returns a JSON error when the store raises."""
        store = MagicMock()
        store.get_stock_context.side_effect = ValueError("DB connection lost")

        tool = IndustryChainQueryTool(store=store)
        result = tool.execute(code="300308.SZ")

        parsed = json.loads(result)
        assert parsed.get("found") is False
        assert "DB connection lost" in parsed.get("error", "")

    def test_missing_code_returns_error(self):
        """execute returns error when code is not provided."""
        store = MagicMock()
        tool = IndustryChainQueryTool(store=store)
        result = tool.execute()

        parsed = json.loads(result)
        assert "code" in parsed.get("error", "").lower() or "required" in parsed.get("error", "").lower()

    def test_store_delegation(self):
        """Verify execute calls get_stock_context with the right code."""
        store = MagicMock()
        store.get_stock_context.return_value = {"stock_name": "Test", "stock_code": "000001.SZ"}

        tool = IndustryChainQueryTool(store=store)
        tool.execute(code="000001.SZ")

        store.get_stock_context.assert_called_once_with("000001.SZ")
