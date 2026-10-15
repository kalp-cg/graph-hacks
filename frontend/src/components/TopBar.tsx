"use client";

import type { Health } from "@/lib/types";

export type ApiState = "connecting" | "up" | "down";

export const usd = (n: number) => "$" + Math.round(n).toLocaleString("en-US");

export function clock(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

interface Props {
  health: Health | null;
  api: ApiState;
  socket: boolean;
  model: string | null;
  incident:
    | { state: "quiet" }
    | { state: "open"; since: number; now: number; alerts: number; unhealthy: number; lost: number; perMin: number }
    | { state: "resolved"; mttr: number; lost: number };
}

export default function TopBar({ health, api, socket, model, incident }: Props) {
  const db = api === "up" && health?.falkordb.ok;
  const modelName = (model ?? health?.llm ?? "").replace(" (deterministic, no LLM)", "");
  return (
    <header className="flex h-12 shrink-0 items-center gap-5 border-b border-line px-4">
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 rotate-45 bg-brand" />
        <span className="text-[14px] font-semibold tracking-tight">sentinelgraph</span>
      </div>

      <div className="flex items-center gap-4 text-[12px] text-muted">
        <Status ok={!!db} warn={api === "connecting"}
                label={api === "down" ? "api unreachable" : api === "connecting" ? "connecting…"
                  : db ? `falkordb · ${health?.falkordb.services} services` : "falkordb down"} />
        {api === "up" && <Status ok={socket} label={socket ? "live" : "reconnecting"} />}
        {api === "up" && modelName && (
          <span className="hidden font-mono text-[11.5px] text-faint lg:inline">
            {model ? "run" : "model"}: {modelName}
          </span>
        )}
      </div>

      <div className="ml-auto">
        {incident.state === "open" ? (
          <div className="flex items-center gap-3 font-mono text-[12px]" data-testid="incident-open">
            <span className="flex items-center gap-1.5 font-sans font-semibold text-crit">
              <span className="blink h-2 w-2 rounded-full bg-crit" /> Incident
            </span>
            <span className="text-muted">{incident.alerts} alerts · {incident.unhealthy} unhealthy</span>
            <span className="text-ink" title="Revenue at risk on unhealthy services" data-testid="cost">
              {usd(incident.lost)} <span className="text-faint">· {usd(incident.perMin)}/min</span>
            </span>
            <span className="tabular-nums text-ink">{clock(incident.now - incident.since)}</span>
          </div>
        ) : incident.state === "resolved" ? (
          <div className="flex items-center gap-3 font-mono text-[12px]" data-testid="incident-resolved">
            <span className="flex items-center gap-1.5 font-sans font-semibold text-ok">
              <span className="h-2 w-2 rounded-full bg-ok" /> Recovered
            </span>
            <span className="text-muted">MTTR <span className="text-ink">{clock(incident.mttr)}</span></span>
            <span className="text-muted">cost <span className="text-ink">{usd(incident.lost)}</span></span>
          </div>
        ) : (
          <span className="flex items-center gap-1.5 text-[12px] text-muted" data-testid="incident-quiet">
            <span className="h-2 w-2 rounded-full bg-ok/80" /> All quiet
          </span>
        )}
      </div>
    </header>
  );
}

function Status({ ok, warn, label }: { ok: boolean; warn?: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-ok" : warn ? "blink bg-warn" : "bg-crit"}`} />
      {label}
    </span>
  );
}
