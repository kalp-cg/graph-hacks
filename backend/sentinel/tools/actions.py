"""Actions: the agent can only *propose*; a human approves; the backend executes.

propose_action  -> (:Action {status: 'pending'})-[:TARGETS]->(Service | Deployment)   [MCP tool]
execute_action  -> graph writes + recovery + incident settlement                         [backend only]
"""
import json
import logging
import os
import urllib.request
import uuid

from falkordb import Graph

from ..db import rows
from .common import check_services, graph_or_default, now_ms, result
from .health import recompute_health
from .incidents import RECENT_DEPLOY_MS, settle_incidents

log = logging.getLogger(__name__)

KINDS = {
    "rollback": "Roll back the most recent deployment of the service",
    "open_breaker": "Open the circuit breakers on every call into the service so callers fall back",
    "scale_up": "Add capacity to the service (and close its breakers again)",
    "page_oncall": "Page the on-call engineer of the team that owns the service",
}
RISKS = {"low", "medium", "high"}


def _action_view(a: dict) -> dict:
    keys = ("uid", "kind", "status", "target", "target_uid", "reason", "risk", "created_at", "executed_at",
            "approved_by", "outcome", "run_id")
    return {k: a.get(k) for k in keys}


def get_action(uid: str, graph: Graph | None = None) -> dict | None:
    g = graph_or_default(graph)
    found = rows(g, "MATCH (a:Action {uid: $uid}) RETURN a", {"uid": uid})
    return _action_view(found[0]["a"].properties) if found else None


def list_actions(status: str | None = None, graph: Graph | None = None) -> list[dict]:
    g = graph_or_default(graph)
    found = rows(g, "MATCH (a:Action) WHERE $status IS NULL OR a.status = $status "
                    "RETURN a ORDER BY a.created_at DESC LIMIT 50", {"status": status})
    return [_action_view(r["a"].properties) for r in found]


def propose_action(kind: str, target: str, reason: str, risk: str = "medium", run_id: str | None = None,
                   graph: Graph | None = None) -> dict:
    """Create a pending Action for a human to approve. Changes nothing else in the graph."""
    g = graph_or_default(graph)
    if kind not in KINDS:
        return {"error": "bad_kind", "message": f"kind must be one of {sorted(KINDS)}"}
    if err := check_services(g, [target]):
        return err
    risk = risk if risk in RISKS else "medium"

    target_uid = f"svc:{target}"
    note = None
    if kind == "rollback":
        dep = rows(
            g,
            "MATCH (d:Deployment {status: 'live'})-[:DEPLOYED_TO]->(:Service {name: $name}) "
            "RETURN d.uid AS uid, d.version AS version, d.at AS at ORDER BY d.at DESC LIMIT 1",
            {"name": target},
        )
        if not dep or dep[0]["at"] < now_ms() - RECENT_DEPLOY_MS:
            # Guard against blaming a change that didn't happen: nothing recent to roll back.
            return {"error": "no_recent_deploy",
                    "message": f"{target} has no deployment in the last 2 hours; a rollback would not help. "
                               "Consider open_breaker or scale_up instead."}
        target_uid = dep[0]["uid"]
        note = f"roll back {dep[0]['version']}"
    elif kind == "page_oncall":
        oncall = rows(
            g,
            "MATCH (:Service {name: $name})<-[:OWNS]-(t:Team)<-[oc:ON_CALL]-(p:Person) "
            "WHERE oc.from <= $now AND oc.to > $now RETURN p.name AS name LIMIT 1",
            {"name": target, "now": now_ms()},
        )
        note = f"page {oncall[0]['name']}" if oncall else "page the owning team"

    existing = rows(
        g,
        "MATCH (a:Action {kind: $kind, target: $target, status: 'pending'}) RETURN a",
        {"kind": kind, "target": target},
    )
    if existing:
        a = _action_view(existing[0]["a"].properties)
        return result({"action": a, "note": "already proposed"}, "MATCH (a:Action {status: 'pending'}) ...",
                      [a["uid"], a["target_uid"]])

    uid = f"act:{uuid.uuid4().hex[:10]}"
    cypher = (
        "MATCH (t {uid: $target_uid}) "
        "CREATE (a:Action {uid: $uid, kind: $kind, status: 'pending', target: $target, target_uid: $target_uid, "
        "reason: $reason, risk: $risk, created_at: $now, run_id: $run, summary: $note})-[:TARGETS]->(t) "
        "WITH a OPTIONAL MATCH (i:Incident {run_id: $run}) "
        "FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END | CREATE (i)-[:RESOLVED_BY]->(a)) "
        "RETURN a"
    )
    created = rows(g, cypher, {"uid": uid, "kind": kind, "target": target, "target_uid": target_uid,
                               "reason": str(reason)[:500], "risk": risk, "now": now_ms(), "run": run_id or "",
                               "note": note})
    a = _action_view(created[0]["a"].properties)
    return result({"action": a, "description": KINDS[kind], "note": note,
                   "next": "A human must approve this action before anything changes."},
                  cypher, [uid, target_uid])


