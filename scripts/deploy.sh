#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# BC AI Agent — Deploy Update
#
# Run this every time you push new code and want to deploy it.
# Must be run on the server (or via SSH) from the app directory.
#
# Usage:
#   cd /opt/bc-ai-agent
#   ./scripts/deploy.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

echo "============================================================"
echo " Deploying BC AI Agent"
echo " Directory: $APP_DIR"
echo "============================================================"

# ── 1. Pull latest code ───────────────────────────────────────────────────────
echo "[1/4] Pulling latest code..."
git pull origin main

# ── 2. Rebuild changed images ─────────────────────────────────────────────────
echo "[2/5] Building Docker images..."
docker compose build

# ── 3. Sweep orphaned hash-prefixed containers from a prior failed recreate ──
# When docker compose fails mid-recreate (e.g. a worker still holding the old
# container's PID), Docker renames the original with a hex-hash prefix
# (e.g. "8b56dce667e8_bc-ai-agent-db-1") and tries to create a fresh one with
# the original name. If anything errors out before the rename is undone, the
# next deploy collides on the container name. Sweep these before bringing the
# stack back up so we never accumulate. Live containers (no hash prefix) are
# untouched because the filter requires an underscore before "bc-ai-agent-".
echo "[3/5] Sweeping hash-prefixed orphan containers..."
orphans=$(docker ps -a --filter "name=_bc-ai-agent-" --format '{{.Names}}' || true)
if [ -n "$orphans" ]; then
    echo "  Found orphans:"
    echo "$orphans" | sed 's/^/    /'
    echo "$orphans" | xargs -r docker rm -f >/dev/null
    echo "  Removed."
else
    echo "  None found."
fi

# ── 4. Restart services with zero-downtime rolling update ─────────────────────
echo "[4/5] Restarting services..."
docker compose up -d --remove-orphans

# ── 5. Run DB migrations ──────────────────────────────────────────────────────
echo "[5/5] Running database migrations..."
docker compose exec backend alembic upgrade head

echo ""
echo "✓ Deploy complete!"
echo "  View logs: docker compose logs -f"
