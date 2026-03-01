# PROPOSAL: Alive Infrastructure Roadmap

**Date:** 2026-03-01
**Status:** DRAFT (rev 7 — added verification tests)
**Sources:** [HKUDS/nanobot](https://github.com/HKUDS/nanobot) patterns + [OpenClaw](https://github.com/openclaw/openclaw) gateway architecture

---

## Context

5 users, 5 agents needed. Current infra: manual port allocation, nginx regen shell scripts, Lounge polling each agent port individually, no config validation, `heartbeat_server.py` is a 1,741-line monolith mixing transports with orchestration. These compound into daily ops friction.

This proposal combines two previously separate proposals into a single sequenced roadmap:
- Nanobot-inspired: deploy ergonomics + event bus (intra-process)
- OpenClaw-inspired: gateway control plane (inter-process)

Skills extensibility (declarative YAML actions) is **parked** — useful but not blocking at 5 agents.

---

## Decisions (from review)

| Question | Decision |
|----------|----------|
| Backward compat for existing `/agent_id/...` URLs from create scripts? | Yes — Gateway Phase 3.1 runs in parallel with port-based routing. Full cutover only after all URLs work through Gateway. |
| Gateway mandatory or optional? | Optional for one full release cycle. `GATEWAY_URL` env var opts in. Standalone mode (direct port) remains default until Phase 3.2 cutover. |
| Canonical ops artifacts: `scripts/` vs `tasks/lounge-deploy/`? | `scripts/` is canonical. `tasks/lounge-deploy/` contains the original deploy runbook (reference only). Phase 1B updates only `scripts/create_agent.sh`. |

---

## Roadmap

| Phase | What | Scope | Depends On |
|-------|------|-------|------------|
| 1 | Deploy Ergonomics | S (2-3 days) | Nothing |
| 2 | Event Bus (intra-process) | L (7-9 days) | Nothing |
| 3 | Gateway (inter-process) | M (6-8 days) | Phase 2 patterns |
| **Total** | | **15-20 days** | |

---

## Phase 1: Deploy Ergonomics

**Problem:** Startup failures are lazy and cryptic. `create_agent.sh` isn't idempotent. No system diagnostic.

### 1A. `engine/preflight.py` — Startup validation (~150 lines)

Runs synchronously before `db.init_db()` in `heartbeat_server.py:start()`. Checks:
- `OPENROUTER_API_KEY` set and non-empty
- `SHOPKEEPER_SERVER_TOKEN` set
- If `AGENT_CONFIG_DIR` set: dir exists, `identity.yaml` parses, `alive_config.yaml` parses, `db/` writable
- Port not already in use (socket probe, 0.5s timeout)
- Python >= 3.12
- Required packages importable (aiosqlite, yaml, httpx)
- DB file not locked by another process

Output: numbered error list with fix instructions, or `Preflight OK`. Fail-loud, no wizard.

### 1B. Idempotent `scripts/create_agent.sh`

Add `--force` flag: if container exists, stop → update config → restart. Never deletes `db/` or `memory/` directories. Add `--validate` flag: run preflight without starting.

**Note:** Only `scripts/create_agent.sh` is modified. `tasks/lounge-deploy/create_agent.sh` is reference/history only.

### 1C. `scripts/doctor.py` — System diagnostic (~200 lines)

Checks all env vars, Docker image status, ports in use, DB integrity, disk space, container status for all agents. Operator runs it when something feels wrong.

### Files

| File | Action |
|------|--------|
| `engine/preflight.py` | CREATE |
| `engine/heartbeat_server.py` | MODIFY (~10 lines: add preflight call in `start()`) |
| `scripts/create_agent.sh` | MODIFY (~30 lines: `--force` + `--validate`) |
| `scripts/doctor.py` | CREATE |
| `tests/test_preflight.py` | CREATE |

### Risks
- Preflight too slow → all checks are <100ms
- `--force` destroys data → only replaces config files, never `db/` or `memory/`

---

## Phase 2: Event Bus (Intra-Process)

**Problem:** `heartbeat_server.py` mixes TCP, WebSocket, HTTP, cycle orchestration, client tracking, and chat history. Route handlers receive the entire `server` instance. Adding a new channel means threading callbacks through the monolith.

**Why before Gateway:** The bus establishes typed message patterns inside the agent. The Gateway (Phase 3) reuses these same message types for inter-process routing. Build the vocabulary first, then the router.

### What We Build

In-process async pub/sub. `asyncio.Queue`-backed topic routing with typed messages. Not Redis. Not NATS. Not external.

```
engine/bus.py        — EventBus class, BusMessage dataclass
engine/bus_types.py  — Typed payloads (InboundSpeech, OutboundDialogue, etc.)
```

**Enumerated topics:**

| Topic | Publisher | Subscribers |
|-------|-----------|-------------|
| `inbound.visitor_speech` | TCP, WS, API, Telegram, X | Heartbeat |
| `inbound.visitor_connect` | TCP, WS, API | Heartbeat, presence tracker |
| `inbound.visitor_disconnect` | TCP, WS, API | Heartbeat, presence tracker |
| `outbound.dialogue` | pipeline/body (via output) | WS broadcaster, TCP writer |
| `outbound.scene_update` | Heartbeat (post-cycle) | WS broadcaster |
| `outbound.status` | Heartbeat (sleep/wake) | WS, TCP |
| `cycle.complete` | Heartbeat | Replaces `_cycle_log_subscribers` |
| `stage.progress` | Heartbeat | Console logger, terminal MRI |

### Cycle log subscriber correctness (Finding #3)

**Problem:** The current `_cycle_log_subscribers` system is a per-visitor keyed queue. `public_routes.py:handle_chat()` subscribes with `visitor_id` as key, then `_wait_for_dialogue()` drains non-dialogue cycles and filters by `required_visitor_id`. A generic bounded topic bus with drop-oldest could lose the specific cycle log a chat handler is waiting for.

**Solution:** `cycle.complete` is NOT a generic broadcast topic. It uses **keyed subscriptions** — same semantics as today:

```python
# Bus supports keyed subscriptions for cycle.complete
bus.subscribe_keyed('cycle.complete', key=visitor_id) → asyncio.Queue
bus.unsubscribe_keyed('cycle.complete', key=visitor_id)

# Heartbeat publishes with key:
bus.publish_keyed('cycle.complete', key=log.get('visitor_id', '*'), payload=log)
# '*' key broadcasts to all keyed subscribers (for ambient/idle cycles)
```

This preserves the current guarantee: each chat handler gets its own queue, receives only cycle logs relevant to its visitor, and `_wait_for_dialogue()` continues to work unchanged. The bus just manages the queue lifecycle instead of Heartbeat doing it directly.

**Concurrent same-visitor race (rev2 Finding #2, rev6 Finding #1):** The current code has a pre-existing race: two concurrent `/api/chat` requests from the same `visitor_id` will call `subscribe_cycle_logs(visitor_id)` twice, and the second call overwrites the first queue (`heartbeat.py:1878-1879`). The bus gives each request its own subscription — but that alone doesn't prevent both requests from consuming the *same* dialogue log (duplicate responses).

**Full solution — serialize per visitor:**

```python
# Bus provides a per-visitor lock (asyncio.Lock keyed by visitor_id):
async with bus.visitor_lock(visitor_id):
    sub_id = bus.subscribe_keyed('cycle.complete', visitor_id=visitor_id)
    try:
        await heartbeat.schedule_microcycle()
        log = await _wait_for_dialogue(bus, sub_id, timeout=30)
    finally:
        bus.unsubscribe_keyed('cycle.complete', sub_id=sub_id)
```

The `visitor_lock` serializes the subscribe → schedule → wait → unsubscribe sequence per visitor. Two concurrent `/api/chat` requests for the same `visitor_id` queue: the first acquires the lock, triggers a microcycle, gets its dialogue, and releases. The second then acquires, triggers its own microcycle, and gets its own dialogue. No duplicate responses because each microcycle produces exactly one dialogue for one lock holder.

Different visitors are fully parallel (separate locks). The lock is an `asyncio.Lock` (not threading), so no deadlock risk in the single event loop.

**Keyed subscription details (unchanged):**

```python
# Each request gets its own subscription, even for the same visitor:
sub_id = bus.subscribe_keyed('cycle.complete', visitor_id=visitor_id)
# Returns unique sub_id like "sub-a1b2c3"

# Internally, bus maintains: visitor_id → set[sub_id] → Queue
# NOT prefix matching. Exact visitor_id lookup + explicit wildcard:
#   publish_keyed('cycle.complete', visitor_id='alice', payload=log)
#     → delivers to all subscriptions registered under exact key 'alice'
#   publish_keyed('cycle.complete', visitor_id='*', payload=log)
#     → delivers to ALL keyed subscriptions (for ambient/idle cycles)

bus.unsubscribe_keyed('cycle.complete', sub_id=sub_id)
```

This uses exact `visitor_id` matching (not string prefix) plus an explicit `'*'` wildcard for broadcast cycles. No risk of `alice` colliding with `alice2`. Combined with the per-visitor lock, this eliminates both the queue-overwrite bug (current) and the duplicate-response bug (previously unaddressed).

**Broadcast topics** (`outbound.scene_update`, `stage.progress`, etc.) use standard fan-out with bounded queues and drop-oldest — same as current `_window_broadcast` semantics, where losing a frame is acceptable.

### RequestContext adapter pattern (Finding #5)

**Problem:** Handlers and tests are built around `(server, writer, ...)`. Tests directly construct `ShopkeeperServer` and call internal methods. A signature rewrite has high blast radius.

**Solution:** Phase 2 sub-phase 3 uses an **adapter**, not a signature rewrite:

```python
# engine/api/request_context.py
class RequestContext:
    """Thin wrapper that delegates to server. Tests can mock this directly."""
    def __init__(self, server):
        self._server = server

    async def http_json(self, writer, status, body):
        await self._server._http_json(writer, status, body)

    @property
    def heartbeat(self):
        return self._server.heartbeat

    @property
    def bus(self):
        return self._server._bus
```

Existing handler signatures remain `(server, writer, ...)` during Phase 2. The `RequestContext` is introduced as an opt-in for new handlers and Gateway RPC handlers in Phase 3. Full migration from `server` to `ctx` is deferred — it's not blocking and can be done incrementally file-by-file.

### What changes

- `Heartbeat._window_broadcast` → `bus.publish('outbound.scene_update', ...)`
- `Heartbeat._stage_callback` → `bus.publish('stage.progress', ...)`
- `Heartbeat._cycle_log_subscribers` → `bus.subscribe_keyed('cycle.complete', ...)` with same per-visitor queue semantics
- TCP handler extracted to `engine/api/tcp.py`
- WS handler extracted to `engine/api/websocket.py`

### What does NOT change

- `window_state.py` builders (produce payloads, bus carries them)
- Pipeline stages (bus is transport layer, above the pipeline)
- DB layer
- Route handler signatures (adapter pattern, not rewrite)
- Any test behavior (sub-phase 1 uses compatibility shim)

### Files

| File | Action |
|------|--------|
| `engine/bus.py` | CREATE (EventBus with broadcast + keyed subscription modes) |
| `engine/bus_types.py` | CREATE |
| `engine/api/tcp.py` | CREATE (extracted from heartbeat_server.py) |
| `engine/api/websocket.py` | CREATE (extracted from heartbeat_server.py) |
| `engine/api/request_context.py` | CREATE (adapter, opt-in) |
| `engine/heartbeat.py` | MODIFY (~50 lines: replace callbacks with bus.publish) |
| `engine/heartbeat_server.py` | MODIFY (large: ~600 lines moved out, shrinks to ~500) |
| `tests/test_bus.py` | CREATE |

### Sub-phases

1. **Foundation (2-3 days):** Create `bus.py` (with both broadcast and keyed subscription modes), `bus_types.py`. Wire heartbeat to publish through bus. Keep old callbacks as bus subscribers (compatibility shim). All tests pass unchanged.
2. **Extraction (3-4 days):** Extract TCP and WS handlers to `engine/api/`. Both register as bus subscribers. `heartbeat_server.py` shrinks to ~500 lines.
3. **Cleanup (1-2 days):** Create `RequestContext` adapter. Integration tests for bus. Remove compatibility shims in heartbeat.

### Risks
- Message ordering → per-topic ordered delivery, single asyncio loop
- Chat response correctness → keyed subscriptions preserve per-visitor queue isolation (Finding #3)
- Test breakage → sub-phase 1 shim means zero test changes; adapter pattern avoids signature rewrite (Finding #5)
- Scope creep → hard constraint: in-process only, forever

---

## Phase 3: Gateway (Inter-Process)

**Problem:** 5 agents need port allocation, nginx regen, health polling, and have no way to talk to each other. Lounge dials DOWN to each agent port. Every agent create/destroy requires SSH + shell script.

**Key change:** Agents connect UP to the Gateway, not the other way around.

### Architecture

```
                    ┌──────────────────────────────────┐
                    │           NGINX                  │
                    │  alive.kaikk.jp → Lounge :3100   │
                    │  api.alive.kaikk.jp → Gateway    │
                    └──────────┬───────────────────────┘
                               │
                      ┌────────v────────┐
                      │    GATEWAY      │
                      │  (single proc)  │
                      │                 │
                      │  HTTP :8000     │  ← Lounge + public clients
                      │  WS   :8001    │  ← Agent pods + dashboards
                      │                 │
                      │  Agent Registry │
                      │  Message Router │
                      │  Health Monitor │
                      └───┬────┬────┬───┘
                          │    │    │
                ┌─────────┘    │    └─────────┐
                │              │              │
          ┌─────v─────┐ ┌─────v─────┐ ┌─────v─────┐
          │ Agent A    │ │ Agent B   │ │ Agent C   │
          │ (container)│ │(container)│ │(container)│
          │  WS client │ │ WS client │ │ WS client │
          └────────────┘ └───────────┘ └───────────┘
```

### Gateway Auth Contract (Findings #4, rev2-#1)

Current auth enforcement:
- **API keys**: `_check_api_key()` in `heartbeat_server.py:1638` validates Bearer tokens against `api_keys.json`
- **Dashboard tokens**: `check_dashboard_auth()` in `dashboard_routes.py:65` validates dashboard password

**Gateway auth model:**

1. **Agent → Gateway WS handshake:** Each agent gets a unique `GATEWAY_AGENT_TOKEN` generated at agent creation time (stored in agent's `.env`). The handshake includes both the token and the `agent_id`. Gateway validates that the token matches the registered `agent_id` — a compromised agent cannot impersonate another agent.

```python
# Agent handshake (gateway_client.py)
{
    "type": "handshake",
    "agent_id": "shopkeeper_main",
    "token": "gw-agent-a1b2c3d4...",   # unique per agent
    "capabilities": ["dashboard", "chat", "public-state"],
    "version": "1.0"
}

# Gateway validates: token_registry[agent_id] == token
# Rejects: unknown agent_id, token mismatch, duplicate agent_id already connected
```

**Token registry:** Gateway reads agent tokens from `/data/gateway/agent_tokens.json`. File format: `{"agent_id": "token", ...}`.

**Token lifecycle:**
- **Create:** `create_agent.sh --gateway` generates token, writes to agent `.env`, and appends to `agent_tokens.json` via atomic write (write to `.tmp`, `mv` to target — shell-safe).
- **Destroy:** `destroy_agent.sh` removes the agent's entry from `agent_tokens.json` (same atomic write pattern). Gateway auto-deregisters when the WS disconnects; stale token is harmless but cleaned up.
- **Rotate:** `scripts/rotate_agent_token.sh <agent_id>` — generates new token, updates both agent `.env` and `agent_tokens.json`, restarts agent container. Not in Phase 3 MVP but documented as future script.
- **Concurrency:** Token registry writes use `flock` + atomic file replacement. All registry mutations (create, destroy, rotate) acquire an exclusive lock on `/data/gateway/agent_tokens.lock` before read-modify-write, then write to `.tmp` in the same directory and `mv` to target. This prevents lost updates from concurrent `/api/agents` HTTP requests. Shell scripts use `flock /data/gateway/agent_tokens.lock -c '...'`. `docker-client.ts` calls the shell script (which handles locking), not the JSON file directly.

2. **Lounge → Gateway HTTP:** Gateway accepts Lounge requests with a `GATEWAY_ADMIN_TOKEN` (separate shared secret). This replaces Lounge's per-agent API key auth for routing purposes.

3. **Per-request auth propagation:** Gateway forwards the original `Authorization` header in the RPC envelope. The agent's `_check_api_key()` and `check_dashboard_auth()` still run inside the agent — Gateway does NOT replace agent-level auth. Gateway is a transparent proxy for auth, not an auth authority.

```python
# RPC envelope with auth propagation
{
    "id": "req-uuid",
    "method": "GET",
    "path": "/api/dashboard/vitals",
    "headers": {"Authorization": "Bearer sk-live-..."},  # passed through
    "body": null,
    "timeout": 10.0
}
```

### Lounge Migration Matrix (Findings #1, #2)

**The full scope of Lounge changes for Gateway cutover:**

| File | What Changes | Lines |
|------|-------------|-------|
| `lounge/src/lib/agent-client.ts` | All 11 functions: replace `http://127.0.0.1:${port}/...` with Gateway URL `http://127.0.0.1:8000/agents/${agentId}/...`. Port param removed from all signatures. | ~80 |
| `lounge/src/lib/types.ts` | `Agent.port` stays `port: number` (0 = Gateway-managed). Add `gateway_registered?: boolean`. | ~5 |
| `lounge/src/lib/manager-db.ts` | `createAgent()`: port param defaults to 0 in Gateway mode. `getNextPort()`: skips rows where `port=0`. No schema change. | ~15 |
| `lounge/src/app/api/agents/route.ts` | POST handler: stop requiring port in create flow. Use Gateway for health instead of direct port check. | ~15 |
| `lounge/src/app/api/agents/[id]/` | All sub-routes (dashboard proxy, chat, status, etc.): resolve agent via Gateway instead of DB port lookup. | ~40 |
| `lounge/src/components/` (if any direct port refs) | Search and replace any hardcoded port patterns. | ~10 |

**DB migration for `agents.port`:**

Keep `port INTEGER NOT NULL` — no schema change needed. Use sentinel value `0` for Gateway-managed agents. SQLite column nullability changes require table rebuild, which is unnecessary complexity. The TypeScript type becomes `port: number` (stays required, `0` means Gateway-managed). `getNextPort()` skips rows where `port=0`.

```typescript
// types.ts — no change needed, port stays required
port: number;  // 0 = Gateway-managed, >0 = standalone with host port

// manager-db.ts — createAgent() in Gateway mode:
createAgent(name, managerId, 0, openrouterKey, role, bio)  // port=0
```

**Gateway-mode agent creation (rev2 Finding #4):**

`scripts/create_agent.sh` currently requires `<port>` as second arg and maps it to the host Docker port. In Gateway mode:

```bash
# Standalone mode (current, preserved):
./scripts/create_agent.sh hina 9001 sk-or-v1-xxx
# Health check: curl 127.0.0.1:9001/api/health (up to 30s retry)

# Gateway mode (new):
./scripts/create_agent.sh --gateway hina sk-or-v1-xxx
# - No host port mapping (container runs internal-only)
# - Generates GATEWAY_AGENT_TOKEN, writes to agent .env
# - Registers token in /data/gateway/agent_tokens.json
# - Container connects to GATEWAY_URL on startup
# - Lounge DB: port=0 (Gateway-managed)
# - Health check: poll Gateway GET /agents/hina/health until
#   status != "unreachable" (up to 45s retry, matching heartbeat timeout)
```

**Readiness path difference (rev6 Finding #2):**

| Mode | What proves agent is healthy |
|------|------------------------------|
| Standalone | `curl 127.0.0.1:${PORT}/api/health` returns `{"status":"alive"}` |
| Gateway | `curl 127.0.0.1:8000/agents/${AGENT_ID}/health` returns `{"status":"alive"}` (Gateway has received at least one heartbeat from the agent's WS connection) |

The Gateway health endpoint returns `{"status":"unreachable","reason":"heartbeat_timeout"}` until the agent completes WS handshake + sends its first health payload. `create_agent.sh --gateway` polls this endpoint with exponential backoff (1s, 2s, 4s, ...) up to 45s total, matching the Gateway's heartbeat timeout window. Failure after 45s prints a diagnostic and exits non-zero (same as standalone mode's 30s curl timeout).

`lounge/src/lib/docker-client.ts:createContainer()` similarly gains a Gateway-mode path where `HostPort` is omitted and `GATEWAY_URL` + `GATEWAY_AGENT_TOKEN` env vars are set instead.

### Health Model (Findings #7, rev2-#5)

**Problem:** Current `/api/health` returns cognitive liveness (supervisor staleness, cycle recency). Pure WS heartbeat timestamps are weaker — a wedged agent could send WS pings while its cognitive loop is frozen.

**Solution:** Agent heartbeat to Gateway includes the actual `get_health_status()` payload (not a simplified version):

```python
# Agent sends every 15s over WS — exact schema from heartbeat.py:296-308:
{
    "type": "heartbeat",
    "agent_id": "shopkeeper_main",
    "health": {
        "status": "alive",              # "alive" | "degraded"
        "reason": "ok",                 # "ok" | "heartbeat_stopped" | "no_loop_heartbeat" | "loop_heartbeat_stale" | "supervisor_not_running"
        "loop_running": true,
        "supervisor_running": true,
        "seconds_since_last_tick": 12,  # null if no tick yet
        "stale_after_seconds": 300,
        "restart_count": 0,
        "last_loop_error": null
    }
}
```

Gateway stores the latest health payload verbatim and exposes it via `GET /agents/{agent_id}/health`. If no heartbeat for 45s, Gateway returns `{"status": "unreachable", "reason": "heartbeat_timeout"}` regardless of last payload.

### What the Gateway Does

**1. Agent Registry** (replaces nginx_regen.sh + port allocation)
- Agent containers open persistent WS to Gateway on startup
- Gateway tracks who's alive because they're connected
- No more port management. No more nginx regen. Agents register themselves.

**2. Request Routing** (replaces per-agent HTTP proxy)
- Lounge calls `GET /agents/{agent_id}/dashboard/vitals` on Gateway
- Gateway forwards request over agent's WebSocket (RPC)
- Returns response to caller
- Auth headers propagated transparently (Finding #4)
- Lounge no longer needs to know ports

**3. Health Monitoring** (replaces polling)
- Agents send cognitive health payload every 15s (Finding #7)
- Gateway stores latest health per agent
- No heartbeat for 45s → mark unhealthy
- Lounge subscribes to `agent_online`/`agent_offline` events via Gateway WS
- Real-time status instead of port polling

**4. Inter-Agent Messaging** (new capability)
- Agents send messages to each other through Gateway
- Gateway handles routing + timeout
- Agents stay isolated — they don't know each other's addresses
- Messages appear in recipient's event stream (like visitor speech events)
- Uses `bus_types.py` message format from Phase 2

### Files

| File | Action |
|------|--------|
| `engine/gateway.py` | CREATE (~400 lines) |
| `engine/gateway_client.py` | CREATE (~150 lines) |
| `engine/heartbeat_server.py` | MODIFY (~30 lines: optional Gateway transport) |
| `lounge/src/lib/agent-client.ts` | MODIFY (~80 lines: all functions) |
| `lounge/src/lib/types.ts` | MODIFY (~5 lines: add `gateway_registered` field) |
| `lounge/src/lib/manager-db.ts` | MODIFY (~15 lines: port defaults to 0, `getNextPort()` skips 0) |
| `lounge/src/app/api/agents/route.ts` | MODIFY (~15 lines) |
| `lounge/src/app/api/agents/[id]/` | MODIFY (~40 lines across sub-routes) |
| `lounge/src/lib/docker-client.ts` | MODIFY (~30 lines: Gateway-mode create path, no host port, set GATEWAY_URL + token envs) |
| `scripts/destroy_agent.sh` | MODIFY (~10 lines: remove agent token from agent_tokens.json) |
| `scripts/create_agent.sh` | MODIFY (~40 lines: `--gateway` mode, token generation, atomic registry write) |
| `deploy/nginx.conf` | MODIFY (simplify to static Gateway routing) |
| `deploy/nginx-alive-lounge.conf` | MODIFY (remove per-agent location blocks) |
| `scripts/nginx_regen.sh` | DELETE (replaced by static Gateway config) |
| `tests/test_gateway.py` | CREATE |
| `tests/test_gateway_client.py` | CREATE |

### Sub-phases

1. **Gateway Core (3-4 days):** `gateway.py` + `gateway_client.py`. Agent registration, cognitive health monitoring, RPC request forwarding with auth propagation. Lounge still works via old port-based routing (parallel operation). Both paths valid.
2. **Lounge Cutover (2-3 days):** Full Lounge migration (all files in matrix above). `agent-client.ts` rewritten to use Gateway. `port=0` convention for Gateway-managed agents (no schema change). Nginx simplified. Old port-based routing removed. *(Revised up from 1-2 days per Finding #1)*
3. **Inter-Agent Messaging (1 day):** `agent_send` RPC. Messages routed through Gateway. Appear in recipient's inbound event stream via Phase 2 bus.

### Risks

| Risk | Mitigation |
|------|-----------|
| Gateway is SPOF | Agents keep local HTTP server as fallback; standalone mode works without Gateway |
| Added latency (extra WS hop) | Same host; WS overhead ~1ms; LLM call is 2-10s |
| Migration disruption | Sub-phase 1 runs alongside existing routing; cut over only after validation |
| RPC protocol maintenance | Minimal envelope: `{id, method, path, headers, body, timeout}` → `{id, status, body}` |
| Auth bypass | Gateway is transparent proxy for auth — agent-level `_check_api_key()` and `check_dashboard_auth()` still enforced inside agent (Finding #4) |
| Agent impersonation | Per-agent unique tokens with full lifecycle (create/destroy/rotate). Gateway validates `agent_id` matches registered token. Stale tokens cleaned on destroy. (rev2 #1, rev3 #1) |
| Lounge cutover scope | Full migration matrix documented above; all port-coupled files identified (Finding #1) |
| Schema/type migration | `agents.port` stays `INTEGER NOT NULL`, sentinel `0` = Gateway-managed. No schema change. `getNextPort()` skips `port=0` rows. (Finding #2, rev6 #3) |
| Wedged agent appears healthy | Agent heartbeat includes full `get_health_status()` payload with exact schema (Findings #7, rev2-#5) |
| Port-first create path | `create_agent.sh --gateway` mode skips port allocation; `docker-client.ts` gains matching Gateway path; `destroy_agent.sh` cleans up token (rev2 #4, rev3 #1, rev3 #2) |
| Token registry corruption | `flock` + atomic file replacement (`write .tmp` → `mv`). All mutations (create/destroy/rotate) acquire exclusive lock. (rev3 #3, rev5 #1) |
| Complexity creep | Gateway is ONLY router + registry. No business logic. No DB writes. No LLM calls. |

---

## What We Explicitly Do NOT Do

1. No external message broker (no Redis/NATS — in-process bus + Gateway WS only)
2. No pip packaging
3. No interactive wizard
4. No changes to cognitive pipeline (11 stages untouched)
5. No new engine DB tables (bus is in-memory, Gateway is stateless, preflight is read-only)
6. No multi-channel inbox (Telegram/Discord adapters are separate future work)
7. No skill extensibility yet (parked — revisit after Gateway is stable)
8. Gateway has NO business logic, NO DB writes, NO LLM calls — router only
9. No handler signature rewrite in Phase 2 — adapter pattern only (Finding #5)
10. No modification or deletion of `tasks/lounge-deploy/` — it's reference/history only, not operational. `scripts/` is the canonical ops path. (Findings #6, rev2-#3)

---

## Lines of Code Summary

| Phase | New | Modified | Deleted |
|-------|-----|----------|---------|
| 1: Deploy Ergonomics | ~350 | ~40 | 0 |
| 2: Event Bus | ~400 | ~650 | ~600 (moved) |
| 3: Gateway | ~550 | ~190 | ~110 |
| **Total** | **~1,300** | **~880** | **~710** |

Net: ~1,470 new lines. `heartbeat_server.py` shrinks from 1,741 to ~500. `nginx_regen.sh` deleted. Port allocation eliminated.

---

## Verification

Test count: **~2,500 tests** (corrected from stale 1,445 figure per Finding #8).

**After Phase 1:**
- `python3 -m pytest tests/ --tb=short -q` — all ~2,500 pass
- `python engine/heartbeat_server.py` with missing env var → clear error message, not crash
- `scripts/doctor.py` on VPS → prints system health report

**After Phase 2:**
- All ~2,500 tests pass
- Terminal connects, visitor speaks, cycle runs, window updates (same as before)
- `heartbeat_server.py` is ~500 lines
- WebSocket broadcast still works after extraction
- `/api/chat` still returns correct visitor-specific dialogue (keyed subscription test)
- Concurrency test: two simultaneous `POST /api/chat` for the same `visitor_id` each get distinct dialogue (per-visitor lock)
- Concurrency test: simultaneous `POST /api/chat` + `POST /api/manager-message` for the same `visitor_id` — both paths serialize correctly through `bus.visitor_lock()`

**After Phase 3:**
- Agent container starts → auto-registers with Gateway (WS handshake + GATEWAY_TOKEN)
- Lounge dashboard shows agent status in real-time (no polling)
- `docker stop <agent>` → Lounge shows agent offline within seconds
- `create_agent.sh --gateway` → no nginx regen needed; readiness check passes only when Gateway reports `status == "alive"` (not just reachable — degraded startup is not treated as healthy)
- Standalone mode (no Gateway) still works for local dev
- Auth propagation: Lounge → Gateway → Agent — agent-level auth still enforced
- Token registry contention test: 5 concurrent `create_agent.sh --gateway` invocations produce correct `agent_tokens.json` (no lost writes, all 5 tokens present). Same test for interleaved create + destroy.
