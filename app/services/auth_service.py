from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timedelta
import secrets
from jose import jwt, JWTError
from loguru import logger

from app.core.security import pwd_context, create_access_token
from app.core.config import settings
from app.models.user import User as UserModel
from app.schemas.user import UserCreate, UserGoogle
from app.core.email import send_verification_email, send_password_reset_email

async def get_user_by_email(db: AsyncSession, email: str) -> Optional[UserModel]:
    """Get user by email."""
    result = await db.execute(select(UserModel).where(UserModel.email == email))
    return result.scalars().first()

async def create_user(db: AsyncSession, user_in: UserCreate) -> Dict[str, Any]:
    """Create a new user with email and password."""
    # Hash password
    hashed_password = pwd_context.hash(user_in.password)
    
    # Generate verification token
    verification_token = secrets.token_urlsafe(32)
    verification_expires = datetime.utcnow() + timedelta(hours=24)
    
    # Create new user
    new_user = UserModel(
        email=user_in.email,
        hashed_password=hashed_password,
        full_name=user_in.full_name,
        is_active=False,
        email_verified=False,
        verification_token=verification_token,
        verification_token_expires=verification_expires
    )
    
    # Save to database
    db.add(new_user)
    await db.commit()
    
    try:
        # Send verification email
        verification_url = f"{settings.FRONTEND_URL}/verify-email?token={verification_token}"
        await send_verification_email(
            email=user_in.email,
            name=user_in.full_name,
            verification_url=verification_url
        )
    except Exception as e:
        # Log the error but don't fail the registration process
        logger.error(f"Failed to send verification email: {str(e)}")
    
    # Return user info
    return {
        "id": new_user.id,
        "email": new_user.email,
        "full_name": new_user.full_name,
        "is_active": new_user.is_active,
        "verification_token": verification_token if settings.DEBUG else None
    }

async def authenticate_user(db: AsyncSession, email: str, password: str) -> Optional[UserModel]:
    """Authenticate a user with email and password."""
    user = await get_user_by_email(db, email=email)
    
    if not user or not user.hashed_password:
        return None
    
    if not pwd_context.verify(password, user.hashed_password):
        return None
    
    return user

async def create_google_user(db: AsyncSession, user_data: Dict[str, Any]) -> UserModel:
    """Create or update user with Google credentials."""
    email = user_data.get("email")
    name = user_data.get("name")
    google_id = user_data.get("sub")
    
    # Check if user exists
    user = await get_user_by_email(db, email=email)
    
    if not user:
        # Create new user
        new_user = UserModel(
            email=email,
            full_name=name,
            google_id=google_id,
            is_active=True,
            email_verified=True
        )
        db.add(new_user)
        await db.commit()
        return new_user
    
    # Update existing user if needed
    if not user.google_id:
        stmt = (
            update(UserModel)
            .where(UserModel.id == user.id)
            .values(
                google_id=google_id,
                is_active=True,
                email_verified=True
            )
        )
        await db.execute(stmt)
        await db.commit()
    
    return user

async def verify_email_token(db: AsyncSession, token: str) -> Dict[str, str]:
    """Verify user's email using token."""
    # Find user with token
    result = await db.execute(
        select(UserModel).where(
            UserModel.verification_token == token,
            UserModel.verification_token_expires > datetime.utcnow()
        )
    )
    user = result.scalars().first()
    
    if not user:
        return {"success": False, "message": "Invalid or expired verification token"}
    
    # Update user
    stmt = (
        update(UserModel)
        .where(UserModel.id == user.id)
        .values(
            email_verified=True,
            is_active=True,
            verification_token=None,
            verification_token_expires=None
        )
    )
    await db.execute(stmt)
    await db.commit()
    
    return {"success": True, "message": "Email verified successfully"}

async def generate_password_reset(db: AsyncSession, email: str) -> Optional[str]:
    """Generate password reset token and send email."""
    # Find user
    user = await get_user_by_email(db, email=email)
    if not user:
        return None
    
    # Generate token
    from app.models.password_reset import PasswordReset
    
    reset_token = secrets.token_urlsafe(32)
    expiration = datetime.utcnow() + timedelta(hours=24)
    
    # Store in database
    reset = PasswordReset(
        user_id=user.id,
        token=reset_token,
        expires_at=expiration,
        used=False
    )
    db.add(reset)
    await db.commit()
    
    # Send reset email
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"
    await send_password_reset_email(
        email=user.email,
        name=user.full_name,
        reset_url=reset_url
    )
    
    return reset_token if settings.DEBUG else None

async def reset_user_password(db: AsyncSession, token: str, new_password: str) -> Dict[str, Any]:
    """Reset user password using token."""
    from app.models.password_reset import PasswordReset
    
    # Find reset token
    result = await db.execute(
        select(PasswordReset).where(
            PasswordReset.token == token,
            PasswordReset.expires_at > datetime.utcnow(),
            PasswordReset.used == False
        )
    )
    reset = result.scalars().first()
    
    if not reset:
        return {"success": False, "message": "Invalid or expired reset token"}
    
    # Update password
    hashed_password = pwd_context.hash(new_password)
    await db.execute(
        update(UserModel)
        .where(UserModel.id == reset.user_id)
        .values(hashed_password=hashed_password)
    )
    
    # Mark token as used
    await db.execute(
        update(PasswordReset)
        .where(PasswordReset.token == token)
        .values(used=True)
    )
    
    await db.commit()
    
    return {"success": True, "message": "Password reset successful"}

async def verify_jwt_token(token: str) -> Optional[str]:
    """Verify JWT token and return email."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload.get("sub")
    except JWTError:
        return None