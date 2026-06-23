"""Automatic financial enrichment layer.

Scans all stock nodes with valid codes, pulls financials / operating
metrics / top-10 holders from tushare pro_api, and writes a new node
version with field-level provenance (src=tushare). Supplier/customer
relations are NOT touched here — they live in annual-report PDFs that
tushare does not expose; those come from the grounded refinement track.
"""
from __future__ import annotations
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from src.industry_chain.store import IndustryChainStore
from src.industry_chain import provenance

_CODE_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")




def _get_pro(pro: Any = None):
    """Return a tushare pro_api client. If ``pro`` is provided (for tests),
    use it directly. Otherwise build one from TUSHARE_TOKEN."""
    if pro is not None:
        return pro
    import tushare as ts
    token = os.getenv("TUSHARE_TOKEN", "").strip() or ts.get_token()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN not set; required for enrichment")
    return ts.pro_api(token)


def _latest_period() -> str:
    """Return the most recently completed reporting period as YYYYMMDD.

    Tushare fina_indicator uses calendar quarter ends. We pick the last
    quarter end on or before today.
    """
    today = datetime.now(timezone.utc)
    quarter_ends = []
    for y in (today.year, today.year - 1):
        for m, d in [(3, 31), (6, 30), (9, 30), (12, 31)]:
            quarter_ends.append(datetime(y, m, d, tzinfo=timezone.utc))
    past = [q for q in quarter_ends if q <= today]
    return max(past).strftime("%Y%m%d")


def fetch_financials(code: str, period: str | None, pro: Any) -> dict:
    """Pull latest fina_indicator row for ``code`` and map to graph fields."""
    period = period or _latest_period()
    try:
        df = pro.fina_indicator(ts_code=code, period=period)
        rows = df.to_dict(orient="records") if df is not None else []
    except Exception:
        return {}
    if not rows:
        return {}
    r = rows[0]
    return {
        "period": period,
        "gross_profit_margin": r.get("gross_profit_margin"),
        "net_profit_margin": r.get("net_profit_margin"),
        "roe": r.get("roe"),
        "debt_to_assets": r.get("debt_to_assets"),
        "q_profit_yoy": r.get("q_profit_yoy"),
        "or_yoy": r.get("or_yoy"),
    }


def fetch_holders(code: str, pro: Any) -> list[dict]:
    """Pull top-10 holders for ``code``."""
    try:
        df = pro.top10_holders(ts_code=code)
        rows = df.to_dict(orient="records") if df is not None else []
    except Exception:
        return []
    return [{"holder_name": r.get("holder_name"), "hold_ratio": r.get("hold_ratio")}
            for r in rows if r.get("holder_name")]


def _recently_enriched(store: IndustryChainStore, node_id: str, max_age_days: int) -> bool:
    """True if the node has a tushare source newer than max_age_days."""
    v = store.get_node_current(node_id)
    if not v:
        return False
    srcs = store.list_sources(v.version_id)
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
    for s in srcs:
        if s.publisher == "tushare" and s.created_at:
            try:
                ts = datetime.fromisoformat(s.created_at).timestamp()
                if ts >= cutoff:
                    return True
            except ValueError:
                continue
    return False


def enrich_stock(store: IndustryChainStore, node_id: str, code: str,
                 pro: Any = None, max_age_days: int = 7) -> bool:
    """Enrich one stock node. Returns True if a new version was written."""
    if not code or not _CODE_RE.match(code):
        return False
    if _recently_enriched(store, node_id, max_age_days):
        return False
    client = _get_pro(pro)

    fin = fetch_financials(code, period=None, pro=client)
    holders = fetch_holders(code, pro=client)
    if not fin and not holders:
        return False

    fields: dict[str, str] = {}
    extra = store.get_node_current(node_id).extra if store.get_node_current(node_id) else "{}"
    if fin:
        fields["financials"] = json.dumps(fin, ensure_ascii=False)
        extra = provenance.set_field_provenance(extra, "financials", src="tushare", ref=code)
        # operating_metrics mirrors financials trend snapshot
        fields["operating_metrics"] = json.dumps(
            {"or_yoy": fin.get("or_yoy"), "q_profit_yoy": fin.get("q_profit_yoy")}, ensure_ascii=False)
        extra = provenance.set_field_provenance(extra, "operating_metrics", src="tushare", ref=code)
    if holders:
        fields["customer_structure"] = json.dumps(
            {"holders": holders, "partial": "holders_only"}, ensure_ascii=False)
        extra = provenance.set_field_provenance(extra, "customer_structure", src="tushare",
                                                ref=code, partial="holders_only")
    fields["extra"] = extra

    vid = store.update_node(node_id, **fields)
    store.add_source(vid, source_type="api", publisher="tushare",
                     title=f"fina_indicator@{fin.get('period', '')}",
                     cited_text=f"tushare fina_indicator for {code}")
    return True


def enrich_all(store: IndustryChainStore, pro: Any = None, max_age_days: int = 7) -> dict:
    """Walk all stock nodes and enrich. Returns a summary report."""
    report = {"enriched": 0, "skipped": 0, "errors": []}
    for node in store.get_tree():
        if node["node_type"] != "stock":
            continue
        code = node.get("code")
        if not code or not _CODE_RE.match(code):
            report["skipped"] += 1
            continue
        try:
            if enrich_stock(store, node["node_id"], code, pro=pro, max_age_days=max_age_days):
                report["enriched"] += 1
            else:
                report["skipped"] += 1
        except Exception as e:
            report["errors"].append({"code": code, "error": str(e)})
    return report
