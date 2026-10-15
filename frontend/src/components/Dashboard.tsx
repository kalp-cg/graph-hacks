"use client";

import dynamic from "next/dynamic";
import { Loader2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, api } from "@/lib/api";
import { C, STATUS_COLOR, TYPE_COLOR, type Highlight } from "@/lib/graphStyle";
import type { Action, GLink, GNode, GraphData, Health, Incident, RunEvent, Scenario, Step } from "@/lib/types";
import { useRunSocket } from "@/lib/useRunSocket";
import AgentTrail from "./AgentTrail";
import ControlPanel from "./ControlPanel";
import TopBar, { type ApiState } from "./TopBar";

const GraphCanvas = dynamic(() => import("./GraphCanvas"), { ssr: false });

const PROVIDERS = [
  { id: "", label: "Server default model" },
  { id: "ollama", label: "Ollama (local model)" },
  { id: "gemini", label: "Gemini" },
  { id: "openai", label: "OpenAI-compatible API" },
  { id: "autopilot", label: "Autopilot (deterministic, no LLM)" },
];

type Data = { nodes: GNode[]; links: GLink[] };
type Break = (mode: "down" | "degraded", deploy: boolean) => void;

const BREAKS: { mode: "down" | "degraded"; deploy: boolean; label: string }[] = [
  { mode: "down", deploy: true, label: "Ship a bad deploy" },
  { mode: "down", deploy: false, label: "Crash it" },
  { mode: "degraded", deploy: false, label: "Degrade it" },
];

/** Merge a fresh snapshot into the live objects so the layout keeps its positions. */
function merge(prev: Data, next: GraphData): { data: Data; recovered: string[] } {
  const old = new Map(prev.nodes.map((n) => [n.id, n]));
  const recovered: string[] = [];
  let changed = prev.nodes.length !== next.nodes.length;
  const nodes = next.nodes.map((n) => {
    const o = old.get(n.id);
    if (!o) {
      changed = true;
      return n;
    }
    if (o.status && o.status !== "healthy" && o.status !== "resolved" && n.status === "healthy") recovered.push(n.id);
    Object.assign(o, n);
    return o;
  });
  const oldLinks = new Map(prev.links.map((l) => [l.id, l]));
  if (prev.links.length !== next.links.length || next.links.some((l) => !oldLinks.has(l.id))) changed = true;
  if (!changed) {
    for (const l of next.links) Object.assign(oldLinks.get(l.id)!, { breaker: l.breaker });
    return { data: prev, recovered };
  }
  const links = next.links.map((l) => {
    const o = oldLinks.get(l.id);
    return o ? Object.assign(o, { breaker: l.breaker }) : l;
  });
  return { data: { nodes, links }, recovered };
}

/** Apply an approval's known effects to the live objects (same in-place style as `merge`). */
function patchLive(data: Data, healed: Set<string>, resolved: Set<string>,
                   breaker: { target: string; state: string } | null) {
  for (const n of data.nodes) {
    if (healed.has(n.id) && n.status !== "healthy") n.status = "healthy";
    if (resolved.has(n.id)) n.status = "resolved";
  }
  if (!breaker) return;
  for (const l of data.links) {
    if (l.type === "DEPENDS_ON" && idOf(l.target) === breaker.target) l.breaker = breaker.state;
  }
}

function idOf(end: string | GNode): string {
  return typeof end === "string" ? end : end.id;
}

