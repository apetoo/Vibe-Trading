#!/usr/bin/env python3
"""Seed 中际旭创(300308.SZ) supply-chain relations into the industry chain graph.

Idempotent: external nodes are deduplicated by name, relations are deduplicated
by (source_id, target_id, relation_type) via store.add_relation().

Run:
    cd agent && python -m src.industry_chain.seed_relations
"""

from __future__ import annotations

from src.industry_chain.models import NodeType
from src.industry_chain.store import IndustryChainStore


def _upsert_external(store: IndustryChainStore, name: str, summary: str) -> str:
    """Upsert an external node by name. Returns the node_id."""
    existing = store._conn.execute(
        "SELECT node_id FROM nodes WHERE name=? AND node_type=?",
        (name, NodeType.EXTERNAL.value),
    ).fetchone()
    if existing:
        node_id = existing["node_id"]
        print(f"  [SKIP] external '{name}' already exists ({node_id})")
        return node_id

    node_id = store.create_node(
        node_type=NodeType.EXTERNAL,
        name=name,
        parent_id=None,
    )
    store.update_node(node_id, summary=summary)
    print(f"  [CREATE] external '{name}' → {node_id}")
    return node_id


def main():
    store = IndustryChainStore()

    # ── Known node IDs (confirmed from DB) ──
    ZJXC = "nd_865b5f79b62c"       # 中际旭创
    YUANJIE = "nd_dde1204e56e0"     # 源杰科技
    TIANFU = "nd_a1933b1d08bb"      # 天孚通信
    CPO_SEGMENT = "nd_f2dcd2f0ac1c" # CPO 共封装光学
    GUANGMOKUAI = "nd_9ce8f2ab327a" # 光模块 link

    print("=" * 60)
    print("Seed: 中际旭创 supply-chain relations")
    print("=" * 60)

    # ── 1. External nodes (6) ──
    print("\n[1] Creating external nodes...")
    broadcom_id = _upsert_external(store, "Broadcom(博通)", "美股 DSP/硅光芯片巨头")
    coherent_id = _upsert_external(store, "Coherent(相干)", "美股光芯片龙头")
    google_id = _upsert_external(store, "谷歌云 (Google Cloud)", "海外云厂商,AI 算力主要买家")
    aws_id = _upsert_external(store, "亚马逊 AWS", "海外云厂商")
    meta_id = _upsert_external(store, "Meta Platforms", "海外云厂商/AI 算力买家")
    nvidia_id = _upsert_external(store, "英伟达 (NVIDIA)", "GPU 链主,AI 算力核心")

    # ── 2. Link node: 可插拔光模块 ──
    print("\n[2] Creating link node 可插拔光模块...")
    existing_link = store._conn.execute(
        "SELECT node_id FROM nodes WHERE name=? AND node_type=? AND parent_id=?",
        ("可插拔光模块", NodeType.LINK.value, GUANGMOKUAI),
    ).fetchone()
    if existing_link:
        pluggable_id = existing_link["node_id"]
        print(f"  [SKIP] link '可插拔光模块' already exists ({pluggable_id})")
    else:
        pluggable_id = store.create_node(
            node_type=NodeType.LINK,
            name="可插拔光模块",
            parent_id=GUANGMOKUAI,
        )
        store.update_node(
            pluggable_id,
            summary="传统可插拔光模块,CPO 的长期替代/被替代对象",
        )
        print(f"  [CREATE] link '可插拔光模块' → {pluggable_id}")

    # ── 3. Relations (9 edges) ──
    print("\n[3] Creating relations...")

    edge_count = 0

    # 3a. Supplier edges (4): A →[supplier]→ 中际旭创
    supplier_edges = [
        (YUANJIE, "源杰科技(光芯片)"),
        (TIANFU, "天孚通信(光器件)"),
        (broadcom_id, "Broadcom(博通)"),
        (coherent_id, "Coherent(相干)"),
    ]
    for src_id, label in supplier_edges:
        rid = store.add_relation(
            source_id=src_id, target_id=ZJXC, relation_type="supplier",
        )
        edge_count += 1
        print(f"  [EDGE] {label} →[supplier]→ 中际旭创  ({rid})")

    # 3b. Customer edges (3): 中际旭创 →[customer]→ B
    customer_edges = [
        (google_id, "谷歌云"),
        (aws_id, "AWS"),
        (meta_id, "Meta"),
    ]
    for tgt_id, label in customer_edges:
        rid = store.add_relation(
            source_id=ZJXC, target_id=tgt_id, relation_type="customer",
        )
        edge_count += 1
        print(f"  [EDGE] 中际旭创 →[customer]→ {label}  ({rid})")

    # 3c. Substitute edge (1): 中际旭创(CPO 产品) ↔ 可插拔光模块
    # 边连在 stock 级而非 segment 级 —— get_node_context_graph 只查 stock
    # 作为端点的边,stock 级边才能让 agent 注入看到替代关系。
    rid = store.add_relation(
        source_id=ZJXC, target_id=pluggable_id, relation_type="substitute",
    )
    edge_count += 1
    print(f"  [EDGE] 中际旭创 ↔[substitute]↔ 可插拔光模块  ({rid})")

    # 3d. Certified_by edge (1): 中际旭创 →[certified_by]→ 英伟达
    rid = store.add_relation(
        source_id=ZJXC, target_id=nvidia_id, relation_type="certified_by",
    )
    edge_count += 1
    print(f"  [EDGE] 中际旭创 →[certified_by]→ 英伟达  ({rid})")

    print(f"\n  Total edges created: {edge_count}")

    # ── 4. Verification ──
    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    ctx = store.get_node_context_graph("300308.SZ")
    if ctx is None:
        print("ERROR: get_node_context_graph returned None!")
        return

    print(f"\n  Stock: {ctx['stock_name']} ({ctx['stock_code']})")
    print(f"  Node ID: {ctx['node_id']}")

    print(f"\n  Path ({len(ctx['path'])} levels):")
    for p in ctx["path"]:
        print(f"    {p['node_type']:10s} {p['name']}")

    print(f"\n  upstream (suppliers):  {len(ctx['upstream'])}")
    for r in ctx["upstream"]:
        print(f"    {r['other_name']}")

    print(f"\n  downstream (customers): {len(ctx['downstream'])}")
    for r in ctx["downstream"]:
        print(f"    {r['other_name']}")

    print(f"\n  substitutes: {len(ctx['substitutes'])}")
    for r in ctx["substitutes"]:
        print(f"    {r['other_name']}")

    print(f"\n  certified_by: {len(ctx['certified_by'])}")
    for r in ctx["certified_by"]:
        print(f"    {r['other_name']}")

    print(f"\n  competitors: {len(ctx['competitors'])}")
    for c in ctx["competitors"]:
        print(f"    {c['name']} ({c['code']})")

    # ── 5. Assertions ──
    print("\n" + "=" * 60)
    print("Assertions")
    print("=" * 60)

    errors = []

    def check(cond, msg):
        if cond:
            print(f"  PASS: {msg}")
        else:
            print(f"  FAIL: {msg}")
            errors.append(msg)

    check(len(ctx["upstream"]) == 4, "upstream = 4")
    check(len(ctx["downstream"]) == 3, "downstream = 3")
    # Substitute edge is stock-level: 中际旭创 ↔ 可插拔光模块(link).
    # get_node_context_graph queries edges where the stock is an endpoint,
    # so the stock-level substitute edge IS visible here.
    check(len(ctx["substitutes"]) == 1,
          "substitutes = 1 (中际旭创 ↔ 可插拔光模块, stock-level edge)")
    check(len(ctx["certified_by"]) == 1, "certified_by = 1")
    check(len(ctx["competitors"]) == 2, "competitors = 2")

    # Verify no dynamic fields leaked into context graph
    check("market_size" not in ctx, "no market_size in context graph")
    check("financials" not in ctx, "no financials in context graph")
    check("growth_rate" not in ctx, "no growth_rate in context graph")
    check("gross_margin" not in ctx, "no gross_margin in context graph")
    check("localization" not in ctx, "no localization in context graph")
    check("tech_trend" not in ctx, "no tech_trend in context graph")
    check("operating_metrics" not in ctx, "no operating_metrics in context graph")
    check("customer_structure" not in ctx, "no customer_structure in context graph")

    # Verify list_relations count: 4 supplier + 3 customer + 1 substitute + 1 certified_by = 9
    all_rels = store.list_relations(ZJXC, "both")
    check(len(all_rels) == 9,
          f"list_relations(stock) = {len(all_rels)} (expected 9: 4 supplier + 3 customer + 1 substitute + 1 certified_by)")

    if errors:
        print(f"\n  {len(errors)} assertion(s) FAILED!")
        raise SystemExit(1)
    else:
        print(f"\n  All assertions PASSED.")

    store.close()


if __name__ == "__main__":
    main()