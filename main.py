from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from loguru import logger
import asyncio
import sys
import os
from alembic.config import Config
from alembic import command
from typing import AsyncIterator

from app.core.config import settings
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.session import router as session_router
from app.database import engine, Base, SessionLocal


def setup_logging():
    """Configure application logging with loguru"""
    logger.configure(
        handlers=[
            {
                "sink": "logs/app.log", 
                "rotation": "10 MB",
                "level": "INFO",
                "format": "{time} - {name} - {level} - {message}"
            },
            {
                "sink": sys.stderr,
                "level": "INFO", 
                "format": "{time} - {name} - {level} - {message}"
            }
        ]
    )

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Manage the application's lifespan, including startup and shutdown operations.
    On startup, this function will:
    - Execute a subprocess to run database migrations.
    - Log whether migrations succeeded or failed.
    """
    # Setup logging
    setup_logging()
    
    try:
        # Run migrations in separate process
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "migrations.py",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        
        if stdout:
            for line in stdout.decode().splitlines():
                if line.strip():
                    logger.info(f"Migration: {line}")
                    
        if stderr:
            for line in stderr.decode().splitlines():
                if line.strip():
                    if "ERROR" in line or "error" in line.lower():
                        logger.error(f"Migration error: {line}")
                    else:
                        logger.info(f"Migration: {line}")
        
        
        if process.returncode == 0:
            logger.info("Database migrations completed successfully")
        else:
            logger.error("Migration process failed")
    except Exception as e:
        logger.error(f"Failed to run database migrations: {e}")
    
    logger.info(f"Starting {settings.APP_NAME}")
    yield
    logger.info(f"Shutting down {settings.APP_NAME}")

# Initialize FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="Backend API for Bluescan Project",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    # allow_origins=settings.CORS_ORIGINS.split(","),
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(
    auth_router,
    prefix=f"{settings.API_V1_STR}/auth",
    tags=["authentication"]
)

app.include_router(
    session_router,
    prefix=f"{settings.API_V1_STR}/session",
    tags=["session"]
)

# Health check endpoint
@app.get("/", tags=["health"])
async def health_check():
    """Health check endpoint to verify API is running."""
    return {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "version": "1.0.0",
        "debug_mode": settings.DEBUG
    }

@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request, exc):
    """Global exception handler for database errors."""
    error_message = str(exc) if settings.DEBUG else "Database error occurred. Please try again later."
    
    # Log the full error to console
    print(f"DATABASE ERROR: {str(exc)}")
    logger.error(f"Database error: {str(exc)}")
    
    # Also log traceback for debugging
    import traceback
    traceback_str = traceback.format_exc()
    print(f"TRACEBACK: \n{traceback_str}")
    logger.error(f"Traceback: \n{traceback_str}")
    
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": error_message
        }
    )