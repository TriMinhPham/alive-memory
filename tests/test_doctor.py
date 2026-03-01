"""Tests for scripts/doctor.py health check functions."""

import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# Import the doctor module from scripts/
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "doctor",
    Path(__file__).resolve().parent.parent / "scripts" / "doctor.py",
)
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)


# ---------------------------------------------------------------------------
# check_env
# ---------------------------------------------------------------------------

class TestCheckEnv:
    def test_pass_all_set(self):
        env = {v: "x" for v in doctor.REQUIRED_ENV + doctor.OPTIONAL_ENV}
        with mock.patch.dict(os.environ, env, clear=False):
            status, msg = doctor.check_env()
        assert status == doctor.PASS

    def test_fail_missing_required(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            status, msg = doctor.check_env()
        assert status == doctor.FAIL
        assert "OPENROUTER_API_KEY" in msg

    def test_warn_optional_missing(self):
        env = {v: "x" for v in doctor.REQUIRED_ENV}
        with mock.patch.dict(os.environ, env, clear=True):
            status, msg = doctor.check_env()
        assert status == doctor.WARN
        assert "Optional" in msg


# ---------------------------------------------------------------------------
# check_docker
# ---------------------------------------------------------------------------

class TestCheckDocker:
    def test_pass_docker_and_image(self):
        version_result = subprocess.CompletedProcess([], 0, stdout="24.0.7\n")
        image_result = subprocess.CompletedProcess([], 0, stdout="2026-02-28T10:00:00\n")

        with mock.patch("subprocess.run", side_effect=[version_result, image_result]):
            doctor.PROD_MODE = False
            status, msg = doctor.check_docker()
        assert status == doctor.PASS
        assert "24.0.7" in msg

    def test_warn_no_docker_dev(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            doctor.PROD_MODE = False
            status, _ = doctor.check_docker()
        assert status == doctor.WARN

    def test_fail_no_docker_prod(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            doctor.PROD_MODE = True
            status, _ = doctor.check_docker()
        assert status == doctor.FAIL

    def test_warn_daemon_down_dev(self):
        result = subprocess.CompletedProcess([], 1, stdout="", stderr="error")
        with mock.patch("subprocess.run", return_value=result):
            doctor.PROD_MODE = False
            status, _ = doctor.check_docker()
        assert status == doctor.WARN

    def test_fail_daemon_down_prod(self):
        result = subprocess.CompletedProcess([], 1, stdout="", stderr="error")
        with mock.patch("subprocess.run", return_value=result):
            doctor.PROD_MODE = True
            status, _ = doctor.check_docker()
        assert status == doctor.FAIL

    def test_warn_no_image_dev(self):
        version_result = subprocess.CompletedProcess([], 0, stdout="24.0.7\n")
        image_result = subprocess.CompletedProcess([], 1, stdout="", stderr="No such image")
        with mock.patch("subprocess.run", side_effect=[version_result, image_result]):
            doctor.PROD_MODE = False
            status, msg = doctor.check_docker()
        assert status == doctor.WARN
        assert "image not found" in msg


# ---------------------------------------------------------------------------
# check_ports
# ---------------------------------------------------------------------------

class TestCheckPorts:
    def test_pass_lounge_and_docker_agents(self):
        ss_output = "LISTEN  0  128  *:3100  *:*\nLISTEN  0  128  *:9001  *:*\n"
        docker_agents = {"hina": 9001}

        with (
            mock.patch.object(doctor, "_get_listening_output", return_value=ss_output),
            mock.patch.object(doctor, "_get_docker_agent_ports", return_value=docker_agents),
        ):
            status, msg = doctor.check_ports()
        assert status == doctor.PASS
        assert "lounge:3100" in msg
        assert "hina:9001" in msg

    def test_no_false_positive_from_non_agent_port(self):
        """Port in range but not a Docker agent should NOT appear."""
        ss_output = "LISTEN  0  128  *:9002  *:*\n"
        docker_agents = {}  # no agent containers

        with (
            mock.patch.object(doctor, "_get_listening_output", return_value=ss_output),
            mock.patch.object(doctor, "_get_docker_agent_ports", return_value=docker_agents),
        ):
            status, msg = doctor.check_ports()
        # Should not report 9002 as an agent
        assert "9002" not in msg
        assert status == doctor.WARN  # nothing found

    def test_warn_no_tools(self):
        with mock.patch.object(doctor, "_get_listening_output", return_value=None):
            status, _ = doctor.check_ports()
        assert status == doctor.WARN


class TestPortHelpers:
    def test_port_in_output(self):
        assert doctor._port_in_output(3100, "LISTEN *:3100 *:*\n")
        assert doctor._port_in_output(9001, "tcp  0  0  *:9001\n")
        assert not doctor._port_in_output(9001, "tcp  0  0  *:19001 *:*\n")

    def test_get_docker_agent_ports_parses_format(self):
        docker_output = "alive-agent-hina\t0.0.0.0:9001->8080/tcp\nalive-agent-kuro\t0.0.0.0:9002->8080/tcp\n"
        result = subprocess.CompletedProcess([], 0, stdout=docker_output)

        with mock.patch("subprocess.run", return_value=result):
            agents = doctor._get_docker_agent_ports()
        assert agents == {"hina": 9001, "kuro": 9002}

    def test_get_docker_agent_ports_no_docker(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            agents = doctor._get_docker_agent_ports()
        assert agents == {}


# ---------------------------------------------------------------------------
# check_dbs
# ---------------------------------------------------------------------------

class TestCheckDbs:
    def test_pass_valid_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.close()

        with mock.patch.object(doctor, "DATA_DIR", tmp_path):
            status, msg = doctor.check_dbs()
        assert status == doctor.PASS
        assert "1 database" in msg

    def test_warn_no_data_dir(self, tmp_path):
        missing = tmp_path / "nonexistent"
        with mock.patch.object(doctor, "DATA_DIR", missing):
            status, _ = doctor.check_dbs()
        assert status == doctor.WARN

    def test_warn_no_db_files(self, tmp_path):
        with mock.patch.object(doctor, "DATA_DIR", tmp_path):
            status, _ = doctor.check_dbs()
        assert status == doctor.WARN


# ---------------------------------------------------------------------------
# check_disk
# ---------------------------------------------------------------------------

class TestCheckDisk:
    def test_pass_normal_usage(self):
        # 50% used
        usage = os.statvfs_result((0,) * 11) if hasattr(os, "statvfs_result") else None
        mock_usage = mock.Mock(total=100_000_000_000, used=50_000_000_000, free=50_000_000_000)
        with mock.patch("shutil.disk_usage", return_value=mock_usage):
            status, msg = doctor.check_disk()
        assert status == doctor.PASS
        assert "50%" in msg

    def test_warn_high_usage(self):
        mock_usage = mock.Mock(total=100_000_000_000, used=90_000_000_000, free=10_000_000_000)
        with mock.patch("shutil.disk_usage", return_value=mock_usage):
            status, _ = doctor.check_disk()
        assert status == doctor.WARN

    def test_fail_critical_usage(self):
        mock_usage = mock.Mock(total=100_000_000_000, used=96_000_000_000, free=4_000_000_000)
        with mock.patch("shutil.disk_usage", return_value=mock_usage):
            status, _ = doctor.check_disk()
        assert status == doctor.FAIL


# ---------------------------------------------------------------------------
# check_containers
# ---------------------------------------------------------------------------

class TestCheckContainers:
    def test_pass_all_running(self):
        result = subprocess.CompletedProcess([], 0, stdout="alive-agent-hina\trunning\n")
        with mock.patch("subprocess.run", return_value=result):
            doctor.PROD_MODE = False
            status, msg = doctor.check_containers()
        assert status == doctor.PASS
        assert "hina" in msg

    def test_fail_all_stopped(self):
        result = subprocess.CompletedProcess([], 0, stdout="alive-agent-hina\texited\n")
        with mock.patch("subprocess.run", return_value=result):
            doctor.PROD_MODE = False
            status, _ = doctor.check_containers()
        assert status == doctor.FAIL

    def test_warn_some_stopped(self):
        result = subprocess.CompletedProcess(
            [], 0, stdout="alive-agent-hina\trunning\nalive-agent-kuro\texited\n"
        )
        with mock.patch("subprocess.run", return_value=result):
            doctor.PROD_MODE = False
            status, msg = doctor.check_containers()
        assert status == doctor.WARN
        assert "1 running" in msg
        assert "1 stopped" in msg

    def test_warn_no_docker_dev(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            doctor.PROD_MODE = False
            status, _ = doctor.check_containers()
        assert status == doctor.WARN

    def test_fail_no_docker_prod(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            doctor.PROD_MODE = True
            status, _ = doctor.check_containers()
        assert status == doctor.FAIL


# ---------------------------------------------------------------------------
# check_network
# ---------------------------------------------------------------------------

class TestCheckNetwork:
    def test_pass_reachable(self):
        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
        mock_resp.__exit__ = mock.Mock(return_value=False)

        with mock.patch("urllib.request.urlopen", return_value=mock_resp):
            status, msg = doctor.check_network()
        assert status == doctor.PASS

    def test_fail_unreachable(self):
        import urllib.error
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            status, _ = doctor.check_network()
        assert status == doctor.FAIL


# ---------------------------------------------------------------------------
# main — exit code behavior
# ---------------------------------------------------------------------------

class TestMain:
    def test_exit_0_all_pass(self):
        all_pass = lambda: (doctor.PASS, "ok")
        checks = [("Test", all_pass)]
        with mock.patch.object(doctor, "CHECKS", checks):
            doctor.PROD_MODE = False
            code = doctor.main()
        assert code == 0

    def test_exit_1_any_fail(self):
        checks = [
            ("Good", lambda: (doctor.PASS, "ok")),
            ("Bad", lambda: (doctor.FAIL, "broken")),
        ]
        with mock.patch.object(doctor, "CHECKS", checks):
            doctor.PROD_MODE = False
            code = doctor.main()
        assert code == 1

    def test_exit_0_warns_only(self):
        checks = [("Meh", lambda: (doctor.WARN, "meh"))]
        with mock.patch.object(doctor, "CHECKS", checks):
            doctor.PROD_MODE = False
            code = doctor.main()
        assert code == 0

    def test_crashed_check_becomes_fail(self):
        def boom():
            raise RuntimeError("kaboom")
        checks = [("Boom", boom)]
        with mock.patch.object(doctor, "CHECKS", checks):
            doctor.PROD_MODE = False
            code = doctor.main()
        assert code == 1
