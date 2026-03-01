"""bus.py — In-process async event bus with broadcast and keyed pub/sub.

Provides fail-open, bounded-queue fan-out for decoupling cognitive
orchestration from transport/observability concerns.

Usage:
    bus = EventBus()
    q = bus.subscribe('topic.name', 'my-sub-id')
    bus.publish('topic.name', {'key': 'value'})
    msg = await bus.wait(q, timeout=5.0)
"""

import asyncio
from typing import Any, Optional


class EventBus:
    """Async event bus with broadcast and keyed (per-visitor) channels."""

    def __init__(self):
        # Broadcast: topic → {sub_id → Queue}
        self._broadcast_subs: dict[str, dict[str, asyncio.Queue]] = {}
        # Keyed: topic → {key → {sub_id → Queue}}
        self._keyed_subs: dict[str, dict[str, dict[str, asyncio.Queue]]] = {}
        # Per-visitor locks for request serialization
        self._visitor_locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Broadcast pub/sub
    # ------------------------------------------------------------------

    def subscribe(self, topic: str, sub_id: str, maxsize: int = 50) -> asyncio.Queue:
        """Subscribe to a broadcast topic. Returns a bounded Queue."""
        if topic not in self._broadcast_subs:
            self._broadcast_subs[topic] = {}
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._broadcast_subs[topic][sub_id] = q
        return q

    def unsubscribe(self, topic: str, sub_id: str) -> None:
        """Remove a broadcast subscription."""
        subs = self._broadcast_subs.get(topic)
        if subs:
            subs.pop(sub_id, None)
            if not subs:
                del self._broadcast_subs[topic]

    def publish(self, topic: str, message: Any) -> None:
        """Publish to all broadcast subscribers. Drop-oldest if full."""
        subs = self._broadcast_subs.get(topic)
        if not subs:
            return
        for sub_id, q in list(subs.items()):
            self._put_drop_oldest(q, message)

    def subscriber_count(self, topic: str) -> int:
        """Return the number of broadcast subscribers for a topic."""
        return len(self._broadcast_subs.get(topic, {}))

    # ------------------------------------------------------------------
    # Keyed pub/sub (per-visitor delivery)
    # ------------------------------------------------------------------

    def subscribe_keyed(
        self, topic: str, key: str, sub_id: str, maxsize: int = 50
    ) -> asyncio.Queue:
        """Subscribe to a keyed topic. key='*' receives all publishes."""
        if topic not in self._keyed_subs:
            self._keyed_subs[topic] = {}
        if key not in self._keyed_subs[topic]:
            self._keyed_subs[topic][key] = {}
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._keyed_subs[topic][key][sub_id] = q
        return q

    def unsubscribe_keyed(self, topic: str, key: str, sub_id: str) -> None:
        """Remove a keyed subscription."""
        topic_subs = self._keyed_subs.get(topic)
        if not topic_subs:
            return
        key_subs = topic_subs.get(key)
        if not key_subs:
            return
        key_subs.pop(sub_id, None)
        if not key_subs:
            del topic_subs[key]
        if not topic_subs:
            del self._keyed_subs[topic]

    def publish_keyed(self, topic: str, key: str, message: Any) -> None:
        """Publish to keyed subscribers. Exact key match + '*' wildcard.

        Wildcard de-dup rule: when key='*', deliver ONLY to exact '*'
        subscribers. '*' subscribers also receive non-wildcard publishes.
        This prevents double delivery.
        """
        topic_subs = self._keyed_subs.get(topic, {})
        # Exact key match
        for sub_id, q in list(topic_subs.get(key, {}).items()):
            self._put_drop_oldest(q, message)
        # Wildcard subscribers get copies of non-wildcard publishes only
        if key != '*':
            for sub_id, q in list(topic_subs.get('*', {}).items()):
                self._put_drop_oldest(q, message)

    # ------------------------------------------------------------------
    # Per-visitor lock
    # ------------------------------------------------------------------

    def visitor_lock(self, visitor_id: str) -> asyncio.Lock:
        """Get or create a per-visitor asyncio.Lock for request serialization."""
        if visitor_id not in self._visitor_locks:
            self._visitor_locks[visitor_id] = asyncio.Lock()
        return self._visitor_locks[visitor_id]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def wait(queue: asyncio.Queue, timeout: float = 30.0) -> Optional[Any]:
        """Wait for a message from a queue with timeout. Returns None on timeout."""
        try:
            return await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    @staticmethod
    def _put_drop_oldest(q: asyncio.Queue, message: Any) -> None:
        """Put message into queue, dropping oldest if full."""
        while q.full():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            pass
