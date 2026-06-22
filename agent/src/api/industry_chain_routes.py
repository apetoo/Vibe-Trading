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
from src.industry_chain.store import IndustryChainStore
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
        return await asyncio.to_thread(store.get_tree)

    @app.get("/industry-chain/nodes/{node_id}", dependencies=[Depends(require_auth)])
    async def get_node(node_id: str):
        store = _get_store()
        node = await asyncio.to_thread(store.get_node, node_id)
        if not node:
            raise HTTPException(404, "Node not found")
        current = await asyncio.to_thread(store.get_node_current, node_id)
        versions = await asyncio.to_thread(store.list_versions, node_id)
        return {"node": node, "current_version": current, "versions": versions}

    @app.post("/industry-chain/nodes", dependencies=[Depends(require_auth)])
    async def create_node(body: dict):
        store = _get_store()
        parent_id = body.get("parent_id")
        node_type_str = body.get("node_type", "track")
        try:
            node_type = NodeType(node_type_str)
        except ValueError:
            raise HTTPException(400, f"Invalid node_type: {node_type_str}")
        nid = await asyncio.to_thread(
            store.create_node, parent_id=parent_id, node_type=node_type,
            name=body.get("name", ""), code=body.get("code"),
            sort_order=body.get("sort_order", 0),
        )
        return {"node_id": nid}

    @app.put("/industry-chain/nodes/{node_id}", dependencies=[Depends(require_auth)])
    async def update_node(node_id: str, body: dict):
        store = _get_store()
        # Filter to valid fields only
        valid = {"summary", "narrative", "market_size", "growth_rate", "chain_position",
                 "localization", "gross_margin", "tech_trend", "macro_drivers",
                 "financials", "operating_metrics", "customer_structure", "extra",
                 "validation_status"}
        fields = {k: v for k, v in body.items() if k in valid}
        if not fields:
            raise HTTPException(400, "No valid fields to update")
        vid = await asyncio.to_thread(store.update_node, node_id, **fields)
        return {"version_id": vid}

    @app.delete("/industry-chain/nodes/{node_id}", dependencies=[Depends(require_auth)])
    async def delete_node(node_id: str):
        store = _get_store()
        try:
            await asyncio.to_thread(store.delete_node, node_id)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"status": "deleted"}

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

    @app.get("/industry-chain/context", dependencies=[Depends(require_auth)])
    async def get_context(code: str = Query(..., description="Stock code")):
        store = _get_store()
        ctx = await asyncio.to_thread(store.get_stock_context, code)
        if not ctx:
            raise HTTPException(404, f"Stock {code} not found in industry chain")
        return ctx
