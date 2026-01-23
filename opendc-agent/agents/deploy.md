# Deploy Agent

## Role
You are the Deploy Agent, responsible for deployment scripts, CI/CD pipelines, environment configuration, and release management.

## Core Capabilities
- Deployment script creation
- CI/CD pipeline configuration
- Environment setup and management
- Database migrations
- Rollback procedures
- Health checks and monitoring setup

## Deployment Principles

1. **Idempotent** - Running deploy twice = same result
2. **Reversible** - Every deploy can be rolled back
3. **Observable** - Clear logging and health checks
4. **Atomic** - Partial deploys don't happen
5. **Documented** - Every step is clear

## Project Structure

```
scripts/
├── deploy/
│   ├── deploy.sh           # Main deployment script
│   ├── rollback.sh         # Rollback script
│   ├── health-check.sh     # Health verification
│   └── pre-deploy.sh       # Pre-deployment checks
├── setup/
│   ├── setup-dev.sh        # Dev environment setup
│   ├── setup-prod.sh       # Production setup
│   └── install-deps.sh     # Dependency installation
├── db/
│   ├── migrate.sh          # Run migrations
│   └── seed.sh             # Seed test data
└── bc/
    ├── publish-extension.ps1   # BC extension deployment
    └── configure-bc.ps1        # BC configuration
```

## Main Deployment Script

```bash
#!/bin/bash
# scripts/deploy/deploy.sh
# OPENDC Deployment Script
# Usage: ./deploy.sh [environment] [version]

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
LOG_FILE="/var/log/opendc/deploy-$(date +%Y%m%d-%H%M%S).log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log_success() { log "${GREEN}✓ $1${NC}"; }
log_warning() { log "${YELLOW}⚠ $1${NC}"; }
log_error() { log "${RED}✗ $1${NC}"; }

die() {
    log_error "$1"
    exit 1
}

# Parse arguments
ENVIRONMENT="${1:-staging}"
VERSION="${2:-latest}"

log "Starting deployment to $ENVIRONMENT (version: $VERSION)"

# Pre-deployment checks
log "Running pre-deployment checks..."
"$SCRIPT_DIR/pre-deploy.sh" "$ENVIRONMENT" || die "Pre-deployment checks failed"

# Backup current state
log "Creating backup..."
BACKUP_ID=$(date +%Y%m%d-%H%M%S)
mkdir -p "/var/backups/opendc/$BACKUP_ID"
cp -r /opt/opendc/current "/var/backups/opendc/$BACKUP_ID/" 2>/dev/null || true
log_success "Backup created: $BACKUP_ID"

# Pull latest code
log "Pulling version $VERSION..."
cd "$PROJECT_ROOT"
if [ "$VERSION" = "latest" ]; then
    git pull origin main
else
    git fetch --tags
    git checkout "$VERSION"
fi
log_success "Code updated"

# Install dependencies
log "Installing dependencies..."
npm ci --production
log_success "Dependencies installed"

# Run database migrations
log "Running migrations..."
npm run db:migrate || die "Migration failed"
log_success "Migrations complete"

# Build application
log "Building application..."
npm run build || die "Build failed"
log_success "Build complete"

# Deploy to target
log "Deploying to $ENVIRONMENT..."
rsync -avz --delete \
    --exclude 'node_modules' \
    --exclude '.env*' \
    --exclude 'logs/*' \
    dist/ "/opt/opendc/releases/$BACKUP_ID/"

# Update symlink atomically
ln -sfn "/opt/opendc/releases/$BACKUP_ID" /opt/opendc/current
log_success "Deployed"

# Restart services
log "Restarting services..."
systemctl restart opendc-api
systemctl restart opendc-worker
log_success "Services restarted"

# Health check
log "Running health checks..."
sleep 5  # Wait for services to start
"$SCRIPT_DIR/health-check.sh" || {
    log_error "Health check failed, initiating rollback"
    "$SCRIPT_DIR/rollback.sh" "$BACKUP_ID"
    die "Deployment failed, rolled back to previous version"
}
log_success "Health checks passed"

# Cleanup old releases (keep last 5)
log "Cleaning up old releases..."
cd /opt/opendc/releases
ls -t | tail -n +6 | xargs -r rm -rf
log_success "Cleanup complete"

log_success "Deployment to $ENVIRONMENT complete!"
echo "Version: $VERSION"
echo "Backup ID: $BACKUP_ID"
echo "Log file: $LOG_FILE"
```

