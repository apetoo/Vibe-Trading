"""Seed the industry chain knowledge graph with AI Compute sector data.

Idempotent: skips nodes that already exist (checked by name).
"""
from __future__ import annotations
from pathlib import Path
from src.industry_chain.store import IndustryChainStore
from src.industry_chain.models import NodeType


_TRACK_NAME = "AI 算力产业链"

_SEGMENTS: list[dict] = [
    {"name": "CPO 共封装光学", "nodes": [
        {"name": "光模块", "type": "link", "stocks": [
            ("中际旭创", "300308.SZ"),
            ("新易盛", "300502.SZ"),
            ("天孚通信", "300394.SZ"),
        ]},
    ]},
    {"name": "OCS 光交换", "nodes": [
        {"name": "光连接器", "type": "link", "stocks": [
            ("太辰光", "300570.SZ"),
        ]},
    ]},
    {"name": "光芯片", "nodes": [
        {"name": "光芯片", "type": "link", "stocks": [
            ("源杰科技", "688048.SH"),
            ("光迅科技", "002281.SZ"),
        ]},
    ]},
    {"name": "PCB 印制电路板", "nodes": [
        {"name": "PCB 制造", "type": "link", "stocks": [
            ("沪电股份", "002463.SZ"),
            ("生益科技", "600183.SH"),
            ("深南电路", "002916.SZ"),
        ]},
    ]},
]


def seed(db_path: Path | None = None) -> None:
    """Idempotent seed: create nodes if they don't exist."""
    store = IndustryChainStore(db_path)

    # Check if track already exists
    existing = store.get_tree()
    existing_names = {n["name"] for n in existing}

    if _TRACK_NAME in existing_names:
        return  # Already seeded

    track_id = store.create_node(
        parent_id=None, node_type=NodeType.TRACK,
        name=_TRACK_NAME, sort_order=0,
    )
    store.update_node(track_id,
        summary="AI 算力产业链涵盖从光芯片、光模块到 PCB 等核心环节，"
                "是 AI 数据中心基础设施的关键组成部分。",
        narrative="AI 算力产业链随着大模型训练和推理需求爆发式增长，"
                  "国产化率在光模块环节已较高（约 60%+），但在高端光芯片"
                  "环节仍依赖进口（国产化率约 15-20%）。",
        chain_position="AI 基础设施的核心支撑",
        localization="约 30-40%（整体）",
        tech_trend="国产替代加速，高端环节突破中",
        macro_drivers='["AI 大模型训练需求爆发", "数据中心 800G/1.6T 升级周期", "国产替代政策支持"]',
    )

    for seg_idx, segment in enumerate(_SEGMENTS):
        seg_id = store.create_node(
            parent_id=track_id, node_type=NodeType.SEGMENT,
            name=segment["name"], sort_order=seg_idx,
        )
        for node_info in segment["nodes"]:
            link_id = store.create_node(
                parent_id=seg_id, node_type=NodeType(node_info["type"]),
                name=node_info["name"],
            )
            for stock_name, stock_code in node_info["stocks"]:
                store.create_node(
                    parent_id=link_id, node_type=NodeType.STOCK,
                    name=stock_name, code=stock_code,
                )


if __name__ == "__main__":
    seed()
    print("Seeded AI 算力产业链")
