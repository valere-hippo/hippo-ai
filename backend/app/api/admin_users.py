from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import DbSession, get_current_user
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.schemas.user import AdminUserCreate, UserResponse
from app.services.notifications import notify_user_created

router = APIRouter(prefix="/admin/users", tags=["admin-users"]) 

@router.post('/', response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(payload: AdminUserCreate, db: DbSession, current_user=Depends(get_current_user)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail='Zugriff verweigert.')
    email = str(payload.email).lower().strip()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail='Es gibt bereits ein Konto mit dieser E-Mail-Adresse.')
    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    try:
        await notify_user_created(user, current_user)
    except Exception:
        pass
    return user

@router.get('/', response_model=list[UserResponse])
async def list_users(db: DbSession, current_user=Depends(get_current_user)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail='Zugriff verweigert.')
    result = await db.execute(select(User))
    users = result.scalars().all()
    return users
