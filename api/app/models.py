"""Database tables. Every user-owned row carries user_id so the app is multi-user ready from day one."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Profile(Base):
    """The user's single source of truth: a JSON document matching app.profile.schema.Profile."""

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Document(Base):
    """An uploaded resume (PDF, DOCX or .tex) and the profile draft parsed from it."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16))  # pdf | docx | tex
    content_type: Mapped[str] = mapped_column(String(127))
    storage_key: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(
        String(16), default="uploaded"
    )  # uploaded | parsing | parsed | failed
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_profile: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RenderedResume(Base):
    """A compiled resume PDF. job_id is set for versions tailored to a job."""

    __tablename__ = "rendered_resumes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True, nullable=True
    )
    template: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | done | failed
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trimmed_items: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    """A job posting the user wants to pursue: fetched from a link (or pasted) and parsed by the LLM."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # workday | jsonld | html | manual
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | parsing | parsed | failed
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # app.jobs.schema.JobPosting
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_pattern: Mapped[str | None] = mapped_column(String(64), nullable=True)  # e.g. "{first}.{last}"
    contacts_status: Mapped[str] = mapped_column(
        String(16), default="idle"
    )  # idle | searching | done | failed
    contacts_warnings: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Contact(Base):
    """A person at the job's company to reach out to: a recruiter/HR, or an employee who could refer."""

    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    first_name: Mapped[str] = mapped_column(String(127), default="")
    last_name: Mapped[str] = mapped_column(String(127), default="")
    position: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_status: Mapped[str] = mapped_column(
        String(16), default="unknown"
    )  # verified | guessed | risky | invalid | unknown
    confidence: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    category: Mapped[str] = mapped_column(
        String(16), default="other"
    )  # recruiter | hiring_manager | peer | other
    score: Mapped[int] = mapped_column(Integer, default=0)  # ranking: higher is a better person to contact
    source: Mapped[str] = mapped_column(String(32))  # posting | hunter | apollo | pattern | manual
    linkedin_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApplicationKit(Base):
    """Everything generated for one job: a tailored resume, outreach messages and a cover letter."""

    __tablename__ = "application_kits"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | generating | done | failed
    template: Mapped[str] = mapped_column(String(64), default="classic")
    tailored_profile: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    honesty_report: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    outreach: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # app.outreach.schema.Outreach
    cover_letter: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_letter_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    resume_id: Mapped[str | None] = mapped_column(
        ForeignKey("rendered_resumes.id", ondelete="SET NULL"), nullable=True
    )
    warnings: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GitHubImport(Base):
    """A GitHub import run: repos summarised into draft projects, applied to the profile on request."""

    __tablename__ = "github_imports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(64))
    featured: Mapped[list] = mapped_column(JSONType, default=list)
    max_repos: Mapped[int] = mapped_column(Integer, default=12)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | running | done | failed
    result: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # GitHubImportResult
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
