# TASK-096 — alive-memory SDK Extraction (In-Place)

> **Context:** You are working in the ALIVE/Shopkeeper monorepo. Read `ARCHITECTURE.md` first.
> **Goal:** Extract the cognitive memory layer into `engine/alive_memory/` as a standalone SDK package, while keeping the Shopkeeper application running on top of it.
> **Branch:** `alive-memory-extraction`
> **Rule:** Tests must pass after every step. Run `python -m pytest tests/ --tb=short -q` frequently.

---

## The Boundary

```
engine/alive_memory/     ← SDK (this is what we're building)
  ↑
  │ depends on
  │
engine/pipeline/         ← Shopkeeper application imports from alive_memory
engine/heartbeat.py
engine/body/
demo/
lounge/
```

**One-way dependency.** `alive_memory/` NEVER imports from:
- `engine/pipeline/cortex.py`
- `engine/pipeline/basal_ganglia.py`
- `engine/pipeline/output.py`
- `engine/pipeline/sensorium.py` (the application-layer perception)
- `engine/pipeline/validator.py`
- `engine/body/`
- `engine/heartbeat.py`
- `engine/heartbeat_server.py`
- `engine/api/`
- `engine/config/identity.py` (hardcoded Shopkeeper identity)
- `demo/`
- `lounge/`

`alive_memory/` MAY import from:
- `engine/clock.py` (time abstraction)
- `engine/models/` (shared dataclasses — but prefer copying needed types into `alive_memory/types.py`)
- Standard library, aiosqlite, numpy (for vector ops)

---

## Target Package Structure

Create this directory tree inside `engine/`:

```
engine/alive_memory/
├── __init__.py                  # AliveMemory class (public API facade)
├── types.py                     # Memory, DriveState, Perception, ConsolidationReport, SelfModel
├── config.py                    # AliveConfig loader (from YAML/dict/defaults)
│
├── intake/
│   ├── __init__.py
│   ├── thalamus.py              # Raw event → structured perception
│   ├── affect.py                # Emotional valence computation
│   ├── formation.py             # Perception → memory (from hippocampus_write.py)
│   └── drives.py                # Drive state updates (from hypothalamus.py)
│
├── recall/
│   ├── __init__.py
│   ├── hippocampus.py           # Memory retrieval + re-ranking
│   ├── weighting.py             # Consolidation strength, valence, drive-coupling scoring
│   └── context.py               # Contextual recall (mood-congruent, drive-coupled)
│
├── consolidation/
│   ├── __init__.py              # Orchestrator (run all phases)
│   ├── strengthening.py         # Rehearsal → strengthen
│   ├── decay.py                 # Time-based decay curve
│   ├── pruning.py               # Remove weak memories
│   ├── merging.py               # Combine similar memories
│   ├── dreaming.py              # Recombine memory fragments (needs LLM)
│   ├── reflection.py            # Self-model update during sleep (needs LLM)
│   └── whisper.py               # Config changes → dream perceptions
│
├── identity/
│   ├── __init__.py
│   ├── self_model.py            # Persistent self-representation
│   ├── drift.py                 # Behavioral drift detection
│   ├── evolution.py             # Identity change resolution
│   └── history.py               # Developmental history snapshots
│
├── meta/
│   ├── __init__.py
│   ├── controller.py            # Self-tuning parameter adjustments
│   └── evaluation.py            # Closed-loop eval of adjustments
│
├── storage/
│   ├── __init__.py
│   ├── base.py                  # BaseStorage ABC (~15 methods)
│   ├── sqlite.py                # SQLite + sqlite-vec adapter
│   └── migrations/
│       └── 001_initial.sql
│
├── embeddings/
│   ├── __init__.py
│   ├── local.py                 # Local embedding model
│   └── api.py                   # API-based embeddings
│
├── llm/
│   ├── __init__.py
│   ├── provider.py              # LLMProvider Protocol
│   ├── anthropic.py             # AnthropicProvider
│   └── openrouter.py            # OpenRouterProvider
│
└── defaults/
    └── alive_config.yaml        # Default cognitive parameters
```

---

## Execution Steps (in order)

### Step 0: Branch + Scaffold

