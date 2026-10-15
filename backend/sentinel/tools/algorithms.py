"""Graph algorithm tools (FalkorDB `algo.*` procedures), used to explain *why* a failure matters."""
from falkordb import Graph

from ..db import rows
from .common import check_services, clamp, graph_or_default, result

PAGERANK_CYPHER = """
CALL algo.pageRank('Service', 'DEPENDS_ON') YIELD node, score
RETURN node.name AS name, node.uid AS uid, node.tier AS tier, node.status AS status, score
ORDER BY score DESC, name
"""

BETWEENNESS_CYPHER = """
CALL algo.betweenness({nodeLabels: ['Service'], relationshipTypes: ['DEPENDS_ON']}) YIELD node, score
RETURN node.name AS name, node.uid AS uid, node.tier AS tier, node.status AS status, score
ORDER BY score DESC, name
"""


def _ranked(g: Graph, cypher: str, top: int, focus: str | None) -> tuple[list[dict], dict | None]:
    ranked = rows(g, cypher)
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
        r["score"] = round(float(r["score"]), 4)
    hit = next((r for r in ranked if r["name"] == focus), None) if focus else None
    if hit:
        hit = {**hit, "out_of": len(ranked)}
    return ranked[:top], hit


def critical_services(top: int = 10, service: str | None = None, graph: Graph | None = None) -> dict:
    """PageRank over DEPENDS_ON: rank flows to the services the most things depend on.

    Pass `service` to also get that service's rank.
    """
    g = graph_or_default(graph)
    if service and (err := check_services(g, [service])):
        return err
    n = clamp(top, 1, 25, 10)
    items, focus = _ranked(g, PAGERANK_CYPHER, n, service)
    return result({"algorithm": "pageRank", "top": items, "focus": focus}, PAGERANK_CYPHER,
                  [r["uid"] for r in items] + ([focus["uid"]] if focus else []))


def chokepoints(top: int = 10, service: str | None = None, graph: Graph | None = None) -> dict:
    """Betweenness centrality: services that sit on the most dependency paths (single points of failure)."""
    g = graph_or_default(graph)
    if service and (err := check_services(g, [service])):
        return err
    n = clamp(top, 1, 25, 10)
    items, focus = _ranked(g, BETWEENNESS_CYPHER, n, service)
    return result({"algorithm": "betweenness", "top": items, "focus": focus}, BETWEENNESS_CYPHER,
                  [r["uid"] for r in items] + ([focus["uid"]] if focus else []))


FAILURE_PATH_CYPHER = """
MATCH (a:Service {name: $from}), (b:Service {name: $to})
CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['DEPENDS_ON'], weightProp: 'weight'})
YIELD path, pathWeight
RETURN [n IN nodes(path) | n.uid] AS uids, [n IN nodes(path) | n.name] AS names,
       [n IN nodes(path) | n.status] AS statuses, [r IN relationships(path) | r.uid] AS edges, pathWeight
"""


def failure_path(from_service: str, to_service: str, graph: Graph | None = None) -> dict:
    """Shortest DEPENDS_ON path from a caller to a failing dependency: how the failure propagates."""
    g = graph_or_default(graph)
    if err := check_services(g, [from_service, to_service]):
        return err
    found = rows(g, FAILURE_PATH_CYPHER, {"from": from_service, "to": to_service})
    if not found:
        return result({"from": from_service, "to": to_service, "path": None,
                       "message": f"{from_service} does not depend on {to_service}"},
                      FAILURE_PATH_CYPHER, [f"svc:{from_service}", f"svc:{to_service}"])
    p = found[0]
    hops = [{"name": n, "uid": u, "status": s} for n, u, s in zip(p["names"], p["uids"], p["statuses"])]
    return result({"from": from_service, "to": to_service, "hops": len(p["edges"]), "path": hops},
                  FAILURE_PATH_CYPHER, p["uids"], p["edges"])
