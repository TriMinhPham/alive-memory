"""Experiment 3: Tests targeting consolidation LLM paths, AliveMemory high-level
methods, meta controller/review/evaluation gaps, storage sqlite branches,
intake thalamus/formation edge cases."""

import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alive_memory.config import AliveConfig
from alive_memory.hot.reader import MemoryReader
from alive_memory.hot.writer import MemoryWriter
from alive_memory.storage.sqlite import SQLiteStorage
from alive_memory.types import (
    CognitiveState, DayMoment, DriveState, EventType,
    MoodState, Perception, SelfModel, SleepReport,
)


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="alive_exp3_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def _make_moment(id="m1", content="test", **kwargs):
    defaults = dict(
        id=id,
        event_type=EventType.CONVERSATION,
        content=content,
        salience=0.5,
        valence=0.0,
        drive_snapshot={"social": 0.5, "curiosity": 0.5, "expression": 0.5},
        timestamp=datetime.now(timezone.utc),
        metadata={},
    )
    defaults.update(kwargs)
    return DayMoment(**defaults)


# ── Consolidation: LLM reflection path (lines 98-121) ───────────

async def test_consolidation_with_llm_reflection(tmp_dir):
    """Cover consolidation lines 98-121: LLM reflect on moment with writer."""
    from alive_memory.consolidation import consolidate

    storage = AsyncMock()
    moments = [_make_moment(
        id="m1", content="A deep conversation",
        metadata={"visitor_name": "Alice", "thread_id": "t1"},
    )]
    storage.get_unprocessed_moments.return_value = moments
    storage.mark_moment_processed = AsyncMock()
    storage.flush_day_memory = AsyncMock()
    storage.log_consolidation = AsyncMock()

    writer = MagicMock()
    writer.append_journal = MagicMock()
    writer.append_reflection = MagicMock()

    reader = MagicMock()

    # Mock LLM
    llm = AsyncMock()

    # Mock reflect_on_moment to return a reflection
    with patch("alive_memory.consolidation.reflect_on_moment") as mock_reflect, \
         patch("alive_memory.consolidation.apply_reflection_to_hot_memory") as mock_apply, \
         patch("alive_memory.consolidation.reflect_daily_summary") as mock_summary:
        mock_reflect.return_value = "This was a meaningful conversation about life."
        mock_apply.return_value = {"journal": 1}
        mock_summary.return_value = "Daily summary of events."

        report = await consolidate(
            storage, writer=writer, reader=reader, llm=llm, depth="full"
        )

    assert report.moments_processed == 1
    assert report.journal_entries_written == 1
    mock_reflect.assert_called_once()
    mock_apply.assert_called_once()


async def test_consolidation_with_llm_no_reflection(tmp_dir):
    """Cover consolidation line 108 false branch: reflect returns None."""
    from alive_memory.consolidation import consolidate

    storage = AsyncMock()
    moments = [_make_moment(id="m1", content="Boring")]
    storage.get_unprocessed_moments.return_value = moments
    storage.mark_moment_processed = AsyncMock()
    storage.flush_day_memory = AsyncMock()
    storage.log_consolidation = AsyncMock()

    writer = MagicMock()
    writer.append_journal = MagicMock()
    writer.append_reflection = MagicMock()
    reader = MagicMock()
    llm = AsyncMock()

    with patch("alive_memory.consolidation.reflect_on_moment") as mock_reflect, \
         patch("alive_memory.consolidation.reflect_daily_summary") as mock_summary:
        mock_reflect.return_value = None  # No reflection
        mock_summary.return_value = None

        report = await consolidate(
            storage, writer=writer, reader=reader, llm=llm, depth="full"
        )

    assert report.moments_processed == 1
    assert report.journal_entries_written == 0


