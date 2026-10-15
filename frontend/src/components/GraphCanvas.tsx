"use client";

import { forceCollide, forceX, forceY } from "d3-force";
import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods, type LinkObject, type NodeObject } from "react-force-graph-2d";
import { C, STATUS_COLOR, TYPE_COLOR, type Highlight } from "@/lib/graphStyle";
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
  onMenu: (node: GNode, x: number, y: number) => void;
}

const LAYER_Y: Record<string, number> = { edge: -340, business: -100, data: 170, platform: 340 };
const INFRA = new Set(["Service", "Database"]);
const RECENT_MS = 2 * 60 * 60 * 1000;
const CONTEXT_LINK = (t: string) => !["DEPENDS_ON", "READS_FROM", "WRITES_TO"].includes(t);

function endId(end: L["source"]): string {
  return typeof end === "object" && end ? String((end as N).id) : String(end);
}

function radius(n: N): number {
  if (n.type === "Service") return 5.5 + 22 * Math.sqrt(n.pagerank ?? 0.01);
  if (n.type === "Database") return 5;
  if (n.type === "Incident" || n.type === "Deployment") return 4.5;
  return 3.5;
}

function isLive(n: GNode, now: number): boolean {
  switch (n.type) {
    case "Alert":
      return n.status !== "resolved"; // the snapshot only has firing alerts; approvals resolve them locally
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

export default function GraphCanvas({ data, highlight, flashes, focus, showContext, selected, onSelect, onMenu }: Props) {
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
      .strength((n) => (INFRA.has(n.type) ? 0.3 : 0)));
    g.d3Force("collide", forceCollide<N>((n) => radius(n) + 4));
    g.d3Force("x", forceX<N>(0).strength((n) => (INFRA.has(n.type) ? 0.015 : 0)));
    const charge = g.d3Force("charge");
    charge?.strength?.((n: N) => (INFRA.has(n.type) ? -320 : -40));
    const link = g.d3Force("link");
    link?.distance?.((l: L) => (l.type === "DEPENDS_ON" ? 80 : 30));
    link?.strength?.((l: L) => (l.type === "DEPENDS_ON" ? 0.12 : l.type === "OWNS" ? 0.02 : 0.6));
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
            fg.current?.zoomToFit(700, 70, (n) => INFRA.has(n.type));
          }
        }}
        nodeVisibility={(n) => visible(n)}
        linkVisibility={linkVisible}
        nodeLabel={(n) => tooltip(n)}
        onNodeClick={(n) => onSelect(n)}
        onNodeRightClick={(n, ev) => {
          const r = box.current?.getBoundingClientRect();
          onMenu(n, ev.clientX - (r?.left ?? 0), ev.clientY - (r?.top ?? 0));
        }}
        onBackgroundClick={() => onSelect(null)}
        linkColor={(l) => {
          const id = l.id as string;
          if (highlight.currentEdges.has(id)) return "rgba(122,162,255,0.95)";
          if (highlight.edges.has(id)) return "rgba(122,162,255,0.6)";
          if (l.breaker === "open") return "rgba(240,169,46,0.85)";
          if (unhealthyTarget(l)) return "rgba(240,82,79,0.4)";
          if (l.type === "DEPENDS_ON") return "rgba(139,144,153,0.16)";
          return "rgba(139,144,153,0.22)";
        }}
        linkWidth={(l) => (highlight.currentEdges.has(l.id as string) ? 2.2 : highlight.edges.has(l.id as string) ? 1.5
          : l.breaker === "open" ? 1.4 : unhealthyTarget(l) ? 1 : 0.6)}
        linkLineDash={(l) => (l.breaker === "open" ? [4, 3] : CONTEXT_LINK(l.type) ? [2, 2] : null)}
        linkDirectionalArrowLength={(l) => (l.type === "DEPENDS_ON" ? 2.5 : 0)}
        linkDirectionalArrowRelPos={0.92}
        linkDirectionalArrowColor={() => "rgba(139,144,153,0.35)"}
        linkDirectionalParticles={(l) => (highlight.edges.has(l.id as string) ? 2 : unhealthyTarget(l) ? 1 : 0)}
        linkDirectionalParticleWidth={(l) => (highlight.edges.has(l.id as string) ? 2 : 1.6)}
        linkDirectionalParticleSpeed={(l) => (highlight.edges.has(l.id as string) ? 0.01 : 0.005)}
        linkDirectionalParticleColor={(l) => (highlight.edges.has(l.id as string) ? C.agent : C.crit)}
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
  const lw = (w: number) => w / Math.max(scale, 0.7);
  const isInfra = n.type === "Service" || n.type === "Database";
  const status = n.status ?? "healthy";
  const unhealthy = isInfra && status !== "healthy";
  const color = isInfra ? STATUS_COLOR[status] ?? C.ok : TYPE_COLOR[n.type];
  const visited = o.highlight.visited.has(n.id);
  const current = o.highlight.current.has(n.id);

  // Only real failures move: a slow, soft pulse ring.
  if (unhealthy) {
    const k = (t % (status === "down" ? 1300 : 2000)) / (status === "down" ? 1300 : 2000);
    ctx.beginPath();
    ctx.arc(x, y, r + 2 + k * 9, 0, 2 * Math.PI);
    ctx.strokeStyle = status === "down" ? `rgba(240,82,79,${0.55 * (1 - k)})` : `rgba(240,169,46,${0.45 * (1 - k)})`;
    ctx.lineWidth = lw(1.5);
    ctx.stroke();
  }
  if (current) {
    ctx.beginPath();
    ctx.arc(x, y, r + 4, 0, 2 * Math.PI);
    ctx.strokeStyle = `rgba(122,162,255,${0.5 + 0.4 * Math.sin(t / 220)})`;
    ctx.lineWidth = lw(1.5);
    ctx.stroke();
  }
  const flashAt = o.flashes.get(n.id);
  if (flashAt) {
    const k = (Date.now() - flashAt) / 1600;
    if (k < 1) {
      ctx.beginPath();
      ctx.arc(x, y, r + 2 + k * 16, 0, 2 * Math.PI);
      ctx.strokeStyle = `rgba(62,207,142,${0.9 * (1 - k)})`;
      ctx.lineWidth = lw(2);
      ctx.stroke();
    }
  }

  shape(ctx, n, r);
  if (n.type === "Service") {
    ctx.fillStyle = unhealthy ? color : "#16241e";
  } else if (n.type === "Database") {
    ctx.fillStyle = unhealthy ? color : "#1c1f25";
  } else {
    ctx.fillStyle = color;
  }
  ctx.fill();
  ctx.lineWidth = lw(visited || o.selected ? 1.8 : 1);
  ctx.strokeStyle = o.selected ? C.ink : visited ? C.agent : isInfra ? color : "rgba(0,0,0,0.4)";
  ctx.stroke();

  if (o.chokepoint && n.type === "Service") {
    ctx.beginPath();
    ctx.setLineDash([2, 2]);
    ctx.arc(x, y, r + 2.5, 0, 2 * Math.PI);
    ctx.strokeStyle = "rgba(231,232,235,0.35)";
    ctx.lineWidth = lw(0.8);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  const named = n.type === "Deployment" || n.type === "Person";
  const showLabel = current || unhealthy || o.selected || ((isInfra || named) && visited) ||
    (n.type === "Service" && scale > 0.95) || (isInfra && scale > 1.5) ||
    (n.type === "Service" && (n.pagerank ?? 0) > 0.04 && scale > 0.8) || (!isInfra && scale > 2.2);
  if (!showLabel) return;
  const strong = visited || unhealthy || o.selected;
  const fontSize = Math.max(10.5 / scale, 2.2);
  ctx.font = `${strong ? 600 : 400} ${fontSize}px ui-sans-serif, system-ui`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const label = n.label.length > 30 ? n.label.slice(0, 29) + "…" : n.label;
  ctx.fillStyle = "rgba(14,15,18,0.8)";
  const w = ctx.measureText(label).width;
  ctx.fillRect(x - w / 2 - 1.5, y + r + 2.5, w + 3, fontSize + 1.5);
  ctx.fillStyle = unhealthy ? (status === "down" ? "#ff9b99" : "#f7c873") : visited ? "#c8d3ff" : strong ? C.ink : "#a3a8b1";
  ctx.fillText(label, x, y + r + 3);
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
