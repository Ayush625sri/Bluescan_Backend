from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
import re

db_url = settings.DATABASE_URL
db_url = re.sub(r'\?sslmode=require', '', db_url)
db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://')

engine = create_async_engine(
    db_url,
    echo=False,
    connect_args={"ssl": True} if "neon.tech" in db_url else {}
)

SessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()

async def get_db():
    async with SessionLocal() as db:
        try:
            yield db
        finally:
            await db.close()
            
def get_db_sync():
    """Synchronous database session for WebSocket usage."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import re
    
    db_url = settings.get_database_url
    db_url = re.sub(r'\?sslmode=require', '', db_url)
    # Remove asyncpg for sync connection
    db_url = db_url.replace('postgresql+asyncpg://', 'postgresql://')
    
    sync_engine = create_engine(db_url)
    SyncSessionLocal = sessionmaker(bind=sync_engine)
    
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()
        
