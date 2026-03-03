"""Smoke tests for the core type system."""

from datetime import datetime, timezone

from alive_memory.types import (
    CognitiveState,
    ConsolidationReport,
    DriveState,
    EventType,
    Memory,
    MemoryType,
    MoodState,
    Perception,
    SelfModel,
)


def test_memory_creation():
    m = Memory(
        id="m-001",
        content="Test memory",
        memory_type=MemoryType.EPISODIC,
        strength=0.75,
        valence=0.3,
        formed_at=datetime.now(timezone.utc),
    )
    assert m.id == "m-001"
    assert m.strength == 0.75
    assert m.recall_count == 0
    assert m.embedding is None
    assert m.drive_coupling == {}


def test_perception_creation():
    p = Perception(
        event_type=EventType.CONVERSATION,
        content="Hello",
        salience=0.9,
        timestamp=datetime.now(timezone.utc),
    )
    assert p.salience == 0.9
    assert p.metadata == {}


def test_drive_state_defaults():
    d = DriveState()
    assert d.curiosity == 0.5
    assert d.social == 0.5
    assert d.expression == 0.5
    assert d.rest == 0.5


def test_mood_state_defaults():
    m = MoodState()
    assert m.valence == 0.0
    assert m.arousal == 0.5
    assert m.word == "neutral"


def test_cognitive_state():
    state = CognitiveState(
        mood=MoodState(),
        energy=0.8,
        drives=DriveState(),
        cycle_count=42,
    )
    assert state.energy == 0.8
    assert state.cycle_count == 42
    assert state.memories_total == 0


def test_consolidation_report_defaults():
    report = ConsolidationReport()
    assert report.memories_strengthened == 0
    assert report.dreams == []
    assert report.reflections == []


def test_self_model_defaults():
    sm = SelfModel()
    assert sm.traits == {}
    assert sm.version == 0
    assert sm.behavioral_summary == ""


def test_event_types():
    assert EventType.CONVERSATION.value == "conversation"
    assert EventType.ACTION.value == "action"
    assert EventType.OBSERVATION.value == "observation"
    assert EventType.SYSTEM.value == "system"


def test_memory_types():
    assert MemoryType.EPISODIC.value == "episodic"
    assert MemoryType.SEMANTIC.value == "semantic"
    assert MemoryType.PROCEDURAL.value == "procedural"


def test_memory_with_all_fields():
    now = datetime.now(timezone.utc)
    m = Memory(
        id="m-full",
        content="Full memory",
        memory_type=MemoryType.SEMANTIC,
        strength=1.0,
        valence=-0.5,
        formed_at=now,
        last_recalled=now,
        recall_count=3,
        source_event=EventType.OBSERVATION,
        drive_coupling={"curiosity": 0.8, "social": 0.2},
        embedding=[0.1, 0.2, 0.3],
        metadata={"source": "test"},
    )
    assert m.recall_count == 3
    assert m.drive_coupling["curiosity"] == 0.8
    assert len(m.embedding) == 3
