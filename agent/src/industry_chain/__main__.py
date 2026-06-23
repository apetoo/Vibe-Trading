"""CLI entry for industry-chain data population.

Usage:
  python -m src.industry_chain generate <track_name>
  python -m src.industry_chain enrich [--max-age-days 7]
"""
from __future__ import annotations
import argparse
import json
import sys

from src.industry_chain.store import IndustryChainStore
from src.industry_chain import generate, enrich


def cmd_generate(args: argparse.Namespace) -> int:
    store = IndustryChainStore()
    try:
        tid = generate.generate_track(store, args.track)
        print(f"Generated track -> {tid}")
        return 0
    finally:
        store.close()


def cmd_enrich(args: argparse.Namespace) -> int:
    store = IndustryChainStore()
    try:
        report = enrich.enrich_all(store, max_age_days=args.max_age_days)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 1
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="industry-chain")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="LLM-generate a full track tree")
    g.add_argument("track", help="Track name, e.g. 人形机器人")
    g.set_defaults(func=cmd_generate)

    e = sub.add_parser("enrich", help="tushare financial enrichment for all stocks")
    e.add_argument("--max-age-days", type=int, default=7)
    e.set_defaults(func=cmd_enrich)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
