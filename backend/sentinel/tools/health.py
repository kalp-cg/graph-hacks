"""Recovery by traversal: a symptom service is healthy again once nothing unhealthy is reachable below it.

"Reachable" follows DEPENDS_ON through *closed* breakers only. Opening the breakers into a failing
service isolates it, so its callers fall back and recover even before the root cause is fixed.
"""
from collections import defaultdict

from falkordb import Graph

from ..db import rows


def recompute_health(graph: Graph) -> dict:
    """Recover symptom services (the ones with firing alerts) whose dependencies are healthy again.

    Root causes (unhealthy services without their own alert) only recover through an action.
    Returns the recovered service uids and the resolved alert uids.
    """
    found = rows(graph, "MATCH (s:Service) RETURN s.name AS name, s.status AS status, "
                        "coalesce(s.root_fault, false) AS fault")
    status = {r["name"]: r["status"] for r in found}
    faulty = {r["name"] for r in found if r["fault"]}
    deps: dict[str, list[str]] = defaultdict(list)
    for r in rows(graph, "MATCH (a:Service)-[r:DEPENDS_ON]->(b:Service) WHERE r.breaker <> 'open' "
                         "RETURN a.name AS a, b.name AS b"):
        deps[r["a"]].append(r["b"])
    alerts: dict[str, list[str]] = defaultdict(list)
    for r in rows(graph, "MATCH (a:Alert {status: 'firing'})-[:FIRED_ON]->(s:Service) "
                         "RETURN s.name AS svc, a.uid AS uid"):
        alerts[r["svc"]].append(r["uid"])

    def unhealthy_below(name: str) -> bool:
        seen, stack = set(), list(deps[name])
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            if status.get(cur) != "healthy":
                return True
            stack.extend(deps[cur])
        return False

    recovered: list[str] = []
    changed = True
    while changed:
        changed = False
        for name in sorted(alerts):
            # A service with its own fault (the root cause) only recovers through an action.
            if status.get(name) != "healthy" and name not in faulty and not unhealthy_below(name):
                status[name] = "healthy"
                recovered.append(name)
                changed = True

    # Alerts resolve on every healthy service with nothing unhealthy below it, including a root that an
    # action fixed directly (e.g. an edge service alerting on itself).
    resolved = [uid for name in sorted(alerts) if status.get(name) == "healthy" and not unhealthy_below(name)
                for uid in alerts[name]]
    if recovered:
        graph.query("UNWIND $names AS n MATCH (s:Service {name: n}) SET s.status = 'healthy'", {"names": recovered})
    if resolved:
        graph.query("UNWIND $uids AS u MATCH (a:Alert {uid: u}) SET a.status = 'resolved'", {"uids": resolved})
    return {"recovered": [f"svc:{n}" for n in recovered], "resolved_alerts": resolved}
