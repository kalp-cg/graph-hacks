"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { RunState } from "@/lib/useRunSocket";
import type { Incident, Step } from "@/lib/types";

interface Props {
  run: RunState;
  incidents: Incident[];
  activeStep: string | null;
  onStep: (s: Step | null) => void;
  onFocus: (ids: string[]) => void;
}

export default function AgentTrail({ run, incidents, activeStep, onStep, onFocus }: Props) {
  const [tab, setTab] = useState<"trail" | "memory">("trail");
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [run.steps.length, run.final]);

  return (
    <aside className="flex w-[384px] shrink-0 flex-col border-l border-line">
      <div className="flex h-10 shrink-0 items-end gap-5 border-b border-line px-4 text-[12.5px]">
        {(["trail", "memory"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} data-testid={`tab-${t}`}
                  className={`-mb-px border-b pb-2 ${tab === t ? "border-ink text-ink" : "border-transparent text-muted hover:text-ink"}`}>
            {t === "trail" ? "Investigation" : `Memory · ${incidents.length}`}
          </button>
        ))}
        {tab === "trail" && run.runId && (
          <span className="ml-auto pb-2 font-mono text-[11px] text-faint">
            {run.incidentId ?? ""} · {run.steps.length} steps
          </span>
        )}
      </div>

      {tab === "trail" ? (
        <div className="thin-scroll flex-1 overflow-y-auto px-4 py-3" data-testid="trail">
          {!run.runId && <EmptyTrail />}
          {run.fallback && (
            <div className="mb-3 rounded-md border border-warn/30 bg-warn/[0.06] px-2.5 py-2 text-[11.5px] text-warn">
              {run.fallback}
            </div>
          )}
          <ol className="relative">
            {run.steps.map((s, i) => (
              <StepRow key={s.id} step={s} n={i + 1} last={i === run.steps.length - 1 && !run.running}
                       active={activeStep === s.id} onClick={() => onStep(activeStep === s.id ? null : s)} />
            ))}
          </ol>
          {run.running && (
            <div className="flex items-center gap-2 pl-[30px] text-[12px] text-muted">
              <span className="blink h-1.5 w-1.5 rounded-full bg-agent" />
              {run.steps.length === 0 ? "Reading the graph" : "Thinking"}
              <span className="font-mono text-[11px] text-faint">{run.provider}</span>
            </div>
          )}
          {run.error && (
            <div className="mt-3 rounded-md border border-crit/30 bg-crit/[0.06] p-2.5 text-[12px] text-crit">{run.error}</div>
          )}
          {run.final && (
            <div className="enter mt-4 border-t border-line pt-3" data-testid="report">
              <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-muted">
                <span><span className="text-ink">{run.final.steps}</span> steps</span>
                <span><span className="text-ink">{run.final.seconds}</span>s</span>
                {run.final.root_cause && (
                  <button onClick={() => onFocus([`svc:${run.final!.root_cause}`])} className="hover:text-ink">
                    root cause <span className="text-crit">{run.final.root_cause}</span>
                  </button>
                )}
              </div>
              {run.final.repeat_of ? (
                <div className="mb-2 rounded-md bg-agent/[0.08] px-2.5 py-1.5 text-[12px] text-[#c8d3ff]" data-testid="repeat">
                  Seen before: <b>{run.final.repeat_of.id}</b> took {run.final.repeat_of.steps_taken} steps. This time:{" "}
                  <b>{run.final.steps}</b>.
                </div>
              ) : run.final.root_cause ? (
                <div className="mb-2 text-[11.5px] text-faint">New failure pattern, stored as memory for next time.</div>
              ) : null}
              <div className="report text-[12.5px] leading-relaxed text-[#c5c8ce]">
                <ReactMarkdown>{run.final.report}</ReactMarkdown>
              </div>
              <div className="mt-1 text-[11px] text-faint">by {run.final.provider}</div>
            </div>
          )}
          <div ref={bottom} />
        </div>
      ) : (
        <MemoryList incidents={incidents} onFocus={onFocus} />
      )}
    </aside>
  );
}

function EmptyTrail() {
  return (
    <div className="mt-6 text-[12.5px] leading-relaxed text-muted">
      <p className="text-ink">How it works</p>
      <ol className="mt-2 list-decimal space-y-1.5 pl-4">
        <li>Break production on the left, or right-click any service.</li>
        <li>Press <b className="text-ink">Investigate</b>. The agent queries FalkorDB through MCP tools; every step
          shows its Cypher and lights up its path on the graph.</li>
        <li>It proposes fixes. Nothing changes until you approve.</li>
        <li>The incident is saved to the graph, so a repeat is solved faster.</li>
      </ol>
    </div>
  );
}

