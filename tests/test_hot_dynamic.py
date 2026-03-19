"""Tests for bounded hot memory with dynamic categories (Phase 2).

Tests:
- Dynamic subdir creation and sanitization
- list_subdirs() dynamic enumeration
- Grep across dynamic subdirs
- Prune old files
- append_to_category routing
- Max subdirs cap
- Rewrite file (distillation)
- Token budget estimation
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from alive_memory.hot.reader import MemoryReader
from alive_memory.hot.writer import MemoryWriter


@pytest.fixture
def hot_dir():
    tmp = tempfile.mkdtemp(prefix="hot_test_")
    yield tmp
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# ── Dynamic subdirs ──────────────────────────────────────────────────


def test_pinned_subdirs_created_at_init(hot_dir: str) -> None:
    writer = MemoryWriter(hot_dir)
    subdirs = writer.list_subdirs()
    assert "journal" in subdirs
    assert "self" in subdirs
    assert "visitors" in subdirs


def test_custom_pinned_subdirs(hot_dir: str) -> None:
    writer = MemoryWriter(hot_dir, pinned_subdirs=["journal", "self", "inventory"])
    subdirs = writer.list_subdirs()
    assert "inventory" in subdirs
    assert "journal" in subdirs


def test_append_to_category_creates_subdir(hot_dir: str) -> None:
    writer = MemoryWriter(hot_dir)
    assert "complaints" not in writer.list_subdirs()
    writer.append_to_category("complaints", "Customer unhappy about broken vase")
    assert "complaints" in writer.list_subdirs()


def test_sanitize_subdir_names(hot_dir: str) -> None:
    writer = MemoryWriter(hot_dir)
    # Spaces and caps → hyphens and lowercase
    writer.append_to_category("Customer Feedback", "test")
    assert "customer-feedback" in writer.list_subdirs()


def test_sanitize_rejects_empty_and_dots(hot_dir: str) -> None:
    writer = MemoryWriter(hot_dir)
    with pytest.raises(ValueError):
        writer._sanitize_subdir("..")
    with pytest.raises(ValueError):
        writer._sanitize_subdir("")
    with pytest.raises(ValueError):
        writer._sanitize_subdir("...")


def test_sanitize_strips_path_traversal(hot_dir: str) -> None:
    """Path traversal chars are stripped, result is safe."""
    writer = MemoryWriter(hot_dir)
    assert writer._sanitize_subdir("../etc/passwd") == "etc-passwd"
    assert writer._sanitize_subdir("foo/bar") == "foo-bar"


def test_max_subdirs_cap(hot_dir: str) -> None:
    writer = MemoryWriter(hot_dir, pinned_subdirs=["journal"], max_subdirs=3)
    writer.append_to_category("cat1", "test")
    writer.append_to_category("cat2", "test")
    # journal + cat1 + cat2 = 3, at cap
    with pytest.raises(ValueError, match="Max subdirectories"):
        writer.append_to_category("cat3", "test")


# ── Grep with dynamic subdirs ────────────────────────────────────────


def test_grep_finds_content_in_dynamic_subdir(hot_dir: str) -> None:
    writer = MemoryWriter(hot_dir)
    writer.append_to_category("complaints", "The customer complained about the broken vase")

    reader = MemoryReader(hot_dir)
    results = reader.grep_memory("broken vase")
    assert len(results) > 0
    assert results[0]["subdir"] == "complaints"


def test_reader_list_subdirs(hot_dir: str) -> None:
    writer = MemoryWriter(hot_dir)
    writer.append_to_category("inventory", "10 blue widgets")
    reader = MemoryReader(hot_dir)
    assert "inventory" in reader.list_subdirs()


# ── Pruning ───────────────────────────────────────────────────────────


def test_prune_old_files(hot_dir: str) -> None:
    writer = MemoryWriter(hot_dir)
    # Create files with old dates in filenames
    old_date = datetime.now(UTC) - timedelta(days=10)
    old_name = old_date.strftime("%Y-%m-%d") + ".md"
    journal_dir = Path(hot_dir) / "journal"
    (journal_dir / old_name).write_text("old content")

    recent_date = datetime.now(UTC) - timedelta(days=1)
    recent_name = recent_date.strftime("%Y-%m-%d") + ".md"
    (journal_dir / recent_name).write_text("recent content")

    pruned = writer.prune_old_files("journal", max_age_days=7)
    assert pruned == 1
    assert not (journal_dir / old_name).exists()
    assert (journal_dir / recent_name).exists()


def test_prune_skips_non_date_files(hot_dir: str) -> None:
    writer = MemoryWriter(hot_dir)
    journal_dir = Path(hot_dir) / "journal"
    (journal_dir / "notes.md").write_text("misc notes")
    pruned = writer.prune_old_files("journal", max_age_days=0)
    assert pruned == 0
    assert (journal_dir / "notes.md").exists()


# ── Rewrite (distillation) ───────────────────────────────────────────


def test_rewrite_file(hot_dir: str) -> None:
    writer = MemoryWriter(hot_dir)
    writer.append_journal("entry 1")
    writer.append_journal("entry 2")

    # Read current content
    reader = MemoryReader(hot_dir)
    journal_dir = Path(hot_dir) / "journal"
    files = list(journal_dir.glob("*.md"))
    assert len(files) > 0
    original = files[0].read_text()
    assert "entry 1" in original
    assert "entry 2" in original

    # Rewrite with distilled content
    writer.rewrite_file("journal", files[0].name, "Distilled: two entries happened today.")
    new_content = files[0].read_text()
    assert "Distilled" in new_content
    assert "entry 1" not in new_content


# ── Token budget ──────────────────────────────────────────────────────


def test_total_token_estimate(hot_dir: str) -> None:
    writer = MemoryWriter(hot_dir)
    writer.append_journal("A" * 400)  # ~100 tokens
    estimate = writer.total_token_estimate()
    assert estimate > 50  # at least some tokens counted


# ── Memory updates with categories ────────────────────────────────────


def test_apply_reflection_with_categories(hot_dir: str) -> None:
    from alive_memory.consolidation.memory_updates import apply_reflection_to_hot_memory
    from alive_memory.types import DayMoment, EventType

    writer = MemoryWriter(hot_dir)
    moment = DayMoment(
        id="m1",
        content="test",
        event_type=EventType.CONVERSATION,
        salience=0.8,
        valence=0.0,
        drive_snapshot={},
        timestamp=datetime.now(UTC),
    )

    counts = apply_reflection_to_hot_memory(
        moment, "Customer complained about service",
        writer=writer,
        categories=["complaints", "customer-service"],
    )

    assert counts["journal"] == 1
    assert counts["dynamic"] == 2
    assert "complaints" in writer.list_subdirs()
    assert "customer-service" in writer.list_subdirs()


def test_apply_reflection_skips_legacy_categories(hot_dir: str) -> None:
    from alive_memory.consolidation.memory_updates import apply_reflection_to_hot_memory
    from alive_memory.types import DayMoment, EventType

    writer = MemoryWriter(hot_dir)
    moment = DayMoment(
        id="m2",
        content="test",
        event_type=EventType.CONVERSATION,
        salience=0.8,
        valence=0.0,
        drive_snapshot={},
        timestamp=datetime.now(UTC),
    )

    counts = apply_reflection_to_hot_memory(
        moment, "Some text",
        writer=writer,
        categories=["journal", "self", "new-category"],
    )

    # journal and self are legacy — should not be double-written via dynamic path
    assert counts["dynamic"] == 1  # only new-category