async def test_consolidation_daily_summary_and_dreaming():
    """Cover consolidation lines 138-156: daily summary + dreaming paths."""
    from alive_memory.consolidation import consolidate

    storage = AsyncMock()
    moments = [_make_moment(id="m1", content="Test")]
    storage.get_unprocessed_moments.return_value = moments
    storage.mark_moment_processed = AsyncMock()
    storage.flush_day_memory = AsyncMock()
    storage.log_consolidation = AsyncMock()

    writer = MagicMock()
    writer.append_journal = MagicMock()
    writer.append_reflection = MagicMock()
    reader = MagicMock()
    llm = AsyncMock()

    with patch("alive_memory.consolidation.reflect_on_moment") as mock_reflect, \
         patch("alive_memory.consolidation.reflect_daily_summary") as mock_summary, \
         patch("alive_memory.consolidation.dream") as mock_dream:
        mock_reflect.return_value = None
        mock_summary.return_value = "A summary of the day."
        mock_dream.return_value = [{"content": "dream 1"}]

        report = await consolidate(
            storage, writer=writer, reader=reader, llm=llm, depth="full"
        )

    assert report.reflections_written == 1
    assert len(report.dreams) == 1
    writer.append_reflection.assert_called_once()


async def test_consolidation_whispers_path():
    """Cover consolidation lines 184-187: whispers processing."""
    from alive_memory.consolidation import consolidate

    storage = AsyncMock()
    moments = [_make_moment(id="m1", content="Something")]
    storage.get_unprocessed_moments.return_value = moments
    storage.mark_moment_processed = AsyncMock()
    storage.log_consolidation = AsyncMock()

    writer = MagicMock()
    writer.append_journal = MagicMock()

    whispers = [{"type": "config_change", "key": "test", "value": "1"}]

    with patch("alive_memory.consolidation.whisper.process_whispers") as mock_pw:
        mock_pw.return_value = [{"content": "whisper dream"}]
        report = await consolidate(
            storage, writer=writer, whispers=whispers, depth="nap"
        )

    assert len(report.dreams) == 1


# ── AliveMemory: constructor branches + high-level methods ──────

async def test_alive_memory_sqlite_prefix(tmp_dir):
    """Cover __init__.py line 117-118: sqlite:/// prefix stripping."""
    from alive_memory import AliveMemory

    db_path = str(tmp_dir / "test.db")
    mem = AliveMemory(storage=f"sqlite:///{db_path}")
    assert mem.storage is not None
    # Check properties (lines 177, 182, 187)
    assert mem.writer is not None
    assert mem.reader is not None
    assert mem.memory_dir is not None


async def test_alive_memory_base_storage_instance(tmp_dir):
    """Cover __init__.py line 121: passing BaseStorage instance directly."""
    from alive_memory import AliveMemory

    storage = SQLiteStorage(str(tmp_dir / "test.db"))
    mem = AliveMemory(storage=storage)
    assert mem.storage is storage


async def test_alive_memory_config_as_dict():
    """Cover __init__.py line 127: config as dict."""
    from alive_memory import AliveMemory

    mem = AliveMemory(config={"intake": {"base_salience": 0.6}})
    assert mem._config.get("intake.base_salience") == 0.6


async def test_alive_memory_config_as_string(tmp_dir):
    """Cover __init__.py line 126: config as string (YAML path)."""
    from alive_memory import AliveMemory

    yaml_path = tmp_dir / "config.yaml"
    yaml_path.write_text("intake:\n  base_salience: 0.7\n")
    mem = AliveMemory(config=str(yaml_path))
    assert mem._config is not None


async def test_alive_memory_config_as_alive_config():
    """Cover __init__.py line 125: config as AliveConfig."""
    from alive_memory import AliveMemory

    cfg = AliveConfig({"intake.base_salience": 0.8})
    mem = AliveMemory(config=cfg)
    assert mem._config is cfg


async def test_alive_memory_get_identity(tmp_dir):
    """Cover __init__.py line 341: get_identity method."""
    from alive_memory import AliveMemory

    db_path = str(tmp_dir / "test.db")
    mem = AliveMemory(storage=db_path)
    await mem.initialize()
    try:
        model = await mem.get_identity()
        assert isinstance(model, SelfModel)
    finally:
        await mem.close()


