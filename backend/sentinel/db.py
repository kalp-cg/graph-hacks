"""FalkorDB connection helpers."""
import socket
from functools import lru_cache
from typing import Any

from falkordb import FalkorDB, Graph

from .config import settings


@lru_cache(maxsize=1)
def get_db() -> FalkorDB:
    host = settings.falkordb_host
    if settings.falkordb_ipv4 and not settings.falkordb_ssl:
        host = socket.getaddrinfo(host, settings.falkordb_port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
    return FalkorDB(
        host=host,
        port=settings.falkordb_port,
        username=settings.falkordb_username,
        password=settings.falkordb_password,
        ssl=settings.falkordb_ssl,
        socket_connect_timeout=10,
    )


def get_graph(name: str | None = None) -> Graph:
    return get_db().select_graph(name or settings.graph_name)


def rows(graph: Graph, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a query and return each row as a dict keyed by the RETURN aliases."""
    res = graph.query(cypher, params or {})
    cols = [h[1] if isinstance(h, (list, tuple)) else h for h in res.header]
    return [dict(zip(cols, r)) for r in res.result_set]
