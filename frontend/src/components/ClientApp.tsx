"use client";

import dynamic from "next/dynamic";

// The dashboard is live data only (clock, WebSocket, canvas), so skip server prerendering.
const Dashboard = dynamic(() => import("./Dashboard"), {
  ssr: false,
  loading: () => <div className="flex h-full items-center justify-center text-sm text-slate-500">Loading SentinelGraph…</div>,
});

export default function ClientApp() {
  return <Dashboard />;
}
