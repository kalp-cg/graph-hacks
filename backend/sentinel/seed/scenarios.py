"""Incident scenarios. Each one resets to the baseline first, so injecting is idempotent."""
from falkordb import Graph

from ..db import get_graph
from .generator import now_ms, seed_baseline
from .history import create_deployments, sha_for

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
}


def inject_scenario(name: str, graph: Graph | None = None, now: int | None = None) -> dict:
    """Reset to the baseline, then break things the way the scenario describes."""
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario {name!r}; choose one of {sorted(SCENARIOS)}")
    spec = SCENARIOS[name]
    graph = graph or get_graph()
    now = now or now_ms()
    seed_baseline(graph, now)

    d = spec["deploy"]
    create_deployments(graph, [{
        "svc": d["svc"], "version": d["version"], "at": now - d["minutes_ago"] * MIN_MS,
        "summary": d["message"], "sha": sha_for(d["svc"], d["version"]), "message": d["message"],
        "files": 3, "author": d["author"],
    }])

    root, root_status = spec["root"]
    graph.query("MATCH (s:Service {name: $name}) SET s.status = $status", {"name": root, "status": root_status})

    alerts = [
        {"id": f"ALR-{1001 + i}", "svc": svc, "metric": metric, "value": value, "threshold": threshold,
         "at": now - (3 - min(i, 2)) * MIN_MS}
        for i, (svc, metric, value, threshold) in enumerate(spec["alerts"])
    ]
    graph.query(
        "UNWIND $rows AS r MATCH (s:Service {name: r.svc}) SET s.status = 'degraded' "
        "CREATE (:Alert {uid: 'alert:' + r.id, id: r.id, metric: r.metric, value: r.value, "
        "threshold: r.threshold, at: r.at, status: 'firing'})-[:FIRED_ON]->(s)",
        {"rows": alerts},
    )
    return {
        "scenario": name,
        "title": spec["title"],
        "alerting_services": [a["svc"] for a in alerts],
        "alert_uids": [f"alert:{a['id']}" for a in alerts],
    }
