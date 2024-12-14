from fastapi import APIRouter
from app.api.v1.endpoints import router as pollution_router

api_router = APIRouter()
api_router.include_router(pollution_router, prefix="/pollution", tags=["pollution"])