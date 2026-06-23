"""Industry chain HTTP routes for the Web UI.

Mounted by ``agent/api_server.py`` via ``register_industry_chain_routes(app)``.
Mirrors ``alpha_routes.py`` pattern: FastAPI ``@app.get/post/put/delete`` with
``Depends(require_auth)``.
"""

from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, Callable
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from src.industry_chain.store import IndustryChainStore, _VALID_NODE_FIELDS
from src.industry_chain.models import NodeType

logger = logging.getLogger(__name__)
AuthDep = Callable[..., Any]

# Module-level store (lazy init, mirrors _get_goal_store pattern)
_industry_chain_store: IndustryChainStore | None = None
_STORE_LOCK = __import__("threading").Lock()


def _get_store() -> IndustryChainStore:
    global _industry_chain_store
    if _industry_chain_store is None:
        with _STORE_LOCK:
            if _industry_chain_store is None:
                _industry_chain_store = IndustryChainStore()
    return _industry_chain_store


# ─── Type mapping helpers ──────────────────────────────────────────

# Map backend NodeType values to frontend IndustryNode types
_BACKEND_TO_FRONTEND_TYPE = {
    "track": "chain",
    "segment": "sector",
    "link": "product",
    "stock": "company",
    "external": "external",
}

# Reverse map
_FRONTEND_TO_BACKEND_TYPE = {v: k for k, v in _BACKEND_TO_FRONTEND_TYPE.items()}


def _to_frontend_node(node: dict) -> dict:
    """Convert a backend tree dict to frontend IndustryNode format."""
    backend_type = node.get("node_type", "track")
    return {
        "id": node["node_id"],
        "name": node.get("name", ""),
        "type": _BACKEND_TO_FRONTEND_TYPE.get(backend_type, "unknown"),
        "parent_id": node.get("parent_id"),
        "description": node.get("summary") or "",
        "children": [],
        "metadata": {
            "code": node.get("code"),
            "sort_order": node.get("sort_order", 0),
            "backend_type": backend_type,
        },
    }


def _to_frontend_node_detail(node, current_version, versions) -> dict:
    """Convert a backend node detail to IndustryNodeResponse format."""
    backend_type = node.node_type if isinstance(node.node_type, str) else node.node_type.value
    return {
        "node": {
            "id": node.node_id,
            "name": node.name,
            "type": _BACKEND_TO_FRONTEND_TYPE.get(backend_type, "unknown"),
            "parent_id": node.parent_id,
            "description": current_version.summary if current_version else "",
            "children": [],
            "metadata": {
                "code": node.code,
                "sort_order": node.sort_order,
                "backend_type": backend_type,
            },
        }
    }


# JSON fields stored as TEXT in node_versions; parsed before returning to frontend.
_JSON_FIELDS = ("macro_drivers", "financials", "operating_metrics", "customer_structure")


