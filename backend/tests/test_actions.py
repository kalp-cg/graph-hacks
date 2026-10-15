from sentinel.db import rows
from sentinel.seed.scenarios import inject_scenario
from sentinel.tools.actions import execute_action, propose_action, reject_action
from sentinel.tools.incidents import conclude_incident, open_incident
from sentinel.tools.memory import recall_similar


def unhealthy(g):
    return set(rows(g, "MATCH (s:Service) WHERE s.status <> 'healthy' RETURN collect(s.name) AS x")[0]["x"])


def firing(g):
    return rows(g, "MATCH (a:Alert {status: 'firing'}) RETURN count(a) AS n")[0]["n"]


def test_propose_changes_nothing_until_approved(graph):
    inject_scenario("db-pool-exhaustion", graph, fresh=True)
    before = unhealthy(graph)
    out = propose_action("rollback", "inventory-db-proxy", "pool size cut", graph=graph)
    assert out["result"]["action"]["status"] == "pending"
    assert out["result"]["action"]["target_uid"] == "dep:inventory-db-proxy:v4.2.0"
    assert unhealthy(graph) == before


def test_rollback_recovers_everything_and_resolves_incident(graph):
    inject_scenario("db-pool-exhaustion", graph, fresh=True)
    inc = open_incident("run-a", graph)
    act = propose_action("rollback", "inventory-db-proxy", "pool size cut", run_id="run-a", graph=graph)
    conclude_incident("run-a", "inventory-db-proxy", "v4.2.0 cut the pool", 7, graph=graph)
    out = execute_action(act["result"]["action"]["uid"], graph=graph)
    assert unhealthy(graph) == set()
    assert firing(graph) == 0
    assert out["resolved_incidents"] == [inc["id"]]
    dep = rows(graph, "MATCH (d:Deployment {uid: 'dep:inventory-db-proxy:v4.2.0'}) RETURN d.status AS s")[0]["s"]
    assert dep == "rolled_back"


def test_rollback_refused_without_recent_deploy(graph):
    inject_scenario("cache-stampede", graph, fresh=True)
    assert propose_action("rollback", "redis-cache", "x", graph=graph)["error"] == "no_recent_deploy"


def test_breaker_isolates_then_scale_up_heals(graph):
    inject_scenario("cache-stampede", graph, fresh=True)
    b = propose_action("open_breaker", "redis-cache", "isolate", graph=graph)["result"]["action"]["uid"]
    out = execute_action(b, graph=graph)
    assert set(out["recovered"]) == {"svc:search-service", "svc:recommendations"}
    assert unhealthy(graph) == {"redis-cache"}
    s = propose_action("scale_up", "redis-cache", "capacity", graph=graph)["result"]["action"]["uid"]
    execute_action(s, graph=graph)
    assert unhealthy(graph) == set()
    assert rows(graph, "MATCH ()-[r:DEPENDS_ON {breaker: 'open'}]->() RETURN count(r) AS n")[0]["n"] == 0


def test_symptom_recovers_only_after_root(graph):
    inject_scenario("bad-config-push", graph, fresh=True)
    page = propose_action("page_oncall", "feature-flags", "flag push", graph=graph)["result"]["action"]["uid"]
    out = execute_action(page, graph=graph)
    assert out["recovered"] == [] and "Priya" in out["outcome"]
    fix = propose_action("rollback", "feature-flags", "flag push", graph=graph)["result"]["action"]["uid"]
    execute_action(fix, graph=graph)
    assert unhealthy(graph) == set()


def test_reject_and_double_execute(graph):
    inject_scenario("db-pool-exhaustion", graph, fresh=True)
    uid = propose_action("scale_up", "inventory-db-proxy", "x", graph=graph)["result"]["action"]["uid"]
    assert reject_action(uid, graph=graph)["status"] == "rejected"
    assert execute_action(uid, graph=graph)["error"] == "not_pending"
    assert propose_action("reboot", "inventory-db-proxy", "x", graph=graph)["error"] == "bad_kind"


def test_learned_incident_is_recalled_after_soft_reset(graph):
    inject_scenario("kafka-rebalance-storm", graph, fresh=True)
    services = ["inventory-service", "notifications", "payments-api"]
    assert all(i["root_cause_service"] != "kafka-bus" for i in recall_similar(services, graph)["result"]["incidents"])
    inc = open_incident("run-k", graph)
    act = propose_action("rollback", "kafka-bus", "partition change", run_id="run-k", graph=graph)
    conclude_incident("run-k", "kafka-bus", "rebalance storm after v4.1.0", 9, graph=graph)
    execute_action(act["result"]["action"]["uid"], graph=graph)

    inject_scenario("kafka-rebalance-storm", graph)  # soft reset keeps memory
    top = recall_similar(services, graph)["result"]["incidents"][0]
    assert top["id"] == inc["id"]
    assert top["root_cause_service"] == "kafka-bus"
    assert top["fixes"] == ["rollback"] and top["steps_taken"] == 9
