"use client";

import dynamic from "next/dynamic";
import { Bomb, Eye, EyeOff, GitCommitHorizontal, TrendingDown, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { STATUS_COLOR, TYPE_COLOR, type Highlight } from "@/lib/graphStyle";
import type { Action, GLink, GNode, GraphData, Health, Incident, RunEvent, Scenario, Step } from "@/lib/types";
import { useRunSocket } from "@/lib/useRunSocket";
import AgentTrail from "./AgentTrail";
import ControlPanel from "./ControlPanel";
import TopBar from "./TopBar";

const GraphCanvas = dynamic(() => import("./GraphCanvas"), { ssr: false });

const PROVIDERS = [
  { id: "", label: "Default model (server LLM_PROVIDER)" },
  { id: "ollama", label: "Local: Ollama" },
  { id: "gemini", label: "Gemini" },
  { id: "openai", label: "OpenAI-compatible API" },
  { id: "autopilot", label: "Autopilot (deterministic, no LLM)" },
];

type Data = { nodes: GNode[]; links: GLink[] };

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
    if (o.status && o.status !== "healthy" && n.status === "healthy") recovered.push(n.id);
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

export default function Dashboard() {
  const [data, setData] = useState<Data>({ nodes: [], links: [] });
  const dataRef = useRef(data);
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
  const [selected, setSelected] = useState<GNode | null>(null);
  const [showContext, setShowContext] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [resolvedIn, setResolvedIn] = useState<number | null>(null);
  const [version, setVersion] = useState(0);
  const lastOpen = useRef<number | null>(null);
  const [menu, setMenu] = useState<{ node: GNode; x: number; y: number } | null>(null);
  const [lost, setLost] = useState(0);
  const costRef = useRef({ perMin: 0, open: false });

  const focusOn = useCallback((ids: string[]) => setFocus({ ids, key: Date.now() }), []);

  const refreshGraph = useCallback(async () => {
    const g = await api.graph();
    const { data: next, recovered } = merge(dataRef.current, g);
    dataRef.current = next;
    setData(next); // same object when only properties changed: no layout re-heat
    setVersion((v) => v + 1);
    if (recovered.length) {
      const at = Date.now();
      setFlashes((f) => new Map([...f, ...recovered.map((id) => [id, at] as [string, number])]));
      focusOn(recovered);
    }
  }, [focusOn]);

  const refreshSide = useCallback(async () => {
    const [inc, acts, h] = await Promise.all([api.incidents(), api.actions(), api.health()]);
    setIncidents(inc);
    setActions(acts);
    setHealth(h);
  }, []);

  const onEvent = useCallback((e: RunEvent) => {
    if (e.type === "graph_update") {
      void refreshGraph();
      void refreshSide();
    } else if (e.type === "tool_result") {
      const ids = (e.node_uids as string[]) ?? [];
      if (ids.length) focusOn(ids);
    } else if (e.type === "action_proposed" || e.type === "action_rejected") {
      void refreshSide();
    } else if (e.type === "final") {
      void refreshGraph();
      void refreshSide();
    } else if (e.type === "scenario_started") {
      setActiveStep(null);
    }
  }, [focusOn, refreshGraph, refreshSide]);

  const { run, connected } = useRunSocket(onEvent);

  useEffect(() => {
    void (async () => {
      try {
        setScenarios(await api.scenarios());
        await Promise.all([refreshGraph(), refreshSide()]);
      } catch (err) {
        setToast(`Backend unreachable: ${(err as Error).message}`);
      }
    })();
  }, [refreshGraph, refreshSide]);

  useEffect(() => {
    let last = Date.now();
    const id = setInterval(() => {
      const t = Date.now();
      // Cost of downtime: integrate $/min of the unhealthy services while the incident is open.
      if (costRef.current.open) setLost((l) => l + (costRef.current.perMin * (t - last)) / 60000);
      last = t;
      setNow(t);
    }, 500);
    return () => clearInterval(id);
  }, []);

  // Alerts with the service they fired on.
  const alerts = useMemo(() => {
    const fired = new Map<string, string>();
    for (const l of data.links) if (l.type === "FIRED_ON") fired.set(idOf(l.source), idOf(l.target).replace(/^svc:/, ""));
    return data.nodes.filter((n) => n.type === "Alert").map((n) => ({ ...n, target: fired.get(n.id) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `version` marks in-place property updates
  }, [data, version]);
  const unhealthy = data.nodes.filter((n) => n.type === "Service" && n.status !== "healthy").length;
  const perMin = data.nodes.reduce((sum, n) => n.type !== "Service" || n.status === "healthy" ? sum
    : sum + (n.revenue_per_min ?? 0) * (n.status === "down" ? 1 : 0.5), 0);

  // MTTR clock: from the first alert until everything is green again.
  const openSince = alerts.length > 0 ? Math.min(...alerts.map((a) => a.at ?? 0)) : null;
  useEffect(() => {
    costRef.current = { perMin, open: openSince !== null };
  }, [perMin, openSince]);
  useEffect(() => {
    if (openSince !== null) {
      if (lastOpen.current === null) setLost(0); // a new incident starts a new bill
      lastOpen.current = openSince;
    } else if (lastOpen.current !== null) {
      const started = lastOpen.current;
      lastOpen.current = null;
      setResolvedIn(Date.now() - started);
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

  const pending = actions.filter((a) => a.status === "pending");
  const done = run.runId
    ? actions.filter((a) => (a.status === "executed" || a.status === "rejected") && a.run_id === run.runId)
    : [];

  return (
    <div className="flex h-full flex-col gap-2 p-2">
      <TopBar health={health} connected={connected} model={run.provider} firing={alerts.length} unhealthy={unhealthy}
              incident={{ openSince, resolvedIn: openSince === null ? resolvedIn : null, now }}
              cost={{ perMin, total: lost }} />
      <div className="flex min-h-0 flex-1 gap-2">
        <ControlPanel
          scenarios={scenarios} alerts={alerts} pending={pending} done={done} running={run.running} busy={busy}
          provider={provider} onProvider={setProvider}
          providers={PROVIDERS.filter((p) => !p.id || !health?.providers || health.providers.includes(p.id))}
          onInject={(name) => guard(name, async () => { setActiveStep(null); await api.inject(name); })}
          onInvestigate={() => guard("run", async () => { setActiveStep(null); await api.run(provider || undefined); })}
          onReset={(keep) => guard("reset", async () => { setActiveStep(null); await api.reset(keep); })}
          onApprove={(a) => guard(a.uid, () => api.approve(a.uid))}
          onReject={(a) => guard(a.uid, () => api.reject(a.uid))}
          onFocus={focusOn}
        />

        <main className="glass relative min-w-0 flex-1 overflow-hidden rounded-xl">
          {alerts.length > 0 && <div className="incident-vignette absolute inset-0 z-10" />}
          <GraphCanvas data={data} highlight={highlight} flashes={flashes} focus={focus} showContext={showContext}
                       selected={selected?.id ?? null} onSelect={(n) => { setSelected(n); setMenu(null); }}
                       onMenu={(node, x, y) => node.type === "Service" && setMenu({ node, x, y })} />
          {menu && (
            <ChaosMenu node={menu.node} x={menu.x} y={menu.y} disabled={run.running}
                       onPick={(mode, deploy) => {
                         setMenu(null);
                         void guard("chaos", async () => { setActiveStep(null); await api.chaos(menu.node.name ?? "", mode, deploy); });
                       }}
                       onClose={() => setMenu(null)} />
          )}
          <Legend />
          <div className="glass absolute bottom-12 left-3 z-20 rounded-md px-2.5 py-1 text-[10.5px] text-slate-400">
            <Bomb className="mr-1 inline h-3 w-3 text-red-400" />Right-click any service to break it: unscripted chaos
          </div>
          <div className="absolute right-3 top-3 z-20 flex gap-1.5">
            <button onClick={() => setShowContext(!showContext)}
                    className="glass flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-slate-300 hover:text-white">
              {showContext ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              {showContext ? "Hide context" : "Show people, teams, memory"}
            </button>
            <button onClick={() => focusOn(data.nodes.filter((n) => n.type === "Service").map((n) => n.id))}
                    className="glass rounded-md px-2 py-1 text-[11px] text-slate-300 hover:text-white">Fit</button>
          </div>
          {selected && (
            <NodeCard node={selected} onClose={() => setSelected(null)} disabled={run.running}
                      onBreak={(mode, deploy) => guard("chaos", async () => {
                        setActiveStep(null);
                        await api.chaos(selected.name ?? "", mode, deploy);
                      })} />
          )}
          {toast && (
            <button onClick={() => setToast(null)}
                    className="absolute bottom-3 left-1/2 z-30 -translate-x-1/2 rounded-md border border-red-500/40 bg-red-950/90 px-3 py-1.5 text-[12px] text-red-200">
              {toast} ✕
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

function idOf(end: string | GNode): string {
  return typeof end === "string" ? end : end.id;
}

function Legend() {
  const items: [string, string][] = [
    ["healthy", STATUS_COLOR.healthy], ["degraded", STATUS_COLOR.degraded], ["down", STATUS_COLOR.down],
    ["alert", TYPE_COLOR.Alert], ["deployment", TYPE_COLOR.Deployment], ["person", TYPE_COLOR.Person],
    ["incident", TYPE_COLOR.Incident], ["action", TYPE_COLOR.Action], ["agent path", "#22d3ee"],
  ];
  return (
    <div className="glass absolute bottom-3 left-3 z-20 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md px-2.5 py-1.5 text-[10.5px] text-slate-400">
      {items.map(([label, color]) => (
        <span key={label} className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full" style={{ background: color }} />{label}
        </span>
      ))}
      <span className="text-slate-500">· size = PageRank · dashed ring = top betweenness</span>
    </div>
  );
}

type Break = (mode: "down" | "degraded", deploy: boolean) => void;

const BREAKS: { mode: "down" | "degraded"; deploy: boolean; label: string; icon: React.ReactNode }[] = [
  { mode: "down", deploy: true, label: "Bad deploy → down", icon: <GitCommitHorizontal className="h-3.5 w-3.5" /> },
  { mode: "down", deploy: false, label: "Crash (no deploy)", icon: <Bomb className="h-3.5 w-3.5" /> },
  { mode: "degraded", deploy: false, label: "Degrade (no deploy)", icon: <TrendingDown className="h-3.5 w-3.5" /> },
];

function ChaosMenu({ node, x, y, disabled, onPick, onClose }: {
  node: GNode; x: number; y: number; disabled: boolean; onPick: Break; onClose: () => void;
}) {
  return (
    <div className="glass slidein absolute z-30 w-52 rounded-lg p-1.5 text-[12px] shadow-2xl" style={{ left: x + 8, top: y + 8 }}
         onMouseLeave={onClose}>
      <div className="px-2 py-1 text-[10.5px] uppercase tracking-wider text-slate-400">Break {node.name}</div>
      {BREAKS.map((b) => (
        <button key={b.label} disabled={disabled} onClick={() => onPick(b.mode, b.deploy)}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-slate-200 hover:bg-red-500/15 disabled:opacity-40">
          <span className="text-red-300">{b.icon}</span>{b.label}
        </button>
      ))}
    </div>
  );
}

function NodeCard({ node, onClose, onBreak, disabled }: { node: GNode; onClose: () => void; onBreak: Break; disabled: boolean }) {
  const skip = new Set(["x", "y", "vx", "vy", "fx", "fy", "index", "__indexColor", "label", "id"]);
  const entries = Object.entries(node).filter(([k, v]) => !skip.has(k) && v !== null && v !== undefined && v !== "");
  return (
    <div className="glass slidein absolute left-3 top-3 z-20 w-72 rounded-lg p-3 text-[12px]">
      <div className="mb-1 flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold text-slate-100">{node.label}</div>
          <div className="font-mono text-[10.5px] text-cyan-300/80">{node.id}</div>
        </div>
        <button onClick={onClose}><X className="h-4 w-4 text-slate-400 hover:text-white" /></button>
      </div>
      <dl className="grid grid-cols-[90px_1fr] gap-x-2 gap-y-0.5">
        {entries.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-slate-500">{k}</dt>
            <dd className="truncate text-slate-200" title={String(v)}>
              {k === "at" ? new Date(Number(v)).toLocaleString() : typeof v === "number" ? +v.toFixed(4) : String(v)}
            </dd>
          </div>
        ))}
      </dl>
      {node.type === "Service" && (
        <div className="mt-2 flex flex-wrap gap-1 border-t border-slate-700/50 pt-2">
          {BREAKS.map((b) => (
            <button key={b.label} disabled={disabled} onClick={() => onBreak(b.mode, b.deploy)}
                    className="flex items-center gap-1 rounded border border-red-500/30 px-1.5 py-0.5 text-[10.5px] text-red-200 hover:bg-red-500/15 disabled:opacity-40">
              {b.icon}{b.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