function StepRow({ step, n, active, last, onClick }: {
  step: Step; n: number; active: boolean; last: boolean; onClick: () => void;
}) {
  const [open, setOpen] = useState(false);
  const args = Object.entries(step.args).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join("  ");
  return (
    <li className="enter relative pb-3 pl-[30px]" data-testid="step">
      {!last && <span className="absolute left-[9px] top-5 h-full w-px bg-line" />}
      <span className={`absolute left-0 top-0.5 flex h-[19px] w-[19px] items-center justify-center rounded-full border font-mono text-[10px] ${
        step.error ? "border-warn/60 text-warn" : !step.done ? "border-agent text-agent" : active ? "border-agent bg-agent text-bg" : "border-line-strong text-muted"}`}>
        {n}
      </span>
      <button onClick={onClick} className={`w-full rounded-md px-1.5 py-0.5 text-left ${active ? "bg-agent/[0.08]" : "hover:bg-raised"}`}>
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-[12px] text-ink">{step.name}</span>
          <span className="ml-auto shrink-0 font-mono text-[10.5px] text-faint">
            {step.done ? `${step.ms}ms · ${step.node_uids.length}n` : "…"}
          </span>
        </div>
        {args && <div className="truncate font-mono text-[10.5px] text-faint" title={args}>{args}</div>}
        {step.summary && (
          <div className={`mt-0.5 text-[12.5px] leading-snug ${step.error ? "text-warn" : "text-[#c5c8ce]"}`}>{step.summary}</div>
        )}
      </button>
      {step.cypher && (
        <div className="px-1.5">
          <button onClick={() => setOpen(!open)} className="mt-0.5 font-mono text-[10.5px] text-faint hover:text-ink">
            {open ? "− hide cypher" : "+ cypher"}
          </button>
          {open && <CypherBlock code={step.cypher} />}
        </div>
      )}
    </li>
  );
}

const KW = "MATCH|OPTIONAL|WHERE|WITH|RETURN|ORDER BY|LIMIT|UNWIND|CALL|YIELD|CREATE|MERGE|SET|DELETE|DETACH|AS|AND|OR|NOT|IN|CASE|WHEN|THEN|ELSE|END|DISTINCT|FOREACH|IS|NULL|DESC";
const IS_KW = new RegExp(`^(?:${KW})$`);
const TOKENS = new RegExp(`(\\$\\w+|'[^']*'|\\b(?:${KW})\\b|algo\\.\\w+)`, "g");

function CypherBlock({ code }: { code: string }) {
  const pretty = code.replace(/\s+(OPTIONAL MATCH|MATCH|WHERE|WITH|RETURN|ORDER BY|LIMIT|UNWIND|CALL|YIELD|CREATE|SET|FOREACH)\b/g, "\n$1");
  return (
    <pre className="thin-scroll mt-1 max-h-60 overflow-auto whitespace-pre-wrap rounded-md border border-line bg-[#0a0b0d] p-2 font-mono text-[10.5px] leading-relaxed text-muted">
      {pretty.split(TOKENS).map((p, i) =>
        p.startsWith("$") ? <span key={i} className="text-warn">{p}</span>
          : p.startsWith("'") ? <span key={i} className="text-ok">{p}</span>
          : p.startsWith("algo.") ? <span key={i} className="text-brand">{p}</span>
          : IS_KW.test(p) ? <span key={i} className="text-agent">{p}</span>
          : <span key={i} className="text-[#c5c8ce]">{p}</span>)}
    </pre>
  );
}

function MemoryList({ incidents, onFocus }: { incidents: Incident[]; onFocus: (ids: string[]) => void }) {
  return (
    <div className="thin-scroll flex-1 overflow-y-auto px-4 py-3" data-testid="memory">
      <p className="mb-3 text-[12px] leading-relaxed text-muted">
        Past incidents live in the same graph as the services they touched. The agent recalls them by traversal,
        so a repeat takes fewer steps.
      </p>
      <div className="flex flex-col divide-y divide-line">
        {incidents.map((i) => (
          <button key={i.uid}
                  onClick={() => onFocus([i.uid, ...(i.root_cause_uid ? [i.root_cause_uid] : []), ...i.affected.map((s) => `svc:${s}`)])}
                  className="-mx-2 rounded-md px-2 py-2 text-left hover:bg-raised">
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-[12px] text-ink">{i.id}</span>
              {i.learned && <span className="font-mono text-[10px] text-agent">learned</span>}
              <span className={`ml-auto font-mono text-[10.5px] ${i.status === "resolved" ? "text-ok"
                : i.status === "abandoned" ? "text-faint" : "text-warn"}`}>{i.status}</span>
            </div>
            <div className="text-[12.5px]">{i.title}</div>
            <div className="mt-0.5 truncate font-mono text-[10.5px] text-faint">
              {i.root_cause_uid ?? "no root cause"}{i.steps_taken ? ` · ${i.steps_taken} steps` : ""}
              {i.actions.length > 0 && ` · ${i.actions.map((a) => a.kind).join(", ")}`}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
