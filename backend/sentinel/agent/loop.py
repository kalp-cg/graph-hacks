"""The investigation loop: model <-> MCP tools, streamed as events.

Event types (each a dict with "type" and "run_id"):
  run_started, thought, tool_call, tool_result, action_proposed, provider_fallback, final, error
Exactly one `final` (or `error`) ends every run.
"""
import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from ..config import settings
from ..tools import incidents
from .autopilot import Autopilot
from .llm import LLM, LLMReply, make_llm
from .mcp_client import GraphToolbox
from .prompts import NUDGE_ACT, NUDGE_PAGE, SYSTEM_PROMPT

log = logging.getLogger(__name__)
Emit = Callable[[dict], Awaitable[None]]
LLM_TEXT_LIMIT = 3500


def compact_for_llm(res: dict) -> str:
    """What the model sees: the result without query text and uid lists, with long lists trimmed."""
    slim = {k: v for k, v in res.items() if k not in ("cypher", "node_uids", "edge_uids")}

    def trim(x: Any, n: int) -> Any:
        if isinstance(x, list):
            return [trim(i, n) for i in x[:n]] + ([f"... {len(x) - n} more"] if len(x) > n else [])
        if isinstance(x, dict):
            return {k: trim(v, n) for k, v in x.items()}
        return x

    text = json.dumps(slim, default=str)
    for n in (10, 6, 3):
        if len(text) <= LLM_TEXT_LIMIT:
            break
        text = json.dumps(trim(slim, n), default=str)
    return text


def summarize(name: str, res: dict) -> str:
    """One human line per tool result for the trail."""
    if "error" in res:
        hint = f" (did you mean {', '.join(res['did_you_mean'])}?)" if res.get("did_you_mean") else ""
        return f"⚠ {res.get('message', res['error'])}{hint}"
    r = res.get("result")
    try:
        if name == "get_active_alerts":
            return f"{len(r)} alerts firing on " + ", ".join(sorted({a['service'] for a in r}))
        if name == "find_common_cause":
            c = r["candidates"]
            return (f"shared dependency: {c[0]['name']} ({c[0]['status']})" if c else "no shared dependency")
        if name == "recent_changes":
            ch = r["changes"]
            return (f"{ch[0]['version']} on {ch[0]['service']} by {ch[0]['author']}, {ch[0]['minutes_ago']} min ago: "
                    f"\"{ch[0]['message']}\"" if ch else f"no deployments in the last {r['minutes']} min")
        if name == "recall_similar":
            inc = r["incidents"]
            return (f"closest past incident: {inc[0]['id']} \"{inc[0]['title']}\" "
                    f"(root cause {inc[0]['root_cause_service']}, {inc[0]['steps_taken']} steps)" if inc
                    else "no similar past incidents")
        if name == "get_service_context":
            oc = ", ".join(p["name"] for p in r["on_call"]) or "nobody"
            return f"{r['service']['name']} is owned by {r['team']}; on call: {oc}"
        if name == "blast_radius":
            tiers = ", ".join(f"{v} {k}" for k, v in r["by_tier"].items())
            return f"{r['count']} upstream services at risk ({tiers})"
        if name == "trace_dependencies":
            return f"{r['count']} downstream dependencies"
        if name in ("critical_services", "chokepoints"):
            f = r.get("focus")
            top = ", ".join(x["name"] for x in r["top"][:3])
            return (f"{f['name']} ranks #{f['rank']} of {f['out_of']}; top: {top}" if f else f"top: {top}")
        if name == "failure_path":
            return " → ".join(h["name"] for h in r["path"]) if r.get("path") else r.get("message", "no path")
        if name == "propose_action":
            a = r["action"]
            return f"proposed {a['kind']} on {a['target']} ({r.get('note') or a['status']}), awaiting approval"
        if name == "conclude_investigation":
            return f"recorded {res.get('incident')}: root cause {res.get('root_cause_uid')}"
    except (KeyError, IndexError, TypeError):
        pass
    return "done"


class RunState:
    """What the loop has learned from tool results, used for fallbacks and the final event."""

    def __init__(self) -> None:
        self.services: list[str] = []
        self.suspect: str | None = None
        self.repeat: dict | None = None
        self.proposed: list[dict] = []
        self.concluded = False
        self.tool_calls = 0

    def observe(self, name: str, res: dict) -> None:
        r = res.get("result")
        if "error" in res or r is None and name != "conclude_investigation":
            return
        if name == "get_active_alerts":
            self.services = sorted({a["service"] for a in r})
        elif name == "find_common_cause" and r.get("candidates"):
            self.suspect = r["candidates"][0]["name"]
        elif name == "recall_similar" and r.get("incidents"):
            # The best match with the same root cause as the graph's suspect (not just the top score).
            for inc in r["incidents"]:
                if self.suspect and inc.get("root_cause_service") == self.suspect:
                    self.repeat = {"id": inc["id"], "title": inc["title"], "steps_taken": inc["steps_taken"],
                                   "fixes": inc.get("fixes", [])}
                    break
        elif name == "propose_action":
            self.proposed.append(r["action"])
        elif name == "conclude_investigation":
            self.concluded = True


