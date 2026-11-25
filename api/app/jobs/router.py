"""Jobs: add a posting by link or pasted text, then find people to contact about it."""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import current_user
from app.contacts.base import FoundContact
from app.contacts.finder import ContactFinder, build_providers, categorize, provider_status, score
from app.contacts.patterns import split_name, valid_pattern
from app.db import get_db
from app.jobs.fetch import normalize_domain
from app.jobs.schema import JobPosting
from app.models import Contact, Job, User
from app.worker import ingest_job, search_contacts

router = APIRouter(tags=["jobs"])


class JobIn(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    text: str | None = Field(default=None, description="The job description, if the link can't be fetched")
    company_domain: str | None = Field(default=None, description="e.g. acme.com, if you know it")

    @model_validator(mode="after")
    def need_url_or_text(self):
        if not (self.url or (self.text and self.text.strip())):
            raise ValueError("Give a job link (url) or the job description (text)")
        return self


class JobPatch(BaseModel):
    company_domain: str | None = None
    email_pattern: str | None = Field(default=None, description="e.g. {first}.{last} or {f}{last}")


class JobOut(BaseModel):
    id: str
    url: str | None
    source: str
    status: str
    title: str | None
    company: str | None
    company_domain: str | None
    email_pattern: str | None
    parsed: JobPosting | None
    contacts_status: str
    contacts_warnings: list[str] | None
    error: str | None
    created_at: datetime


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    position: str = ""
    email: str | None = None
    linkedin_url: str | None = None


class ContactOut(BaseModel):
    id: str
    full_name: str
    position: str
    email: str | None
    email_status: str
    confidence: int
    category: str
    score: int
    source: str
    linkedin_url: str | None
    created_at: datetime


def owned_job(job_id: str, user: User, db: Session) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


def _domain(value: str | None) -> str | None:
    if not value:
        return None
    d = normalize_domain(value)
    if not d:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{value!r} is not a company domain")
    return d


@router.post("/jobs", response_model=JobOut, status_code=202)
def add_job(body: JobIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Job:
    """Add a job by link (Workday, most career sites) or pasted text. Parsing runs in the background."""
    if body.url and not body.url.lower().startswith(("http://", "https://")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "url must start with http:// or https://")
    job = Job(
        user_id=user.id,
        url=body.url,
        raw_text=body.text.strip() if body.text and body.text.strip() else None,
        source="manual" if body.text else "html",
        company_domain=_domain(body.company_domain),
    )
    db.add(job)
    db.commit()
    ingest_job.delay(job.id)
    db.refresh(job)
    return job


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[Job]:
    return list(db.scalars(select(Job).where(Job.user_id == user.id).order_by(Job.created_at.desc())))


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Job:
    return owned_job(job_id, user, db)


@router.patch("/jobs/{job_id}", response_model=JobOut)
def update_job(
    job_id: str, body: JobPatch, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Job:
    """Correct the company's email domain or set its email pattern, then search contacts again."""
    job = owned_job(job_id, user, db)
    if "company_domain" in body.model_fields_set:
        job.company_domain = _domain(body.company_domain)
    if "email_pattern" in body.model_fields_set:
        if body.email_pattern and not valid_pattern(body.email_pattern):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "email_pattern uses {first}, {last}, {f}, {l} and . _ -, e.g. {first}.{last}",
            )
        job.email_pattern = body.email_pattern or None
    db.commit()
    return job


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    db.delete(owned_job(job_id, user, db))
    db.commit()
    return Response(status_code=204)


# --- contacts -----------------------------------------------------------------------------------


@router.get("/contacts/providers", tags=["contacts"])
def contact_providers() -> dict[str, bool]:
    """Which contact sources are active. Add HUNTER_API_KEY / APOLLO_API_KEY to turn more on."""
    return provider_status()


@router.post("/jobs/{job_id}/contacts/search", response_model=JobOut, status_code=202, tags=["contacts"])
def start_contact_search(
    job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Job:
    """Find HR/recruiters and likely referrers at the company. Poll GET /jobs/{id} for contacts_status."""
    job = owned_job(job_id, user, db)
    if job.status != "parsed":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Job is {job.status}; wait until it is parsed")
    job.contacts_status, job.contacts_warnings = "searching", None
    db.commit()
    search_contacts.delay(job.id)
    db.refresh(job)
    return job


@router.get("/jobs/{job_id}/contacts", response_model=list[ContactOut], tags=["contacts"])
def list_contacts(
    job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[Contact]:
    job = owned_job(job_id, user, db)
    q = select(Contact).where(Contact.job_id == job.id).order_by(Contact.score.desc(), Contact.created_at)
    return list(db.scalars(q))


@router.post("/jobs/{job_id}/contacts", response_model=ContactOut, status_code=201, tags=["contacts"])
def add_contact(
    job_id: str, body: ContactIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Contact:
    """Add someone you found yourself (e.g. on LinkedIn). Without an email, one is found or guessed."""
    job = owned_job(job_id, user, db)
    first, last = split_name(body.name)
    found = FoundContact(
        full_name=body.name.strip(),
        first_name=first,
        last_name=last,
        position=body.position.strip(),
        email=(body.email or "").strip(),
        email_status="verified" if body.email else "unknown",
        confidence=100 if body.email else 0,
        source="manual",
        linkedin_url=body.linkedin_url or "",
    )
    warnings: list[str] = []
    if not found.email:
        providers, verifier = build_providers()
        finder = ContactFinder(providers, verifier)
        found = asyncio.run(
            finder.resolve_email(found, job.company_domain or "", job.email_pattern or "", warnings)
        )
    posting = JobPosting.model_validate(job.parsed or {})
    cat = categorize(found, posting)
    row = Contact(
        user_id=user.id,
        job_id=job.id,
        full_name=found.full_name[:255],
        first_name=found.first_name[:127],
        last_name=found.last_name[:127],
        position=found.position[:255],
        email=found.email or None,
        email_status=found.email_status,
        confidence=found.confidence,
        category=cat,
        score=score(found, cat),
        source="manual",
        linkedin_url=found.linkedin_url or None,
    )
    db.add(row)
    db.commit()
    return row


@router.delete("/jobs/{job_id}/contacts/{contact_id}", status_code=204, tags=["contacts"])
def delete_contact(
    job_id: str, contact_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    job = owned_job(job_id, user, db)
    row = db.get(Contact, contact_id)
    if row is None or row.job_id != job.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    db.delete(row)
    db.commit()
    return Response(status_code=204)
