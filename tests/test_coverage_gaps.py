"""Tests targeting coverage gaps in config, hot/reader, recall, consolidation, and intake modules."""

import os
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alive_memory.config import AliveConfig, _parse_simple_yaml, _parse_value, _deep_merge
from alive_memory.hot.reader import MemoryReader, _safe_filename
from alive_memory.hot.writer import MemoryWriter
from alive_memory.recall.hippocampus import recall
from alive_memory.recall.weighting import score_grep_result, decay_strength
from alive_memory.recall.context import mood_congruent_recall, drive_coupled_recall
from alive_memory.intake.affect import apply_affect, compute_valence, time_dilation
from alive_memory.consolidation.reflection import _extract_keywords
from alive_memory.consolidation.memory_updates import apply_reflection_to_hot_memory
from alive_memory.consolidation.dreaming import dream
from alive_memory.types import (
    CognitiveState, DayMoment, DriveState, EventType,
    MoodState, Perception, SelfModel,
)


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="alive_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


# ── Config: _parse_simple_yaml ─────────────────────────────────

def test_parse_simple_yaml(tmp_dir):
    yaml_file = tmp_dir / "test.yaml"
    yaml_file.write_text(
        "memory:\n"
        "  embedding_dimensions: 512\n"
        "  enabled: true\n"
        "  rate: 0.5\n"
        "  name: hello\n"
        "  nothing: null\n"
        "  # this is a comment\n"
        "  inline: value  # inline comment\n"
        "\n"
        "recall:\n"
        "  limit: 10\n"
    )
    result = _parse_simple_yaml(yaml_file)
    assert result["memory"]["embedding_dimensions"] == 512
    assert result["memory"]["enabled"] is True
    assert result["memory"]["rate"] == 0.5
    assert result["memory"]["name"] == "hello"
    assert result["memory"]["nothing"] is None
    assert result["memory"]["inline"] == "value"
    assert result["recall"]["limit"] == 10


def test_parse_value_types():
    assert _parse_value("true") is True
    assert _parse_value("True") is True
    assert _parse_value("false") is False
    assert _parse_value("False") is False
    assert _parse_value("null") is None
    assert _parse_value("None") is None
    assert _parse_value("~") is None
    assert _parse_value("42") == 42
    assert _parse_value("3.14") == 3.14
    assert _parse_value("'hello'") == "hello"
    assert _parse_value('"world"') == "world"
    assert _parse_value("plain") == "plain"


def test_config_from_yaml_file(tmp_dir):
    yaml_file = tmp_dir / "config.yaml"
    yaml_file.write_text("memory:\n  embedding_dimensions: 768\n")
    cfg = AliveConfig(str(yaml_file))
    assert cfg.get("memory.embedding_dimensions") == 768


def test_config_data_property():
    cfg = AliveConfig({"foo": "bar"})
    assert "foo" in cfg.data


def test_config_set_nested():
    cfg = AliveConfig()
    cfg.set("a.b.c", 42)
    assert cfg.get("a.b.c") == 42


def test_deep_merge():
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    override = {"a": {"y": 99, "z": 100}, "c": 4}
    result = _deep_merge(base, override)
    assert result["a"]["x"] == 1
    assert result["a"]["y"] == 99
    assert result["a"]["z"] == 100
    assert result["c"] == 4


# ── Hot Reader ──────────────────────────────────────────────────

def test_reader_grep_memory(tmp_dir):
    journal_dir = tmp_dir / "journal"
    journal_dir.mkdir()
    (journal_dir / "2024-01-01.md").write_text("# Journal\n## Morning\nThe cat sat on the mat.\n")

    reader = MemoryReader(tmp_dir)
    results = reader.grep_memory("cat mat")
    assert len(results) >= 1
    assert results[0]["subdir"] == "journal"
    assert "cat" in results[0]["match"].lower()


def test_reader_grep_empty_query(tmp_dir):
    reader = MemoryReader(tmp_dir)
    assert reader.grep_memory("") == []
    assert reader.grep_memory("x") == []  # single char filtered


