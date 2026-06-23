"""Broad-coverage track generation lane.

Asks the LLM to emit a full tree (track → segment → link → stock/external)
plus qualitative fields for one industry chain, and writes it to the store
as validation_status=unverified with field-level provenance (src=llm).
Only certified_by / substitute edges are allowed here — supplier/customer
edges require grounded sources and belong to the refinement track.
"""
from __future__ import annotations
import json
import re
from typing import Any

from src.industry_chain.store import IndustryChainStore, NodeType
from src.industry_chain import provenance

_CODE_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
_ALLOWED_EDGE_TYPES = {"certified_by", "substitute"}

_PROMPT_TEMPLATE = """你是 A 股行业链分析师。请为产业链「{track}」生成一棵完整的产业链树，输出严格 JSON（只输出 JSON，不要解释）。

JSON schema：
{{
  "track": {{ "name": "...", "summary": "...", "market_size": "...",
            "macro_drivers": ["..."], "tech_trend": "...",
            "chain_position": "...", "localization": "..." }},
  "segments": [
    {{ "name": "...", "summary": "...", "links": [
      {{ "name": "...", "summary": "...", "stocks": [
        {{ "name": "...", "code": "300308.SZ", "summary": "..." }}
      ] }}
    ] }}
  ],
  "externals": [ {{ "name": "英伟达 (NVIDIA)" }} ],
  "edges": [
    {{ "src": "<stock 或 external 的 name>", "dst": "<name>", "type": "certified_by|substitute", "note": "" }}
  ]
}}

要求：
1. stock.code 用 A 股代码格式 6 位数字.SH/.SZ/.BJ，不确定就留空字符串。
2. edges 只允许 certified_by（认证关系）和 substitute（同环节替代）两种；不要输出 supplier/customer。
3. externals 是海外/非上市公司，name 带「(英文名)」，最多 5 个。
4. 每个环节列 2-3 个代表性 A 股标的，不要超过 3 个。
5. 所有 summary 控制在一句话（30 字以内），market_size/localization 用简短数字+单位。
6. segments 3-4 个，每个 segment 下 links 2-4 个，总输出控制在 8000 字以内，确保 JSON 完整不截断。
"""


def build_prompt(track_name: str) -> str:
    return _PROMPT_TEMPLATE.format(track=track_name)


def parse_track_json(raw: str) -> dict:
    """Parse LLM JSON output, stripping code fences if present."""
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    return json.loads(text)


def _name_index(store: IndustryChainStore) -> dict[str, str]:
    return {n["name"]: n["node_id"] for n in store.get_tree()}


def _write_node(store: IndustryChainStore, parent_id: str | None, node_type: NodeType,
                name: str, code: str | None, fields: dict, existing: dict[str, str]) -> str:
    """Create a node (if new) and write qualitative fields with llm provenance."""
    nid = existing.get(name)
    if nid is None:
        nid = store.create_node(parent_id=parent_id, node_type=node_type, name=name, code=code)
        existing[name] = nid
    else:
        return nid  # already exists — don't overwrite

    extra = "{}"
    vfields: dict[str, str] = {}
    for k in ("summary", "market_size", "tech_trend", "chain_position", "localization"):
        val = fields.get(k, "")
        if val:
            vfields[k] = val
            extra = provenance.set_field_provenance(extra, k, src="llm")
    md = fields.get("macro_drivers")
    if md:
        vfields["macro_drivers"] = json.dumps(md, ensure_ascii=False)
        extra = provenance.set_field_provenance(extra, "macro_drivers", src="llm")
    vfields["validation_status"] = "unverified"

    # invalid code flag
    if code and not _CODE_RE.match(code):
        extra = json.loads(extra)
        extra["code_unverified"] = True
        extra = json.dumps(extra, ensure_ascii=False)

    vfields["extra"] = extra
    vid = store.update_node(nid, **vfields)
    store.add_source(vid, source_type="llm", publisher="Claude",
                     title=f"LLM 生成: {name}")
    return nid


def generate_track(store: IndustryChainStore, track_name: str, llm: Any = None) -> str:
    """Generate a full industry-chain tree for ``track_name``. Idempotent:
    skips if a node with this name already exists. Returns track node_id."""
    existing = _name_index(store)
    if track_name in existing:
        return existing[track_name]

    if llm is None:
        from src.providers.chat import ChatLLM
        llm = ChatLLM()
    resp = llm.chat([{"role": "user", "content": build_prompt(track_name)}])
    payload = parse_track_json(resp.content)

    track = payload.get("track", {})
    track_id = _write_node(store, None, NodeType.TRACK, track_name, None, track, existing)

    for seg in payload.get("segments", []):
        seg_id = _write_node(store, track_id, NodeType.SEGMENT, seg["name"], None, seg, existing)
        for link in seg.get("links", []):
            link_id = _write_node(store, seg_id, NodeType.LINK, link["name"], None, link, existing)
            for stock in link.get("stocks", []):
                code = stock.get("code") or None
                if code == "":
                    code = None
                _write_node(store, link_id, NodeType.STOCK, stock["name"], code, stock, existing)

    for ext in payload.get("externals", []):
        _write_node(store, track_id, NodeType.EXTERNAL, ext["name"], None, ext, existing)

    # Edges: only certified_by / substitute, resolved by name
    for edge in payload.get("edges", []):
        rtype = edge.get("type")
        if rtype not in _ALLOWED_EDGE_TYPES:
            continue
        src_id = existing.get(edge.get("src"))
        dst_id = existing.get(edge.get("dst"))
        if not src_id or not dst_id:
            continue
        note = json.dumps({"src": "llm"}, ensure_ascii=False) if not edge.get("note") else edge["note"]
        store.add_relation(src_id, dst_id, rtype, note=note)

    return track_id