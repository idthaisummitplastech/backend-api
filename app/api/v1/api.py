from fastapi import APIRouter
from app.api.v1.endpoints import auth, jobs, applicants, recruitment, tests, cms

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication & MFA"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["Job Vacancies"])
api_router.include_router(applicants.router, prefix="/applicants", tags=["Applicants & Tracking"])
api_router.include_router(recruitment.router, prefix="/recruitment", tags=["Recruitment 7-Stage Pipeline"])
api_router.include_router(tests.router, prefix="/tests", tags=["Online Tests & Anti-Cheat Engine"])
api_router.include_router(cms.router, prefix="/cms", tags=["Company Profile CMS"])
