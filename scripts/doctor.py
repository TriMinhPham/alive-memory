#!/usr/bin/env python3
"""
doctor.py — ALIVE system health checker.

Read-only diagnostic. Outputs a human-readable report.
Exit 0 if all checks pass, exit 1 if any fail.

Usage:
    python scripts/doctor.py           # dev mode (Docker issues = WARN)
    python scripts/doctor.py --prod    # prod mode (Docker issues = FAIL)

Prod mode is auto-detected when DATA_DIR exists.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_ENV = ["OPENROUTER_API_KEY"]
OPTIONAL_ENV = ["SHOPKEEPER_DB_PATH", "FAL_KEY", "OPENAI_API_KEY", "COLD_SEARCH_ENABLED"]

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data/alive-agents"))
LOUNGE_PORT = 3100
OPENROUTER_HEALTH_URL = "https://openrouter.ai/api/v1/models"

# Status constants
PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

# Prod mode: set by --prod flag or auto-detected when DATA_DIR exists.
# In prod mode, Docker/container issues are FAIL instead of WARN.
PROD_MODE = False


# ---------------------------------------------------------------------------
# Check functions — each returns (status, message)
# ---------------------------------------------------------------------------

def check_env() -> tuple[str, str]:
    """Check that required environment variables are set."""
    missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
    unset_optional = [v for v in OPTIONAL_ENV if not os.environ.get(v)]

    if missing:
        return FAIL, f"Missing required: {', '.join(missing)}"

    if unset_optional:
        return WARN, f"Optional not set: {', '.join(unset_optional)}"

    return PASS, "All env vars present"


def check_docker() -> tuple[str, str]:
    """Check that Docker is available and alive-engine:latest image exists."""
    severity = FAIL if PROD_MODE else WARN

    # Check docker binary
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=5,
        )
    except FileNotFoundError:
        return severity, "Docker not installed"
    except subprocess.TimeoutExpired:
        return FAIL, "Docker command timed out"

    if result.returncode != 0:
        return severity, "Docker daemon not running"

    docker_version = result.stdout.strip()

    # Check image
    result = subprocess.run(
        ["docker", "image", "inspect", "alive-engine:latest",
         "--format", "{{.Created}}"],
        capture_output=True, text=True, timeout=5,
    )

    if result.returncode != 0:
        return severity, f"Docker {docker_version} OK, but alive-engine:latest image not found"

    image_created = result.stdout.strip()[:19]  # trim to readable datetime
    return PASS, f"Docker {docker_version}, image built {image_created}"


def _get_listening_output() -> str | None:
    """Get raw output from ss or lsof showing listening ports."""
    try:
        result = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout
    except FileNotFoundError:
        pass

    # macOS fallback
    try:
        result = subprocess.run(
            ["lsof", "-i", "-P", "-n", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout
    except FileNotFoundError:
        pass

    return None


def _get_docker_agent_ports() -> dict[str, int]:
    """Query Docker for alive-agent-* container port mappings.

    Returns {agent_id: host_port} for running containers.
    """
    agents: dict[str, int] = {}
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=alive-agent-",
             "--format", "{{.Names}}\t{{.Ports}}"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return agents

    if result.returncode != 0:
        return agents

    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t", 1)
        name = parts[0].replace("alive-agent-", "")
        port_str = parts[1] if len(parts) > 1 else ""
        # Format: "0.0.0.0:9001->8080/tcp" — extract host port
        for mapping in port_str.split(","):
            mapping = mapping.strip()
            if "->" in mapping and "8080" in mapping:
                try:
                    host_part = mapping.split("->")[0]
                    port = int(host_part.rsplit(":", 1)[-1])
                    agents[name] = port
                except (ValueError, IndexError):
                    pass

    return agents


def _port_in_output(port: int, output: str) -> bool:
    """Check if a port appears in ss/lsof output."""
    return (f":{port} " in output
            or f":{port}\n" in output
            or f"*:{port}" in output)


def check_ports() -> tuple[str, str]:
    """Check expected ports for ALIVE services.

    Uses Docker port mappings to identify agent ports (avoids false
    positives from non-agent listeners). Falls back to lounge-only
    check when Docker is unavailable.
    """
    output = _get_listening_output()
    if output is None:
        return WARN, "Neither ss nor lsof available — cannot check ports"

    listening: list[str] = []

    # Check lounge port
    if _port_in_output(LOUNGE_PORT, output):
        listening.append(f"lounge:{LOUNGE_PORT}")

    # Use Docker to get verified agent port mappings
    docker_agents = _get_docker_agent_ports()
    for agent_id, port in sorted(docker_agents.items(), key=lambda x: x[1]):
        if _port_in_output(port, output):
            listening.append(f"{agent_id}:{port}")
        else:
            listening.append(f"{agent_id}:{port}(mapped but not listening)")

    if not listening:
        return WARN, "No ALIVE services detected on expected ports"

    return PASS, f"Listening: {', '.join(listening)}"


def check_dbs() -> tuple[str, str]:
    """Run PRAGMA integrity_check on each agent's DB."""
    if not DATA_DIR.exists():
        return WARN, f"Data directory {DATA_DIR} not found (expected in dev)"

    db_files = list(DATA_DIR.rglob("*.db"))
    if not db_files:
        return WARN, f"No .db files found under {DATA_DIR}"

    results: list[str] = []
    failures: list[str] = []

    for db_path in db_files:
        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            cursor = conn.execute("PRAGMA integrity_check")
            status = cursor.fetchone()[0]
            conn.close()

            name = db_path.relative_to(DATA_DIR)
            if status == "ok":
                results.append(str(name))
            else:
                failures.append(f"{name}: {status}")
        except Exception as e:
            failures.append(f"{db_path.name}: {e}")

    if failures:
        return FAIL, f"DB integrity failures: {'; '.join(failures)}"

    return PASS, f"{len(results)} database(s) OK: {', '.join(results)}"


