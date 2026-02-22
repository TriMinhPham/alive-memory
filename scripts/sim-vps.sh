#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Run the ALIVE simulation on the VPS in a background process.
#
# Usage:
#   bash scripts/sim-vps.sh                          # uses default host
#   bash scripts/sim-vps.sh shopkeeper@<ip>          # explicit host
#
# The sim runs detached (nohup) so you can disconnect.
# Monitor: ssh <host> tail -f /var/www/shopkeeper/experiments/simv2_social_pr4/run.log
# Status:  ssh <host> cat /var/www/shopkeeper/experiments/simv2_social_pr4/sim.pid
# Kill:    ssh <host> kill \$(cat /var/www/shopkeeper/experiments/simv2_social_pr4/sim.pid)
# ─────────────────────────────────────────────────────────────
set -euo pipefail

VPS_HOST="${1:-shopkeeper@shopkeeper.tokyo}"
APP_DIR="/var/www/shopkeeper"
OUT_DIR="${APP_DIR}/experiments/simv2_social_pr4"
LOG="${OUT_DIR}/run.log"
PID_FILE="${OUT_DIR}/sim.pid"

echo "[sim-vps] Target: ${VPS_HOST}"
echo "[sim-vps] Output: ${OUT_DIR}"

ssh -A "${VPS_HOST}" bash -s <<EOF
set -euo pipefail

APP_DIR="${APP_DIR}"
OUT_DIR="${OUT_DIR}"
LOG="${LOG}"
PID_FILE="${PID_FILE}"

# ── Pull latest code ──
echo "[sim-vps] Pulling latest main..."
cd "\${APP_DIR}"
git fetch origin main --quiet
git reset --hard origin/main --quiet

# ── Activate venv ──
source "\${APP_DIR}/.venv/bin/activate"

# ── Load env (OPENROUTER_API_KEY, etc.) ──
set -a
source "\${APP_DIR}/.env"
set +a

# Force M2.5 regardless of what .env says
export LLM_DEFAULT_MODEL="minimax/minimax-m2.5"
echo "[sim-vps] Model: \${LLM_DEFAULT_MODEL}"

# Isolate DB so cost logging doesn't contend with production
export SHOPKEEPER_DB_PATH="\${OUT_DIR}/sim.db"
echo "[sim-vps] DB: \${SHOPKEEPER_DB_PATH}"

# ── Check for existing run (never kill — parallel runs ok) ──
if [ -f "\${PID_FILE}" ]; then
    OLD_PID=\$(cat "\${PID_FILE}")
    if kill -0 "\${OLD_PID}" 2>/dev/null; then
        echo "[sim-vps] WARNING: sim already running (PID \${OLD_PID}) — launching in parallel"
    fi
fi

# ── Prepare output dir ──
mkdir -p "\${OUT_DIR}"

# ── Launch sim detached ──
echo "[sim-vps] Starting sim (detached)..."
PYTHONUNBUFFERED=1 nohup python3 -m sim \\
    --variant full \\
    --scenario social \\
    --cycles 1000 \\
    --llm cached \\
    --daily-budget 1.0 \\
    --seed 42 \\
    --output-dir "\${OUT_DIR}" \\
    --verbose \\
    > "\${LOG}" 2>&1 &

SIM_PID=\$!
echo "\${SIM_PID}" > "\${PID_FILE}"
echo "[sim-vps] Sim running — PID \${SIM_PID}"
echo "[sim-vps] Log: \${LOG}"

# ── Tail the first 10 lines to confirm startup ──
sleep 3
echo ""
echo "── First output ──────────────────────"
head -20 "\${LOG}" 2>/dev/null || echo "(no output yet)"
echo "───────────────────────────────────────"
EOF

echo ""
echo "[sim-vps] Done. To monitor:"
echo "  ssh ${VPS_HOST} tail -f ${LOG}"
echo "  ssh ${VPS_HOST} cat ${PID_FILE}    # PID"
