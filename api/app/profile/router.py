from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import current_user
from app.db import get_db
from app.models import Profile as ProfileRow
from app.models import User
from app.profile.schema import Profile

router = APIRouter(prefix="/profile", tags=["profile"])


def get_or_create_profile(db: Session, user: User) -> ProfileRow:
    row = db.scalar(select(ProfileRow).where(ProfileRow.user_id == user.id))
    if row is None:
        row = ProfileRow(user_id=user.id, data=Profile().model_dump())
        db.add(row)
        db.commit()
    return row


@router.get("", response_model=Profile)
def read_profile(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Profile:
    return Profile.model_validate(get_or_create_profile(db, user).data)


@router.put("", response_model=Profile)
def replace_profile(
    body: Profile, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Profile:
    row = get_or_create_profile(db, user)
    row.data = body.model_dump()
    db.commit()
    return body
