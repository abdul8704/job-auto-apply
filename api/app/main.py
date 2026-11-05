import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.db import Base, get_engine
from app.documents.router import router as documents_router
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
    app = FastAPI(title="job-auto-apply", version="0.1.0", lifespan=lifespan)
    app.include_router(auth_router)
    app.include_router(profile_router)
    app.include_router(documents_router)
    app.include_router(resumes_router)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
