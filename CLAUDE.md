# OPENDC Portal — BC AI Agent

## Permissions
- Full execution permitted — run builds, tests, deploys, migrations, and file edits without asking
- Commit and push to main when the user says "push" or "commit"
- SSH to production server (159.203.3.173) for deploys and debugging
- Kill stale processes before starting servers

## Quick Start
```bash
# Kill stale processes
powershell.exe -Command "Get-Process python3.13 -ErrorAction SilentlyContinue | Stop-Process -Force"
# Backend (port 8000)
cd /c/Users/jhein/bc-ai-agent/backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
# Frontend (port 3001, proxy /api → localhost:8000)
export PATH="/c/Program Files/nodejs:$PATH" && cd /c/Users/jhein/bc-ai-agent/frontend && npm run dev &
```

## Stack
- **Backend**: FastAPI + SQLAlchemy + PostgreSQL (prod) / SQLite (local)
- **Frontend**: React + Vite + Tailwind + Recharts
- **BC Integration**: OData v4 REST API via `backend/app/integrations/bc/client.py`
- **AI**: Anthropic Claude (tool_use for structured outputs)
- **Auth**: JWT tokens, roles: admin / reviewer / viewer

## BC Environment
- **We use the Production environment, NOT Sandbox** — all BC API calls target production
- BC_ENVIRONMENT should always be set to production

## Production
- **URL**: https://portal.opendc.ca
- **Server**: DigitalOcean droplet, 159.203.3.173, Ubuntu 24.04
- **Stack**: Docker Compose (nginx + backend + postgres:16)
- **Deploy**: `git push origin main` triggers GitHub Actions → SSH → `scripts/deploy.sh`
- **Manual deploy**: `ssh root@159.203.3.173 "cd /opt/bc-ai-agent && bash scripts/deploy.sh"`
- **Container conflict fix**: use `docker compose up -d --force-recreate`
- **Logs**: `docker compose logs -f backend`

## DB Migrations
```bash
cd backend && python -m alembic upgrade head          # local
ssh root@159.203.3.173 "cd /opt/bc-ai-agent && docker compose exec backend alembic upgrade head"  # prod
```

## Tests
```bash
cd backend && python -m pytest tests/ -v --tb=short
```

## Key Architecture

### Pricing System
- Tiers: platinum / unlisted / gold / silver / bronze / retail
- Formula: `selling_price = (unitCost × (1 + adj%/100)) / (1 - margin%/100)`
- Door type margins: residential, commercial, aluminium, glazing
- GK17 glazing + PN10/PN12 V130G frames → always "glazing" margins
- Aluminum door hardware → customer's commercial tier

### Quote Generation Flow
1. `frontend/src/components/DoorConfigurator.jsx` — UI configurator
2. `POST /api/door-config/generate-quote` → `backend/app/api/door_configurator.py`
3. `get_parts_for_door_config()` → `backend/app/services/part_number_service.py`
4. Creates BC sales quote with comment + item lines
5. Customer portal: `backend/app/api/customer_portal.py` (two functions: `_generate_bc_quote_with_items` and `_generate_local_estimate`)

### BC API Client
- `backend/app/integrations/bc/client.py` — OAuth2 via MSAL, all OData operations
- Key methods: `get_sales_quotes()`, `create_sales_quote()`, `add_quote_line()`, `convert_quote_to_order()`
- Pagination: `_get_all_pages()` follows `@odata.nextLink`

### Widget (Embeddable Door Designer)
- Source: `widget/src/` — React IIFE bundle with CSS injected
- Build: `cd widget && npm run build` → `dist/opendc-door-designer.iife.js`
- Served at: `https://portal.opendc.ca/widget/opendc-door-designer.iife.js`
- SVG rendering: `widget/src/DoorPreview.jsx`

## Key Files
- `backend/app/services/part_number_service.py` — part numbers, weight calc, spring calc
- `backend/app/services/pricing_service.py` — tier margins, cost adjustments
- `backend/app/api/customer_portal.py` — quote generation (BC + local estimate)
- `backend/app/api/door_configurator.py` — configurator API
- `backend/app/services/bc_metrics_service.py` — business dashboard metrics
- `backend/app/services/quoting_analytics_service.py` — quoting pipeline analytics
- `frontend/src/App.jsx` — routing, nav items
- `frontend/src/components/DoorConfigurator.jsx` — main configurator UI

## Env Vars (keys only)
BC_TENANT_ID, BC_CLIENT_ID, BC_CLIENT_SECRET, BC_ENVIRONMENT, BC_COMPANY_ID, ANTHROPIC_API_KEY, SECRET_KEY, DATABASE_URL, ALLOWED_ORIGINS, GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET

## Admin Login
joey@opendc.ca / test123

## External API (SQB + QOC, 2026-05)

BC AI Agent exposes a small surface for Service.AI to call into:

- `POST /api/external/price-items` — resolve BC SalesPriceLists prices for a basket (customer → group → all-customers fall-through). 60s in-memory cache per `(account_code, sku, qty)`.
- `POST /api/external/quotes` — idempotent commit. Same `external_quote_id` → same `SQ-XXXXXX`. Backed by the `external_quote_commits` table (UNIQUE on `external_quote_id`) plus a per-key in-process `threading.Lock`.
- `POST /api/external/quotes/{external_quote_id}/convert-to-order` — **QOC-04**. Idempotent quote→order conversion. Looks up the existing `external_quote_commits` row, calls `bc_client.convert_quote_to_order(bc_quote_id)`, persists `bc_order_id` + `bc_order_ref` + `converted_at` on the SAME row. Repeat calls return cached `SO-XXXXXX`. 422 UNPROCESSABLE if the source quote is not in `status='committed'`.
- `POST /api/external-keys` — admin-only key mint. Plaintext returned ONCE; only the bcrypt hash + 12-char prefix live in the DB.
- `POST /api/external-keys/:id/revoke|rotate` — idempotent admin actions.

Auth: `X-Service-AI-Key` header. Each key is bound to a single `supplier_account_code` (e.g., the Elevated Doors BC customer number). Cross-key probes return 404 NOT_FOUND (never 403) — never confirm the existence of another tenant's account code.

Observability: `RequestIdMiddleware` reads / echoes `X-Request-ID` so one id traces web → Service.AI → BC AI Agent → BC OData.

Detailed reference: see `servicetitan-clone/docs/api/supplier-quote-bridge.md`.

## Forbidden patterns (external API)

- No business logic in the external routes. They wrap the existing services (`pricing_service`, `bc_quote_service`) and add auth + idempotency. Anything more = refactor the service.
- No API key logged or echoed. The verification path returns `None` on a miss without distinguishing unknown/revoked/forged — callers map every failure to 401 with the same message.
- No client-supplied `bc_quote_id` or `supplier_quote_ref` on the commit body. Those are server-assigned by BC.