def check_disk() -> tuple[str, str]:
    """Check disk space on the data partition."""
    check_path = str(DATA_DIR) if DATA_DIR.exists() else "/"

    usage = shutil.disk_usage(check_path)
    free_gb = usage.free / (1024 ** 3)
    total_gb = usage.total / (1024 ** 3)
    used_pct = (usage.used / usage.total) * 100

    if used_pct > 95:
        return FAIL, f"{used_pct:.0f}% used — {free_gb:.1f} GB free of {total_gb:.0f} GB ({check_path})"

    if used_pct > 85:
        return WARN, f"{used_pct:.0f}% used — {free_gb:.1f} GB free of {total_gb:.0f} GB ({check_path})"

    return PASS, f"{used_pct:.0f}% used — {free_gb:.1f} GB free of {total_gb:.0f} GB ({check_path})"


def check_containers() -> tuple[str, str]:
    """Check status of all alive-agent-* containers."""
    severity = FAIL if PROD_MODE else WARN

    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=alive-agent-",
             "--format", "{{.Names}}\t{{.State}}"],
            capture_output=True, text=True, timeout=5,
        )
    except FileNotFoundError:
        return severity, "Docker not installed"
    except subprocess.TimeoutExpired:
        return FAIL, "Docker command timed out"

    if result.returncode != 0:
        return severity, "Docker daemon not running"

    lines = [l for l in result.stdout.strip().split("\n") if l]
    if not lines:
        return severity, "No agent containers found"

    running = []
    stopped = []
    for line in lines:
        parts = line.split("\t")
        name = parts[0].replace("alive-agent-", "")
        state = parts[1] if len(parts) > 1 else "unknown"
        if state == "running":
            running.append(name)
        else:
            stopped.append(f"{name}({state})")

    parts_out: list[str] = []
    if running:
        parts_out.append(f"{len(running)} running: {', '.join(running)}")
    if stopped:
        parts_out.append(f"{len(stopped)} stopped: {', '.join(stopped)}")

    status = FAIL if stopped and not running else (WARN if stopped else PASS)
    return status, "; ".join(parts_out)


def check_network() -> tuple[str, str]:
    """Check connectivity to OpenRouter API."""
    try:
        req = urllib.request.Request(OPENROUTER_HEALTH_URL, method="GET")
        req.add_header("User-Agent", "alive-doctor/1.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return PASS, f"OpenRouter reachable (HTTP {resp.status})"
            return WARN, f"OpenRouter returned HTTP {resp.status}"
    except urllib.error.URLError as e:
        return FAIL, f"Cannot reach OpenRouter: {e.reason}"
    except Exception as e:
        return FAIL, f"Network error: {e}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

CHECKS = [
    ("Environment variables", check_env),
    ("Docker engine & image", check_docker),
    ("Listening ports", check_ports),
    ("Database integrity", check_dbs),
    ("Disk space", check_disk),
    ("Agent containers", check_containers),
    ("Network (OpenRouter)", check_network),
]

STATUS_LABEL = {
    PASS: "\033[32m[PASS]\033[0m",
    WARN: "\033[33m[WARN]\033[0m",
    FAIL: "\033[31m[FAIL]\033[0m",
}


def main() -> int:
    global PROD_MODE
    if "--prod" in sys.argv:
        PROD_MODE = True
    elif DATA_DIR.exists():
        PROD_MODE = True

    mode_label = "PROD" if PROD_MODE else "DEV"
    print("=" * 60)
    print(f"  ALIVE System Doctor  [{mode_label}]")
    print("=" * 60)
    print()

    has_fail = False
    results: list[tuple[str, str, str]] = []

    for label, check_fn in CHECKS:
        try:
            status, message = check_fn()
        except Exception as e:
            status, message = FAIL, f"Check crashed: {e}"

        results.append((label, status, message))
        if status == FAIL:
            has_fail = True

    # Print results table
    for label, status, message in results:
        badge = STATUS_LABEL.get(status, status)
        print(f"  {badge}  {label}")
        print(f"         {message}")
        print()

    # Summary
    passes = sum(1 for _, s, _ in results if s == PASS)
    warns = sum(1 for _, s, _ in results if s == WARN)
    fails = sum(1 for _, s, _ in results if s == FAIL)

    print("-" * 60)
    print(f"  {passes} passed, {warns} warnings, {fails} failures")

    if has_fail:
        print("  Exit 1 — issues found.")
        return 1

    print("  Exit 0 — system OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
