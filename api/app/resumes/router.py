from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import current_user
from app.db import get_db
from app.models import RenderedResume, User
from app.profile.router import get_or_create_profile
from app.profile.schema import Profile
from app.rendering.latex import TEMPLATES, render_latex
from app.storage import get_storage
from app.worker import render_resume

router = APIRouter(prefix="/resumes", tags=["resumes"])


class RenderIn(BaseModel):
    template: str = "classic"
    max_pages: int = Field(default=1, ge=1, le=3)


class ResumeOut(BaseModel):
    id: str
    template: str
    status: str
    pages: int | None
    trimmed_items: list[str] | None
    error: str | None
    created_at: datetime


def owned_resume(resume_id: str, user: User, db: Session) -> RenderedResume:
    row = db.get(RenderedResume, resume_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    return row


@router.get("/templates", response_model=list[str])
def list_templates() -> list[str]:
    return sorted(TEMPLATES)


@router.post("", response_model=ResumeOut, status_code=202)
def render(
    body: RenderIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> RenderedResume:
    """Render the current profile to a PDF in the background. Poll GET /resumes/{id}."""
    if body.template not in TEMPLATES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown template {body.template}")
    profile = get_or_create_profile(db, user).data
    row = RenderedResume(user_id=user.id, template=body.template)
    db.add(row)
    db.commit()
    render_resume.delay(row.id, profile, body.max_pages)
    db.refresh(row)
    return row


@router.get("/preview.tex", response_class=Response)
def preview_latex(
    template: str = "classic", user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    """The LaTeX source for the current profile, useful for debugging templates."""
    if template not in TEMPLATES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown template {template}")
    latex = render_latex(Profile.model_validate(get_or_create_profile(db, user).data), template)
    return Response(latex, media_type="text/plain")


@router.get("", response_model=list[ResumeOut])
def list_resumes(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[RenderedResume]:
    q = (
        select(RenderedResume)
        .where(RenderedResume.user_id == user.id)
        .order_by(RenderedResume.created_at.desc())
    )
    return list(db.scalars(q))


@router.get("/{resume_id}", response_model=ResumeOut)
def get_resume(
    resume_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> RenderedResume:
    return owned_resume(resume_id, user, db)


@router.get("/{resume_id}/pdf", response_class=Response)
def download_pdf(
    resume_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    row = owned_resume(resume_id, user, db)
    if row.status != "done" or not row.storage_key:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Resume is {row.status}")
    return Response(
        get_storage().get(row.storage_key),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="resume-{row.id[:8]}.pdf"'},
    )
