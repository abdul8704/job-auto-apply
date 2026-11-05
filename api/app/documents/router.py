from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import current_user
from app.db import get_db
from app.models import Document, User, new_id
from app.profile.parsing import UnsupportedFile, detect_kind
from app.profile.router import get_or_create_profile
from app.profile.schema import Profile
from app.settings import get_settings
from app.storage import get_storage, user_key
from app.worker import parse_document

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentOut(BaseModel):
    id: str
    filename: str
    kind: str
    status: str
    error: str | None
    parsed_profile: Profile | None
    created_at: datetime


def owned_document(document_id: str, user: User, db: Session) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:  # never reveal other users' documents
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.post("", response_model=DocumentOut, status_code=201)
def upload_resume(
    file: UploadFile, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Document:
    """Upload a resume (PDF, DOCX or .tex). It is parsed into a profile draft in the background."""
    try:
        kind, content_type = detect_kind(file.filename or "")
    except UnsupportedFile as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")
    doc_id = new_id()
    key = user_key(user.id, "documents", doc_id, f"original.{kind}")
    get_storage().put(key, data, content_type)
    doc = Document(
        id=doc_id,
        user_id=user.id,
        filename=(file.filename or "")[:255],
        kind=kind,
        content_type=content_type,
        storage_key=key,
    )
    db.add(doc)
    db.commit()
    parse_document.delay(doc.id)
    db.refresh(doc)
    return doc


@router.get("", response_model=list[DocumentOut])
def list_documents(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[Document]:
    q = select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc())
    return list(db.scalars(q))


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Document:
    return owned_document(document_id, user, db)


@router.post("/{document_id}/apply", response_model=Profile)
def apply_to_profile(
    document_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Profile:
    """Copy the parsed draft into the profile. The user should review it first (GET, then PUT /profile)."""
    doc = owned_document(document_id, user, db)
    if doc.status != "parsed" or doc.parsed_profile is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Document is {doc.status}, not parsed")
    row = get_or_create_profile(db, user)
    row.data = doc.parsed_profile
    db.commit()
    return Profile.model_validate(row.data)


@router.delete("/{document_id}", status_code=204)
def delete_document(
    document_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> None:
    doc = owned_document(document_id, user, db)
    get_storage().delete(doc.storage_key)
    db.delete(doc)
    db.commit()
