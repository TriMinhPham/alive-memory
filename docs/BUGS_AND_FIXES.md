# Bug & Fix Log

> All bugs discovered and fixes applied in this repository are documented here.
> Entries are in reverse chronological order (newest first).
> See `CLAUDE.md` §18 for the required format.

---

### BUG-2026-02-12-sleep-date-filter-drops-waking-period

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Critical |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | #7 |
| **Commit**      | N/A |

**Symptom:** Sleep consolidation at 03:00 JST dropped most moments from the prior waking period. Only moments from 00:00–03:00 JST were included.

**Root Cause:** `get_unprocessed_day_memory()` filtered `ts >= _jst_today_start_utc()` (midnight JST). At 03:00 JST, this excluded the entire prior day's moments (06:00–23:59 JST), which span the previous calendar day. The shopkeeper's waking period crosses midnight.

**Fix:** Removed the JST date filter from `get_unprocessed_day_memory()` — sleep should consolidate ALL unprocessed moments regardless of calendar day. The `delete_stale_day_memory(max_age_days=2)` safety net prevents unbounded accumulation. The date filter remains on `get_day_memory()` (waking-hours recall) where "Earlier today" semantics are correct.

**Files Affected:**
- `db.py` — removed date filter from `get_unprocessed_day_memory()`

**Tests Added:**
- [ ] Verify moments from 18:00 JST (previous day) included in sleep consolidation at 03:00 JST

**Follow-ups / Notes:**
- Found by Codex re-review of the fix commit. The original P1 fix was too aggressive — date filter was correct for waking recall but wrong for overnight consolidation.

---

### BUG-2026-02-12-explicit-commit-inside-transaction

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | #7 |
| **Commit**      | N/A |

**Symptom:** `insert_day_memory()` could prematurely commit an outer transaction if called within a nested `async with transaction()` block.

**Root Cause:** The function called `await conn.commit()` explicitly inside `async with transaction()`. The `transaction().__aexit__` already handles commit/rollback. An explicit commit could finalize work from an enclosing transaction prematurely.

**Fix:** Removed `await conn.commit()`, replaced with comment noting that commit is handled by `transaction().__aexit__`.

**Files Affected:**
- `db.py` — removed explicit `conn.commit()` from `insert_day_memory()`

**Tests Added:**
- [ ] Verify no explicit `commit()` calls inside `async with transaction()` blocks

**Follow-ups / Notes:**
- Found by Codex re-review. Currently `insert_day_memory()` is only called from `maybe_record_moment()` which has no outer transaction, but the fix prevents future breakage.

---

### BUG-2026-02-12-sleep-deferral-starves-microcycles

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Critical |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | #7 |
| **Commit**      | N/A |

**Symptom:** During 03:00–06:00 JST, if the shopkeeper was engaged in conversation, the heartbeat loop entered an infinite tight loop calling `sleep_cycle()` → getting `False` (deferred) → `continue` → back to sleep check. Visitor microcycles (messages) were never processed for up to 3 hours.

**Root Cause:** The sleep check (`_should_sleep()`) was the first branch in the `while self.running` loop at `heartbeat.py:232`. When sleep deferred, the `continue` at line 247 looped back to the top, hitting the sleep check again immediately. The microcycle check at lines 249–260 was unreachable.

**Fix:** Restructured the loop to check microcycles FIRST, before sleep. Microcycles now have unconditional top priority. The sleep window idle block was simplified since microcycles are handled above it.

**Files Affected:**
- `heartbeat.py` — reordered loop: microcycle → sleep → sleep-window-idle → autonomous

**Tests Added:**
- [ ] Verify microcycle runs during 03:00–06:00 when engaged
- [ ] Verify sleep still executes when no microcycle pending

**Follow-ups / Notes:**
- Found by Codex review of PR #7. P0 severity — could stall active conversations for hours.

---

### BUG-2026-02-12-day-memory-leaks-across-days

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | #7 |
| **Commit**      | N/A |

