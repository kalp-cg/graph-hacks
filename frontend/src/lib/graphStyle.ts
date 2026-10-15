/** Shared by the canvas (client-only) and the server-rendered UI around it. */
export interface Highlight {
  visited: Set<string>;
  current: Set<string>;
  edges: Set<string>;
  currentEdges: Set<string>;
}

export const STATUS_COLOR: Record<string, string> = {
  healthy: "#10b981", degraded: "#f59e0b", down: "#ef4444",
};

export const TYPE_COLOR: Record<string, string> = {
  Service: "#10b981", Database: "#94a3b8", Team: "#64748b", Person: "#38bdf8", Deployment: "#a78bfa",
  Commit: "#c4b5fd", Alert: "#fb7185", Incident: "#e879f9", Runbook: "#2dd4bf", Action: "#facc15", Page: "#7dd3fc",
};
