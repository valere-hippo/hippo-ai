from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from app.api.dependencies import DbSession
from app.core.security import hash_password

from app.api.dependencies import get_current_user
from app.models.user import User
from app.schemas.user import UserResponse, UserProfileUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> User:
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    payload: UserProfileUpdate,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> User:
    email = str(payload.email).lower().strip()
    result = await db.execute(select(User).where(User.email == email, User.id != current_user.id))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Es gibt bereits ein Konto mit dieser E-Mail-Adresse.")

    current_user.full_name = payload.full_name.strip()
    current_user.email = email
    if payload.password:
        current_user.password_hash = hash_password(payload.password)
    await db.commit()
    await db.refresh(current_user)
    return current_user
