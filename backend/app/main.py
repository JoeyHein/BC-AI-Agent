"""
BC AI Agent - Main FastAPI Application
Phase 1: Email-based quote request parsing + Quote generation
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
from contextlib import asynccontextmanager

# Import API routers
from app.api import feedback, auth, email_connections, email_feedback, quotes, orders, analytics, door_configurator
from app.api import customer_auth, customer_portal, admin_customers, inventory, production

# Import services
from app.services.scheduler_service import get_scheduler
from app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("=" * 80)
    logger.info("BC AI Agent starting up...")
    logger.info("Phase 1: Email quote parsing + Quote generation")
    logger.info("=" * 80)

    # TODO: Initialize database connection
    # TODO: Initialize BC API client
    # TODO: Initialize Graph API client
    # TODO: Initialize Anthropic client

    # Start scheduled email monitoring
    if settings.ENABLE_EMAIL_MONITORING:
        try:
            scheduler = get_scheduler()
            scheduler.start(email_check_interval_minutes=settings.EMAIL_CHECK_INTERVAL_MINUTES)
            logger.info(f"✓ Scheduled email monitoring started (every {settings.EMAIL_CHECK_INTERVAL_MINUTES} minutes)")
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}", exc_info=True)
    else:
        logger.info("Email monitoring disabled (ENABLE_EMAIL_MONITORING=False)")

    yield

    # Shutdown
    logger.info("=" * 80)
    logger.info("BC AI Agent shutting down...")
    logger.info("=" * 80)

    # Stop background scheduler
    try:
        scheduler = get_scheduler()
        scheduler.stop()
        logger.info("Scheduler stopped")
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}", exc_info=True)

    # TODO: Close database connections


# Create FastAPI application
app = FastAPI(
    title="BC AI Agent",
    description="AI-powered Business Central automation for quote generation and business operations",
    version="0.1.0",
    lifespan=lifespan
)

# CORS middleware (configure for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002", "http://localhost:3003", "http://localhost:5173"],  # React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
# Mounting authentication and email connection routers
logger.info(f"Including auth router: {auth.router.prefix}")
app.include_router(auth.router)
logger.info(f"Including email_connections router: {email_connections.router.prefix}")
app.include_router(email_connections.router)
logger.info(f"Including feedback router: {feedback.router.prefix}")
app.include_router(feedback.router)
logger.info(f"Including email_feedback router: {email_feedback.router.prefix}")
app.include_router(email_feedback.router)
logger.info(f"Including quotes router: {quotes.router.prefix}")
app.include_router(quotes.router)
logger.info(f"Including orders router: {orders.router.prefix}")
app.include_router(orders.router)
logger.info(f"Including analytics router: {analytics.router.prefix}")
app.include_router(analytics.router)
logger.info(f"Including door_configurator router: {door_configurator.router.prefix}")
app.include_router(door_configurator.router)

# Customer Portal routers
logger.info(f"Including customer_auth router: {customer_auth.router.prefix}")
app.include_router(customer_auth.router)
logger.info(f"Including customer_portal router: {customer_portal.router.prefix}")
app.include_router(customer_portal.router)

# Admin Customer Management router (customer portal accounts)
logger.info(f"Including admin_customers router: {admin_customers.router.prefix}")
app.include_router(admin_customers.router)

# Inventory Management router
logger.info(f"Including inventory router: {inventory.router.prefix}")
app.include_router(inventory.router)

# Production Management router
logger.info(f"Including production router: {production.router.prefix}")
app.include_router(production.router)

logger.info(f"Total routes after including routers: {len(app.routes)}")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "operational",
        "service": "BC AI Agent",
        "phase": "1 - Email Quote Parsing",
        "version": "0.1.0"
    }


@app.post("/test-register")
async def test_register():
    """Test endpoint to verify POST works"""
    return {"message": "Test endpoint works!"}


@app.get("/debug/routes")
async def debug_routes():
    """Debug endpoint to list all registered routes"""
    routes_list = []
    for route in app.routes:
        if hasattr(route, 'path'):
            routes_list.append({
                "path": route.path,
                "methods": list(getattr(route, 'methods', []))
            })
    return {"total_routes": len(routes_list), "routes": routes_list}


@app.get("/health")
async def health_check():
    """Detailed health check"""
    # Check scheduler status
    try:
        scheduler = get_scheduler()
        scheduler_status = scheduler.get_status()
        email_monitoring_status = "running" if scheduler_status['running'] else "stopped"
    except:
        email_monitoring_status = "error"

    # TODO: Check BC API connectivity
    # TODO: Check database connectivity
    # TODO: Check email service connectivity

    return {
        "status": "healthy",
        "services": {
            "api": "operational",
            "database": "operational",
            "bc_connection": "pending",
            "email_monitoring": email_monitoring_status,
            "ai_service": "operational"
        }
    }


@app.get("/api/scheduler/status")
async def scheduler_status():
    """Get scheduler status and job details"""
    try:
        scheduler = get_scheduler()
        status = scheduler.get_status()

        return {
            "success": True,
            "scheduler": status,
            "message": "Scheduler is running" if status['running'] else "Scheduler is stopped"
        }
    except Exception as e:
        logger.error(f"Error getting scheduler status: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc)
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

