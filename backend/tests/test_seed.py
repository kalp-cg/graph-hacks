import pytest

from sentinel.db import rows
from sentinel.seed.generator import seed_baseline
from sentinel.seed.scenarios import SCENARIOS, inject_scenario


def test_baseline_is_deterministic(graph):
    first = seed_baseline(graph)
    uids_a = rows(graph, "MATCH (n) RETURN n.uid AS uid ORDER BY uid")
    second = seed_baseline(graph)
    uids_b = rows(graph, "MATCH (n) RETURN n.uid AS uid ORDER BY uid")
    assert first == second
    assert uids_a == uids_b


def test_baseline_shape(graph):
    seed_baseline(graph)
    counts = {r["label"]: r["n"] for r in rows(graph, "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n")}
    assert counts["Service"] >= 35
    assert counts["Team"] == 8
    assert counts["Incident"] == 3
    # Every node has a uid, and uids are unique.
    missing = rows(graph, "MATCH (n) WHERE n.uid IS NULL RETURN count(n) AS n")[0]["n"]
    dupes = rows(graph, "MATCH (n) WITH n.uid AS uid, count(*) AS c WHERE c > 1 RETURN count(uid) AS n")[0]["n"]
    assert missing == 0 and dupes == 0


def test_dependencies_are_a_dag(graph):
    seed_baseline(graph)
    cycles = rows(graph, "MATCH (a:Service)-[:DEPENDS_ON*1..10]->(a) RETURN count(a) AS n")[0]["n"]
    assert cycles == 0


def test_baseline_is_healthy_and_quiet(graph):
    seed_baseline(graph)
    assert rows(graph, "MATCH (s:Service) WHERE s.status <> 'healthy' RETURN count(s) AS n")[0]["n"] == 0
    assert rows(graph, "MATCH (a:Alert {status: 'firing'}) RETURN count(a) AS n")[0]["n"] == 0


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_fires_alerts(graph, name):
    info = inject_scenario(name, graph)
    firing = rows(graph, "MATCH (a:Alert {status: 'firing'})-[:FIRED_ON]->(s) RETURN s.name AS svc")
    assert sorted(r["svc"] for r in firing) == sorted(info["alerting_services"])


def test_unknown_scenario(graph):
    with pytest.raises(ValueError):
        inject_scenario("does-not-exist", graph)
