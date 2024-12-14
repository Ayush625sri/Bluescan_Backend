from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from typing import Any, Annotated
import httpx

from app.core.security import create_access_token, verify_token
from app.core.config import settings
from app.database import get_db
from app.schemas.user import UserCreate, User, Token, UserGoogle
from app.models.user import User
from app.services import auth_service
from app.core.rate_limit import RateLimiter

# Initialize router and OAuth2 scheme
router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

rate_limiter = RateLimiter(requests_per_minute=5) 

@router.post("/register", response_model=User)
def register(*, request: Request, db: Session = Depends(get_db), user_in: UserCreate) -> Any:
    """
    Register a new user with email and password.
    Creates an inactive user account and sends email verification.
    """
    # Check if rate limit is exceeded
    rate_limiter.check_rate_limit(request)
    
    user = auth_service.get_user_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )
    
    # Create user with email verification token
    user = auth_service.create_user(db, user_in)
    verification_token = auth_service.create_verification_token(db, user)
    
    # Here you would normally send an email with the verification link
    # For development, we return the token in the response
    return {
        "user": user,
        "verification_token": verification_token
    }


@router.post("/login", response_model=Token)
def login(
    request: Request,  
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """OAuth2 compatible token login, get an access token for future requests."""
    # Check rate limit before processing the login
    rate_limiter.check_rate_limit(request)
    
    user = auth_service.authenticate(
        db, email=form_data.username, password=form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    elif not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(
        subject=user.email, expires_delta=access_token_expires
    )
    return {"access_token": token, "token_type": "bearer"}

@router.post("/google", response_model=Token)
async def google_auth(*, db: Session = Depends(get_db), token: str) -> Any:
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
        
        user_data = response.json()
        user = auth_service.get_user_by_email(db, email=user_data["email"])
        
        if not user:
            user_in = UserGoogle(
                email=user_data["email"],
                full_name=user_data["name"],
                google_id=user_data["sub"]
            )
            user = auth_service.create_google_user(db, user_in)
        
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        token = create_access_token(
            subject=user.email, expires_delta=access_token_expires
        )
        return {"access_token": token, "token_type": "bearer"}

@router.get("/me", response_model=User)
def read_current_user( current_user: Annotated[User, Depends(get_current_user)]) -> User:
    """
    Get details of currently logged-in user.
    This endpoint demonstrates how to protect routes with JWT authentication.
    """
    return current_user

@router.post("/verify-email")
async def verify_email(token: str, db: Session = Depends(get_db)):
    """
    Verify user's email address using the verification token sent to their email.
    This endpoint activates the user account after email verification.
    """
    user = auth_service.verify_email_token(db, token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token"
        )
    return {"message": "Email verified successfully"}

@router.post("/resend-verification")
async def resend_verification(email: str, db: Session = Depends(get_db)):
    """
    Resend email verification token if the previous one expired.
    """
    user = auth_service.get_user_by_email(db, email)
    if not user or user.email_verified:
        return {"message": "If this email exists and is not verified, a new verification link has been sent"}
    
    # Generate new verification token
    verification_token = auth_service.create_verification_token(db, user)
    
    # Here you would normally send an email with the verification link
    # For development, we'll return the token
    return {"verification_token": verification_token}