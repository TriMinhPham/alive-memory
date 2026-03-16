"""Memory updates — apply LLM reflection outputs to hot memory.

After the LLM reflects on a day moment (with hot context + cold echoes),
this module writes the reflection outputs to the appropriate hot memory files.

Supports both legacy fixed routing (journal/visitors/threads) and
LLM-driven dynamic categories from the reflection result.
"""

from __future__ import annotations

import logging

from alive_memory.hot.writer import MemoryWriter
from alive_memory.types import DayMoment

logger = logging.getLogger(__name__)


def apply_reflection_to_hot_memory(
    moment: DayMoment,
    reflection_text: str,
    writer: MemoryWriter,
    *,
    visitor_name: str | None = None,
    thread_id: str | None = None,
    self_updates: dict[str, str] | None = None,
    categories: list[str] | None = None,
) -> dict[str, int]:
    """Apply a reflection's outputs to hot memory files.

    Writes to journal, visitors, threads, self-knowledge, and any
    dynamic categories returned by the LLM.

    Args:
        moment: The original day moment.
        reflection_text: LLM-generated reflection about the moment.
        writer: MemoryWriter for hot memory.
        visitor_name: If the moment involved a visitor, record notes about them.
        thread_id: If the moment is part of a thread, append thread context.
        self_updates: Dict of self-knowledge file → content to write.
        categories: LLM-returned category names for dynamic routing.

    Returns:
        Dict counting writes by type: {journal: N, visitor: N, ...}
    """
    counts: dict[str, int] = {"journal": 0, "visitor": 0, "thread": 0, "self": 0, "dynamic": 0}

    # Always write a journal entry
    writer.append_journal(
        reflection_text,
        date=moment.timestamp,
        moment_id=moment.id,
    )
    counts["journal"] = 1

    # Write visitor notes if applicable
    if visitor_name:
        writer.append_visitor(
            visitor_name,
            reflection_text,
            timestamp=moment.timestamp,
        )
        counts["visitor"] = 1

    # Append to thread if applicable
    if thread_id:
        writer.append_thread(
            thread_id,
            reflection_text,
            timestamp=moment.timestamp,
        )
        counts["thread"] = 1

    # Update self-knowledge files if reflection produced self-insights
    if self_updates:
        for filename, content in self_updates.items():
            writer.write_self_file(filename, content)
            counts["self"] += 1

    # Write to dynamic categories (skip legacy subdirs already handled above)
    _legacy = {"journal", "visitors", "threads", "reflections", "self", "collection"}
    if categories:
        for cat in categories:
            if not cat or cat.lower() in _legacy:
                continue
            try:
                writer.append_to_category(
                    cat,
                    reflection_text,
                    timestamp=moment.timestamp,
                )
                counts["dynamic"] += 1
            except ValueError:
                logger.debug("Skipping invalid category %r", cat)

    return counts
