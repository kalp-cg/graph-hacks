"""Read / traversal tools. All values from the agent go in as query parameters."""
from falkordb import Graph

from ..db import rows
from .common import capped, check_services, clamp, graph_or_default, now_ms, result

CONTEXT_CYPHER = """
MATCH (s:Service {name: $service})
OPTIONAL MATCH (t:Team)-[:OWNS]->(s)
OPTIONAL MATCH (p:Person)-[oc:ON_CALL]->(t) WHERE oc.from <= $now AND oc.to > $now
OPTIONAL MATCH (s)-[:READS_FROM|WRITES_TO]->(db:Database)
WITH s, t, collect(DISTINCT p) AS oncall, collect(DISTINCT db) AS dbs
OPTIONAL MATCH (d:Deployment)-[:DEPLOYED_TO]->(s)
WITH s, t, oncall, dbs, d ORDER BY d.at DESC
RETURN s, t, oncall, dbs, collect(d)[0..3] AS deploys
"""


def get_service_context(service: str, graph: Graph | None = None) -> dict:
    """Owner team, current on-call, tier/status, databases and the last 3 deployments of a service."""
    g = graph_or_default(graph)
    if err := check_services(g, [service]):
        return err
    r = rows(g, CONTEXT_CYPHER, {"service": service, "now": now_ms()})[0]
    s, t = r["s"].properties, r["t"].properties if r["t"] else {}
    oncall = [p.properties for p in r["oncall"]]
    dbs = [d.properties for d in r["dbs"]]
    deploys = [d.properties for d in r["deploys"]]
    value = {
        "service": {k: s.get(k) for k in ("name", "uid", "tier", "status", "layer", "language", "version")},
        "team": t.get("name"),
        "slack_channel": t.get("slack_channel"),
        "on_call": [{"name": p["name"], "handle": p["handle"], "uid": p["uid"]} for p in oncall],
        "databases": [{"name": d["name"], "engine": d["engine"], "uid": d["uid"]} for d in dbs],
        "recent_deployments": [
            {"uid": d["uid"], "version": d["version"], "at": d["at"], "status": d["status"],
             "change_summary": d["change_summary"]}
            for d in deploys
        ],
    }
    uids = [s["uid"], t.get("uid")] + [p["uid"] for p in oncall] + [d["uid"] for d in dbs] + [d["uid"] for d in deploys]
    return result(value, CONTEXT_CYPHER, [u for u in uids if u])


ALERTS_CYPHER = """
MATCH (a:Alert {status: 'firing'})-[:FIRED_ON]->(s:Service)
RETURN a.uid AS uid, a.id AS id, a.metric AS metric, a.value AS value, a.threshold AS threshold,
       a.at AS at, s.name AS service, s.uid AS service_uid, s.status AS service_status
ORDER BY a.at
"""


def get_active_alerts(graph: Graph | None = None) -> dict:
    """Every alert that is currently firing, oldest first, with the service it fired on."""
    g = graph_or_default(graph)
    alerts = rows(g, ALERTS_CYPHER)
    uids = [u for a in alerts for u in (a["uid"], a["service_uid"])]
    return result(alerts, ALERTS_CYPHER, uids)


def _path_hops(g: Graph, cypher: str, params: dict) -> tuple[list[dict], list[str]]:
    """Run a DEPENDS_ON traversal that returns one row per reachable service plus the edge uids on its path."""
    found = rows(g, cypher, params)
    edges = [e for r in found for e in r.pop("edges")]
    return found, edges


def trace_dependencies(service: str, depth: int = 3, graph: Graph | None = None) -> dict:
    """Everything a service depends on, directly or transitively (downstream), nearest first."""
    g = graph_or_default(graph)
    if err := check_services(g, [service]):
        return err
    d = clamp(depth, 1, 6, 3)
    cypher = f"""
    MATCH p = (s:Service {{name: $service}})-[:DEPENDS_ON*1..{d}]->(dep:Service)
    WITH dep, min(length(p)) AS hops, collect(p) AS paths
    WITH dep, hops, [x IN paths WHERE length(x) = hops][0] AS p
    RETURN dep.name AS name, dep.uid AS uid, dep.status AS status, dep.tier AS tier, hops,
           [r IN relationships(p) | r.uid] AS edges
    ORDER BY hops, name
    """
    found, edges = _path_hops(g, cypher, {"service": service})
    items, truncated = capped(found)
    return result(
        {"service": service, "depth": d, "dependencies": items, "count": len(found)},
        cypher, [f"svc:{service}"] + [r["uid"] for r in found], edges, truncated=truncated,
    )


def blast_radius(service: str, depth: int = 6, graph: Graph | None = None) -> dict:
    """Everything that breaks if this service fails (upstream callers), with a count per tier."""
    g = graph_or_default(graph)
    if err := check_services(g, [service]):
        return err
    d = clamp(depth, 1, 6, 6)
    cypher = f"""
    MATCH p = (up:Service)-[:DEPENDS_ON*1..{d}]->(s:Service {{name: $service}})
    WITH up, min(length(p)) AS hops, collect(p) AS paths
    WITH up, hops, [x IN paths WHERE length(x) = hops][0] AS p
    RETURN up.name AS name, up.uid AS uid, up.tier AS tier, up.status AS status, hops,
           [r IN relationships(p) | r.uid] AS edges
    ORDER BY hops, name
    """
    found, edges = _path_hops(g, cypher, {"service": service})
    by_tier: dict[str, int] = {}
    for r in found:
        by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
    items, truncated = capped(found)
    return result(
        {"service": service, "depth": d, "impacted": items, "count": len(found), "by_tier": by_tier},
        cypher, [f"svc:{service}"] + [r["uid"] for r in found], edges, truncated=truncated,
    )
