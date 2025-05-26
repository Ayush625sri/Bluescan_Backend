from sqlalchemy import Column, Integer, String, DateTime, Text, BigInteger
from sqlalchemy.sql import func
from app.database import Base

class SessionImage(Base):
    __tablename__ = "session_images"
    
    id = Column(String, primary_key=True, index=True)
    session_id = Column(String, index=True)
    uploaded_by = Column(Integer, index=True)
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    thumbnail_path = Column(String, nullable=True)
    content_type = Column(String, nullable=False)
    file_size = Column(BigInteger, nullable=False)
    description = Column(Text, nullable=True)
    
    # Analysis fields for ocean pollution detection
    analysis_status = Column(String, default="pending")
    analysis_results = Column(Text, nullable=True)
    pollution_detected = Column(String, nullable=True)
    severity_score = Column(Integer, nullable=True)
    confidence_score = Column(Integer, nullable=True)
    
    # Location and environmental data
    latitude = Column(String, nullable=True)
    longitude = Column(String, nullable=True)
    location_name = Column(String, nullable=True)
    water_temperature = Column(String, nullable=True)
    weather_conditions = Column(String, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())