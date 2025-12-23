# BC AI Agent

AI-powered Business Central automation system for quote generation and business operations.

## Project Overview

**Phase 1 Goal**: Email-based quote request parsing + Quote generation with approval (Production-ready by January 31, 2026)

## Architecture

- **Backend**: Python 3.13+ with FastAPI
- **Frontend**: React 18+ with TypeScript
- **Database**: Azure PostgreSQL + Business Central APIs
- **AI**: Anthropic Claude (claude-3-5-sonnet)
- **Cloud**: Azure (App Service, Key Vault, Blob Storage, Application Insights)

## Quick Start

### Prerequisites

- Python 3.11 or higher
- Node.js 18 or higher
- PostgreSQL 14+ (or Azure PostgreSQL)
- Business Central Cloud instance with API access
- Azure AD app registration for BC OAuth 2.0
- Anthropic API key

### Backend Setup

1. Navigate to backend directory:
```bash
cd backend
```

2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your actual credentials
```

5. Run development server:
```bash
python -m app.main
```

Server will start at http://localhost:8000

API documentation available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Frontend Setup

1. Navigate to frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Run development server:
```bash
npm run dev
```

Frontend will start at http://localhost:3000 or http://localhost:5173

### Test BC Connection

Once you have BC credentials configured in `.env`:

```bash
cd backend
python scripts/test_bc_connection.py
```

## Project Structure

```
bc-ai-agent/
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI routes
│   │   ├── services/         # Business logic
│   │   ├── models/           # Pydantic models
│   │   ├── integrations/     # External integrations
│   │   │   ├── bc/          # Business Central client
│   │   │   ├── email/       # MS Graph email client
│   │   │   └── ai/          # Anthropic Claude client
│   │   ├── db/              # Database models & migrations
│   │   ├── config.py        # Configuration management
│   │   └── main.py          # Application entry point
│   ├── tests/               # Unit & integration tests
│   └── requirements.txt     # Python dependencies
├── frontend/
│   ├── src/
│   │   ├── components/      # React components
│   │   ├── pages/           # Page components
│   │   ├── services/        # API client
│   │   └── utils/           # Utilities
│   └── package.json         # Node dependencies
├── docs/                    # Documentation
├── scripts/                 # Deployment & utility scripts
└── README.md
```

## Configuration

### Business Central Setup

1. Create Azure AD app registration for BC API access
2. Configure API permissions: `Dynamics 365 Business Central` > `user_impersonation`
3. Generate client secret
4. Add credentials to `.env`:
   - `BC_TENANT_ID`
   - `BC_CLIENT_ID`
   - `BC_CLIENT_SECRET`
   - `BC_COMPANY_ID`

### Office 365 Email Setup

1. Create Azure AD app registration for Graph API
2. Configure API permissions: `Mail.Read`, `Mail.ReadWrite`
3. Add credentials to `.env`:
   - `GRAPH_TENANT_ID`
   - `GRAPH_CLIENT_ID`
   - `GRAPH_CLIENT_SECRET`
   - `EMAIL_INBOX_1`
   - `EMAIL_INBOX_2`

### Anthropic API Setup

1. Sign up at https://console.anthropic.com/
2. Generate API key
3. Add to `.env`: `ANTHROPIC_API_KEY`

## Development Timeline

### Week 1 (Current) - Foundation & Setup
- [x] Project structure created
- [x] Backend foundation (FastAPI)
- [x] BC OAuth 2.0 client implemented
- [ ] BC API connection tested
- [ ] Frontend foundation (React)
- [ ] Database schema designed

### Week 2 - Email Integration
- [ ] MS Graph API integration
- [ ] Email monitoring service
- [ ] Analyze existing email agent
- [ ] Analyze Excel door tool

### Week 3 - AI Email Parsing
- [ ] Claude AI integration
- [ ] Email parsing service
- [ ] Confidence scoring
- [ ] Human feedback interface

### Week 4 - Door Configuration & Pricing
- [ ] Door configuration engine
- [ ] BC product mapping
- [ ] Pricing calculation
- [ ] Quote line generation

### Week 5 - Quote Creation & Approval
- [ ] BC quote creation API
- [ ] Manager approval workflow
- [ ] Audit trail implementation
- [ ] Dashboard metrics

### Week 6 - Vendor Intelligence & Testing
- [ ] Vendor performance tracking
- [ ] Integration testing
- [ ] UAT preparation

### Week 7 - Production Deployment
- [ ] Security hardening
- [ ] Documentation
- [ ] Training materials
- [ ] Go-live

## API Endpoints (Phase 1)

### Health & Status
- `GET /` - Service status
- `GET /health` - Detailed health check

### Email Management (Coming Week 2)
- `GET /api/emails` - List incoming emails
- `GET /api/emails/{id}` - Get email details
- `POST /api/emails/{id}/parse` - Trigger AI parsing

### Quote Management (Coming Week 5)
- `GET /api/quotes` - List quotes
- `GET /api/quotes/{id}` - Get quote details
- `POST /api/quotes` - Create quote from parsed email
- `PATCH /api/quotes/{id}` - Update quote
- `POST /api/quotes/{id}/approve` - Approve quote

### Metrics (Coming Week 5)
- `GET /api/metrics/dashboard` - Dashboard metrics
- `GET /api/metrics/time-saved` - Time saved calculations
- `GET /api/metrics/error-rate` - Error rate tracking

## Testing

Run backend tests:
```bash
cd backend
pytest
```

Run frontend tests:
```bash
cd frontend
npm test
```

## Security

- All secrets stored in Azure Key Vault
- OAuth 2.0 for all API authentication
- RBAC for user access control
- Full audit trail for all AI actions
- Data encryption at rest and in transit

## Support

For issues or questions:
1. Check the documentation in `/docs`
2. Review the development plan: `BC_AI_Agent_Development_Plan.txt`
3. Contact the development team

## License

Proprietary - Internal use only

---

**Current Status**: Week 1 - Foundation & Setup
**Next Milestone**: BC API connectivity test (awaiting sandbox credentials)
