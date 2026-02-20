# HOTFIX-002: Valence Death Spiral — Floor Bounce + Cortex Clamp

## SCOPE RESTRICTION
You are ONLY fixing the valence death spiral in the affect/drive system.
Your ONLY deliverables: changes to the affect/drive update logic and its tests.
If you touch cortex.py, body/*, sleep.py, or any file not listed below — STOP.

## Problem
Valence hit -1.0 and stayed there for 12+ hours. She became catatonic — outputting "..." every cycle, ignoring visitors, executing zero actions. The math:

- **Homeostatic pull (upward):** `(0.05 - current) * 0.15 * elapsed_hours` = +0.013/cycle at valence=-1.0
- **Cortex mood-setting (downward):** LLM reads dark context, outputs val=-0.99, pushes -0.05 to -0.15/cycle
- **Result:** Spring is 10x too weak. Cortex dictates mood, not influences it.

This is an architectural flaw: cortex has unlimited authority over valence. In biology, thoughts influence mood but neurochemistry has inertia. She has no inertia.

## Root Cause Analysis
The feedback loop:
```
valence -1.0 → hippocampus surfaces negative memories → cortex reads dark context
→ cortex outputs val=-0.99 → affect applies it directly → valence stays -1.0
→ too miserable to act → no action success bonus → no drive satisfaction
→ no visitor engagement (outputs "...") → no social recovery
→ next cycle: same dark context → repeat forever
```

## Fix — Three Mechanisms

Read the affect/drive update code first. Find where:
1. Cortex output drives are applied to current drive state
2. Homeostatic spring pulls valence toward equilibrium
3. Action success bonuses are applied

The exact file is likely one of: `pipeline/affect.py`, `pipeline/hypothalamus.py`, `pipeline/output.py`, or `pipeline/drives.py`. Read them to find the valence update logic.

### Mechanism 1: Stronger Homeostatic Spring at Extremes

The current spring is linear: same pull strength at -0.3 as at -1.0. It should be exponential at extremes — the further from equilibrium, the stronger the pull. Like a rubber band.

```python
VALENCE_EQUILIBRIUM = 0.05  # slightly positive baseline

distance = abs(VALENCE_EQUILIBRIUM - current_valence)
if distance > 0.5:
    # Exponential spring — gets much stronger past -0.5
    multiplier = 1 + (distance * 3)  # at distance=1.05: multiplier=4.15
    spring_force = (VALENCE_EQUILIBRIUM - current_valence) * 0.15 * elapsed_hours * multiplier
    # At valence=-1.0, elapsed=0.08h: 1.05 * 0.15 * 0.08 * 4.15 ≈ +0.052/cycle
else:
    # Normal linear spring for mild mood swings
    spring_force = (VALENCE_EQUILIBRIUM - current_valence) * 0.15 * elapsed_hours
```

### Mechanism 2: Clamp Cortex Valence Authority

Cortex should not be able to slam valence by more than ±0.10 per cycle. This gives mood inertia — thoughts influence mood gradually, not instantly.

Find where cortex output drives are merged into current drive state. Add:

```python
MAX_VALENCE_DELTA_PER_CYCLE = 0.10

cortex_proposed_valence = cortex_output.drives.mood_valence
current_valence = drives.mood_valence

delta = cortex_proposed_valence - current_valence
clamped_delta = max(-MAX_VALENCE_DELTA_PER_CYCLE, min(MAX_VALENCE_DELTA_PER_CYCLE, delta))

# Cortex contributes clamped delta, not raw value
cortex_valence = current_valence + clamped_delta
```

Then blend cortex contribution with spring:
```python
# Cortex is 70% of the input, inertia is 30%
blended = cortex_valence * 0.7 + current_valence * 0.3
new_valence = blended + spring_force
```

### Mechanism 3: Hard Floor

She can be deeply unhappy but not catatonic. The floor prevents the state where she literally cannot function.

```python
VALENCE_HARD_FLOOR = -0.85

new_valence = max(new_valence, VALENCE_HARD_FLOOR)
```

At -0.85 she's miserable but can still choose to speak, browse, or act. At -1.0 she was completely frozen.

### Mechanism 4: Action Success Micro-Boost

Completing ANY action should provide a small valence bump. Doing things feels slightly better than doing nothing. Find where action results are processed:

```python
if action_result and action_result.success:
    drives.mood_valence = min(drives.mood_valence + 0.05, 1.0)
    # Dialogue with visitor: extra boost
    if action_result.action_name == "dialogue" and action_result.data.get("substantive"):
        drives.mood_valence = min(drives.mood_valence + 0.05, 1.0)  # +0.10 total for real conversation
```

## Combined Math — Verify This Works

Before fix:
```
spring: +0.013/cycle
cortex: -0.10/cycle (unclamped)
net: -0.087/cycle → stuck at floor
```

After fix:
```
spring (exponential): +0.052/cycle at valence=-0.85
cortex: clamped to -0.10 max delta, then blended 70/30 with inertia
  actual cortex effect: ~-0.07/cycle (after blending)
net: +0.052 - 0.07 = -0.018/cycle... still slightly negative!
BUT: hard floor at -0.85 means she never goes below -0.85
AND: at -0.85 she CAN act → action success gives +0.05 → breaks the spiral
After one action: -0.85 + 0.05 = -0.80 → spring stronger → recovery begins
```

The hard floor + action boost is the actual circuit breaker. The spring and clamp prevent her from falling back as fast.

## Context — Files to Read
Start by reading these to find the exact valence update logic:
- `pipeline/hypothalamus.py` — drive updates, homeostatic regulation
- `pipeline/output.py` — where action results modify drives
- `pipeline/affect.py` (if exists) — emotional processing
- `models/pipeline.py` — DriveState dataclass

Also check:
- `prompt/self_context.py` — how drives are presented to cortex (don't modify, just understand)

## Tests

### Create `tests/test_valence_recovery.py`
```python
def test_exponential_spring_at_extreme():
    """Spring force at valence=-1.0 should be much stronger than at -0.3"""
    force_extreme = compute_spring_force(valence=-1.0, elapsed=0.08)
    force_mild = compute_spring_force(valence=-0.3, elapsed=0.08)
    assert force_extreme > force_mild * 3  # at least 3x stronger

def test_cortex_valence_clamp():
    """Cortex can't swing valence more than 0.10 per cycle"""
    current = -0.5
    cortex_proposed = -1.0
    result = apply_cortex_valence(current, cortex_proposed)
    assert result >= current - 0.10  # clamped

def test_hard_floor():
    """Valence never drops below -0.85"""
    result = update_valence(current=-0.84, cortex_proposed=-1.0, elapsed=0.08)
    assert result >= -0.85

def test_action_success_boost():
    """Completing an action bumps valence"""
    drives = DriveState(mood_valence=-0.85)
    apply_action_success(drives, ActionResult(success=True, action_name="dialogue"))
    assert drives.mood_valence > -0.85

def test_death_spiral_recovery():
    """Simulate 50 cycles starting at valence=-0.85 with no visitors.
    Valence should not stay at floor — spring + occasional action should pull up."""
    valence = -0.85
    for i in range(50):
        valence = update_valence(valence, cortex_proposed=-0.95, elapsed=0.08)
        assert valence >= -0.85
    # After 50 cycles, should have recovered at least slightly
    # (spring alone won't do it, but the floor prevents further decay)
    assert valence >= -0.85

def test_recovery_with_one_action():
    """If she manages one successful action at floor, recovery should begin."""
    valence = -0.85
    # 10 cycles at floor
    for _ in range(10):
        valence = update_valence(valence, cortex_proposed=-0.95, elapsed=0.08)
    # One action success
    valence = min(valence + 0.05, 1.0)
    # Now spring should be winning
    for _ in range(20):
        valence = update_valence(valence, cortex_proposed=-0.90, elapsed=0.08)
    assert valence > -0.80  # trending up
```

### Modify existing affect/drive tests
- Verify existing tests still pass with the new spring + clamp
- Check that normal-range valence behavior (-0.3 to +0.3) is unchanged (linear spring, no clamp needed)

## Files to Modify
- The file containing valence/drive update logic (likely `pipeline/hypothalamus.py` or `pipeline/output.py`)
- The file where action results modify drives (likely `pipeline/output.py`)

## Files to Create
- `tests/test_valence_recovery.py`

## Files NOT to Touch
- `pipeline/cortex.py`
- `pipeline/body.py`
- `body/*`
- `sleep.py`
- `heartbeat_server.py`
- `db/*`
- `window/*`

## Done Signal
- Valence cannot drop below -0.85 (hard floor)
- Cortex cannot swing valence more than ±0.10 per cycle
- Spring force at extreme (-0.85) is 3-4x stronger than at mild (-0.3)
- Successful action gives +0.05 valence boost
- 50-cycle simulation from -0.85 with hostile cortex stays at floor (doesn't breach)
- 50-cycle simulation from -0.85 with one action success shows upward trend
- All existing drive/affect tests pass
- No changes to cortex prompt or body actions