```bash
git checkout -b alive-memory-extraction
mkdir -p engine/alive_memory/{intake,recall,consolidation,identity,meta,storage/migrations,embeddings,llm,defaults}
touch engine/alive_memory/__init__.py
touch engine/alive_memory/{types,config}.py
touch engine/alive_memory/intake/{__init__,thalamus,affect,formation,drives}.py
touch engine/alive_memory/recall/{__init__,hippocampus,weighting,context}.py
touch engine/alive_memory/consolidation/{__init__,strengthening,decay,pruning,merging,dreaming,reflection,whisper}.py
touch engine/alive_memory/identity/{__init__,self_model,drift,evolution,history}.py
touch engine/alive_memory/meta/{__init__,controller,evaluation}.py
touch engine/alive_memory/storage/{__init__,base,sqlite}.py
touch engine/alive_memory/embeddings/{__init__,local,api}.py
touch engine/alive_memory/llm/{__init__,provider,anthropic,openrouter}.py
```

Copy `config/alive_config.yaml` → `engine/alive_memory/defaults/alive_config.yaml`.

### Step 1: Types (`alive_memory/types.py`)

Define the core type system. Extract and adapt from `engine/models/state.py` and `engine/models/pipeline.py`.

**Required types:**

```python
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
    salience: float              # 0-1
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class Memory:
    """A formed memory with cognitive metadata."""
    id: str
    content: str
    memory_type: MemoryType
    strength: float              # 0-1, consolidation strength
    valence: float               # -1 to 1, emotional valence
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
    valence: float = 0.0         # -1 to 1
    arousal: float = 0.5         # 0 to 1
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
```

**Do NOT import these from `engine/models/`. Copy and adapt.** The SDK types are the public contract — they must be stable and independent of internal engine types. Later, the engine's pipeline stages will be updated to use these types or map to them.

### Step 2: LLM Provider Protocol (`alive_memory/llm/provider.py`)

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class LLMProvider(Protocol):
    async def complete(self, prompt: str, max_tokens: int = 1000) -> str: ...
```

Build `AnthropicProvider` in `llm/anthropic.py` and `OpenRouterProvider` in `llm/openrouter.py` by extracting the call logic from `engine/llm/client.py`. Strip the OpenRouter-specific retry/format logic into a clean interface.

### Step 3: Storage Interface (`alive_memory/storage/base.py`)

Define the `BaseStorage` ABC. Extract method signatures from `engine/db/memory.py`, `engine/db/state.py`, `engine/db/parameters.py`.

**Required methods (approximately):**

```python
from abc import ABC, abstractmethod

class BaseStorage(ABC):
    # Memory CRUD
    @abstractmethod
    async def store_memory(self, memory: Memory) -> str: ...
    @abstractmethod
    async def get_memory(self, memory_id: str) -> Optional[Memory]: ...
    @abstractmethod
    async def search_memories(self, embedding: list[float], limit: int, filters: dict) -> list[Memory]: ...
    @abstractmethod
    async def update_memory_strength(self, memory_id: str, strength: float) -> None: ...
    @abstractmethod
    async def update_memory_recall(self, memory_id: str) -> None: ...  # increment recall_count, set last_recalled
    @abstractmethod
    async def delete_memory(self, memory_id: str) -> None: ...
    @abstractmethod
    async def get_memories_for_consolidation(self, min_age_hours: float = 1.0) -> list[Memory]: ...
    @abstractmethod
    async def merge_memories(self, source_ids: list[str], merged: Memory) -> None: ...

    # State
    @abstractmethod
    async def get_drive_state(self) -> DriveState: ...
    @abstractmethod
    async def set_drive_state(self, state: DriveState) -> None: ...
    @abstractmethod
    async def get_mood_state(self) -> MoodState: ...
    @abstractmethod
    async def set_mood_state(self, state: MoodState) -> None: ...
    @abstractmethod
    async def get_cognitive_state(self) -> CognitiveState: ...

    # Identity
    @abstractmethod
    async def get_self_model(self) -> SelfModel: ...
    @abstractmethod
    async def save_self_model(self, model: SelfModel) -> None: ...

    # Parameters
    @abstractmethod
    async def get_parameters(self) -> dict: ...
    @abstractmethod
    async def set_parameter(self, key: str, value: Any, reason: str) -> None: ...

    # Cycle log
    @abstractmethod
    async def log_cycle(self, entry: dict) -> None: ...

    # Lifecycle
    @abstractmethod
    async def initialize(self) -> None: ...  # run migrations, create tables
    @abstractmethod
    async def close(self) -> None: ...
