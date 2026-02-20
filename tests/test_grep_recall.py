"""Tests for hippocampus MD-first recall with SQLite fallback."""

import os
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from memory_writer import MemoryWriter
from memory_reader import MemoryReader, reset_memory_reader

JST = timezone(timedelta(hours=9))
FIXED_TIME = datetime(2026, 2, 19, 14, 32, 0, tzinfo=JST)


@pytest.fixture
def _mock_clock():
    with patch('memory_writer.clock') as w_clock, \
         patch('memory_reader.clock') as r_clock:
        w_clock.now.return_value = FIXED_TIME
        r_clock.now.return_value = FIXED_TIME
        yield


@pytest.fixture
def memory_setup(tmp_path, _mock_clock):
    """Set up a memory dir with writer and reader."""
    root = str(tmp_path / 'memory')
    writer = MemoryWriter(root=root)
    writer.ensure_dirs()
    reader = MemoryReader(root=root)
    return root, writer, reader


class TestRecallVisitorSummaryMDFirst:
    @pytest.mark.asyncio
    async def test_md_file_used_when_present(self, memory_setup):
        root, writer, reader = memory_setup
        await writer.append_visitor('vis_123', 'Alice', 'She loves music and rain.')

        with patch('pipeline.hippocampus.get_memory_reader', return_value=reader), \
             patch('pipeline.hippocampus.db') as mock_db:
            from pipeline.hippocampus import recall
            chunks = await recall([{'type': 'visitor_summary', 'visitor_id': 'vis_123'}])

            assert len(chunks) == 1
            assert 'Alice' in chunks[0]['label']
            assert 'music' in chunks[0]['content']
            # DB should NOT have been called
            mock_db.get_visitor.assert_not_called()

    @pytest.mark.asyncio
    async def test_sqlite_fallback_when_no_md(self, memory_setup):
        root, writer, reader = memory_setup
        # No MD file written

        mock_visitor = SimpleNamespace(
            name='Bob', visit_count=3, trust_level='familiar',
            emotional_imprint='warm', summary='A regular visitor.'
        )

        with patch('pipeline.hippocampus.get_memory_reader', return_value=reader), \
             patch('pipeline.hippocampus.db') as mock_db:
            mock_db.get_visitor = AsyncMock(return_value=mock_visitor)
            from pipeline.hippocampus import recall
            chunks = await recall([{'type': 'visitor_summary', 'visitor_id': 'vis_999'}])

            assert len(chunks) == 1
            assert 'Bob' in chunks[0]['label']
            mock_db.get_visitor.assert_called_once_with('vis_999')


class TestRecallRecentJournalMDFirst:
    @pytest.mark.asyncio
    async def test_md_used_when_present(self, memory_setup):
        root, writer, reader = memory_setup
        await writer.append_journal('I thought about Erik Satie today.')

        with patch('pipeline.hippocampus.get_memory_reader', return_value=reader), \
             patch('pipeline.hippocampus.db') as mock_db:
            from pipeline.hippocampus import recall
            chunks = await recall([{'type': 'recent_journal'}])

            assert len(chunks) >= 1
            assert any('Satie' in c['content'] for c in chunks)
            mock_db.get_recent_journal.assert_not_called()

    @pytest.mark.asyncio
    async def test_sqlite_fallback(self, memory_setup):
        root, writer, reader = memory_setup

        mock_entry = SimpleNamespace(content='Some old entry', mood='calm')

        with patch('pipeline.hippocampus.get_memory_reader', return_value=reader), \
             patch('pipeline.hippocampus.db') as mock_db:
            mock_db.get_recent_journal = AsyncMock(return_value=[mock_entry])
            from pipeline.hippocampus import recall
            chunks = await recall([{'type': 'recent_journal'}])

            assert len(chunks) == 1
            assert 'old entry' in chunks[0]['content']


class TestRecallSelfKnowledge:
    @pytest.mark.asyncio
    async def test_md_used_when_present(self, memory_setup):
        root, writer, reader = memory_setup
        await writer.write_self_file('identity.md', '# Who I Am\n\nA shopkeeper in Daikanyama.')

        with patch('pipeline.hippocampus.get_memory_reader', return_value=reader), \
             patch('pipeline.hippocampus.db') as mock_db:
            from pipeline.hippocampus import recall
            chunks = await recall([{'type': 'self_knowledge'}])

            assert len(chunks) == 1
            assert 'Daikanyama' in chunks[0]['content']
            mock_db.get_self_discoveries.assert_not_called()


class TestRecallDayContext:
    @pytest.mark.asyncio
    async def test_md_used_when_present(self, memory_setup):
        root, writer, reader = memory_setup
        await writer.append_journal('A visitor came in this morning.')

        with patch('pipeline.hippocampus.get_memory_reader', return_value=reader), \
             patch('pipeline.hippocampus.db') as mock_db:
            from pipeline.hippocampus import recall
            chunks = await recall([{'type': 'day_context'}])

            assert len(chunks) >= 1
            assert any('visitor' in c['content'] for c in chunks)
            mock_db.get_day_memory.assert_not_called()


class TestRecallInterfaceContract:
    @pytest.mark.asyncio
    async def test_returns_label_content_dicts(self, memory_setup):
        root, writer, reader = memory_setup
        await writer.append_journal('Test entry.')
        await writer.write_self_file('identity.md', '# Who I Am\n\nTest identity.')

        with patch('pipeline.hippocampus.get_memory_reader', return_value=reader), \
             patch('pipeline.hippocampus.db'):
            from pipeline.hippocampus import recall
            chunks = await recall([
                {'type': 'recent_journal'},
                {'type': 'self_knowledge'},
            ])

            for chunk in chunks:
                assert 'label' in chunk, f"Missing 'label' in chunk: {chunk}"
                assert 'content' in chunk, f"Missing 'content' in chunk: {chunk}"
                assert isinstance(chunk['label'], str)
                assert isinstance(chunk['content'], str)
