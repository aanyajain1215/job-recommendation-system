from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.applications import router as applications_router
from app.api.auth import router as auth_router
from app.api.careers import router as careers_router
from app.api.employer import router as employer_router
from app.api.feedback import router as feedback_router
from app.api.gap import router as gap_router
from app.api.health import router as health_router
from app.api.interactions import router as interactions_router
from app.api.jobs import router as jobs_router
from app.api.onboarding import router as onboarding_router
from app.api.preferences import router as preferences_router
from app.api.profiles import router as profiles_router
from app.api.project_mapping import router as project_mapping_router
from app.api.recommendations import router as recommendations_router
from app.api.resume_optimize import router as resume_optimize_router
from app.api.roadmap import actions_router as roadmap_actions_router
from app.api.roadmap import router as roadmap_router
from app.api.search import router as search_router
from app.api.skills import router as skills_router
from app.api.simulate import router as simulate_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(profiles_router)
api_router.include_router(jobs_router)
api_router.include_router(skills_router)
api_router.include_router(recommendations_router)
api_router.include_router(interactions_router)
api_router.include_router(applications_router)
# ---- Phase 2 (plan §18): gap, roadmap, simulator, career discovery ----
api_router.include_router(gap_router)
api_router.include_router(roadmap_router)
api_router.include_router(roadmap_actions_router)
api_router.include_router(simulate_router)
api_router.include_router(careers_router)
# ---- Phase 4 (plan §18): feedback, preferences, NL search, resume/project ----
api_router.include_router(feedback_router)
api_router.include_router(preferences_router)
api_router.include_router(search_router)
api_router.include_router(resume_optimize_router)
api_router.include_router(project_mapping_router)
# ---- Phase 5 (plan §18/§22): admin surface + M5 onboarding elicitation ----
api_router.include_router(admin_router)
api_router.include_router(onboarding_router)
# ---- Phase E0 (employer experience): company profile + posting lifecycle ----
api_router.include_router(employer_router)
