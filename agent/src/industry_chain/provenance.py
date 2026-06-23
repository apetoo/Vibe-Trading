"""Field-level provenance helpers for the industry chain graph.

Each node version has an ``extra`` JSON TEXT column. We store a
``field_provenance`` map inside it recording which source produced each
field, so a single version can mix LLM-generated (unverified) and
tushare-fetched (verified) fields without losing the trust distinction.
All functions take and return the ``extra`` column as a JSON *string*.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _parse(extra_json: str) -> dict:
    if not extra_json:
        return {}
    try:
        obj = json.loads(extra_json)
    except (json.JSONDecodeError, TypeError):
        obj = {}
    if not isinstance(obj, dict):
        return {}
    return obj


def set_field_provenance(extra_json: str, field: str, *, src: str, **meta) -> str:
    """Return a new extra JSON string with provenance for ``field`` set.

    Preserves all other keys in ``extra`` and all other fields in
    ``field_provenance``. Overwrites an existing entry for ``field``.
    Adds a UTC ``ts`` timestamp unless caller supplied one.
    """
    obj = _parse(extra_json)
    prov = obj.get("field_provenance")
    if not isinstance(prov, dict):
        prov = {}
    entry = {"src": src}
    entry.update(meta)
    entry.setdefault("ts", _now_iso())
    prov[field] = entry
    obj["field_provenance"] = prov
    return json.dumps(obj, ensure_ascii=False)


def get_field_provenance(extra_json: str, field: str) -> dict | None:
    obj = _parse(extra_json)
    prov = obj.get("field_provenance")
    if not isinstance(prov, dict):
        return None
    return prov.get(field)


def merge_provenance(extra_json: str, updates: dict[str, dict]) -> str:
    """Batch-set provenance for multiple fields. Each value is a dict
    whose ``src`` is required; ``ts`` defaults to now."""
    obj = _parse(extra_json)
    prov = obj.get("field_provenance")
    if not isinstance(prov, dict):
        prov = {}
    for field, meta in updates.items():
        entry = {"src": meta.get("src", "unknown")}
        entry.update({k: v for k, v in meta.items()})
        entry.setdefault("ts", _now_iso())
        prov[field] = entry
    obj["field_provenance"] = prov
    return json.dumps(obj, ensure_ascii=False)