def _safe_json(value: str, default):
    """Parse a JSON TEXT column; return default on empty/invalid."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def _to_node_detail_response(node, current_version, sources) -> dict:
    """Build the full detail response: node + all rich fields + sources."""
    backend_type = node.node_type if isinstance(node.node_type, str) else node.node_type.value
    cv = current_version
    fields = {
        "summary": cv.summary if cv else "",
        "narrative": cv.narrative if cv else "",
        "market_size": cv.market_size if cv else "",
        "growth_rate": cv.growth_rate if cv else "",
        "chain_position": cv.chain_position if cv else "",
        "localization": cv.localization if cv else "",
        "gross_margin": cv.gross_margin if cv else "",
        "tech_trend": cv.tech_trend if cv else "",
        "macro_drivers": _safe_json(cv.macro_drivers if cv else "[]", []),
        "financials": _safe_json(cv.financials if cv else "{}", {}),
        "operating_metrics": _safe_json(cv.operating_metrics if cv else "{}", {}),
        "customer_structure": _safe_json(cv.customer_structure if cv else "{}", {}),
        "validation_status": cv.validation_status if cv else "unverified",
    }
    return {
        "node": {
            "id": node.node_id,
            "name": node.name,
            "type": _BACKEND_TO_FRONTEND_TYPE.get(backend_type, "unknown"),
            "parent_id": node.parent_id,
            "description": cv.summary if cv else "",
            "code": node.code,
            "sort_order": node.sort_order,
        },
        "fields": fields,
        "sources": [
            {
                "source_type": s.source_type,
                "title": s.title,
                "publisher": s.publisher,
                "url": s.url,
                "published_date": s.published_date,
                "cited_text": s.cited_text,
            }
            for s in sources
        ],
        "version_id": cv.version_id if cv else None,
        "snapshot_at": cv.snapshot_at if cv else None,
    }


def _to_pending_review(pc) -> dict:
    """Convert a backend PendingChange to frontend PendingReview format."""
    return {
        "id": pc.change_id,
        "node_id": pc.node_id,
        "field": "all",
        "original_value": None,
        "suggested_value": pc.proposed_fields,
        "status": "pending" if pc.status == "draft" else pc.status,
        "created_at": pc.created_at,
    }


def register_industry_chain_routes(
    app: FastAPI,
    require_auth: AuthDep | None = None,
) -> None:
    """Mount the industry chain routes onto ``app``."""
    if require_auth is None:
        import sys as _sys
        host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        if host is None:
            raise RuntimeError("api_server not in sys.modules; pass require_auth explicitly")
        require_auth = host.require_auth

    @app.get("/industry-chain/tree", dependencies=[Depends(require_auth)])
    async def get_tree():
        store = _get_store()
        raw_nodes = await asyncio.to_thread(store.get_tree)
        frontend_nodes = [_to_frontend_node(n) for n in raw_nodes]
        # Build children lists
        node_map = {n["id"]: n for n in frontend_nodes}
        for n in frontend_nodes:
            pid = n["parent_id"]
            if pid and pid in node_map:
                node_map[pid]["children"].append(n["id"])
        return {
            "tree": {"nodes": frontend_nodes, "relations": []},
            "stats": {
                "total_nodes": len(frontend_nodes),
                "total_relations": 0,
                "pending_reviews": 0,
                "chain_count": sum(1 for n in frontend_nodes if n["type"] == "chain"),
                "sector_count": sum(1 for n in frontend_nodes if n["type"] == "sector"),
                "product_count": sum(1 for n in frontend_nodes if n["type"] == "product"),
                "company_count": sum(1 for n in frontend_nodes if n["type"] == "company"),
            },
        }

    @app.get("/industry-chain/nodes/{node_id}", dependencies=[Depends(require_auth)])
    async def get_node(node_id: str):
        store = _get_store()
        node = await asyncio.to_thread(store.get_node, node_id)
        if not node:
            raise HTTPException(404, "Node not found")
        current = await asyncio.to_thread(store.get_node_current, node_id)
        sources = []
        if current:
            sources = await asyncio.to_thread(store.list_sources, current.version_id)
        return _to_node_detail_response(node, current, sources)

    @app.post("/industry-chain/nodes", dependencies=[Depends(require_auth)])
    async def create_node(body: dict):
        store = _get_store()
        parent_id = body.get("parent_id")
        frontend_type = body.get("type", "chain")
        backend_type_str = _FRONTEND_TO_BACKEND_TYPE.get(frontend_type, "track")
        try:
            node_type = NodeType(backend_type_str)
        except ValueError:
            raise HTTPException(400, f"Invalid node_type: {frontend_type}")
        nid = await asyncio.to_thread(
            store.create_node, parent_id=parent_id, node_type=node_type,
            name=body.get("name", ""), code=body.get("code"),
            sort_order=body.get("sort_order", 0),
        )
        return {"node": {
            "id": nid,
            "name": body.get("name", ""),
            "type": frontend_type,
            "parent_id": parent_id,
            "description": body.get("description", ""),
            "children": [],
        }}

    @app.put("/industry-chain/nodes/{node_id}", dependencies=[Depends(require_auth)])
    async def update_node(node_id: str, body: dict):
        store = _get_store()
        # Map description → summary (back-compat)
        fields: dict[str, str] = {}
        if "description" in body:
            fields["summary"] = body["description"]
        # Rich fields: filter by whitelist, JSON-encode object/array fields
        raw_fields = body.get("fields") or {}
        for k, v in raw_fields.items():
            if k not in _VALID_NODE_FIELDS:
                continue
            if k in _JSON_FIELDS and not isinstance(v, str):
                fields[k] = json.dumps(v, ensure_ascii=False)
            else:
                fields[k] = v
        if "name" in body:
            store.update_node_meta(node_id, name=body["name"])
        if fields:
            await asyncio.to_thread(store.update_node, node_id, **fields)
        return {"node": {"id": node_id}}

    @app.delete("/industry-chain/nodes/{node_id}", dependencies=[Depends(require_auth)])
    async def delete_node(node_id: str):
        store = _get_store()
        try:
            await asyncio.to_thread(store.delete_node, node_id)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"status": "deleted", "success": True}

    # ── Relations ────────────────────────────────────────────────

    @app.post("/industry-chain/nodes/{node_id}/relations", dependencies=[Depends(require_auth)])
    async def add_relation(node_id: str, body: dict):
        """Add a directed relation edge from node_id to target_id."""
        store = _get_store()
        if not await asyncio.to_thread(store.get_node, node_id):
            raise HTTPException(404, f"Node {node_id!r} not found")
        target_id = body.get("target_id", "")
        relation_type = body.get("relation_type", "")
        note = body.get("note", "")
        try:
            rid = await asyncio.to_thread(
                store.add_relation,
                source_id=node_id,
                target_id=target_id,
                relation_type=relation_type,
                note=note,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {
            "relation": {
                "relation_id": rid,
                "source_id": node_id,
                "target_id": target_id,
                "relation_type": relation_type,
                "note": note,
            }
        }

    @app.get("/industry-chain/nodes/{node_id}/relations", dependencies=[Depends(require_auth)])
    async def list_relations(
        node_id: str,
        direction: str = Query("both", description="out, in, or both"),
    ):
        """List relations involving a node."""
        store = _get_store()
        if not await asyncio.to_thread(store.get_node, node_id):
            raise HTTPException(404, f"Node {node_id!r} not found")
        try:
            relations = await asyncio.to_thread(
                store.list_relations, node_id, direction
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"relations": relations, "total": len(relations)}

    @app.delete("/industry-chain/relations/{relation_id}", dependencies=[Depends(require_auth)])
    async def delete_relation(relation_id: str):
        """Delete a relation edge."""
        store = _get_store()
        deleted = await asyncio.to_thread(store.remove_relation, relation_id)
        if not deleted:
            raise HTTPException(404, f"Relation {relation_id!r} not found")
        return {"deleted": True}

    # ── Reviews (frontend-facing) ─────────────────────────────────

    @app.get("/industry-chain/reviews", dependencies=[Depends(require_auth)])
    async def list_reviews():
        store = _get_store()
        pending = await asyncio.to_thread(store.list_pending)
        reviews = [_to_pending_review(pc) for pc in pending]
        return {"reviews": reviews, "total": len(reviews)}

    @app.post("/industry-chain/reviews/{change_id}/approve", dependencies=[Depends(require_auth)])
    async def approve_review(change_id: str):
        store = _get_store()
        try:
            vid = await asyncio.to_thread(store.accept_change, change_id, snapshot_by="human")
            if not vid:
                raise HTTPException(404, "Change not found or already resolved")
            return {"status": "accepted", "success": True}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/industry-chain/reviews/{change_id}/reject", dependencies=[Depends(require_auth)])
    async def reject_review(change_id: str):
        store = _get_store()
        await asyncio.to_thread(store.reject_change, change_id)
        return {"status": "rejected", "success": True}

    # ── Legacy endpoints (keep for backward compat) ───────────────

    @app.get("/industry-chain/pending", dependencies=[Depends(require_auth)])
    async def list_pending():
        store = _get_store()
        return await asyncio.to_thread(store.list_pending)

    @app.post("/industry-chain/nodes/draft", dependencies=[Depends(require_auth)])
    async def draft_change(body: dict):
        store = _get_store()
        try:
            cid = await asyncio.to_thread(
                store.draft_change,
                node_id=body.get("node_id", ""),
                proposed_fields=json.dumps(body.get("fields", {}), ensure_ascii=False),
                proposed_sources=json.dumps(body.get("sources", []), ensure_ascii=False),
                rationale=body.get("rationale", ""),
                is_new_node=body.get("is_new_node", False),
                new_node_name=body.get("new_node_name", ""),
                new_node_type=body.get("new_node_type", ""),
                new_node_code=body.get("new_node_code", ""),
                new_node_parent=body.get("new_node_parent", ""),
            )
            return {"change_id": cid}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/industry-chain/pending/{change_id}/accept", dependencies=[Depends(require_auth)])
    async def accept_change(change_id: str):
        store = _get_store()
        try:
            vid = await asyncio.to_thread(store.accept_change, change_id, snapshot_by="human")
            if not vid:
                raise HTTPException(404, "Change not found or already resolved")
            return {"version_id": vid, "status": "accepted"}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/industry-chain/pending/{change_id}/reject", dependencies=[Depends(require_auth)])
    async def reject_change(change_id: str):
        store = _get_store()
        await asyncio.to_thread(store.reject_change, change_id)
        return {"status": "rejected"}

    @app.get("/industry-chain/stats", dependencies=[Depends(require_auth)])
    async def get_stats():
        store = _get_store()
        raw_nodes = await asyncio.to_thread(store.get_tree)
        pending = await asyncio.to_thread(store.list_pending)
        frontend_nodes = [_to_frontend_node(n) for n in raw_nodes]
        return {
            "total_nodes": len(frontend_nodes),
            "total_relations": 0,
            "pending_reviews": len(pending),
            "chain_count": sum(1 for n in frontend_nodes if n["type"] == "chain"),
            "sector_count": sum(1 for n in frontend_nodes if n["type"] == "sector"),
            "product_count": sum(1 for n in frontend_nodes if n["type"] == "product"),
            "company_count": sum(1 for n in frontend_nodes if n["type"] == "company"),
        }

    @app.get("/industry-chain/context", dependencies=[Depends(require_auth)])
    async def get_context(code: str = Query(..., description="Stock code")):
        store = _get_store()
        ctx = await asyncio.to_thread(store.get_stock_context, code)
        if not ctx:
            raise HTTPException(404, f"Stock {code} not found in industry chain")
        return ctx
