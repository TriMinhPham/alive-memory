"""A/B comparison: old thalamus (single heuristic) vs new thalamus (multi-axis).

Replays all autotune scenarios through both scoring paths and compares:
- What gets stored vs dropped
- Per-event salience scores
- Recall accuracy after consolidation

Usage:
    uv run python tools/thalamus_ab.py
"""

from __future__ import annotations

import asyncio
import copy
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from alive_memory.clock import SimulatedClock
from alive_memory.config import AliveConfig
from alive_memory.types import EventType, Perception
from tools.autotune.types import Scenario


# ── Old thalamus reimplementation (frozen copy of the original) ──────────

_STOP_WORDS: frozenset[str] = frozenset(
    "i me my myself we our ours ourselves you your yours yourself yourselves "
    "he him his himself she her hers herself it its itself they them their "
    "theirs themselves what which who whom this that these those am is are was "
    "were be been being have has had having do does did doing a an the and but "
    "if or because as until while of at by for with about against between "
    "through during before after above below to from up down in out on off "
    "over under again further then once here there when where why how all both "
    "each few more most other some such no nor not only own same so than too "
    "very s t can will just don should now d ll m o re ve y ain aren couldn "
    "didn doesn hadn hasn haven isn ma mightn mustn needn shan shouldn wasn "
    "weren won wouldn could would shall may might must also still already yet "
    "even really actually just like well yeah yes ok okay sure right got get "
    "let know think going go see look want need come take make say said".split()
)
_NUMBER_RE = re.compile(r"\b\d[\d,./:%-]*\b")


def _old_estimate_novelty(content: str) -> float:
    if not content:
        return 0.0
    words = content.split()
    word_count = len(words)
    if word_count < 3:
        return 0.05
    content_words = [
        w for w in words
        if w.lower().strip(".,!?;:'\"()[]{}") not in _STOP_WORDS
    ]
    content_ratio = len(content_words) / word_count
    avg_content_len = 0.0
    if content_words:
        avg_content_len = sum(len(w) for w in content_words) / len(content_words)
    length_signal = min(1.0, max(0.0, (avg_content_len - 3) / 5))
    number_count = len(_NUMBER_RE.findall(content))
    number_signal = min(1.0, number_count * 0.2)
    unique_ratio = len(set(w.lower() for w in words)) / word_count
    return float(min(1.0,
        content_ratio * 0.40
        + length_signal * 0.25
        + number_signal * 0.15
        + unique_ratio * 0.20
    ))


def old_perceive(
    event_type: str | EventType,
    content: str,
    *,
    metadata: dict | None = None,
    timestamp: datetime | None = None,
    identity_keywords: list[str] | None = None,
) -> Perception:
    """Frozen copy of the old single-heuristic thalamus."""
    cfg = AliveConfig()
    if isinstance(event_type, str):
        try:
            et = EventType(event_type)
        except ValueError:
            et = EventType.SYSTEM
    else:
        et = event_type

    meta = metadata or {}
    ts = timestamp or datetime.now(UTC)

    # Metadata override
    if "salience" in meta:
        salience = float(max(0.0, min(1.0, float(meta["salience"]))))
    else:
        _event_base = {
            EventType.CONVERSATION: 0.25,
            EventType.ACTION: 0.20,
            EventType.OBSERVATION: 0.15,
            EventType.SYSTEM: 0.05,
        }
        base = _event_base.get(et, 0.10)
        base += float(cfg.get("intake.base_salience", 0.0))
        if et == EventType.CONVERSATION:
            base += float(cfg.get("intake.conversation_boost", 0.0))
        novelty_weight = cfg.get("intake.novelty_weight", 0.3)
        novelty = _old_estimate_novelty(content)
        base += novelty * novelty_weight
        if identity_keywords:
            content_lower = content.lower()
            identity_boost = cfg.get("intake.identity_boost", 0.15)
            if any(kw.lower() in content_lower for kw in identity_keywords):
                base += identity_boost
        salience = float(max(0.0, min(1.0, base)))

    return Perception(
        event_type=et, content=content, salience=salience,
        timestamp=ts, metadata=meta,
    )


# ── New thalamus ─────────────────────────────────────────────────────────

from alive_cognition.thalamus import Thalamus
from alive_cognition.types import EventSchema, SalienceBand


# ── Comparison logic ─────────────────────────────────────────────────────

@dataclass
class EventComparison:
    content: str
    old_salience: float
    new_salience: float
    new_band: str
    new_channels: dict[str, float]
    old_stored: bool  # would old thalamus store it (salience >= 0.35)?
    new_stored: bool  # would new thalamus store it (band != DROP)?
    agreement: bool


