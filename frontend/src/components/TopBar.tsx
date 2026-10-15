"use client";

import { Activity, Database, Radio, ShieldCheck, Timer } from "lucide-react";
import type { Health } from "@/lib/types";

function fmt(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

interface Props {
  health: Health | null;
  connected: boolean;
  incident: { openSince: number | null; resolvedIn: number | null; now: number };
  firing: number;
  unhealthy: number;
}

export default function TopBar({ health, connected, incident, firing, unhealthy }: Props) {
  const open = incident.openSince !== null;
  return (
    <header className="glass relative z-20 flex h-14 shrink-0 items-center gap-4 rounded-xl px-4">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-6 w-6 text-cyan-300" />
        <div className="leading-tight">
          <div className="text-[15px] font-semibold tracking-tight">SentinelGraph</div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-slate-400">incident commander on FalkorDB</div>
        </div>
      </div>

      <div className="ml-4 flex items-center gap-2 text-xs">
        <Pill ok={!!health?.falkordb.ok} icon={<Database className="h-3.5 w-3.5" />}
              text={health?.falkordb.ok ? `FalkorDB · ${health.graph} · ${health.falkordb.services} services` : "FalkorDB offline"} />
        <Pill ok={!!health && !health.llm.startsWith("unavailable")} icon={<Activity className="h-3.5 w-3.5" />}
              text={health ? health.llm : "LLM …"} />
        <Pill ok={connected} icon={<Radio className="h-3.5 w-3.5" />} text={connected ? "live" : "reconnecting"} />
        {health && <span className="text-slate-500">{health.tools.length} MCP tools</span>}
      </div>

      <div className="ml-auto flex items-center gap-3">
        {open ? (
          <div className="flex items-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-1.5">
            <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
            <span className="text-xs font-semibold uppercase tracking-wider text-red-300">Incident</span>
            <span className="text-xs text-red-200/80">{firing} alerts · {unhealthy} unhealthy</span>
            <Timer className="ml-1 h-3.5 w-3.5 text-red-300" />
            <span className="font-mono text-sm tabular-nums text-red-100">{fmt(incident.now - (incident.openSince ?? 0))}</span>
          </div>
        ) : incident.resolvedIn !== null ? (
          <div className="flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
            <span className="text-xs font-semibold uppercase tracking-wider text-emerald-300">Recovered</span>
            <span className="text-xs text-emerald-200/80">MTTR</span>
            <span className="font-mono text-sm tabular-nums text-emerald-100">{fmt(incident.resolvedIn)}</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 rounded-lg border border-emerald-500/25 px-3 py-1.5 text-xs text-emerald-300/80">
            <span className="h-2 w-2 rounded-full bg-emerald-400" /> All systems operational
          </div>
        )}
      </div>
    </header>
  );
}

function Pill({ ok, icon, text }: { ok: boolean; icon: React.ReactNode; text: string }) {
  return (
    <span className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 ${ok
      ? "border-emerald-500/25 bg-emerald-500/5 text-emerald-200/90" : "border-amber-500/30 bg-amber-500/10 text-amber-200"}`}>
      {icon}
      <span className="max-w-[260px] truncate">{text}</span>
    </span>
  );
}
