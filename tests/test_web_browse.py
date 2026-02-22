"""Tests for body/web.py — web browse executor."""

import sys
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from models.pipeline import ActionRequest, ActionResult


@pytest.fixture(autouse=True)
def _patch_deps():
    """Mock all external deps for web browse executor."""
    mock_writer = MagicMock()
    mock_writer.append_browse = AsyncMock()
    with patch('body.web.clock') as mock_clock, \
         patch('body.web.get_limiter_decision', new_callable=AsyncMock) as mock_rate, \
         patch('body.web.record_action', new_callable=AsyncMock), \
         patch('body.rate_limiter.is_channel_enabled', new_callable=AsyncMock) as mock_chan, \
         patch('body.web.db') as mock_db:
        mock_clock.now_utc.return_value = datetime(2025, 1, 1, tzinfo=timezone.utc)
        mock_clock.now.return_value = datetime(2025, 1, 1, tzinfo=timezone.utc)
        mock_rate.return_value = {
            'allowed': True,
            'reason': '',
            'limiter_decision': 'allow',
            'cooldown_state': 'ready',
            'rate_limit_remaining': 1,
        }
        mock_chan.return_value = True
        mock_db.append_event = AsyncMock()
        # Mock memory_writer and memory_translator to prevent real file I/O
        mock_mem_writer_mod = MagicMock()
        mock_mem_writer_mod.get_memory_writer.return_value = mock_writer
        mock_mem_translator_mod = MagicMock()
        mock_mem_translator_mod.scrub_numbers = lambda x: x
        with patch.dict('sys.modules', {
            'memory_writer': mock_mem_writer_mod,
            'memory_translator': mock_mem_translator_mod,
        }):
            yield {
                'clock': mock_clock,
                'rate_limit': mock_rate,
                'channel_enabled': mock_chan,
                'db': mock_db,
                'memory_writer': mock_writer,
            }


class TestBrowseWeb:
    """Test execute_browse_web executor."""

    @pytest.mark.asyncio
    async def test_successful_search(self, _patch_deps):
        """Successful search returns content."""
        from body.web import execute_browse_web
        action = ActionRequest(type='browse_web', detail={'query': 'test search'})

        with patch('body.web._web_search', new_callable=AsyncMock) as mock_search:
            mock_search.return_value = 'Search results: found something'
            # insert_pool_item is a local import that may not exist — just let it error silently
            with patch.dict('sys.modules', {'db.content': MagicMock()}):
                result = await execute_browse_web(action)

        assert result.success is True
        assert result.content == 'Search results: found something'
        assert result.payload['query'] == 'test search'

    @pytest.mark.asyncio
    async def test_empty_query_fails(self, _patch_deps):
        """Empty query returns error."""
        from body.web import execute_browse_web
        action = ActionRequest(type='browse_web', detail={})
        result = await execute_browse_web(action)
        assert result.success is False
        assert 'no search query' in result.error

    @pytest.mark.asyncio
    async def test_rate_limit_blocks(self, _patch_deps):
        """Rate limit blocks execution."""
        _patch_deps['rate_limit'].return_value = {
            'allowed': False,
            'reason': 'hourly limit reached',
            'limiter_decision': 'deny:hourly_limit',
            'cooldown_state': 'ready',
            'rate_limit_remaining': 0,
        }
        from body.web import execute_browse_web
        action = ActionRequest(type='browse_web', detail={'query': 'test'})
        result = await execute_browse_web(action)
        assert result.success is False
        assert 'hourly limit' in result.error

    @pytest.mark.asyncio
    async def test_channel_disabled_blocks(self, _patch_deps):
        """Disabled web channel blocks execution."""
        _patch_deps['channel_enabled'].return_value = False
        from body.web import execute_browse_web
        action = ActionRequest(type='browse_web', detail={'query': 'test'})
        result = await execute_browse_web(action)
        assert result.success is False
        assert 'channel disabled' in result.error

    @pytest.mark.asyncio
    async def test_long_results_truncated(self, _patch_deps):
        """Results > 6000 chars are truncated."""
        from body.web import execute_browse_web
        action = ActionRequest(type='browse_web', detail={'query': 'big search'})

        with patch('body.web._web_search', new_callable=AsyncMock) as mock_search:
            mock_search.return_value = 'x' * 8000
            with patch.dict('sys.modules', {'db.content': MagicMock()}):
                result = await execute_browse_web(action)

        assert result.success is True
        assert len(result.content) < 8000
        assert '[...truncated]' in result.content

    @pytest.mark.asyncio
    async def test_pool_insert_failure_skips_event(self, _patch_deps):
        """Pool insert failure → no content_consumed event emitted."""
        from body.web import execute_browse_web
        action = ActionRequest(type='browse_web', detail={'query': 'test search'})

        mock_insert = AsyncMock(side_effect=Exception('DB locked'))
        mock_content_mod = MagicMock()
        mock_content_mod.insert_pool_item = mock_insert

        with patch('body.web._web_search', new_callable=AsyncMock) as mock_search:
            mock_search.return_value = 'Search results'
            with patch.dict('sys.modules', {'db.content': mock_content_mod}):
                result = await execute_browse_web(action)

        # Action still succeeds (content was fetched)
        assert result.success is True
        assert result.content == 'Search results'
        # But no content_consumed event should have been emitted
        _patch_deps['db'].append_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_pool_insert_success_emits_event(self, _patch_deps):
        """Pool insert success → content_consumed event emitted."""
        from body.web import execute_browse_web
        action = ActionRequest(type='browse_web', detail={'query': 'test search'})

        mock_insert = AsyncMock()
        mock_content_mod = MagicMock()
        mock_content_mod.insert_pool_item = mock_insert

        with patch('body.web._web_search', new_callable=AsyncMock) as mock_search:
            mock_search.return_value = 'Search results'
            with patch.dict('sys.modules', {'db.content': mock_content_mod}):
                result = await execute_browse_web(action)

        assert result.success is True
        # content_consumed event should have been emitted
        _patch_deps['db'].append_event.assert_called_once()
        event = _patch_deps['db'].append_event.call_args[0][0]
        assert event.event_type == 'content_consumed'
        assert event.payload['source'] == 'browse_web'
