"""Shared helpers: the explainable result shape, name lookup, argument clamping."""
import difflib
import time
from typing import Any

from falkordb import Graph

from ..db import get_graph, rows

MAX_ROWS = 25


def now_ms() -> int:
    return int(time.time() * 1000)


def clamp(value: Any, low: int, high: int, default: int) -> int:
    """Coerce an LLM-provided number into [low, high]. Variable-length bounds are built from this only."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(low, min(high, n))


def result(value: Any, cypher: str, node_uids: list[str] | None = None,
           edge_uids: list[str] | None = None, **extra: Any) -> dict:
    """Every tool returns the query it ran and the graph elements it touched, so the UI can show its work."""
    out = {
        "result": value,
        "cypher": " ".join(cypher.split()),
        "node_uids": list(dict.fromkeys(node_uids or [])),
        "edge_uids": list(dict.fromkeys(edge_uids or [])),
    }
    out.update(extra)
    return out


def capped(items: list, limit: int = MAX_ROWS) -> tuple[list, bool]:
    return items[:limit], len(items) > limit


def service_names(graph: Graph) -> list[str]:
    return [r["name"] for r in rows(graph, "MATCH (s:Service) RETURN s.name AS name")]


def not_found(graph: Graph, name: str) -> dict:
    return {
        "error": "not_found",
        "message": f"No service named {name!r}",
        "did_you_mean": difflib.get_close_matches(str(name), service_names(graph), n=3, cutoff=0.4),
    }


def check_services(graph: Graph, names: list[str]) -> dict | None:
    """Return a not_found error for the first unknown service name, or None if all exist."""
    known = set(service_names(graph))
    for name in names:
        if name not in known:
            return not_found(graph, name)
    return None


def graph_or_default(graph: Graph | None) -> Graph:
    return graph if graph is not None else get_graph()
