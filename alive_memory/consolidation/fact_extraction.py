"""Fact extraction — extract totems and traits from moments during consolidation.

Ported from Shopkeeper's hippocampus_write pipeline.
After the LLM reflects on a moment, this module asks the LLM to extract
structured facts (totems + traits) and writes them to storage.
"""

from __future__ import annotations

import json
import logging

from alive_memory.llm.provider import LLMProvider
from alive_memory.storage.base import BaseStorage
from alive_memory.types import DayMoment

logger = logging.getLogger(__name__)

# Trait dedup cooldown — prevents writing the same trait within a short window.
# Without this, the LLM reads back its own trait and reinforces it (feedback loop).
TRAIT_COOLDOWN_SECONDS = 300
_recent_traits: dict[tuple[str, str, str], tuple[str, float]] = {}


def _trait_is_duplicate(
    visitor_id: str, category: str, key: str, value: str
) -> bool:
    """Check if this trait was already written recently."""
    import time

    now = time.monotonic()
    cache_key = (visitor_id, category, key)

    # Prune stale entries
    stale = [
        k for k, (_, ts) in _recent_traits.items()
        if now - ts > TRAIT_COOLDOWN_SECONDS
    ]
    for k in stale:
        del _recent_traits[k]

    if cache_key in _recent_traits:
        cached_value, _ = _recent_traits[cache_key]
        if cached_value == value:
            return True

    _recent_traits[cache_key] = (value, now)
    return False


_EXTRACTION_PROMPT = """\
Extract structured facts from this conversation moment. Return a JSON object with two arrays:

1. "totems": facts, entities, or concepts mentioned. Each totem has:
   - "entity": the fact or thing (string, be specific)
   - "weight": importance 0.0-1.0
   - "context": brief context explaining relevance
   - "category": one of "personal", "preference", "relationship", "location", "event", "general"

2. "traits": observations about people mentioned. Each trait has:
   - "trait_category": one of "personal", "preference", "demographic", "relationship", "behavioral", "emotional"
   - "trait_key": specific attribute name (e.g. "gender_identity", "favorite_food", "occupation")
   - "trait_value": the observed value
   - "confidence": 0.0-1.0

Only extract facts clearly stated in the text. Do not infer or speculate.
If no facts are found, return {"totems": [], "traits": []}.

The moment:
{content}

Visitor name: {visitor_name}

Return ONLY valid JSON, no markdown fencing."""


async def extract_facts(
    moment: DayMoment,
    *,
    storage: BaseStorage,
    llm: LLMProvider,
    visitor_name: str | None = None,
) -> dict[str, int]:
    """Extract totems and traits from a moment and write to storage.

    Args:
        moment: The day moment to extract facts from.
        storage: Storage backend for writing totems/traits.
        llm: LLM provider for structured extraction.
        visitor_name: Visitor name from moment metadata.

    Returns:
        Dict with counts: {totems: N, traits: N}
    """
    counts = {"totems": 0, "traits": 0}

    prompt = _EXTRACTION_PROMPT.format(
        content=moment.content[:1000],
        visitor_name=visitor_name or "unknown",
    )

    try:
        response = await llm.complete(
            prompt,
            system="You extract structured facts from text. Return only valid JSON.",
            max_tokens=500,
            temperature=0.1,
        )
        text = response.text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        data = json.loads(text)
    except (json.JSONDecodeError, Exception):
        logger.debug("Fact extraction failed for moment %s", moment.id, exc_info=True)
        return counts

    visitor_id = moment.metadata.get("visitor_id") or moment.metadata.get("visitor_name")

    # Process totems
    for totem in data.get("totems", []):
        entity = totem.get("entity", "").strip()
        if not entity:
            continue
        try:
            await storage.insert_totem(
                entity=entity,
                visitor_id=visitor_id,
                weight=float(totem.get("weight", 0.5)),
                context=totem.get("context", ""),
                category=totem.get("category", "general"),
                source_moment_id=moment.id,
            )
            counts["totems"] += 1
        except Exception:
            logger.debug("Failed to insert totem %r", entity, exc_info=True)

    # Process traits
    for trait in data.get("traits", []):
        cat = trait.get("trait_category", "").strip()
        key = trait.get("trait_key", "").strip()
        val = trait.get("trait_value", "").strip()
        if not (cat and key and val and visitor_id):
            continue

        # Dedup check
        if _trait_is_duplicate(visitor_id, cat, key, val):
            logger.debug("Trait dedup: skipped %s=%s", key, val)
            continue

        try:
            # Check for contradiction
            existing = await storage.get_latest_trait(visitor_id, cat, key)
            if existing and existing.trait_value != val:
                logger.info(
                    "Trait contradiction: %s.%s was %r, now %r",
                    cat, key, existing.trait_value, val,
                )

            await storage.insert_trait(
                visitor_id=visitor_id,
                trait_category=cat,
                trait_key=key,
                trait_value=val,
                confidence=float(trait.get("confidence", 0.5)),
                source_moment_id=moment.id,
            )
            counts["traits"] += 1
        except Exception:
            logger.debug("Failed to insert trait %s=%s", key, val, exc_info=True)

    return counts
