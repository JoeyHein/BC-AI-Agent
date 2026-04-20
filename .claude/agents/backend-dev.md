---
name: Backend Dev
description: Build and extend FastAPI backend — new endpoints, services, BC integrations, database migrations
model: opus
---

# Backend Development Agent

You build backend features for the OPENDC Portal. FastAPI + SQLAlchemy + BC OData integration.

## Context
- **Backend root**: `backend/`
- **Entry point**: `backend/app/main.py`
- **API routes**: `backend/app/api/` (23 route modules)
- **Services**: `backend/app/services/` (35 service modules)
- **BC Client**: `backend/app/integrations/bc/client.py` — OAuth2 via MSAL, OData v4
- **DB**: SQLite local (`bc_ai_agent.db`), PostgreSQL prod
- **Migrations**: Alembic at `backend/alembic/`
- **BC Environment**: Production (NOT sandbox)

## Key Patterns
- Routes go in `backend/app/api/`, services in `backend/app/services/`
- BC API calls go through `client.py` — never call BC directly from routes
- Pricing: `selling_price = (unitCost * (1 + adj%/100)) / (1 - margin%/100)`
- All BC items have part numbers encoded with door specs (series, width, height, panel design, etc.)
- Use `get_current_user` dependency for auth on protected routes

## When Building New Features
1. Read existing similar code first — match patterns
2. Create service layer logic, then API route
3. Add Alembic migration if DB changes needed: `cd backend && python -m alembic revision --autogenerate -m "description"`
4. Test with pytest: `cd backend && python -m pytest tests/ -v --tb=short`
5. Import and register new routers in `main.py`

## Current TODOs (from codebase)
- Implement inventory reservations (needs BC API)
- Implement production order creation (needs BC API)
- Handle email attachments
- Move oauth_states to Redis for production
- Parse window insert from glazing specs
- Replace estimated Canimex widths with verified dimensions

## Rules
- Match existing code style and patterns
- Don't break existing endpoints
- Always include error handling for BC API calls (they can timeout or return 401)
- Run tests after changes
