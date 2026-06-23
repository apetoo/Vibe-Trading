"""Tests for industry-chain context injection in ContextBuilder.

Verifies that build_messages injects ONLY structure (topology) fields and
never leaks dynamic fields (market_size, localization, financials, etc.).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.context import ContextBuilder
from src.agent.memory import WorkspaceMemory
from src.agent.tools import ToolRegistry


# ── helpers ──────────────────────────────────────────────────────────

def _fake_graph(*, include_market_size: bool = False) -> dict:
    """Return a dict matching get_node_context_graph's return shape."""
    ctx: dict = {
        "stock_name": "中际旭创",
        "stock_code": "300308.SZ",
        "node_id": "stock_abc123",
        "path": [
            {"node_id": "t1", "name": "AI 算力", "node_type": "track", "summary": ""},
            {"node_id": "s1", "name": "CPO", "node_type": "segment", "summary": ""},
            {"node_id": "l1", "name": "光模块", "node_type": "link", "summary": "光模块环节"},
            {"node_id": "stock_abc123", "name": "中际旭创", "node_type": "stock", "summary": "中际旭创简介"},
        ],
        "competitors": [
            {"node_id": "c1", "name": "新易盛", "code": "300502.SZ"},
            {"node_id": "c2", "name": "华工科技", "code": "000988.SZ"},
            {"node_id": "c3", "name": "光迅科技", "code": "002281.SZ"},
        ],
        "upstream": [
            {"other_id": "e1", "other_name": "光芯片（源杰）", "other_type": "external",
             "source_id": "e1", "target_id": "stock_abc123", "relation_type": "supplier"},
            {"other_id": "e2", "other_name": "硅光组件", "other_type": "external",
             "source_id": "e2", "target_id": "stock_abc123", "relation_type": "supplier"},
        ],
        "downstream": [
            {"other_id": "e3", "other_name": "谷歌云", "other_type": "external",
             "source_id": "stock_abc123", "target_id": "e3", "relation_type": "customer"},
            {"other_id": "e4", "other_name": "亚马逊AWS", "other_type": "external",
             "source_id": "stock_abc123", "target_id": "e4", "relation_type": "customer"},
        ],
        "substitutes": [
            {"other_id": "e5", "other_name": "共封装光学 vs 板载光学", "other_type": "external",
             "source_id": "stock_abc123", "target_id": "e5", "relation_type": "substitute"},
        ],
        "related": [
            {"other_id": "e7", "other_name": "AI 算力链", "other_type": "industry",
             "source_id": "stock_abc123", "target_id": "e7", "relation_type": "related"},
        ],
        "certified_by": [
            {"other_id": "e6", "other_name": "英伟达", "other_type": "external",
             "source_id": "stock_abc123", "target_id": "e6", "relation_type": "certified_by"},
        ],
        "business_lines": [
            {"other_id": "i1", "other_name": "数据中心光模块", "other_type": "industry",
             "source_id": "stock_abc123", "target_id": "i1", "relation_type": "segment_of"},
        ],
    }
    if include_market_size:
        ctx["market_size"] = "500 亿美元"
        ctx["growth_rate"] = "15% CAGR"
        ctx["localization"] = "30%"
        ctx["gross_margin"] = "35%"
        ctx["tech_trend"] = "1.6T 光模块"
        ctx["financials"] = {"revenue": "100亿", "net_profit": "20亿"}
        ctx["operating_metrics"] = {"roe": "15%"}
        ctx["customer_structure"] = {"top5": "80%"}
        ctx["stock_summary"] = "光模块龙头"
    return ctx


def _build_context_builder() -> ContextBuilder:
    """Build a minimal ContextBuilder with mocked dependencies."""
    registry = ToolRegistry()
    memory = WorkspaceMemory(run_dir="/tmp/test")
    # Mock skills_loader: needs .skills (iterable) and .get_descriptions()
    skills_loader = MagicMock()
    skills_loader.skills = {}
    skills_loader.get_descriptions.return_value = ""
    return ContextBuilder(registry=registry, memory=memory, skills_loader=skills_loader)


# ── tests ────────────────────────────────────────────────────────────

