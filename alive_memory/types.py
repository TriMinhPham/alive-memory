"""Core type system for alive-memory."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class EventType(Enum):
    CONVERSATION = "conversation"
    ACTION = "action"
    OBSERVATION = "observation"
    SYSTEM = "system"


class MemoryType(Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


@dataclass
class Perception:
    """Structured perception from raw event (thalamus output)."""
    event_type: EventType
    content: str
    salience: float  # 0-1
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Memory:
    """A formed memory with cognitive metadata."""
    id: str
    content: str
    memory_type: MemoryType
    strength: float  # 0-1, consolidation strength
    valence: float  # -1 to 1, emotional valence
    formed_at: datetime
    last_recalled: Optional[datetime] = None
    recall_count: int = 0
    source_event: Optional[EventType] = None
    drive_coupling: dict[str, float] = field(default_factory=dict)
    embedding: Optional[list[float]] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DriveState:
    """Current drive levels."""
    curiosity: float = 0.5
    social: float = 0.5
    expression: float = 0.5
    rest: float = 0.5


@dataclass
class MoodState:
    """Current mood."""
    valence: float = 0.0  # -1 to 1
    arousal: float = 0.5  # 0 to 1
    word: str = "neutral"


@dataclass
class CognitiveState:
    """Full cognitive state snapshot."""
    mood: MoodState
    energy: float
    drives: DriveState
    cycle_count: int
    last_sleep: Optional[datetime] = None
    memories_total: int = 0


@dataclass
class ConsolidationReport:
    """Report from a consolidation (sleep) cycle."""
    memories_strengthened: int = 0
    memories_weakened: int = 0
    memories_pruned: int = 0
    memories_merged: int = 0
    dreams: list[str] = field(default_factory=list)
    reflections: list[str] = field(default_factory=list)
    identity_drift: Optional[dict] = None
    duration_ms: int = 0


@dataclass
class SelfModel:
    """Persistent self-model."""
    traits: dict[str, float] = field(default_factory=dict)
    behavioral_summary: str = ""
    drift_history: list[dict] = field(default_factory=list)
    version: int = 0
    snapshot_at: Optional[datetime] = None
