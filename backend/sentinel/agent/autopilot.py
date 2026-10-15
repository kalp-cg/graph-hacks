"""Autopilot: a deterministic policy that speaks the same interface as an LLM.

It runs the same investigation protocol through the same MCP tools, so its runs look exactly like an LLM
run in the UI. Uses: CI, demos without a model, and taking over mid-run when the model fails (rate limit,
outage). It is always labelled as autopilot, never presented as the model.
"""
import asyncio
import json
import uuid
from typing import Any

from .llm import LLMReply, ToolCall


def _history(messages: list[dict]) -> list[tuple[str, dict, dict]]:
    """(tool name, args, result) for every tool call so far, in order."""
    calls: dict[str, tuple[str, dict]] = {}
    out = []
    for m in messages:
        if m["role"] == "assistant":
            for c in m.get("tool_calls") or []:
                args = c["function"]["arguments"]
                calls[c["id"]] = (c["function"]["name"], json.loads(args) if isinstance(args, str) else args)
        elif m["role"] == "tool" and m.get("tool_call_id") in calls:
            name, args = calls[m["tool_call_id"]]
            try:
                res = json.loads(m["content"])
            except (json.JSONDecodeError, TypeError):
                res = {}
            out.append((name, args, res if isinstance(res, dict) else {}))
    return out


class Autopilot:
    name = "autopilot (deterministic, no LLM)"

    def __init__(self, delay_s: float = 0.0):
        # Optional pause per step so people watching the UI can follow along; 0 in tests and CLI.
        self.delay_s = delay_s

    async def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        h = _history(messages)
        last = {name: res.get("result", res) for name, _args, res in h}
        done = set(last)

        def call(name: str, **args: Any) -> LLMReply:
            return LLMReply(tool_calls=[ToolCall(id=f"auto_{uuid.uuid4().hex[:8]}", name=name, args=args)])

        if "get_active_alerts" not in done:
            return call("get_active_alerts")
        alerts = last["get_active_alerts"] if isinstance(last["get_active_alerts"], list) else []
        services = sorted({a["service"] for a in alerts})
        if not services:
            return LLMReply(content="**All clear.** No alerts are firing, so there is nothing to investigate.")

        if "find_common_cause" not in done:
            return call("find_common_cause", services=services)
        candidates = last["find_common_cause"].get("candidates") or []
        if not candidates:
            return LLMReply(content="No shared dependency found for the alerting services; escalating to a human.")
        top = candidates[0]["name"]

        if "recall_similar" not in done:
            return call("recall_similar", services=services)
        repeat = next((i for i in last["recall_similar"].get("incidents") or []
                       if i.get("root_cause_service") == top), None)

        if "recent_changes" not in done:
            return call("recent_changes", services=[top], minutes=60)
        changes = last["recent_changes"].get("changes") or []
        change = changes[0] if changes else None

        if not repeat:
            if "get_service_context" not in done:
                return call("get_service_context", service=top)
            if "blast_radius" not in done:
                return call("blast_radius", service=top)
            if "critical_services" not in done:
                return call("critical_services", top=5, service=top)

        if repeat:
            kinds = [k for k in repeat.get("fixes", []) if k != "rollback" or change]
        else:
            kinds = ["rollback"] if change else ["open_breaker", "scale_up"]
        if "page_oncall" not in kinds:
            kinds.append("page_oncall")
        proposed = {args.get("kind") for name, args, _ in h if name == "propose_action"}
        why = (f"{change['version']} '{change['message']}' by {change['author']} deployed "
               f"{change['minutes_ago']} min before the alerts" if change
               else f"{top} is the deepest unhealthy dependency shared by {', '.join(services)}")
        for kind in kinds:
            if kind not in proposed:
                return call("propose_action", kind=kind, target_service=top, reason=why,
                            risk="low" if kind == "page_oncall" else "medium")

        summary = (f"{', '.join(services)} alerted because they all depend on {top}. " + why[0].upper() + why[1:] + ".")
        if "conclude_investigation" not in done:
            return call("conclude_investigation", root_cause_service=top, summary=summary,
                        similar_incident=repeat["id"] if repeat else "")
        return LLMReply(content=self._report(top, services, change, repeat, last, kinds))

    @staticmethod
    def _report(top: str, services: list[str], change: dict | None, repeat: dict | None, last: dict,
                kinds: list[str]) -> str:
        cause = (f"`{top}`: deployment **{change['version']}** \"{change['message']}\" by {change['author']}, "
                 f"{change['minutes_ago']} min before the alerts (`{change['uid']}`)." if change
                 else f"`{top}` itself is unhealthy; there is no recent deployment on it.")
        evidence = (f"Alerts on {', '.join(f'`svc:{s}`' for s in services)} → `find_common_cause` → all of them "
                    f"depend on `svc:{top}`, the deepest unhealthy shared dependency.")
        blast = last.get("blast_radius") or {}
        impact = (f"{blast.get('count')} upstream services at risk ({', '.join(f'{v} {k}' for k, v in blast.get('by_tier', {}).items())})."
                  if blast else f"{len(services)} alerting services.")
        memory = (f"Repeat of **{repeat['id']}** ({repeat['title']}); last time it took {repeat['steps_taken']} steps."
                  if repeat else "No past incident with this root cause; this one is now stored as memory.")
        return (f"**Root cause**: {cause}\n\n**Evidence**: {evidence}\n\n**Impact**: {impact}\n\n"
                f"**Proposed actions**: {', '.join(kinds)} on `{top}`, awaiting human approval.\n\n"
                f"**Memory**: {memory}")
