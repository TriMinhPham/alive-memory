"""Tests for identity-aware salience (Phase 3).

Tests:
- Metadata salience override skips heuristic
- Identity keyword boost
- Raised day memory cap (500)
"""

from __future__ import annotations

from alive_memory.config import AliveConfig
from alive_memory.intake.thalamus import perceive
from alive_memory.types import EventType


def test_metadata_salience_override() -> None:
    """metadata.salience should bypass all heuristic computation."""
    p = perceive(
        EventType.CONVERSATION,
        "irrelevant content that would normally get some salience",
        metadata={"salience": 0.1},
    )
    assert p.salience == 0.1


def test_metadata_salience_override_high() -> None:
    p = perceive(
        EventType.SYSTEM,
        "system event",
        metadata={"salience": 0.95},
    )
    assert p.salience == 0.95


def test_identity_boost_increases_salience() -> None:
    """Events matching identity keywords should get a salience boost."""
    # Without identity keywords
    p_base = perceive(
        EventType.CONVERSATION,
        "A customer asked about rare pottery",
    )

    # With identity keywords matching content
    p_boosted = perceive(
        EventType.CONVERSATION,
        "A customer asked about rare pottery",
        identity_keywords=["customer", "pottery", "shopkeeper"],
    )

    assert p_boosted.salience > p_base.salience


def test_identity_boost_no_match() -> None:
    """Non-matching identity keywords should not change salience."""
    p_base = perceive(
        EventType.CONVERSATION,
        "The weather is nice today",
    )

    p_same = perceive(
        EventType.CONVERSATION,
        "The weather is nice today",
        identity_keywords=["customer", "pottery"],
    )

    assert p_same.salience == p_base.salience


def test_identity_boost_configurable() -> None:
    """Identity boost amount should be configurable."""
    cfg = AliveConfig({"intake": {"identity_boost": 0.3}})
    p = perceive(
        EventType.CONVERSATION,
        "A customer walked in",
        config=cfg,
        identity_keywords=["customer"],
    )

    p_no_boost = perceive(
        EventType.CONVERSATION,
        "A customer walked in",
        config=cfg,
    )

    diff = p.salience - p_no_boost.salience
    # Should show a boost (may be clamped to 1.0)
    assert diff > 0.1


def test_day_memory_cap_raised() -> None:
    """MAX_DAY_MOMENTS should be 500, not 30."""
    from alive_memory.intake.formation import MAX_DAY_MOMENTS
    assert MAX_DAY_MOMENTS == 500