@dataclass
class ScenarioComparison:
    name: str
    events: list[EventComparison] = field(default_factory=list)
    old_recall_hits: int = 0
    new_recall_hits: int = 0
    old_recall_total: int = 0
    new_recall_total: int = 0
    old_moments_stored: int = 0
    new_moments_stored: int = 0
    total_events: int = 0


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def run_comparison(scenario: Scenario) -> ScenarioComparison:
    """Run a scenario through both old and new thalamus, compare results."""
    from alive_memory import AliveMemory

    result = ScenarioComparison(name=scenario.name)
    old_threshold = 0.35  # formation's default salience_threshold

    # Collect intake events for head-to-head scoring
    thalamus = Thalamus()

    for turn in scenario.turns:
        if turn.action != "intake":
            continue

        ts = _parse_iso(turn.simulated_time) if turn.simulated_time else datetime.now(UTC)

        # Old thalamus
        old_p = old_perceive("conversation", turn.content, metadata=turn.metadata or None, timestamp=ts)

        # New thalamus
        event = EventSchema(
            event_type=EventType.CONVERSATION,
            content=turn.content,
            timestamp=ts,
            metadata=turn.metadata or {},
        )
        new_p = thalamus.perceive(event)

        old_stored = old_p.salience >= old_threshold
        new_stored = new_p.band != SalienceBand.DROP

        result.events.append(EventComparison(
            content=turn.content[:60],
            old_salience=round(old_p.salience, 3),
            new_salience=round(new_p.salience, 3),
            new_band=new_p.band.name,
            new_channels={
                "rel": round(new_p.channels.relevance, 2),
                "sur": round(new_p.channels.surprise, 2),
                "imp": round(new_p.channels.impact, 2),
                "urg": round(new_p.channels.urgency, 2),
            },
            old_stored=old_stored,
            new_stored=new_stored,
            agreement=old_stored == new_stored,
        ))

        result.total_events += 1
        if old_stored:
            result.old_moments_stored += 1
        if new_stored:
            result.new_moments_stored += 1

    # Now run full pipeline for recall comparison (old path vs new path)
    start_time = datetime.now(UTC)
    for turn in scenario.turns:
        if turn.simulated_time:
            start_time = _parse_iso(turn.simulated_time)
            break

    # Run new thalamus (current code)
    cfg = AliveConfig()
    if scenario.setup_config:
        from alive_memory.config import _deep_merge
        cfg_data = copy.deepcopy(cfg.data)
        _deep_merge(cfg_data, scenario.setup_config)
        cfg = AliveConfig(cfg_data)

    clock = SimulatedClock(start_time)
    with tempfile.TemporaryDirectory(prefix="ab_new_") as tmpdir:
        mem = AliveMemory(storage=":memory:", memory_dir=tmpdir, config=cfg, clock=clock)
        await mem.initialize()

        for turn in scenario.turns:
            if turn.simulated_time:
                clock.set(_parse_iso(turn.simulated_time))
            if turn.action == "intake":
                await mem.intake("conversation", turn.content, metadata=turn.metadata or None, timestamp=clock.now())
            elif turn.action == "consolidate":
                try:
                    await mem.consolidate(depth="full")
                except Exception:
                    pass
            elif turn.action == "advance_time":
                clock.advance(turn.advance_seconds)
            elif turn.action == "recall":
                ctx = await mem.recall(turn.content)
                all_text = " ".join(
                    ctx.journal_entries + ctx.visitor_notes + ctx.self_knowledge
                    + ctx.reflections + ctx.thread_context
                )
                result.new_recall_total += 1
                if turn.expected_recall:
                    if all(kw.lower() in all_text.lower() for kw in turn.expected_recall.must_contain):
                        result.new_recall_hits += 1
        await mem.close()

    # Run old thalamus path — override intake to use old scoring
    clock2 = SimulatedClock(start_time)
    with tempfile.TemporaryDirectory(prefix="ab_old_") as tmpdir2:
        mem2 = AliveMemory(storage=":memory:", memory_dir=tmpdir2, config=cfg, clock=clock2)
        await mem2.initialize()

        for turn in scenario.turns:
            if turn.simulated_time:
                clock2.set(_parse_iso(turn.simulated_time))
            if turn.action == "intake":
                # Force old salience via metadata override
                old_p = old_perceive("conversation", turn.content, metadata=turn.metadata or None, timestamp=clock2.now())
                meta = dict(turn.metadata or {})
                meta["salience"] = old_p.salience
                await mem2.intake("conversation", turn.content, metadata=meta, timestamp=clock2.now())
            elif turn.action == "consolidate":
                try:
                    await mem2.consolidate(depth="full")
                except Exception:
                    pass
            elif turn.action == "advance_time":
                clock2.advance(turn.advance_seconds)
            elif turn.action == "recall":
                ctx = await mem2.recall(turn.content)
                all_text = " ".join(
                    ctx.journal_entries + ctx.visitor_notes + ctx.self_knowledge
                    + ctx.reflections + ctx.thread_context
                )
                result.old_recall_total += 1
                if turn.expected_recall:
                    if all(kw.lower() in all_text.lower() for kw in turn.expected_recall.must_contain):
                        result.old_recall_hits += 1
        await mem2.close()

    return result


