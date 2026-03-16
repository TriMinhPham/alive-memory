"""MemoryWriter — append-only writes to hot memory markdown files.

Tier 2 of the three-tier memory architecture.
All writes are append-only (no overwrites except self-knowledge files).
Directory structure is created on first use.

All content is passed through scrub_numbers() before writing to prevent
raw numeric state (valence=0.84, 73%, etc.) from leaking into conscious
memory. Dates and times are preserved.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path

from alive_memory.hot.translator import scrub_numbers

# Default pinned subdirectories — always created at init
_DEFAULT_PINNED = ["journal", "visitors", "threads", "reflections", "self", "collection"]


class MemoryWriter:
    """Writer for hot memory markdown files with dynamic subdirectories.

    Subdirectories can be created dynamically by the LLM during consolidation.
    Pinned subdirs are always created at init. Subdir names are sanitized.

    Args:
        memory_dir: Root directory for hot memory files (e.g., /data/agent/memory).
        pinned_subdirs: Subdirs to always create (default: journal, visitors, etc.).
        max_subdirs: Safety cap on total subdirectory count.
    """

    # Keep SUBDIRS for backward compat — code that references MemoryWriter.SUBDIRS
    SUBDIRS = _DEFAULT_PINNED

    def __init__(
        self,
        memory_dir: str | Path,
        *,
        pinned_subdirs: list[str] | None = None,
        max_subdirs: int = 20,
    ) -> None:
        self._root = Path(memory_dir)
        self._pinned = pinned_subdirs or list(_DEFAULT_PINNED)
        self._max_subdirs = max_subdirs
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        for subdir in self._pinned:
            (self._root / subdir).mkdir(parents=True, exist_ok=True)

    def _sanitize_subdir(self, name: str) -> str:
        """Sanitize a subdirectory name: lowercase, alphanumeric + hyphens, max 30 chars."""
        safe = re.sub(r"[^a-z0-9-]", "-", name.lower().strip())
        safe = re.sub(r"-+", "-", safe).strip("-")[:30]
        if not safe or safe in (".", ".."):
            raise ValueError(f"Invalid category name: {name!r}")
        return safe

    def _ensure_subdir(self, name: str) -> Path:
        """Create a subdirectory on demand (sanitized). Respects max_subdirs cap."""
        safe = self._sanitize_subdir(name)
        path = self._root / safe
        if not path.is_dir():
            existing = [d for d in self._root.iterdir() if d.is_dir()]
            if len(existing) >= self._max_subdirs:
                raise ValueError(
                    f"Max subdirectories ({self._max_subdirs}) reached, "
                    f"cannot create '{safe}'"
                )
            path.mkdir(parents=True, exist_ok=True)
        return path

    def list_subdirs(self) -> list[str]:
        """List all existing subdirectory names."""
        if not self._root.is_dir():
            return []
        return sorted(d.name for d in self._root.iterdir() if d.is_dir())

    # ── Generic append (for dynamic categories) ───────────────────

    def append_to_category(
        self,
        category: str,
        content: str,
        *,
        filename: str | None = None,
        timestamp: datetime | None = None,
    ) -> Path:
        """Append content to a dynamic category subdirectory.

        Creates the subdir if it doesn't exist (sanitized name).
        """
        safe_cat = self._sanitize_subdir(category)
        self._ensure_subdir(safe_cat)
        ts = timestamp or datetime.now(UTC)
        date_str = ts.strftime("%Y-%m-%d")
        fname = filename or f"{date_str}.md"
        if not fname.endswith(".md"):
            fname += ".md"
        filepath = self._root / safe_cat / fname

        time_str = ts.strftime("%H:%M")
        with open(filepath, "a", encoding="utf-8") as f:
            if not filepath.exists() or os.path.getsize(filepath) == 0:
                f.write(f"# {category.title()} — {date_str}\n")
            f.write(f"\n## {time_str}\n\n")
            f.write(scrub_numbers(content.strip()))
            f.write("\n")

        return filepath

    # ── Rewrite (for distillation) ────────────────────────────────

    def rewrite_file(self, subdir: str, filename: str, content: str) -> Path:
        """Overwrite a file in any subdirectory (used for distillation)."""
        safe_sub = self._sanitize_subdir(subdir)
        self._ensure_subdir(safe_sub)
        filepath = self._root / safe_sub / filename
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(scrub_numbers(content))
        return filepath

    # ── Pruning ───────────────────────────────────────────────────

    def prune_old_files(self, subdir: str, max_age_days: int) -> int:
        """Remove files older than max_age_days from a subdirectory.

        Only removes files with YYYY-MM-DD in the name (date-based files).
        Returns count of files removed.
        """
        dir_path = self._root / subdir
        if not dir_path.is_dir():
            return 0
        cutoff = datetime.now(UTC)
        count = 0
        for filepath in dir_path.glob("*.md"):
            # Try to extract date from filename
            match = re.search(r"(\d{4}-\d{2}-\d{2})", filepath.stem)
            if not match:
                continue
            try:
                file_date = datetime.strptime(match.group(1), "%Y-%m-%d").replace(
                    tzinfo=UTC
                )
                age_days = (cutoff - file_date).days
                if age_days > max_age_days:
                    filepath.unlink()
                    count += 1
            except ValueError:
                continue
        return count

    def total_token_estimate(self) -> int:
        """Estimate total tokens across all hot memory files (~4 chars/token)."""
        total_chars = 0
        if not self._root.is_dir():
            return 0
        for filepath in self._root.rglob("*.md"):
            try:
                total_chars += filepath.stat().st_size
            except OSError:
                continue
        return total_chars // 4

    @property
    def root(self) -> Path:
        return self._root

    # ── Journal ──────────────────────────────────────────────────

    def append_journal(
        self,
        content: str,
        *,
        date: datetime | None = None,
        moment_id: str | None = None,
    ) -> Path:
        """Append a journal entry for the given date.

        Each day gets its own file: journal/YYYY-MM-DD.md
        Entries are appended with timestamps.
        """
        ts = date or datetime.now(UTC)
        date_str = ts.strftime("%Y-%m-%d")
        filepath = self._root / "journal" / f"{date_str}.md"

        time_str = ts.strftime("%H:%M")
        header = f"\n## {time_str}"
        if moment_id:
            header += f" [{moment_id[:8]}]"
        header += "\n\n"

        with open(filepath, "a", encoding="utf-8") as f:
            if os.path.getsize(filepath) == 0 if filepath.exists() else True:
                f.write(f"# Journal — {date_str}\n")
            f.write(header)
            f.write(scrub_numbers(content.strip()))
            f.write("\n")

        return filepath

    # ── Visitors ─────────────────────────────────────────────────

    def append_visitor(
        self,
        visitor_name: str,
        content: str,
        *,
        timestamp: datetime | None = None,
    ) -> Path:
        """Append a note about a visitor/person.

        Each visitor gets their own file: visitors/{name}.md
        """
        safe_name = _safe_filename(visitor_name)
        filepath = self._root / "visitors" / f"{safe_name}.md"
        ts = timestamp or datetime.now(UTC)
        time_str = ts.strftime("%Y-%m-%d %H:%M")

        with open(filepath, "a", encoding="utf-8") as f:
            if not filepath.exists() or os.path.getsize(filepath) == 0:
                f.write(f"# {visitor_name}\n\n")
            f.write(f"\n### {time_str}\n\n")
            f.write(scrub_numbers(content.strip()))
            f.write("\n")

        return filepath

    # ── Reflections ──────────────────────────────────────────────

    def append_reflection(
        self,
        content: str,
        *,
        date: datetime | None = None,
        label: str = "",
    ) -> Path:
        """Append a reflection from consolidation.

        One file per day: reflections/YYYY-MM-DD.md
        """
        ts = date or datetime.now(UTC)
        date_str = ts.strftime("%Y-%m-%d")
        filepath = self._root / "reflections" / f"{date_str}.md"

        with open(filepath, "a", encoding="utf-8") as f:
            if not filepath.exists() or os.path.getsize(filepath) == 0:
                f.write(f"# Reflections — {date_str}\n")
            header = "\n---\n"
            if label:
                header += f"**{label}**\n\n"
            f.write(header)
            f.write(scrub_numbers(content.strip()))
            f.write("\n")

        return filepath

    # ── Threads ──────────────────────────────────────────────────

    def append_thread(
        self,
        thread_id: str,
        content: str,
        *,
        timestamp: datetime | None = None,
    ) -> Path:
        """Append context to a conversation thread.

        Each thread gets its own file: threads/{thread_id}.md
        """
        safe_id = _safe_filename(thread_id)
        filepath = self._root / "threads" / f"{safe_id}.md"
        ts = timestamp or datetime.now(UTC)
        time_str = ts.strftime("%Y-%m-%d %H:%M")

        with open(filepath, "a", encoding="utf-8") as f:
            if not filepath.exists() or os.path.getsize(filepath) == 0:
                f.write(f"# Thread {thread_id}\n\n")
            f.write(f"\n### {time_str}\n\n")
            f.write(scrub_numbers(content.strip()))
            f.write("\n")

        return filepath

    # ── Self-Knowledge ───────────────────────────────────────────

    def write_self_file(
        self,
        filename: str,
        content: str,
    ) -> Path:
        """Write (overwrite) a self-knowledge file.

        These are the only non-append files. Used for:
          self/identity.md, self/preferences.md, self/relationships.md, etc.
        """
        safe_name = _safe_filename(filename)
        if not safe_name.endswith(".md"):
            safe_name += ".md"
        filepath = self._root / "self" / safe_name

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(scrub_numbers(content))

        return filepath

    # ── Collection ───────────────────────────────────────────────

    def append_collection(
        self,
        item_name: str,
        content: str,
    ) -> Path:
        """Append to a collection file.

        Collection items: collection/{item_name}.md
        """
        safe_name = _safe_filename(item_name)
        filepath = self._root / "collection" / f"{safe_name}.md"

        with open(filepath, "a", encoding="utf-8") as f:
            if not filepath.exists() or os.path.getsize(filepath) == 0:
                f.write(f"# {item_name}\n\n")
            f.write(scrub_numbers(content.strip()))
            f.write("\n\n")

        return filepath


def _safe_filename(name: str) -> str:
    """Convert a string to a safe filename."""
    safe = name.lower().strip()
    safe = safe.replace(" ", "_")
    # Keep only alphanumeric, underscore, hyphen, dot
    safe = "".join(c for c in safe if c.isalnum() or c in ("_", "-", "."))
    return safe or "unnamed"
