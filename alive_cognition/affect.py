"""Affect Lens — emotional valence computation.

Part of alive_cognition (moved from alive_memory.intake.affect).
Stripped: pipeline-stage interface, DrivesState dependency.
Kept: valence computation, time dilation math.

Dual-perspective tracking: computes both agent and other-speaker valence.
See docs/emotion-vectors-review.md for the research basis.
"""

from __future__ import annotations

import random

from alive_memory.types import DriveState, MoodState, Perception

# ── Keyword lexicons ──────────────────────────────────────────────────

_POSITIVE = {
    "happy",
    "love",
    "beautiful",
    "wonderful",
    "thank",
    "great",
    "amazing",
    "joy",
    "good",
    "kind",
    "warm",
    "friend",
    "smile",
    "laugh",
    "gift",
    "welcome",
    "nice",
    "sweet",
}
_NEGATIVE = {
    "sad",
    "angry",
    "hate",
    "ugly",
    "terrible",
    "bad",
    "awful",
    "pain",
    "hurt",
    "lonely",
    "alone",
    "cold",
    "leave",
    "gone",
    "sorry",
    "lost",
    "miss",
    "cry",
    "fear",
    "worry",
}


def apply_affect(
    perception: Perception,
    mood: MoodState,
    drives: DriveState,
) -> Perception:
    """Color a perception with current emotional state.

    Modifies salience based on mood valence and returns the perception.
    Negative mood amplifies salience (things feel heavier).
    When in the desperation quadrant, dampens salience to reduce
    over-reactive behavior (paper: calm is protective).
    """
    if mood.is_desperate:
        # Desperation safety: dampen salience to reduce impulsive reactions.
        perception.salience = max(0.0, perception.salience - 0.1)
    elif mood.valence < -0.3:
        perception.salience = min(1.0, perception.salience + 0.1)
    elif mood.valence > 0.3 and perception.metadata.get("valence", 0) < 0:
        # Positive mood: slightly dampens negative events
        perception.salience = max(0.0, perception.salience - 0.05)

    return perception


def _base_valence(content: str) -> float:
    """Raw keyword valence of content text, without mood bias. Returns -1 to 1."""
    words = set(content.lower().split())
    pos_count = len(words & _POSITIVE)
    neg_count = len(words & _NEGATIVE)
    total = pos_count + neg_count
    return 0.0 if total == 0 else (pos_count - neg_count) / total


def compute_valence(content: str, mood: MoodState) -> float:
    """Estimate agent's operative emotional valence for content.

    Keyword-based with mood-congruent bias. Returns -1 to 1.
    This is the *self* perspective: how the agent feels about the content.
    """
    base = _base_valence(content)
    mood_bias = mood.valence * 0.2
    return max(-1.0, min(1.0, base + mood_bias))


def compute_other_valence(content: str) -> float:
    """Estimate the other speaker's emotional valence from their content.

    Pure keyword scoring without agent mood bias — the other person's
    emotion is independent of how the agent currently feels.

    Maintains a separate subspace from compute_valence, following the
    paper's finding of orthogonal self/other emotion representations.
    """
    return max(-1.0, min(1.0, _base_valence(content)))


def time_dilation(drives: DriveState) -> float:
    """Compute subjective time dilation from drive state.

    Social hunger makes time feel slower (loneliness drags).
    High curiosity makes time fly.
    """
    d = 1.0
    d *= 1.0 + 0.6 * max(0.0, drives.social - 0.6)
    d *= 1.0 - 0.5 * max(0.0, drives.curiosity - 0.6)
    return max(0.7, min(1.3, d + random.uniform(-0.08, 0.08)))
