"""Seed memory: past incidents, the actions that fixed them, and runbooks.

Memory lives in the same graph as the infrastructure, linked to the services it
touched, so recalling "have we seen this before?" is a traversal.
"""
from falkordb import Graph

from .history import create_deployments, sha_for

DAY_MS = 24 * 60 * 60 * 1000
MIN_MS = 60 * 1000

RUNBOOKS = [
    {
        "slug": "db-pool-exhaustion",
        "title": "DB connection pool exhaustion",
        "steps": "1. Confirm p99 latency on callers of inventory-db-proxy. "
                 "2. Check recent deploys to the proxy for pool-size changes. "
                 "3. Roll back the deploy. 4. If still saturated, raise max pool size. "
                 "5. Page Platform on-call.",
        "services": ["inventory-db-proxy"],
    },
    {
        "slug": "feature-flag-rollback",
        "title": "Bad feature-flag / config push",
        "steps": "1. Diff the last flag push. 2. Roll back the feature-flags deploy. "
                 "3. Verify login success rate recovers.",
        "services": ["feature-flags", "config-service"],
    },
    {
        "slug": "cache-eviction-storm",
        "title": "Cache eviction storm / stampede",
        "steps": "1. Check redis-cache memory and eviction rate. 2. Open the circuit breaker on callers "
                 "so they fall back to the source of truth. 3. Scale up redis-cache. 4. Close breakers.",
        "services": ["redis-cache"],
    },
]

# Each past incident: who it hit, what caused it, and how it was fixed.
INCIDENTS = [
    {
        "id": "INC-0042",
        "title": "Checkout & cart timeouts",
        "severity": "SEV1",
        "age_days": 34,
        "minutes": 47,
        "summary": "Deploy v3.0.1 to inventory-db-proxy cut max pool size; callers queued for connections "
                   "and checkout p99 hit 9 s. Fixed by rollback plus a pool resize.",
        "steps_taken": 9,
        "affected": ["checkout-api", "cart-service", "inventory-service"],
        "root_cause": {"svc": "inventory-db-proxy", "version": "v3.0.1",
                       "message": "Lower max pool size to 20", "author": "dan"},
        "alerts": [("checkout-api", "p99_latency_ms", 9100, 800), ("cart-service", "p99_latency_ms", 6400, 600)],
        "actions": [("rollback", "dep"), ("page_oncall", "svc"), ("scale_up", "svc")],
        "runbook": "db-pool-exhaustion",
    },
    {
        "id": "INC-0057",
        "title": "Login latency spike",
        "severity": "SEV2",
        "age_days": 21,
        "minutes": 22,
        "summary": "A feature-flags push enabled an expensive token check for all users; auth p99 tripled. "
                   "Fixed by rolling back the flag push.",
        "steps_taken": 6,
        "affected": ["auth-service", "user-profile"],
        "root_cause": {"svc": "feature-flags", "version": "v2.9.1",
                       "message": "Enable strict-token-check for 100% of users", "author": "eva"},
        "alerts": [("auth-service", "p99_latency_ms", 2400, 500)],
        "actions": [("rollback", "dep")],
        "runbook": "feature-flag-rollback",
    },
    {
        "id": "INC-0063",
        "title": "Search degraded",
        "severity": "SEV2",
        "age_days": 9,
        "minutes": 31,
        "summary": "redis-cache hit maxmemory and started an eviction storm; search and recommendations "
                   "hammered their databases. Fixed by opening breakers and scaling the cache.",
        "steps_taken": 7,
        "affected": ["search-service", "recommendations"],
        "root_cause": {"svc": "redis-cache"},
        "alerts": [("search-service", "error_rate", 0.18, 0.02)],
        "actions": [("open_breaker", "svc"), ("scale_up", "svc")],
        "runbook": "cache-eviction-storm",
    },
]

SIMILAR = [("INC-0042", "INC-0063", 0.6, "both: shared platform dependency saturated, callers timed out")]


