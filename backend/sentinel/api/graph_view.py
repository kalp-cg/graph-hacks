"""Read models for the UI: the graph to draw and the incident list."""
from typing import Any

from ..db import get_graph, rows
from ..tools.common import now_ms

RECENT_MS = 2 * 60 * 60 * 1000

# Which nodes the UI draws. Infrastructure always; context nodes only when they matter right now.
NODE_QUERIES = [
    "MATCH (n:Service) OPTIONAL MATCH (t:Team)-[:OWNS]->(n) RETURN n, 'Service' AS type, t.name AS team",
    "MATCH (n:Database) OPTIONAL MATCH (t:Team)-[:OWNS]->(n) RETURN n, 'Database' AS type, t.name AS team",
    "MATCH (n:Team) RETURN n, 'Team' AS type, n.name AS team",
    # On-call people, plus authors of recent changes.
    "MATCH (n:Person)-[oc:ON_CALL]->(t:Team) WHERE oc.from <= $now AND oc.to > $now "
    "RETURN DISTINCT n, 'Person' AS type, t.name AS team",
    "MATCH (d:Deployment)-[:CONTAINS]->(:Commit)-[:AUTHORED_BY]->(n:Person)-[:MEMBER_OF]->(t:Team) "
    "WHERE d.at >= $since RETURN DISTINCT n, 'Person' AS type, t.name AS team",
    # Recent deployments and their commits, plus deployments that incidents blame.
    "MATCH (n:Deployment) WHERE n.at >= $since RETURN n, 'Deployment' AS type, null AS team",
    "MATCH (:Incident)-[:ROOT_CAUSE]->(n:Deployment) RETURN DISTINCT n, 'Deployment' AS type, null AS team",
    "MATCH (d:Deployment)-[:CONTAINS]->(n:Commit) WHERE d.at >= $since RETURN n, 'Commit' AS type, null AS team",
    "MATCH (n:Alert {status: 'firing'}) RETURN n, 'Alert' AS type, null AS team",
    "MATCH (n:Incident) RETURN n, 'Incident' AS type, null AS team",
    "MATCH (n:Runbook) RETURN n, 'Runbook' AS type, null AS team",
    "MATCH (n:Action) WHERE n.status = 'pending' OR n.created_at >= $since RETURN n, 'Action' AS type, null AS team",
    "MATCH (n:Page) WHERE n.at >= $since RETURN n, 'Page' AS type, null AS team",
]

KEEP = ("name", "status", "tier", "layer", "language", "version", "at", "change_summary", "message", "sha",
        "metric", "value", "threshold", "id", "title", "severity", "summary", "steps_taken", "kind", "target",
        "reason", "risk", "outcome", "role", "handle", "engine", "size_gb", "learned", "root_cause_service",
        "revenue_per_min", "root_fault")


def _label(n: dict, t: str) -> str:
    if t == "Deployment":
        return f"{n['uid'].split(':')[1]} {n.get('version', '')}"
    if t == "Commit":
        return (n.get("message") or n.get("sha", ""))[:40]
    if t == "Alert":
        return f"{n.get('metric')} {n.get('value')}"
    if t == "Incident":
        return n.get("id", "")
    if t == "Action":
        return f"{n.get('kind')} {n.get('target')}"
    if t == "Runbook":
        return n.get("title", "")
    if t == "Page":
        return "page"
    return n.get("name", n["uid"])


def graph_snapshot() -> dict[str, Any]:
    g = get_graph()
    now = now_ms()
    params = {"now": now, "since": now - RECENT_MS}
    nodes: dict[str, dict] = {}
    # One round trip instead of one per query: matters when the database is a network hop away.
    for r in rows(g, " UNION ALL ".join(NODE_QUERIES), params):
        p = r["n"].properties
        if p.get("uid") in nodes:
            continue
        # `id` is the graph key (the uid); a node's own id property (INC-0042, ALR-...) becomes `ref`.
        props = {("ref" if k == "id" else k): p[k] for k in KEEP if k in p}
        nodes[p["uid"]] = {**props, "id": p["uid"], "type": r["type"], "label": _label(p, r["type"]),
                           "team": r["team"]}

    for metric, q in (("pagerank", "CALL algo.pageRank('Service', 'DEPENDS_ON') YIELD node, score "
                                   "RETURN node.uid AS uid, score"),
                      ("betweenness", "CALL algo.betweenness({nodeLabels: ['Service'], relationshipTypes: "
                                      "['DEPENDS_ON']}) YIELD node, score RETURN node.uid AS uid, score")):
        for r in rows(g, q):
            if r["uid"] in nodes:
                nodes[r["uid"]][metric] = round(float(r["score"]), 4)

    links = []
    for r in rows(g, "MATCH (a)-[r]->(b) WHERE a.uid IN $uids AND b.uid IN $uids "
                     "RETURN a.uid AS s, b.uid AS t, type(r) AS type, r.uid AS uid, r.breaker AS breaker",
                  {"uids": list(nodes)}):
        if r["type"] == "MEMBER_OF":
            continue
        links.append({"id": r["uid"] or f"{r['type']}:{r['s']}->{r['t']}", "source": r["s"], "target": r["t"],
                      "type": r["type"], **({"breaker": r["breaker"]} if r["breaker"] else {})})
    return {"nodes": list(nodes.values()), "links": links, "at": now}


def incidents_view() -> list[dict]:
    g = get_graph()
    out = rows(
        g,
        "MATCH (i:Incident) "
        "OPTIONAL MATCH (i)-[:ROOT_CAUSE]->(rc) OPTIONAL MATCH (rc)-[:DEPLOYED_TO]->(rs:Service) "
        "OPTIONAL MATCH (i)-[:RESOLVED_BY]->(a:Action) "
        "OPTIONAL MATCH (i)-[:SIMILAR_TO]->(o:Incident) "
        "OPTIONAL MATCH (i)-[:AFFECTED]->(s:Service) "
        "RETURN i.uid AS uid, i.id AS id, i.title AS title, i.status AS status, i.severity AS severity, "
        "i.summary AS summary, i.steps_taken AS steps_taken, i.opened_at AS opened_at, "
        "i.resolved_at AS resolved_at, coalesce(i.learned, false) AS learned, rc.uid AS root_cause_uid, "
        "coalesce(rs.name, rc.name) AS root_cause_service, "
        "collect(DISTINCT {kind: a.kind, status: a.status}) AS actions, collect(DISTINCT o.id) AS similar_to, "
        "collect(DISTINCT s.name) AS affected ORDER BY opened_at DESC",
    )
    for r in out:
        r["actions"] = [a for a in r["actions"] if a.get("kind")]
    return out