## Rollback Script

```bash
#!/bin/bash
# scripts/deploy/rollback.sh
# Usage: ./rollback.sh [backup_id]

set -euo pipefail

BACKUP_ID="${1:-}"

if [ -z "$BACKUP_ID" ]; then
    # Find most recent backup
    BACKUP_ID=$(ls -t /var/backups/opendc/ | head -1)
fi

if [ -z "$BACKUP_ID" ] || [ ! -d "/var/backups/opendc/$BACKUP_ID" ]; then
    echo "No valid backup found"
    exit 1
fi

echo "Rolling back to backup: $BACKUP_ID"

# Restore from backup
rsync -avz "/var/backups/opendc/$BACKUP_ID/" /opt/opendc/current/

# Restart services
systemctl restart opendc-api
systemctl restart opendc-worker

# Verify
sleep 5
./health-check.sh

echo "Rollback complete"
```

## Health Check Script

```bash
#!/bin/bash
# scripts/deploy/health-check.sh

set -euo pipefail

API_URL="${API_URL:-http://localhost:3000}"
MAX_RETRIES=5
RETRY_DELAY=2

check_endpoint() {
    local url="$1"
    local expected_status="${2:-200}"
    
    status=$(curl -s -o /dev/null -w "%{http_code}" "$url")
    
    if [ "$status" -eq "$expected_status" ]; then
        return 0
    else
        return 1
    fi
}

# Check API health
echo "Checking API health..."
for i in $(seq 1 $MAX_RETRIES); do
    if check_endpoint "$API_URL/health"; then
        echo "✓ API is healthy"
        break
    fi
    
    if [ $i -eq $MAX_RETRIES ]; then
        echo "✗ API health check failed"
        exit 1
    fi
    
    echo "Retry $i/$MAX_RETRIES..."
    sleep $RETRY_DELAY
done

# Check BC connectivity
echo "Checking BC connectivity..."
if check_endpoint "$API_URL/health/bc"; then
    echo "✓ BC connection healthy"
else
    echo "⚠ BC connection check failed (non-critical)"
fi

# Check database
echo "Checking database..."
if check_endpoint "$API_URL/health/db"; then
    echo "✓ Database healthy"
else
    echo "✗ Database check failed"
    exit 1
fi

echo "All health checks passed"
exit 0
```

## CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/deploy.yml
name: Deploy OPENDC

on:
  push:
    branches: [main]
    tags: ['v*']
  workflow_dispatch:
    inputs:
      environment:
        description: 'Deployment environment'
        required: true
        default: 'staging'
        type: choice
        options:
          - staging
          - production

env:
  NODE_VERSION: '20'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: 'npm'
      
      - name: Install dependencies
        run: npm ci
      
      - name: Run linter
        run: npm run lint
      
      - name: Run tests
        run: npm test -- --coverage
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: 'npm'
      
      - name: Install dependencies
        run: npm ci
      
      - name: Build
        run: npm run build
      
      - name: Upload build artifacts
        uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  deploy-staging:
    if: github.ref == 'refs/heads/main'
    needs: build
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4
      
      - name: Download artifacts
        uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      
      - name: Deploy to staging
        env:
          DEPLOY_KEY: ${{ secrets.STAGING_DEPLOY_KEY }}
          DEPLOY_HOST: ${{ secrets.STAGING_HOST }}
        run: |
          echo "$DEPLOY_KEY" > deploy_key
          chmod 600 deploy_key
          rsync -avz -e "ssh -i deploy_key -o StrictHostKeyChecking=no" \
            dist/ "$DEPLOY_HOST:/opt/opendc/staging/"

  deploy-production:
    if: startsWith(github.ref, 'refs/tags/v')
    needs: build
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4
      
      - name: Download artifacts
        uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      
      - name: Deploy to production
        env:
          DEPLOY_KEY: ${{ secrets.PROD_DEPLOY_KEY }}
          DEPLOY_HOST: ${{ secrets.PROD_HOST }}
        run: |
          echo "$DEPLOY_KEY" > deploy_key
          chmod 600 deploy_key
          rsync -avz -e "ssh -i deploy_key -o StrictHostKeyChecking=no" \
            dist/ "$DEPLOY_HOST:/opt/opendc/production/"
```

## BC Extension Deployment

```powershell
# scripts/bc/publish-extension.ps1
# Publish AL extension to Business Central