class TestStructureInjection:
    """Structure fields are injected; dynamic fields are absent."""

    def test_stock_and_chain_lines_always_present(self):
        """Stock and Chain lines are always output."""
        builder = _build_context_builder()
        fake = _fake_graph()

        mock_store = MagicMock()
        mock_store.get_node_code_index.return_value = {"300308.SZ"}
        mock_store.get_node_context_graph.return_value = fake

        with patch("src.industry_chain.store.IndustryChainStore",
                   return_value=mock_store):
            messages = builder.build_messages("分析 300308.SZ 的产业链")

        user_content = messages[-1]["content"]
        assert "<industry-chain-context>" in user_content
        assert "Stock: 中际旭创 (300308.SZ)" in user_content
        assert "Chain: AI 算力" in user_content
        assert "CPO" in user_content
        assert "光模块" in user_content
        assert "中际旭创" in user_content

    def test_upstream_downstream_injected(self):
        """Upstream and Downstream lines use other_name."""
        builder = _build_context_builder()
        fake = _fake_graph()

        mock_store = MagicMock()
        mock_store.get_node_code_index.return_value = {"300308.SZ"}
        mock_store.get_node_context_graph.return_value = fake

        with patch("src.industry_chain.store.IndustryChainStore",
                   return_value=mock_store):
            messages = builder.build_messages("分析 300308.SZ")

        user_content = messages[-1]["content"]
        assert "Upstream: 光芯片（源杰）, 硅光组件" in user_content
        assert "Downstream: 谷歌云, 亚马逊AWS" in user_content

    def test_competitors_use_name_key(self):
        """Competitors use the 'name' key, not 'other_name'."""
        builder = _build_context_builder()
        fake = _fake_graph()

        mock_store = MagicMock()
        mock_store.get_node_code_index.return_value = {"300308.SZ"}
        mock_store.get_node_context_graph.return_value = fake

        with patch("src.industry_chain.store.IndustryChainStore",
                   return_value=mock_store):
            messages = builder.build_messages("分析 300308.SZ")

        user_content = messages[-1]["content"]
        assert "Competitors: 新易盛, 华工科技, 光迅科技" in user_content

    def test_certified_by_and_business_lines_injected(self):
        """Certified by and Business lines use other_name."""
        builder = _build_context_builder()
        fake = _fake_graph()

        mock_store = MagicMock()
        mock_store.get_node_code_index.return_value = {"300308.SZ"}
        mock_store.get_node_context_graph.return_value = fake

        with patch("src.industry_chain.store.IndustryChainStore",
                   return_value=mock_store):
            messages = builder.build_messages("分析 300308.SZ")

        user_content = messages[-1]["content"]
        assert "Certified by: 英伟达" in user_content
        assert "Business lines: 数据中心光模块" in user_content

    def test_substitutes_injected(self):
        """Substitutes use other_name."""
        builder = _build_context_builder()
        fake = _fake_graph()

        mock_store = MagicMock()
        mock_store.get_node_code_index.return_value = {"300308.SZ"}
        mock_store.get_node_context_graph.return_value = fake

        with patch("src.industry_chain.store.IndustryChainStore",
                   return_value=mock_store):
            messages = builder.build_messages("分析 300308.SZ")

        user_content = messages[-1]["content"]
        assert "Substitutes: 共封装光学 vs 板载光学" in user_content

    def test_related_injected(self):
        """Related edges use other_name."""
        builder = _build_context_builder()
        fake = _fake_graph()

        mock_store = MagicMock()
        mock_store.get_node_code_index.return_value = {"300308.SZ"}
        mock_store.get_node_context_graph.return_value = fake

        with patch("src.industry_chain.store.IndustryChainStore",
                   return_value=mock_store):
            messages = builder.build_messages("分析 300308.SZ")

        user_content = messages[-1]["content"]
        assert "Related: AI 算力链" in user_content

    def test_empty_categories_not_output(self):
        """Empty categories (related=[]) produce no line."""
        builder = _build_context_builder()
        fake = _fake_graph()
        fake["related"] = []
        fake["certified_by"] = []
        fake["business_lines"] = []
        fake["substitutes"] = []
        fake["upstream"] = []
        fake["downstream"] = []
        fake["competitors"] = []

        mock_store = MagicMock()
        mock_store.get_node_code_index.return_value = {"300308.SZ"}
        mock_store.get_node_context_graph.return_value = fake

        with patch("src.industry_chain.store.IndustryChainStore",
                   return_value=mock_store):
            messages = builder.build_messages("分析 300308.SZ")

        user_content = messages[-1]["content"]
        assert "Upstream:" not in user_content
        assert "Downstream:" not in user_content
        assert "Substitutes:" not in user_content
        assert "Competitors:" not in user_content
        assert "Certified by:" not in user_content
        assert "Business lines:" not in user_content
        # Stock and Chain still present
        assert "Stock: 中际旭创 (300308.SZ)" in user_content
        assert "Chain:" in user_content


