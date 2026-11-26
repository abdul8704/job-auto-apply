import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.db import Base, get_engine
from app.documents.router import router as documents_router
from app.github.router import router as github_router
from app.jobs.router import router as jobs_router
from app.outreach.router import router as outreach_router
from app.profile.router import router as profile_router
from app.resumes.router import router as resumes_router
from app.settings import get_settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().auto_create_tables:
        Base.metadata.create_all(get_engine())
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="job-auto-apply", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_router)
    app.include_router(profile_router)
    app.include_router(documents_router)
    app.include_router(resumes_router)
    app.include_router(jobs_router)
    app.include_router(outreach_router)
    app.include_router(github_router)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