**Symptom:** Day memory entries from previous days could appear in "Earlier today" recall, contaminating conversation context with stale moments.

**Root Cause:** `get_day_memory()` and `get_unprocessed_day_memory()` in `db.py` had no date filter. Sleep only processes top-7 moments by salience, and `flush_day_memory()` only deletes processed rows. Unprocessed rows from previous days persisted indefinitely.

**Fix:** Added `_jst_today_start_utc()` helper that computes midnight JST in UTC. Both query functions now filter `AND ts >= ?` to scope results to the current JST day. Added `delete_stale_day_memory(max_age_days=2)` as a safety net, called during `flush_day_memory()` to clean up any rows older than 2 days regardless of processed status.

**Files Affected:**
- `db.py` — added `_jst_today_start_utc()`, date filter on both queries, `delete_stale_day_memory()`
- `sleep.py` — `flush_day_memory()` now calls `delete_stale_day_memory()`

**Tests Added:**
- [ ] Verify yesterday's day_memory excluded from `get_day_memory()`
- [ ] Verify stale rows cleaned up by `delete_stale_day_memory()`

**Follow-ups / Notes:**
- Found by Codex review of PR #7. P1 severity — incorrect temporal context in conversations.

---

### BUG-2026-02-12-insert-day-memory-non-atomic

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Low |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | #7 |
| **Commit**      | N/A |

**Symptom:** Under theoretical concurrent inserts, `day_memory` table could exceed the 30-row cap by 1-2 rows.

**Root Cause:** `insert_day_memory()` did count → evict → insert as 3 separate `_exec_write` calls. Two concurrent inserts could both see count=30, both evict, then both insert.

**Fix:** Wrapped count + evict + insert in a single `async with transaction()` block using `conn.execute()` directly (not `_exec_write()` which acquires its own lock).

**Files Affected:**
- `db.py` — `insert_day_memory()` now uses transaction for atomicity

**Tests Added:**
- [ ] Verify count never exceeds 30 under rapid inserts

**Follow-ups / Notes:**
- Found by Codex review of PR #7. Low severity — soft cap overshoot is brief and harmless.

---

### BUG-2026-02-12-sleep-returns-true-on-all-fail

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | #7 |
| **Commit**      | N/A |

**Symptom:** If all moment reflections failed during sleep (e.g. API outage), `sleep_cycle()` still returned `True`, stamping `_last_sleep_date` and preventing retry until the next day.

**Root Cause:** The function returned `True` unconditionally after the moment loop, regardless of how many moments were actually processed. `all_reflections` being empty didn't change the return value.

**Fix:** Added `processed_count` tracker. If moments existed but zero were processed successfully, return `False` to allow retry within the same sleep window. Poison-skipped moments count as "handled" to prevent infinite retry loops.

**Files Affected:**
- `sleep.py` — added `processed_count` tracking and early `return False` on all-fail

**Tests Added:**
- [ ] Verify `sleep_cycle()` returns False when all moments raise
- [ ] Verify poison-skipped moments still allow completion

**Follow-ups / Notes:**
- Found by Codex review of PR #7. Medium severity — missed consolidation until next day.

---

### BUG-2026-02-12-had-contradiction-timing-note

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Low |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | #7 |
| **Commit**      | N/A |

**Symptom:** Codex flagged that `had_contradiction` signal in `_build_cycle_context()` might never fire because `internal_shift_candidate` events are emitted during the same cycle's execution, after unread was fetched.

**Root Cause:** `internal_shift_candidate` is emitted by `hippocampus_consolidate()` during `execute()`, but `unread` is fetched at cycle start. The event appears in the *next* cycle's unread, not the current one.

**Fix:** Analysis confirmed the signal works correctly — it fires one cycle late, boosting the salience of the follow-up moment. This is acceptable because the follow-up cycle is contextually adjacent. Added explanatory comment documenting this intentional timing behavior.

