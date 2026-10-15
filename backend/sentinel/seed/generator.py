"""Deterministic baseline graph: same input, same uids, every time (seed 42)."""
import random
import time

from falkordb import Graph

from ..db import get_graph
from .catalog import DATA_ACCESS, DATABASES, OBSERVABILITY, ON_CALL, PEOPLE, REVENUE_PER_MIN, SERVICES, TEAMS
from .history import build_history
from .indexes import create_indexes
from .memory import build_memory

SEED = 42
DAY_MS = 24 * 60 * 60 * 1000
PROTOCOLS = ["grpc", "http", "grpc", "tcp"]


def now_ms() -> int:
    return int(time.time() * 1000)


def wipe(graph: Graph) -> None:
    """Drop the whole graph. Deleting a graph that doesn't exist yet raises, which is fine."""
    try:
        graph.delete()
    except Exception:
        pass


def dependency_edges(rng: random.Random) -> list[tuple[str, str]]:
    """Hand-picked edges plus observability edges for business services.

    Asserts the DAG rule from catalog.py: a service only depends on services listed after it.
    """
    order = {name: i for i, (name, *_rest) in enumerate(SERVICES)}
    edges: list[tuple[str, str]] = []
    for name, _team, _tier, layer, _lang, deps in SERVICES:
        targets = list(deps)
        if layer == "business":
            # Not every service ships metrics/logs through the pipeline; pick deterministically.
            targets += [o for o in OBSERVABILITY if rng.random() < 0.5]
        for dep in targets:
            assert dep in order, f"{name} depends on unknown service {dep}"
            assert order[dep] > order[name], f"cycle risk: {name} -> {dep}"
            edges.append((name, dep))
    return edges


def build_topology(graph: Graph, rng: random.Random, now: int) -> None:
    graph.query(
        "UNWIND $rows AS r CREATE (:Team {uid: 'team:' + r.slug, name: r.name, domain: r.domain, "
        "slack_channel: '#team-' + r.slug})",
        {"rows": [{"slug": s, "name": n, "domain": d} for s, n, d in TEAMS]},
    )
    graph.query(
        "UNWIND $rows AS r MATCH (t:Team {uid: 'team:' + r.team}) "
        "CREATE (p:Person {uid: 'person:' + r.handle, handle: r.handle, name: r.name, role: r.role})"
        "-[:MEMBER_OF]->(t)",
        {"rows": [{"handle": h, "name": n, "role": r, "team": t} for h, n, r, t in PEOPLE]},
    )
    graph.query(
        "UNWIND $rows AS r MATCH (p:Person {uid: 'person:' + r.handle}), (t:Team {uid: 'team:' + r.team}) "
        "CREATE (p)-[:ON_CALL {from: $from, to: $to}]->(t)",
        {
            "rows": [{"team": t, "handle": h} for t, h in sorted(ON_CALL.items())],
            "from": now - DAY_MS,
            "to": now + 30 * DAY_MS,
        },
    )
    graph.query(
        "UNWIND $rows AS r MATCH (t:Team {uid: 'team:' + r.team}) "
        "CREATE (t)-[:OWNS]->(:Service {uid: 'svc:' + r.name, name: r.name, tier: r.tier, layer: r.layer, "
        "language: r.lang, version: r.version, status: 'healthy', revenue_per_min: r.revenue})",
        {
            "rows": [
                {"name": n, "team": t, "tier": tier, "layer": layer, "lang": lang, "revenue": REVENUE_PER_MIN.get(n, 0),
                 "version": f"v{rng.randint(1, 5)}.{rng.randint(0, 9)}.{rng.randint(0, 9)}"}
                for n, t, tier, layer, lang, _deps in SERVICES
            ]
        },
    )
    graph.query(
        "UNWIND $rows AS r MATCH (a:Service {uid: 'svc:' + r.src}), (b:Service {uid: 'svc:' + r.dst}) "
        "CREATE (a)-[:DEPENDS_ON {uid: 'e:' + r.src + '->' + r.dst, protocol: r.protocol, weight: 1, "
        "latency_ms: r.latency, breaker: 'closed'}]->(b)",
        {
            "rows": [
                {"src": a, "dst": b, "protocol": rng.choice(PROTOCOLS), "latency": rng.randint(2, 40)}
                for a, b in dependency_edges(rng)
            ]
        },
    )
    graph.query(
        "UNWIND $rows AS r MATCH (t:Team {uid: 'team:' + r.team}) "
        "CREATE (t)-[:OWNS]->(:Database {uid: 'db:' + r.name, name: r.name, engine: r.engine, "
        "size_gb: r.size, status: 'healthy'})",
        {"rows": [{"name": n, "engine": e, "size": s, "team": t} for n, e, s, t in DATABASES]},
    )
    for rel in ("READS_FROM", "WRITES_TO"):
        # Relationship types can't be parameters, so the type comes from this fixed tuple only.
        graph.query(
            f"UNWIND $rows AS r MATCH (s:Service {{uid: 'svc:' + r.svc}}), (d:Database {{uid: 'db:' + r.db}}) "
            f"CREATE (s)-[:{rel} {{uid: 'e:' + r.svc + '-{rel.lower()}->' + r.db}}]->(d)",
            {"rows": [{"svc": s, "db": d} for s, d, kind in DATA_ACCESS if kind == rel]},
        )


def seed_baseline(graph: Graph | None = None, now: int | None = None) -> dict[str, int]:
    """Wipe the graph and rebuild the healthy baseline. Returns node/edge counts."""
    graph = graph or get_graph()
    now = now or now_ms()
    rng = random.Random(SEED)
    wipe(graph)
    create_indexes(graph)
    build_topology(graph, rng, now)
    build_history(graph, rng, now)
    build_memory(graph, now)
    res = graph.query("MATCH (n) WITH count(n) AS nodes MATCH ()-[r]->() RETURN nodes, count(r) AS edges")
    nodes, edges = res.result_set[0]
    return {"nodes": nodes, "edges": edges}
