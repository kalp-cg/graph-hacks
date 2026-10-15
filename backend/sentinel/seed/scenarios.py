"""Incident scenarios and the soft reset that sits between them.

`soft_reset` restores a healthy, quiet infrastructure but **keeps learned memory**: incidents the agent
resolved (and the alerts, actions and deployments they point to) survive, so re-running a similar incident
can be faster. `seed_baseline` (python -m sentinel.seed --reset) is the hard reset that wipes everything.
"""
from falkordb import Graph

from ..db import get_graph, rows
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
    graph.query("MATCH (s:Service) SET s.status = 'healthy'")
    graph.query("MATCH (d:Database) SET d.status = 'healthy'")
    graph.query("MATCH ()-[r:DEPENDS_ON]->() SET r.breaker = 'closed'")
    graph.query("MATCH (a:Alert {status: 'firing'}) SET a.status = 'resolved'")
    # Unfinished investigations don't become memory (recall only reads resolved incidents).
    graph.query("MATCH (i:Incident) WHERE i.status <> 'resolved' SET i.status = 'abandoned'")
    graph.query("MATCH (a:Action) WHERE a.status IN ['pending', 'approved'] SET a.status = 'expired'")
    # Drop scenario leftovers that no incident points to.
    graph.query("MATCH (a:Alert) WHERE size([(a)<-[:TRIGGERED_BY]-(:Incident) | 1]) = 0 DETACH DELETE a")
    graph.query("MATCH (a:Action) WHERE size([(a)<-[:RESOLVED_BY]-(:Incident) | 1]) = 0 DETACH DELETE a")
    graph.query("MATCH (p:Page) WHERE size([(p)<-[:PAGED]-(:Incident) | 1]) = 0 DETACH DELETE p")
    graph.query(
        "MATCH (d:Deployment {origin: 'scenario'}) WHERE size([(d)<-[:ROOT_CAUSE]-(:Incident) | 1]) = 0 "
        "OPTIONAL MATCH (d)-[:CONTAINS]->(c:Commit) DETACH DELETE d, c"
    )
    graph.query("MATCH (d:Deployment {origin: 'scenario'}) SET d.status = 'rolled_back'")


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
    sha = sha_for(d["svc"], d["version"])
    # MERGE: re-running a scenario re-deploys the same change (and a learned incident may point at it).
    graph.query(
        "MATCH (s:Service {name: $svc}), (p:Person {handle: $author}) "
        "MERGE (dep:Deployment {uid: 'dep:' + $svc + ':' + $version}) "
        "SET dep.id = $svc + '@' + $version, dep.version = $version, dep.at = $at, dep.status = 'live', "
        "dep.change_summary = $message, dep.origin = 'scenario' "
        "MERGE (dep)-[:DEPLOYED_TO]->(s) "
        "MERGE (c:Commit {uid: 'commit:' + $sha}) SET c.sha = $sha, c.message = $message, c.files_changed = 3 "
        "MERGE (dep)-[:CONTAINS]->(c) MERGE (c)-[:AUTHORED_BY]->(p)",
        {"svc": d["svc"], "version": d["version"], "author": d["author"], "message": d["message"],
         "sha": sha, "at": now - d["minutes_ago"] * MIN_MS},
    )

    root, root_status = spec["root"]
    graph.query("MATCH (s:Service {name: $name}) SET s.status = $status", {"name": root, "status": root_status})

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


def reset(graph: Graph | None = None, keep_memory: bool = True) -> None:
    """Soft reset (keeps learned memory) or hard reset (re-seed everything)."""
    graph = graph or get_graph()
    if keep_memory and rows(graph, "MATCH (s:Service) RETURN count(s) AS n")[0]["n"]:
        soft_reset(graph)
    else:
        seed_baseline(graph)