```

### Step 4: SQLite Storage (`alive_memory/storage/sqlite.py`)

Implement `BaseStorage` using aiosqlite + sqlite-vec. Extract table schemas from `engine/db/connection.py` (the migration logic). Only include SDK-relevant tables:

- `memories` — id, content, type, strength, valence, formed_at, last_recalled, recall_count, source_event, drive_coupling (JSON), embedding (BLOB), metadata (JSON)
- `drive_state` — single row, curiosity/social/expression/rest floats
- `mood_state` — single row, valence/arousal/word
- `cognitive_state` — cycle_count, energy, last_sleep, memories_total
- `self_model` — JSON blob, version, snapshot_at
- `parameters` — key/value pairs with modification history
- `cycle_log` — cycle audit trail

**Do NOT copy** the events, inbox, content_pool, threads, visitors, social, analytics, or actions tables. Those are application concerns.

Write the initial migration in `storage/migrations/001_initial.sql`.

### Step 5: Intake Pipeline

Extract module by module. For each:
1. Copy the source file
2. Remove all imports from `engine/` except `engine/clock.py`
3. Replace `engine/db/` calls with `BaseStorage` method calls (passed in via constructor)
4. Replace `engine/config/identity.py` constants with config parameters
5. Replace `engine/models/` types with `alive_memory/types.py`
6. Run tests

**File mapping:**

| Source | Target | Key changes |
|--------|--------|-------------|
| `engine/pipeline/thalamus.py` (352 lines) | `alive_memory/intake/thalamus.py` | Remove routing decision logic (that's application). Keep: event → Perception conversion, salience scoring. |
| `engine/pipeline/affect.py` (51 lines) | `alive_memory/intake/affect.py` | Small file, mostly clean. Remove pipeline-stage interface, keep valence computation. |
| `engine/pipeline/hypothalamus.py` (387 lines) | `alive_memory/intake/drives.py` | Remove session tracking specific to Shopkeeper visitors. Keep: drive update math, diminishing returns, equilibrium pull. Parameterize social_sensitivity (currently from agent identity). |
| `engine/pipeline/hippocampus_write.py` (388 lines) | `alive_memory/intake/formation.py` | Remove visitor trait updates (application concern). Keep: memory formation with valence + drive-coupling, embedding generation. |

### Step 6: Recall Pipeline

| Source | Target | Key changes |
|--------|--------|-------------|
| `engine/pipeline/hippocampus.py` (243 lines) | `alive_memory/recall/hippocampus.py` | Remove journal/totem/collection retrieval (application-specific memory types). Keep: vector search + re-ranking logic. |

Create `alive_memory/recall/weighting.py` — extract the re-ranking math into its own module:
- Consolidation strength weighting
- Emotional valence weighting (mood-congruent recall)
- Drive-coupled weighting
- Decay curve application
- Recall count strengthening

Create `alive_memory/recall/context.py` — contextual recall wrapper that takes current `CognitiveState` and applies it to weighting.

### Step 7: Consolidation (Sleep)

This is the most complex extraction. The current `engine/sleep/` package has 6 files totaling ~1,400 lines.

| Source | Target | Key changes |
|--------|--------|-------------|
| `engine/sleep/__init__.py` (171 lines) | `alive_memory/consolidation/__init__.py` | Rewrite as orchestrator that runs phases in order. Remove heartbeat coupling. |
| `engine/sleep/consolidation.py` (159 lines) | `alive_memory/consolidation/strengthening.py` | Extract strengthening logic. |
| `engine/sleep/reflection.py` (162 lines) | `alive_memory/consolidation/reflection.py` | Keep LLM reflection calls. Use `LLMProvider` protocol instead of direct OpenRouter calls. |
| `engine/sleep/nap.py` (83 lines) | Merge into orchestrator | Nap = lighter consolidation. Parameterize depth. |
| `engine/sleep/meta_controller.py` (642 lines) | `alive_memory/meta/controller.py` | This is big. Strip metric collection (application concern). Keep: parameter adjustment logic, confidence tracking, revert logic. |
| `engine/sleep/whisper.py` (239 lines) | `alive_memory/consolidation/whisper.py` | Keep dream-translation of config changes. |
| `engine/sleep/wake.py` (130 lines) | Part of orchestrator | Wake = post-consolidation reset. Drive reset, embedding batch. |

**New files to create:**
- `alive_memory/consolidation/decay.py` — extract decay curve logic (currently inline in consolidation.py)
- `alive_memory/consolidation/pruning.py` — extract pruning logic
- `alive_memory/consolidation/merging.py` — extract memory merging logic
- `alive_memory/consolidation/dreaming.py` — extract dream recombination (needs LLM)

### Step 8: Identity

| Source | Target | Key changes |
|--------|--------|-------------|
| `engine/identity/self_model.py` (407 lines) | `alive_memory/identity/self_model.py` | Remove file I/O (currently writes to `identity/self_model.json`). Use storage adapter instead. Remove hardcoded trait lists — parameterize. |
| `engine/identity/drift.py` (512 lines) | `alive_memory/identity/drift.py` | Keep drift detection math. Remove pipeline-specific event emission. Return drift reports as data. |
| `engine/identity/evolution.py` (320 lines) | `alive_memory/identity/evolution.py` | Keep three-tier accept/correct/defer logic. Parameterize protection rules. |

Create `alive_memory/identity/history.py` — developmental history retrieval from stored self-model snapshots.

### Step 9: AliveMemory Facade (`alive_memory/__init__.py`)

Build the public API class that wires everything together:

```python
class AliveMemory:
    def __init__(self, storage, config=None, llm=None):
        # Initialize storage adapter
        # Load config (YAML, dict, or defaults)
        # Set up LLM provider (optional, only needed for consolidation)

    def intake(self, event_type, content, metadata=None):
        # thalamus → affect → drives → formation → store

    def recall(self, query, limit=5, min_strength=0.0, context=None):
        # embed query → search → re-rank → return

    async def consolidate(self, whispers=None):
        # strengthen → decay → merge → prune → dream → reflect → identity
        # Returns ConsolidationReport

    @property
    def state(self) -> CognitiveState:
        # Return current cognitive state

    @property
    def identity(self) -> SelfModel:
        # Return current self-model

    def update_drive(self, drive, delta):
        # Manual drive update

    def inject_backstory(self, content, title=None):
        # Create memory with origin=injected

    async def meta_tune(self):
        # Run meta-controller manually

    def schedule_consolidation(self, interval_hours=None, after_events=None, cron=None):
        # Set up automatic consolidation

    def developmental_history(self, from_cycle=0, to_cycle=None):
        # Return identity snapshots over time
