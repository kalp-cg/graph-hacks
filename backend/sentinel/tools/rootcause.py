"""Root-cause tools: what do the failing services share, and what changed there recently."""
from falkordb import Graph

from ..db import rows
from .common import capped, check_services, clamp, graph_or_default, now_ms, result

# Candidates = services every alerting service can reach (hops 0 = the service itself).
# Rank: unhealthy with nothing unhealthy below it (the deepest failure) > unhealthy but explained
# by an unhealthy dependency (a symptom) > healthy. Then down before degraded, then nearest.
# The bare `WITH d, worst, total` is needed: FalkorDB raises a type mismatch when an OPTIONAL MATCH
# follows a filtered aggregation directly.
COMMON_CAUSE_CYPHER = """
UNWIND $services AS name
MATCH p = (s:Service {name: name})-[:DEPENDS_ON*0..5]->(d:Service)
WITH s, d, min(length(p)) AS dist
WITH d, count(s) AS hits, max(dist) AS worst, sum(dist) AS total
WHERE hits = $n
WITH d, worst, total
OPTIONAL MATCH (d)-[:DEPENDS_ON*1..5]->(x:Service) WHERE x.status <> 'healthy'
WITH d, worst, total, count(DISTINCT x) AS unhealthy_below
RETURN d.name AS name, d.uid AS uid, d.status AS status, d.tier AS tier, worst AS max_hops, total AS total_hops,
       unhealthy_below,
       CASE WHEN d.status = 'healthy' THEN 0 WHEN unhealthy_below = 0 THEN 2 ELSE 1 END AS rank,
       CASE d.status WHEN 'down' THEN 1 ELSE 0 END AS is_down
ORDER BY rank DESC, is_down DESC, max_hops, total_hops, name
LIMIT 5
"""

# FalkorDB only allows shortestPath() in WITH/RETURN, with both endpoints bound.
PATHS_CYPHER = """
UNWIND $services AS name
MATCH (s:Service {name: name}), (d:Service {uid: $target})
WHERE s <> d
WITH shortestPath((s)-[:DEPENDS_ON*]->(d)) AS p
WHERE p IS NOT NULL
RETURN [n IN nodes(p) | n.uid] AS nodes, [r IN relationships(p) | r.uid] AS edges
"""


def find_common_cause(services: list[str], graph: Graph | None = None) -> dict:
    """Services that ALL the given services depend on (including themselves), unhealthy and nearest first."""
    g = graph_or_default(graph)
    names = sorted(set(services or []))
    if not names:
        return {"error": "bad_request", "message": "pass at least one service name"}
    if err := check_services(g, names):
        return err
    candidates = rows(g, COMMON_CAUSE_CYPHER, {"services": names, "n": len(names)})
    for c in candidates:
        c["likely_root_cause"] = c.pop("rank") == 2
        c.pop("is_down")
    node_uids = [f"svc:{n}" for n in names]
    edge_uids: list[str] = []
    if candidates:
        top = candidates[0]["uid"]
        # Light up the path from each alerting service to the top candidate.
        for p in rows(g, PATHS_CYPHER, {"services": names, "target": top}):
            node_uids += p["nodes"]
            edge_uids += p["edges"]
        node_uids.append(top)
    return result({"services": names, "candidates": candidates}, COMMON_CAUSE_CYPHER, node_uids, edge_uids)


RECENT_CHANGES_CYPHER = """
MATCH (d:Deployment)-[:DEPLOYED_TO]->(s:Service)
WHERE s.name IN $services AND d.at >= $since
OPTIONAL MATCH (d)-[:CONTAINS]->(c:Commit)
OPTIONAL MATCH (c)-[:AUTHORED_BY]->(p:Person)
OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
RETURN d.uid AS uid, d.version AS version, d.at AS at, d.status AS status, s.name AS service,
       c.uid AS commit_uid, c.sha AS sha, c.message AS message,
       p.name AS author, p.uid AS author_uid, t.name AS author_team
ORDER BY d.at DESC
"""


def recent_changes(services: list[str], minutes: int = 60, graph: Graph | None = None) -> dict:
    """Deployments to the given services in the last N minutes, with commit message and author."""
    g = graph_or_default(graph)
    names = sorted(set(services or []))
    if err := check_services(g, names):
        return err
    window = clamp(minutes, 1, 7 * 24 * 60, 60)
    now = now_ms()
    found = rows(g, RECENT_CHANGES_CYPHER, {"services": names, "since": now - window * 60_000})
    for r in found:
        r["minutes_ago"] = round((now - r["at"]) / 60_000, 1)
    items, truncated = capped(found)
    uids = [u for r in found for u in (r["uid"], f"svc:{r['service']}", r["commit_uid"], r["author_uid"]) if u]
    return result({"services": names, "minutes": window, "changes": items}, RECENT_CHANGES_CYPHER, uids,
                  truncated=truncated)
