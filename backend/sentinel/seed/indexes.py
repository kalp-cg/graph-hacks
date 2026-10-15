"""Indexes on the lookup keys the tools filter by."""
from falkordb import Graph

INDEXES = [
    ("Service", "uid"),
    ("Service", "name"),
    ("Database", "uid"),
    ("Team", "uid"),
    ("Person", "uid"),
    ("Deployment", "uid"),
    ("Deployment", "at"),
    ("Alert", "status"),
    ("Incident", "id"),
    ("Action", "uid"),
]


def create_indexes(graph: Graph) -> int:
    """Create every index; an index that already exists raises, so skip it. Returns how many were created."""
    created = 0
    for label, prop in INDEXES:
        try:
            graph.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
            created += 1
        except Exception as exc:  # noqa: BLE001 - FalkorDB raises ResponseError for duplicates
            if "already indexed" not in str(exc).lower():
                raise
    return created
