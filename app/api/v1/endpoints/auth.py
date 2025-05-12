from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import timedelta
from typing import Any, Dict
import httpx

from app.core.security import create_access_token
from app.core.config import settings
from app.database import get_db
from app.schemas.user import UserCreate, User, Token, PasswordReset
from app.models.user import User as UserModel
from app.services import auth_service
from app.core.rate_limit import RateLimiter

# Initialize router and OAuth2 scheme
router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")
rate_limiter = RateLimiter(requests_per_minute=5)

@router.post("/register", response_model=Dict[str, Any])
async def register(
    user_in: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Register a new user with email and password."""
    # Check rate limit
    rate_limiter.check_rate_limit(request)
    
    # Check if user exists
    existing_user = await auth_service.get_user_by_email(db, email=user_in.email)
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create user and send verification email
    user_data = await auth_service.create_user(db, user_in)
    
    return {
        "message": "User registered successfully. Please check your email for verification.",
        "email": user_in.email,
        "full_name": user_in.full_name,
        "verification_token": user_data.get("verification_token")  # Only in DEBUG mode
    }

@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """Login with username and password."""
    # Check rate limit
    rate_limiter.check_rate_limit(request)
    
    # Authenticate user
    user = await auth_service.authenticate_user(db, email=form_data.username, password=form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user. Please verify your email."
        )
    
    # Generate token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(
        subject=user.email, expires_delta=access_token_expires
    )
    
    return {"access_token": token, "token_type": "bearer"}

@router.post("/google", response_model=Token)
async def google_auth(token: str, db: AsyncSession = Depends(get_db)):
    """Authenticate with Google OAuth2."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google token"
            )
        
        # Process Google user data
        user_data = response.json()
        user = await auth_service.create_google_user(db, user_data)
        
        # Generate JWT token
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        token = create_access_token(
            subject=user.email, expires_delta=access_token_expires
        )
        return {"access_token": token, "token_type": "bearer"}

@router.get("/me", response_model=Dict[str, Any])
async def read_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
):
    """Get currently logged-in user details."""
    email = await auth_service.verify_jwt_token(token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = await auth_service.get_user_by_email(db, email=email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Return user data
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser
    }

@router.get("/verify-email", response_model=Dict[str, str])
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    """Verify user's email address using the verification token."""
    result = await auth_service.verify_email_token(db, token)
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )
    
    return {"message": result["message"]}

@router.post("/forgot-password", response_model=Dict[str, str])
async def forgot_password(email: str, db: AsyncSession = Depends(get_db)):
    """Send password reset email."""
    reset_token = await auth_service.generate_password_reset(db, email)
    
    return {
        "message": "If your email is registered, a password reset link has been sent.",
        "reset_token": reset_token  # Only in DEBUG mode
    }

@router.post("/reset-password", response_model=Dict[str, str])
async def reset_password(
    reset_data: PasswordReset,
    db: AsyncSession = Depends(get_db)
):
    """Reset password using token."""
    result = await auth_service.reset_user_password(db, reset_data.token, reset_data.new_password)
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )
    
    return {"message": result["message"]}