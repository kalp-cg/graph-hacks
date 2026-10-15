"""Incident scenarios and the soft reset that sits between them.

`soft_reset` restores a healthy, quiet infrastructure but **keeps learned memory**: incidents the agent
resolved (and the alerts, actions and deployments they point to) survive, so re-running a similar incident
can be faster. `seed_baseline` (python -m sentinel.seed --reset) is the hard reset that wipes everything.
"""
import random

from falkordb import Graph

from ..db import get_graph, rows
from .catalog import CHAOS_CHANGES
from .generator import now_ms, seed_baseline
from .history import sha_for

MIN_MS = 60 * 1000

SCENARIOS: dict[str, dict] = {
    "db-pool-exhaustion": {
        "title": "Checkout, cart and orders slow down",
        "deploy": {"svc": "inventory-db-proxy", "version": "v4.2.0", "minutes_ago": 6, "author": "priya",
                   "message": "Reduce max pool size to 10 to cut DB costs"},
        "root": ("inventory-db-proxy", "down"),
        "alerts": [("checkout-api", "p99_latency_ms", 8700, 800),
                   ("cart-service", "p99_latency_ms", 6100, 600),
                   ("orders-service", "p99_latency_ms", 5400, 700)],
    },
    "bad-config-push": {
        "title": "Login and profile latency spike",
        "deploy": {"svc": "feature-flags", "version": "v4.0.3", "minutes_ago": 8, "author": "eva",
                   "message": "Roll out strict-session-validation to 100% of traffic"},
        "root": ("feature-flags", "degraded"),
        "alerts": [("auth-service", "p99_latency_ms", 2900, 500),
                   ("user-profile", "p99_latency_ms", 1800, 400)],
    },
    "cache-stampede": {
        # Red herring: the only recent deploy is on an unrelated service. The real cause has no deploy.
        "title": "Search and recommendations erroring",
        "deploy": {"svc": "email-sender", "version": "v4.0.3", "minutes_ago": 4, "author": "zoe",
                   "message": "Update order-confirmation email template"},
        "root": ("redis-cache", "degraded"),
        "alerts": [("search-service", "error_rate", 0.21, 0.02),
                   ("recommendations", "error_rate", 0.34, 0.05)],
    },
    "kafka-rebalance-storm": {
        # No seeded memory matches this one: the first run is a full investigation, the second can use
        # what the agent learned the first time.
        "title": "Payments, notifications and inventory lagging",
        "deploy": {"svc": "kafka-bus", "version": "v4.1.0", "minutes_ago": 5, "author": "dan",
                   "message": "Raise partitions 12 -> 48 and switch to eager rebalancing"},
        "root": ("kafka-bus", "degraded"),
        "alerts": [("payments-api", "consumer_lag_s", 95, 10),
                   ("notifications", "consumer_lag_s", 240, 30),
                   ("inventory-service", "consumer_lag_s", 120, 15)],
    },
}


def soft_reset(graph: Graph) -> None:
    """Healthy, quiet infrastructure; learned incidents and everything they reference are kept."""
    graph.query("MATCH (s:Service) SET s.status = 'healthy', s.root_fault = false")
    graph.query("MATCH (d:Database) SET d.status = 'healthy'")
    graph.query("MATCH ()-[r:DEPENDS_ON]->() SET r.breaker = 'closed'")
    graph.query("MATCH (a:Alert {status: 'firing'}) SET a.status = 'resolved'")
    # Unfinished investigations don't become memory (recall only reads resolved incidents).
    graph.query("MATCH (i:Incident) WHERE i.status <> 'resolved' SET i.status = 'abandoned'")
    graph.query("MATCH (a:Action) WHERE a.status IN ['pending', 'approved'] SET a.status = 'expired'")
    # Drop scenario leftovers that no incident points to. (OPTIONAL MATCH + count rather than pattern
    # comprehensions in WHERE, which FalkorDB 4.x rejects.)
    for label, rel in (("Alert", "TRIGGERED_BY"), ("Action", "RESOLVED_BY"), ("Page", "PAGED")):
        graph.query(f"MATCH (n:{label}) OPTIONAL MATCH (n)<-[r:{rel}]-(:Incident) "
                    "WITH n, count(r) AS refs WHERE refs = 0 DETACH DELETE n")
    graph.query(
        "MATCH (d:Deployment {origin: 'scenario'}) OPTIONAL MATCH (d)<-[r:ROOT_CAUSE]-(:Incident) "
        "WITH d, count(r) AS refs WHERE refs = 0 "
        "OPTIONAL MATCH (d)-[:CONTAINS]->(c:Commit) DETACH DELETE d, c"
    )
    graph.query("MATCH (d:Deployment {origin: 'scenario'}) SET d.status = 'rolled_back'")


def _deploy(graph: Graph, svc: str, version: str, author: str, message: str, at: int) -> None:
    """MERGE a scenario deployment (re-running re-deploys the same change; memory may point at it)."""
    sha = sha_for(svc, version)
    graph.query(
        "MATCH (s:Service {name: $svc}), (p:Person {handle: $author}) "
        "MERGE (dep:Deployment {uid: 'dep:' + $svc + ':' + $version}) "
        "SET dep.id = $svc + '@' + $version, dep.version = $version, dep.at = $at, dep.status = 'live', "
        "dep.change_summary = $message, dep.origin = 'scenario' "
        "MERGE (dep)-[:DEPLOYED_TO]->(s) "
        "MERGE (c:Commit {uid: 'commit:' + $sha}) SET c.sha = $sha, c.message = $message, c.files_changed = 3 "
        "MERGE (dep)-[:CONTAINS]->(c) MERGE (c)-[:AUTHORED_BY]->(p)",
        {"svc": svc, "version": version, "author": author, "message": message, "sha": sha, "at": at},
    )


