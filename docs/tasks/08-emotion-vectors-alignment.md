# Task 08: Emotion Vectors Alignment

Findings from reviewing our codebase against Anthropic's "Emotion Concepts and their Function in a Large Language Model" (Transformer Circuits, April 2026). See `docs/emotion-vectors-review.md` for the full analysis.

---

## P1 — High Priority

### [ ] 08a: Add desperation quadrant detector

**Why:** Paper shows "desperate" (high-arousal + low-valence) is the single most dangerous emotion vector for alignment. Our system has safety floors but no specific monitoring for this quadrant.

**Where:** `alive_cognition/drives.py` (mood update), new safety hook in thalamus or affect pipeline

**What:**
- Detect `valence < -0.3 and arousal > 0.6` as "desperation zone"
- When triggered: suppress risky action selection, increase logging, activate calming drive pressure
- Add arousal damping when in desperation zone (paper shows "calm" is protective)
- Consider emitting a system event so downstream consumers can react

---

### [ ] 08b: Dual-perspective emotion tracking (self vs. other)

**Why:** Paper found two orthogonal emotion subspaces — present-speaker and other-speaker. We conflate "how I feel" with "how I model their emotion."

**Where:** `alive_cognition/affect.py`, `alive_memory/types.py` (MoodState), `alive_memory/intake/formation.py`

**What:**
- Add `other_valence: float` and `other_arousal: float` to perception or moment data
- During conversation events, compute both agent valence and inferred user valence
- Store both on `DayMoment` for use during consolidation
- Update `emotional_imprint` on visitors to use other-speaker valence history
- Keep the two subspaces independent (paper says they're nearly orthogonal)

---

## P2 — Medium Priority

### [ ] 08c: Derive operative mood from recent memory

**Why:** Paper found no persistent emotional state in the model — emotions are locally scoped and reconstructed from context via attention. Our `MoodState` is a persistent variable with homeostatic drift equations.

**Where:** `alive_cognition/drives.py` (mood update logic), `alive_memory/types.py`

**What:**
- Prototype computing mood from last N moments' valence/drive snapshots instead of maintaining running state
- Keep homeostatic drives (curiosity, social, expression, rest) as persistent — these are closer to needs than emotions
- Mood becomes a derivation: `mood = f(recent_moments, current_drives, current_context)`
- Evaluate whether this produces more natural emotional trajectories than the current drift model
- This is a bigger architectural shift — prototype alongside current system before replacing

---

### [ ] 08d: Semantic valence scoring at moment formation

**Why:** Paper shows emotion vectors respond to semantic meaning, not surface features. Our `compute_valence()` uses keyword lists and misses sarcasm, implied emotion, contextual danger.

**Where:** `alive_cognition/affect.py` (compute_valence), `alive_memory/intake/formation.py`

**What:**
- Keep keyword heuristic for thalamus hot path (fast, cheap, good enough for routing)
- At moment formation, compute a more accurate valence using either:
  - Embedding projection onto valence/arousal axes (cheap, fast)
  - Lightweight LLM call (expensive but accurate)
- Store the semantic valence on `DayMoment`, not the keyword valence
- Benchmark accuracy improvement vs. latency cost

---

## P3 — Low Priority

### [ ] 08e: Expand mood vocabulary to ~15-20 terms

**Why:** Paper used 171 emotions clustering into ~10 groups. Our 7 words can't distinguish "anxious" (defensive) from "desperate" (risk-seeking) — both map to `valence < -0.3, arousal > 0.6`.

**Where:** `alive_cognition/drives.py` (_mood_word function)

**What:**
- Map the paper's 10 clusters to ~15-20 discrete mood labels
- Refine the valence/arousal→word mapping with finer quadrant boundaries
- Ensure downstream consumers (prompt templates, journal reflections) handle the expanded vocabulary
- Consider adding a third axis (dominance/control) if the 10 clusters demand it

---

### [ ] 08f: Emotion deflection model (internal vs. displayed)

**Why:** Paper found distinct representations for characters hiding emotions. Our mood word always reflects internal state directly.

**Where:** `alive_memory/types.py` (MoodState), response generation layer

**What:**
- Split `MoodState` into `internal_mood` and `displayed_mood`
- `displayed_mood` is what gets surfaced in prompts and responses
- `internal_mood` is what drives salience, memory, and drives
- Only needed if the character design requires social masking (e.g., staying professional while frustrated)

---

### [ ] 08g: Intended-affect planning (sensory → action split)

**Why:** Paper shows early layers encode "what emotion is in the input" (sensory) while late layers encode "what emotion to express next" (action). Our thalamus only does the sensory side.

**Where:** Response generation pipeline (outside alive_memory proper)

**What:**
- Before generating a response, compute an **intended affect** separate from current mood
- Example: agent is melancholy but decides to be warm to a returning visitor
- This is an "action layer" analogue — planning what emotion to express based on context, drives, and identity
- May live in alive_cognition rather than alive_memory (boundary rule)

---

## Dependencies

- 08a (desperation detector) is standalone, can ship immediately
- 08b (dual perspective) is standalone, can ship immediately
- 08c (operative mood) depends on evaluating 08b results first
- 08d (semantic valence) is standalone
- 08e (vocabulary) should follow 08a (desperation detector needs the distinction)
- 08f and 08g are design-dependent, lower urgency