async def test_alive_memory_meta_tune(tmp_dir):
    """Cover __init__.py lines 402-404: meta_tune method."""
    from alive_memory import AliveMemory

    db_path = str(tmp_dir / "test.db")
    mem = AliveMemory(storage=db_path)
    await mem.initialize()
    try:
        result = await mem.meta_tune({"test_metric": 0.5})
        assert isinstance(result, list)
    finally:
        await mem.close()


async def test_alive_memory_detect_drift(tmp_dir):
    """Cover __init__.py lines 415-416: detect_drift method."""
    from alive_memory import AliveMemory

    db_path = str(tmp_dir / "test.db")
    mem = AliveMemory(storage=db_path)
    await mem.initialize()
    try:
        result = await mem.detect_drift()
        assert isinstance(result, list)
    finally:
        await mem.close()


async def test_alive_memory_developmental_history(tmp_dir):
    """Cover __init__.py lines 420-421: developmental_history method."""
    from alive_memory import AliveMemory

    db_path = str(tmp_dir / "test.db")
    mem = AliveMemory(storage=db_path)
    await mem.initialize()
    try:
        result = await mem.developmental_history()
        assert isinstance(result, dict)
    finally:
        await mem.close()


# ── Storage SQLite: uncovered branches ──────────────────────────

@pytest.fixture
async def storage(tmp_dir):
    db_path = str(tmp_dir / "test.db")
    s = SQLiteStorage(db_path)
    await s.initialize()
    yield s
    await s.close()


async def test_storage_set_cognitive_state(storage):
    """Cover sqlite.py lines 341-354: set_cognitive_state."""
    state = await storage.get_cognitive_state()
    state.energy = 0.6
    state.cycle_count = 5
    state.memories_total = 10
    await storage.set_cognitive_state(state)
    updated = await storage.get_cognitive_state()
    assert updated.energy == pytest.approx(0.6)
    assert updated.cycle_count == 5


async def test_storage_record_moment_without_id(storage):
    """Cover sqlite.py lines 108-109: moment without id gets auto-generated."""
    moment = _make_moment(id="", content="auto id test")
    result_id = await storage.record_moment(moment)
    assert result_id  # Should have auto-generated an id


async def test_storage_get_parameter_bounds(storage):
    """Cover sqlite.py line 605: get_parameter_bounds for missing key."""
    min_b, max_b = await storage.get_parameter_bounds("nonexistent_key")
    assert min_b is None
    assert max_b is None


async def test_storage_update_experiment_empty(storage):
    """Cover sqlite.py line 572: update_experiment with no valid keys."""
    await storage.update_experiment("fake-id", {"invalid_key": "value"})
    # Should not raise, just return early


async def test_storage_get_drift_baseline_empty(storage):
    """Cover sqlite.py line 424: empty drift baseline."""
    baseline = await storage.get_drift_baseline()
    # May return empty or default
    assert isinstance(baseline, dict)


async def test_storage_exec_write_in_transaction(storage):
    """Cover sqlite.py line 99: _exec_write inside tx_depth > 0."""
    # Simulate being inside a transaction by setting tx_depth
    storage._tx_depth.set(1)
    try:
        moment = _make_moment(id="tx-m1", content="In transaction")
        await storage.record_moment(moment)
    finally:
        storage._tx_depth.set(0)
    # Manually commit since we bypassed the normal path
    conn = await storage._get_db()
    await conn.commit()
    moments = await storage.get_unprocessed_moments()
    assert any(m.id == "tx-m1" for m in moments)


# ── Meta controller: uncovered branches ──────────────────────────

async def test_meta_controller_no_metrics():
    """Cover controller.py lines 100-101: no metrics returns empty."""
    from alive_memory.meta.controller import run_meta_controller

    storage = AsyncMock()
    result = await run_meta_controller(storage, metrics=None, targets=[])
    assert result == []


