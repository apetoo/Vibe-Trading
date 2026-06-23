"""Tests for the tushare financial enrichment layer."""
from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.industry_chain.store import IndustryChainStore, NodeType
from src.industry_chain import enrich


def _store(tmp_path: Path) -> IndustryChainStore:
    return IndustryChainStore(tmp_path / "ic.db")


def _make_stock(store, name="中际旭创", code="300308.SZ"):
    tid = store.create_node(name="AI算力", node_type=NodeType.TRACK)
    sid = store.create_node(parent_id=tid, name=name, node_type=NodeType.STOCK, code=code)
    store.update_node(sid, summary="光模块")
    return sid


def _fake_pro():
    """A mock tushare pro_api client."""
    pro = MagicMock()
    pro.fina_indicator.return_value = MagicMock(to_dict=MagicMock(return_value=[
        {"ts_code": "300308.SZ", "end_date": "20251231",
         "gross_profit_margin": 35.2, "net_profit_margin": 18.1,
         "roe": 22.5, "debt_to_assets": 30.0,
         "q_profit_yoy": 50.0, "or_yoy": 40.0}
    ]))
    pro.top10_holders.return_value = MagicMock(to_dict=MagicMock(return_value=[
        {"holder_name": "中际旭创控股股东", "hold_ratio": 45.0}
    ]))
    return pro


class TestFetch:
    def test_fetch_financials_returns_mapped_dict(self):
        pro = _fake_pro()
        out = enrich.fetch_financials("300308.SZ", period=None, pro=pro)
        assert out["gross_profit_margin"] == 35.2
        assert out["net_profit_margin"] == 18.1
        assert out["roe"] == 22.5
        assert "period" in out

    def test_fetch_financials_empty_returns_empty(self):
        pro = MagicMock()
        pro.fina_indicator.return_value = MagicMock(to_dict=MagicMock(return_value=[]))
        out = enrich.fetch_financials("300308.SZ", period=None, pro=pro)
        assert out == {}

    def test_fetch_holders_returns_list(self):
        pro = _fake_pro()
        out = enrich.fetch_holders("300308.SZ", pro=pro)
        assert isinstance(out, list)
        assert out[0]["holder_name"] == "中际旭创控股股东"


class TestEnrichStock:
    def test_enrich_stock_writes_financials_and_provenance(self, tmp_path: Path):
        store = _store(tmp_path)
        sid = _make_stock(store)
        pro = _fake_pro()
        ok = enrich.enrich_stock(store, sid, "300308.SZ", pro=pro)
        assert ok is True
        v = store.get_node_current(sid)
        fin = json.loads(v.financials)
        assert fin["gross_profit_margin"] == 35.2
        extra = json.loads(v.extra)
        assert extra["field_provenance"]["financials"]["src"] == "tushare"
        assert extra["field_provenance"]["customer_structure"]["src"] == "tushare"
        # source recorded on this version
        srcs = store.list_sources(v.version_id)
        assert any(s.source_type == "api" and s.publisher == "tushare" for s in srcs)
        store.close()

    def test_enrich_stock_skips_when_no_data(self, tmp_path: Path):
        store = _store(tmp_path)
        sid = _make_stock(store)
        pro = MagicMock()
        pro.fina_indicator.return_value = MagicMock(to_dict=MagicMock(return_value=[]))
        ok = enrich.enrich_stock(store, sid, "300308.SZ", pro=pro)
        assert ok is False
        store.close()

    def test_enrich_stock_skips_when_recently_enriched(self, tmp_path: Path):
        store = _store(tmp_path)
        sid = _make_stock(store)
        pro = _fake_pro()
        enrich.enrich_stock(store, sid, "300308.SZ", pro=pro)  # first enrich
        # second enrich within max_age_days should skip
        ok = enrich.enrich_stock(store, sid, "300308.SZ", pro=pro, max_age_days=7)
        assert ok is False
        store.close()


class TestEnrichAll:
    def test_enrich_all_walks_stock_nodes(self, tmp_path: Path):
        store = _store(tmp_path)
        _make_stock(store, name="中际旭创", code="300308.SZ")
        _make_stock(store, name="新易盛", code="300502.SZ")
        # a node with bad code should be skipped, not crash
        tid = store.create_node(name="AI算力", node_type=NodeType.TRACK)
        store.create_node(parent_id=tid, name="无代码", node_type=NodeType.STOCK, code=None)
        pro = _fake_pro()
        report = enrich.enrich_all(store, pro=pro, max_age_days=7)
        assert report["enriched"] == 2
        assert report["skipped"] == 1
        store.close()
