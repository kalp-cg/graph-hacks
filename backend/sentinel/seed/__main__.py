"""CLI: python -m sentinel.seed --reset | --scenario NAME [--graph NAME]"""
import argparse

from ..config import settings
from ..db import get_graph
from .generator import seed_baseline
from .scenarios import SCENARIOS, inject_scenario


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the SentinelGraph baseline into FalkorDB.")
    parser.add_argument("--reset", action="store_true", help="wipe the graph and load the healthy baseline")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS),
                        help="soft reset (keeps learned memory), then inject an incident")
    parser.add_argument("--fresh", action="store_true", help="with --scenario: re-seed everything first")
    parser.add_argument("--if-empty", action="store_true", help="seed only if the graph has no services yet")
    parser.add_argument("--graph", default=settings.graph_name, help="graph name (default: %(default)s)")
    args = parser.parse_args()
    if args.scenario:
        info = inject_scenario(args.scenario, get_graph(args.graph), fresh=args.fresh)
        print(f"Injected '{args.scenario}' into '{args.graph}': alerts on {', '.join(info['alerting_services'])}")
        return
    if args.if_empty:
        from ..db import rows

        g = get_graph(args.graph)
        if rows(g, "MATCH (s:Service) RETURN count(s) AS n")[0]["n"]:
            print(f"Graph '{args.graph}' already seeded; leaving it (and its learned memory) alone")
            return
        counts = seed_baseline(g)
        print(f"Seeded graph '{args.graph}': {counts['nodes']} nodes, {counts['edges']} relationships")
        return
    if not args.reset:
        parser.error("nothing to do; pass --reset or --scenario NAME")
    counts = seed_baseline(get_graph(args.graph))
    print(f"Seeded graph '{args.graph}': {counts['nodes']} nodes, {counts['edges']} relationships")


if __name__ == "__main__":
    main()