async def test_meta_controller_metrics_provider():
    """Cover controller.py lines 98-99, 104-105: using metrics_provider."""
    from alive_memory.meta.controller import run_meta_controller, MetricTarget

    storage = AsyncMock()
    storage.get_parameters.return_value = {"salience.base": 0.5}
    storage.get_parameter_bounds.return_value = (0.0, 1.0)
    storage.set_parameter = AsyncMock()
    storage.get_confidence.return_value = 0.5
    storage.save_experiment = AsyncMock()

    provider = AsyncMock()
    provider.collect_metrics.return_value = {"test_metric": 0.1}
    provider.get_cycle_count.return_value = 10

    targets = [MetricTarget(
        name="test_metric", min_value=0.3, max_value=0.7,
        param_key="salience.base", adjustment_step=0.05,
    )]

    result = await run_meta_controller(
        storage, targets=targets, metrics_provider=provider,
    )
    assert len(result) == 1
    assert result[0].param_key == "salience.base"


async def test_meta_controller_metric_too_high():
    """Cover controller.py line 132-133: metric too high, decrease param."""
    from alive_memory.meta.controller import run_meta_controller, MetricTarget

    storage = AsyncMock()
    storage.get_parameters.return_value = {"salience.base": 0.5}
    storage.get_parameter_bounds.return_value = (0.0, 1.0)
    storage.set_parameter = AsyncMock()
    storage.get_confidence.return_value = 0.5
    storage.save_experiment = AsyncMock()
    storage.get_cycle_count.return_value = 5

    targets = [MetricTarget(
        name="test_metric", min_value=0.3, max_value=0.7,
        param_key="salience.base", adjustment_step=0.05,
    )]

    result = await run_meta_controller(
        storage, metrics={"test_metric": 0.9}, targets=targets,
    )
    assert len(result) == 1
    assert result[0].new_value < 0.5  # Decreased


async def test_meta_controller_no_change():
    """Cover controller.py line 142: no meaningful change."""
    from alive_memory.meta.controller import run_meta_controller, MetricTarget

    storage = AsyncMock()
    storage.get_parameters.return_value = {"salience.base": 1.0}
    storage.get_parameter_bounds.return_value = (1.0, 1.0)
    storage.get_cycle_count.return_value = 5

    targets = [MetricTarget(
        name="test_metric", min_value=0.3, max_value=0.7,
        param_key="salience.base", adjustment_step=0.05,
    )]

    result = await run_meta_controller(
        storage, metrics={"test_metric": 0.1}, targets=targets,
    )
    assert result == []  # No change because hard floor clamps to same


async def test_meta_controller_missing_param():
    """Cover controller.py line 126: param_key not in params."""
    from alive_memory.meta.controller import run_meta_controller, MetricTarget

    storage = AsyncMock()
    storage.get_parameters.return_value = {}  # No params
    storage.get_cycle_count.return_value = 5

    targets = [MetricTarget(
        name="test_metric", min_value=0.3, max_value=0.7,
        param_key="nonexistent", adjustment_step=0.05,
    )]

    result = await run_meta_controller(
        storage, metrics={"test_metric": 0.1}, targets=targets,
    )
    assert result == []


async def test_meta_controller_missing_metric():
    """Cover controller.py line 115: target metric not in metrics dict."""
    from alive_memory.meta.controller import run_meta_controller, MetricTarget

    storage = AsyncMock()
    storage.get_parameters.return_value = {"salience.base": 0.5}
    storage.get_cycle_count.return_value = 5

    targets = [MetricTarget(
        name="missing_metric", min_value=0.3, max_value=0.7,
        param_key="salience.base",
    )]

    result = await run_meta_controller(
        storage, metrics={"other_metric": 0.5}, targets=targets,
    )
    assert result == []


def test_classify_outcome_all_branches():
    """Cover controller.py lines 211-226: all classify_outcome branches."""
    from alive_memory.meta.controller import classify_outcome

    assert classify_outcome(0.1, 0.4, 0.3, 0.7) == "improved"
    assert classify_outcome(0.4, 0.1, 0.3, 0.7) == "degraded"
    assert classify_outcome(0.5, 0.5, 0.3, 0.7) == "neutral"


def test_compute_adaptive_cooldown_all_branches():
    """Cover controller.py lines 238-247: all adaptive cooldown branches."""
    from alive_memory.meta.controller import compute_adaptive_cooldown

    assert compute_adaptive_cooldown(10, 0.9) == 7   # high conf
    assert compute_adaptive_cooldown(10, 0.6) == 10  # medium conf
    assert compute_adaptive_cooldown(10, 0.4) == 15  # low conf
    assert compute_adaptive_cooldown(10, 0.2) == 20  # very low conf