def reject_action(uid: str, by: str = "human", graph: Graph | None = None) -> dict | None:
    g = graph_or_default(graph)
    found = rows(g, "MATCH (a:Action {uid: $uid, status: 'pending'}) SET a.status = 'rejected', "
                    "a.approved_by = $by, a.executed_at = $now RETURN a", {"uid": uid, "by": by, "now": now_ms()})
    return _action_view(found[0]["a"].properties) if found else None


def _page(g: Graph, a: dict) -> tuple[list[str], str]:
    oncall = rows(
        g,
        "MATCH (:Service {name: $name})<-[:OWNS]-(t:Team)<-[oc:ON_CALL]-(p:Person) "
        "WHERE oc.from <= $now AND oc.to > $now RETURN p.uid AS uid, p.name AS name, t.slack_channel AS channel",
        {"name": a["target"], "now": now_ms()},
    )
    if not oncall:
        return [], "no on-call engineer found"
    p = oncall[0]
    message = f"[SentinelGraph] {a['target']}: {a.get('reason') or 'incident in progress'}"
    page_uid = f"page:{uuid.uuid4().hex[:10]}"
    g.query(
        "MATCH (p:Person {uid: $person}) CREATE (pg:Page {uid: $uid, at: $now, message: $msg, channel: $channel})"
        "-[:NOTIFIED]->(p) WITH pg OPTIONAL MATCH (i:Incident {run_id: $run}) "
        "FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END | CREATE (i)-[:PAGED]->(pg))",
        {"person": p["uid"], "uid": page_uid, "now": now_ms(), "msg": message, "channel": p["channel"],
         "run": a.get("run_id") or ""},
    )
    delivered = _send_webhook(f"🚨 Paging {p['name']} ({p['channel']}): {message}")
    return [page_uid, p["uid"]], f"paged {p['name']} via {p['channel']}" + (" + webhook" if delivered else "")


def _send_webhook(text: str) -> bool:
    """Optional real page: POST to a Discord/Slack-compatible webhook if PAGER_WEBHOOK_URL is set."""
    url = os.getenv("PAGER_WEBHOOK_URL")
    if not url:
        return False
    body = json.dumps({"content": text, "text": text}).encode()
    try:
        req = urllib.request.Request(url, body, {"Content-Type": "application/json", "User-Agent": "SentinelGraph"})
        urllib.request.urlopen(req, timeout=5).close()
        return True
    except Exception as exc:  # noqa: BLE001 - paging must never break the action
        log.warning("webhook failed: %s", exc)
        return False


def execute_action(uid: str, approved_by: str = "human", graph: Graph | None = None) -> dict:
    """Run an approved action against the graph, then let recovery and incident settlement follow."""
    g = graph_or_default(graph)
    a = get_action(uid, g)
    if not a:
        return {"error": "not_found", "message": f"no action {uid}"}
    if a["status"] != "pending":
        return {"error": "not_pending", "message": f"action {uid} is {a['status']}"}

    changed: list[str] = []
    edges: list[str] = []
    kind, target = a["kind"], a["target"]
    if kind == "rollback":
        g.query("MATCH (d:Deployment {uid: $dep}) SET d.status = 'rolled_back'", {"dep": a["target_uid"]})
        g.query("MATCH (s:Service {name: $name}) SET s.status = 'healthy'", {"name": target})
        changed += [a["target_uid"], f"svc:{target}"]
        outcome = f"rolled back {a['target_uid'].split(':')[-1]} on {target}"
    elif kind == "open_breaker":
        opened = rows(g, "MATCH (:Service)-[r:DEPENDS_ON]->(:Service {name: $name}) SET r.breaker = 'open' "
                         "RETURN r.uid AS uid", {"name": target})
        edges += [r["uid"] for r in opened]
        outcome = f"opened {len(opened)} circuit breakers into {target}"
    elif kind == "scale_up":
        g.query("MATCH (s:Service {name: $name}) SET s.status = 'healthy'", {"name": target})
        closed = rows(g, "MATCH (:Service)-[r:DEPENDS_ON {breaker: 'open'}]->(:Service {name: $name}) "
                         "SET r.breaker = 'closed' RETURN r.uid AS uid", {"name": target})
        edges += [r["uid"] for r in closed]
        changed.append(f"svc:{target}")
        outcome = f"scaled up {target}" + (f" and closed {len(closed)} breakers" if closed else "")
    else:  # page_oncall
        uids, outcome = _page(g, a)
        changed += uids

    health = recompute_health(g)
    g.query("MATCH (a:Action {uid: $uid}) SET a.status = 'executed', a.approved_by = $by, a.executed_at = $now, "
            "a.outcome = $outcome", {"uid": uid, "by": approved_by, "now": now_ms(), "outcome": outcome})
    resolved_incidents = settle_incidents(g)
    return {
        "action": get_action(uid, g),
        "outcome": outcome,
        "node_uids": list(dict.fromkeys(changed + health["recovered"] + health["resolved_alerts"])),
        "edge_uids": edges,
        "recovered": health["recovered"],
        "resolved_alerts": health["resolved_alerts"],
        "resolved_incidents": resolved_incidents,
    }
