"""Tests for IndustryChainDraftTool."""
from __future__ import annotations
from pathlib import Path
import json
import pytest
from src.industry_chain.store import IndustryChainStore
from src.industry_chain.models import NodeType
from src.tools.industry_chain_draft_tool import IndustryChainDraftTool


def _setup_store(tmp_path: Path) -> IndustryChainStore:
    store = IndustryChainStore(tmp_path / "ic.db")
    store.create_node(node_type=NodeType.STOCK, name="中际旭创", code="300308.SZ")
    return store


def test_draft_update_existing(tmp_path: Path):
    store = _setup_store(tmp_path)
    tool = IndustryChainDraftTool(store=store)
    result = tool.execute(
        node_id="", is_new_node="false",
        fields=json.dumps({"market_size": "600亿"}, ensure_ascii=False),
        sources=json.dumps([{"source_type": "broker_report", "title": "R"}], ensure_ascii=False),
        rationale="updated",
    )
    assert "change_id" in result


def test_draft_new_node(tmp_path: Path):
    store = _setup_store(tmp_path)
    tool = IndustryChainDraftTool(store=store)
    result = tool.execute(
        node_id="", is_new_node="true",
        new_node_name="新易盛", new_node_type="stock", new_node_code="300502.SZ",
        fields=json.dumps({"summary": "光模块"}),
        sources=json.dumps([{"source_type": "broker_report", "title": "R"}]),
        rationale="new stock",
    )
    assert "change_id" in result


def test_draft_rejects_unknown_field(tmp_path: Path):
    store = _setup_store(tmp_path)
    tool = IndustryChainDraftTool(store=store)
    result = tool.execute(
        node_id="", is_new_node="false",
        fields=json.dumps({"unknown_field": "value"}),
        sources=json.dumps([{"source_type": "broker_report", "title": "R"}]),
        rationale="test",
    )
    assert "error" in result or "unknown" in result.lower()
