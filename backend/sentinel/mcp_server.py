"""SentinelGraph MCP server: FalkorDB graph tools for incident investigation.

Run over stdio:  python -m sentinel.mcp_server
Works with any MCP client (our agent, Claude Desktop, Cursor, MCP Inspector).
"""
from mcp.server.mcpserver import MCPServer

from .tools import algorithms, memory, read, rootcause

server = MCPServer(
    name="sentinelgraph",
    instructions=(
        "Tools over a FalkorDB graph of services, dependencies, deployments, people and past incidents. "
        "Investigate in this order: get_active_alerts -> find_common_cause on the alerting services -> "
        "recent_changes on the top candidate -> recall_similar -> get_service_context for the owner/on-call. "
        "Use blast_radius / critical_services / chokepoints to explain impact. Every result includes the Cypher "
        "it ran and the node/edge uids it touched; cite uids as evidence."
    ),
)


@server.tool()
def get_active_alerts() -> dict:
    """List every alert that is currently firing, oldest first, with the service it fired on."""
    return read.get_active_alerts()


@server.tool()
def get_service_context(service: str) -> dict:
    """Owner team, current on-call engineer, tier/status, databases and the last 3 deployments of a service."""
    return read.get_service_context(service)


@server.tool()
def trace_dependencies(service: str, depth: int = 3) -> dict:
    """Everything a service depends on (downstream), nearest first. depth is clamped to 1..6."""
    return read.trace_dependencies(service, depth)


@server.tool()
def blast_radius(service: str, depth: int = 6) -> dict:
    """Every upstream service that breaks if this service fails, with a count per tier. depth is clamped to 1..6."""
    return read.blast_radius(service, depth)


@server.tool()
def find_common_cause(services: list[str]) -> dict:
    """Given the alerting services, find the dependency they ALL share, deepest unhealthy one first."""
    return rootcause.find_common_cause(services)


@server.tool()
def recent_changes(services: list[str], minutes: int = 60) -> dict:
    """Deployments to these services in the last N minutes, with commit message, author and team."""
    return rootcause.recent_changes(services, minutes)


@server.tool()
def critical_services(top: int = 10, service: str | None = None) -> dict:
    """PageRank over dependencies: the most depended-on services. Pass `service` to get its rank."""
    return algorithms.critical_services(top, service)


@server.tool()
def chokepoints(top: int = 10, service: str | None = None) -> dict:
    """Betweenness centrality: services on the most dependency paths (single points of failure)."""
    return algorithms.chokepoints(top, service)


@server.tool()
def failure_path(from_service: str, to_service: str) -> dict:
    """Shortest dependency path from a caller to a failing service: how the failure propagates."""
    return algorithms.failure_path(from_service, to_service)


@server.tool()
def recall_similar(services: list[str]) -> dict:
    """Past resolved incidents near these services, with root cause, fixes that worked and the runbook."""
    return memory.recall_similar(services)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
