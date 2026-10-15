"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { WS_URL } from "./api";
import type { Action, FinalEvent, RunEvent, Step } from "./types";

export interface RunState {
  runId: string | null;
  provider: string | null;
  running: boolean;
  steps: Step[];
  thoughts: { t: number; text: string }[];
  proposed: Action[];
  final: FinalEvent | null;
  error: string | null;
  fallback: string | null;
  incidentId: string | null;
  startedAt: number | null;
}

const empty: RunState = {
  runId: null, provider: null, running: false, steps: [], thoughts: [], proposed: [],
  final: null, error: null, fallback: null, incidentId: null, startedAt: null,
};

function reduce(state: RunState, e: RunEvent): RunState {
  switch (e.type) {
    case "run_started":
      return {
        ...empty, runId: e.run_id ?? null, running: true, provider: String(e.provider ?? ""),
        incidentId: (e.incident as { id?: string } | null)?.id ?? null, startedAt: Date.now() - (e.t ?? 0) * 1000,
      };
    case "thought":
      return { ...state, thoughts: [...state.thoughts, { t: e.t ?? 0, text: String(e.text) }] };
    case "tool_call":
      return {
        ...state,
        steps: [...state.steps, {
          id: String(e.id), name: String(e.name), args: (e.args as Record<string, unknown>) ?? {},
          t: e.t ?? 0, done: false, node_uids: [], edge_uids: [],
        }],
      };
    case "tool_result":
      return {
        ...state,
        steps: state.steps.map((s) => s.id === e.id ? {
          ...s, done: true, summary: String(e.summary ?? ""), error: (e.error as string) ?? null,
          cypher: (e.cypher as string) ?? null, ms: Number(e.ms ?? 0),
          node_uids: (e.node_uids as string[]) ?? [], edge_uids: (e.edge_uids as string[]) ?? [],
        } : s),
      };
    case "action_proposed":
      return { ...state, proposed: [...state.proposed, e.action as Action] };
    case "provider_fallback":
      return { ...state, fallback: `${e.from} failed (${String(e.reason).slice(0, 80)}). ${e.to} took over.`, provider: String(e.to) };
    case "final":
      return { ...state, running: false, final: e as unknown as FinalEvent };
    case "error":
      return { ...state, running: false, error: String(e.message ?? "run failed") };
    case "scenario_started":
      return { ...empty };
    default:
      return state;
  }
}

type Action_ = { kind: "event"; e: RunEvent } | { kind: "replace"; events: RunEvent[] };

function reducer(state: RunState, a: Action_): RunState {
  if (a.kind === "replace") return a.events.reduce(reduce, { ...empty });
  return reduce(state, a.e);
}

/** One WebSocket for everything. `onEvent` sees every event (graph_update, action_executed, ...). */
export function useRunSocket(onEvent: (e: RunEvent) => void) {
  const [run, dispatch] = useReducer(reducer, empty);
  const [connected, setConnected] = useState(false);
  const handler = useRef(onEvent);
  useEffect(() => {
    handler.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let closedByUs = false; // lesson: never reconnect after unmount (duplicate sockets in dev)
    let retry: ReturnType<typeof setTimeout> | undefined;
    let ping: ReturnType<typeof setInterval> | undefined;

    const open = () => {
      socket = new WebSocket(WS_URL);
      socket.onopen = () => {
        setConnected(true);
        ping = setInterval(() => socket?.readyState === WebSocket.OPEN && socket.send("ping"), 20000);
      };
      socket.onmessage = (msg) => {
        const e = JSON.parse(msg.data) as RunEvent;
        if (e.type === "hello") {
          dispatch({ kind: "replace", events: (e.history as RunEvent[]) ?? [] });
        } else {
          dispatch({ kind: "event", e });
        }
        handler.current(e);
      };
      socket.onclose = () => {
        setConnected(false);
        clearInterval(ping);
        if (!closedByUs) retry = setTimeout(open, 1500);
      };
    };
    open();
    return () => {
      closedByUs = true;
      clearTimeout(retry);
      clearInterval(ping);
      socket?.close();
    };
  }, []);

  const clear = useCallback(() => dispatch({ kind: "replace", events: [] }), []);
  return { run, connected, clear };
}