def print_report(comparisons: list[ScenarioComparison]) -> None:
    """Print a human-readable A/B report."""
    print("=" * 80)
    print("THALAMUS A/B COMPARISON: Old (single heuristic) vs New (multi-axis)")
    print("=" * 80)

    total_old_stored = 0
    total_new_stored = 0
    total_events = 0
    total_agreements = 0
    total_old_recall = 0
    total_new_recall = 0
    total_recall_queries = 0

    for comp in comparisons:
        print(f"\n{'─' * 80}")
        print(f"Scenario: {comp.name}")
        print(f"{'─' * 80}")
        print(f"  Events: {comp.total_events}  |  "
              f"Old stored: {comp.old_moments_stored}  |  "
              f"New stored: {comp.new_moments_stored}")

        if comp.old_recall_total > 0:
            old_pct = comp.old_recall_hits / comp.old_recall_total * 100
            new_pct = comp.new_recall_hits / comp.new_recall_total * 100
            print(f"  Recall: Old {comp.old_recall_hits}/{comp.old_recall_total} ({old_pct:.0f}%)  |  "
                  f"New {comp.new_recall_hits}/{comp.new_recall_total} ({new_pct:.0f}%)")

        # Event-level detail
        disagreements = [e for e in comp.events if not e.agreement]
        if disagreements:
            print(f"\n  Disagreements ({len(disagreements)}):")
            for e in disagreements:
                old_icon = "STORE" if e.old_stored else "DROP "
                new_icon = "STORE" if e.new_stored else "DROP "
                print(f"    Old={old_icon}({e.old_salience:.3f})  "
                      f"New={new_icon}({e.new_salience:.3f}) [{e.new_band}]  "
                      f"ch={e.new_channels}")
                print(f"      \"{e.content}\"")

        # Score distribution
        print(f"\n  Score comparison:")
        print(f"    {'Content':<45s} {'Old':>6s} {'New':>6s} {'Band':<10s}")
        for e in comp.events:
            delta = e.new_salience - e.old_salience
            marker = "  " if e.agreement else " *"
            print(f"  {marker}{e.content:<45s} {e.old_salience:6.3f} {e.new_salience:6.3f} {e.new_band:<10s}")

        total_old_stored += comp.old_moments_stored
        total_new_stored += comp.new_moments_stored
        total_events += comp.total_events
        total_agreements += sum(1 for e in comp.events if e.agreement)
        total_old_recall += comp.old_recall_hits
        total_new_recall += comp.new_recall_hits
        total_recall_queries += comp.old_recall_total

    # Summary
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    print(f"  Total events:      {total_events}")
    print(f"  Old stored:        {total_old_stored} ({total_old_stored/total_events*100:.0f}%)")
    print(f"  New stored:        {total_new_stored} ({total_new_stored/total_events*100:.0f}%)")
    print(f"  Agreement rate:    {total_agreements}/{total_events} ({total_agreements/total_events*100:.0f}%)")
    if total_recall_queries > 0:
        print(f"  Old recall hits:   {total_old_recall}/{total_recall_queries} ({total_old_recall/total_recall_queries*100:.0f}%)")
        print(f"  New recall hits:   {total_new_recall}/{total_recall_queries} ({total_new_recall/total_recall_queries*100:.0f}%)")


async def main() -> None:
    from tools.autotune.scenarios.loader import load_scenarios

    scenarios = load_scenarios("builtin")
    print(f"Loaded {len(scenarios)} scenarios\n")

    comparisons = []
    for scenario in scenarios:
        comp = await run_comparison(scenario)
        comparisons.append(comp)

    print_report(comparisons)


if __name__ == "__main__":
    asyncio.run(main())
