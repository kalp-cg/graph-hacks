"""FastAPI app: REST for control, one WebSocket that streams every event to every viewer.

Run: uvicorn sentinel.api.main:app --port 8000
"""
import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..agent.llm import make_llm
from ..agent.loop import investigate
from ..agent.mcp_client import GraphToolbox
from ..config import settings
from ..db import get_graph, rows
from ..seed.scenarios import SCENARIOS, inject_scenario, reset
from ..tools import actions
from .graph_view import graph_snapshot, incidents_view

log = logging.getLogger("sentinel.api")


class Hub:
    """Fan-out of events to every connected WebSocket, plus the current run's history for late joiners."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.history: list[dict] = []

    async def broadcast(self, event: dict) -> None:
        if event.get("run_id") and event["type"] != "graph_update":
            if event["type"] == "run_started":
                self.history = []
            self.history.append(event)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001 - a closed socket must not break the others
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


class RunManager:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.toolbox: GraphToolbox | None = None
        self.task: asyncio.Task | None = None
        self.run_id: str | None = None

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    async def start(self, question: str, provider: str | None) -> str:
        if self.busy:
            raise HTTPException(409, "an investigation is already running")
        try:
            llm = make_llm(provider)
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc
        if self.toolbox is None:
            self.toolbox = await GraphToolbox().start()
        self.run_id = uuid.uuid4().hex[:12]
        self.task = asyncio.create_task(self._run(question, llm, self.run_id))
        return self.run_id

    async def _run(self, question: str, llm: Any, run_id: str) -> None:
        try:
            assert self.toolbox is not None
            await investigate(question, self.hub.broadcast, self.toolbox, llm, run_id=run_id)
        except Exception as exc:  # noqa: BLE001 - report every failure to the UI as the single terminal event
            log.exception("run failed")
            await self.hub.broadcast({"type": "error", "run_id": run_id, "message": str(exc)[:500]})
            # A broken MCP session is restarted on the next run.
            if self.toolbox:
                await self.toolbox.close()
            self.toolbox = None
        finally:
            await self.hub.broadcast({"type": "graph_update", "reason": "run_finished"})


hub = Hub()
runs = RunManager(hub)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        runs.toolbox = await GraphToolbox().start()
    except Exception:  # noqa: BLE001 - the API still serves; the toolbox is retried on first run
        log.exception("could not start the MCP toolbox")
    yield
    if runs.toolbox:
        await runs.toolbox.close()


app = FastAPI(title="SentinelGraph", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins) + ["*"], allow_methods=["*"],
                   allow_headers=["*"])


class RunRequest(BaseModel):
    question: str = "Alerts are firing. Investigate, find the root cause and fix it."
    provider: str | None = None


@app.get("/api/health")
async def health() -> dict:
    try:
        n = await asyncio.to_thread(lambda: rows(get_graph(), "MATCH (s:Service) RETURN count(s) AS n")[0]["n"])
        db = {"ok": True, "services": n}
    except Exception as exc:  # noqa: BLE001
        db = {"ok": False, "error": str(exc)[:200]}
    try:
        llm = make_llm().name
    except RuntimeError as exc:
        llm = f"unavailable: {exc}"
    return {"falkordb": db, "graph": settings.graph_name, "llm": llm,
            "tools": runs.toolbox.names if runs.toolbox else [], "running": runs.busy}


@app.get("/api/graph")
async def graph() -> dict:
    return await asyncio.to_thread(graph_snapshot)


@app.get("/api/incidents")
async def incidents() -> list[dict]:
    return await asyncio.to_thread(incidents_view)


@app.get("/api/scenarios")
async def scenarios() -> list[dict]:
    return [{"name": k, "title": v["title"], "alerts": [a[0] for a in v["alerts"]]} for k, v in SCENARIOS.items()]


@app.post("/api/scenarios/{name}")
async def start_scenario(name: str) -> dict:
    if name not in SCENARIOS:
        raise HTTPException(404, f"unknown scenario {name}")
    if runs.busy:
        raise HTTPException(409, "wait for the current investigation to finish")
    info = await asyncio.to_thread(inject_scenario, name)
    hub.history = []
    await hub.broadcast({"type": "scenario_started", **info})
    await hub.broadcast({"type": "graph_update", "reason": "scenario"})
    return info


@app.post("/api/reset")
async def reset_graph(keep_memory: bool = True) -> dict:
    if runs.busy:
        raise HTTPException(409, "wait for the current investigation to finish")
    await asyncio.to_thread(reset, None, keep_memory)
    hub.history = []
    await hub.broadcast({"type": "graph_update", "reason": "reset"})
    return {"ok": True, "keep_memory": keep_memory}


@app.post("/api/runs")
async def start_run(req: RunRequest) -> dict:
    run_id = await runs.start(req.question, req.provider)
    return {"run_id": run_id}


@app.get("/api/actions")
async def list_actions(status: str | None = None) -> list[dict]:
    return await asyncio.to_thread(actions.list_actions, status)


@app.post("/api/actions/{uid}/approve")
async def approve(uid: str) -> dict:
    out = await asyncio.to_thread(actions.execute_action, uid, "human")
    if "error" in out:
        raise HTTPException(409 if out["error"] == "not_pending" else 404, out["message"])
    await hub.broadcast({"type": "action_executed", **out})
    await hub.broadcast({"type": "graph_update", "reason": "action"})
    return out


@app.post("/api/actions/{uid}/reject")
async def reject(uid: str) -> dict:
    out = await asyncio.to_thread(actions.reject_action, uid, "human")
    if not out:
        raise HTTPException(409, "action is not pending")
    await hub.broadcast({"type": "action_rejected", "action": out})
    return out


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()
    hub.clients.add(socket)
    await socket.send_json({"type": "hello", "history": hub.history, "running": runs.busy})
    try:
        while True:
            await socket.receive_text()  # keepalive pings from the client
    except WebSocketDisconnect:
        hub.clients.discard(socket)
