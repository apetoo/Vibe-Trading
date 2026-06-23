"""Tests for the broad-coverage track generation lane."""
from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.industry_chain.store import IndustryChainStore, NodeType
from src.industry_chain import generate


def _store(tmp_path: Path) -> IndustryChainStore:
    return IndustryChainStore(tmp_path / "ic.db")


_FAKE_LLM_JSON = {
    "track": {
        "name": "人形机器人",
        "summary": "人形机器人产业链",
        "market_size": "2030年万亿级",
        "macro_drivers": ["劳动力短缺", "AI 大模型驱动"],
        "tech_trend": "从液压向电驱演进",
        "chain_position": "下一代通用智能终端",
        "localization": "约 40%",
    },
    "segments": [
        {"name": "减速器", "summary": "关节核心", "links": [
            {"name": "谐波减速器", "summary": "小关节用", "stocks": [
                {"name": "绿的谐波", "code": "688017.SH", "summary": "谐波龙头"}
            ]}
        ]}
    ],
    "externals": [{"name": "波士顿动力 (Boston Dynamics)"}],
    "edges": [
        {"src": "绿的谐波", "dst": "波士顿动力 (Boston Dynamics)", "type": "certified_by", "note": ""}
    ],
}


def _fake_llm(payload: dict):
    llm = MagicMock()
    llm.chat.return_value = MagicMock(content=json.dumps(payload, ensure_ascii=False))
    return llm


class TestParse:
    def test_parse_valid_json(self):
        out = generate.parse_track_json(json.dumps(_FAKE_LLM_JSON, ensure_ascii=False))
        assert out["track"]["name"] == "人形机器人"
        assert out["segments"][0]["links"][0]["stocks"][0]["code"] == "688017.SH"

    def test_parse_strips_code_fence(self):
        raw = "```json\n" + json.dumps(_FAKE_LLM_JSON, ensure_ascii=False) + "\n```"
        out = generate.parse_track_json(raw)
        assert out["track"]["name"] == "人形机器人"


class TestGenerateTrack:
    def test_generates_full_tree(self, tmp_path: Path):
        store = _store(tmp_path)
        llm = _fake_llm(_FAKE_LLM_JSON)
        tid = generate.generate_track(store, "人形机器人", llm=llm)
        tree = store.get_tree()
        names = {n["name"] for n in tree}
        assert "人形机器人" in names
        assert "减速器" in names
        assert "谐波减速器" in names
        assert "绿的谐波" in names
        assert "波士顿动力 (Boston Dynamics)" in names
        # track version is unverified with llm provenance
        v = store.get_node_current(tid)
        assert v.validation_status == "unverified"
        extra = json.loads(v.extra)
        assert extra["field_provenance"]["summary"]["src"] == "llm"
        # certified_by edge present, no supplier/customer edges
        rels = store.list_all_relations()
        assert any(r["relation_type"] == "certified_by" for r in rels)
        assert not any(r["relation_type"] in ("supplier", "customer") for r in rels)
        store.close()

    def test_idempotent_skip_existing(self, tmp_path: Path):
        store = _store(tmp_path)
        llm = _fake_llm(_FAKE_LLM_JSON)
        generate.generate_track(store, "人形机器人", llm=llm)
        before = len(store.get_tree())
        generate.generate_track(store, "人形机器人", llm=llm)
        after = len(store.get_tree())
        assert before == after  # no duplication
        store.close()

    def test_invalid_code_still_creates_node(self, tmp_path: Path):
        payload = json.loads(json.dumps(_FAKE_LLM_JSON))
        payload["segments"][0]["links"][0]["stocks"][0]["code"] = "not-a-code"
        store = _store(tmp_path)
        llm = _fake_llm(payload)
        generate.generate_track(store, "人形机器人", llm=llm)
        # node exists but flagged
        tree = store.get_tree()
        stock = next(n for n in tree if n["name"] == "绿的谐波")
        v = store.get_node_current(stock["node_id"])
        extra = json.loads(v.extra)
        assert extra.get("code_unverified") is True
        store.close()