**Files Affected:**
- `heartbeat.py` — added timing comment on `had_contradiction` check

**Tests Added:**
- [ ] Code review verification only

**Follow-ups / Notes:**
- Found by Codex review of PR #7. The behavior is by-design, not a bug. Comment prevents future confusion.

---

### BUG-2026-02-12-sleep-dispatch-stamps-before-run

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | N/A |
| **Commit**      | N/A |

**Symptom:** If the sleep cycle was deferred (visitor engaged at 03:00 JST) or crashed, `_last_sleep_date` was already stamped, consuming the entire night's sleep window with no retry.

**Root Cause:** `heartbeat.py` set `_last_sleep_date` BEFORE calling `sleep_cycle()`. The stamp was unconditional — deferral and exceptions both left it set.

**Fix:** Moved `_last_sleep_date` assignment to AFTER `sleep_cycle()` returns `True`. Deferral (`False`) and exceptions no longer stamp, allowing retry on the next heartbeat iteration within the 03:00-06:00 window.

**Files Affected:**
- `heartbeat.py` — moved `_last_sleep_date` assignment inside success branch

**Tests Added:**
- [ ] Verify `_last_sleep_date` not set when `sleep_cycle()` returns False
- [ ] Verify `_last_sleep_date` not set when `sleep_cycle()` raises

**Follow-ups / Notes:**
- Discovered during three-tier memory implementation. The new `sleep_cycle()` returns `bool` (True=ran, False=deferred), making this fix natural.

---

### BUG-2026-02-12-canonical-identity-contradiction

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `fix/engagement-state-and-sanitization` |
| **PR**          | #4 |
| **Commit**      | N/A |

**Symptom:** Shopkeeper could deny canonical physical traits (e.g. "I don't wear glasses") because Cortex hallucinated and validator had no guardrail.

**Root Cause:** `validator.py` had no check against stable identity traits from `IDENTITY_COMPACT`. The LLM could contradict established physical appearance.

**Fix:** Added `CANONICAL_TRAITS` list with denial-pattern regexes and a `canonical_consistency_check()` stage in `validate()`. Contradicting dialogue is flagged via `_canonical_contradiction`. Codex review improved this: regex broadened to catch uncontracted "I do not" forms, and sentence-level removal preserves valid dialogue instead of blanking to `'...'`.

**Files Affected:**
- `pipeline/validator.py` — added canonical trait patterns, consistency check stage, sentence-level removal

**Tests Added:**
- [ ] Unit test covering denial patterns (glasses, height)
- [ ] Regression test: dialogue contradicting glasses → offending sentence removed, rest preserved

**Follow-ups / Notes:**
- Only covers glasses and height for now. Extend `CANONICAL_TRAITS` as more stable traits are established.
- Does not cover subtle contradictions ("my eyes are fine") — only explicit denials.
- Known false positive: third-person speech like "she doesn't wear glasses" would be flagged.

---

### BUG-2026-02-12-port-conflict-traceback

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Low |
| **Status**      | Fixed |
| **Branch**      | `fix/engagement-state-and-sanitization` |
| **PR**          | #4 |
| **Commit**      | N/A |

**Symptom:** Starting `heartbeat_server.py` when port 9999 was already in use produced a raw Python traceback with no recovery guidance.

**Root Cause:** `asyncio.start_server()` at line 65 had no `try/except` for `OSError`/`EADDRINUSE`.

**Fix:** Wrapped `start_server` in `try/except OSError`, prints friendly error with `lsof` hint, then cleanly shuts down heartbeat and DB before returning. Codex review improved this: replaced hardcoded errno `48` (macOS-only) with portable `errno.EADDRINUSE` constant.

**Files Affected:**
- `heartbeat_server.py` — added port conflict handling around `start_server`, portable errno

**Tests Added:**
- [ ] Manual test: start two instances, second prints friendly error
- [ ] Regression test: no traceback on `EADDRINUSE`