def test_reader_grep_limit(tmp_dir):
    journal_dir = tmp_dir / "journal"
    journal_dir.mkdir()
    lines = "\n".join(f"line {i} with keyword" for i in range(50))
    (journal_dir / "test.md").write_text(lines)

    reader = MemoryReader(tmp_dir)
    results = reader.grep_memory("keyword", limit=5)
    assert len(results) == 5


def test_reader_grep_specific_subdirs(tmp_dir):
    visitors_dir = tmp_dir / "visitors"
    visitors_dir.mkdir()
    (visitors_dir / "alice.md").write_text("Alice visited the shop\n")

    journal_dir = tmp_dir / "journal"
    journal_dir.mkdir()
    (journal_dir / "test.md").write_text("Alice was mentioned\n")

    reader = MemoryReader(tmp_dir)
    results = reader.grep_memory("alice", subdirs=["visitors"])
    assert all(r["subdir"] == "visitors" for r in results)


def test_reader_read_visitor(tmp_dir):
    visitors_dir = tmp_dir / "visitors"
    visitors_dir.mkdir()
    (visitors_dir / "bob_smith.md").write_text("Bob is a regular.\n")

    reader = MemoryReader(tmp_dir)
    content = reader.read_visitor("Bob Smith")
    assert content == "Bob is a regular.\n"
    assert reader.read_visitor("nonexistent") is None


def test_reader_list_visitors(tmp_dir):
    visitors_dir = tmp_dir / "visitors"
    visitors_dir.mkdir()
    (visitors_dir / "alice.md").write_text("x")
    (visitors_dir / "bob_jones.md").write_text("y")

    reader = MemoryReader(tmp_dir)
    visitors = reader.list_visitors()
    assert "alice" in visitors
    assert "bob jones" in visitors


def test_reader_list_visitors_empty(tmp_dir):
    reader = MemoryReader(tmp_dir)
    assert reader.list_visitors() == []


def test_reader_read_recent_journal(tmp_dir):
    journal_dir = tmp_dir / "journal"
    journal_dir.mkdir()
    (journal_dir / "2024-01-03.md").write_text(
        "# Journal\n## Entry 1\nSomething happened\n## Entry 2\nAnother thing\n"
    )
    (journal_dir / "2024-01-02.md").write_text("# Journal\n## Old\nOlder event\n")

    reader = MemoryReader(tmp_dir)
    entries = reader.read_recent_journal(days=3)
    assert len(entries) >= 1


def test_reader_read_recent_journal_empty(tmp_dir):
    reader = MemoryReader(tmp_dir)
    assert reader.read_recent_journal() == []


def test_reader_read_self_knowledge(tmp_dir):
    self_dir = tmp_dir / "self"
    self_dir.mkdir()
    (self_dir / "identity.md").write_text("I am a shopkeeper.\n")

    reader = MemoryReader(tmp_dir)
    content = reader.read_self_knowledge("identity")
    assert "shopkeeper" in content
    assert reader.read_self_knowledge("nonexistent") is None


def test_reader_list_self_files(tmp_dir):
    self_dir = tmp_dir / "self"
    self_dir.mkdir()
    (self_dir / "identity.md").write_text("x")
    (self_dir / "values.md").write_text("y")

    reader = MemoryReader(tmp_dir)
    files = reader.list_self_files()
    assert "identity" in files
    assert "values" in files


def test_reader_list_self_files_empty(tmp_dir):
    reader = MemoryReader(tmp_dir)
    assert reader.list_self_files() == []


def test_reader_read_recent_reflections(tmp_dir):
    refl_dir = tmp_dir / "reflections"
    refl_dir.mkdir()
    (refl_dir / "2024-01-01.md").write_text(
        "# Reflections\n---\nFirst reflection\n---\nSecond reflection\n"
    )

    reader = MemoryReader(tmp_dir)
    entries = reader.read_recent_reflections(days=3)
    assert len(entries) >= 1


def test_reader_read_recent_reflections_empty(tmp_dir):
    reader = MemoryReader(tmp_dir)
    assert reader.read_recent_reflections() == []


def test_reader_read_thread(tmp_dir):
    threads_dir = tmp_dir / "threads"
    threads_dir.mkdir()
    (threads_dir / "abc123.md").write_text("Thread content\n")

    reader = MemoryReader(tmp_dir)
    content = reader.read_thread("abc123")
    assert "Thread content" in content
    assert reader.read_thread("nonexistent") is None


