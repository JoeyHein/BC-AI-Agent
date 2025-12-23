"""
BC AI Agent - Main FastAPI Application
Phase 1: Email-based quote request parsing + Quote generation
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
from contextlib import asynccontextmanager

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
    logger.info("🚀 BC AI Agent starting up...")
    logger.info("Phase 1: Email quote parsing + Quote generation")

    # TODO: Initialize database connection
    # TODO: Initialize BC API client
    # TODO: Initialize Graph API client
    # TODO: Initialize Anthropic client
    # TODO: Start email monitoring service

    yield

    # Shutdown
    logger.info("👋 BC AI Agent shutting down...")
    # TODO: Close database connections
    # TODO: Stop background tasks


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
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "operational",
        "service": "BC AI Agent",
        "phase": "1 - Email Quote Parsing",
        "version": "0.1.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    # TODO: Check BC API connectivity
    # TODO: Check database connectivity
    # TODO: Check email service connectivity

    return {
        "status": "healthy",
        "services": {
            "api": "operational",
            "database": "pending",
            "bc_connection": "pending",
            "email_monitoring": "pending",
            "ai_service": "pending"
        }
    }


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
