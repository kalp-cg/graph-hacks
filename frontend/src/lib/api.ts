import type { Action, GraphData, Health, Incident, Scenario } from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100").replace(/\/$/, "");
export const WS_URL = API_BASE.replace(/^http/, "ws") + "/ws";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not json */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => call<Health>("/api/health"),
  graph: () => call<GraphData>("/api/graph"),
  scenarios: () => call<Scenario[]>("/api/scenarios"),
  incidents: () => call<Incident[]>("/api/incidents"),
  actions: (status?: string) => call<Action[]>("/api/actions" + (status ? `?status=${status}` : "")),
  inject: (name: string) => call<{ alerting_services: string[] }>(`/api/scenarios/${name}`, { method: "POST" }),
  reset: (keepMemory = true) => call(`/api/reset?keep_memory=${keepMemory}`, { method: "POST" }),
  run: (provider?: string, question?: string) =>
    call<{ run_id: string }>("/api/runs", {
      method: "POST",
      body: JSON.stringify({ provider: provider || null, ...(question ? { question } : {}) }),
    }),
  approve: (uid: string) => call<Record<string, unknown>>(`/api/actions/${uid}/approve`, { method: "POST" }),
  reject: (uid: string) => call<Action>(`/api/actions/${uid}/reject`, { method: "POST" }),
};
