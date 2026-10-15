"""CLI: python -m sentinel.seed --reset [--graph NAME]"""
import argparse

from ..config import settings
from ..db import get_graph
from .generator import seed_baseline


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the SentinelGraph baseline into FalkorDB.")
    parser.add_argument("--reset", action="store_true", help="wipe the graph and load the healthy baseline")
    parser.add_argument("--graph", default=settings.graph_name, help="graph name (default: %(default)s)")
    args = parser.parse_args()
    if not args.reset:
        parser.error("nothing to do; pass --reset to (re)load the baseline")
    counts = seed_baseline(get_graph(args.graph))
    print(f"Seeded graph '{args.graph}': {counts['nodes']} nodes, {counts['edges']} relationships")


if __name__ == "__main__":
    main()