def build_runbooks(graph: Graph) -> None:
    graph.query(
        "UNWIND $rows AS r CREATE (b:Runbook {uid: 'rb:' + r.slug, title: r.title, steps: r.steps}) "
        "WITH b, r UNWIND r.services AS name MATCH (s:Service {name: name}) CREATE (b)-[:APPLIES_TO]->(s)",
        {"rows": RUNBOOKS},
    )


def build_incident(graph: Graph, inc: dict, now: int) -> None:
    opened = now - inc["age_days"] * DAY_MS
    resolved = opened + inc["minutes"] * MIN_MS
    graph.query(
        "CREATE (:Incident {uid: 'inc:' + $id, id: $id, title: $title, severity: $sev, status: 'resolved', "
        "opened_at: $opened, resolved_at: $resolved, summary: $summary, steps_taken: $steps})",
        {"id": inc["id"], "title": inc["title"], "sev": inc["severity"], "opened": opened,
         "resolved": resolved, "summary": inc["summary"], "steps": inc["steps_taken"]},
    )
    graph.query(
        "MATCH (i:Incident {id: $id}) UNWIND $names AS name MATCH (s:Service {name: name}) "
        "CREATE (i)-[:AFFECTED]->(s)",
        {"id": inc["id"], "names": inc["affected"]},
    )

    rc = inc["root_cause"]
    target_uid = f"svc:{rc['svc']}"
    if "version" in rc:
        # The bad deploy was rolled back, so it stays in history with that status.
        create_deployments(graph, [{
            "svc": rc["svc"], "version": rc["version"], "at": opened - 6 * MIN_MS,
            "summary": rc["message"], "sha": sha_for(rc["svc"], rc["version"]), "message": rc["message"],
            "files": 2, "author": rc["author"],
        }], status="rolled_back")
        target_uid = f"dep:{rc['svc']}:{rc['version']}"
    graph.query(
        "MATCH (i:Incident {id: $id}), (t {uid: $target}) CREATE (i)-[:ROOT_CAUSE]->(t)",
        {"id": inc["id"], "target": target_uid},
    )

    for n, (svc, metric, value, threshold) in enumerate(inc["alerts"], start=1):
        alert_id = f"{inc['id']}-A{n}"
        graph.query(
            "MATCH (i:Incident {id: $inc}), (s:Service {name: $svc}) "
            "CREATE (i)-[:TRIGGERED_BY]->(:Alert {uid: 'alert:' + $id, id: $id, metric: $metric, value: $value, "
            "threshold: $threshold, at: $at, status: 'resolved'})-[:FIRED_ON]->(s)",
            {"inc": inc["id"], "svc": svc, "id": alert_id, "metric": metric, "value": value,
             "threshold": threshold, "at": opened},
        )

    for n, (kind, on) in enumerate(inc["actions"], start=1):
        graph.query(
            "MATCH (i:Incident {id: $inc}), (t {uid: $target}) "
            "CREATE (i)-[:RESOLVED_BY]->(:Action {uid: 'act:' + $id, kind: $kind, status: 'executed', "
            "reason: 'past incident', risk: 'low', created_at: $at, executed_at: $at, approved_by: 'on-call'})"
            "-[:TARGETS]->(t)",
            {"inc": inc["id"], "id": f"{inc['id']}-{n}", "kind": kind,
             "target": target_uid if on == "dep" else f"svc:{rc['svc']}", "at": resolved},
        )

    graph.query(
        "MATCH (i:Incident {id: $id}), (b:Runbook {uid: 'rb:' + $rb}) CREATE (i)-[:FOLLOWED]->(b)",
        {"id": inc["id"], "rb": inc["runbook"]},
    )


def build_memory(graph: Graph, now: int) -> None:
    build_runbooks(graph)
    for inc in INCIDENTS:
        build_incident(graph, inc, now)
    graph.query(
        "UNWIND $rows AS r MATCH (a:Incident {id: r.a}), (b:Incident {id: r.b}) "
        "CREATE (a)-[:SIMILAR_TO {score: r.score, reason: r.reason}]->(b)",
        {"rows": [{"a": a, "b": b, "score": s, "reason": why} for a, b, s, why in SIMILAR]},
    )
