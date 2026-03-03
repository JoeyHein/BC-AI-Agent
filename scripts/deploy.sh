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
echo "[2/4] Building Docker images..."
docker compose build

# ── 3. Restart services with zero-downtime rolling update ─────────────────────
echo "[3/4] Restarting services..."
docker compose up -d --remove-orphans

# ── 4. Run DB migrations ──────────────────────────────────────────────────────
echo "[4/4] Running database migrations..."
docker compose exec backend alembic upgrade head

echo ""
echo "✓ Deploy complete!"
echo "  View logs: docker compose logs -f"
