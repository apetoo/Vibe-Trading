"""Tests for industry chain HTTP routes."""
from __future__ import annotations
from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient
import api_server
from src.industry_chain.store import IndustryChainStore
from src.industry_chain.models import NodeType


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("VIBE_TRADING_INDUSTRY_CHAIN_DB_PATH", str(tmp_path / "ic.db"))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "runs"))
    monkeypatch.setattr(api_server, "_goal_store", None)
    monkeypatch.setattr(api_server, "_session_service", None)
    monkeypatch.setattr(api_server, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(api_server, "RUNS_DIR", tmp_path / "runs")
    return TestClient(api_server.app)


def test_get_tree(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/industry-chain/tree")
    assert resp.status_code in (200,)


def test_create_node(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/industry-chain/nodes", json={
        "parent_id": None, "node_type": "track", "name": "AI 算力",
    })
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert "node_id" in data


def test_create_and_get_node(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create = client.post("/industry-chain/nodes", json={
        "parent_id": None, "node_type": "track", "name": "AI 算力",
    })
    nid = create.json()["node_id"]
    resp = client.get(f"/industry-chain/nodes/{nid}")
    assert resp.status_code == 200
    assert resp.json()["node"]["name"] == "AI 算力"


def test_update_node(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create = client.post("/industry-chain/nodes", json={
        "parent_id": None, "node_type": "segment", "name": "CPO",
    })
    nid = create.json()["node_id"]
    resp = client.put(f"/industry-chain/nodes/{nid}", json={"summary": "CPO 共封装光学"})
    assert resp.status_code == 200
    assert "version_id" in resp.json()


def test_delete_node(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create = client.post("/industry-chain/nodes", json={
        "parent_id": None, "node_type": "segment", "name": "Temp",
    })
    nid = create.json()["node_id"]
    resp = client.delete(f"/industry-chain/nodes/{nid}")
    assert resp.status_code in (200, 204)


def test_get_pending(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/industry-chain/pending")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_accept_pending(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create = client.post("/industry-chain/nodes", json={
        "parent_id": None, "node_type": "stock", "name": "中际旭创", "code": "300308.SZ",
    })
    nid = create.json()["node_id"]
    draft = client.post("/industry-chain/nodes/draft", json={
        "node_id": nid, "fields": {"market_size": "600亿"},
        "sources": [{"source_type": "broker_report", "title": "研报"}],
        "rationale": "更新",
    })
    cid = draft.json()["change_id"]
    resp = client.post(f"/industry-chain/pending/{cid}/accept")
    assert resp.status_code == 200
    assert "version_id" in resp.json()


def test_reject_pending(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create = client.post("/industry-chain/nodes", json={
        "parent_id": None, "node_type": "stock", "name": "Test", "code": "000001.SZ",
    })
    nid = create.json()["node_id"]
    draft = client.post("/industry-chain/nodes/draft", json={
        "node_id": nid, "fields": {"summary": "v2"},
        "sources": [{"source_type": "broker_report", "title": "R"}],
        "rationale": "test",
    })
    cid = draft.json()["change_id"]
    resp = client.post(f"/industry-chain/pending/{cid}/reject")
    assert resp.status_code == 200


def test_get_context(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create = client.post("/industry-chain/nodes", json={
        "parent_id": None, "node_type": "stock", "name": "中际旭创", "code": "300308.SZ",
    })
    nid = create.json()["node_id"]
    client.put(f"/industry-chain/nodes/{nid}", json={"summary": "光模块龙头"})
    resp = client.get("/industry-chain/context?code=300308.SZ")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stock_name"] == "中际旭创"


def test_get_context_unknown_code(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/industry-chain/context?code=000000.SZ")
    assert resp.status_code == 404


# ── Relations API tests ────────────────────────────────────────

def test_create_external_node(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create = client.post("/industry-chain/nodes", json={
        "parent_id": None, "type": "external", "name": "外部合作方",
    })
    assert create.status_code in (200, 201)
    nid = create.json()["node"]["id"]
    assert create.json()["node"]["type"] == "external"

    resp = client.get(f"/industry-chain/nodes/{nid}")
    assert resp.status_code == 200
    assert resp.json()["node"]["type"] == "external"


def test_add_and_list_relation(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    # Create two stock nodes
    a = client.post("/industry-chain/nodes", json={
        "parent_id": None, "type": "company", "name": "中际旭创", "code": "300308.SZ",
    })
    a_id = a.json()["node"]["id"]
    b = client.post("/industry-chain/nodes", json={
        "parent_id": None, "type": "company", "name": "英伟达", "code": "NVDA",
    })
    b_id = b.json()["node"]["id"]

    # Add relation: A is supplier of B (A →[supplier]→ B)
    add = client.post(f"/industry-chain/nodes/{a_id}/relations", json={
        "relation_type": "supplier", "target_id": b_id,
    })
    assert add.status_code in (200, 201)
    rel = add.json()["relation"]
    assert rel["relation_type"] == "supplier"
    assert rel["source_id"] == a_id
    assert rel["target_id"] == b_id

    # List relations for A
    resp = client.get(f"/industry-chain/nodes/{a_id}/relations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["relations"][0]["other_name"] == "英伟达"


def test_tree_includes_relations(tmp_path: Path, monkeypatch):
    """The /tree response must carry all relations (bulk) for the graph view,
    and each edge must be the lean shape (no denormalized peer fields).

    Note: the module-level store is cached across tests (pre-existing isolation
    quirk), so we assert THIS edge is present + stats consistency rather than
    an exact global count.
    """
    client = _client(tmp_path, monkeypatch)
    a = client.post("/industry-chain/nodes", json={
        "parent_id": None, "type": "company", "name": "中际旭创", "code": "300308.SZ",
    })
    a_id = a.json()["node"]["id"]
    b = client.post("/industry-chain/nodes", json={
        "parent_id": None, "type": "external", "name": "英伟达-GraphTest",
    })
    b_id = b.json()["node"]["id"]
    client.post(f"/industry-chain/nodes/{a_id}/relations", json={
        "relation_type": "certified_by", "target_id": b_id,
    })

    resp = client.get("/industry-chain/tree")
    assert resp.status_code == 200
    data = resp.json()
    rels = data["tree"]["relations"]
    # Our edge is present
    mine = [r for r in rels if r["source_id"] == a_id and r["target_id"] == b_id]
    assert len(mine) == 1
    rel = mine[0]
    assert rel["relation_type"] == "certified_by"
    # Lean edge: no denormalized peer fields (those come from per-node /relations)
    assert "other_name" not in rel
    assert "other_type" not in rel
    # stats.total_relations is consistent with the array length
    assert data["stats"]["total_relations"] == len(rels)


def test_add_relation_validation(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    a = client.post("/industry-chain/nodes", json={
        "parent_id": None, "type": "company", "name": "A", "code": "000001.SZ",
    })
    a_id = a.json()["node"]["id"]

    # Invalid relation_type
    resp = client.post(f"/industry-chain/nodes/{a_id}/relations", json={
        "relation_type": "bogus", "target_id": a_id,
    })
    assert resp.status_code == 400

    # Non-existent target
    resp = client.post(f"/industry-chain/nodes/{a_id}/relations", json={
        "relation_type": "supplier", "target_id": "nonexistent",
    })
    assert resp.status_code == 400

    # Non-existent source node (the node_id in the path)
    resp = client.post("/industry-chain/nodes/nonexistent/relations", json={
        "relation_type": "supplier", "target_id": a_id,
    })
    assert resp.status_code == 404


def test_delete_relation(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    a = client.post("/industry-chain/nodes", json={
        "parent_id": None, "type": "company", "name": "A", "code": "000001.SZ",
    })
    a_id = a.json()["node"]["id"]
    b = client.post("/industry-chain/nodes", json={
        "parent_id": None, "type": "company", "name": "B", "code": "000002.SZ",
    })
    b_id = b.json()["node"]["id"]

    # Add relation
    add = client.post(f"/industry-chain/nodes/{a_id}/relations", json={
        "relation_type": "supplier", "target_id": b_id,
    })
    rel_id = add.json()["relation"]["relation_id"]

    # Delete it
    resp = client.delete(f"/industry-chain/relations/{rel_id}")
    assert resp.status_code in (200, 204)
    assert resp.json()["deleted"] is True

    # Delete again → 404
    resp = client.delete(f"/industry-chain/relations/{rel_id}")
    assert resp.status_code == 404


def test_relation_direction(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    a = client.post("/industry-chain/nodes", json={
        "parent_id": None, "type": "company", "name": "A", "code": "000001.SZ",
    })
    a_id = a.json()["node"]["id"]
    b = client.post("/industry-chain/nodes", json={
        "parent_id": None, "type": "company", "name": "B", "code": "000002.SZ",
    })
    b_id = b.json()["node"]["id"]

    # A →[supplier]→ B: A is the source, B is the target
    client.post(f"/industry-chain/nodes/{a_id}/relations", json={
        "relation_type": "supplier", "target_id": b_id,
    })

    # From A's perspective (out): should see the relation
    out = client.get(f"/industry-chain/nodes/{a_id}/relations?direction=out")
    assert out.status_code == 200
    assert out.json()["total"] == 1

    # From A's perspective (in): should NOT see the relation
    in_resp = client.get(f"/industry-chain/nodes/{a_id}/relations?direction=in")
    assert in_resp.status_code == 200
    assert in_resp.json()["total"] == 0

    # From B's perspective (in): should see the relation
    in_resp = client.get(f"/industry-chain/nodes/{b_id}/relations?direction=in")
    assert in_resp.status_code == 200
    assert in_resp.json()["total"] == 1

    # From B's perspective (out): should NOT see the relation
    out = client.get(f"/industry-chain/nodes/{b_id}/relations?direction=out")
    assert out.status_code == 200
    assert out.json()["total"] == 0
