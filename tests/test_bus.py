"""Tests for engine/bus.py and bus integration in heartbeat.py."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'engine'))

from bus import EventBus
from bus_types import TOPIC_CYCLE_COMPLETE, TOPIC_SCENE_UPDATE, TOPIC_STAGE_PROGRESS


# ---------------------------------------------------------------------------
# TestBroadcastPubSub
# ---------------------------------------------------------------------------

class TestBroadcastPubSub:
    def test_subscribe_and_publish(self):
        bus = EventBus()
        q = bus.subscribe('t', 'sub1')
        bus.publish('t', {'a': 1})
        assert q.get_nowait() == {'a': 1}

    def test_fanout_to_multiple_subscribers(self):
        bus = EventBus()
        q1 = bus.subscribe('t', 's1')
        q2 = bus.subscribe('t', 's2')
        bus.publish('t', 'msg')
        assert q1.get_nowait() == 'msg'
        assert q2.get_nowait() == 'msg'

    def test_unsubscribe(self):
        bus = EventBus()
        q = bus.subscribe('t', 's1')
        bus.unsubscribe('t', 's1')
        bus.publish('t', 'msg')
        assert q.empty()

    def test_drop_oldest_when_full(self):
        bus = EventBus()
        q = bus.subscribe('t', 's1', maxsize=2)
        bus.publish('t', 'a')
        bus.publish('t', 'b')
        bus.publish('t', 'c')  # should drop 'a'
        assert q.get_nowait() == 'b'
        assert q.get_nowait() == 'c'
        assert q.empty()

    def test_empty_topic_noop(self):
        bus = EventBus()
        # Should not raise
        bus.publish('nonexistent', {'x': 1})

    def test_subscriber_count(self):
        bus = EventBus()
        assert bus.subscriber_count('t') == 0
        bus.subscribe('t', 's1')
        assert bus.subscriber_count('t') == 1
        bus.subscribe('t', 's2')
        assert bus.subscriber_count('t') == 2
        bus.unsubscribe('t', 's1')
        assert bus.subscriber_count('t') == 1

    def test_unsubscribe_nonexistent_is_noop(self):
        bus = EventBus()
        bus.unsubscribe('no-topic', 'no-sub')  # should not raise


# ---------------------------------------------------------------------------
# TestKeyedPubSub
# ---------------------------------------------------------------------------

class TestKeyedPubSub:
    def test_exact_key_match(self):
        bus = EventBus()
        q = bus.subscribe_keyed('t', 'alice', 's1')
        bus.publish_keyed('t', 'alice', 'msg')
        assert q.get_nowait() == 'msg'

    def test_no_cross_delivery(self):
        bus = EventBus()
        q_alice = bus.subscribe_keyed('t', 'alice', 's1')
        q_bob = bus.subscribe_keyed('t', 'bob', 's2')
        bus.publish_keyed('t', 'alice', 'for-alice')
        assert q_alice.get_nowait() == 'for-alice'
        assert q_bob.empty()

    def test_wildcard_receives_non_wildcard_publishes(self):
        bus = EventBus()
        q_star = bus.subscribe_keyed('t', '*', 'watcher')
        bus.publish_keyed('t', 'alice', 'msg1')
        bus.publish_keyed('t', 'bob', 'msg2')
        assert q_star.get_nowait() == 'msg1'
        assert q_star.get_nowait() == 'msg2'

    def test_wildcard_key_publish_no_double_delivery(self):
        """publish_keyed(key='*') delivers only to '*' subscribers, not all keys."""
        bus = EventBus()
        q_star = bus.subscribe_keyed('t', '*', 'watcher')
        q_alice = bus.subscribe_keyed('t', 'alice', 's1')
        bus.publish_keyed('t', '*', 'ambient')
        # '*' subscriber gets it via exact match
        assert q_star.get_nowait() == 'ambient'
        # 'alice' subscriber does NOT get it (not a broadcast)
        assert q_alice.empty()
        # '*' subscriber got it exactly once (no double delivery)
        assert q_star.empty()

    def test_unsubscribe_keyed(self):
        bus = EventBus()
        q = bus.subscribe_keyed('t', 'k', 's1')
        bus.unsubscribe_keyed('t', 'k', 's1')
        bus.publish_keyed('t', 'k', 'msg')
        assert q.empty()

    def test_drop_oldest_keyed(self):
        bus = EventBus()
        q = bus.subscribe_keyed('t', 'k', 's1', maxsize=2)
        bus.publish_keyed('t', 'k', 'a')
        bus.publish_keyed('t', 'k', 'b')
        bus.publish_keyed('t', 'k', 'c')
        assert q.get_nowait() == 'b'
        assert q.get_nowait() == 'c'

    def test_unsubscribe_keyed_nonexistent_is_noop(self):
        bus = EventBus()
        bus.unsubscribe_keyed('no-topic', 'no-key', 'no-sub')  # should not raise


# ---------------------------------------------------------------------------
# TestVisitorLock
# ---------------------------------------------------------------------------

class TestVisitorLock:
    def test_same_visitor_same_lock(self):
        bus = EventBus()
        lock1 = bus.visitor_lock('v1')
        lock2 = bus.visitor_lock('v1')
        assert lock1 is lock2

    def test_different_visitors_different_locks(self):
        bus = EventBus()
        lock1 = bus.visitor_lock('v1')
        lock2 = bus.visitor_lock('v2')
        assert lock1 is not lock2

    @pytest.mark.asyncio
    async def test_lock_serializes(self):
        bus = EventBus()
        lock = bus.visitor_lock('v1')
        order = []

        async def worker(label, delay):
            async with lock:
                order.append(f'{label}-start')
                await asyncio.sleep(delay)
                order.append(f'{label}-end')

        t1 = asyncio.create_task(worker('A', 0.05))
        await asyncio.sleep(0.01)  # ensure A starts first
        t2 = asyncio.create_task(worker('B', 0.01))
        await asyncio.gather(t1, t2)
        assert order == ['A-start', 'A-end', 'B-start', 'B-end']


# ---------------------------------------------------------------------------
# TestWait
# ---------------------------------------------------------------------------

class TestWait:
    @pytest.mark.asyncio
    async def test_returns_message(self):
        bus = EventBus()
        q = bus.subscribe('t', 's1')
        bus.publish('t', 'hello')
        result = await bus.wait(q, timeout=1.0)
        assert result == 'hello'

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self):
        bus = EventBus()
        q = bus.subscribe('t', 's1')
        result = await bus.wait(q, timeout=0.05)
        assert result is None


# ---------------------------------------------------------------------------
# TestHeartbeatIntegration
# ---------------------------------------------------------------------------

class TestHeartbeatIntegration:
    def test_set_bus(self):
        from heartbeat import Heartbeat
        hb = Heartbeat()
        bus = EventBus()
        hb.set_bus(bus)
        assert hb._bus is bus

    @pytest.mark.asyncio
    async def test_publish_cycle_log_to_bus(self):
        from heartbeat import Heartbeat
        hb = Heartbeat()
        bus = EventBus()
        hb.set_bus(bus)
        q = bus.subscribe_keyed(TOPIC_CYCLE_COMPLETE, 'visitor-1', 'test')
        log = {'visitor_id': 'visitor-1', 'type': 'test'}
        await hb._publish_cycle_log(log)
        assert q.get_nowait() == log

    @pytest.mark.asyncio
    async def test_publish_cycle_log_wildcard_subscriber(self):
        from heartbeat import Heartbeat
        hb = Heartbeat()
        bus = EventBus()
        hb.set_bus(bus)
        q = bus.subscribe_keyed(TOPIC_CYCLE_COMPLETE, '*', 'watcher')
        log = {'visitor_id': 'visitor-1', 'type': 'test'}
        await hb._publish_cycle_log(log)
        assert q.get_nowait() == log

    @pytest.mark.asyncio
    async def test_publish_cycle_log_ambient_uses_wildcard_key(self):
        """Cycle with no visitor_id publishes with key='*'."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        bus = EventBus()
        hb.set_bus(bus)
        q = bus.subscribe_keyed(TOPIC_CYCLE_COMPLETE, '*', 'watcher')
        log = {'type': 'idle'}  # no visitor_id
        await hb._publish_cycle_log(log)
        assert q.get_nowait() == log

    @pytest.mark.asyncio
    async def test_publish_cycle_log_no_bus_fallback(self):
        """Legacy path still works when bus is None."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        q = asyncio.Queue(maxsize=10)
        hb._cycle_log_subscribers['test'] = q
        log = {'type': 'test'}
        await hb._publish_cycle_log(log)
        assert q.get_nowait() == log

    @pytest.mark.asyncio
    async def test_emit_stage_to_bus(self):
        from heartbeat import Heartbeat
        hb = Heartbeat()
        bus = EventBus()
        hb.set_bus(bus)
        q = bus.subscribe(TOPIC_STAGE_PROGRESS, 'test')
        await hb._emit_stage('cortex', {'tokens': 100})
        msg = q.get_nowait()
        assert msg['stage'] == 'cortex'
        assert msg['data'] == {'tokens': 100}

    @pytest.mark.asyncio
    async def test_emit_stage_legacy_and_bus_coexist(self):
        from heartbeat import Heartbeat
        hb = Heartbeat()
        bus = EventBus()
        hb.set_bus(bus)
        legacy_calls = []
        hb.set_stage_callback(AsyncMock(side_effect=lambda s, d: legacy_calls.append(s)))
        q = bus.subscribe(TOPIC_STAGE_PROGRESS, 'test')
        await hb._emit_stage('body', {'action': 'sip_tea'})
        # Both paths got the message
        assert 'body' in legacy_calls
        assert not q.empty()

    @pytest.mark.asyncio
    async def test_emit_stage_legacy_failure_does_not_block_bus(self):
        """Legacy callback raising does not prevent bus publish."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        bus = EventBus()
        hb.set_bus(bus)
        hb.set_stage_callback(AsyncMock(side_effect=RuntimeError("boom")))
        q = bus.subscribe(TOPIC_STAGE_PROGRESS, 'test')
        await hb._emit_stage('cortex', {'x': 1})
        # Bus still got the message
        msg = q.get_nowait()
        assert msg['stage'] == 'cortex'

    @pytest.mark.asyncio
    async def test_emit_stage_bus_failure_does_not_break_cycle(self):
        """Bus exception in _emit_stage is caught (fail-open)."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        bus = EventBus()
        hb.set_bus(bus)
        # Monkey-patch publish to raise
        bus.publish = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("bus-fail"))
        # Should not raise
        await hb._emit_stage('test', {})


# ---------------------------------------------------------------------------
# TestSceneUpdateIntegration
# ---------------------------------------------------------------------------

class TestSceneUpdateIntegration:
    """Tests for the scene_update bus path in run_cycle's window broadcast block.

    These test the restructured build-once publish-twice pattern. We can't
    easily run full run_cycle, so we test the bus wiring via _emit_stage and
    _publish_cycle_log, plus verify the attribute wiring.
    """

    def test_bus_attribute_independent_of_window_broadcast(self):
        """Bus can be set without window_broadcast being set."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        bus = EventBus()
        hb.set_bus(bus)
        assert hb._bus is bus
        assert hb._window_broadcast is None

    def test_scene_update_topic_constant(self):
        """TOPIC_SCENE_UPDATE has expected value."""
        assert TOPIC_SCENE_UPDATE == 'outbound.scene_update'

    @pytest.mark.asyncio
    async def test_scene_update_bus_publish(self):
        """Verify bus.publish works for scene_update topic."""
        bus = EventBus()
        q = bus.subscribe(TOPIC_SCENE_UPDATE, 'viewer')
        broadcast_msg = {'type': 'scene_update', 'expression': 'neutral'}
        bus.publish(TOPIC_SCENE_UPDATE, broadcast_msg)
        assert q.get_nowait() == broadcast_msg

    @pytest.mark.asyncio
    async def test_scene_update_bus_exception_is_caught(self):
        """Bus failure in scene_update path must not propagate."""
        bus = EventBus()
        # Monkey-patch publish to raise
        original_publish = bus.publish
        def failing_publish(topic, msg):
            if topic == TOPIC_SCENE_UPDATE:
                raise RuntimeError("bus-fail")
            return original_publish(topic, msg)
        bus.publish = failing_publish

        # Simulate the fail-open pattern from heartbeat.py
        broadcast_msg = {'type': 'scene_update'}
        try:
            bus.publish(TOPIC_SCENE_UPDATE, broadcast_msg)
        except Exception:
            pass  # This is what the try/except in heartbeat.py does

        # Other topics still work
        q = bus.subscribe(TOPIC_STAGE_PROGRESS, 'test')
        bus.publish(TOPIC_STAGE_PROGRESS, {'stage': 'ok'})
        assert q.get_nowait() == {'stage': 'ok'}
