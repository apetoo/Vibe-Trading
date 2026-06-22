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
