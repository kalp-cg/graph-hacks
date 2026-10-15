"use client";

import {
  AlertOctagon, Brain, ChevronDown, ChevronRight, Database, FileText, GitCommitHorizontal, History, Loader2,
  Network, Search, Share2, Sparkles, Users, Wrench, Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { RunState } from "@/lib/useRunSocket";
import type { Incident, Step } from "@/lib/types";

const TOOL_ICON: Record<string, React.ReactNode> = {
  get_active_alerts: <AlertOctagon className="h-3.5 w-3.5 text-rose-300" />,
  find_common_cause: <Network className="h-3.5 w-3.5 text-cyan-300" />,
  recent_changes: <GitCommitHorizontal className="h-3.5 w-3.5 text-violet-300" />,
  recall_similar: <History className="h-3.5 w-3.5 text-fuchsia-300" />,
  get_service_context: <Users className="h-3.5 w-3.5 text-sky-300" />,
  blast_radius: <Zap className="h-3.5 w-3.5 text-amber-300" />,
  trace_dependencies: <Share2 className="h-3.5 w-3.5 text-cyan-300" />,
  critical_services: <Sparkles className="h-3.5 w-3.5 text-emerald-300" />,
  chokepoints: <Sparkles className="h-3.5 w-3.5 text-emerald-300" />,
  failure_path: <Search className="h-3.5 w-3.5 text-cyan-300" />,
  propose_action: <Wrench className="h-3.5 w-3.5 text-yellow-300" />,
  conclude_investigation: <FileText className="h-3.5 w-3.5 text-slate-300" />,
};

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
    <aside className="glass flex w-[400px] shrink-0 flex-col overflow-hidden rounded-xl">
      <div className="flex border-b border-slate-700/50 text-[12px]">
        {(["trail", "memory"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
                  className={`flex flex-1 items-center justify-center gap-1.5 py-2.5 font-medium ${tab === t
                    ? "border-b-2 border-cyan-400 text-cyan-200" : "text-slate-400 hover:text-slate-200"}`}>
            {t === "trail" ? <><Brain className="h-3.5 w-3.5" /> Investigation</> : <><Database className="h-3.5 w-3.5" /> Memory ({incidents.length})</>}
          </button>
        ))}
      </div>

      {tab === "trail" ? (
        <div className="scroll-thin flex-1 overflow-y-auto p-3">
          {!run.runId && !run.final && (
            <div className="mt-10 px-4 text-center text-[12px] leading-relaxed text-slate-500">
              Inject an incident, then press <b className="text-slate-300">Investigate</b>.<br />
              Every step the agent takes shows up here with the exact Cypher it ran, and lights up on the graph.
            </div>
          )}
          {run.runId && (
            <div className="mb-2 flex items-center justify-between text-[11px] text-slate-400">
              <span className="truncate">model: <span className="text-slate-200">{run.provider}</span></span>
              <span>{run.steps.length} steps{run.incidentId ? ` · ${run.incidentId}` : ""}</span>
            </div>
          )}
          {run.fallback && (
            <div className="mb-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-200">
              ⚠ {run.fallback}
            </div>
          )}
          <ol className="relative flex flex-col gap-1.5">
            {run.steps.map((s, i) => (
              <StepRow key={s.id} step={s} n={i + 1} active={activeStep === s.id}
                       onClick={() => onStep(activeStep === s.id ? null : s)} />
            ))}
          </ol>
          {run.running && (
            <div className="mt-2 flex items-center gap-2 text-[12px] text-cyan-300/80">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> {run.steps.length === 0 ? "reading the graph…" : "thinking…"}
            </div>
          )}
          {run.error && (
            <div className="mt-2 rounded-md border border-red-500/40 bg-red-500/10 p-2 text-[12px] text-red-200">{run.error}</div>
          )}
          {run.final && (
            <div className="slidein mt-3 rounded-lg border border-cyan-500/25 bg-cyan-500/[0.04] p-3">
              <div className="mb-2 flex flex-wrap items-center gap-1.5 text-[10px]">
                <Badge>{run.final.steps} steps</Badge>
                <Badge>{run.final.seconds}s</Badge>
                {run.final.repeat_of ? (
                  <Badge tone="fuchsia">repeat of {run.final.repeat_of.id} · last time {run.final.repeat_of.steps_taken} steps</Badge>
                ) : run.final.root_cause ? <Badge tone="fuchsia">new memory stored</Badge> : null}
                {run.final.root_cause && (
                  <button onClick={() => onFocus([`svc:${run.final!.root_cause}`])}><Badge tone="red">root cause: {run.final.root_cause}</Badge></button>
                )}
              </div>
              <div className="report text-[12.5px] leading-relaxed text-slate-300">
                <ReactMarkdown>{run.final.report}</ReactMarkdown>
              </div>
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

function StepRow({ step, n, active, onClick }: { step: Step; n: number; active: boolean; onClick: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <li className={`slidein rounded-lg border px-2.5 py-2 transition ${active ? "border-cyan-400/60 bg-cyan-400/10"
      : "border-slate-700/50 bg-slate-900/40 hover:border-slate-600"}`}>
      <button onClick={onClick} className="w-full text-left">
        <div className="flex items-center gap-2">
          <span className="w-4 text-right font-mono text-[10px] text-slate-500">{n}</span>
          {TOOL_ICON[step.name] ?? <Wrench className="h-3.5 w-3.5" />}
          <span className="font-mono text-[12px] text-slate-100">{step.name}</span>
          {!step.done ? <Loader2 className="ml-auto h-3 w-3 animate-spin text-cyan-300" />
            : <span className="ml-auto font-mono text-[10px] text-slate-500">{step.ms} ms · {step.node_uids.length} nodes</span>}
        </div>
        {Object.keys(step.args).length > 0 && (
          <div className="mt-0.5 truncate pl-6 font-mono text-[10.5px] text-slate-500">
            {Object.entries(step.args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join("  ")}
          </div>
        )}
        {step.summary && (
          <div className={`mt-1 pl-6 text-[12px] ${step.error ? "text-amber-300" : "text-slate-300"}`}>{step.summary}</div>
        )}
      </button>
      {step.cypher && (
        <div className="pl-6">
          <button onClick={() => setOpen(!open)} className="mt-1 flex items-center gap-0.5 text-[10.5px] text-cyan-400/80 hover:text-cyan-300">
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />} Cypher
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
  const parts = pretty.split(TOKENS);
  return (
    <pre className="scroll-thin mt-1 max-h-56 overflow-auto whitespace-pre-wrap rounded-md border border-slate-700/50 bg-slate-950/80 p-2 font-mono text-[10.5px] leading-relaxed text-slate-300">
      {parts.map((p, i) =>
        p.startsWith("$") ? <span key={i} className="text-amber-300">{p}</span>
          : p.startsWith("'") ? <span key={i} className="text-emerald-300">{p}</span>
          : p.startsWith("algo.") ? <span key={i} className="font-semibold text-fuchsia-300">{p}</span>
          : IS_KW.test(p) ? <span key={i} className="text-cyan-300">{p}</span>
          : <span key={i}>{p}</span>)}
    </pre>
  );
}

function MemoryList({ incidents, onFocus }: { incidents: Incident[]; onFocus: (ids: string[]) => void }) {
  return (
    <div className="scroll-thin flex-1 overflow-y-auto p-3">
      <p className="mb-2 text-[11px] leading-relaxed text-slate-500">
        Past incidents live in the same graph as the services they touched. The agent recalls them by traversal
        (<span className="font-mono text-slate-400">recall_similar</span>), so a repeat takes fewer steps.
      </p>
      <div className="flex flex-col gap-1.5">
        {incidents.map((i) => (
          <button key={i.uid} onClick={() => onFocus([i.uid, ...(i.root_cause_uid ? [i.root_cause_uid] : []), ...i.affected.map((s) => `svc:${s}`)])}
                  className="rounded-lg border border-slate-700/50 bg-slate-900/40 p-2 text-left hover:border-fuchsia-400/40">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-[12px] text-fuchsia-200">{i.id}</span>
              {i.learned && <Badge tone="fuchsia">learned</Badge>}
              <span className={`ml-auto text-[10px] uppercase ${i.status === "resolved" ? "text-emerald-400"
                : i.status === "abandoned" ? "text-slate-500" : "text-amber-300"}`}>{i.status}</span>
            </div>
            <div className="text-[12px] text-slate-200">{i.title}</div>
            <div className="mt-0.5 text-[11px] text-slate-400">
              root cause <span className="font-mono text-slate-300">{i.root_cause_uid ?? "?"}</span>
              {i.steps_taken ? ` · ${i.steps_taken} steps` : ""}
              {i.actions.length > 0 && ` · ${i.actions.map((a) => a.kind).join(", ")}`}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function Badge({ children, tone = "slate" }: { children: React.ReactNode; tone?: "slate" | "fuchsia" | "red" }) {
  const cls = tone === "fuchsia" ? "border-fuchsia-400/30 bg-fuchsia-400/10 text-fuchsia-200"
    : tone === "red" ? "border-red-400/30 bg-red-400/10 text-red-200" : "border-slate-600/60 bg-slate-800/60 text-slate-300";
  return <span className={`rounded border px-1.5 py-0.5 ${cls}`}>{children}</span>;
}