def test_reader_list_threads(tmp_dir):
    threads_dir = tmp_dir / "threads"
    threads_dir.mkdir()
    (threads_dir / "t1.md").write_text("x")
    (threads_dir / "t2.md").write_text("y")

    reader = MemoryReader(tmp_dir)
    threads = reader.list_threads()
    assert "t1" in threads
    assert "t2" in threads


def test_reader_list_threads_empty(tmp_dir):
    reader = MemoryReader(tmp_dir)
    assert reader.list_threads() == []


def test_reader_root_property(tmp_dir):
    reader = MemoryReader(tmp_dir)
    assert reader.root == tmp_dir


def test_safe_filename():
    assert _safe_filename("Bob Smith") == "bob_smith"
    assert _safe_filename("Alice!@#$") == "alice"
    assert _safe_filename("  ") == "unnamed"
    assert _safe_filename("file.txt") == "file.txt"


# ── Recall: Hippocampus ────────────────────────────────────────

def _make_state(**kwargs):
    defaults = dict(
        mood=MoodState(valence=0.0, arousal=0.5, word="neutral"),
        energy=0.8,
        drives=DriveState(social=0.5, curiosity=0.5, expression=0.5),
        cycle_count=1,
    )
    defaults.update(kwargs)
    return CognitiveState(**defaults)