**Follow-ups / Notes:**
- Could add auto-retry on a different port, but explicit failure is better for now.

---

### BUG-2026-02-12-ansi-control-chars-in-memory

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `fix/engagement-state-and-sanitization` |
| **PR**          | #4 |
| **Commit**      | N/A |

**Symptom:** Terminal escape sequences (arrow keys producing `^[[A`, etc.) leaked into `conversation_log` and could appear in Cortex prompt context.

**Root Cause:** `terminal.py` only called `.strip()` on input, and `heartbeat_server.py` passed raw `msg.get('text')` directly to DB. No ANSI/control character sanitization.

**Fix:** Created `pipeline/sanitize.py` with `sanitize_input()` that strips ANSI escape sequences and control characters. Applied at both intake boundaries: `terminal.py` (client + standalone modes) and `heartbeat_server.py`. Codex review improved this: extended regex to cover C1 control range (`\x7f-\x9f`) and `\x9b` CSI variant, preventing terminal injection via non-ESC CSI sequences.

**Files Affected:**
- `pipeline/sanitize.py` — new module, ANSI + C1 control char stripping
- `terminal.py` — sanitize at both input paths
- `heartbeat_server.py` — sanitize at speech intake

**Tests Added:**
- [ ] Unit test: `^[[A` stripped from input
- [ ] Unit test: normal text preserved
- [ ] Regression test: control chars never reach `conversation_log`

**Follow-ups / Notes:**
- Drop command content (`drop <text>`) is not sanitized — could be a follow-up.

---

### BUG-2026-02-12-stale-conversation-on-connect

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `fix/engagement-state-and-sanitization` |
| **PR**          | #4 |
| **Commit**      | N/A |

**Symptom:** On reconnect, shopkeeper immediately referenced topics from the previous session (e.g. "New York" appearing on first connect cycle) because old conversation was loaded into Cortex prompt.

**Root Cause:** `db.get_recent_conversation()` fetched last 10 messages from `conversation_log` with no session scoping. On `visitor_connect`, old messages from previous visits leaked into the Cortex context.

**Fix:** Added `db.mark_session_boundary()` which inserts a `__session_boundary__` marker row. Updated `get_recent_conversation()` to only return messages after the most recent boundary. Both `heartbeat_server.py` and `terminal.py` now call `mark_session_boundary()` on connect.

**Files Affected:**
- `db.py` — added `mark_session_boundary()`, updated `get_recent_conversation()` to scope by session
- `heartbeat_server.py` — calls `mark_session_boundary` on connect
- `terminal.py` — calls `mark_session_boundary` on connect

**Tests Added:**
- [ ] Unit test: messages before boundary are excluded
- [ ] Unit test: first session (no boundary) returns all messages
- [ ] Regression test: no old topic carryover on reconnect

**Follow-ups / Notes:**
- Old conversation is still in DB for memory/sleep consolidation. Only Cortex prompt context is scoped.

---

### BUG-2026-02-12-end-engagement-state-collision

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `fix/engagement-state-and-sanitization` |
| **PR**          | #4 |
| **Commit**      | N/A |

**Symptom:** When shopkeeper ended a conversation, engagement state was briefly set to `engaged` (with turn count incremented) before `end_engagement` action set it to `cooldown`. Dirty state could cause next-cycle confusion.

**Root Cause:** In `executor.py`, the engagement update block (lines 70-79) unconditionally set `status='engaged'` and incremented turn count whenever dialogue existed with a visitor. This fired even when `end_engagement` was in the approved actions list, writing `engaged` before the action handler wrote `cooldown`.

**Fix:** Added an `ending` guard that checks if `end_engagement` is in `_approved_actions`. When true, the engagement update block is skipped entirely — no spurious `engaged` write, no turn count increment on farewell.

**Files Affected:**
- `pipeline/executor.py` — guarded engagement update with `ending` check