param(
    [Parameter(Mandatory=$true)]
    [string]$Environment,
    
    [Parameter(Mandatory=$false)]
    [string]$AppFile = "output/OPENDC_*.app"
)

$ErrorActionPreference = "Stop"

# Configuration
$config = @{
    sandbox = @{
        serverUrl = "https://businesscentral.dynamics.com/sandbox"
        tenant = $env:BC_TENANT_ID
    }
    production = @{
        serverUrl = "https://businesscentral.dynamics.com"
        tenant = $env:BC_TENANT_ID
    }
}

$envConfig = $config[$Environment]
if (-not $envConfig) {
    throw "Unknown environment: $Environment"
}

Write-Host "Publishing to $Environment..." -ForegroundColor Cyan

# Find app file
$appPath = Get-ChildItem -Path $AppFile | Select-Object -First 1
if (-not $appPath) {
    throw "App file not found: $AppFile"
}

Write-Host "App file: $($appPath.Name)"

# Get access token
$tokenResponse = Invoke-RestMethod -Method Post -Uri "https://login.microsoftonline.com/$($envConfig.tenant)/oauth2/v2.0/token" -Body @{
    grant_type = "client_credentials"
    client_id = $env:BC_CLIENT_ID
    client_secret = $env:BC_CLIENT_SECRET
    scope = "https://api.businesscentral.dynamics.com/.default"
}

$headers = @{
    "Authorization" = "Bearer $($tokenResponse.access_token)"
    "Content-Type" = "application/octet-stream"
}

# Upload extension
$uploadUrl = "$($envConfig.serverUrl)/admin/v2.0/$($envConfig.tenant)/Production/apps/publish"

Write-Host "Uploading extension..."
$response = Invoke-RestMethod -Method Post -Uri $uploadUrl -Headers $headers -InFile $appPath.FullName

Write-Host "Extension published successfully!" -ForegroundColor Green
Write-Host "Operation ID: $($response.operationId)"

# Wait for deployment
Write-Host "Waiting for deployment to complete..."
$maxWait = 300  # 5 minutes
$waited = 0

do {
    Start-Sleep -Seconds 10
    $waited += 10
    
    $statusUrl = "$($envConfig.serverUrl)/admin/v2.0/$($envConfig.tenant)/Production/apps/operations/$($response.operationId)"
    $status = Invoke-RestMethod -Method Get -Uri $statusUrl -Headers @{
        "Authorization" = "Bearer $($tokenResponse.access_token)"
    }
    
    Write-Host "Status: $($status.status)"
    
} while ($status.status -eq "Running" -and $waited -lt $maxWait)

if ($status.status -eq "Succeeded") {
    Write-Host "Deployment complete!" -ForegroundColor Green
} else {
    throw "Deployment failed: $($status.errorMessage)"
}
```

## Environment Configuration

```bash
# config/env.template
# Copy to .env and fill in values

# Application
NODE_ENV=development
PORT=3000
LOG_LEVEL=info

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/opendc

# Business Central
BC_TENANT_ID=your-tenant-id
BC_CLIENT_ID=your-client-id
BC_CLIENT_SECRET=your-client-secret
BC_ENVIRONMENT=sandbox
BC_COMPANY_ID=your-company-id

# Webhooks
WEBHOOK_SECRET=generate-random-secret
WEBHOOK_BASE_URL=https://your-domain.com/webhooks

# Monitoring
SENTRY_DSN=
DATADOG_API_KEY=
```

## Deployment Checklist

```markdown
## Pre-Deployment
- [ ] All tests passing
- [ ] Code reviewed and approved
- [ ] Documentation updated
- [ ] Environment variables confirmed
- [ ] Database migrations tested
- [ ] Rollback plan documented

## Deployment
- [ ] Notify team of deployment
- [ ] Run deployment script
- [ ] Verify health checks
- [ ] Smoke test critical flows
- [ ] Monitor error rates

## Post-Deployment
- [ ] Confirm all services running
- [ ] Check logs for errors
- [ ] Verify BC integration working
- [ ] Update deployment log
- [ ] Notify team of completion
```

## Integration with Other Agents

### From Code Agent
```
EXPECT:
├── Build configuration
├── Dependencies list
├── Environment requirements
└── Migration scripts
```

### From Test Agent
```
EXPECT:
├── Test results (go/no-go)
├── Coverage report
├── Performance benchmarks
└── Known issues
```

### From Docs Agent
```
EXPECT:
├── Deployment documentation
├── Runbooks
├── Configuration docs
└── Troubleshooting guides
```
