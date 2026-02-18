# TASK-062: Drift Detection

## Problem

Without drift detection, the self-model (061) just passively records. Drift detection is the awareness layer — "I'm acting differently than I usually do." This is prerequisite for 063's choice to evolve or correct.

## What drift means

Drift is **NOT** deviation in a single cycle. One quiet cycle doesn't mean she's become introverted.

Drift is a **sustained divergence** over N cycles (configurable, default ~20) where behavioral patterns consistently differ from the self-model baseline.

## Metrics to compare

### 1. Action frequency distribution
- Current rolling window (last N cycles) vs self-model behavioral signature
- Example: if self-model says she reads 23% of the time but recent window shows 8%, that's drift

### 2. Drive response patterns
- How she responds to high social_hunger now vs how she used to
- Measured by action choices when specific drives are elevated

### 3. Conversation style metrics
- Response length (current avg vs baseline avg)
- Question frequency (asking vs telling ratio)
- Emotional tone distribution

### 4. Sleep/wake rhythm deviation
- Cycle count between sleeps
- Nap frequency
- Energy patterns

## Detection method

Per-metric drift score:
```
drift_score = abs(current_rolling_avg - self_model_baseline) / self_model_baseline
```

Individual scores feed into a composite drift score (weighted average — action frequency weights highest).

**Thresholds** (configurable in `identity/drift_config.json`):
- `> 0.3` = notable drift → logged, visible on dashboard
- `> 0.5` = significant drift → drift event emitted, injected into self-context

## What happens when drift is detected

1. **Drift event emitted** — visible on dashboard, logged to event system
2. **Drift summary injected into self-context** (060's block) so she's aware:
   > "I've been more withdrawn than usual for the past 15 cycles"
3. **No automatic correction.** Drift is information, not a problem to solve. TASK-063 decides what to do with it.

## Drift config format (identity/drift_config.json)

```json
{
  "window_size": 20,
  "thresholds": {
    "notable": 0.3,
    "significant": 0.5
  },
  "metric_weights": {
    "action_frequency": 0.35,
    "drive_response": 0.25,
    "conversation_style": 0.25,
    "sleep_wake_rhythm": 0.15
  },
  "min_cycles_for_detection": 10,
  "cooldown_cycles_between_events": 5
}
```

## Scope

**Files you may touch:**
- `identity/drift.py` (new — drift scoring, detection, event emission)
- `identity/drift_config.json` (new — thresholds, window sizes, metric weights)
- Cycle end (add drift check after self-model update)
- 060's self-context block (inject drift summary when active)
- Dashboard: drift indicator in DrivesPanel or new panel

**Files you may NOT touch:**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `simulate.py`

## Depends on

- TASK-061 (persistent self-model — drift needs a baseline to compare against)

## Blocks

- TASK-063 (identity evolution — needs drift detection to know when evolution is relevant)

## Tests

- Force behavioral shift in test (suppress all social actions for 30 cycles) → drift detected
- Return to normal behavior → drift score decreases back below threshold
- Single anomalous cycle does NOT trigger drift (window smoothing works)
- Dashboard shows drift event when significant threshold crossed
- Self-context includes drift summary when drift is active
- Drift cooldown prevents event spam (no event within cooldown_cycles of last event)

## Definition of done

- Drift detection runs after each self-model update
- Sustained divergence (not single-cycle noise) triggers drift events
- Dashboard shows drift indicators with scores
- Self-context includes drift summary when active
- No automatic correction — drift is information only
- All thresholds configurable via drift_config.json
