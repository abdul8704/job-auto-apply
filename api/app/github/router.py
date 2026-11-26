"""Import projects from GitHub, and choose the top 3 featured projects."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.security import current_user
from app.db import get_db
from app.github.importer import MAX_FEATURED, GitHubImportResult, merge_into_profile, set_featured
from app.models import GitHubImport, User
from app.profile.router import get_or_create_profile
from app.profile.schema import Profile
from app.worker import run_github_import

router = APIRouter(tags=["github"])

USERNAME_RE = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$"


class ImportIn(BaseModel):
    username: str = Field(pattern=USERNAME_RE)
    featured: list[str] = Field(
        default_factory=list, max_length=MAX_FEATURED, description="Your top 3 repo names"
    )
    max_repos: int = Field(default=12, ge=1, le=30)


class ImportOut(BaseModel):
    id: str
    username: str
    featured: list[str]
    status: str
    result: GitHubImportResult | None
    error: str | None
    created_at: datetime


class ApplyIn(BaseModel):
    repos: list[str] | None = Field(default=None, description="Repo names to add; all when omitted")
    add_languages: bool = True


class FeaturedIn(BaseModel):
    project_ids: list[str] = Field(max_length=MAX_FEATURED)


def owned_import(import_id: str, user: User, db: Session) -> GitHubImport:
    row = db.get(GitHubImport, import_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    return row


@router.post("/github/imports", response_model=ImportOut, status_code=202)
def start_import(
    body: ImportIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> GitHubImport:
    """Read your public repos and READMEs and draft a project entry for each (runs in the background)."""
    row = GitHubImport(
        user_id=user.id, username=body.username, featured=body.featured, max_repos=body.max_repos
    )
    db.add(row)
    db.commit()
    run_github_import.delay(row.id)
    db.refresh(row)
    return row


@router.get("/github/imports/{import_id}", response_model=ImportOut)
def get_import(
    import_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> GitHubImport:
    return owned_import(import_id, user, db)


@router.post("/github/imports/{import_id}/apply", response_model=Profile)
def apply_import(
    import_id: str, body: ApplyIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Profile:
    row = owned_import(import_id, user, db)
    if row.status != "done" or not row.result:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Import is {row.status}")
    prow = get_or_create_profile(db, user)
    merged = merge_into_profile(
        Profile.model_validate(prow.data),
        GitHubImportResult.model_validate(row.result),
        body.repos,
        body.add_languages,
    )
    prow.data = merged.model_dump()
    db.commit()
    return merged


@router.put("/profile/featured", response_model=Profile, tags=["profile"])
def choose_featured(
    body: FeaturedIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Profile:
    """Mark up to 3 projects as your top projects. Tailoring keeps them unless they're irrelevant."""
    prow = get_or_create_profile(db, user)
    try:
        updated = set_featured(Profile.model_validate(prow.data), body.project_ids)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    prow.data = updated.model_dump()
    db.commit()
    return updated
