"""Tests for engine/preflight.py — startup validation checks."""

import os
import socket
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# preflight.py lives in engine/ — add to path if needed
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'engine'))

from preflight import (
    _check_config_dir,
    _check_db_lock,
    _check_env_vars,
    _check_packages,
    _check_port,
    _check_python_version,
    run_preflight,
)


# ---------------------------------------------------------------------------
# _check_env_vars
# ---------------------------------------------------------------------------

class TestCheckEnvVars:
    def test_both_set(self):
        with patch.dict(os.environ, {
            'OPENROUTER_API_KEY': 'sk-or-v1-test',
            'SHOPKEEPER_SERVER_TOKEN': 'token123',
        }):
            assert _check_env_vars() == []

    def test_missing_api_key(self):
        with patch.dict(os.environ, {
            'SHOPKEEPER_SERVER_TOKEN': 'token123',
        }, clear=True):
            errors = _check_env_vars()
            assert len(errors) == 1
            assert 'OPENROUTER_API_KEY' in errors[0]

    def test_missing_server_token(self):
        with patch.dict(os.environ, {
            'OPENROUTER_API_KEY': 'sk-or-v1-test',
        }, clear=True):
            errors = _check_env_vars()
            assert len(errors) == 1
            assert 'SHOPKEEPER_SERVER_TOKEN' in errors[0]

    def test_both_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            errors = _check_env_vars()
            assert len(errors) == 2

    def test_empty_string_counts_as_missing(self):
        with patch.dict(os.environ, {
            'OPENROUTER_API_KEY': '',
            'SHOPKEEPER_SERVER_TOKEN': '',
        }):
            errors = _check_env_vars()
            assert len(errors) == 2


# ---------------------------------------------------------------------------
# _check_python_version
# ---------------------------------------------------------------------------

class TestCheckPythonVersion:
    def test_current_version_passes(self):
        # We're running on 3.12+, so this should pass
        assert _check_python_version() == []

    def test_old_version_fails(self):
        with patch.object(sys, 'version_info', (3, 11, 0)):
            errors = _check_python_version()
            assert len(errors) == 1
            assert '3.12' in errors[0]

    def test_exact_312_passes(self):
        with patch.object(sys, 'version_info', (3, 12, 0)):
            assert _check_python_version() == []

    def test_future_version_passes(self):
        with patch.object(sys, 'version_info', (3, 14, 0)):
            assert _check_python_version() == []


# ---------------------------------------------------------------------------
# _check_packages
# ---------------------------------------------------------------------------

class TestCheckPackages:
    def test_all_installed(self):
        # aiosqlite, yaml, httpx should be installed in test env
        assert _check_packages() == []

    def test_missing_package(self):
        with patch('importlib.import_module', side_effect=ImportError("no module")):
            errors = _check_packages()
            assert len(errors) == 3  # all 3 fail

    def test_one_missing(self):
        original_import = __import__

        def selective_import(name, *args, **kwargs):
            if name == 'httpx':
                raise ImportError("no httpx")
            return original_import(name, *args, **kwargs)

        with patch('importlib.import_module', side_effect=selective_import):
            errors = _check_packages()
            assert len(errors) == 1
            assert 'httpx' in errors[0]


# ---------------------------------------------------------------------------
# _check_port
# ---------------------------------------------------------------------------

class TestCheckPort:
    def test_zero_port_skipped(self):
        assert _check_port(0) == []

    def test_negative_port_skipped(self):
        assert _check_port(-1) == []

    def test_free_port_passes(self):
        # Find a free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        # Port is now free
        assert _check_port(port) == []

    def test_occupied_port_fails(self):
        # Bind a port, then check it
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', 0))
            s.listen(1)
            port = s.getsockname()[1]
            errors = _check_port(port)
            assert len(errors) == 1
            assert str(port) in errors[0]


# ---------------------------------------------------------------------------
# _check_config_dir
# ---------------------------------------------------------------------------