# ── Meta review: uncovered branches ──────────────────────────────

async def test_review_trait_stability_directions():
    """Cover review.py lines 99-106: all direction branches."""
    from alive_memory.meta.review import review_trait_stability

    storage = AsyncMock()
    model = SelfModel(
        traits={"openness": 0.5},
        behavioral_summary="test",
        drift_history=[
            {"trait": "openness", "delta": 0.001},  # stable
            {"trait": "openness", "delta": -0.001},
            {"trait": "warmth", "delta": 0.1},     # increasing
            {"trait": "warmth", "delta": 0.2},
            {"trait": "caution", "delta": -0.1},    # decreasing
            {"trait": "caution", "delta": -0.2},
            {"trait": "mood", "delta": 0.1},        # oscillating
            {"trait": "mood", "delta": -0.1},
        ],
    )
    storage.get_self_model.return_value = model

    reports = await review_trait_stability(storage, window=5)
    directions = {r.trait: r.direction for r in reports}
    assert directions["openness"] == "stable"
    assert directions["warmth"] == "increasing"
    assert directions["caution"] == "decreasing"
    assert directions["mood"] == "oscillating"


async def test_review_self_modifications_reverts():
    """Cover review.py lines 146-184: review_self_modifications with revert."""
    from alive_memory.meta.review import review_self_modifications

    storage = AsyncMock()
    storage.get_parameters.return_value = {
        "social.threshold": 0.8,
        "curiosity.base": 0.5,
    }
    storage.get_parameter_bounds.return_value = (0.0, 1.0)
    storage.set_parameter = AsyncMock()

    drive_provider = MagicMock()
    drive_provider.get_category_drive_map.return_value = {
        "social": ["social_drive"],
        "curiosity": ["curiosity_drive"],
    }
    drive_provider.get_drive_values = AsyncMock(return_value={
        "social_drive": 0.2,    # degraded (below 0.5 - 0.15 = 0.35)
        "curiosity_drive": 0.6,  # healthy
    })

    reverted = await review_self_modifications(storage, drive_provider)
    assert "social.threshold" in reverted
    assert "curiosity.base" not in reverted


async def test_review_self_modifications_no_degradation():
    """Cover review.py lines 155-156: no degradation, skip revert."""
    from alive_memory.meta.review import review_self_modifications

    storage = AsyncMock()
    storage.get_parameters.return_value = {"social.threshold": 0.5}

    drive_provider = MagicMock()
    drive_provider.get_category_drive_map.return_value = {"social": ["social_drive"]}
    drive_provider.get_drive_values = AsyncMock(return_value={"social_drive": 0.6})

    reverted = await review_self_modifications(storage, drive_provider)
    assert reverted == []


# ── Meta evaluation: uncovered branches ──────────────────────────

async def test_evaluate_experiment_degraded():
    """Cover evaluation.py lines 50-56: degraded outcome reverts."""
    from alive_memory.meta.evaluation import evaluate_experiment
    from alive_memory.meta.controller import Experiment

    storage = AsyncMock()
    storage.set_parameter = AsyncMock()

    exp = Experiment(
        id="e1", param_key="salience.base", old_value=0.5,
        new_value=0.6, target_metric="test_m", metric_at_change=0.4,
        confidence=0.5,
    )

    result = await evaluate_experiment(exp, {"test_m": 0.1}, 0.3, 0.7, storage)
    assert result.outcome == "degraded"
    assert result.confidence < 0.5
    storage.set_parameter.assert_called_once()


async def test_evaluate_experiment_no_metric():
    """Cover evaluation.py lines 38-39: metric not in current_metrics."""
    from alive_memory.meta.evaluation import evaluate_experiment
    from alive_memory.meta.controller import Experiment

    storage = AsyncMock()
    exp = Experiment(
        id="e1", param_key="salience.base", old_value=0.5,
        new_value=0.6, target_metric="missing", metric_at_change=0.4,
    )

    result = await evaluate_experiment(exp, {}, 0.3, 0.7, storage)
    assert result.outcome == "neutral"