def inject_scenario(name: str, graph: Graph | None = None, now: int | None = None, fresh: bool = False) -> dict:
    """Restore a healthy graph (soft reset, or a full re-seed if `fresh` or empty), then break things."""
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario {name!r}; choose one of {sorted(SCENARIOS)}")
    spec = SCENARIOS[name]
    graph = graph or get_graph()
    now = now or now_ms()
    has_data = bool(rows(graph, "MATCH (s:Service) RETURN count(s) AS n")[0]["n"]) if not fresh else False
    if has_data:
        soft_reset(graph)
    else:
        seed_baseline(graph, now)

    d = spec["deploy"]
    _deploy(graph, d["svc"], d["version"], d["author"], d["message"], now - d["minutes_ago"] * MIN_MS)

    root, root_status = spec["root"]
    graph.query("MATCH (s:Service {name: $name}) SET s.status = $status, s.root_fault = true",
                {"name": root, "status": root_status})

    stamp = now // 1000 % 100000  # keeps alert ids unique across re-runs
    alerts = [
        {"id": f"ALR-{stamp}-{i + 1}", "svc": svc, "metric": metric, "value": value, "threshold": threshold,
         "at": now - (3 - min(i, 2)) * MIN_MS}
        for i, (svc, metric, value, threshold) in enumerate(spec["alerts"])
    ]
    graph.query(
        "UNWIND $rows AS r MATCH (s:Service {name: r.svc}) SET s.status = 'degraded' "
        "CREATE (:Alert {uid: 'alert:' + r.id, id: r.id, metric: r.metric, value: r.value, "
        "threshold: r.threshold, at: r.at, status: 'firing', scenario: $scenario})-[:FIRED_ON]->(s)",
        {"rows": alerts, "scenario": name},
    )
    return {
        "scenario": name,
        "title": spec["title"],
        "alerting_services": [a["svc"] for a in alerts],
        "alert_uids": [f"alert:{a['id']}" for a in alerts],
    }


TIER_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def inject_chaos(service: str, mode: str = "down", with_deploy: bool = False, graph: Graph | None = None,
                 now: int | None = None) -> dict:
    """Break any service. Its most important direct callers start alerting. Nothing here is scripted:
    the agent has to work it out from the graph like any other incident."""
    graph = graph or get_graph()
    now = now or now_ms()
    if not rows(graph, "MATCH (s:Service {name: $n}) RETURN count(s) AS c", {"n": service})[0]["c"]:
        raise ValueError(f"unknown service {service!r}")
    mode = mode if mode in ("down", "degraded") else "down"
    soft_reset(graph)

    deploy = None
    if with_deploy:
        rng = random.Random(f"{service}:{now // 60000}")
        author = rows(graph, "MATCH (:Service {name: $n})<-[:OWNS]-(:Team)<-[:MEMBER_OF]-(p:Person) "
                             "RETURN p.handle AS h ORDER BY h", {"n": service})
        version = f"v9.{rng.randint(0, 9)}.{rng.randint(1, 9)}"
        message = rng.choice(CHAOS_CHANGES)
        _deploy(graph, service, version, rng.choice(author)["h"] if author else "dan", message, now - 4 * MIN_MS)
        deploy = {"version": version, "message": message}

    graph.query("MATCH (s:Service {name: $n}) SET s.status = $mode, s.root_fault = true", {"n": service, "mode": mode})
    callers = rows(graph, "MATCH (c:Service)-[:DEPENDS_ON]->(:Service {name: $n}) "
                          "RETURN c.name AS name, c.tier AS tier, coalesce(c.revenue_per_min, 0) AS rev", {"n": service})
    callers.sort(key=lambda c: (TIER_RANK.get(c["tier"], 9), -c["rev"], c["name"]))
    alerting = [c["name"] for c in callers[:3]] or [service]
    stamp = now // 1000 % 100000
    metric = ("p99_latency_ms", 4200, 600) if mode == "degraded" else ("error_rate", 0.42, 0.02)
    alerts = [{"id": f"ALR-{stamp}-{i + 1}", "svc": name, "metric": metric[0], "value": metric[1],
               "threshold": metric[2], "at": now - (3 - min(i, 2)) * MIN_MS} for i, name in enumerate(alerting)]
    graph.query(
        "UNWIND $rows AS r MATCH (s:Service {name: r.svc}) "
        "SET s.status = CASE WHEN s.name = $root THEN s.status ELSE 'degraded' END "
        "CREATE (:Alert {uid: 'alert:' + r.id, id: r.id, metric: r.metric, value: r.value, "
        "threshold: r.threshold, at: r.at, status: 'firing', scenario: 'chaos'})-[:FIRED_ON]->(s)",
        {"rows": alerts, "root": service},
    )
    return {"scenario": "chaos", "title": f"Chaos: {service} {mode}", "target": service, "deploy": deploy,
            "alerting_services": alerting, "alert_uids": [f"alert:{a['id']}" for a in alerts]}


def reset(graph: Graph | None = None, keep_memory: bool = True) -> None:
    """Soft reset (keeps learned memory) or hard reset (re-seed everything)."""
    graph = graph or get_graph()
    if keep_memory and rows(graph, "MATCH (s:Service) RETURN count(s) AS n")[0]["n"]:
        soft_reset(graph)
    else:
        seed_baseline(graph)
