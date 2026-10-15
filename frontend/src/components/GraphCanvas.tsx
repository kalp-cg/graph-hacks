"use client";

import { forceCollide, forceX, forceY } from "d3-force";
import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods, type LinkObject, type NodeObject } from "react-force-graph-2d";
import { STATUS_COLOR, TYPE_COLOR, type Highlight } from "@/lib/graphStyle";
import type { GLink, GNode } from "@/lib/types";

type N = NodeObject<GNode>;
type L = LinkObject<GNode, GLink>;

interface Props {
  data: { nodes: GNode[]; links: GLink[] };
  highlight: Highlight;
  flashes: Map<string, number>;
  focus: { ids: string[]; key: number } | null;
  showContext: boolean;
  selected: string | null;
  onSelect: (node: GNode | null) => void;
}

const LAYER_Y: Record<string, number> = { edge: -300, business: -90, data: 170, platform: 300 };
const INFRA = new Set(["Service", "Database"]);
const RECENT_MS = 2 * 60 * 60 * 1000;
const CONTEXT_LINK = (t: string) => !["DEPENDS_ON", "READS_FROM", "WRITES_TO"].includes(t);

function endId(end: L["source"]): string {
  return typeof end === "object" && end ? String((end as N).id) : String(end);
}

function radius(n: N): number {
  if (n.type === "Service") return 4.5 + 20 * Math.sqrt(n.pagerank ?? 0.01);
  if (n.type === "Database") return 5;
  if (n.type === "Incident" || n.type === "Deployment") return 4.5;
  return 3.5;
}

function isLive(n: GNode, now: number): boolean {
  switch (n.type) {
    case "Alert":
      return true; // the snapshot only contains firing alerts
    case "Deployment":
      return (n.at ?? 0) >= now - RECENT_MS && n.status === "live";
    case "Action":
      return n.status === "pending";
    case "Incident":
      return n.status === "investigating" || n.status === "mitigating";
    default:
      return false;
  }
}

function shape(ctx: CanvasRenderingContext2D, n: N, r: number) {
  const x = n.x ?? 0;
  const y = n.y ?? 0;
  ctx.beginPath();
  switch (n.type) {
    case "Database": {
      ctx.roundRect(x - r, y - r * 0.8, r * 2, r * 1.6, r * 0.4);
      break;
    }
    case "Deployment":
    case "Incident": {
      ctx.moveTo(x, y - r * 1.3);
      ctx.lineTo(x + r * 1.3, y);
      ctx.lineTo(x, y + r * 1.3);
      ctx.lineTo(x - r * 1.3, y);
      ctx.closePath();
      break;
    }
    case "Alert": {
      ctx.moveTo(x, y - r * 1.4);
      ctx.lineTo(x + r * 1.3, y + r);
      ctx.lineTo(x - r * 1.3, y + r);
      ctx.closePath();
      break;
    }
    case "Team":
    case "Runbook": {
      ctx.rect(x - r, y - r, r * 2, r * 2);
      break;
    }
    default:
      ctx.arc(x, y, r, 0, 2 * Math.PI);
  }
}

