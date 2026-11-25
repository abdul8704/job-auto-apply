"""Application kits: a tailored resume, outreach messages and a cover letter for one job."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import current_user
from app.db import get_db
from app.jobs.router import owned_job
from app.models import ApplicationKit, Contact, User
from app.outreach.schema import Outreach
from app.outreach.writing import personalize
from app.profile.router import get_or_create_profile
from app.profile.schema import Profile
from app.rendering.latex import TEMPLATES
from app.storage import get_storage
from app.worker import generate_kit

router = APIRouter(tags=["outreach"])


class KitIn(BaseModel):
    template: str = "classic"


class KitOut(BaseModel):
    id: str
    job_id: str
    status: str
    template: str
    tailored_profile: Profile | None
    honesty_report: dict | None
    outreach: Outreach | None
    cover_letter: str | None
    has_cover_letter_pdf: bool
    resume_id: str | None
    warnings: list[str] | None
    error: str | None
    created_at: datetime


class MessageOut(BaseModel):
    contact_id: str
    to_name: str
    to_email: str | None
    email_status: str
    kind: str  # referral_request | recruiter_note
    subject: str
    body: str
    resume_id: str | None
    has_cover_letter_pdf: bool


def _out(kit: ApplicationKit) -> KitOut:
    return KitOut(
        **{k: getattr(kit, k) for k in KitOut.model_fields if k != "has_cover_letter_pdf"},
        has_cover_letter_pdf=bool(kit.cover_letter_key),
    )


def owned_kit(kit_id: str, user: User, db: Session) -> ApplicationKit:
    kit = db.get(ApplicationKit, kit_id)
    if kit is None or kit.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kit not found")
    return kit


@router.post("/jobs/{job_id}/kits", response_model=KitOut, status_code=202)
def create_kit(
    job_id: str, body: KitIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> KitOut:
    """Generate the tailored resume, referral/recruiter messages and cover letter. Poll GET /kits/{id}."""
    job = owned_job(job_id, user, db)
    if job.status != "parsed":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Job is {job.status}; wait until it is parsed")
    if body.template not in TEMPLATES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown template {body.template}")
    profile = Profile.model_validate(get_or_create_profile(db, user).data)
    if not (profile.experience or profile.projects):
        raise HTTPException(status.HTTP_409_CONFLICT, "Fill in your profile (upload a resume) first")
    kit = ApplicationKit(user_id=user.id, job_id=job.id, template=body.template)
    db.add(kit)
    db.commit()
    generate_kit.delay(kit.id)
    db.refresh(kit)
    return _out(kit)


@router.get("/jobs/{job_id}/kits", response_model=list[KitOut])
def list_kits(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[KitOut]:
    job = owned_job(job_id, user, db)
    q = (
        select(ApplicationKit)
        .where(ApplicationKit.job_id == job.id)
        .order_by(ApplicationKit.created_at.desc())
    )
    return [_out(k) for k in db.scalars(q)]


@router.get("/kits/{kit_id}", response_model=KitOut)
def get_kit(kit_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> KitOut:
    return _out(owned_kit(kit_id, user, db))


@router.get("/kits/{kit_id}/cover-letter.pdf", response_class=Response)
def cover_letter_pdf(
    kit_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    kit = owned_kit(kit_id, user, db)
    if not kit.cover_letter_key:
        raise HTTPException(status.HTTP_409_CONFLICT, f"No cover letter PDF (kit is {kit.status})")
    return Response(
        get_storage().get(kit.cover_letter_key),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="cover-letter-{kit.id[:8]}.pdf"'},
    )


@router.get("/kits/{kit_id}/messages/{contact_id}", response_model=MessageOut)
def message_for_contact(
    kit_id: str, contact_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> MessageOut:
    """The outreach email for one contact: a recruiter note for HR, a referral request for anyone else."""
    kit = owned_kit(kit_id, user, db)
    contact = db.get(Contact, contact_id)
    if contact is None or contact.job_id != kit.job_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    if kit.status != "done" or not kit.outreach:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Kit is {kit.status}")
    outreach = Outreach.model_validate(kit.outreach)
    kind = "recruiter_note" if contact.category == "recruiter" else "referral_request"
    draft = personalize(getattr(outreach, kind), contact.first_name)
    return MessageOut(
        contact_id=contact.id,
        to_name=contact.full_name,
        to_email=contact.email,
        email_status=contact.email_status,
        kind=kind,
        subject=draft.subject,
        body=draft.body,
        resume_id=kit.resume_id,
        has_cover_letter_pdf=bool(kit.cover_letter_key),
    )
