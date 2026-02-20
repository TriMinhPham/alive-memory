"""Tests for memory_writer — append-only conscious memory layer."""

import os
from unittest.mock import patch

import pytest

from memory_writer import MemoryWriter, slugify


@pytest.fixture
def writer(tmp_path):
    """Create a MemoryWriter with a temporary root directory."""
    w = MemoryWriter(root=str(tmp_path / 'memory'))
    w.ensure_dirs()
    return w


@pytest.fixture
def _mock_clock():
    """Mock clock.now() to return a fixed JST time."""
    from datetime import datetime, timezone, timedelta
    JST = timezone(timedelta(hours=9))
    fixed = datetime(2026, 2, 19, 14, 32, 0, tzinfo=JST)
    with patch('memory_writer.clock') as mock_clock:
        mock_clock.now.return_value = fixed
        yield mock_clock


class TestEnsureDirs:
    def test_creates_all_directories(self, writer):
        for d in ('journal', 'visitors', 'reflections', 'browse',
                  'self', 'threads', 'collection'):
            assert os.path.isdir(os.path.join(writer.root, d))

    def test_idempotent(self, writer):
        # Calling again should not raise
        writer.ensure_dirs()
        assert os.path.isdir(os.path.join(writer.root, 'journal'))


class TestAppendJournal:
    @pytest.mark.asyncio
    async def test_creates_dated_file(self, writer, _mock_clock):
        await writer.append_journal('Something happened today.')
        path = os.path.join(writer.root, 'journal', '2026-02-19.md')
        assert os.path.exists(path)
        content = open(path).read()
        assert '## 14:32' in content
        assert 'Something happened today.' in content

    @pytest.mark.asyncio
    async def test_appends_not_overwrites(self, writer, _mock_clock):
        await writer.append_journal('First entry.')
        await writer.append_journal('Second entry.')
        path = os.path.join(writer.root, 'journal', '2026-02-19.md')
        content = open(path).read()
        assert 'First entry.' in content
        assert 'Second entry.' in content

    @pytest.mark.asyncio
    async def test_includes_mood_and_tags(self, writer, _mock_clock):
        await writer.append_journal('Entry', mood_desc='reflective',
                                    tags=['sleep', 'quiet'])
        path = os.path.join(writer.root, 'journal', '2026-02-19.md')
        content = open(path).read()
        assert 'mood: reflective' in content
        assert 'tags: sleep, quiet' in content

    @pytest.mark.asyncio
    async def test_empty_text_skipped(self, writer, _mock_clock):
        await writer.append_journal('')
        path = os.path.join(writer.root, 'journal', '2026-02-19.md')
        assert not os.path.exists(path)

    @pytest.mark.asyncio
    async def test_scrubs_numbers(self, writer, _mock_clock):
        await writer.append_journal('Arousal was 0.84 and valence 0.22.')
        path = os.path.join(writer.root, 'journal', '2026-02-19.md')
        content = open(path).read()
        assert '0.84' not in content
        assert '0.22' not in content


class TestAppendVisitor:
    @pytest.mark.asyncio
    async def test_creates_visitor_file(self, writer, _mock_clock):
        await writer.append_visitor('visitor_abc', 'Heo', 'He came back.')
        path = os.path.join(writer.root, 'visitors', 'visitor_abc.md')
        assert os.path.exists(path)
        content = open(path).read()
        assert '# Visitor: Heo' in content
        assert 'He came back.' in content

    @pytest.mark.asyncio
    async def test_appends_to_existing(self, writer, _mock_clock):
        await writer.append_visitor('v1', 'Alice', 'First visit.')
        await writer.append_visitor('v1', 'Alice', 'Second visit.')
        path = os.path.join(writer.root, 'visitors', 'v1.md')
        content = open(path).read()
        assert 'First visit.' in content
        assert 'Second visit.' in content

    @pytest.mark.asyncio
    async def test_empty_entry_skipped(self, writer, _mock_clock):
        await writer.append_visitor('v1', 'Alice', '')
        path = os.path.join(writer.root, 'visitors', 'v1.md')
        assert not os.path.exists(path)


class TestWriteSelfFile:
    @pytest.mark.asyncio
    async def test_overwrites_not_appends(self, writer, _mock_clock):
        await writer.write_self_file('identity.md', 'Version 1')
        await writer.write_self_file('identity.md', 'Version 2')
        path = os.path.join(writer.root, 'self', 'identity.md')
        content = open(path).read()
        assert 'Version 1' not in content
        assert 'Version 2' in content

    @pytest.mark.asyncio
    async def test_adds_md_extension(self, writer, _mock_clock):
        await writer.write_self_file('traits', 'My traits here')
        path = os.path.join(writer.root, 'self', 'traits.md')
        assert os.path.exists(path)


class TestAnnotate:
    @pytest.mark.asyncio
    async def test_adds_bracketed_note(self, writer, _mock_clock):
        # Create a file first
        await writer.append_journal('Some entry')
        await writer.annotate('journal/2026-02-19.md', 'Looking back, this was important.')
        path = os.path.join(writer.root, 'journal', '2026-02-19.md')
        content = open(path).read()
        assert '[annotation' in content
        assert 'Looking back' in content

    @pytest.mark.asyncio
    async def test_nonexistent_file_skipped(self, writer, _mock_clock):
        # Should not raise
        await writer.annotate('journal/nonexistent.md', 'note')


class TestAppendReflection:
    @pytest.mark.asyncio
    async def test_creates_reflection_file(self, writer, _mock_clock):
        await writer.append_reflection('2026-02-19', 'night', 'I dreamed of rain.')
        path = os.path.join(writer.root, 'reflections', '2026-02-19-night.md')
        assert os.path.exists(path)
        content = open(path).read()
        assert 'I dreamed of rain.' in content


class TestAppendBrowse:
    @pytest.mark.asyncio
    async def test_creates_browse_file(self, writer, _mock_clock):
        await writer.append_browse('2026-02-19', 'erik-satie', '# Web search: erik satie\n\nResults...')
        path = os.path.join(writer.root, 'browse', '2026-02-19-erik-satie.md')
        assert os.path.exists(path)


class TestAppendThread:
    @pytest.mark.asyncio
    async def test_creates_thread_file(self, writer, _mock_clock):
        await writer.append_thread('rain-and-memory', 'Why does rain remind me of Tokyo?')
        path = os.path.join(writer.root, 'threads', 'rain-and-memory.md')
        assert os.path.exists(path)
        content = open(path).read()
        assert 'rain remind me' in content


class TestAppendCollection:
    @pytest.mark.asyncio
    async def test_creates_catalog_with_header(self, writer, _mock_clock):
        await writer.append_collection('- **Erik Satie** — Quiet notes')
        path = os.path.join(writer.root, 'collection', 'catalog.md')
        content = open(path).read()
        assert '# My Collection' in content
        assert 'Erik Satie' in content


class TestSlugify:
    def test_basic(self):
        assert slugify('Hello World!') == 'hello-world'

    def test_max_length(self):
        assert len(slugify('a' * 100, max_len=50)) <= 50

    def test_special_chars(self):
        assert slugify('Erik Satie — Gymnopédie No.1') == 'erik-satie-gymnop-die-no-1'
