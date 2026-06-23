"""Tests for IndustryChainStore (SQLite)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.industry_chain.models import NodeType, ChainNode, NodeVersion, Source, PendingChange
from src.industry_chain.store import IndustryChainStore


def _store(tmp_path: Path) -> IndustryChainStore:
    return IndustryChainStore(tmp_path / "industry_chain.db")


class TestInit:
    def test_db_created(self, tmp_path: Path):
        db = tmp_path / "industry_chain.db"
        assert not db.exists()
        IndustryChainStore(db).close()
        assert db.exists()

    def test_user_version(self, tmp_path: Path):
        store = _store(tmp_path)
        row = store._conn.execute("PRAGMA user_version").fetchone()
        assert row[0] == 2
        store.close()

    def test_wal_mode(self, tmp_path: Path):
        store = _store(tmp_path)
        row = store._conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0].lower() == "wal"
        store.close()

    def test_tables_exist(self, tmp_path: Path):
        store = _store(tmp_path)
        tables = {r[0] for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        for name in ("nodes", "node_versions", "node_current", "sources", "pending_changes", "node_relations"):
            assert name in tables, f"table {name!r} missing"
        store.close()


class TestNodes:
    def test_create_and_get_node(self, tmp_path: Path):
        store = _store(tmp_path)
        nid = store.create_node(parent_id=None, node_type=NodeType.TRACK, name="AI 算力产业链")
        node = store.get_node(nid)
        assert node is not None
        assert node.name == "AI 算力产业链"
        assert node.node_type == NodeType.TRACK
        assert node.parent_id is None
        store.close()

    def test_update_node_creates_version(self, tmp_path: Path):
        store = _store(tmp_path)
        nid = store.create_node(parent_id=None, node_type=NodeType.SEGMENT, name="CPO")
        v1 = store.update_node(nid, summary="CPO 共封装光学")
        current = store.get_node_current(nid)
        assert current is not None
        assert current.summary == "CPO 共封装光学"
        assert current.version_id == v1
        versions = store.list_versions(nid)
        assert len(versions) == 1
        store.close()

    def test_update_node_twice_two_versions(self, tmp_path: Path):
        store = _store(tmp_path)
        nid = store.create_node(parent_id=None, node_type=NodeType.SEGMENT, name="CPO")
        store.update_node(nid, summary="v1")
        store.update_node(nid, summary="v2")
        versions = store.list_versions(nid)
        assert len(versions) == 2
        current = store.get_node_current(nid)
        assert current is not None
        assert current.summary == "v2"
        store.close()

    def test_delete_node_has_children_fails(self, tmp_path: Path):
        store = _store(tmp_path)
        pid = store.create_node(parent_id=None, node_type=NodeType.TRACK, name="Track")
        cid = store.create_node(parent_id=pid, node_type=NodeType.SEGMENT, name="Segment")
        with pytest.raises(ValueError, match="children"):
            store.delete_node(pid)
        store.delete_node(cid)
        store.delete_node(pid)  # no longer has children
        store.close()

    def test_list_children(self, tmp_path: Path):
        store = _store(tmp_path)
        pid = store.create_node(node_type=NodeType.TRACK, name="T")
        c1 = store.create_node(parent_id=pid, node_type=NodeType.SEGMENT, name="A")
        c2 = store.create_node(parent_id=pid, node_type=NodeType.SEGMENT, name="B")
        children = store.list_children(pid)
        assert len(children) == 2
        store.close()


class TestChangeLifecycle:
    def test_draft_and_accept_change(self, tmp_path: Path):
        store = _store(tmp_path)
        nid = store.create_node(node_type=NodeType.STOCK, name="中际旭创", code="300308.SZ")
        change_id = store.draft_change(
            node_id=nid,
            proposed_fields=json.dumps({"market_size": "600亿"}),
            proposed_sources=json.dumps([{"source_type": "broker_report", "title": "研报"}]),
            rationale="更新",
        )
        pending = store.list_pending()
        assert len(pending) == 1
        assert pending[0].status == "draft"

        new_vid = store.accept_change(change_id, snapshot_by="human")
        assert new_vid is not None
        current = store.get_node_current(nid)
        assert current is not None
        assert current.market_size == "600亿"
        accepted = store.list_pending(status=None)
        assert any(pc.status == "accepted" for pc in accepted)
        store.close()

    def test_accept_change_rollback_on_failure(self, tmp_path: Path):
        """T-tx: simulate failure mid-accept to verify no partial state."""
        store = _store(tmp_path)
        nid = store.create_node(node_type=NodeType.STOCK, name="Test", code="000001.SZ")
        store.update_node(nid, summary="original")

        # Draft a change and accept it
        change_id = store.draft_change(
            node_id=nid,
            proposed_fields=json.dumps({"summary": "new"}),
            proposed_sources=json.dumps([{"source_type": "broker_report", "title": "t"}]),
            rationale="test",
        )
        store.accept_change(change_id, snapshot_by="human")

        # Second accept on the same change should fail (not in draft status)
        # This triggers ValueError inside accept_change
        with pytest.raises(ValueError):
            store.accept_change(change_id, snapshot_by="human")

        # Verify no partial state: original node's current should still be "new"
        current = store.get_node_current(nid)
        assert current is not None
        assert current.summary == "new"
        store.close()

    def test_draft_and_reject_change(self, tmp_path: Path):
        store = _store(tmp_path)
        nid = store.create_node(node_type=NodeType.STOCK, name="Test")
        change_id = store.draft_change(
            node_id=nid, proposed_fields="{}",
            proposed_sources=json.dumps([{"source_type": "broker_report", "title": "t"}]),
            rationale="test",
        )
        store.reject_change(change_id)
        pending = store.list_pending(status=None)
        assert any(pc.status == "rejected" for pc in pending)


class TestSources:
    def test_add_and_list_sources(self, tmp_path: Path):
        store = _store(tmp_path)
        nid = store.create_node(node_type=NodeType.STOCK, name="中际旭创", code="300308.SZ")
        vid = store.update_node(nid, summary="test")
        sid = store.add_source(
            vid,
            source_type="broker_report",
            title="中际旭创深度研报",
            publisher="中信证券",
            url="https://example.com",
            published_date="2026-06-01",
            cited_text="光模块龙头",
        )
        sources = store.list_sources(vid)
        assert len(sources) == 1
        assert sources[0].source_id == sid
        assert sources[0].publisher == "中信证券"
        store.close()


class TestContext:
    def test_get_stock_context(self, tmp_path: Path):
        store = _store(tmp_path)
        track_id = store.create_node(node_type=NodeType.TRACK, name="AI 算力")
        seg_id = store.create_node(parent_id=track_id, node_type=NodeType.SEGMENT, name="CPO")
        link_id = store.create_node(parent_id=seg_id, node_type=NodeType.LINK, name="光模块")
        s1 = store.create_node(parent_id=link_id, node_type=NodeType.STOCK, name="中际旭创", code="300308.SZ")
        store.update_node(link_id, summary="光模块环节", chain_position="核心")
        store.update_node(s1, summary="中际旭创简介", market_size="100亿")
        s2 = store.create_node(parent_id=link_id, node_type=NodeType.STOCK, name="新易盛", code="300502.SZ")

        ctx = store.get_stock_context("300308.SZ")
        assert ctx is not None
        assert ctx["stock_name"] == "中际旭创"
        assert len(ctx["path"]) == 4
        assert ctx["path"][0]["name"] == "AI 算力"
        assert ctx["path"][2]["name"] == "光模块"
        assert "中际旭创简介" in ctx.get("stock_summary", "")
        assert len(ctx["competitors"]) > 0
        assert any(c["code"] == "300502.SZ" for c in ctx["competitors"])
        store.close()

    def test_get_stock_context_unknown_code(self, tmp_path: Path):
        store = _store(tmp_path)
        ctx = store.get_stock_context("000000.SZ")
        assert ctx is None
        store.close()


class TestTreeIndex:
    def test_get_tree(self, tmp_path: Path):
        store = _store(tmp_path)
        t = store.create_node(node_type=NodeType.TRACK, name="T")
        s = store.create_node(parent_id=t, node_type=NodeType.SEGMENT, name="S")
        tree = store.get_tree()
        assert len(tree) == 2
        assert any(n["name"] == "T" for n in tree)
        assert any(n["name"] == "S" for n in tree)
        store.close()

    def test_node_code_index(self, tmp_path: Path):
        store = _store(tmp_path)
        n1 = store.create_node(node_type=NodeType.STOCK, name="中际旭创", code="300308.SZ")
        n2 = store.create_node(node_type=NodeType.STOCK, name="新易盛", code="300502.SZ")
        idx = store.get_node_code_index()
        assert "300308.SZ" in idx
        assert "300502.SZ" in idx
        store.close()


class TestValidation:
    def test_draft_change_fields_validation(self, tmp_path: Path):
        """F4: reject unknown fields."""
        store = _store(tmp_path)
        nid = store.create_node(node_type=NodeType.STOCK, name="Test")
        with pytest.raises(ValueError, match="unknown_field"):
            store.draft_change(
                node_id=nid,
                proposed_fields=json.dumps({"unknown_field": "value"}),
                proposed_sources=json.dumps([{"source_type": "broker_report", "title": "t"}]),
                rationale="test",
            )
        store.close()

    def test_draft_change_sources_required(self, tmp_path: Path):
        """F4: sources required."""
        store = _store(tmp_path)
        nid = store.create_node(node_type=NodeType.STOCK, name="Test")
        with pytest.raises(ValueError, match="source is required"):
            store.draft_change(
                node_id=nid,
                proposed_fields=json.dumps({"summary": "test"}),
                proposed_sources="[]",
                rationale="test",
            )
        store.close()


class TestConcurrency:
    def test_concurrent_write(self, tmp_path: Path):
        from concurrent.futures import ThreadPoolExecutor
        store = _store(tmp_path)
        nid = store.create_node(node_type=NodeType.STOCK, name="Test", code="000001.SZ")

        def write_v1():
            store.update_node(nid, summary="v1")
            return "v1_done"

        def write_v2():
            store.update_node(nid, summary="v2")
            return "v2_done"

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(write_v1), pool.submit(write_v2)]
            for f in futures:
                f.result(timeout=5)

        versions = store.list_versions(nid)
        assert len(versions) == 2  # 2 updates = 2 versions
        store.close()


class TestNodeRelations:
    def test_add_relation_and_dedupe(self, tmp_path: Path):
        """add_relation succeeds and deduplicates same (source, target, type)."""
        store = _store(tmp_path)
        n1 = store.create_node(node_type=NodeType.STOCK, name="中际旭创", code="300308.SZ")
        n2 = store.create_node(node_type=NodeType.EXTERNAL, name="外部供应商A")

        rid1 = store.add_relation(n2, n1, "supplier", note="光芯片供应")
        assert rid1.startswith("rel_")

        # Same triple returns existing id, no error
        rid2 = store.add_relation(n2, n1, "supplier", note="重复")
        assert rid2 == rid1

        store.close()

    def test_add_relation_validation(self, tmp_path: Path):
        """add_relation rejects invalid relation_type and missing nodes."""
        store = _store(tmp_path)
        n1 = store.create_node(node_type=NodeType.STOCK, name="中际旭创", code="300308.SZ")
        n2 = store.create_node(node_type=NodeType.EXTERNAL, name="外部供应商A")

        # Invalid relation_type
        with pytest.raises(ValueError, match="Invalid relation_type"):
            store.add_relation(n1, n2, "bogus_type")

        # Non-existent source
        with pytest.raises(ValueError, match="does not exist"):
            store.add_relation("nd_nonexistent", n2, "supplier")

        # Non-existent target
        with pytest.raises(ValueError, match="does not exist"):
            store.add_relation(n1, "nd_nonexistent", "supplier")

        store.close()

    def test_list_relations_directions(self, tmp_path: Path):
        """list_relations returns correct edges for out, in, and both."""
        store = _store(tmp_path)
        stock = store.create_node(node_type=NodeType.STOCK, name="中际旭创", code="300308.SZ")
        supplier = store.create_node(node_type=NodeType.EXTERNAL, name="供应商A")
        customer = store.create_node(node_type=NodeType.EXTERNAL, name="客户B")

        store.add_relation(supplier, stock, "supplier")
        store.add_relation(stock, customer, "customer")

        out_edges = store.list_relations(stock, "out")
        assert len(out_edges) == 1
        assert out_edges[0]["other_name"] == "客户B"
        assert out_edges[0]["other_type"] == "external"

        in_edges = store.list_relations(stock, "in")
        assert len(in_edges) == 1
        assert in_edges[0]["other_name"] == "供应商A"
        assert in_edges[0]["other_type"] == "external"

        both = store.list_relations(stock, "both")
        assert len(both) == 2
        names = {e["other_name"] for e in both}
        assert names == {"供应商A", "客户B"}

        # Non-existent node returns empty list
        assert store.list_relations("nd_nonexistent", "both") == []

        store.close()

    def test_remove_relation(self, tmp_path: Path):
        """remove_relation deletes and returns True; returns False if not found."""
        store = _store(tmp_path)
        n1 = store.create_node(node_type=NodeType.STOCK, name="A", code="000001.SZ")
        n2 = store.create_node(node_type=NodeType.EXTERNAL, name="B")
        rid = store.add_relation(n1, n2, "related")

        assert store.remove_relation(rid) is True
        assert store.remove_relation(rid) is False  # already gone
        assert store.remove_relation("rel_nonexistent") is False

        store.close()

    def test_get_node_context_graph(self, tmp_path: Path):
        """get_node_context_graph returns full topology with no dynamic fields."""
        store = _store(tmp_path)
        # Build a simple graph
        track = store.create_node(node_type=NodeType.TRACK, name="AI 算力")
        seg = store.create_node(parent_id=track, node_type=NodeType.SEGMENT, name="CPO")
        link = store.create_node(parent_id=seg, node_type=NodeType.LINK, name="光模块")
        stock = store.create_node(parent_id=link, node_type=NodeType.STOCK, name="中际旭创", code="300308.SZ")
        competitor = store.create_node(parent_id=link, node_type=NodeType.STOCK, name="新易盛", code="300502.SZ")

        supplier = store.create_node(node_type=NodeType.EXTERNAL, name="光芯片供应商")
        customer = store.create_node(node_type=NodeType.EXTERNAL, name="数据中心客户")
        substitute = store.create_node(node_type=NodeType.EXTERNAL, name="替代品厂商")

        store.update_node(link, summary="光模块环节")
        store.update_node(stock, summary="中际旭创简介")

        store.add_relation(supplier, stock, "supplier")
        store.add_relation(stock, customer, "customer")
        store.add_relation(stock, substitute, "substitute")

        ctx = store.get_node_context_graph("300308.SZ")
        assert ctx is not None
        assert ctx["stock_name"] == "中际旭创"
        assert ctx["stock_code"] == "300308.SZ"

        # Path
        assert len(ctx["path"]) == 4
        assert ctx["path"][0]["name"] == "AI 算力"
        assert ctx["path"][3]["name"] == "中际旭创"

        # Competitors
        assert len(ctx["competitors"]) == 1
        assert ctx["competitors"][0]["code"] == "300502.SZ"

        # Upstream
        assert len(ctx["upstream"]) == 1
        assert ctx["upstream"][0]["other_name"] == "光芯片供应商"

        # Downstream
        assert len(ctx["downstream"]) == 1
        assert ctx["downstream"][0]["other_name"] == "数据中心客户"

        # Substitutes
        assert len(ctx["substitutes"]) == 1
        assert ctx["substitutes"][0]["other_name"] == "替代品厂商"

        # Empty categories
        assert ctx["related"] == []
        assert ctx["certified_by"] == []
        assert ctx["business_lines"] == []

        # No dynamic fields on the returned dict
        for key in ("market_size", "financials", "growth_rate", "operating_metrics",
                     "customer_structure", "stock_summary", "stock_financials",
                     "stock_metrics", "stock_customers"):
            assert key not in ctx, f"dynamic field {key!r} should not be in context_graph"

        # Unknown code
        assert store.get_node_context_graph("000000.SZ") is None

        store.close()


class TestSourceTypes:
    def test_llm_and_api_in_valid_source_types(self, tmp_path: Path):
        from src.industry_chain.store import _VALID_SOURCE_TYPES
        assert "llm" in _VALID_SOURCE_TYPES
        assert "api" in _VALID_SOURCE_TYPES

    def test_draft_change_accepts_llm_source(self, tmp_path: Path):
        store = _store(tmp_path)
        nid = store.create_node(name="测试节点", node_type=NodeType.TRACK)
        vid = store.update_node(nid, summary="初始")
        cid = store.draft_change(
            node_id=nid,
            proposed_fields=json.dumps({"summary": "更新"}, ensure_ascii=False),
            proposed_sources=json.dumps([{"source_type": "llm", "publisher": "Claude"}], ensure_ascii=False),
        )
        assert cid
        store.close()
