"""Celery app and background tasks. With CELERY_EAGER=true tasks run inline (no Redis needed)."""

import asyncio

from celery import Celery

from app.db import get_sessionmaker
from app.llm import get_llm
from app.models import Document, RenderedResume
from app.profile.parsing import extract_text, parse_resume
from app.profile.schema import Profile
from app.rendering.compile import LatexCompileError
from app.rendering.service import render_pdf
from app.settings import get_settings
from app.storage import get_storage, user_key

settings = get_settings()
celery_app = Celery("job_auto_apply", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_always_eager=settings.celery_eager,
    task_eager_propagates=False,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="documents.parse")
def parse_document(document_id: str) -> str:
    with get_sessionmaker()() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            return "missing"
        doc.status = "parsing"
        db.commit()
        try:
            raw = get_storage().get(doc.storage_key)
            text = extract_text(doc.kind, raw)
            doc.extracted_text = text
            profile = asyncio.run(parse_resume(get_llm(), doc.kind, text, raw))
            doc.parsed_profile = profile.model_dump()
            doc.status = "parsed"
            doc.error = None
        except Exception as exc:  # surfaced to the user via GET /documents/{id}
            doc.status = "failed"
            doc.error = f"{type(exc).__name__}: {exc}"[:2000]
        db.commit()
        return doc.status


@celery_app.task(name="resumes.render")
def render_resume(resume_id: str, profile_data: dict, max_pages: int = 1) -> str:
    with get_sessionmaker()() as db:
        row = db.get(RenderedResume, resume_id)
        if row is None:
            return "missing"
        try:
            result = render_pdf(Profile.model_validate(profile_data), row.template, max_pages=max_pages)
            key = user_key(row.user_id, "resumes", f"{row.id}.pdf")
            get_storage().put(key, result.pdf, "application/pdf")
            row.storage_key, row.pages, row.trimmed_items = key, result.pages, result.trimmed
            row.status, row.error = "done", None
        except LatexCompileError as exc:
            row.status, row.error = "failed", f"{exc}\n{exc.log}"[:4000]
        except Exception as exc:
            row.status, row.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        db.commit()
        return row.status