```

### Step 10: Update Shopkeeper Imports

**Last step.** Once the SDK works standalone:

1. Update `engine/heartbeat.py` to instantiate `AliveMemory` and pass it to pipeline stages
2. Update `engine/pipeline/cortex.py` to call `memory.recall()` instead of importing hippocampus directly
3. Update `engine/pipeline/output.py` to call `memory.intake()` for memory formation
4. Update sleep orchestration to call `memory.consolidate()`
5. Run full test suite

This is the riskiest step — it touches the most files. Do it in small commits.

---

## Boundary Enforcement

After every step, run:

```bash
# Check no alive_memory module imports from forbidden engine modules
grep -r "from engine\." engine/alive_memory/ | grep -v "engine.clock" | grep -v "engine.alive_memory"
# Should return nothing
```

If it returns anything, you have a boundary violation. Fix it before proceeding.

---

## Files to Read First

Before starting, read these files to understand what you're extracting:

1. `ARCHITECTURE.md` — full module map (you have this)
2. `engine/pipeline/hypothalamus.py` — drive math (most complex extraction)
3. `engine/pipeline/hippocampus.py` — recall logic (SDK value proposition)
4. `engine/pipeline/hippocampus_write.py` — memory formation
5. `engine/sleep/__init__.py` — sleep orchestration
6. `engine/identity/self_model.py` — self-model persistence
7. `engine/db/memory.py` — storage operations to extract
8. `engine/db/state.py` — state persistence
9. `config/alive_config.yaml` — all cognitive parameters

---

## What Success Looks Like

```python
from engine.alive_memory import AliveMemory

memory = AliveMemory(storage="sqlite:///test.db")

# Record something
memory.intake(event_type="conversation", content="Hello world")

# Remember it
results = memory.recall(query="greetings", limit=3)
assert len(results) > 0
assert results[0].content == "Hello world"

# Consolidate
report = await memory.consolidate()
assert report.memories_strengthened >= 0

# Check state
assert memory.state.drives.curiosity >= 0
assert memory.state.mood.valence >= -1

print("alive-memory works.")
```
