# SentinelGraph UI

Next.js 16 + `react-force-graph-2d`. Talks to the FastAPI backend over REST and one WebSocket.

```bash
cp .env.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8100
npm install
npm run dev -- -p 3001          # http://localhost:3001
```

- `src/components/Dashboard.tsx`: state, event handling, graph merge (positions survive refreshes)
- `src/components/GraphCanvas.tsx`: the canvas (status halos, agent path, particles, camera)
- `src/components/AgentTrail.tsx`: step trail with Cypher, final report, memory list
- `src/components/ControlPanel.tsx`: scenarios, alerts, provider, approval cards
- `src/lib/useRunSocket.ts`: WebSocket + run-state reducer