async def investigate(question: str, emit: Emit, toolbox: GraphToolbox, llm: LLM | None = None,
                      run_id: str | None = None, max_steps: int | None = None) -> dict:
    """Run one investigation end to end. Returns the final event."""
    run_id = run_id or uuid.uuid4().hex[:12]
    llm = llm or make_llm()
    max_steps = max_steps or settings.llm_max_steps
    state = RunState()
    started = time.monotonic()

    async def send(event: dict) -> None:
        await emit({"run_id": run_id, "t": round(time.monotonic() - started, 2), **event})

    incident = await asyncio.to_thread(incidents.open_incident, run_id)
    await send({"type": "run_started", "question": question, "provider": llm.name, "incident": incident,
                "tools": toolbox.names})

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}]
    nudged: set[str] = set()
    report = ""
    for _step in range(max_steps):
        try:
            reply: LLMReply = await llm.chat(messages, toolbox.tools)
        except Exception as exc:  # noqa: BLE001 - any provider failure hands over to autopilot
            if isinstance(llm, Autopilot):
                raise
            log.warning("LLM failed, autopilot takes over: %s", exc)
            await send({"type": "provider_fallback", "from": llm.name, "to": Autopilot.name, "reason": str(exc)[:300]})
            llm = Autopilot(settings.autopilot_delay_s)
            continue

        if reply.content and reply.tool_calls:
            await send({"type": "thought", "text": reply.content})
        if not reply.tool_calls:
            # One reminder each: act at all, and page a human. Proposing is safe; a person still approves.
            nudge = None
            if incident and not state.proposed and "act" not in nudged:
                nudge = "act"
            elif incident and state.proposed and "page" not in nudged and \
                    not any(a["kind"] == "page_oncall" for a in state.proposed):
                nudge = "page"
            if nudge:
                nudged.add(nudge)
                messages += [reply.as_message(),
                             {"role": "user", "content": NUDGE_ACT if nudge == "act" else NUDGE_PAGE}]
                continue
            report = reply.content
            break

        messages.append(reply.as_message())
        for call in reply.tool_calls:
            await send({"type": "tool_call", "id": call.id, "name": call.name, "args": call.args})
            t0 = time.monotonic()
            hidden = {"run_id": run_id, "steps_taken": state.tool_calls}
            res = await toolbox.call(call.name, call.args, hidden)
            if call.name != "conclude_investigation":
                state.tool_calls += 1
            state.observe(call.name, res)
            await send({
                "type": "tool_result", "id": call.id, "name": call.name, "ms": round((time.monotonic() - t0) * 1000),
                "summary": summarize(call.name, res), "error": res.get("error"),
                "cypher": res.get("cypher"), "node_uids": res.get("node_uids", []),
                "edge_uids": res.get("edge_uids", []), "result": res.get("result", res),
            })
            if call.name == "propose_action" and "error" not in res:
                await send({"type": "action_proposed", "action": res["result"]["action"], "note": res["result"].get("note")})
            content = compact_for_llm(res)
            if call.name == "recall_similar" and state.repeat:
                # Memory-guided planning: spell out what the graph memory means for this run.
                r = state.repeat
                hint = (f"{r['id']} had the same root cause ({state.suspect}) and was fixed by "
                            f"{', '.join(r['fixes']) or 'the recorded actions'} in {r['steps_taken']} steps. This is a "
                            f"REPEAT: call recent_changes for {state.suspect} to confirm, then propose those fixes "
                            f"(rollback only if there is a recent deployment) and page_oncall, then conclude with "
                            f"similar_incident={r['id']}. Skip further exploration.")
                content = json.dumps({**json.loads(content), "memory_match": hint})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
    else:
        report = report or "Stopped after the maximum number of steps."

    # The model forgot to record the conclusion: the backend records what the graph showed.
    if incident and not state.concluded and state.suspect:
        await asyncio.to_thread(incidents.conclude_incident, run_id, state.suspect,
                                f"Shared unhealthy dependency of {', '.join(state.services)}: {state.suspect}.",
                                state.tool_calls, state.repeat["id"] if state.repeat else None)

    if incident:
        await asyncio.to_thread(incidents.record_steps, run_id, state.tool_calls)

    final = {"type": "final", "report": report or "(no report)", "provider": llm.name, "steps": state.tool_calls,
             "root_cause": state.suspect, "incident": incident, "repeat_of": state.repeat,
             "actions": state.proposed, "seconds": round(time.monotonic() - started, 1)}
    await send(final)
    return final
