"""Change history: Deployment -> Commit -> Person, all older than 24 h in the baseline."""
import hashlib
import random

from falkordb import Graph

from .catalog import PEOPLE, SERVICES

DAY_MS = 24 * 60 * 60 * 1000
HOUR_MS = 60 * 60 * 1000

COMMIT_MESSAGES = [
    "Bump dependencies",
    "Add request tracing to handlers",
    "Refactor retry policy",
    "Tune connection timeouts",
    "Fix null check in serializer",
    "Add metrics for cache hit ratio",
    "Improve error messages",
    "Upgrade base image",
    "Remove dead feature flag",
    "Batch writes to reduce round trips",
]


def sha_for(*parts: str) -> str:
    return hashlib.sha1(":".join(parts).encode()).hexdigest()[:10]


def members_by_team() -> dict[str, list[str]]:
    teams: dict[str, list[str]] = {}
    for handle, _name, _role, team in PEOPLE:
        teams.setdefault(team, []).append(handle)
    return teams


def deployment_rows(rng: random.Random, now: int) -> list[dict]:
    """2-3 historical deployments per service, each with one commit by a member of the owning team."""
    members = members_by_team()
    rows = []
    for name, team, *_ in SERVICES:
        count = rng.randint(2, 3)
        ages_days = sorted(rng.sample(range(2, 30), count), reverse=True)
        for i, age in enumerate(ages_days):
            version = f"v{i + 1}.{rng.randint(0, 9)}.0"
            msg = rng.choice(COMMIT_MESSAGES)
            rows.append({
                "svc": name,
                "version": version,
                "at": now - age * DAY_MS - rng.randint(0, 23) * HOUR_MS,
                "summary": msg,
                "sha": sha_for(name, version),
                "message": msg,
                "files": rng.randint(1, 12),
                "author": rng.choice(members[team]),
            })
    return rows


def create_deployments(graph: Graph, rows: list[dict], status: str = "live") -> None:
    graph.query(
        "UNWIND $rows AS r MATCH (s:Service {uid: 'svc:' + r.svc}), (p:Person {uid: 'person:' + r.author}) "
        "CREATE (d:Deployment {uid: 'dep:' + r.svc + ':' + r.version, id: r.svc + '@' + r.version, "
        "version: r.version, at: r.at, status: $status, change_summary: r.summary})-[:DEPLOYED_TO]->(s), "
        "(d)-[:CONTAINS]->(c:Commit {uid: 'commit:' + r.sha, sha: r.sha, message: r.message, "
        "files_changed: r.files})-[:AUTHORED_BY]->(p)",
        {"rows": rows, "status": status},
    )


def build_history(graph: Graph, rng: random.Random, now: int) -> None:
    create_deployments(graph, deployment_rows(rng, now))
