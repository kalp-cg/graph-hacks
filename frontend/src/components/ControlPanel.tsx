"use client";

import { AlertTriangle, Bot, Check, Flame, Loader2, Play, RotateCcw, Siren, X } from "lucide-react";
import type { Action, GNode, Scenario } from "@/lib/types";

const KIND_LABEL: Record<string, string> = {
  rollback: "Roll back", open_breaker: "Open circuit breaker", scale_up: "Scale up", page_oncall: "Page on-call",
};

interface Props {
  scenarios: Scenario[];
  alerts: GNode[];
  pending: Action[];
  done: Action[];
  running: boolean;
  busy: string | null;
  provider: string;
  providers: { id: string; label: string }[];
  onProvider: (p: string) => void;
  onInject: (name: string) => void;
  onInvestigate: () => void;
  onReset: (keepMemory: boolean) => void;
  onApprove: (a: Action) => void;
  onReject: (a: Action) => void;
  onFocus: (ids: string[]) => void;
}

export default function ControlPanel(p: Props) {
  return (
    <aside className="glass scroll-thin flex w-[300px] shrink-0 flex-col gap-4 overflow-y-auto rounded-xl p-3">
      <section>
        <Heading icon={<Flame className="h-3.5 w-3.5" />}>Break production</Heading>
        <div className="flex flex-col gap-1.5">
          {p.scenarios.map((s) => (
            <button key={s.name} disabled={p.running || !!p.busy} onClick={() => p.onInject(s.name)}
                    className="group rounded-lg border border-slate-700/60 bg-slate-900/40 px-2.5 py-2 text-left transition hover:border-red-400/50 hover:bg-red-500/5 disabled:opacity-40">
              <div className="flex items-center justify-between">
                <span className="font-mono text-[12px] text-slate-200">{s.name}</span>
                {p.busy === s.name ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  : <Play className="h-3.5 w-3.5 text-slate-500 group-hover:text-red-300" />}
              </div>
              <div className="text-[11px] text-slate-400">{s.title}</div>
            </button>
          ))}
        </div>
        <div className="mt-2 flex gap-1.5">
          <button onClick={() => p.onReset(true)} disabled={p.running}
                  className="flex flex-1 items-center justify-center gap-1 rounded-md border border-slate-700/60 py-1 text-[11px] text-slate-300 hover:bg-slate-800/60 disabled:opacity-40"
                  title="Healthy infrastructure, keep what the agent learned">
            <RotateCcw className="h-3 w-3" /> Reset
          </button>
          <button onClick={() => p.onReset(false)} disabled={p.running}
                  className="flex flex-1 items-center justify-center gap-1 rounded-md border border-slate-700/60 py-1 text-[11px] text-slate-400 hover:bg-slate-800/60 disabled:opacity-40"
                  title="Re-seed everything, including memory">
            Wipe memory
          </button>
        </div>
      </section>

      <section>
        <Heading icon={<Siren className="h-3.5 w-3.5" />}>Firing alerts <span className="text-slate-500">({p.alerts.length})</span></Heading>
        {p.alerts.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-700/60 px-3 py-3 text-center text-[11px] text-slate-500">
            Quiet. Break something above.
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            {p.alerts.map((a) => (
              <button key={a.id} onClick={() => p.onFocus([a.id])}
                      className="slidein flex items-center gap-2 rounded-md border border-rose-500/25 bg-rose-500/5 px-2 py-1.5 text-left">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-rose-400" />
                <div className="min-w-0">
                  <div className="truncate text-[12px] text-rose-100">{a.target ?? alertService(a)}</div>
                  <div className="font-mono text-[10px] text-rose-300/70">{a.metric} {a.value} &gt; {a.threshold}</div>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      <section>
        <Heading icon={<Bot className="h-3.5 w-3.5" />}>Agent</Heading>
        <select value={p.provider} onChange={(e) => p.onProvider(e.target.value)} disabled={p.running}
                className="mb-1.5 w-full rounded-md border border-slate-700/60 bg-slate-900 px-2 py-1 text-[12px] text-slate-200">
          {p.providers.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
        <button onClick={p.onInvestigate} disabled={p.running || p.alerts.length === 0}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-cyan-500 to-sky-600 py-2 text-sm font-semibold text-slate-950 shadow-lg shadow-cyan-500/20 transition hover:brightness-110 disabled:from-slate-700 disabled:to-slate-700 disabled:text-slate-400 disabled:shadow-none">
          {p.running ? <><Loader2 className="h-4 w-4 animate-spin" /> Investigating…</> : <><Bot className="h-4 w-4" /> Investigate</>}
        </button>
      </section>

      <section>
        <Heading icon={<Check className="h-3.5 w-3.5" />}>Awaiting approval <span className="text-slate-500">({p.pending.length})</span></Heading>
        {p.pending.length === 0 && (
          <div className="text-[11px] text-slate-500">The agent can only propose. You decide.</div>
        )}
        <div className="flex flex-col gap-2">
          {p.pending.map((a) => (
            <div key={a.uid} className="slidein rounded-lg border border-yellow-400/30 bg-yellow-400/5 p-2.5">
              <div className="flex items-center justify-between">
                <span className="text-[13px] font-semibold text-yellow-100">{KIND_LABEL[a.kind] ?? a.kind}</span>
                <span className={`rounded px-1.5 text-[10px] uppercase ${a.risk === "high" ? "bg-red-500/20 text-red-300"
                  : a.risk === "low" ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-300"}`}>{a.risk} risk</span>
              </div>
              <button onClick={() => p.onFocus([a.target_uid, `svc:${a.target}`])} className="font-mono text-[11px] text-cyan-300 hover:underline">
                {a.target_uid}
              </button>
              {a.reason && <p className="mt-1 line-clamp-3 text-[11px] text-slate-300">{a.reason}</p>}
              <div className="mt-2 flex gap-1.5">
                <button onClick={() => p.onApprove(a)} disabled={!!p.busy}
                        className="flex flex-1 items-center justify-center gap-1 rounded-md bg-emerald-500 py-1 text-[12px] font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50">
                  {p.busy === a.uid ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />} Approve
                </button>
                <button onClick={() => p.onReject(a)} disabled={!!p.busy}
                        className="flex items-center justify-center gap-1 rounded-md border border-slate-600 px-2 py-1 text-[12px] text-slate-300 hover:bg-slate-800 disabled:opacity-50">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
        {p.done.length > 0 && (
          <div className="mt-2 flex flex-col gap-1">
            {p.done.map((a) => (
              <div key={a.uid} className="flex items-start gap-1.5 text-[11px]">
                {a.status === "executed" ? <Check className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400" />
                  : <X className="mt-0.5 h-3 w-3 shrink-0 text-slate-500" />}
                <span className={a.status === "executed" ? "text-emerald-200/90" : "text-slate-500 line-through"}>
                  {a.outcome ?? `${KIND_LABEL[a.kind] ?? a.kind} ${a.target}`}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </aside>
  );
}

function alertService(a: GNode) {
  return a.label;
}

function Heading({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <h3 className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
      {icon}{children}
    </h3>
  );
}