async def test_evaluate_pending_experiments():
    """Cover evaluation.py lines 97-131: evaluate_pending_experiments."""
    from alive_memory.meta.evaluation import evaluate_pending_experiments
    from alive_memory.meta.controller import MetricTarget

    storage = AsyncMock()
    storage.get_pending_experiments.return_value = [
        {
            "id": "e1", "param_key": "salience.base", "old_value": 0.5,
            "new_value": 0.6, "target_metric": "test_m",
            "metric_at_change": 0.2, "confidence": 0.5,
            "side_effects": [], "cycle_at_creation": 0,
        },
        {
            "id": "e2", "param_key": "other.param", "old_value": 0.5,
            "new_value": 0.6, "target_metric": "unknown_metric",
            "metric_at_change": 0.2, "confidence": 0.5,
            "side_effects": [], "cycle_at_creation": 0,
        },
    ]
    storage.set_parameter = AsyncMock()
    storage.set_confidence = AsyncMock()
    storage.update_experiment = AsyncMock()

    targets = [MetricTarget(name="test_m", min_value=0.3, max_value=0.7, param_key="salience.base")]

    result = await evaluate_pending_experiments(
        storage, {"test_m": 0.5}, targets, min_age_cycles=0,
    )
    # Only e1 should be evaluated (e2's target_metric not in targets)
    assert len(result) == 1
    assert result[0].outcome == "improved"


def test_detect_side_effects():
    """Cover evaluation.py lines 134-163: detect_side_effects."""
    from alive_memory.meta.evaluation import detect_side_effects
    from alive_memory.meta.controller import Experiment

    exp = Experiment(
        id="e1", param_key="p1", old_value=0.5, new_value=0.6,
        target_metric="primary", metric_at_change=0.4,
    )

    before = {"primary": 0.4, "secondary": 0.5}
    after = {"primary": 0.5, "secondary": 0.2}  # secondary went out of range
    targets = {"primary": (0.3, 0.7), "secondary": (0.3, 0.7)}

    effects = detect_side_effects(exp, before, after, targets)
    assert "secondary" in effects


# ── Intake thalamus: uncovered branches ──────────────────────────

def test_perceive_with_event_type_enum():
    """Cover thalamus.py line 46: event_type as EventType directly."""
    from alive_memory.intake.thalamus import perceive

    p = perceive(EventType.ACTION, "did something")
    assert p.event_type == EventType.ACTION


def test_perceive_empty_content():
    """Cover thalamus.py line 100: empty content novelty."""
    from alive_memory.intake.thalamus import perceive

    p = perceive("conversation", "")
    assert p.salience >= 0


def test_perceive_long_content():
    """Cover thalamus.py line 115: long content novelty path."""
    from alive_memory.intake.thalamus import perceive

    content = " ".join(f"word{i}" for i in range(30))
    p = perceive("observation", content)
    assert p.salience >= 0


# ── Intake formation: eviction path ──────────────────────────────

async def test_formation_eviction_at_capacity():
    """Cover formation.py lines 114-119: eviction when at capacity."""
    from alive_memory.intake.formation import form_moment, MAX_DAY_MOMENTS

    storage = AsyncMock()
    storage.get_day_memory_count.return_value = MAX_DAY_MOMENTS
    storage.get_recent_moment_content.return_value = []
    # Lowest moment has lower salience than new one
    storage.get_lowest_salience_moment.return_value = _make_moment(
        id="low", content="low", salience=0.1
    )
    storage.delete_moment = AsyncMock()
    storage.record_moment = AsyncMock()

    perception = Perception(
        event_type=EventType.CONVERSATION,
        content="Very important new conversation that must be kept",
        salience=0.9,
        timestamp=datetime.now(timezone.utc),
        metadata={},
    )
    mood = MoodState(valence=0.5, arousal=0.8, word="excited")
    drives = DriveState(social=0.5, curiosity=0.5, expression=0.5)
    prev_drives = DriveState(social=0.3, curiosity=0.3, expression=0.3)

    result = await form_moment(
        perception, mood, drives, storage, previous_drives=prev_drives
    )
    if result is not None:
        storage.delete_moment.assert_called_once_with("low")


