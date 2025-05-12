from typing import AsyncGenerator
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError

from app.core.config import settings
from app.database import SessionLocal
from app.services import auth_service
from app.core.security import verify_token

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)

async def get_db() -> AsyncGenerator:
    """Database session dependency."""
    async with SessionLocal() as db:
        yield db

async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme)
):
    """Get the current authenticated user."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        email = verify_token(token)
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = await auth_service.get_user_by_email(db, email=email)
    if user is None:
        raise credentials_exception
    
    return user