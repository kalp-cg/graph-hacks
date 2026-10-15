"""Memory tools: recall past incidents by graph proximity, not text similarity."""
from falkordb import Graph

from ..db import rows
from .common import check_services, graph_or_default, result

# A past incident is relevant if it touched a service these services depend on (<= 2 hops downstream,
# where failures come from) or the services themselves. Each touched service adds weight / (1 + hops):
# a root-cause link (direct, or via the deployment that caused it) weighs 2, an AFFECTED link 1.
RECALL_CYPHER = """
UNWIND $services AS name
MATCH p = (s:Service {name: name})-[:DEPENDS_ON*0..2]->(n:Service)
WITH n, min(length(p)) AS hops
MATCH (i:Incident {status: 'resolved'})
WHERE (i)-[:AFFECTED|ROOT_CAUSE]->(n) OR (i)-[:ROOT_CAUSE]->(:Deployment)-[:DEPLOYED_TO]->(n)
WITH i, n, hops,
     size([(i)-[:ROOT_CAUSE]->(n) | 1]) + size([(i)-[:ROOT_CAUSE]->(:Deployment)-[:DEPLOYED_TO]->(n) | 1]) AS rc
WITH i, n, hops, CASE WHEN rc > 0 THEN 2.0 ELSE 1.0 END AS weight
WITH i, collect(DISTINCT n.name) AS via, sum(weight / (1 + hops)) AS score
OPTIONAL MATCH (i)-[:ROOT_CAUSE]->(rc)
OPTIONAL MATCH (rc)-[:DEPLOYED_TO]->(rcs:Service)
OPTIONAL MATCH (i)-[:RESOLVED_BY]->(a:Action)
OPTIONAL MATCH (i)-[:FOLLOWED]->(rb:Runbook)
OPTIONAL MATCH (i)-[:SIMILAR_TO]-(other:Incident)
RETURN i.id AS id, i.uid AS uid, i.title AS title, i.severity AS severity, i.summary AS summary,
       i.steps_taken AS steps_taken, rc.uid AS root_cause_uid, coalesce(rcs.name, rc.name) AS root_cause_service,
       collect(DISTINCT a.kind) AS fixes, rb.uid AS runbook_uid, rb.title AS runbook, rb.steps AS runbook_steps,
       collect(DISTINCT other.id) AS similar_to, via, score
ORDER BY score DESC, id DESC
LIMIT 5
"""

def recall_similar(services: list[str], graph: Graph | None = None) -> dict:
    """Resolved past incidents near these services (themselves or <= 2 hops downstream), best match first."""
    g = graph_or_default(graph)
    names = sorted(set(services or []))
    if not names:
        return {"error": "bad_request", "message": "pass at least one service name"}
    if err := check_services(g, names):
        return err
    found = rows(g, RECALL_CYPHER, {"services": names})
    for r in found:
        r["score"] = round(float(r["score"]), 3)
    uids = [u for r in found for u in (r["uid"], r["root_cause_uid"], r["runbook_uid"]) if u]
    return result({"services": names, "incidents": found}, RECALL_CYPHER, uids)
