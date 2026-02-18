# TASK-063: Identity Evolution (STUB)

**THIS IS A STUB SPEC.** Implementation is gated on resolving the philosophical question below.

## Problem

When drift is detected (062), something should happen. But what?

## The philosophical problem

- **If she always accepts drift** → identity dissolves, she becomes whatever the LLM drifts toward
- **If she always corrects** → she's frozen, can't grow
- **If we hardcode the criteria** → we're deciding her identity for her, which contradicts the ALIVE premise
- **If she decides** → the decision itself is influenced by the current drift, creating a circular dependency

This is not a technical problem. It's a design philosophy problem that needs to be resolved before implementation begins.

## Interface (stub only)

```python
class IdentityEvolution:
    def evaluate_drift(self, drift_report: DriftReport) -> EvolutionDecision:
        """Given a drift report, decide: accept, correct, or defer."""
        raise NotImplementedError("Gated on philosophical review")

    def accept_drift(self, drift_report: DriftReport):
        """Update self-model baseline to incorporate the drift as new normal."""
        pass

    def correct_drift(self, drift_report: DriftReport):
        """Inject corrective guidance into next N cycles to steer back toward baseline."""
        pass

    def defer(self, drift_report: DriftReport):
        """Take no action. Continue observing."""
        pass
```

## Guard rails (non-negotiable regardless of implementation)

1. **Core safety traits cannot be evolved away** — she can't drift into being hostile to visitors
2. **Evolution rate capped** — no more than one trait update per sleep cycle
3. **All evolution decisions logged** with full context for operator review
4. **Operator override** — dashboard can force-correct or force-accept any drift

These guard rails are hard constraints. Whatever solution we choose for the philosophical problem must respect them.

## Scope

**Files you may touch:**
- `identity/evolution.py` (new — stub with interface only)
- `identity/evolution_config.json` (new — guard rail params)
- No integration with cortex or cycle — disconnected until philosophical gate passes

**Files you may NOT touch:**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `simulate.py`

## Depends on

- TASK-062 (drift detection — evolution needs drift reports to act on)

## Blocks

- Nothing (end of the identity evolution chain)

## Tests (for stub)

- Interface exists and is importable
- Guard rail config loads
- Calling any method raises NotImplementedError
- Dashboard shows evolution status as "disabled — pending review"

## Definition of done (for stub)

- Interface class exists with `evaluate_drift`/`accept_drift`/`correct_drift`/`defer` methods
- All methods raise NotImplementedError
- Guard rail config loads and validates
- Dashboard shows disabled status
- No integration with live system
- Clear documentation of the philosophical problem for future resolution
