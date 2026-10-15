# How I Built an AI Incident Commander That Thinks in Graphs

*Built for the Graph Hacks: Context for AI Agents Hackathon (WeMakeDevs × FalkorDB)*

---

At 3 AM, three services break at once: `checkout-api`, `cart-service`, and `orders-service` all start timing out. The on-call engineer gets paged. They open five dashboards, grep through logs, and 45 minutes later—after digging through pull requests—they find it: someone reduced a connection pool size in a shared library that everything depends on.

This is the problem SentinelGraph solves. And it solves it in **under 90 seconds**, using a graph.

## Why a Graph Database and Not a Vector Search?

The first instinct when building an AI agent for incident response is to throw logs at a vector database and use semantic search to find "similar past incidents." It feels right. But it misses the most important question an engineer actually asks:

> *"What do all three broken services have in common?"*

This isn't a similarity question. It's a **path question**. You need to find the shared downstream dependency—the node that lies on the path from every alerting service to something broken. That's a multi-hop graph traversal, not a cosine similarity.

FalkorDB makes this a single Cypher query:

```cypher
MATCH (s:Service)-[:DEPENDS_ON*0..5]->(candidate:Service)
WHERE s.name IN $services AND candidate.status IN ['down', 'degraded']
WITH candidate, count(DISTINCT s) AS covering
WHERE covering = size($services)
RETURN candidate.name ORDER BY covering DESC
```

This finds every node reachable from *all* alerting services that is itself unhealthy—the shared root, not a symptom.

## The Architecture: Every Decision Is a Graph Query

SentinelGraph is built as a chain of tools exposed over **MCP (Model Context Protocol)**:

```
Browser (Next.js)
    ↕ REST + WebSocket
FastAPI backend
    ↕ MCP (stdio)
MCP Tool Server — 12 graph tools
    ↕ Cypher
FalkorDB (graph: "sentinel")
```

The agent is an MCP client. It discovers the available tools at startup with `list_tools`. It never touches the database directly—it goes through tools that always return a structured result with `{result, cypher, node_uids, edge_uids}`. The UI shows every Cypher query and lights up exactly the nodes and edges the agent touched, in order.

### The Graph Model

Everything lives in one FalkorDB graph called `sentinel`:

- **Services** are nodes with `status` (healthy/degraded/down), `tier`, and `layer`.
- **`DEPENDS_ON`** edges carry a `breaker` property (open/closed) for circuit breaker state.
- **`Deployment → Commit → Person`** tracks who pushed what and when.
- **`Incident → SIMILAR_TO → Incident`** is the memory layer—past postmortems linked to the services they touched.

The direction rule matters: `(checkout-api)-[:DEPENDS_ON]->(inventory-db-proxy)` means checkout *calls* the proxy. Failure flows *against* the arrow. Blast radius is a *reverse* traversal.

## The Investigation Protocol

The agent follows a deterministic protocol through 7 steps:

1. **`get_active_alerts`** — which services are firing?
2. **`find_common_cause`** — multi-hop traversal to find the deepest shared unhealthy dependency.
3. **`recall_similar`** — has the graph seen this pattern before? Two hops through `SIMILAR_TO` edges.
4. **`recent_changes`** — what was deployed in the last 60 minutes on the suspect service?
5. **`blast_radius`** + **`critical_services`** — how many services are at risk? Uses `algo.pageRank` and `algo.betweenness` from FalkorDB's built-in algorithms.
6. **`propose_action`** — draft a rollback, circuit breaker, or scale-up. Write it to the graph as `(:Action {status:'pending'})`. The agent can't execute anything.
7. **`conclude_investigation`** — write the incident back as memory.

A human clicks **Approve**. Only then does the backend execute the action and trigger graph-traversal-based recovery (callers recover once nothing below them is broken).

## The Killer Feature: Memory That Actually Works

Most agent memory systems store text embeddings and do semantic search. The problem is they match on *language*, not on *structure*.

SentinelGraph stores resolved incidents as nodes in the same FalkorDB graph, linked directly to the services and deployments they involved. When a new incident fires, the `recall_similar` tool does this:

```cypher
MATCH (s:Service)<-[:AFFECTED]-(i:Incident)-[:ROOT_CAUSE]->(d:Deployment)-[:DEPLOYED_TO]->(rc:Service)
WHERE s.name IN $services
WITH i, rc, count(DISTINCT s) AS overlap
RETURN i, rc ORDER BY overlap DESC, i.at DESC
LIMIT 5
```

It finds past incidents that affected the *same services in the graph*, not incidents that *sound* similar. If the root cause service matches the current suspect, the agent recognizes it as a repeat and skips straight to the fix.

**Measured result**: first run of `kafka-rebalance-storm`: **8 steps, 67 seconds**. Second run (with memory): **6 steps, 47 seconds**.

## Algorithms FalkorDB Provided Out of the Box

One of the reasons we chose FalkorDB over rolling our own graph layer is the built-in algorithm suite. We used four directly in production:

| Algorithm | Where |
| :--- | :--- |
| `algo.pageRank` | Node size in the UI; identifies which services are globally most central |
| `algo.betweenness` | Chokepoints tool; finds single points of failure with dashed rings in the UI |
| `algo.SPpaths` | `failure_path` tool; shortest weighted path from an alert to its root cause |
| Variable-length `DEPENDS_ON*0..5` | Blast radius, common cause, and memory recall |

These aren't decorative. The betweenness centrality result is what the agent cites when it says *"inventory-db-proxy sits on the path of 14 services; here is why this hurts so much."*

## What I Learned

**1. Graph traversal and LLM reasoning are complementary, not competing.**
The LLM is good at deciding *which* tool to call next and how to phrase a report. The graph is good at answering structural questions the LLM cannot reason about from text alone. Separating these cleanly through MCP made both better.

**2. Autopilot as a safety net is essential for live demos.**
Free LLM tiers have rate limits. We built a deterministic `Autopilot` fallback that implements the same investigation protocol without any model. It looks identical in the UI. If Groq hits a limit during the demo, the autopilot takes over mid-run without breaking anything.

**3. "Human in the loop" is a feature, not a limitation.**
Several people who saw the project said: "Why doesn't the agent just fix it automatically?" Because production is where your bad days happen. The approval gate is the point—you get the reasoning and the recommendation, but the action only runs after a human reviews it.

## Try It Live

- **Demo**: [https://graph-hacks-alpha.vercel.app](https://graph-hacks-alpha.vercel.app)
- **GitHub**: [https://github.com/kalp-cg/graph-hacks](https://github.com/kalp-cg/graph-hacks)
- **One-command local run**: `git clone ... && docker compose up`

Click **db-pool-exhaustion**, then **Investigate**, then **Approve**. The whole cycle completes in under 90 seconds. Then run it a second time and watch the memory shortcut kick in.

---

*Built during Graph Hacks: Context for AI Agents (WeMakeDevs × FalkorDB, Oct 15–18, 2026).*
