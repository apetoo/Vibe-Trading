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
        assert row[0] == 1
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
        for name in ("nodes", "node_versions", "node_current", "sources", "pending_changes"):
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
