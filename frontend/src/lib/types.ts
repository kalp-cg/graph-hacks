export type NodeType =
  | "Service" | "Database" | "Team" | "Person" | "Deployment" | "Commit"
  | "Alert" | "Incident" | "Runbook" | "Action" | "Page";

export interface GNode {
  id: string;
  type: NodeType;
  label: string;
  team?: string | null;
  name?: string;
  status?: string;
  tier?: string;
  layer?: string;
  version?: string;
  at?: number;
  message?: string;
  change_summary?: string;
  metric?: string;
  value?: number;
  threshold?: number;
  ref?: string;
  title?: string;
  summary?: string;
  steps_taken?: number;
  kind?: string;
  target?: string;
  outcome?: string;
  reason?: string;
  role?: string;
  engine?: string;
  learned?: boolean;
  pagerank?: number;
  betweenness?: number;
  x?: number;
  y?: number;
}

export interface GLink {
  id: string;
  source: string | GNode;
  target: string | GNode;
  type: string;
  breaker?: string;
}

export interface GraphData {
  nodes: GNode[];
  links: GLink[];
  at: number;
}

export interface Action {
  uid: string;
  kind: string;
  status: string;
  target: string;
  target_uid: string;
  reason?: string;
  risk?: string;
  outcome?: string | null;
  created_at?: number;
  run_id?: string;
}

export interface Scenario {
  name: string;
  title: string;
  alerts: string[];
}

export interface Incident {
  uid: string;
  id: string;
  title: string;
  status: string;
  summary?: string;
  steps_taken?: number;
  learned: boolean;
  root_cause_uid?: string;
  root_cause_service?: string;
  actions: { kind: string; status: string }[];
  similar_to: string[];
  affected: string[];
  opened_at?: number;
  resolved_at?: number;
}

export interface Health {
  falkordb: { ok: boolean; services?: number; error?: string };
  graph: string;
  llm: string;
  tools: string[];
  running: boolean;
}

export interface Step {
  id: string;
  name: string;
  args: Record<string, unknown>;
  t: number;
  done: boolean;
  summary?: string;
  error?: string | null;
  cypher?: string | null;
  ms?: number;
  node_uids: string[];
  edge_uids: string[];
}

export interface RunEvent {
  type: string;
  run_id?: string;
  t?: number;
  [key: string]: unknown;
}

export interface FinalEvent {
  report: string;
  provider: string;
  steps: number;
  seconds: number;
  root_cause: string | null;
  repeat_of: { id: string; title: string; steps_taken: number } | null;
  incident: { id: string; uid: string } | null;
  actions: Action[];
}
