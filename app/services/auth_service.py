from typing import Optional
from sqlalchemy.orm import Session
from app.core.security import pwd_context
from app.models.user import User
from app.schemas.user import UserCreate, UserGoogle
from datetime import datetime, timedelta
from typing import Optional
import secrets

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()

def create_user(db: Session, user_in: UserCreate) -> User:
    hashed_password = pwd_context.hash(user_in.password)
    user = User(
        email=user_in.email,
        hashed_password=hashed_password,
        full_name=user_in.full_name
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def create_google_user(db: Session, user_in: UserGoogle) -> User:
    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        google_id=user_in.google_id
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def authenticate(db: Session, email: str, password: str) -> Optional[User]:
    user = get_user_by_email(db, email=email)
    if not user or not user.hashed_password:
        return None
    if not pwd_context.verify(password, user.hashed_password):
        return None
    return user

def store_reset_token(db: Session, user_id: int, token: str) -> None:
    """Stores password reset token with expiration time"""
    expiration = datetime.utcnow() + timedelta(hours=24)
    db.execute(
        """INSERT INTO password_resets (user_id, token, expires_at)
        VALUES (:user_id, :token, :expires_at)""",
        {
            "user_id": user_id,
            "token": token,
            "expires_at": expiration
        }
    )
    db.commit()

def verify_reset_token(db: Session, token: str) -> bool:
    """Verifies if a reset token is valid and not expired"""
    result = db.execute(
        """SELECT user_id FROM password_resets 
        WHERE token = :token AND expires_at > :now
        AND used = FALSE""",
        {
            "token": token,
            "now": datetime.utcnow()
        }
    ).first()
    return bool(result)

def reset_password(db: Session, token: str, new_password: str) -> None:
    """Resets user password and marks reset token as used"""
    user_id = db.execute(
        "SELECT user_id FROM password_resets WHERE token = :token",
        {"token": token}
    ).scalar()
    
    if user_id:
        hashed_password = pwd_context.hash(new_password)
        db.execute(
            "UPDATE users SET hashed_password = :password WHERE id = :user_id",
            {"password": hashed_password, "user_id": user_id}
        )
        db.execute(
            "UPDATE password_resets SET used = TRUE WHERE token = :token",
            {"token": token}
        )
        db.commit()
        
        
def create_verification_token(db: Session, user: User) -> str:
    """
    Creates a new email verification token for a user.
    """
    token = secrets.token_urlsafe(32)
    user.verification_token = token
    user.verification_token_expires = datetime.utcnow() + timedelta(hours=24)
    db.commit()
    return token

def verify_email_token(db: Session, token: str) -> Optional[User]:
    """
    Verifies an email verification token and activates the user account.
    """
    user = db.query(User).filter(
        User.verification_token == token,
        User.verification_token_expires > datetime.utcnow()
    ).first()
    
    if user:
        user.email_verified = True
        user.is_active = True
        user.verification_token = None
        user.verification_token_expires = None
        db.commit()
        return user
    return None