export default function GraphCanvas({ data, highlight, flashes, focus, showContext, selected, onSelect }: Props) {
  const fg = useRef<ForceGraphMethods<N, L> | undefined>(undefined);
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const fitted = useRef(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!box.current) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(box.current);
    return () => ro.disconnect();
  }, []);

  // Top chokepoints by betweenness get a dashed ring.
  const chokepoints = useMemo(() => {
    const s = data.nodes.filter((n) => n.type === "Service").sort((a, b) => (b.betweenness ?? 0) - (a.betweenness ?? 0));
    return new Set(s.slice(0, 5).map((n) => n.id));
  }, [data]);

  useEffect(() => {
    const g = fg.current;
    if (!g) return;
    g.d3Force("y", forceY<N>((n) => (n.layer ? LAYER_Y[n.layer] ?? 0 : n.type === "Database" ? 380 : 0))
      .strength((n) => (INFRA.has(n.type) ? 0.22 : 0)));
    g.d3Force("collide", forceCollide<N>((n) => radius(n) + 4));
    g.d3Force("x", forceX<N>(0).strength((n) => (INFRA.has(n.type) ? 0.015 : 0)));
    const charge = g.d3Force("charge");
    charge?.strength?.((n: N) => (INFRA.has(n.type) ? -150 : -40));
    const link = g.d3Force("link");
    link?.distance?.((l: L) => (l.type === "DEPENDS_ON" ? 55 : 28));
    link?.strength?.((l: L) => (l.type === "DEPENDS_ON" ? 0.25 : l.type === "OWNS" ? 0.03 : 0.6));
    g.d3ReheatSimulation();
  }, [data]);

  useEffect(() => {
    if (!focus || !fg.current || focus.ids.length === 0) return;
    const ids = new Set(focus.ids);
    const t = setTimeout(() => {
      const pts = data.nodes.filter((n) => ids.has(n.id) && n.x !== undefined && n.y !== undefined);
      if (!pts.length || !fg.current) return;
      const xs = pts.map((n) => n.x!);
      const ys = pts.map((n) => n.y!);
      const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
      // Fit the step's nodes, but never zoom in so far that the surrounding graph disappears.
      const zoom = Math.max(0.7, Math.min(2.2, Math.min(size.w / (x1 - x0 + 260), size.h / (y1 - y0 + 220))));
      fg.current.centerAt((x0 + x1) / 2, (y0 + y1) / 2, 900);
      fg.current.zoom(zoom, 900);
    }, 60);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refocus only when asked to
  }, [focus]);

  const visible = (n: GNode) =>
    INFRA.has(n.type) || showContext || highlight.visited.has(n.id) || isLive(n, now) || n.id === selected;

  const nodeById = useMemo(() => new Map(data.nodes.map((n) => [n.id, n])), [data]);
  const linkVisible = (l: L) => {
    const s = nodeById.get(endId(l.source));
    const t = nodeById.get(endId(l.target));
    if (!s || !t || !visible(s) || !visible(t)) return false;
    if (l.type === "OWNS") return showContext || highlight.edges.has(l.id as string) ||
      (highlight.visited.has(s.id) && highlight.visited.has(t.id));
    return true;
  };

  const unhealthyTarget = (l: L) => {
    const t = nodeById.get(endId(l.target));
    return l.type === "DEPENDS_ON" && l.breaker !== "open" && t && t.status && t.status !== "healthy";
  };

  return (
    <div ref={box} className="absolute inset-0">
      <ForceGraph2D<GNode, GLink>
        ref={fg}
        width={size.w}
        height={size.h}
        graphData={data as { nodes: N[]; links: L[] }}
        backgroundColor="rgba(0,0,0,0)"
        autoPauseRedraw={false}
        cooldownTicks={180}
        d3VelocityDecay={0.35}
        minZoom={0.3}
        maxZoom={8}
        onEngineStop={() => {
          if (!fitted.current) {
            fitted.current = true;
            fg.current?.zoomToFit(700, 50, (n) => INFRA.has(n.type));
          }
        }}
        nodeVisibility={(n) => visible(n)}
        linkVisibility={linkVisible}
        nodeLabel={(n) => tooltip(n)}
        onNodeClick={(n) => onSelect(n)}
        onBackgroundClick={() => onSelect(null)}
        linkColor={(l) => {
          if (highlight.currentEdges.has(l.id as string)) return "rgba(34,211,238,0.95)";
          if (highlight.edges.has(l.id as string)) return "rgba(34,211,238,0.55)";
          if (l.breaker === "open") return "rgba(251,146,60,0.9)";
          if (unhealthyTarget(l)) return "rgba(239,68,68,0.45)";
          if (l.type === "DEPENDS_ON") return "rgba(148,163,184,0.16)";
          return "rgba(148,163,184,0.22)";
        }}
        linkWidth={(l) => (highlight.currentEdges.has(l.id as string) ? 2.6 : highlight.edges.has(l.id as string) ? 1.8
          : l.breaker === "open" ? 1.6 : unhealthyTarget(l) ? 1.2 : 0.6)}
        linkLineDash={(l) => (l.breaker === "open" ? [3, 3] : CONTEXT_LINK(l.type) ? [2, 2] : null)}
        linkDirectionalArrowLength={(l) => (l.type === "DEPENDS_ON" ? 2.5 : 0)}
        linkDirectionalArrowRelPos={0.92}
        linkDirectionalArrowColor={() => "rgba(148,163,184,0.35)"}
        linkDirectionalParticles={(l) => (highlight.edges.has(l.id as string) ? 3 : unhealthyTarget(l) ? 2 : 0)}
        linkDirectionalParticleWidth={(l) => (highlight.edges.has(l.id as string) ? 2.4 : 1.8)}
        linkDirectionalParticleSpeed={(l) => (highlight.edges.has(l.id as string) ? 0.012 : 0.006)}
        linkDirectionalParticleColor={(l) => (highlight.edges.has(l.id as string) ? "#67e8f9" : "#f87171")}
        nodeCanvasObject={(n, ctx, scale) => drawNode(n, ctx, scale, {
          highlight, flashes, chokepoint: chokepoints.has(n.id), selected: n.id === selected,
        })}
        nodePointerAreaPaint={(n, color, ctx) => {
          ctx.fillStyle = color;
          shape(ctx, n, radius(n) + 2);
          ctx.fill();
        }}
      />
    </div>
  );
}

