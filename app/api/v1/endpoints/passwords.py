from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import timedelta
import secrets

from app.core.deps import get_db
from app.services import auth_service
from app.schemas.user import PasswordReset
from app.core.config import settings

router = APIRouter()

@router.post("/forgot-password")
async def forgot_password(email: str, db: Session = Depends(get_db)):
    """
    Initiates password reset process by generating and storing a reset token.
    In a production environment, this would send an email with the reset link.
    """
    user = auth_service.get_user_by_email(db, email)
    if not user:
        # We return success even if email doesn't exist for security
        return {"message": "If this email exists, a reset link has been sent"}
    
    # Generate reset token
    reset_token = secrets.token_urlsafe(32)
    auth_service.store_reset_token(db, user.id, reset_token)
    
    # Here you would normally send an email with the reset link
    # For development, we'll just return the token
    return {"reset_token": reset_token}

@router.post("/reset-password")
async def reset_password(
    reset_data: PasswordReset,
    db: Session = Depends(get_db)
):
    """
    Resets user password using the provided reset token.
    """
    if not auth_service.verify_reset_token(db, reset_data.token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    auth_service.reset_password(db, reset_data.token, reset_data.new_password)
    return {"message": "Password successfully reset"}