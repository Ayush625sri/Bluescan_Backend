from typing import Optional, Dict, List, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from fastapi import UploadFile, HTTPException
from datetime import datetime
import uuid
import os
from pathlib import Path
import aiofiles
from PIL import Image
import io

from app.core.config import settings
from app.models.session_image import SessionImage

# Create upload directory
UPLOAD_DIR = Path("uploads/session_images")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

THUMBNAIL_DIR = Path("uploads/thumbnails")
THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

async def upload_session_image(
    db: AsyncSession,
    session_id: str,
    user_id: int,
    file: UploadFile,
    description: Optional[str] = None
) -> Dict[str, Any]:
    """Upload and store a session image."""
    
    # Generate unique filename
    file_extension = file.filename.split('.')[-1].lower()
    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    file_path = UPLOAD_DIR / unique_filename
    
    # Save original image
    async with aiofiles.open(file_path, 'wb') as buffer:
        content = await file.read()
        await buffer.write(content)
    
    # Create thumbnail
    thumbnail_filename = f"thumb_{unique_filename}"
    thumbnail_path = THUMBNAIL_DIR / thumbnail_filename
    await create_thumbnail(file_path, thumbnail_path)
    
    # Save to database
    image_record = SessionImage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        uploaded_by=user_id,
        filename=unique_filename,
        original_filename=file.filename,
        file_path=str(file_path),
        thumbnail_path=str(thumbnail_path),
        content_type=file.content_type,
        file_size=len(content),
        description=description
    )
    
    db.add(image_record)
    await db.commit()
    
    return {
        "id": image_record.id,
        "filename": image_record.filename,
        "original_filename": image_record.original_filename,
        "url": f"/uploads/session_images/{unique_filename}",
        "thumbnail_url": f"/uploads/thumbnails/{thumbnail_filename}",
        "content_type": image_record.content_type,
        "file_size": image_record.file_size,
        "description": image_record.description,
        "uploaded_at": image_record.created_at.isoformat(),
        "uploaded_by": user_id
    }

async def get_session_images(
    db: AsyncSession,
    session_id: str,
    skip: int = 0,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get all images from a session."""
    
    result = await db.execute(
        select(SessionImage)
        .where(SessionImage.session_id == session_id)
        .order_by(SessionImage.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    images = result.scalars().all()
    
    return [
        {
            "id": img.id,
            "filename": img.filename,
            "original_filename": img.original_filename,
            "url": f"/uploads/session_images/{img.filename}",
            "thumbnail_url": f"/uploads/thumbnails/thumb_{img.filename}",
            "content_type": img.content_type,
            "file_size": img.file_size,
            "description": img.description,
            "uploaded_at": img.created_at.isoformat(),
            "uploaded_by": img.uploaded_by
        }
        for img in images
    ]

async def get_image_by_id(
    db: AsyncSession,
    image_id: str,
    session_id: str
) -> Optional[Dict[str, Any]]:
    """Get a specific image by ID."""
    
    result = await db.execute(
        select(SessionImage).where(
            and_(
                SessionImage.id == image_id,
                SessionImage.session_id == session_id
            )
        )
    )
    image = result.scalars().first()
    
    if not image:
        return None
    
    return {
        "id": image.id,
        "filename": image.filename,
        "original_filename": image.original_filename,
        "url": f"/uploads/session_images/{image.filename}",
        "thumbnail_url": f"/uploads/thumbnails/thumb_{image.filename}",
        "content_type": image.content_type,
        "file_size": image.file_size,
        "description": image.description,
        "uploaded_at": image.created_at.isoformat(),
        "uploaded_by": image.uploaded_by,
        "session_id": image.session_id
    }

async def delete_session_image(
    db: AsyncSession,
    image_id: str,
    session_id: str,
    user_id: int
) -> bool:
    """Delete a session image."""
    
    result = await db.execute(
        select(SessionImage).where(
            and_(
                SessionImage.id == image_id,
                SessionImage.session_id == session_id,
                SessionImage.uploaded_by == user_id
            )
        )
    )
    image = result.scalars().first()
    
    if not image:
        raise HTTPException(status_code=404, detail="Image not found or access denied")
    
    # Delete files
    try:
        if os.path.exists(image.file_path):
            os.remove(image.file_path)
        if os.path.exists(image.thumbnail_path):
            os.remove(image.thumbnail_path)
    except Exception as e:
        # Log error but continue with database deletion
        print(f"Error deleting files: {e}")
    
    # Delete from database
    await db.delete(image)
    await db.commit()
    
    return True

async def get_session_image_count(db: AsyncSession, session_id: str) -> int:
    """Get count of images in a session."""
    from sqlalchemy import func
    
    result = await db.execute(
        select(func.count(SessionImage.id)).where(
            SessionImage.session_id == session_id
        )
    )
    return result.scalar() or 0

async def create_thumbnail(input_path: Path, output_path: Path, size: tuple = (200, 200)):
    """Create a thumbnail from an image."""
    try:
        with Image.open(input_path) as img:
            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            
            # Create thumbnail
            img.thumbnail(size, Image.Resampling.LANCZOS)
            img.save(output_path, 'JPEG', quality=85, optimize=True)
    except Exception as e:
        print(f"Error creating thumbnail: {e}")
        # Copy original if thumbnail creation fails
        import shutil
        shutil.copy2(input_path, output_path)