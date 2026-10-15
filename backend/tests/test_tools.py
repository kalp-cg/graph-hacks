import asyncio

import pytest

from sentinel.seed.scenarios import inject_scenario
from sentinel.tools import algorithms, memory, read, rootcause

SHAPE = {"result", "cypher", "node_uids", "edge_uids"}

# scenario -> (root cause service, version of the deploy that caused it, or None)
EXPECTED = {
    "db-pool-exhaustion": ("inventory-db-proxy", "v4.2.0"),
    "bad-config-push": ("feature-flags", "v4.0.3"),
    "cache-stampede": ("redis-cache", None),
    "kafka-rebalance-storm": ("kafka-bus", "v4.1.0"),
}
PAST_INCIDENT = {"db-pool-exhaustion": "INC-0042", "bad-config-push": "INC-0057", "cache-stampede": "INC-0063"}


@pytest.fixture
def pool(graph):
    """Fresh db-pool-exhaustion state for each test (other tests inject other scenarios)."""
    info = inject_scenario("db-pool-exhaustion", graph, fresh=True)
    return graph, info


def assert_shape(out):
    assert SHAPE <= out.keys(), out
    assert out["cypher"]


# --- read tools ---------------------------------------------------------------

def test_active_alerts(pool):
    g, info = pool
    out = read.get_active_alerts(g)
    assert_shape(out)
    assert {a["service"] for a in out["result"]} == set(info["alerting_services"])
    assert set(info["alert_uids"]) <= set(out["node_uids"])


def test_service_context(pool):
    g, _ = pool
    out = read.get_service_context("inventory-db-proxy", g)
    assert_shape(out)
    ctx = out["result"]
    assert ctx["team"] == "Platform"
    assert [p["handle"] for p in ctx["on_call"]] == ["priya"]
    assert ctx["recent_deployments"][0]["version"] == "v4.2.0"
    assert "db:inventory-db" in out["node_uids"]


def test_trace_dependencies_is_downstream(pool):
    g, _ = pool
    out = read.trace_dependencies("checkout-api", 1, g)
    assert_shape(out)
    names = {d["name"] for d in out["result"]["dependencies"]}
    assert {"cart-service", "payments-api", "orders-service"} <= names
    assert all(d["hops"] == 1 for d in out["result"]["dependencies"])
    assert "e:checkout-api->cart-service" in out["edge_uids"]


def test_blast_radius_is_upstream(pool):
    g, _ = pool
    out = read.blast_radius("inventory-db-proxy", graph=g)
    assert_shape(out)
    names = {d["name"] for d in out["result"]["impacted"]}
    assert {"inventory-service", "orders-service", "checkout-api", "api-gateway", "cdn-edge"} <= names
    assert sum(out["result"]["by_tier"].values()) == out["result"]["count"]


@pytest.mark.parametrize("depth", [-5, 0, "abc", None, 999, "3; MATCH (n) DETACH DELETE n"])
def test_depth_is_clamped(pool, depth):
    g, _ = pool
    out = read.trace_dependencies("checkout-api", depth, g)
    assert 1 <= out["result"]["depth"] <= 6


def test_not_found_suggests_names(pool):
    g, _ = pool
    out = read.blast_radius("inventory-proxy", graph=g)
    assert out["error"] == "not_found"
    assert "inventory-db-proxy" in out["did_you_mean"]


# --- root cause -------------------------------------------------------------------

@pytest.mark.parametrize("scenario", sorted(EXPECTED))
def test_common_cause_and_recent_change(graph, scenario):
    info = inject_scenario(scenario, graph)
    root, version = EXPECTED[scenario]

    cause = rootcause.find_common_cause(info["alerting_services"], graph)
    assert_shape(cause)
    top = cause["result"]["candidates"][0]
    assert top["name"] == root
    assert top["likely_root_cause"] is True
    assert f"svc:{root}" in cause["node_uids"]

    changes = rootcause.recent_changes([root], 60, graph)["result"]["changes"]
    if version:
        assert changes[0]["version"] == version
        assert changes[0]["author"] and changes[0]["message"]
    else:
        # Red herring: there IS a fresh deploy, just not on the root cause.
        assert changes == []
        unrelated = rootcause.recent_changes(["email-sender"], 60, graph)["result"]["changes"]
        assert len(unrelated) == 1


def test_common_cause_needs_services(graph):
    assert rootcause.find_common_cause([], graph)["error"] == "bad_request"


# --- algorithms -------------------------------------------------------------------

def test_pagerank_ranks_platform_first(pool):
    g, _ = pool
    out = algorithms.critical_services(5, "inventory-db-proxy", g)
    assert_shape(out)
    assert out["result"]["top"][0]["name"] == "service-mesh"
    assert out["result"]["focus"]["name"] == "inventory-db-proxy"
    assert 1 <= out["result"]["focus"]["rank"] <= out["result"]["focus"]["out_of"]


def test_betweenness(pool):
    g, _ = pool
    out = algorithms.chokepoints(3, graph=g)
    assert_shape(out)
    scores = [r["score"] for r in out["result"]["top"]]
    assert len(scores) == 3 and scores == sorted(scores, reverse=True)


def test_failure_path(pool):
    g, _ = pool
    out = algorithms.failure_path("cdn-edge", "inventory-db-proxy", g)
    path = [h["name"] for h in out["result"]["path"]]
    assert path[0] == "cdn-edge" and path[-1] == "inventory-db-proxy"
    assert len(out["edge_uids"]) == out["result"]["hops"] == len(path) - 1


def test_failure_path_against_the_arrow(pool):
    g, _ = pool
    out = algorithms.failure_path("service-mesh", "cdn-edge", g)
    assert out["result"]["path"] is None


# --- memory -------------------------------------------------------------------------

@pytest.mark.parametrize("scenario", sorted(PAST_INCIDENT))
def test_recall_finds_matching_incident(graph, scenario):
    info = inject_scenario(scenario, graph)
    out = memory.recall_similar(info["alerting_services"], graph)
    assert_shape(out)
    assert out["result"]["incidents"][0]["id"] == PAST_INCIDENT[scenario]


def test_recall_nothing_nearby(pool):
    g, _ = pool
    assert memory.recall_similar(["etl-scheduler"], g)["result"]["incidents"] == []


# --- MCP -------------------------------------------------------------------------

def test_mcp_registers_every_tool():
    from sentinel.mcp_server import server

    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {
        "get_active_alerts", "get_service_context", "trace_dependencies", "blast_radius",
        "find_common_cause", "recent_changes", "critical_services", "chokepoints",
        "failure_path", "recall_similar", "propose_action", "conclude_investigation",
    }
