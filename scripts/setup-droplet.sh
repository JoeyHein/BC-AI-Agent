#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# BC AI Agent — DigitalOcean Droplet Setup
#
# Run once on a fresh Ubuntu 24 LTS droplet as root (or with sudo).
# Before running: point your domain's A record to this server's IP.
#
# Usage:
#   chmod +x setup-droplet.sh
#   sudo ./setup-droplet.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Config — edit these ───────────────────────────────────────────────────────
DOMAIN=""           # e.g. portal.yourdomain.com
EMAIL=""            # for Let's Encrypt renewal notices
REPO_URL=""         # e.g. https://github.com/yourorg/bc-ai-agent.git
APP_DIR="/opt/bc-ai-agent"
# ─────────────────────────────────────────────────────────────────────────────

if [[ -z "$DOMAIN" || -z "$EMAIL" || -z "$REPO_URL" ]]; then
    echo "ERROR: Set DOMAIN, EMAIL, and REPO_URL at the top of this script before running."
    exit 1
fi

echo "============================================================"
echo " BC AI Agent — Droplet Setup"
echo " Domain: $DOMAIN"
echo "============================================================"

# ── 1. System update ─────────────────────────────────────────────────────────
apt-get update -y && apt-get upgrade -y
apt-get install -y git curl ufw certbot

# ── 2. Firewall ──────────────────────────────────────────────────────────────
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
echo "✓ Firewall configured"

# ── 3. Install Docker CE ──────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
    echo "✓ Docker installed"
else
    echo "✓ Docker already installed"
fi

# ── 4. Install Docker Compose plugin ─────────────────────────────────────────
if ! docker compose version &>/dev/null; then
    COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest \
        | grep '"tag_name"' | cut -d'"' -f4)
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
    echo "✓ Docker Compose installed ($COMPOSE_VERSION)"
else
    echo "✓ Docker Compose already installed"
fi

# ── 5. Clone repository ───────────────────────────────────────────────────────
if [[ -d "$APP_DIR" ]]; then
    echo "Directory $APP_DIR already exists — pulling latest..."
    git -C "$APP_DIR" pull
else
    git clone "$REPO_URL" "$APP_DIR"
    echo "✓ Repository cloned to $APP_DIR"
fi

# ── 6. Create .env from example ──────────────────────────────────────────────
if [[ ! -f "$APP_DIR/.env" ]]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo ""
    echo "============================================================"
    echo " ACTION REQUIRED: Edit $APP_DIR/.env"
    echo " Fill in ALL values, then re-run this script."
    echo "============================================================"
    exit 0
fi

# ── 7. Patch nginx.conf with the real domain ──────────────────────────────────
sed -i "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" "$APP_DIR/nginx/nginx.conf"
echo "✓ nginx.conf patched with domain: $DOMAIN"

# ── 8. Obtain SSL certificate (standalone — no nginx running yet) ─────────────
echo "Obtaining Let's Encrypt certificate for $DOMAIN..."
certbot certonly \
    --standalone \
    --non-interactive \
    --agree-tos \
    --email "$EMAIL" \
    -d "$DOMAIN"
echo "✓ SSL certificate obtained"

# ── 9. Set up automatic cert renewal ─────────────────────────────────────────
# After renewal, reload nginx inside the container
RENEW_HOOK="docker exec \$(docker ps -qf name=nginx) nginx -s reload"
CRON_LINE="0 3 * * * certbot renew --quiet --post-hook '$RENEW_HOOK'"
(crontab -l 2>/dev/null | grep -v certbot; echo "$CRON_LINE") | crontab -
echo "✓ Auto-renewal cron job set (daily at 03:00)"

# ── 10. Build and start all containers ───────────────────────────────────────
cd "$APP_DIR"
docker compose pull --ignore-buildable
docker compose build --no-cache
docker compose up -d
echo "✓ Containers started"

# ── 11. Done ──────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo " Setup complete!"
echo " App is running at: https://$DOMAIN"
echo " Admin dashboard:   https://$DOMAIN/"
echo " Customer portal:   https://$DOMAIN/customer.html"
echo " View logs:         docker compose -f $APP_DIR/docker-compose.yml logs -f"
echo "============================================================"