class TestDynamicFieldsAbsent:
    """Dynamic fields must NEVER appear in injected context."""

    DYNAMIC_TERMS = [
        "Market size",
        "market_size",
        "Localization",
        "localization",
        "Gross margin",
        "gross_margin",
        "Tech trend",
        "tech_trend",
        "Growth rate",
        "growth_rate",
        "financials",
        "operating_metrics",
        "customer_structure",
        "stock_summary",
    ]

    def test_no_dynamic_fields_in_normal_output(self):
        """Even with a clean graph, no dynamic field names leak."""
        builder = _build_context_builder()
        fake = _fake_graph()

        mock_store = MagicMock()
        mock_store.get_node_code_index.return_value = {"300308.SZ"}
        mock_store.get_node_context_graph.return_value = fake

        with patch("src.industry_chain.store.IndustryChainStore",
                   return_value=mock_store):
            messages = builder.build_messages("分析 300308.SZ")

        user_content = messages[-1]["content"]
        for term in self.DYNAMIC_TERMS:
            assert term not in user_content, (
                f"Dynamic term {term!r} should not appear in injected context"
            )

    def test_defensive_market_size_not_injected(self):
        """If get_node_context_graph accidentally returns market_size,
        the injection must still NOT output it."""
        builder = _build_context_builder()
        fake = _fake_graph(include_market_size=True)

        mock_store = MagicMock()
        mock_store.get_node_code_index.return_value = {"300308.SZ"}
        mock_store.get_node_context_graph.return_value = fake

        with patch("src.industry_chain.store.IndustryChainStore",
                   return_value=mock_store):
            messages = builder.build_messages("分析 300308.SZ")

        user_content = messages[-1]["content"]
        for term in self.DYNAMIC_TERMS:
            assert term not in user_content, (
                f"Dynamic term {term!r} leaked into injected context (defensive check)"
            )


class TestInjectionGuards:
    """Try/except silent fallback, break after first match, double-inject guard."""

    def test_no_injection_when_code_not_in_index(self):
        """When code is not in the code index, no injection happens."""
        builder = _build_context_builder()

        mock_store = MagicMock()
        mock_store.get_node_code_index.return_value = set()  # empty

        with patch("src.industry_chain.store.IndustryChainStore",
                   return_value=mock_store):
            messages = builder.build_messages("分析 300308.SZ")

        user_content = messages[-1]["content"]
        assert "<industry-chain-context>" not in user_content

    def test_no_injection_when_get_node_context_graph_returns_none(self):
        """When get_node_context_graph returns None, no injection."""
        builder = _build_context_builder()

        mock_store = MagicMock()
        mock_store.get_node_code_index.return_value = {"300308.SZ"}
        mock_store.get_node_context_graph.return_value = None

        with patch("src.industry_chain.store.IndustryChainStore",
                   return_value=mock_store):
            messages = builder.build_messages("分析 300308.SZ")

        user_content = messages[-1]["content"]
        assert "<industry-chain-context>" not in user_content

    def test_first_match_only_break(self):
        """Only the first matching stock code gets injected (break after first)."""
        builder = _build_context_builder()
        fake = _fake_graph()

        mock_store = MagicMock()
        mock_store.get_node_code_index.return_value = {"300308.SZ", "300502.SZ"}
        mock_store.get_node_context_graph.return_value = fake

        with patch("src.industry_chain.store.IndustryChainStore",
                   return_value=mock_store):
            messages = builder.build_messages("分析 300308.SZ 和 300502.SZ")

        user_content = messages[-1]["content"]
        # Should have exactly one <industry-chain-context> block
        assert user_content.count("<industry-chain-context>") == 1
        # First match is 300308.SZ
        assert "Stock: 中际旭创 (300308.SZ)" in user_content

    def test_double_inject_guard(self):
        """If enriched already starts with <industry-chain-context>, skip injection."""
        builder = _build_context_builder()

        mock_store = MagicMock()
        mock_store.get_node_code_index.return_value = {"300308.SZ"}

        pre_enriched = "<industry-chain-context>\nStock: SomeCorp (000001.SZ)\n</industry-chain-context>\n\n分析 300308.SZ"

        with patch("src.industry_chain.store.IndustryChainStore",
                   return_value=mock_store):
            messages = builder.build_messages(pre_enriched)

        user_content = messages[-1]["content"]
        # Should have exactly one block (the pre-existing one, not re-injected)
        assert user_content.count("<industry-chain-context>") == 1
        assert "Stock: SomeCorp" in user_content

    def test_silent_fallback_on_store_error(self):
        """When store blows up, injection is silently skipped."""
        builder = _build_context_builder()

        mock_store = MagicMock()
        mock_store.get_node_code_index.side_effect = RuntimeError("DB down")

        with patch("src.industry_chain.store.IndustryChainStore",
                   return_value=mock_store):
            messages = builder.build_messages("分析 300308.SZ")

        user_content = messages[-1]["content"]
        assert "<industry-chain-context>" not in user_content
        # Original user message still present
        assert "分析 300308.SZ" in user_content