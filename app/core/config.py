from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # API Settings
    APP_NAME: str = "Ocean Pollution API"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"
    
    # Authentication
    SECRET_KEY: str  
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    
    # Database
    DATABASE_URL: str 
    NEON_DATABASE_URL: str 
    USE_NEON_DB: bool = False
    # CORS
    CORS_ORIGINS: str
    
    # Google OAuth
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    
    FRONTEND_URL: str 
    
    # Email settings
    EMAIL_SENDER: str 
    SMTP_HOST: str
    SMTP_PORT: int 
    SMTP_USER: str
    SMTP_PASSWORD: str
    SMTP_TLS: bool
    SMTP_SSL: bool 
    @property
    def get_database_url(self) -> str:
        if self.USE_NEON_DB:
            return self.NEON_DATABASE_URL
        return self.DATABASE_URL
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()