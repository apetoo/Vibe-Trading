"""Tests for industry chain models."""
from __future__ import annotations
import json
from src.industry_chain.models import NodeType, ChainNode, NodeVersion, Source, PendingChange


def test_node_type_values():
    assert NodeType.TRACK.value == "track"
    assert NodeType.SEGMENT.value == "segment"
    assert NodeType.LINK.value == "link"
    assert NodeType.STOCK.value == "stock"


def test_chain_node():
    n = ChainNode(node_id="nd_abc", parent_id=None, node_type=NodeType.TRACK, name="AI 算力产业链")
    assert n.node_id == "nd_abc"
    assert n.parent_id is None
    assert n.name == "AI 算力产业链"


def test_node_version_full():
    nv = NodeVersion(
        version_id="v1", node_id="nd_abc",
        summary="Test summary", narrative="Test narrative",
        market_size="500亿", growth_rate="20%",
        chain_position="核心", localization="45%",
        gross_margin="35%", tech_trend="趋势向好",
        macro_drivers=json.dumps(["AI需求爆发", "政策支持"]),
        financials=json.dumps({"revenue": 100, "profit": 20}),
        operating_metrics=json.dumps({"yield_rate": "95%"}),
        customer_structure=json.dumps({"客户A": "30%", "客户B": "20%"}),
        extra="{}", validation_status="unverified",
        snapshot_at="2026-06-22T00:00:00", snapshot_by="human",
    )
    assert nv.market_size == "500亿"
    assert nv.localization == "45%"
    assert nv.validation_status == "unverified"


def test_source():
    s = Source(source_id="src_1", version_id="v1", source_type="broker_report",
               title="中际旭创深度研报", publisher="中信证券", url="https://...",
               published_date="2026-06-01", cited_text="光模块龙头", created_at="2026-06-22T00:00:00")
    assert s.source_type == "broker_report"
    assert s.publisher == "中信证券"


def test_pending_change():
    pc = PendingChange(change_id="pc_1", node_id="nd_abc", is_new_node=False,
        proposed_fields=json.dumps({"market_size": "600亿"}),
        proposed_sources=json.dumps([{"source_type": "broker_report", "title": "研报"}]),
        rationale="基于最新研报", drafted_by="agent", status="draft",
        created_at="2026-06-22T00:00:00")
    assert pc.status == "draft"
    assert pc.drafted_by == "agent"
