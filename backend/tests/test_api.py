import os

from fastapi.testclient import TestClient

from conftest import TEST_GRAPH


def test_api_flow(graph, monkeypatch):
    os.environ["GRAPH_NAME"] = TEST_GRAPH
    monkeypatch.setattr("sentinel.api.main.get_graph", lambda name=None: graph)
    monkeypatch.setattr("sentinel.api.graph_view.get_graph", lambda name=None: graph)
    monkeypatch.setattr("sentinel.seed.scenarios.get_graph", lambda name=None: graph)
    monkeypatch.setattr("sentinel.tools.common.get_graph", lambda name=None: graph)
    from sentinel.api.main import app
    from sentinel.seed.scenarios import inject_scenario

    inject_scenario("db-pool-exhaustion", graph, fresh=True)
    with TestClient(app) as c:
        assert c.get("/api/health").json()["falkordb"]["ok"]
        assert {s["name"] for s in c.get("/api/scenarios").json()} >= {"db-pool-exhaustion", "cache-stampede"}
        assert c.post("/api/scenarios/nope").status_code == 404
        info = c.post("/api/scenarios/bad-config-push").json()
        assert info["alerting_services"] == ["auth-service", "user-profile"]

        g = c.get("/api/graph").json()
        ids = {n["id"] for n in g["nodes"]}
        assert "svc:feature-flags" in ids and "dep:feature-flags:v4.0.3" in ids
        assert all(link["source"] in ids and link["target"] in ids for link in g["links"])
        assert any(n.get("pagerank") for n in g["nodes"])

        with c.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            assert c.post("/api/runs", json={"provider": "autopilot"}).status_code == 200
            events = []
            while not events or events[-1]["type"] not in ("final", "error"):
                events.append(ws.receive_json())
            final = events[-1]
            assert final["type"] == "final" and final["root_cause"] == "feature-flags"

        rollback = next(a for a in final["actions"] if a["kind"] == "rollback")
        out = c.post(f"/api/actions/{rollback['uid']}/approve").json()
        assert set(out["recovered"]) == {"svc:auth-service", "svc:user-profile"}
        assert c.post(f"/api/actions/{rollback['uid']}/approve").status_code == 409
        page = next(a for a in final["actions"] if a["kind"] == "page_oncall")
        assert c.post(f"/api/actions/{page['uid']}/reject").json()["status"] == "rejected"
        assert c.get("/api/incidents").json()[0]["status"] == "resolved"