def _make_moment(id="m1", content="test", **kwargs):
    defaults = dict(
        id=id,
        event_type=EventType.CONVERSATION,
        content=content,
        salience=0.5,
        valence=0.0,
        drive_snapshot={"social": 0.5, "curiosity": 0.5, "expression": 0.5},
        timestamp=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return DayMoment(**defaults)


@pytest.fixture
def state():
    return _make_state()


async def test_recall_with_grep_hits(tmp_dir, state):
    journal_dir = tmp_dir / "journal"
    journal_dir.mkdir()
    (journal_dir / "2024-01-01.md").write_text("# Journal\n## Entry\nThe weather was sunny and warm\n")
    self_dir = tmp_dir / "self"
    self_dir.mkdir()
    (self_dir / "identity.md").write_text("I am a shopkeeper.\n")

    reader = MemoryReader(tmp_dir)
    ctx = await recall("weather sunny", reader, state)
    assert ctx.query == "weather sunny"
    assert ctx.total_hits >= 1


async def test_recall_empty_query(tmp_dir, state):
    reader = MemoryReader(tmp_dir)
    ctx = await recall("", reader, state)
    assert ctx.total_hits == 0


async def test_recall_fills_self_knowledge(tmp_dir, state):
    self_dir = tmp_dir / "self"
    self_dir.mkdir()
    (self_dir / "identity.md").write_text("I am a friendly bot.\n")

    reader = MemoryReader(tmp_dir)
    ctx = await recall("something random", reader, state)
    assert len(ctx.self_knowledge) >= 1


# ── Recall: Weighting ─────────────────────────────────────────

def test_score_grep_result(state):
    score_self = score_grep_result("some content about identity", "self", state)
    score_thread = score_grep_result("some content about thread", "threads", state)
    assert score_self > score_thread  # self has higher priority

    score_long = score_grep_result("a " * 100, "journal", state)
    score_short = score_grep_result("a", "journal", state)
    assert score_long >= score_short


def test_decay_strength_with_config():
    cfg = AliveConfig({"consolidation": {"decay_rate": 0.02, "decay_floor": 0.1}})
    result = decay_strength(1.0, 10.0, config=cfg)
    assert result == max(0.1, 1.0 - 0.02 * 10.0)


# ── Recall: Context ─────────────────────────────────────────────

async def test_mood_congruent_recall(tmp_dir, state):
    reader = MemoryReader(tmp_dir)
    ctx = await mood_congruent_recall("test query", reader, state)
    assert ctx.query == "test query"


async def test_drive_coupled_recall(tmp_dir, state):
    reader = MemoryReader(tmp_dir)
    ctx = await drive_coupled_recall("curiosity", reader, state)
    assert ctx.query == "curiosity"


# ── Intake: Affect ─────────────────────────────────────────────

def test_apply_affect_negative_mood():
    p = Perception(
        event_type=EventType.CONVERSATION,
        content="test",
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    mood = MoodState(valence=-0.5, arousal=0.5, word="sad")
    drives = DriveState(social=0.5, curiosity=0.5, expression=0.5)
    result = apply_affect(p, mood, drives)
    assert result.salience == 0.6  # +0.1 boost


def test_apply_affect_positive_mood_negative_event():
    p = Perception(
        event_type=EventType.CONVERSATION,
        content="test",
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
        metadata={"valence": -0.5},
    )
    mood = MoodState(valence=0.5, arousal=0.5, word="happy")
    drives = DriveState(social=0.5, curiosity=0.5, expression=0.5)
    result = apply_affect(p, mood, drives)
    assert result.salience == 0.45  # -0.05 dampening


def test_compute_valence_positive():
    mood = MoodState(valence=0.0, arousal=0.5, word="neutral")
    v = compute_valence("I love this beautiful wonderful day", mood)
    assert v > 0


def test_compute_valence_negative():
    mood = MoodState(valence=0.0, arousal=0.5, word="neutral")
    v = compute_valence("I hate this terrible ugly day", mood)
    assert v < 0


def test_compute_valence_neutral():
    mood = MoodState(valence=0.0, arousal=0.5, word="neutral")
    v = compute_valence("the sky is blue", mood)
    assert v == 0.0


def test_compute_valence_mood_bias():
    happy = MoodState(valence=0.8, arousal=0.5, word="happy")
    sad = MoodState(valence=-0.8, arousal=0.5, word="sad")
    v_happy = compute_valence("the sky is blue", happy)
    v_sad = compute_valence("the sky is blue", sad)
    assert v_happy > v_sad


def test_time_dilation():
    # High social hunger → time drags
    drives_social = DriveState(social=0.9, curiosity=0.3, expression=0.5)
    d_social = time_dilation(drives_social)
    assert d_social >= 0.7

    # High curiosity → time flies
    drives_curious = DriveState(social=0.3, curiosity=0.9, expression=0.5)
    d_curious = time_dilation(drives_curious)
    assert d_curious <= 1.3


# ── Consolidation: Reflection (keyword extraction) ──────────────

def test_extract_keywords():
    kw = _extract_keywords("The quick brown fox jumped over the lazy dog", max_keywords=3)
    words = kw.split()
    assert len(words) <= 3
    assert "the" not in words  # stop word
    assert "quick" in words or "brown" in words or "jumped" in words


def test_extract_keywords_empty():
    assert _extract_keywords("") == ""
    assert _extract_keywords("the a an is") == ""  # all stop words


def test_extract_keywords_deduplication():
    kw = _extract_keywords("hello hello hello world world", max_keywords=5)
    words = kw.split()
    assert words.count("hello") == 1
    assert words.count("world") == 1


# ── Consolidation: Memory Updates ───────────────────────────────

def test_apply_reflection_to_hot_memory(tmp_dir):
    writer = MemoryWriter(tmp_dir)
    moment = _make_moment(id="test-moment-1", content="A visitor came by", salience=0.7, valence=0.3)

    counts = apply_reflection_to_hot_memory(
        moment,
        "This was a meaningful visit.",
        writer,
        visitor_name="Alice",
        thread_id="thread-1",
        self_updates={"identity": "I value connections."},
    )

    assert counts["journal"] == 1
    assert counts["visitor"] == 1
    assert counts["thread"] == 1
    assert counts["self"] == 1


def test_apply_reflection_minimal(tmp_dir):
    writer = MemoryWriter(tmp_dir)
    moment = _make_moment(id="test-moment-2", content="A quiet day",
                          event_type=EventType.OBSERVATION, salience=0.3)

    counts = apply_reflection_to_hot_memory(moment, "Nothing notable.", writer)
    assert counts["journal"] == 1
    assert counts["visitor"] == 0
    assert counts["thread"] == 0
    assert counts["self"] == 0


# ── Consolidation: Dreaming ─────────────────────────────────────

async def test_dream_too_few_moments():
    llm = AsyncMock()
    moments = [_make_moment(id="m1", content="Only one moment")]
    result = await dream(moments, llm=llm, count=2)
    assert result == []  # needs >= 2 moments


async def test_dream_with_moments():
    llm = AsyncMock()
    llm.complete.return_value = MagicMock(text="A dreamy recombination.")

    moments = [_make_moment(id=f"m{i}", content=f"Moment {i} about interesting things") for i in range(5)]
    result = await dream(moments, llm=llm, count=2)
    assert len(result) == 2
    assert all("dreamy" in d.lower() for d in result)


async def test_dream_with_cold_echoes():
    llm = AsyncMock()
    llm.complete.return_value = MagicMock(text="Echo dream.")

    moments = [_make_moment(id=f"m{i}", content=f"Moment {i}") for i in range(3)]
    cold_echoes = [{"content": "An old memory from long ago"}]
    result = await dream(moments, llm=llm, cold_echoes=cold_echoes, count=1)
    assert len(result) == 1


async def test_dream_llm_failure():
    llm = AsyncMock()
    llm.complete.side_effect = Exception("LLM failed")

    moments = [_make_moment(id=f"m{i}", content=f"Moment {i}") for i in range(3)]
    result = await dream(moments, llm=llm, count=2)
    assert result == []


# ── Consolidation: Reflection (LLM-based) ──────────────────────

async def test_reflect_on_moment():
    from alive_memory.consolidation.reflection import reflect_on_moment

    llm = AsyncMock()
    llm.complete.return_value = MagicMock(text="This was a meaningful moment.")

    storage = AsyncMock()
    storage.get_self_model.return_value = SelfModel(traits={"kind": 0.8})
    storage.get_cognitive_state.return_value = _make_state(
        mood=MoodState(valence=0.3, arousal=0.5, word="content"),
    )

    tmp = tempfile.mkdtemp()
    try:
        reader = MemoryReader(tmp)
        moment = _make_moment(
            id="m1", content="Someone shared a story about their childhood garden",
            salience=0.7, valence=0.4,
        )
        result = await reflect_on_moment(
            moment, reader=reader, storage=storage, llm=llm,
            cold_echoes=[{"content": "An old memory about gardens"}],
        )
        assert "meaningful" in result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def test_reflect_on_moment_llm_failure():
    from alive_memory.consolidation.reflection import reflect_on_moment

    llm = AsyncMock()
    llm.complete.side_effect = Exception("fail")

    storage = AsyncMock()
    storage.get_self_model.return_value = SelfModel(traits={})
    storage.get_cognitive_state.return_value = _make_state()

    tmp = tempfile.mkdtemp()
    try:
        reader = MemoryReader(tmp)
        moment = _make_moment(id="m1", content="test")
        result = await reflect_on_moment(moment, reader=reader, storage=storage, llm=llm)
        assert result == ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def test_reflect_daily_summary():
    from alive_memory.consolidation.reflection import reflect_daily_summary

    llm = AsyncMock()
    llm.complete.return_value = MagicMock(text="Today was a day of discovery.")

    storage = AsyncMock()
    storage.get_self_model.return_value = SelfModel(traits={"curious": 0.9})
    storage.get_cognitive_state.return_value = _make_state(
        mood=MoodState(valence=0.5, arousal=0.6, word="excited"),
        drives=DriveState(social=0.5, curiosity=0.8, expression=0.5),
    )

    moments = [_make_moment(id=f"m{i}", content=f"Moment {i} content") for i in range(3)]
    result = await reflect_daily_summary(moments, storage=storage, llm=llm)
    assert "discovery" in result


async def test_reflect_daily_summary_empty():
    from alive_memory.consolidation.reflection import reflect_daily_summary

    llm = AsyncMock()
    storage = AsyncMock()
    result = await reflect_daily_summary([], storage=storage, llm=llm)
    assert result == ""


async def test_reflect_daily_summary_failure():
    from alive_memory.consolidation.reflection import reflect_daily_summary

    llm = AsyncMock()
    llm.complete.side_effect = Exception("fail")

    storage = AsyncMock()
    storage.get_self_model.return_value = SelfModel(traits={})
    storage.get_cognitive_state.return_value = _make_state()

    moments = [_make_moment(id="m1", content="test")]
    result = await reflect_daily_summary(moments, storage=storage, llm=llm)
    assert result == ""
