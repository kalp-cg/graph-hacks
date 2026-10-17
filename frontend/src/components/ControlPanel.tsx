"use client";

import { Loader2 } from "lucide-react";
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
  offline: boolean;
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
  const locked = p.running || !!p.busy || p.offline;
  return (
    <aside className="thin-scroll flex w-[272px] shrink-0 flex-col overflow-y-auto border-r border-line">
      <Section title="Break production" hint="Inject a realistic incident">
        <div className="flex flex-col">
          {p.scenarios.map((s) => (
            <button key={s.name} disabled={locked} onClick={() => p.onInject(s.name)}
                    data-testid={`scenario-${s.name}`}
                    className="group -mx-2 rounded-md px-2 py-1.5 text-left hover:bg-raised disabled:pointer-events-none disabled:opacity-40">
              <div className="flex items-center justify-between">
                <span className="font-mono text-[12px] text-ink">{s.name}</span>
                {p.busy === s.name && <Loader2 className="h-3 w-3 animate-spin text-muted" />}
              </div>
              <div className="text-[11.5px] text-muted">{s.title}</div>
            </button>
          ))}
          {p.scenarios.length === 0 && <div className="text-[12px] text-faint">Waiting for the API…</div>}
        </div>
        <div className="mt-2 flex gap-3 text-[11.5px]">
          <button onClick={() => p.onReset(true)} disabled={locked} data-testid="reset"
                  className="text-muted underline-offset-2 hover:text-ink hover:underline disabled:opacity-40"
                  title="Healthy infrastructure; keep what the agent learned">Reset</button>
          <button onClick={() => p.onReset(false)} disabled={locked}
                  className="text-faint underline-offset-2 hover:text-ink hover:underline disabled:opacity-40"
                  title="Re-seed everything, including learned memory">Wipe memory</button>
        </div>
      </Section>

      <Section title={`Alerts${p.alerts.length ? ` · ${p.alerts.length}` : ""}`}>
        {p.alerts.length === 0 ? (
          <div className="text-[12px] text-faint">Nothing firing.</div>
        ) : (
          <div className="flex flex-col gap-1" data-testid="alerts">
            {p.alerts.map((a) => (
              <button key={a.id} onClick={() => p.onFocus([a.id, `svc:${a.target}`])}
                      className="enter flex items-center justify-between gap-2 border-l-2 border-crit bg-crit/[0.06] py-1 pl-2 pr-1 text-left hover:bg-crit/10">
                <span className="truncate text-[12.5px]">{a.target ?? a.label}</span>
                <span className="shrink-0 font-mono text-[10.5px] text-muted">{a.metric} {a.value}</span>
              </button>
            ))}
          </div>
        )}
      </Section>

      <Section title="Agent">
        <select value={p.provider} onChange={(e) => p.onProvider(e.target.value)} disabled={p.running}
                data-testid="provider"
                className="mb-1 w-full rounded-md border border-line bg-raised px-2 py-1.5 text-[12px] text-ink outline-none focus:border-line-strong">
          {p.providers.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
        <p className="mb-2 text-[10.5px] text-faint">
          ⚡ Includes multi-key pool rotation & Autopilot failover.
        </p>
        <button onClick={p.onInvestigate} disabled={locked || p.alerts.length === 0} data-testid="investigate"
                className="flex w-full items-center justify-center gap-2 rounded-md bg-brand py-2 text-[13px] font-semibold text-[#1a0d06] hover:brightness-110 disabled:bg-raised disabled:text-faint">
          {p.running ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Investigating</> : "Investigate"}
        </button>
        {!p.running && p.alerts.length === 0 && !p.offline && (
          <p className="mt-1.5 text-[11px] text-faint">Break something first.</p>
        )}
      </Section>

      <Section title={`Needs approval${p.pending.length ? ` · ${p.pending.length}` : ""}`}
               hint="The agent proposes. You decide.">
        <div className="flex flex-col gap-2" data-testid="approvals">
          {p.pending.map((a) => (
            <div key={a.uid} className="enter rounded-md border border-line bg-raised p-2.5">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[13px] font-medium">{KIND_LABEL[a.kind] ?? a.kind}</span>
                <span className={`font-mono text-[10.5px] ${a.risk === "high" ? "text-crit" : a.risk === "low" ? "text-ok" : "text-warn"}`}>
                  {a.risk} risk
                </span>
              </div>
              <button onClick={() => p.onFocus([a.target_uid, `svc:${a.target}`])}
                      className="font-mono text-[11px] text-agent hover:underline">{a.target_uid}</button>
              {a.reason && <p className="mt-1 line-clamp-3 text-[11.5px] leading-snug text-muted">{a.reason}</p>}
              <div className="mt-2 flex gap-1.5">
                <button onClick={() => p.onApprove(a)} disabled={!!p.busy || p.offline}
                        className="flex flex-1 items-center justify-center gap-1 rounded bg-ink py-1 text-[12px] font-semibold text-bg hover:bg-white disabled:opacity-40">
                  {p.busy === a.uid ? <Loader2 className="h-3 w-3 animate-spin" /> : "Approve"}
                </button>
                <button onClick={() => p.onReject(a)} disabled={!!p.busy || p.offline}
                        className="rounded border border-line-strong px-2.5 py-1 text-[12px] text-muted hover:text-ink disabled:opacity-40">
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
        {p.done.length > 0 && (
          <ul className="mt-2 flex flex-col gap-1 text-[11.5px]" data-testid="done-actions">
            {p.done.map((a) => (
              <li key={a.uid} className={a.status === "executed" ? "text-ok" : "text-faint line-through"}>
                {a.status === "executed" ? "✓ " : "✕ "}{a.outcome || `${KIND_LABEL[a.kind] ?? a.kind} ${a.target}`}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </aside>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-line px-4 py-3">
      <h3 className="text-[11px] font-medium uppercase tracking-[0.08em] text-faint">{title}</h3>
      {hint && <p className="mb-1.5 text-[11.5px] text-faint/80">{hint}</p>}
      <div className={hint ? "" : "mt-1.5"}>{children}</div>
    </section>
  );
}
