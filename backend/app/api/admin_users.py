from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, update

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


@router.delete('/{user_id}')
async def delete_user(user_id: int, db: DbSession, current_user=Depends(get_current_user)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail='Zugriff verweigert.')
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail='Das eigene Konto kann hier nicht gelöscht werden.')

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail='Benutzer nicht gefunden.')

    from app.models.chat import ChatMessage, Conversation
    from app.models.permission import ProjectPermission
    from app.models.project import Project

    project_result = await db.execute(select(Project.id).where(Project.owner_id == user_id))
    owned_project_ids = [row[0] for row in project_result.fetchall()]
    if owned_project_ids:
        await db.execute(
            update(Project)
            .where(Project.owner_id == user_id)
            .values(owner_id=current_user.id)
        )

    conversation_result = await db.execute(
        select(Conversation.id)
        .where(
            Conversation.id.in_(
                select(ChatMessage.conversation_id).where(ChatMessage.user_id == user_id)
            )
        )
    )
    conversation_ids = [row[0] for row in conversation_result.fetchall()]
    deleted_messages = 0
    deleted_conversations = 0
    deleted_permissions = 0

    if conversation_ids:
        msg_result = await db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(conversation_ids)))
        deleted_messages = msg_result.rowcount or 0
        conv_result = await db.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))
        deleted_conversations = conv_result.rowcount or 0

    perm_result = await db.execute(delete(ProjectPermission).where(ProjectPermission.user_id == user_id))
    deleted_permissions = perm_result.rowcount or 0

    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()

    return {
        "ok": True,
        "user_id": user_id,
        "deleted_messages": deleted_messages,
        "deleted_conversations": deleted_conversations,
        "deleted_permissions": deleted_permissions,
        "reassigned_projects": len(owned_project_ids),
    }
