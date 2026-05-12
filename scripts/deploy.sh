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

# Helper — wipes any container whose name starts with "<hex>_bc-ai-agent-".
# Docker creates these as a side-effect of failed force-recreates: the
# original is renamed with a hex prefix, the new one is created with the
# original name, but if Docker can't release the rename cleanly the orphan
# persists and collides on the next deploy. Live containers have no hex
# prefix so they're never matched.
sweep_orphans() {
    local orphans
    orphans=$(docker ps -a --filter "name=_bc-ai-agent-" --format '{{.Names}}' || true)
    if [ -n "$orphans" ]; then
        echo "  Removing orphans:"
        echo "$orphans" | sed 's/^/    /'
        echo "$orphans" | xargs -r docker rm -f >/dev/null
    else
        echo "  No orphans."
    fi
}

# ── 3. Pre-sweep any orphans left over from a prior failed deploy ─────────────
echo "[3/5] Pre-sweep:"
sweep_orphans

# ── 4. Restart services. If compose up fails because of a mid-recreate name
#       conflict (Docker engine quirk we hit roughly every other deploy on
#       this host), sweep the freshly-created orphan and try once more.
echo "[4/5] Restarting services..."
if ! docker compose up -d --remove-orphans 2>&1 | tee /tmp/deploy-up.log; then
    if grep -q "is already in use by container" /tmp/deploy-up.log; then
        echo "  Container name conflict — sweeping and retrying once."
        sweep_orphans
        docker compose up -d --remove-orphans
    else
        echo "  compose up failed for a reason other than name conflict — aborting."
        exit 1
    fi
fi

# ── 5. Run DB migrations ──────────────────────────────────────────────────────
echo "[5/5] Running database migrations..."
docker compose exec backend alembic upgrade head

echo ""
echo "✓ Deploy complete!"
echo "  View logs: docker compose logs -f"