function drawNode(n: N, ctx: CanvasRenderingContext2D, scale: number,
                  o: { highlight: Highlight; flashes: Map<string, number>; chokepoint: boolean; selected: boolean }) {
  const x = n.x ?? 0;
  const y = n.y ?? 0;
  const r = radius(n);
  const t = performance.now();
  const status = n.status ?? "healthy";
  const statusColor = n.type === "Service" || n.type === "Database" ? STATUS_COLOR[status] ?? "#10b981" : TYPE_COLOR[n.type];
  const visited = o.highlight.visited.has(n.id);
  const current = o.highlight.current.has(n.id);
  const unhealthy = (n.type === "Service" || n.type === "Database") && status !== "healthy";

  // Halo: pulsing for unhealthy services, steady for anything the agent touched.
  if (unhealthy) {
    const pulse = 0.5 + 0.5 * Math.sin(t / (status === "down" ? 180 : 320));
    ctx.beginPath();
    ctx.arc(x, y, r + 4 + pulse * 5, 0, 2 * Math.PI);
    ctx.fillStyle = status === "down" ? `rgba(239,68,68,${0.12 + pulse * 0.18})` : `rgba(245,158,11,${0.1 + pulse * 0.14})`;
    ctx.fill();
  }
  if (current) {
    const k = (t % 1400) / 1400;
    ctx.beginPath();
    ctx.arc(x, y, r + 3 + k * 14, 0, 2 * Math.PI);
    ctx.strokeStyle = `rgba(103,232,249,${0.9 * (1 - k)})`;
    ctx.lineWidth = 1.6 / Math.max(scale, 0.6);
    ctx.stroke();
  }
  const flashAt = o.flashes.get(n.id);
  if (flashAt) {
    const k = (Date.now() - flashAt) / 1800;
    if (k < 1) {
      ctx.beginPath();
      ctx.arc(x, y, r + 2 + k * 22, 0, 2 * Math.PI);
      ctx.strokeStyle = `rgba(52,211,153,${1 - k})`;
      ctx.lineWidth = 2.5 / Math.max(scale, 0.6);
      ctx.stroke();
    }
  }

  ctx.save();
  if (visited || unhealthy || o.selected) {
    ctx.shadowColor = visited ? "#22d3ee" : statusColor;
    ctx.shadowBlur = visited ? 14 : 10;
  }
  shape(ctx, n, r);
  ctx.fillStyle = n.type === "Service" && !unhealthy ? "rgba(16,185,129,0.28)" : statusColor + (n.type === "Service" ? "dd" : "cc");
  ctx.fill();
  ctx.lineWidth = (visited ? 1.8 : 1.1) / Math.max(scale, 0.7);
  ctx.strokeStyle = visited ? "#a5f3fc" : o.selected ? "#ffffff" : statusColor;
  ctx.stroke();
  ctx.restore();

  if (o.chokepoint && n.type === "Service") {
    ctx.beginPath();
    ctx.setLineDash([2, 2]);
    ctx.arc(x, y, r + 3, 0, 2 * Math.PI);
    ctx.strokeStyle = "rgba(226,232,240,0.45)";
    ctx.lineWidth = 0.8 / Math.max(scale, 0.7);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  const isInfra = n.type === "Service" || n.type === "Database";
  const named = n.type === "Deployment" || n.type === "Person";
  const showLabel = current || unhealthy || o.selected || ((isInfra || named) && visited) || (isInfra && scale > 1.5) ||
    (n.type === "Service" && (n.pagerank ?? 0) > 0.04 && scale > 0.8) || (!isInfra && scale > 2.2);
  if (showLabel) {
    const fontSize = Math.max(10 / scale, 2.2);
    ctx.font = `${visited || unhealthy ? 600 : 400} ${fontSize}px ui-sans-serif, system-ui`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const label = n.label.length > 32 ? n.label.slice(0, 31) + "…" : n.label;
    ctx.fillStyle = "rgba(2,6,23,0.75)";
    const w = ctx.measureText(label).width;
    ctx.fillRect(x - w / 2 - 1.5, y + r + 2, w + 3, fontSize + 2);
    ctx.fillStyle = visited ? "#cffafe" : unhealthy ? (status === "down" ? "#fecaca" : "#fde68a") : "#cbd5e1";
    ctx.fillText(label, x, y + r + 3);
  }
}

function tooltip(n: GNode): string {
  const rows: string[] = [`<b>${esc(n.label)}</b> <span style="opacity:.6">${n.type}</span>`];
  if (n.status) rows.push(`status: ${esc(n.status)}`);
  if (n.tier) rows.push(`tier: ${esc(n.tier)} · layer: ${esc(n.layer ?? "")}`);
  if (n.team) rows.push(`team: ${esc(n.team)}`);
  if (n.pagerank) rows.push(`pagerank: ${n.pagerank.toFixed(3)} · betweenness: ${(n.betweenness ?? 0).toFixed(1)}`);
  if (n.change_summary) rows.push(esc(n.change_summary));
  if (n.message && n.type === "Commit") rows.push(esc(n.message));
  if (n.metric) rows.push(`${esc(n.metric)} = ${n.value} (threshold ${n.threshold})`);
  if (n.title) rows.push(esc(n.title));
  if (n.reason) rows.push(esc(String(n.reason)));
  return `<div style="font:12px ui-sans-serif;line-height:1.45;max-width:280px">${rows.join("<br/>")}</div>`;
}

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
