# HOTFIX-003: Thread Dedup + Rumination Breaker

## SCOPE RESTRICTION
You are ONLY fixing thread deduplication and adding a rumination breaker.
Your ONLY deliverables: changes to thread management and hippocampus context selection.
If you touch affect/drives, cortex.py, body/*, or any file not listed below — STOP.

## Problem
She opened 6 separate "What is anti-pleasure?" threads with near-identical content. Each cycle, hippocampus surfaces the same negative thread, cortex ruminates on it, and nothing breaks the loop. This is the cognitive equivalent of intrusive thoughts with no ability to redirect attention.

Two fixes needed:
1. **Thread dedup** — prevent opening duplicate threads
2. **Rumination breaker** — deprioritize threads that have appeared in too many consecutive cycles

## Bug 1: Thread Dedup

She can open the same thread multiple times because there's no check for existing similar threads.

Find the thread creation code (likely in `pipeline/output.py`, `pipeline/hippocampus_write.py`, or wherever `thread_open` action is handled).

### Fix
Before creating a new thread, check if an open thread with similar topic/content exists:

```python
async def open_thread(topic: str, content: str, db) -> Thread:
    # Check for existing open thread with same or similar topic
    open_threads = await db.get_threads(status="open")
    
    for existing in open_threads:
        # Exact match on topic
        if existing.topic.lower().strip() == topic.lower().strip():
            # Append to existing thread instead of creating new
            await db.append_to_thread(existing.id, content)
            return existing
        
        # Fuzzy match — check if topic words overlap significantly
        existing_words = set(existing.topic.lower().split())
        new_words = set(topic.lower().split())
        if len(existing_words & new_words) / max(len(existing_words | new_words), 1) > 0.6:
            await db.append_to_thread(existing.id, content)
            return existing
    
    # No match — create new thread
    return await db.create_thread(topic, content)
```

Also: **close stale threads.** If a thread has been open for more than 48h with no updates, auto-close it during sleep. Find the sleep consolidation logic and add:

```python
# During sleep — close stale threads
stale_threads = await db.get_threads(status="open", last_updated_before=hours_ago(48))
for thread in stale_threads:
    await db.close_thread(thread.id, reason="stale — no new thoughts in 48h")
```

## Bug 2: Rumination Breaker

Even with dedup, a single open thread can dominate hippocampus output for dozens of cycles. She needs the ability to "set aside" a thought she can't resolve.

Find where hippocampus selects context/threads for the cortex prompt (likely `pipeline/hippocampus.py`).

### Fix — Attention Fatigue

Track how many consecutive cycles each thread has appeared in context. After a threshold, reduce its salience so other content surfaces.

```python
# In hippocampus context assembly

# Track thread appearances (can use a simple in-memory counter or DB)
# Key: thread_id, Value: count of consecutive cycles in context
THREAD_APPEARANCE_COUNTER: dict[int, int] = {}
RUMINATION_THRESHOLD = 5  # after 5 consecutive cycles, start fading

def select_threads_for_context(open_threads: list[Thread], cycle_count: int) -> list[Thread]:
    scored_threads = []
    
    for thread in open_threads:
        consecutive = THREAD_APPEARANCE_COUNTER.get(thread.id, 0)
        
        if consecutive >= RUMINATION_THRESHOLD:
            # Attention fatigue — exponentially reduce salience
            fatigue_factor = 0.3 ** (consecutive - RUMINATION_THRESHOLD + 1)
            # After 5 cycles: 0.3x, after 6: 0.09x, after 7: 0.027x
            effective_salience = thread.salience * fatigue_factor
        else:
            effective_salience = thread.salience
        
        scored_threads.append((thread, effective_salience))
    
    # Sort by effective salience, return top N
    scored_threads.sort(key=lambda x: x[1], reverse=True)
    
    selected = [t for t, s in scored_threads[:MAX_THREADS_IN_CONTEXT]]
    
    # Update counters
    selected_ids = {t.id for t in selected}
    for thread in open_threads:
        if thread.id in selected_ids:
            THREAD_APPEARANCE_COUNTER[thread.id] = THREAD_APPEARANCE_COUNTER.get(thread.id, 0) + 1
        else:
            # Reset counter when thread drops out of context
            THREAD_APPEARANCE_COUNTER[thread.id] = 0
    
    return selected
```

**Important:** The counter should reset when the thread drops out of context. This means a ruminating thread fades, disappears for a few cycles (she "sets it aside"), then can resurface later with fresh salience. Just like how humans stop thinking about something, then revisit it later with new perspective.

### Alternative simpler approach if the above is too complex:
```python
# Just add a "last_in_context" timestamp to threads
# If thread was in context for the last 5 cycles, skip it for the next 3 cycles
if thread.consecutive_context_cycles >= 5:
    thread.cooldown_remaining = 3  # skip next 3 cycles
    continue
```

## Context — Files to Read
- `pipeline/hippocampus.py` — context assembly, thread selection
- `pipeline/hippocampus_write.py` — where threads are created
- `pipeline/output.py` — where thread_open/thread_update actions are processed
- `models/pipeline.py` — Thread dataclass
- `db/memory.py` — thread table queries
- `sleep.py` — consolidation logic (for stale thread cleanup)

## Tests

### Create `tests/test_thread_dedup.py`
```python
def test_exact_duplicate_blocked():
    """Opening same topic twice returns existing thread"""
    t1 = await open_thread("What is anti-pleasure?", "First thought", db)
    t2 = await open_thread("What is anti-pleasure?", "Second thought", db)
    assert t1.id == t2.id  # same thread, content appended

def test_fuzzy_duplicate_blocked():
    """Similar topics merge into existing thread"""
    t1 = await open_thread("What is anti-pleasure?", "First", db)
    t2 = await open_thread("anti-pleasure question", "Second", db)
    assert t1.id == t2.id

def test_different_topics_allowed():
    """Genuinely different topics create separate threads"""
    t1 = await open_thread("What is anti-pleasure?", "...", db)
    t2 = await open_thread("Vintage Carddass pricing trends", "...", db)
    assert t1.id != t2.id

def test_closed_thread_not_matched():
    """Closed threads don't block new ones on same topic"""
    t1 = await open_thread("anti-pleasure", "First", db)
    await db.close_thread(t1.id)
    t2 = await open_thread("anti-pleasure", "Revisiting", db)
    assert t1.id != t2.id  # new thread since old was closed
```

### Create `tests/test_rumination_breaker.py`
```python
def test_thread_fades_after_threshold():
    """Thread salience decreases after 5 consecutive appearances"""
    thread = Thread(id=1, topic="test", salience=0.9)
    
    # First 5 cycles: full salience
    for i in range(5):
        selected = select_threads_for_context([thread], cycle=i)
        assert thread in selected
    
    # Cycle 6+: salience reduced
    # (may still appear if no competition, but with lower score)
    effective = get_effective_salience(thread)
    assert effective < 0.3  # significantly reduced

def test_thread_resets_after_dropout():
    """Thread counter resets when it drops out of context"""
    thread = Thread(id=1, topic="test", salience=0.9)
    
    # Ruminate for 7 cycles
    for i in range(7):
        select_threads_for_context([thread], cycle=i)
    
    # Simulate dropout (not selected for 1 cycle)
    THREAD_APPEARANCE_COUNTER[thread.id] = 0
    
    # Should resurface at full salience
    effective = get_effective_salience(thread)
    assert effective == thread.salience

def test_stale_thread_closed_during_sleep():
    """Threads open >48h with no updates get closed in sleep"""
    old_thread = create_thread_with_age(hours=50)
    await close_stale_threads(db)
    assert (await db.get_thread(old_thread.id)).status == "closed"
```

## Files to Modify
- Thread creation logic (likely `pipeline/hippocampus_write.py` or `pipeline/output.py`)
- Thread context selection (likely `pipeline/hippocampus.py`)
- Sleep consolidation (likely `sleep.py` or `sleep/consolidation.py`)
- `db/memory.py` — add `append_to_thread()` if it doesn't exist

## Files to Create
- `tests/test_thread_dedup.py`
- `tests/test_rumination_breaker.py`

## Files NOT to Touch
- `pipeline/cortex.py`
- `pipeline/hypothalamus.py` (that's HOTFIX-002's scope)
- `body/*`
- `heartbeat_server.py`
- `window/*`

## Done Signal
- Cannot open duplicate thread with same/similar topic (merges into existing)
- Thread appearing in 5+ consecutive cycles has salience reduced by 70%+
- Thread counter resets when thread drops out of context
- Stale threads (>48h no update) closed during sleep
- "Anti-pleasure" scenario: 6 threads impossible, rumination fades after 5 cycles
- All existing thread tests pass
- New dedup + rumination tests pass
