"""Incident lifecycle: every investigation becomes an Incident node, i.e. memory for the next one."""
from falkordb import Graph

from ..db import rows
from .common import graph_or_default, now_ms

RECENT_DEPLOY_MS = 2 * 60 * 60 * 1000


def next_incident_id(graph: Graph) -> str:
    found = rows(graph, "MATCH (i:Incident) RETURN max(toInteger(substring(i.id, 4))) AS n")
    n = found[0]["n"] or 0
    return f"INC-{max(1000, int(n)) + 1}"


def open_incident(run_id: str, graph: Graph | None = None) -> dict | None:
    """Create an `investigating` incident for the alerts firing now. None if nothing is firing."""
    g = graph_or_default(graph)
    firing = rows(g, "MATCH (a:Alert {status: 'firing'})-[:FIRED_ON]->(s:Service) "
                     "RETURN a.uid AS alert, s.name AS service")
    if not firing:
        return None
    inc_id = next_incident_id(g)
    services = sorted({f["service"] for f in firing})
    g.query(
        "CREATE (i:Incident {uid: 'inc:' + $id, id: $id, title: $title, severity: 'SEV2', status: 'investigating', "
        "opened_at: $now, run_id: $run, learned: true, steps_taken: 0}) "
        "WITH i UNWIND $alerts AS au MATCH (a:Alert {uid: au}) CREATE (i)-[:TRIGGERED_BY]->(a) "
        "WITH DISTINCT i UNWIND $services AS sn MATCH (s:Service {name: sn}) CREATE (i)-[:AFFECTED]->(s)",
        {"id": inc_id, "title": "Alerts on " + ", ".join(services), "now": now_ms(), "run": run_id,
         "alerts": [f["alert"] for f in firing], "services": services},
    )
    return {"id": inc_id, "uid": f"inc:{inc_id}", "services": services, "alerts": [f["alert"] for f in firing]}


def conclude_incident(run_id: str, root_cause_service: str, summary: str, steps_taken: int,
                      similar_to: str | None = None, graph: Graph | None = None) -> dict:
    """Record the root cause (the recent deploy on that service if there is one), summary and memory links."""
    g = graph_or_default(graph)
    inc = rows(g, "MATCH (i:Incident {run_id: $run}) RETURN i.uid AS uid, i.id AS id", {"run": run_id})
    if not inc:
        return {"error": "no_incident", "message": f"no incident for run {run_id}"}
    svc = rows(g, "MATCH (s:Service {name: $name}) RETURN s.uid AS uid", {"name": root_cause_service})
    if not svc:
        return {"error": "not_found", "message": f"No service named {root_cause_service!r}"}
    dep = rows(
        g,
        "MATCH (d:Deployment)-[:DEPLOYED_TO]->(:Service {name: $name}) WHERE d.at >= $since "
        "RETURN d.uid AS uid ORDER BY d.at DESC LIMIT 1",
        {"name": root_cause_service, "since": now_ms() - RECENT_DEPLOY_MS},
    )
    target = dep[0]["uid"] if dep else svc[0]["uid"]
    g.query(
        "MATCH (i:Incident {run_id: $run}) OPTIONAL MATCH (i)-[old:ROOT_CAUSE]->() DELETE old",
        {"run": run_id},
    )
    g.query(
        "MATCH (i:Incident {run_id: $run}), (t {uid: $target}) "
        "SET i.summary = $summary, i.steps_taken = $steps, i.root_cause_service = $svc, "
        "i.title = $title, i.status = CASE WHEN i.status = 'resolved' THEN 'resolved' ELSE 'mitigating' END "
        "CREATE (i)-[:ROOT_CAUSE]->(t)",
        {"run": run_id, "target": target, "summary": summary, "steps": int(steps_taken),
         "svc": root_cause_service, "title": f"{root_cause_service} failure"},
    )
    g.query(
        "MATCH (i:Incident {run_id: $run}), (rb:Runbook)-[:APPLIES_TO]->(:Service {name: $svc}) "
        "MERGE (i)-[:FOLLOWED]->(rb)",
        {"run": run_id, "svc": root_cause_service},
    )
    if similar_to:
        g.query(
            "MATCH (i:Incident {run_id: $run}), (o:Incident {id: $other}) WHERE i <> o "
            "MERGE (i)-[r:SIMILAR_TO]->(o) SET r.score = 1.0, r.reason = 'same root cause service'",
            {"run": run_id, "other": similar_to},
        )
    return {"incident": inc[0]["id"], "uid": inc[0]["uid"], "root_cause_uid": target}


def settle_incidents(graph: Graph | None = None) -> list[str]:
    """Mark incidents resolved once every alert that triggered them is resolved. Returns their ids."""
    g = graph_or_default(graph)
    done = rows(
        g,
        "MATCH (i:Incident)-[:TRIGGERED_BY]->(a:Alert) WHERE i.status IN ['investigating', 'mitigating'] "
        "WITH i, sum(CASE WHEN a.status = 'firing' THEN 1 ELSE 0 END) AS firing WHERE firing = 0 "
        "SET i.status = 'resolved', i.resolved_at = $now RETURN i.id AS id",
        {"now": now_ms()},
    )
    return [d["id"] for d in done]


def record_steps(run_id: str, steps: int, graph: Graph | None = None) -> None:
    """Store the final step count (the model may keep acting after it concluded)."""
    g = graph_or_default(graph)
    g.query("MATCH (i:Incident {run_id: $run}) SET i.steps_taken = $steps", {"run": run_id, "steps": int(steps)})