export default function Dashboard() {
  const [data, setData] = useState<Data>({ nodes: [], links: [] });
  const dataRef = useRef(data);
  const [version, setVersion] = useState(0);
  const [apiState, setApiState] = useState<ApiState>("connecting");
  const [health, setHealth] = useState<Health | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [actions, setActions] = useState<Action[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [provider, setProvider] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const [flashes, setFlashes] = useState<Map<string, number>>(new Map());
  const [focus, setFocus] = useState<{ ids: string[]; key: number } | null>(null);
  const [activeStep, setActiveStep] = useState<Step | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ node: GNode; x: number; y: number } | null>(null);
  const [showContext, setShowContext] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [lost, setLost] = useState(0);
  const [resolved, setResolved] = useState<{ mttr: number; lost: number } | null>(null);
  const costRef = useRef({ perMin: 0, open: false });
  const lastOpen = useRef<number | null>(null);
  const resetting = useRef(false); // alerts vanishing because of Reset is not a recovery
  const lostRef = useRef(0);

  const focusOn = useCallback((ids: string[]) => setFocus({ ids, key: Date.now() }), []);

  const refreshGraph = useCallback(async () => {
    try {
      const g = await api.graph();
      const { data: next, recovered } = merge(dataRef.current, g);
      dataRef.current = next;
      setData(next); // same object when only properties changed: no layout re-heat
      setVersion((v) => v + 1);
      if (recovered.length) {
        const at = Date.now();
        setFlashes((f) => new Map([...f, ...recovered.map((id) => [id, at] as [string, number])]));
      }
    } catch {
      /* the health loop reports connectivity; the next event retries */
    }
  }, []);

  const refreshSide = useCallback(async () => {
    try {
      const [inc, acts, h] = await Promise.all([api.incidents(), api.actions(), api.health()]);
      setIncidents(inc);
      setActions(acts);
      setHealth(h);
    } catch {
      /* same as above */
    }
  }, []);

  const loadAll = useCallback(async () => {
    const [sc] = await Promise.all([api.scenarios(), refreshGraph(), refreshSide()]);
    setScenarios(sc);
  }, [refreshGraph, refreshSide]);

  // Connect: poll health until the API answers (free hosting sleeps), then load everything.
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    let tries = 0;
    const attempt = async () => {
      try {
        setHealth(await api.health());
        if (stop) return;
        setApiState("up");
        await loadAll();
      } catch {
        if (stop) return;
        tries += 1;
        setApiState(tries > 1 ? "down" : "connecting");
        timer = setTimeout(attempt, 3000);
      }
    };
    void attempt();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [loadAll]);

  const onEvent = useCallback((e: RunEvent) => {
    if (e.type === "hello") {
      // (Re)connected: the backend may have restarted or woken up, so reload everything.
      setApiState("up");
      void loadAll();
    } else if (e.type === "graph_update") {
      if (e.reason === "reset") resetting.current = true;
      void refreshGraph();
      void refreshSide();
    } else if (e.type === "tool_result") {
      const ids = (e.node_uids as string[]) ?? [];
      if (ids.length) focusOn(ids);
    } else if (e.type === "action_proposed" || e.type === "action_rejected" || e.type === "action_executed") {
      void refreshSide();
    } else if (e.type === "final") {
      void refreshGraph();
      void refreshSide();
    } else if (e.type === "scenario_started") {
      setActiveStep(null);
      setResolved(null);
    }
  }, [focusOn, loadAll, refreshGraph, refreshSide]);

  const { run, connected } = useRunSocket(onEvent);

  // Clock + cost of downtime: integrate $/min of the unhealthy services while the incident is open.
  useEffect(() => {
    let last = Date.now();
    const id = setInterval(() => {
      const t = Date.now();
      const add = costRef.current.open ? (costRef.current.perMin * (t - last)) / 60000 : 0; // computed now, not in the updater
      if (add) {
        lostRef.current += add;
        setLost(lostRef.current);
      }
      last = t;
      setNow(t);
    }, 500);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") {
        setMenu(null);
        setSelectedId(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const alerts = useMemo(() => {
    const fired = new Map<string, string>();
    for (const l of data.links) if (l.type === "FIRED_ON") fired.set(idOf(l.source), idOf(l.target).replace(/^svc:/, ""));
    return data.nodes.filter((n) => n.type === "Alert" && n.status !== "resolved")
      .map((n) => ({ ...n, target: fired.get(n.id) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `version` marks in-place property updates
  }, [data, version]);
  const services = useMemo(() => data.nodes.filter((n) => n.type === "Service"),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- as above
    [data, version]);
  const unhealthy = services.filter((n) => n.status !== "healthy").length;
  const perMin = services.reduce((sum, n) => n.status === "healthy" ? sum
    : sum + (n.revenue_per_min ?? 0) * (n.status === "down" ? 1 : 0.5), 0);
  const openSince = alerts.length > 0 ? Math.min(...alerts.map((a) => a.at ?? now)) : null;

  useEffect(() => {
    costRef.current = { perMin, open: openSince !== null };
  }, [perMin, openSince]);

  // Incident lifecycle in the header: open -> recovered (with MTTR and the bill). A reset is not a recovery.
  useEffect(() => {
    if (openSince !== null) {
      if (lastOpen.current === null) {
        lostRef.current = 0;
        setLost(0);
        setResolved(null);
      }
      lastOpen.current = openSince;
      resetting.current = false;
    } else if (lastOpen.current !== null) {
      const started = lastOpen.current;
      lastOpen.current = null;
      setResolved(resetting.current ? null : { mttr: Date.now() - started, lost: lostRef.current });
      resetting.current = false;
    }
  }, [openSince]);

  const highlight: Highlight = useMemo(() => {
    const steps = activeStep ? run.steps.filter((s) => s.id === activeStep.id) : run.steps;
    const last = activeStep ?? [...run.steps].reverse().find((s) => s.done);
    return {
      visited: new Set(steps.flatMap((s) => s.node_uids)),
      edges: new Set(steps.flatMap((s) => s.edge_uids)),
      current: new Set(run.running || activeStep ? last?.node_uids ?? [] : []),
      currentEdges: new Set(last?.edge_uids ?? []),
    };
  }, [run.steps, run.running, activeStep]);

  /** Show the result of an approval at once; the WebSocket refresh reconciles later (slow on free hosting). */
  const applyApproval = (a: Action, out: Record<string, unknown>) => {
    setActions((prev) => prev.map((x) => (x.uid === a.uid ? { ...x, status: "executed", outcome: String(out.outcome ?? "") } : x)));
    const healed = new Set([...((out.recovered as string[]) ?? []),
      ...(a.kind === "rollback" || a.kind === "scale_up" ? [`svc:${a.target}`] : [])]);
    const resolvedAlerts = new Set((out.resolved_alerts as string[]) ?? []);
    const at = Date.now();
    const breaker = a.kind === "open_breaker" ? "open" : a.kind === "scale_up" ? "closed" : null;
    patchLive(dataRef.current, healed, resolvedAlerts, breaker ? { target: `svc:${a.target}`, state: breaker } : null);
    if (healed.size) setFlashes((f) => new Map([...f, ...[...healed].map((id) => [id, at] as [string, number])]));
    setVersion((v) => v + 1);
    void refreshGraph();
  };

  const guard = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try {
      await fn();
    } catch (err) {
      setToast((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const breakService = (name: string): Break => (mode, deploy) => {
    setMenu(null);
    void guard("chaos", async () => {
      setActiveStep(null);
      await api.chaos(name, mode, deploy);
    });
  };

  const offline = apiState !== "up";
  const pending = actions.filter((a) => a.status === "pending");
  const done = run.runId
    ? actions.filter((a) => ["executed", "rejected", "failed"].includes(a.status) && a.run_id === run.runId)
    : [];
  const selected = selectedId ? data.nodes.find((n) => n.id === selectedId) ?? null : null;

  return (
    <div className="flex h-full flex-col">
      <TopBar health={health} api={apiState} socket={connected} model={run.provider}
              incident={openSince !== null
                ? { state: "open", since: openSince, now, alerts: alerts.length, unhealthy, lost, perMin }
                : resolved ? { state: "resolved", ...resolved } : { state: "quiet" }} />
      {openSince !== null && <div className="h-[2px] shrink-0 bg-crit" />}
      <div className="flex min-h-0 flex-1">
        <ControlPanel
          scenarios={scenarios} alerts={alerts} pending={pending} done={done} running={run.running} busy={busy}
          offline={offline} provider={provider} onProvider={setProvider}
          providers={PROVIDERS.filter((p) => !p.id || !health?.providers || health.providers.includes(p.id))}
          onInject={(name) => guard(name, async () => { setActiveStep(null); await api.inject(name); })}
          onInvestigate={() => guard("run", async () => { setActiveStep(null); await api.run(provider || undefined); })}
          onReset={(keep) => guard("reset", async () => {
            setActiveStep(null);
            resetting.current = true;
            await api.reset(keep);
          })}
          onApprove={(a) => guard(a.uid, async () => applyApproval(a, await api.approve(a.uid)))}
          onReject={(a) => guard(a.uid, async () => {
            await api.reject(a.uid);
            setActions((prev) => prev.map((x) => (x.uid === a.uid ? { ...x, status: "rejected" } : x)));
          })}
          onFocus={focusOn}
        />

        <main className="dotgrid relative min-w-0 flex-1 overflow-hidden" data-testid="graph">
          <GraphCanvas data={data} highlight={highlight} flashes={flashes} focus={focus} showContext={showContext}
                       selected={selectedId} onSelect={(n) => { setSelectedId(n?.id ?? null); setMenu(null); }}
                       onMenu={(node, x, y) => node.type === "Service" && setMenu({ node, x, y })} />

          <div className="absolute left-3 top-3 z-20 flex items-start gap-2">
            <ServiceSearch services={services} onPick={(n) => { setSelectedId(n.id); focusOn([n.id]); }} />
          </div>
          <div className="absolute right-3 top-3 z-20 flex gap-1.5 text-[12px]">
            <button onClick={() => setShowContext(!showContext)} data-testid="toggle-context"
                    className={`rounded-md border px-2.5 py-1 ${showContext ? "border-line-strong bg-raised text-ink" : "border-line bg-panel text-muted hover:text-ink"}`}>
              People, teams, memory
            </button>
            <button onClick={() => focusOn(services.map((n) => n.id))}
                    className="rounded-md border border-line bg-panel px-2.5 py-1 text-muted hover:text-ink">Fit</button>
          </div>

          {selected && (
            <NodeCard node={selected} onClose={() => setSelectedId(null)} disabled={run.running || offline}
                      onBreak={breakService(selected.name ?? "")} />
          )}
          {menu && (
            <div className="enter absolute z-30 w-48 rounded-md border border-line-strong bg-panel p-1 text-[12.5px] shadow-xl shadow-black/40"
                 style={{ left: menu.x + 6, top: menu.y + 6 }} onMouseLeave={() => setMenu(null)} data-testid="chaos-menu">
              <div className="px-2 py-1 font-mono text-[11px] text-faint">{menu.node.name}</div>
              {BREAKS.map((b) => (
                <button key={b.label} disabled={run.running || offline} onClick={() => breakService(menu.node.name ?? "")(b.mode, b.deploy)}
                        className="block w-full rounded px-2 py-1.5 text-left hover:bg-raised disabled:opacity-40">{b.label}</button>
              ))}
            </div>
          )}

          <Legend />
          {offline && <Offline state={apiState} />}
          {toast && (
            <button onClick={() => setToast(null)} data-testid="toast"
                    className="enter absolute bottom-10 left-1/2 z-30 -translate-x-1/2 rounded-md border border-crit/40 bg-[#1d1214] px-3 py-1.5 text-[12px] text-[#ffb3b1]">
              {toast} <span className="ml-2 text-faint">dismiss</span>
            </button>
          )}
        </main>

        <AgentTrail run={run} incidents={incidents} activeStep={activeStep?.id ?? null}
                    onStep={(s) => { setActiveStep(s); if (s?.node_uids.length) focusOn(s.node_uids); }}
                    onFocus={focusOn} />
      </div>
    </div>
  );
}

function ServiceSearch({ services, onPick }: { services: GNode[]; onPick: (n: GNode) => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const typing = ev.target instanceof HTMLInputElement || ev.target instanceof HTMLSelectElement;
      if ((ev.key === "/" && !typing) || (ev.key === "k" && (ev.metaKey || ev.ctrlKey))) {
        ev.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const matches = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = s ? services.filter((n) => (n.name ?? "").includes(s)) : services;
    return [...list].sort((a, b) => Number(a.status === "healthy") - Number(b.status === "healthy")
      || (a.name ?? "").localeCompare(b.name ?? "")).slice(0, 8);
  }, [q, services]);

  const pick = (n: GNode) => {
    onPick(n);
    setQ("");
    setOpen(false);
    input.current?.blur();
  };

  return (
    <div className="relative w-64">
      <input ref={input} value={q} data-testid="search"
             onChange={(e) => { setQ(e.target.value); setOpen(true); setHi(0); }}
             onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 120)}
             onKeyDown={(e) => {
               if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(h + 1, matches.length - 1)); }
               if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
               if (e.key === "Enter" && matches[hi]) pick(matches[hi]);
               if (e.key === "Escape") input.current?.blur();
             }}
             placeholder="Find a service to inspect or break"
             className="w-full rounded-md border border-line bg-panel px-2.5 py-1.5 pr-8 text-[12.5px] text-ink outline-none placeholder:text-faint focus:border-line-strong" />
      <kbd className="pointer-events-none absolute right-2 top-1.5">/</kbd>
      {open && matches.length > 0 && (
        <ul className="absolute mt-1 w-full overflow-hidden rounded-md border border-line-strong bg-panel py-1 shadow-xl shadow-black/40">
          {matches.map((n, i) => (
            <li key={n.id}>
              <button onMouseDown={(e) => { e.preventDefault(); pick(n); }} onMouseEnter={() => setHi(i)}
                      className={`flex w-full items-center gap-2 px-2.5 py-1 text-left text-[12.5px] ${i === hi ? "bg-raised" : ""}`}>
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: STATUS_COLOR[n.status ?? "healthy"] }} />
                <span className="font-mono">{n.name}</span>
                <span className="ml-auto text-[11px] text-faint">{n.tier}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Legend() {
  const items: [string, string][] = [
    ["healthy", C.ok], ["degraded", C.warn], ["down", C.crit], ["agent path", C.agent],
    ["deploy", TYPE_COLOR.Deployment], ["person", TYPE_COLOR.Person], ["incident", TYPE_COLOR.Incident],
  ];
  return (
    <div className="pointer-events-none absolute bottom-2.5 left-3 z-20 flex flex-wrap items-center gap-x-3 text-[11px] text-faint">
      {items.map(([label, color]) => (
        <span key={label} className="flex items-center gap-1">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />{label}
        </span>
      ))}
      <span className="hidden 2xl:inline">· size = PageRank · dashed ring = chokepoint · right-click a service to break it</span>
    </div>
  );
}

function Offline({ state }: { state: ApiState }) {
  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center bg-bg/70" data-testid="offline">
      <div className="max-w-sm rounded-lg border border-line bg-panel p-5 text-center">
        <Loader2 className="mx-auto mb-3 h-5 w-5 animate-spin text-muted" />
        <div className="text-[14px] font-medium">{state === "connecting" ? "Connecting to the API" : "Waking up the API"}</div>
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
          The backend runs on free hosting and sleeps when idle. The first request can take up to a minute;
          this page keeps retrying and loads by itself.
        </p>
        <p className="mt-2 font-mono text-[11px] text-faint">{API_BASE}</p>
      </div>
    </div>
  );
}

function NodeCard({ node, onClose, onBreak, disabled }: { node: GNode; onClose: () => void; onBreak: Break; disabled: boolean }) {
  const skip = new Set(["x", "y", "vx", "vy", "fx", "fy", "index", "__indexColor", "label", "id", "type", "name"]);
  const entries = Object.entries(node).filter(([k, v]) => !skip.has(k) && v !== null && v !== undefined && v !== "" && v !== false && !(k === "revenue_per_min" && v === 0));
  const fmt = (k: string, v: unknown) => k === "at" ? new Date(Number(v)).toLocaleString()
    : k === "revenue_per_min" ? `$${v}/min` : typeof v === "number" ? String(+v.toFixed(4)) : String(v);
  return (
    <div className="enter absolute left-3 top-14 z-20 w-72 rounded-lg border border-line-strong bg-panel text-[12px] shadow-xl shadow-black/40"
         data-testid="node-card">
      <div className="flex items-start justify-between gap-2 border-b border-line px-3 py-2.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {node.status && <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: STATUS_COLOR[node.status] ?? C.muted }} />}
            <span className="truncate text-[13px] font-medium">{node.label}</span>
          </div>
          <div className="mt-0.5 font-mono text-[10.5px] text-faint">{node.type} · {node.id}</div>
        </div>
        <button onClick={onClose} className="text-faint hover:text-ink"><X className="h-4 w-4" /></button>
      </div>
      <dl className="grid grid-cols-[96px_1fr] gap-x-2 gap-y-1 px-3 py-2.5">
        {entries.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-faint">{k.replace(/_/g, " ")}</dt>
            <dd className="truncate font-mono text-[11.5px] text-ink" title={String(v)}>{fmt(k, v)}</dd>
          </div>
        ))}
      </dl>
      {node.type === "Service" && (
        <div className="border-t border-line px-3 py-2.5">
          <div className="mb-1.5 text-[11px] uppercase tracking-[0.08em] text-faint">Chaos</div>
          <div className="flex flex-wrap gap-1.5">
            {BREAKS.map((b) => (
              <button key={b.label} disabled={disabled} onClick={() => onBreak(b.mode, b.deploy)}
                      data-testid={`break-${b.mode}-${b.deploy}`}
                      className="rounded border border-crit/35 px-2 py-0.5 text-[11.5px] text-[#ffb3b1] hover:bg-crit/10 disabled:opacity-40">
                {b.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