class TestCheckConfigDir:
    def test_no_config_dir_set(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _check_config_dir() == []

    def test_nonexistent_dir(self):
        with patch.dict(os.environ, {'AGENT_CONFIG_DIR': '/tmp/nonexistent_xyz_999'}):
            errors = _check_config_dir()
            assert len(errors) == 1
            assert 'does not exist' in errors[0]

    def test_valid_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {'AGENT_CONFIG_DIR': tmpdir}):
                assert _check_config_dir() == []

    def test_valid_identity_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / 'identity.yaml').write_text('name: test\n')
            with patch.dict(os.environ, {'AGENT_CONFIG_DIR': tmpdir}):
                assert _check_config_dir() == []

    def test_invalid_identity_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / 'identity.yaml').write_text(': : invalid yaml {{{\n')
            with patch.dict(os.environ, {'AGENT_CONFIG_DIR': tmpdir}):
                errors = _check_config_dir()
                assert len(errors) == 1
                assert 'identity.yaml' in errors[0]

    def test_invalid_alive_config_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / 'alive_config.yaml').write_text(': bad\n  nope')
            with patch.dict(os.environ, {'AGENT_CONFIG_DIR': tmpdir}):
                errors = _check_config_dir()
                assert len(errors) == 1
                assert 'alive_config.yaml' in errors[0]

    def test_unwritable_db_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_dir = Path(tmpdir) / 'db'
            db_dir.mkdir()
            db_dir.chmod(0o444)
            try:
                with patch.dict(os.environ, {'AGENT_CONFIG_DIR': tmpdir}):
                    errors = _check_config_dir()
                    # On some systems root can still write — only check if non-root
                    if os.getuid() != 0:
                        assert len(errors) == 1
                        assert 'not writable' in errors[0]
            finally:
                db_dir.chmod(0o755)


# ---------------------------------------------------------------------------
# _check_db_lock
# ---------------------------------------------------------------------------

class TestCheckDbLock:
    def test_no_db_file(self):
        with patch.dict(os.environ, {
            'AGENT_CONFIG_DIR': '/tmp/nonexistent_xyz_999',
            'AGENT_ID': 'test',
        }):
            assert _check_db_lock() == []

    def test_unlocked_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'db' / 'test.db'
            db_path.parent.mkdir()
            # Create a valid SQLite DB
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.close()

            with patch.dict(os.environ, {
                'AGENT_CONFIG_DIR': tmpdir,
                'AGENT_ID': 'test',
            }):
                assert _check_db_lock() == []

    def test_locked_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'db' / 'test.db'
            db_path.parent.mkdir()

            # Create DB and hold exclusive lock
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.execute("BEGIN EXCLUSIVE")

            try:
                with patch.dict(os.environ, {
                    'AGENT_CONFIG_DIR': tmpdir,
                    'AGENT_ID': 'test',
                }):
                    errors = _check_db_lock()
                    assert len(errors) == 1
                    assert 'locked' in errors[0].lower()
            finally:
                conn.close()


# ---------------------------------------------------------------------------
# run_preflight (integration)
# ---------------------------------------------------------------------------

class TestRunPreflight:
    def test_all_pass(self, capsys):
        with patch.dict(os.environ, {
            'OPENROUTER_API_KEY': 'sk-or-v1-test',
            'SHOPKEEPER_SERVER_TOKEN': 'token123',
        }):
            result = run_preflight()
            assert result is True
            captured = capsys.readouterr()
            assert 'OK' in captured.out

    def test_failures_return_false(self, capsys):
        with patch.dict(os.environ, {}, clear=True):
            result = run_preflight()
            assert result is False
            captured = capsys.readouterr()
            assert 'error(s) found' in captured.out

    def test_port_check_included(self):
        with patch.dict(os.environ, {
            'OPENROUTER_API_KEY': 'sk-or-v1-test',
            'SHOPKEEPER_SERVER_TOKEN': 'token123',
        }):
            # Bind a port, pass it to preflight
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('127.0.0.1', 0))
                s.listen(1)
                port = s.getsockname()[1]
                result = run_preflight(http_port=port)
                assert result is False

    def test_same_port_checked_once(self):
        """When http_port == ws_port, only check once."""
        with patch('preflight._check_port') as mock_check:
            mock_check.return_value = []
            with patch.dict(os.environ, {
                'OPENROUTER_API_KEY': 'sk-or-v1-test',
                'SHOPKEEPER_SERVER_TOKEN': 'token123',
            }):
                run_preflight(http_port=8080, ws_port=8080)
                # Should be called once for 8080, not twice
                assert mock_check.call_count == 1
