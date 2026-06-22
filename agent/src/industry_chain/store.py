"""SQLite-backed store for the industry chain knowledge graph.

Mirrors ``src/goal/store.py``: single connection + ``_synchronized`` +
``_lock`` + WAL + ``PRAGMA user_version`` migration.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar

from src.industry_chain.models import ChainNode, NodeType, NodeVersion, PendingChange, Source

F = TypeVar("F", bound=Callable)

# Whitelist of valid field names for NodeVersion (F4 validation)
_VALID_NODE_FIELDS = {
    "summary", "narrative", "market_size", "growth_rate", "chain_position",
    "localization", "gross_margin", "tech_trend", "macro_drivers",
    "financials", "operating_metrics", "customer_structure", "extra",
    "validation_status",
}
_VALID_SOURCE_TYPES = {
    "annual_report", "prospectus", "exchange_announcement", "broker_report",
}
_DEFAULT_DB_PATH = Path.home() / ".vibe-trading" / "industry_chain.db"
_DB_PATH_ENV = "VIBE_TRADING_INDUSTRY_CHAIN_DB_PATH"


def _default_db_path() -> Path:
    raw = os.getenv(_DB_PATH_ENV, "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_DB_PATH


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _synchronized(method: F) -> F:
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper  # type: ignore


class IndustryChainStore:
    """SQLite store for industry chain nodes, versions, sources, and pending changes."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    parent_id TEXT,
                    node_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    code TEXT,
                    sort_order INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (parent_id) REFERENCES nodes(node_id)
                );
                CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);
                CREATE INDEX IF NOT EXISTS idx_nodes_code ON nodes(code);

                CREATE TABLE IF NOT EXISTS node_versions (
                    version_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    summary TEXT DEFAULT '',
                    narrative TEXT DEFAULT '',
                    market_size TEXT DEFAULT '',
                    growth_rate TEXT DEFAULT '',
                    chain_position TEXT DEFAULT '',
                    localization TEXT DEFAULT '',
                    gross_margin TEXT DEFAULT '',
                    tech_trend TEXT DEFAULT '',
                    macro_drivers TEXT DEFAULT '[]',
                    financials TEXT DEFAULT '{}',
                    operating_metrics TEXT DEFAULT '{}',
                    customer_structure TEXT DEFAULT '{}',
                    extra TEXT DEFAULT '{}',
                    validation_status TEXT DEFAULT 'unverified',
                    snapshot_at TEXT NOT NULL,
                    snapshot_by TEXT NOT NULL,
                    FOREIGN KEY (node_id) REFERENCES nodes(node_id)
                );
                CREATE INDEX IF NOT EXISTS idx_versions_node ON node_versions(node_id, snapshot_at);

                CREATE TABLE IF NOT EXISTS node_current (
                    node_id TEXT PRIMARY KEY,
                    version_id TEXT NOT NULL,
                    FOREIGN KEY (version_id) REFERENCES node_versions(version_id)
                );

                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT PRIMARY KEY,
                    version_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    publisher TEXT DEFAULT '',
                    url TEXT DEFAULT '',
                    published_date TEXT DEFAULT '',
                    cited_text TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (version_id) REFERENCES node_versions(version_id)
                );
                CREATE INDEX IF NOT EXISTS idx_sources_version ON sources(version_id);

                CREATE TABLE IF NOT EXISTS pending_changes (
                    change_id TEXT PRIMARY KEY,
                    node_id TEXT DEFAULT '',
                    is_new_node INTEGER DEFAULT 0,
                    new_node_name TEXT DEFAULT '',
                    new_node_type TEXT DEFAULT '',
                    new_node_code TEXT DEFAULT '',
                    new_node_parent TEXT DEFAULT '',
                    proposed_fields TEXT NOT NULL DEFAULT '{}',
                    proposed_sources TEXT NOT NULL DEFAULT '[]',
                    rationale TEXT DEFAULT '',
                    drafted_by TEXT NOT NULL,
                    status TEXT DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT DEFAULT '',
                    resolved_by TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_changes(status);

                PRAGMA user_version=1;
            """)

    # -- Lifecycle --

    def close(self) -> None:
        self._conn.close()

    # -- Node CRUD --

    @_synchronized
    def create_node(
        self,
        parent_id: str | None = None,
        node_type: NodeType = NodeType.TRACK,
        name: str = "",
        code: str | None = None,
        sort_order: int = 0,
    ) -> str:
        nid = _id("nd")
        now = _now_iso()
        self._conn.execute(
            "INSERT INTO nodes (node_id, parent_id, node_type, name, code, sort_order, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (nid, parent_id, node_type.value, name, code, sort_order, now, now),
        )
        self._conn.commit()
        return nid

    @_synchronized
    def get_node(self, node_id: str) -> ChainNode | None:
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE node_id=?", (node_id,)
        ).fetchone()
        if not row:
            return None
        return ChainNode(**dict(row))

    @_synchronized
    def delete_node(self, node_id: str) -> None:
        children = self._conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE parent_id=?", (node_id,)
        ).fetchone()[0]
        if children > 0:
            raise ValueError(
                f"Node {node_id} has {children} children; delete them first"
            )
        self._conn.execute("DELETE FROM nodes WHERE node_id=?", (node_id,))
        self._conn.commit()

    @_synchronized
    def update_node_meta(self, node_id: str, **fields: str | None) -> None:
        """Update node metadata (name, code, sort_order, parent_id)."""
        allowed = {"name", "code", "sort_order", "parent_id"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return
        now = _now_iso()
        sets = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [now, node_id]
        self._conn.execute(
            f"UPDATE nodes SET {sets}, updated_at=? WHERE node_id=?",
            values,
        )
        self._conn.commit()

    @_synchronized
    def list_children(self, parent_id: str) -> list[ChainNode]:
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE parent_id=? ORDER BY sort_order, name",
            (parent_id,),
        ).fetchall()
        return [ChainNode(**dict(r)) for r in rows]

    @_synchronized
    def update_node(self, node_id: str, **fields: str) -> str:
        """Update node fields, write a new version snapshot, update current pointer.
        Returns the new version_id."""
        now = _now_iso()
        self._conn.execute(
            "UPDATE nodes SET updated_at=? WHERE node_id=?", (now, node_id)
        )

        # Build version fields from current + override with provided
        current_v = self.get_node_current(node_id)
        vfields: dict[str, str] = {
            "summary": "", "narrative": "", "market_size": "", "growth_rate": "",
            "chain_position": "", "localization": "", "gross_margin": "", "tech_trend": "",
            "macro_drivers": "[]", "financials": "{}", "operating_metrics": "{}",
            "customer_structure": "{}", "extra": "{}", "validation_status": "unverified",
        }
        if current_v:
            for k in vfields:
                vfields[k] = getattr(current_v, k, vfields[k])
        vfields.update(fields)

        vid = _id("vr")
        self._conn.execute(
            """INSERT INTO node_versions (version_id, node_id, summary, narrative, market_size,
               growth_rate, chain_position, localization, gross_margin, tech_trend,
               macro_drivers, financials, operating_metrics, customer_structure, extra,
               validation_status, snapshot_at, snapshot_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (vid, node_id, vfields["summary"], vfields["narrative"],
             vfields["market_size"], vfields["growth_rate"],
             vfields["chain_position"], vfields["localization"],
             vfields["gross_margin"], vfields["tech_trend"],
             vfields["macro_drivers"], vfields["financials"],
             vfields["operating_metrics"], vfields["customer_structure"],
             vfields["extra"], vfields["validation_status"],
             now, "human"),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO node_current (node_id, version_id) VALUES (?,?)",
            (node_id, vid),
        )
        self._conn.commit()
        return vid

    @_synchronized
    def get_node_current(self, node_id: str) -> NodeVersion | None:
        row = self._conn.execute(
            """SELECT nv.* FROM node_versions nv
               JOIN node_current nc ON nv.version_id = nc.version_id
               WHERE nc.node_id=?""",
            (node_id,),
        ).fetchone()
        if not row:
            return None
        return NodeVersion(**dict(row))

    @_synchronized
    def list_versions(self, node_id: str) -> list[NodeVersion]:
        rows = self._conn.execute(
            "SELECT * FROM node_versions WHERE node_id=? ORDER BY snapshot_at DESC",
            (node_id,),
        ).fetchall()
        return [NodeVersion(**dict(r)) for r in rows]

    # -- Sources --

    @_synchronized
    def add_source(
        self,
        version_id: str,
        source_type: str,
        title: str = "",
        publisher: str = "",
        url: str = "",
        published_date: str = "",
        cited_text: str = "",
    ) -> str:
        sid = _id("src")
        self._conn.execute(
            """INSERT INTO sources (source_id, version_id, source_type, title, publisher, url,
               published_date, cited_text, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (sid, version_id, source_type, title, publisher, url,
             published_date, cited_text, _now_iso()),
        )
        self._conn.commit()
        return sid

    @_synchronized
    def list_sources(self, version_id: str) -> list[Source]:
        rows = self._conn.execute(
            "SELECT * FROM sources WHERE version_id=?", (version_id,)
        ).fetchall()
        return [Source(**dict(r)) for r in rows]

    # -- Pending Changes --

    _VALID_FIELDS = _VALID_NODE_FIELDS

    @_synchronized
    def draft_change(
        self,
        node_id: str,
        proposed_fields: str = "{}",
        proposed_sources: str = "[]",
        rationale: str = "",
        is_new_node: bool = False,
        new_node_name: str = "",
        new_node_type: str = "",
        new_node_code: str = "",
        new_node_parent: str = "",
    ) -> str:
        # F4: validate field names
        fields = json.loads(proposed_fields)
        unknown = set(fields.keys()) - self._VALID_FIELDS
        if unknown:
            raise ValueError(
                f"Unknown field(s): {', '.join(sorted(unknown))}. "
                f"Valid: {sorted(self._VALID_FIELDS)}"
            )
        # F4: sources required
        sources = json.loads(proposed_sources)
        if not sources:
            raise ValueError("At least one source is required")
        # Validate source_type values
        for s in sources:
            if s.get("source_type", "") not in _VALID_SOURCE_TYPES:
                raise ValueError(
                    f"Invalid source_type: {s.get('source_type')}. "
                    f"Valid: {sorted(_VALID_SOURCE_TYPES)}"
                )

        cid = _id("pc")
        self._conn.execute(
            """INSERT INTO pending_changes (change_id, node_id, is_new_node, new_node_name,
               new_node_type, new_node_code, new_node_parent, proposed_fields, proposed_sources,
               rationale, drafted_by, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, node_id, 1 if is_new_node else 0, new_node_name, new_node_type,
             new_node_code, new_node_parent, proposed_fields, proposed_sources,
             rationale, "agent", "draft", _now_iso()),
        )
        self._conn.commit()
        return cid

    @_synchronized
    def list_pending(self, status: str | None = "draft") -> list[PendingChange]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM pending_changes WHERE status=? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM pending_changes ORDER BY created_at DESC"
            ).fetchall()
        return [PendingChange(**dict(r)) for r in rows]

    @_synchronized
    def accept_change(
        self, change_id: str, snapshot_by: str = "human"
    ) -> str:
        """Accept a pending change: write a new version, update current pointer,
        mark accepted. Uses a single transaction (F5). Returns new version_id.

        Raises ValueError if change is not found or not in draft status.
        """
        row = self._conn.execute(
            "SELECT * FROM pending_changes WHERE change_id=?", (change_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Change {change_id!r} not found")
        pc = PendingChange(**dict(row))
        if pc.status != "draft":
            raise ValueError(f"Change {change_id!r} is not in draft status")
        node_id = pc.node_id
        fields = json.loads(pc.proposed_fields)

        try:
            vid = _id("vr")
            now = _now_iso()
            self._conn.execute(
                "UPDATE nodes SET updated_at=? WHERE node_id=?", (now, node_id)
            )

            # Build version from current + proposed
            current_v = self.get_node_current(node_id)
            vfields: dict[str, str] = {
                "summary": "", "narrative": "", "market_size": "", "growth_rate": "",
                "chain_position": "", "localization": "", "gross_margin": "", "tech_trend": "",
                "macro_drivers": "[]", "financials": "{}", "operating_metrics": "{}",
                "customer_structure": "{}", "extra": "{}", "validation_status": "unverified",
            }
            if current_v:
                for k in vfields:
                    vfields[k] = getattr(current_v, k, vfields[k])
            vfields.update(fields)

            # Use explicit INSERT (not the truncated version from the brief)
            self._conn.execute(
                """INSERT INTO node_versions (version_id, node_id, summary, narrative,
                   market_size, growth_rate, chain_position, localization, gross_margin,
                   tech_trend, macro_drivers, financials, operating_metrics,
                   customer_structure, extra, validation_status, snapshot_at, snapshot_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (vid, node_id, vfields["summary"], vfields["narrative"],
                 vfields["market_size"], vfields["growth_rate"],
                 vfields["chain_position"], vfields["localization"],
                 vfields["gross_margin"], vfields["tech_trend"],
                 vfields["macro_drivers"], vfields["financials"],
                 vfields["operating_metrics"], vfields["customer_structure"],
                 vfields["extra"], vfields["validation_status"],
                 now, snapshot_by),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO node_current (node_id, version_id) VALUES (?,?)",
                (node_id, vid),
            )
            self._conn.execute(
                """UPDATE pending_changes SET status='accepted', resolved_at=?,
                   resolved_by=? WHERE change_id=?""",
                (now, snapshot_by, change_id),
            )

            # Add sources from proposed_sources
            sources = json.loads(pc.proposed_sources)
            for s in sources:
                self.add_source(
                    vid,
                    s.get("source_type", "broker_report"),
                    title=s.get("title", ""),
                    publisher=s.get("publisher", ""),
                    url=s.get("url", ""),
                    published_date=s.get("published_date", ""),
                    cited_text=s.get("cited_text", ""),
                )
            self._conn.commit()
            return vid
        except Exception:
            self._conn.rollback()
            raise

    @_synchronized
    def reject_change(
        self, change_id: str, resolved_by: str = "human"
    ) -> None:
        self._conn.execute(
            """UPDATE pending_changes SET status='rejected', resolved_at=?,
               resolved_by=? WHERE change_id=?""",
            (_now_iso(), resolved_by, change_id),
        )
        self._conn.commit()

    # -- Context Query --

    @_synchronized
    def get_stock_context(self, code: str) -> dict | None:
        """Return a stock's industry chain context (D6 slice)."""
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE code=?", (code,)
        ).fetchone()
        if not row:
            return None
        stock = ChainNode(**dict(row))

        # Build path from stock up to root
        path: list[dict] = []
        current_id = stock.node_id
        while current_id:
            n = self.get_node(current_id)
            if not n:
                break
            cv = self.get_node_current(current_id)
            path.append({
                "node_id": n.node_id,
                "name": n.name,
                "node_type": n.node_type if isinstance(n.node_type, str) else n.node_type.value,
                "summary": cv.summary if cv else "",
            })
            current_id = n.parent_id
        path.reverse()

        # Siblings (competitors) at the same parent
        competitors: list[dict] = []
        if stock.parent_id:
            siblings = self.list_children(stock.parent_id)
            for sib in siblings:
                if sib.node_id != stock.node_id and sib.node_type == NodeType.STOCK:
                    competitors.append({
                        "node_id": sib.node_id,
                        "name": sib.name,
                        "code": sib.code,
                    })

        current_version = self.get_node_current(stock.node_id)
        return {
            "stock_name": stock.name,
            "stock_code": stock.code,
            "node_id": stock.node_id,
            "path": path,
            "competitors": competitors,
            "stock_summary": current_version.summary if current_version else "",
            "stock_financials": current_version.financials if current_version else "{}",
            "stock_metrics": current_version.operating_metrics if current_version else "{}",
            "stock_customers": current_version.customer_structure if current_version else "{}",
            "validation_status": current_version.validation_status if current_version else "",
            "market_size": current_version.market_size if current_version else "",
            "localization": current_version.localization if current_version else "",
            "gross_margin": current_version.gross_margin if current_version else "",
            "tech_trend": current_version.tech_trend if current_version else "",
        }

    # -- Tree / Index --

    @_synchronized
    def get_tree(self) -> list[dict]:
        """Return all nodes with their current version summary (flat list,
        tree built on client)."""
        rows = self._conn.execute(
            """SELECT n.node_id, n.parent_id, n.node_type, n.name, n.code, n.sort_order,
                      nv.summary
               FROM nodes n
               LEFT JOIN node_current nc ON n.node_id = nc.node_id
               LEFT JOIN node_versions nv ON nc.version_id = nv.version_id
               ORDER BY n.sort_order, n.name"""
        ).fetchall()
        return [dict(r) for r in rows]

    @_synchronized
    def get_node_code_index(self) -> dict[str, str]:
        """Return {code: node_id} for all stock nodes with codes
        (F3: memory cache seed)."""
        rows = self._conn.execute(
            "SELECT code, node_id FROM nodes WHERE code IS NOT NULL AND code != ''"
        ).fetchall()
        return {r["code"]: r["node_id"] for r in rows}
