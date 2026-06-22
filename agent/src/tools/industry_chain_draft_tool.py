"""Tool: draft an industry chain update (does not write directly — requires human approval)."""
from __future__ import annotations
import json
import logging
from typing import Any
from src.agent.tools import BaseTool
from src.industry_chain.store import IndustryChainStore

logger = logging.getLogger(__name__)
_store: IndustryChainStore | None = None


def _get_store() -> IndustryChainStore:
    global _store
    if _store is None:
        _store = IndustryChainStore()
    return _store


class IndustryChainDraftTool(BaseTool):
    """Draft an industry chain knowledge graph update for human review."""

    name = "draft_industry_chain_update"
    description = (
        "Draft an update to the industry chain knowledge graph. "
        "The change is NOT written directly — it goes to a pending review queue "
        "where a human must approve it on the /industry-chain page. "
        "Use this to update existing nodes (e.g. 'update 中际旭创 latest financials') "
        "or propose new nodes (e.g. 'add 光芯片 segment'). "
        "Each field change requires at least one source citation "
        "(broker_report, annual_report, prospectus, or exchange_announcement)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "node_id": {
                "type": "string",
                "description": "Node ID to update (leave empty for new nodes)",
            },
            "is_new_node": {
                "type": "string",
                "description": "'true' if proposing a new node",
            },
            "new_node_name": {
                "type": "string",
                "description": "Name for a new node",
            },
            "new_node_type": {
                "type": "string",
                "description": "track|segment|link|stock",
            },
            "new_node_code": {
                "type": "string",
                "description": "Stock code (stock type only)",
            },
            "new_node_parent": {
                "type": "string",
                "description": "Parent node name or ID for new node",
            },
            "fields": {
                "type": "string",
                "description": "JSON object of fields to update, e.g. {\"market_size\": \"600亿\"}",
            },
            "sources": {
                "type": "string",
                "description": "JSON array of sources, each with source_type, title, publisher, url, published_date, cited_text",
            },
            "rationale": {
                "type": "string",
                "description": "Why this update is needed",
            },
        },
        "required": ["fields", "sources", "rationale"],
    }
    repeatable = True

    def __init__(self, store: IndustryChainStore | None = None) -> None:
        super().__init__()
        self._store = store

    def execute(self, **kwargs: Any) -> str:
        store = self._store or _get_store()
        try:
            fields_str = kwargs.get("fields", "{}")
            sources_str = kwargs.get("sources", "[]")
            # Parse and re-serialize for validation
            fields = json.loads(fields_str) if isinstance(fields_str, str) else fields_str
            sources = json.loads(sources_str) if isinstance(sources_str, str) else sources_str
            cid = store.draft_change(
                node_id=kwargs.get("node_id", ""),
                proposed_fields=json.dumps(fields, ensure_ascii=False),
                proposed_sources=json.dumps(sources, ensure_ascii=False),
                rationale=kwargs.get("rationale", ""),
                is_new_node=kwargs.get("is_new_node", "").lower() == "true",
                new_node_name=kwargs.get("new_node_name", ""),
                new_node_type=kwargs.get("new_node_type", ""),
                new_node_code=kwargs.get("new_node_code", ""),
                new_node_parent=kwargs.get("new_node_parent", ""),
            )
            return json.dumps({"change_id": cid, "status": "draft", "message": "Pending human review"}, ensure_ascii=False)
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
