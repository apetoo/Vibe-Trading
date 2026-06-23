"""Tests for field-level provenance helpers."""
from __future__ import annotations
import json
from src.industry_chain import provenance


def test_set_field_provenance_on_empty_extra():
    out = provenance.set_field_provenance("{}", "financials", src="tushare", ref="300308.SZ")
    extra = json.loads(out)
    assert extra["field_provenance"]["financials"]["src"] == "tushare"
    assert extra["field_provenance"]["financials"]["ref"] == "300308.SZ"
    assert "ts" in extra["field_provenance"]["financials"]


def test_set_field_provenance_preserves_existing_fields():
    base = json.dumps({"field_provenance": {"summary": {"src": "llm"}}, "other": 1})
    out = provenance.set_field_provenance(base, "financials", src="tushare")
    extra = json.loads(out)
    assert extra["field_provenance"]["summary"]["src"] == "llm"  # preserved
    assert extra["field_provenance"]["financials"]["src"] == "tushare"  # added
    assert extra["other"] == 1  # preserved


def test_set_field_provenance_overwrites_same_field():
    base = json.dumps({"field_provenance": {"summary": {"src": "llm", "old": True}}})
    out = provenance.set_field_provenance(base, "summary", src="human", verified=True)
    extra = json.loads(out)
    assert extra["field_provenance"]["summary"] == {"src": "human", "verified": True, "ts": out and extra["field_provenance"]["summary"]["ts"]}


def test_get_field_provenance():
    base = json.dumps({"field_provenance": {"summary": {"src": "llm"}}})
    assert provenance.get_field_provenance(base, "summary") == {"src": "llm"}
    assert provenance.get_field_provenance(base, "missing") is None


def test_merge_provenance_batch():
    out = provenance.merge_provenance("{}", {
        "summary": {"src": "llm"},
        "financials": {"src": "tushare", "ref": "300308.SZ"},
    })
    extra = json.loads(out)
    assert extra["field_provenance"]["summary"]["src"] == "llm"
    assert extra["field_provenance"]["financials"]["ref"] == "300308.SZ"


def test_set_field_provenance_invalid_json_returns_valid():
    out = provenance.set_field_provenance("not json", "summary", src="llm")
    extra = json.loads(out)  # must not raise
    assert extra["field_provenance"]["summary"]["src"] == "llm"