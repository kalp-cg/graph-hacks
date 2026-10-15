"""Terminal run: python -m sentinel.agent.cli [--scenario NAME] [--provider ollama|gemini|autopilot] [--approve]"""
import argparse
import asyncio
import json

from ..seed.scenarios import SCENARIOS, inject_scenario
from ..tools.actions import execute_action
from .llm import make_llm
from .loop import investigate
from .mcp_client import GraphToolbox

DIM, BOLD, RED, GREEN, CYAN, RESET = "\033[2m", "\033[1m", "\033[31m", "\033[32m", "\033[36m", "\033[0m"


async def print_event(e: dict) -> None:
    t = f"{DIM}{e['t']:>6.1f}s{RESET}"
    kind = e["type"]
    if kind == "run_started":
        print(f"{t} {BOLD}run {e['run_id']}{RESET} with {e['provider']}  incident={e['incident'] and e['incident']['id']}")
    elif kind == "thought":
        print(f"{t} 💭 {e['text'][:300]}")
    elif kind == "tool_call":
        print(f"{t} {CYAN}→ {e['name']}{RESET}({json.dumps(e['args'])})")
    elif kind == "tool_result":
        color = RED if e["error"] else GREEN
        print(f"{t}   {color}{e['summary']}{RESET} {DIM}[{e['ms']} ms, {len(e['node_uids'])} nodes]{RESET}")
    elif kind == "provider_fallback":
        print(f"{t} {RED}⚠ {e['from']} failed ({e['reason'][:120]}); {e['to']} takes over{RESET}")
    elif kind == "final":
        print(f"\n{BOLD}Report{RESET} ({e['steps']} steps, {e['seconds']} s, {e['provider']})\n{e['report']}\n")


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", choices=sorted(SCENARIOS))
    p.add_argument("--provider")
    p.add_argument("--approve", action="store_true", help="approve every proposed action after the run")
    p.add_argument("question", nargs="?", default="Alerts are firing. Investigate, find the root cause and fix it.")
    args = p.parse_args()
    if args.scenario:
        info = inject_scenario(args.scenario)
        print(f"Injected {args.scenario}: alerts on {', '.join(info['alerting_services'])}")
    async with GraphToolbox() as tb:
        final = await investigate(args.question, print_event, tb, make_llm(args.provider))
    if args.approve:
        for a in final["actions"]:
            out = execute_action(a["uid"], approved_by="cli")
            print(f"✅ {out.get('outcome') or out}  recovered={out.get('recovered')} incidents={out.get('resolved_incidents')}")


if __name__ == "__main__":
    asyncio.run(main())
