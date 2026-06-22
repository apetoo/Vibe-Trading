"""Data models for the industry chain knowledge graph."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class NodeType(str, Enum):
    TRACK = "track"
    SEGMENT = "segment"
    LINK = "link"
    STOCK = "stock"


@dataclass(frozen=True)
class ChainNode:
    node_id: str
    parent_id: str | None = None
    node_type: NodeType = NodeType.TRACK
    name: str = ""
    code: str | None = None
    sort_order: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class NodeVersion:
    version_id: str
    node_id: str
    summary: str = ""
    narrative: str = ""
    market_size: str = ""
    growth_rate: str = ""
    chain_position: str = ""
    localization: str = ""
    gross_margin: str = ""
    tech_trend: str = ""
    macro_drivers: str = ""
    financials: str = ""
    operating_metrics: str = ""
    customer_structure: str = ""
    extra: str = "{}"
    validation_status: str = "unverified"
    snapshot_at: str = ""
    snapshot_by: str = "human"


@dataclass(frozen=True)
class Source:
    source_id: str
    version_id: str
    source_type: str = ""
    title: str = ""
    publisher: str = ""
    url: str = ""
    published_date: str = ""
    cited_text: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class PendingChange:
    change_id: str
    node_id: str = ""
    is_new_node: bool = False
    new_node_name: str = ""
    new_node_type: str = ""
    new_node_code: str = ""
    new_node_parent: str = ""
    proposed_fields: str = "{}"
    proposed_sources: str = "[]"
    rationale: str = ""
    drafted_by: str = "agent"
    status: str = "draft"
    created_at: str = ""
    resolved_at: str = ""
    resolved_by: str = ""
