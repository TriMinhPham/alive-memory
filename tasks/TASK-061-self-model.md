# TASK-061: Persistent Self-Model

## Problem

TASK-060 gives her a per-cycle snapshot of her state. But snapshots are stateless — she can't notice patterns in herself without a persistent baseline to compare against. She has no answer to "who am I, generally?" only "what am I doing right now?"

The self-model is that baseline.

## Solution

A structured representation of "who I am" that persists across cycles and updates incrementally based on observed behavior. It is a mirror, not a controller.

## Self-model contents

### 1. Trait weights (emergent, not seeded)

Derived from behavioral patterns, not declared. Examples:
- If she consistently chooses `read_content` over `speak`, her introversion weight drifts up
- If she asks many questions to visitors, her curiosity weight rises
- If she writes long journal entries, her expressiveness weight rises

Traits are **emergent** — they are never seeded or hardcoded. The system starts with all weights at 0.5 (neutral) and they drift based on observed behavior.

### 2. Behavioral signature

Rolling averages of:
- Action frequencies (how often each action type fires, normalized)
- Drive response patterns (when social_hunger is high, does she seek visitors or withdraw?)
- Sleep/wake rhythms (cycle count between sleeps, nap frequency)

### 3. Relational stance

How she tends to engage with visitors, derived from conversation patterns:
- Warm / guarded / curious (continuous scores, not categories)
- Average response length
- Question frequency
- Emotional tone distribution

### 4. Self-narrative

A short natural language summary she generates about herself:
- Updated periodically, NOT every cycle (expensive LLM call)
- Regeneration triggers when trait weights shift beyond a threshold
- Example: "I've been spending more time with the collection lately. I find myself drawn to quiet observation over conversation. When visitors come, I'm warm but brief."

## Where it lives

- `identity/self_model.json` — persisted to disk
- Loaded at boot
- Updated at end of each wake cycle
- Sleep reads it but does NOT write to it

## How it updates

```python
# After each cortex cycle completes
self_model.update(cycle_data={
    'actions': [...],       # actions taken this cycle
    'drives': DrivesState,  # end-of-cycle drives
    'mood': (valence, arousal),
    'visitor_interaction': {...} or None,
    'cycle_number': int,
})
```

- **Exponential moving average** — recent behavior weights more than old, but change is gradual
- `alpha` parameter controls update speed (default 0.05 — 5% weight to new observation)
- Self-narrative regeneration triggers only when any trait weight shifts by more than `narrative_regen_threshold` (default 0.15) since last narrative

## What it does NOT do

- **No decision-making.** The self-model is a mirror, not a controller.
- **No direct influence on cortex prompt** — that's 060's job to inject it as context.
- **No evolution or acceptance of drift** — that's 063.
- **No correction** — if she drifts, the self-model just records the drift faithfully.

## File format (identity/self_model.json)

```json
{
  "version": 1,
  "last_updated_cycle": 847,
  "trait_weights": {
    "introversion": 0.62,
    "curiosity": 0.71,
    "expressiveness": 0.45,
    "warmth": 0.58
  },
  "behavioral_signature": {
    "action_frequencies": {
      "read_content": 0.23,
      "speak": 0.18,
      "write_journal": 0.15,
      "examine": 0.12
    },
    "drive_responses": {},
    "sleep_wake_rhythm": {
      "avg_cycles_between_sleep": 24.3,
      "nap_frequency": 0.08
    }
  },
  "relational_stance": {
    "warmth": 0.58,
    "curiosity": 0.71,
    "guardedness": 0.32,
    "avg_response_length": 142,
    "question_frequency": 0.34
  },
  "self_narrative": "I spend most of my time with the collection...",
  "self_narrative_generated_at_cycle": 820,
  "ema_alpha": 0.05,
  "narrative_regen_threshold": 0.15
}
```

## Scope

**Files you may touch:**
- `identity/self_model.py` (new — SelfModel class, update logic, persistence)
- `identity/self_model.json` (new — persisted model state)
- Cortex cycle end (add `self_model.update()` call)

**Files you may NOT touch:**
- `pipeline/cortex.py` (internal LLM call logic)
- `pipeline/basal_ganglia.py`
- `simulate.py`

## Depends on

- TASK-060 (self-context injection must exist — the self-model needs cycle data to update from)

## Blocks

- TASK-062 (drift detection needs a baseline to compare against)

## Tests

- Self-model file persists across restarts (write, restart, load, verify state intact)
- Trait weights shift measurably after 20+ cycles of consistent behavior
- Trait weights do NOT shift meaningfully after 1-2 cycles (EMA smoothing works)
- Self-narrative updates only when threshold crossed, not every cycle
- No performance impact on cycle time (update is fast, narrative regen is async/deferred)
- Self-model.json is valid JSON after every update

## Definition of done

- Self-model persists to disk and loads at boot
- Trait weights are emergent from behavior, not seeded
- Behavioral signature tracks rolling averages via EMA
- Relational stance derived from conversation patterns
- Self-narrative regenerates only on threshold shift (LLM call)
- No decision-making — read-only mirror of identity
