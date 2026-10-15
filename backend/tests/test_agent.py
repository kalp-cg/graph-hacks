"""The agent loop end to end through the real MCP server, driven by the deterministic autopilot."""
import asyncio
import os

import pytest

from conftest import TEST_GRAPH
from sentinel.agent.autopilot import Autopilot
from sentinel.agent.llm import LLMReply
from sentinel.agent.loop import compact_for_llm, investigate
from sentinel.agent.mcp_client import GraphToolbox
from sentinel.seed.scenarios import inject_scenario
from sentinel.tools.actions import execute_action


def run(question="Investigate", llm=None):
    events: list[dict] = []

    async def emit(e):
        events.append(e)

    async def go():
        os.environ["GRAPH_NAME"] = TEST_GRAPH  # the MCP server subprocess reads this
        async with GraphToolbox() as tb:
            return await investigate(question, emit, tb, llm or Autopilot())

    final = asyncio.run(go())
    return final, events


def test_full_run_then_faster_repeat(graph, monkeypatch):
    monkeypatch.setattr("sentinel.tools.common.get_graph", lambda name=None: graph)
    inject_scenario("kafka-rebalance-storm", graph, fresh=True)
    first, events = run()
    assert [e["type"] for e in events][0] == "run_started"
    assert [e["type"] for e in events].count("final") == 1
    assert first["root_cause"] == "kafka-bus" and first["repeat_of"] is None
    kinds = {a["kind"] for a in first["actions"]}
    assert kinds == {"rollback", "page_oncall"}
    for a in first["actions"]:
        execute_action(a["uid"], graph=graph)

    inject_scenario("kafka-rebalance-storm", graph)
    second, _ = run()
    assert second["repeat_of"]["id"] == first["incident"]["id"]
    assert second["steps"] < first["steps"]


def test_red_herring_is_not_rolled_back(graph, monkeypatch):
    monkeypatch.setattr("sentinel.tools.common.get_graph", lambda name=None: graph)
    inject_scenario("cache-stampede", graph, fresh=True)
    final, events = run()
    assert final["root_cause"] == "redis-cache"
    assert all(a["target"] == "redis-cache" for a in final["actions"])
    assert "rollback" not in {a["kind"] for a in final["actions"]}
    results = [e for e in events if e["type"] == "tool_result"]
    assert all(r["cypher"] for r in results if r["name"] != "conclude_investigation")


class Broken:
    name = "broken-llm"

    async def chat(self, messages, tools):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")


def test_autopilot_takes_over_when_model_fails(graph, monkeypatch):
    monkeypatch.setattr("sentinel.tools.common.get_graph", lambda name=None: graph)
    inject_scenario("db-pool-exhaustion", graph, fresh=True)
    final, events = run(llm=Broken())
    assert any(e["type"] == "provider_fallback" for e in events)
    assert final["root_cause"] == "inventory-db-proxy"


class Lazy:
    """Answers immediately without tools: the loop must nudge it, then accept."""
    name = "lazy"

    def __init__(self):
        self.calls = 0

    async def chat(self, messages, tools):
        self.calls += 1
        return LLMReply(content="Probably the database.")


def test_lazy_model_gets_nudged_once(graph, monkeypatch):
    monkeypatch.setattr("sentinel.tools.common.get_graph", lambda name=None: graph)
    inject_scenario("db-pool-exhaustion", graph, fresh=True)
    lazy = Lazy()
    final, _ = run(llm=lazy)
    assert lazy.calls == 2 and final["actions"] == []


def test_compact_for_llm_trims():
    big = {"result": {"items": [{"x": "y" * 50} for _ in range(200)]}, "cypher": "MATCH", "node_uids": ["a"] * 100}
    text = compact_for_llm(big)
    assert len(text) < 4000 and "cypher" not in text and "more" in text


CHAOS = [("pricing-service", "degraded", True), ("secrets-vault", "down", False), ("session-store", "down", True),
         ("cdn-edge", "down", True), ("service-mesh", "degraded", False), ("kafka-bus", "down", False)]


@pytest.mark.parametrize("service,mode,with_deploy", CHAOS)
def test_chaos_anywhere_is_found_and_fixed(graph, monkeypatch, service, mode, with_deploy):
    """Unscripted failures in every layer: the agent must find the broken service and the fix must heal all."""
    from sentinel.db import rows
    from sentinel.seed.scenarios import inject_chaos

    monkeypatch.setattr("sentinel.tools.common.get_graph", lambda name=None: graph)
    inject_scenario("db-pool-exhaustion", graph, fresh=True)
    inject_chaos(service, mode, with_deploy, graph)
    final, _ = run()
    assert final["root_cause"] == service
    kinds = {a["kind"] for a in final["actions"]}
    assert ("rollback" in kinds) == with_deploy
    for a in final["actions"]:
        execute_action(a["uid"], graph=graph)
    assert rows(graph, "MATCH (s:Service) WHERE s.status <> 'healthy' RETURN count(s) AS n")[0]["n"] == 0
    assert rows(graph, "MATCH (a:Alert {status: 'firing'}) RETURN count(a) AS n")[0]["n"] == 0
