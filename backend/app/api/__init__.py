from fastapi import APIRouter

from app.api.applications import router as applications_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.interactions import router as interactions_router
from app.api.jobs import router as jobs_router
from app.api.profiles import router as profiles_router
from app.api.recommendations import router as recommendations_router
from app.api.skills import router as skills_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(profiles_router)
api_router.include_router(jobs_router)
api_router.include_router(skills_router)
api_router.include_router(recommendations_router)
api_router.include_router(interactions_router)
api_router.include_router(applications_router)
