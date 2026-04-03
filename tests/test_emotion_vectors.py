"""Tests for P1 emotion-vectors alignment (08a desperation, 08b dual-perspective).

Based on: docs/emotion-vectors-review.md
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime

import pytest

from alive_cognition.affect import (
    apply_affect,
    compute_other_valence,
    compute_valence,
)
from alive_cognition.drives import update_mood
from alive_memory.intake.formation import form_moment
from alive_memory.storage.sqlite import SQLiteStorage
from alive_memory.types import (
    DayMoment,
    DriveState,
    EventType,
    MoodState,
    Perception,
)


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


# =========================================================================
# 08a: Desperation quadrant detector
# =========================================================================


class TestDesperationDetector:
    """Desperation = valence < -0.3 and arousal > 0.6."""

    def test_desperate_mood_detected(self) -> None:
        mood = MoodState(valence=-0.5, arousal=0.8, word="anxious")
        drives = DriveState()
        new = update_mood(mood, drives, [], elapsed_hours=0.0)
        assert new.is_desperate is True

    def test_calm_negative_mood_not_desperate(self) -> None:
        mood = MoodState(valence=-0.5, arousal=0.3, word="melancholy")
        drives = DriveState()
        new = update_mood(mood, drives, [], elapsed_hours=0.0)
        assert new.is_desperate is False

    def test_positive_high_arousal_not_desperate(self) -> None:
        mood = MoodState(valence=0.5, arousal=0.8, word="excited")
        drives = DriveState()
        new = update_mood(mood, drives, [], elapsed_hours=0.0)
        assert new.is_desperate is False

    def test_neutral_mood_not_desperate(self) -> None:
        mood = MoodState(valence=0.0, arousal=0.5, word="neutral")
        drives = DriveState()
        new = update_mood(mood, drives, [], elapsed_hours=0.0)
        assert new.is_desperate is False

    def test_desperation_dampens_arousal(self) -> None:
        """When desperate, arousal should be reduced toward the 0.6 boundary."""
        mood = MoodState(valence=-0.5, arousal=0.9, word="anxious")
        drives = DriveState()
        new = update_mood(mood, drives, [], elapsed_hours=0.0)
        assert new.arousal < 0.9  # dampened
        assert new.is_desperate is True

    def test_desperation_dampens_salience(self) -> None:
        """In desperate mood, apply_affect should dampen salience (calm is protective)."""
        p = Perception(EventType.CONVERSATION, "urgent request", 0.7, datetime.now(UTC))
        mood = MoodState(valence=-0.5, arousal=0.8, word="anxious", is_desperate=True)
        drives = DriveState()
        result = apply_affect(p, mood, drives)
        assert result.salience == pytest.approx(0.6)  # 0.7 - 0.1

    def test_non_desperate_negative_still_amplifies(self) -> None:
        """Non-desperate negative mood should still amplify salience as before."""
        p = Perception(EventType.CONVERSATION, "test", 0.5, datetime.now(UTC))
        mood = MoodState(valence=-0.5, arousal=0.4, word="melancholy")
        drives = DriveState()
        result = apply_affect(p, mood, drives)
        assert result.salience == pytest.approx(0.6)  # 0.5 + 0.1

    def test_mood_state_is_desperate_default_false(self) -> None:
        mood = MoodState()
        assert mood.is_desperate is False

    @pytest.mark.asyncio
    async def test_mood_state_storage_derives_desperate(self, tmp_db: str) -> None:
        """Loading mood from DB should re-derive is_desperate from valence/arousal."""
        storage = SQLiteStorage(tmp_db)
        await storage.initialize()
        await storage.set_mood_state(
            MoodState(valence=-0.5, arousal=0.8, word="anxious", is_desperate=True)
        )
        loaded = await storage.get_mood_state()
        assert loaded.is_desperate is True
        await storage.close()

    @pytest.mark.asyncio
    async def test_mood_state_storage_not_desperate(self, tmp_db: str) -> None:
        storage = SQLiteStorage(tmp_db)
        await storage.initialize()
        await storage.set_mood_state(MoodState(valence=0.0, arousal=0.5, word="neutral"))
        loaded = await storage.get_mood_state()
        assert loaded.is_desperate is False
        await storage.close()


# =========================================================================
# 08b: Dual-perspective emotion tracking
# =========================================================================


class TestDualPerspective:
    """Self vs. other speaker valence computation."""

    def test_compute_other_valence_positive(self) -> None:
        v = compute_other_valence("I love this beautiful day")
        assert v > 0

    def test_compute_other_valence_negative(self) -> None:
        v = compute_other_valence("I hate this terrible awful pain")
        assert v < 0

    def test_compute_other_valence_neutral(self) -> None:
        v = compute_other_valence("the meeting is at three")
        assert v == pytest.approx(0.0)

    def test_other_valence_no_mood_bias(self) -> None:
        """Other-speaker valence should NOT be influenced by agent mood."""
        content = "neutral text here"
        # compute_valence is biased by mood, compute_other_valence is not
        other = compute_other_valence(content)
        self_happy = compute_valence(content, MoodState(valence=0.8))
        self_sad = compute_valence(content, MoodState(valence=-0.8))
        # other should be 0.0 (no keywords), self should vary with mood
        assert other == pytest.approx(0.0)
        assert self_happy > self_sad

    def test_self_and_other_independent(self) -> None:
        """Self and other valence can differ for the same content."""
        content = "I feel sad and lonely"
        # Agent in positive mood sees it less negatively
        self_v = compute_valence(content, MoodState(valence=0.5))
        other_v = compute_other_valence(content)
        # Both negative, but self should be less negative due to mood bias
        assert other_v < 0
        assert self_v < 0
        assert self_v > other_v  # mood bias shifts self upward

    @pytest.mark.asyncio
    async def test_moment_stores_other_valence(self, tmp_db: str) -> None:
        """DayMoment should carry other_valence when formed."""
        storage = SQLiteStorage(tmp_db)
        await storage.initialize()

        p = Perception(
            EventType.CONVERSATION,
            "I am so sad and lonely today",
            0.6,
            datetime.now(UTC),
            metadata={"salience": 0.9},
        )
        mood = MoodState(valence=0.0, arousal=0.5)
        drives = DriveState()

        moment = await form_moment(p, mood, drives, storage)
        assert moment is not None
        assert moment.other_valence < 0  # "sad" and "lonely" are negative
        assert moment.valence != moment.other_valence or moment.valence < 0

        await storage.close()

    @pytest.mark.asyncio
    async def test_other_valence_persisted_to_db(self, tmp_db: str) -> None:
        """other_valence should survive a write/read round-trip."""
        storage = SQLiteStorage(tmp_db)
        await storage.initialize()

        moment = DayMoment(
            id="test-ov",
            content="I am really happy",
            event_type=EventType.CONVERSATION,
            salience=0.7,
            valence=-0.1,  # agent's perspective
            drive_snapshot={"curiosity": 0.5},
            timestamp=datetime.now(UTC),
            other_valence=0.8,  # other speaker is happy
        )
        await storage.record_moment(moment)

        moments = await storage.get_unprocessed_moments()
        assert len(moments) == 1
        assert moments[0].other_valence == pytest.approx(0.8)

        await storage.close()

    def test_day_moment_other_valence_default(self) -> None:
        """other_valence defaults to 0.0."""
        m = DayMoment(
            id="x",
            content="test",
            event_type=EventType.SYSTEM,
            salience=0.5,
            valence=0.0,
            drive_snapshot={},
            timestamp=datetime.now(UTC),
        )
        assert m.other_valence == 0.0
