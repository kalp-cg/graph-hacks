"""FalkorDB connection helpers."""
from functools import lru_cache
from typing import Any

from falkordb import FalkorDB, Graph

from .config import settings


@lru_cache(maxsize=1)
def get_db() -> FalkorDB:
    return FalkorDB(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        username=settings.falkordb_username,
        password=settings.falkordb_password,
    )


def get_graph(name: str | None = None) -> Graph:
    return get_db().select_graph(name or settings.graph_name)


def rows(graph: Graph, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a query and return each row as a dict keyed by the RETURN aliases."""
    res = graph.query(cypher, params or {})
    cols = [h[1] if isinstance(h, (list, tuple)) else h for h in res.header]
    return [dict(zip(cols, r)) for r in res.result_set]
