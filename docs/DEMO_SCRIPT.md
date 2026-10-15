# Demo Video Script — SentinelGraph
**Target: 2:30 · Hard max: 3:00**
**Live URL: https://graph-hacks-alpha.vercel.app**

---

## Before You Hit Record

```bash
# Reset with memory preserved from a previous run
curl -X POST https://sentinelgraph-api-relh.onrender.com/api/reset?keep_memory=true
```

- Browser fullscreen, zoom 100%, no bookmarks bar
- Use headphones mic or a quiet room
- Practice once without recording

---

## Shot-by-Shot

### 0:00 – 0:12 | Opening — calm green graph

**On screen:** Full-screen dashboard. 38 green nodes, edges connecting them. Cost ticker shows $0/min.

**Say:**
> "It's 3 AM. Checkout is timing out. Fifty services, eight teams. What broke — and who fixes it?
> This is SentinelGraph, an incident commander that thinks in graphs."

---

### 0:12 – 0:22 | Inject the incident

**Action:** Click **"db-pool-exhaustion"** in the Break Production panel.

**On screen:** Three nodes flash red — `checkout-api`, `cart-service`, `orders-service`. Cost ticker climbs to ~$1,800/min.

**Say:**
> "Three services alert at once. The classic nightmare: multiple failures, one root cause — somewhere."

---

### 0:22 – 0:32 | Start investigation

**Action:** Click **"Investigate"**.

**On screen:** Agent Trail panel appears. First step: `recall_similar`.

**Say:**
> "The agent checks memory first — has the graph seen this pattern before?"

---

### 0:32 – 1:10 | Agent walks the graph

**On screen:** Steps stream in. Expand the `find_common_cause` step to show the Cypher query. The graph path glows from all three alerting services converging on `inventory-db-proxy`.

**Say:**
> "Then it asks FalkorDB: what do all three alerting services share downstream?
> A multi-hop graph traversal — variable-length paths across 38 services — finds one shared dependency.
> inventory-db-proxy.
> Every step shows its exact Cypher query. No hallucination — every claim comes from the graph."

*Pause one beat while the path pulses.*

> "Then: what changed there? A deploy six minutes ago. Version 4.2.0.
> 'Reduce max pool size to 10 to cut DB costs.' Author: Priya."

---

### 1:10 – 1:25 | Blast radius + chokepoints

**On screen:** `blast_radius` and `critical_services` steps. Nodes resize by PageRank. Dashed rings appear on chokepoints.

**Say:**
> "Betweenness centrality shows why this hurts: inventory-db-proxy sits on the path of 14 services.
> PageRank marks it critical. The graph already knew this was a single point of failure."

---

### 1:25 – 1:45 | Final report + action cards

**On screen:** Markdown report with cited node IDs. Two action cards below: Rollback and Page on-call.

**Say:**
> "The agent proposes two actions and cites every claim with a node ID.
> But it can't execute anything. A pending Action node sits in FalkorDB waiting for a human."

---

### 1:45 – 2:00 | Approve → recovery wave

**Action:** Click **Approve** on the rollback card.

**On screen:** Recovery spreads outward from `inventory-db-proxy` — callers turn green in dependency order. Cost ticker freezes, shows MTTR.

**Say:**
> "I approve. The rollback runs. Recovery propagates up the graph — callers come back once nothing below them is broken.
> MTTR: 84 seconds."

---

### 2:00 – 2:20 | Memory — second run is faster

**Action:** Inject same scenario again → Investigate.

**On screen:** Trail moves faster. Badge shows "6 steps · was 8 last time".

**Say:**
> "Now the second run. The agent finds the previous incident in memory — by graph traversal, not keyword search.
> Same root cause, same fix. Six steps instead of eight. 47 seconds instead of 67."

---

### 2:20 – 2:30 | Closing

**On screen:** Full green graph. Show URL.

**Say:**
> "SentinelGraph: graph-native incident response on FalkorDB.
> Every decision traces back to a Cypher query. Every fix needs a human.
> And it gets smarter with every incident."

---

## Optional Bonus Clip (15 s)

Press **`/`** or `Ctrl+K`, search for `secrets-vault`, click **Break → Bad Deploy**.
The agent has no script for this. Watch it work it out live from the graph.

**Say:**
> "That was a scripted scenario. Let's break something random. No script. The graph figures it out."

---

## Post-Production

- [ ] Speed up the agent thinking steps 1.5×–2× in editing to hit 2:30
- [ ] Add quiet instrumental background music
- [ ] Text readable at 720p (zoom the Cypher trail if needed)
- [ ] Upload YouTube **Unlisted** — test the link in incognito before pasting