**Tests Added:**
- [ ] Unit test: `end_engagement` approved → no `engaged` write
- [ ] Regression test: cooldown persists after `end_engagement`

**Follow-ups / Notes:**
- The actual "undo" was mitigated by execution order (cooldown wrote second), but the dirty intermediate state and unnecessary turn increment were real bugs.

---

### BUG-2025-02-12-fidget-mismatch-hijacks-routing

| Field           | Value |
|-----------------|-------|
| **Date**        | 2025-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `fix/memory-identity-fidgets-journal` |
| **PR**          | #3 |
| **Commit**      | `453422d` |

**Symptom:** `fidget_mismatch` perception (salience 0.7) outranked `visitor_speech` (salience 0.5–0.6), becoming cycle focus. Since `route()` had no branch for `fidget_mismatch`, cycles fell through to drive-based routing (idle/rest/express), causing engaged conversations to be processed as non-engaged.

**Root Cause:** Two issues: (1) `fidget_mismatch` salience was 0.7, higher than typical speech. (2) `thalamus.route()` had no explicit branch for `fidget_mismatch`, so it fell to drive-based default.

**Fix:**
- Lowered `fidget_mismatch` salience from 0.7 to 0.4 so it augments speech as background context rather than replacing it as focus.
- Added explicit `fidget_mismatch` → `engage` branch in `thalamus.route()` as a safety net.

**Files Affected:**
- `pipeline/sensorium.py` — lowered fidget_mismatch salience to 0.4
- `pipeline/thalamus.py` — added fidget_mismatch routing branch

**Tests Added:**
- [ ] No test infrastructure in repo yet

**Follow-ups / Notes:**
- Found by Codex review. Confidence 0.97.

---

### BUG-2025-02-12-memory-update-errors-permanently-lost

| Field           | Value |
|-----------------|-------|
| **Date**        | 2025-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `fix/memory-identity-fidgets-journal` |
| **PR**          | #3 |
| **Commit**      | `453422d` |

**Symptom:** Memory consolidation errors were logged to console but not persisted. Since the cycle then marks inbox events as read, transient DB/runtime failures in memory writes became permanent data loss with no replay path.

**Root Cause:** Per-update `try/except` only logged `type+message` to stdout. No durable record was created, and the cycle committed normally afterward.

**Fix:** Failed memory updates now emit a `memory_consolidation_failed` event via `db.append_event()`, preserving the original update payload, error details, and visitor_id in the append-only event log for diagnosis and potential retry.

**Files Affected:**
- `pipeline/executor.py` — emit event on memory consolidation failure

**Tests Added:**
- [ ] No test infrastructure in repo yet

**Follow-ups / Notes:**
- A future retry mechanism could read `memory_consolidation_failed` events and re-attempt consolidation.
- Found by Codex review. Confidence 0.91.

---

### BUG-2025-02-12-fidget-ring-no-recency-check

| Field           | Value |
|-----------------|-------|
| **Date**        | 2025-02-12 |
| **Severity**    | Low |
| **Status**      | Fixed |
| **Branch**      | `fix/memory-identity-fidgets-journal` |
| **PR**          | #3 |
| **Commit**      | `453422d` |

**Symptom:** Fidget ring stored `(behavior, description, ts)` tuples but matching ignored the timestamp. In low-fidget periods, stale fidgets from much earlier could trigger mismatch perceptions.

**Root Cause:** `check_fidget_reference` iterated all entries in `recent_fidgets` without checking `ts` against current time.

**Fix:** Added a 5-minute (`FIDGET_RECENCY_SECONDS = 300`) time window. Fidgets older than 5 minutes are skipped during matching.

**Files Affected:**
- `pipeline/sensorium.py` — added time-window enforcement in `check_fidget_reference`

**Tests Added:**
- [ ] No test infrastructure in repo yet

**Follow-ups / Notes:**
- Found by Codex review. Confidence 0.82.
