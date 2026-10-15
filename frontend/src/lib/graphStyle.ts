/** Shared by the canvas (client-only) and the server-rendered UI around it. Mirrors the CSS palette. */
export interface Highlight {
  visited: Set<string>;
  current: Set<string>;
  edges: Set<string>;
  currentEdges: Set<string>;
}

export const C = {
  bg: "#0e0f12",
  ink: "#e7e8eb",
  muted: "#8b9099",
  faint: "#5d626c",
  line: "#24262b",
  ok: "#3ecf8e",
  warn: "#f0a92e",
  crit: "#f0524f",
  agent: "#7aa2ff",
  brand: "#ff7a45",
};

export const STATUS_COLOR: Record<string, string> = { healthy: C.ok, degraded: C.warn, down: C.crit };

export const TYPE_COLOR: Record<string, string> = {
  Service: C.ok, Database: "#9aa3b2", Team: "#6b7280", Person: "#6cb6ff", Deployment: "#b197fc",
  Commit: "#cdbcff", Alert: C.crit, Incident: "#f783ac", Runbook: "#63e6be", Action: "#e3b341", Page: "#6cb6ff",
};