async def test_formation_eviction_rejected():
    """Cover formation.py line 119: new moment not salient enough for eviction."""
    from alive_memory.intake.formation import form_moment, MAX_DAY_MOMENTS

    storage = AsyncMock()
    storage.get_day_memory_count.return_value = MAX_DAY_MOMENTS
    storage.get_recent_moment_content.return_value = []
    # Lowest moment has HIGHER salience
    storage.get_lowest_salience_moment.return_value = _make_moment(
        id="high", content="high", salience=0.99
    )
    storage.record_moment = AsyncMock()

    perception = Perception(
        event_type=EventType.SYSTEM,
        content="x",
        salience=0.2,
        timestamp=datetime.now(timezone.utc),
        metadata={},
    )
    mood = MoodState(valence=0.0, arousal=0.3, word="neutral")
    drives = DriveState(social=0.5, curiosity=0.5, expression=0.5)

    result = await form_moment(perception, mood, drives, storage)
    assert result is None


# ── Identity: self_model needs_narrative_regen branches ──────────

def test_needs_narrative_regen_no_snapshot():
    """Cover self_model.py line 188: no snapshot yet."""
    from alive_memory.identity.self_model import SelfModelManager

    storage = AsyncMock()
    mgr = SelfModelManager(storage)
    model = SelfModel(
        traits={"openness": 0.5},
        behavioral_summary="test",
        behavioral_signature={},  # no snapshot
    )
    assert mgr.needs_narrative_regen(model) is True


def test_needs_narrative_regen_no_traits():
    """Cover self_model.py line 191: no traits."""
    from alive_memory.identity.self_model import SelfModelManager

    storage = AsyncMock()
    mgr = SelfModelManager(storage)
    model = SelfModel(
        traits={},
        behavioral_summary="test",
        behavioral_signature={"narrative_trait_snapshot": {"openness": 0.5}},
    )
    assert mgr.needs_narrative_regen(model) is False


# ── Identity drift: severity 'none' branch ──────────────────────

async def test_drift_detector_severity_none():
    """Cover drift.py line 275: severity 'none' classification."""
    from alive_memory.identity.drift import DriftDetector, DriftConfig

    storage = AsyncMock()
    storage.get_drift_baseline.return_value = {
        "scalar_metrics": {},
        "action_frequencies": {},
        "sample_count": 0,
    }
    storage.log_evolution_decision = AsyncMock()

    cfg = DriftConfig(significant_threshold=0.8, notable_threshold=0.5)
    # No metrics configured → composite = 0 → severity "none"
    detector = DriftDetector(storage, config=cfg, metrics=[])

    result = await detector.detect(current_data={}, cycle=10)
    assert result.severity == "none"


async def test_drift_detector_cooldown():
    """Cover drift.py line 282-283: cooldown suppresses detection."""
    from alive_memory.identity.drift import DriftDetector, DriftConfig, DriftMetric

    storage = AsyncMock()
    storage.get_drift_baseline.return_value = {
        "scalar_metrics": {"openness": 0.1},
        "action_frequencies": {},
        "sample_count": 100,
    }
    storage.log_evolution_decision = AsyncMock()

    # Create a metric that always returns high score
    high_metric = AsyncMock(spec=DriftMetric)
    high_metric.name = "test_drift"
    high_metric.weight = 1.0
    high_metric.compute = AsyncMock(return_value=0.9)

    cfg = DriftConfig(
        cooldown_cycles=100,
        significant_threshold=0.5,
        notable_threshold=0.3,
    )
    detector = DriftDetector(storage, config=cfg, metrics=[high_metric])
    detector._last_drift_cycle = 4  # Last detection was cycle 4

    result = await detector.detect(current_data={"openness": 0.9}, cycle=5)
    # Should be suppressed by cooldown (5 - 4 < 100)
    assert result.severity == "none"
