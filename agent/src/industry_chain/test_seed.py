"""Tests for seed data."""
from __future__ import annotations
from pathlib import Path
from src.industry_chain.seed import seed
from src.industry_chain.store import IndustryChainStore


def test_seed_creates_nodes(tmp_path: Path):
    db = tmp_path / "ic.db"
    seed(db_path=db)
    store = IndustryChainStore(db)
    tree = store.get_tree()
    assert len(tree) > 0
    # Should have track + segments + stocks
    idx = store.get_node_code_index()
    assert "300308.SZ" in idx  # 中际旭创
    assert "300502.SZ" in idx  # 新易盛


def test_seed_is_idempotent(tmp_path: Path):
    db = tmp_path / "ic.db"
    seed(db_path=db)
    count1 = len(IndustryChainStore(db).get_tree())
    seed(db_path=db)
    count2 = len(IndustryChainStore(db).get_tree())
    assert count1 == count2  # No duplicates
