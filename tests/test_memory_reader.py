"""Tests for memory_reader — grep-based conscious memory recall."""

import os
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

import pytest

from memory_reader import MemoryReader
from memory_writer import MemoryWriter

JST = timezone(timedelta(hours=9))
FIXED_TIME = datetime(2026, 2, 19, 14, 32, 0, tzinfo=JST)


@pytest.fixture
def _mock_clock():
    """Mock clock.now() for both writer and reader."""
    with patch('memory_writer.clock') as w_clock, \
         patch('memory_reader.clock') as r_clock:
        w_clock.now.return_value = FIXED_TIME
        r_clock.now.return_value = FIXED_TIME
        yield


@pytest.fixture
def memory_dir(tmp_path, _mock_clock):
    """Create a memory dir with some seed content."""
    root = str(tmp_path / 'memory')
    writer = MemoryWriter(root=root)
    writer.ensure_dirs()
    return root, writer


class TestGrepMemory:
    @pytest.mark.asyncio
    async def test_finds_keyword(self, memory_dir):
        root, writer = memory_dir
        await writer.append_journal('I heard Erik Satie playing softly.')
        reader = MemoryReader(root=root)

        results = await reader.grep_memory('Satie', directories=['journal'])
        assert len(results) >= 1
        assert any('Satie' in r['content'] for r in results)

    @pytest.mark.asyncio
    async def test_returns_label_content_dicts(self, memory_dir):
        root, writer = memory_dir
        await writer.append_journal('Some entry here.')
        reader = MemoryReader(root=root)

        results = await reader.grep_memory('entry', directories=['journal'])
        for r in results:
            assert 'label' in r
            assert 'content' in r

    @pytest.mark.asyncio
    async def test_empty_directory_returns_empty(self, memory_dir):
        root, _ = memory_dir
        reader = MemoryReader(root=root)
        results = await reader.grep_memory('anything')
        assert results == []

    @pytest.mark.asyncio
    async def test_max_results_respected(self, memory_dir):
        root, writer = memory_dir
        for i in range(10):
            await writer.append_journal(f'Entry number {i} about music.')
        reader = MemoryReader(root=root)

        results = await reader.grep_memory('music', max_results=3)
        assert len(results) <= 3


class TestReadVisitor:
    @pytest.mark.asyncio
    async def test_reads_visitor_file(self, memory_dir):
        root, writer = memory_dir
        await writer.append_visitor('visitor_abc', 'Heo', 'He brought music.')
        reader = MemoryReader(root=root)

        result = await reader.read_visitor('visitor_abc')
        assert result is not None
        assert result['label'] == 'Memory of Heo'
        assert 'music' in result['content']

    @pytest.mark.asyncio
    async def test_nonexistent_visitor_returns_none(self, memory_dir):
        root, _ = memory_dir
        reader = MemoryReader(root=root)
        result = await reader.read_visitor('nonexistent')
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_source_key_returns_none(self, memory_dir):
        root, _ = memory_dir
        reader = MemoryReader(root=root)
        assert await reader.read_visitor('') is None


class TestReadRecentJournal:
    @pytest.mark.asyncio
    async def test_reads_today(self, memory_dir):
        root, writer = memory_dir
        await writer.append_journal('Morning thoughts.')
        await writer.append_journal('Afternoon reflection.')
        reader = MemoryReader(root=root)

        results = await reader.read_recent_journal()
        assert len(results) >= 1
        # Should get the most recent entry
        assert any('thoughts' in r['content'] or 'reflection' in r['content']
                    for r in results)

    @pytest.mark.asyncio
    async def test_empty_journal_returns_empty(self, memory_dir):
        root, _ = memory_dir
        reader = MemoryReader(root=root)
        results = await reader.read_recent_journal()
        assert results == []


class TestReadDayContext:
    @pytest.mark.asyncio
    async def test_reads_today_as_earlier(self, memory_dir):
        root, writer = memory_dir
        await writer.append_journal('This happened earlier.')
        reader = MemoryReader(root=root)

        results = await reader.read_day_context()
        assert len(results) >= 1
        assert results[0]['label'] == 'Earlier today'


class TestReadSelfKnowledge:
    @pytest.mark.asyncio
    async def test_reads_self_files(self, memory_dir):
        root, writer = memory_dir
        await writer.write_self_file('identity.md', '# Who I Am\n\nA quiet shopkeeper.')
        await writer.write_self_file('traits.md', '# My Traits\n\n- Curious\n- Guarded')
        reader = MemoryReader(root=root)

        result = await reader.read_self_knowledge()
        assert result is not None
        assert 'Things I know about myself' in result['label']
        assert 'shopkeeper' in result['content']
        assert 'Curious' in result['content']

    @pytest.mark.asyncio
    async def test_no_self_files_returns_none(self, memory_dir):
        root, _ = memory_dir
        reader = MemoryReader(root=root)
        assert await reader.read_self_knowledge() is None


class TestReadCollection:
    @pytest.mark.asyncio
    async def test_reads_catalog(self, memory_dir):
        root, writer = memory_dir
        await writer.append_collection('- **Erik Satie** — Quiet notes')
        await writer.append_collection('- **Rain photo** — Reflection')
        reader = MemoryReader(root=root)

        results = await reader.read_collection()
        assert len(results) >= 1
        assert 'Satie' in results[0]['content']

    @pytest.mark.asyncio
    async def test_search_collection(self, memory_dir):
        root, writer = memory_dir
        await writer.append_collection('- **Erik Satie** — Quiet notes')
        await writer.append_collection('- **Camus** — Freedom quote')
        reader = MemoryReader(root=root)

        results = await reader.read_collection(query='Camus')
        assert len(results) >= 1
        assert 'Camus' in results[0]['content']


class TestReadThreads:
    @pytest.mark.asyncio
    async def test_reads_threads(self, memory_dir):
        root, writer = memory_dir
        await writer.append_thread('rain-memory', 'Why does rain remind me of home?')
        reader = MemoryReader(root=root)

        results = await reader.read_threads()
        assert len(results) >= 1
        assert 'rain-memory' in results[0]['label']
        assert 'rain' in results[0]['content']

    @pytest.mark.asyncio
    async def test_empty_threads_returns_empty(self, memory_dir):
        root, _ = memory_dir
        reader = MemoryReader(root=root)
        assert await reader.read_threads() == []
