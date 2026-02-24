"""Heartbeat watchdog and health status tests."""

import asyncio
from datetime import timedelta
import time
from unittest.mock import AsyncMock

import pytest

import clock
from heartbeat import Heartbeat


def test_health_degraded_when_loop_heartbeat_stale():
    hb = Heartbeat()
    hb.running = True
    hb._last_loop_tick_ts = clock.now_utc() - timedelta(
        seconds=hb.HEALTH_DEGRADED_AFTER_SECONDS + 5
    )

    health = hb.get_health_status()

    assert health['status'] == 'degraded'
    assert health['reason'] == 'loop_heartbeat_stale'


@pytest.mark.asyncio
async def test_health_alive_when_loop_and_supervisor_running():
    hb = Heartbeat()
    hb.running = True
    hb._touch_loop_heartbeat()
    hb._supervisor_task = asyncio.create_task(asyncio.sleep(10))
    hb._loop_task = asyncio.create_task(asyncio.sleep(10))

    try:
        health = hb.get_health_status()
        assert health['status'] == 'alive'
        assert health['loop_running'] is True
        assert health['supervisor_running'] is True
    finally:
        hb._supervisor_task.cancel()
        hb._loop_task.cancel()
        await asyncio.gather(
            hb._supervisor_task, hb._loop_task, return_exceptions=True
        )
        hb._supervisor_task = None
        hb._loop_task = None


@pytest.mark.asyncio
async def test_supervisor_restarts_main_loop_after_crash(monkeypatch):
    hb = Heartbeat()
    hb.running = True
    hb.SUPERVISOR_RESTART_MIN = 0.01
    hb.SUPERVISOR_RESTART_MAX = 0.05
    monkeypatch.setattr('heartbeat.db.log_runtime_event', AsyncMock())
    calls = 0
    restarted = asyncio.Event()

    async def fake_main_loop():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError('boom')
        restarted.set()
        hb.running = False

    monkeypatch.setattr(hb, '_main_loop', fake_main_loop)

    supervisor = asyncio.create_task(hb._main_loop_supervisor())
    try:
        await asyncio.wait_for(restarted.wait(), timeout=1)
        await asyncio.wait_for(supervisor, timeout=1)
    finally:
        hb.running = False
        if not supervisor.done():
            supervisor.cancel()
            await asyncio.gather(supervisor, return_exceptions=True)

    assert calls == 2
    assert hb._loop_restart_count == 1
    assert hb._last_loop_error is not None
    assert hb._last_loop_error.startswith('RuntimeError')


@pytest.mark.asyncio
async def test_stop_cancels_loop_even_if_supervisor_drops_task_ref(monkeypatch):
    hb = Heartbeat()
    hb.running = True
    monkeypatch.setattr('heartbeat.db.log_runtime_event', AsyncMock())
    monkeypatch.setattr('heartbeat.db.mark_run_end', AsyncMock())

    loop_task = asyncio.create_task(asyncio.sleep(60))
    hb._loop_task = loop_task

    blocker = asyncio.Event()

    async def fake_supervisor():
        try:
            await blocker.wait()
        finally:
            # Simulate supervisor cleanup dropping the shared reference.
            hb._loop_task = None

    hb._supervisor_task = asyncio.create_task(fake_supervisor())

    real_wait_for = asyncio.wait_for

    async def fake_wait_for(awaitable, timeout):
        if awaitable is hb._supervisor_task:
            raise asyncio.TimeoutError
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr('heartbeat.asyncio.wait_for', fake_wait_for)

    await hb.stop()

    assert loop_task.cancelled()
    assert hb._loop_task is None
    assert hb._supervisor_task is None


@pytest.mark.asyncio
async def test_supervisor_backoff_wakes_immediately_on_stop(monkeypatch):
    hb = Heartbeat()
    hb.running = True
    hb.SUPERVISOR_RESTART_MIN = 30
    hb.SUPERVISOR_RESTART_MAX = 30
    monkeypatch.setattr('heartbeat.db.log_runtime_event', AsyncMock())

    crashed = asyncio.Event()

    async def crash_loop():
        crashed.set()
        raise RuntimeError('boom')

    monkeypatch.setattr(hb, '_main_loop', crash_loop)

    supervisor = asyncio.create_task(hb._main_loop_supervisor())
    await asyncio.wait_for(crashed.wait(), timeout=1)

    start = time.monotonic()
    hb.running = False
    hb._wake_event.set()
    await asyncio.wait_for(supervisor, timeout=1)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0
