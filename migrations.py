"""Database migration script for Ocean Pollution Detection API."""
import os
import sys
from alembic import command
from alembic.config import Config
import logging

logger = logging.getLogger("migrations")

def setup_logging():
    """Configure logging for migrations"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

def run_migrations(database_url=None):
    """Configure and run database migrations using Alembic."""
    try:
        from app.core.config import settings
        
        # Use provided database_url or get from settings
        if not database_url:
            database_url = settings.get_database_url
            
        # Convert async URI to sync URI for Alembic
        if 'asyncpg' in database_url:
            sync_uri = database_url.replace('postgresql+asyncpg', 'postgresql')
        else:
            sync_uri = database_url
        
        # Configure Alembic
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", sync_uri)
        
        # Ensure migrations directory exists
        os.makedirs("migrations/versions", exist_ok=True)
        
        # Check if versions directory has migration files
        has_revisions = len(os.listdir("migrations/versions")) > 0
        
        if not has_revisions:
            logger.info("No migrations found. Skipping migration application.")
        else:
            logger.info("Applying database migrations")
            command.upgrade(alembic_cfg, "head")
            logger.info("Database migrations completed")
        
        return 0
    except Exception as e:
        logger.error(f"Migration failed: {str(e)}")
        return 1

if __name__ == "__main__":
    setup_logging()
    if len(sys.argv) > 1:
        db_url = sys.argv[1]
        sys.exit(run_migrations(db_url))
    else:
        sys.exit(run_migrations())