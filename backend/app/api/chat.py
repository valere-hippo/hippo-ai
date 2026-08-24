from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import openai

from app.api.dependencies import get_current_user, DbSession
from app.models.user import User
from app.models.chat import Conversation, ChatMessage
from app.models.project import Project
from app.models.permission import PermissionLevel
from app.core.config import settings
from sqlalchemy import select, insert

router = APIRouter(prefix="/chat", tags=["chat"]) 

class ChatRequest(BaseModel):
    conversation_id: int | None = None
    project_id: int | None = None
    message: str

class ChatResponse(BaseModel):
    reply: str
    conversation_id: int | None = None


@router.post("/", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: DbSession, current_user: User = Depends(get_current_user)) -> ChatResponse:
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")
    openai.api_key = settings.openai_api_key

    # verify project permission if provided
    conv_project = None
    if payload.project_id is not None:
        result = await db.execute(select(Project).where(Project.id == payload.project_id))
        proj = result.scalar_one_or_none()
        if proj is None:
            raise HTTPException(status_code=404, detail='Project not found')
        from app.services.permissions import has_project_permission
        allowed = await has_project_permission(db, current_user, proj, PermissionLevel.READ)
        if not allowed:
            raise HTTPException(status_code=403, detail='Forbidden')
        conv_project = proj

    # ensure conversation
    conv_id = payload.conversation_id
    if conv_id is None:
        stmt = insert(Conversation).values(title=None, project_id=conv_project.id if conv_project else None).returning(Conversation)
        result = await db.execute(stmt)
        conv = result.scalar_one()
        conv_id = conv.id

    # store user message
    await db.execute(
        insert(ChatMessage).values(
            conversation_id=conv_id,
            user_id=current_user.id,
            role='user',
            content=payload.message,
        )
    )
    await db.commit()

    # fetch messages for context
    q = select(ChatMessage).where(ChatMessage.conversation_id == conv_id).order_by(ChatMessage.created_at)
    res = await db.execute(q)
    messages = res.scalars().all()

    openai_messages = []
    for m in messages:
        role = 'user' if m.role == 'user' else 'assistant' if m.role == 'assistant' else 'system'
        openai_messages.append({"role": role, "content": m.content})

    # If conversation is tied to a project, inform the assistant it may generate files for that project
    if conv_project is not None:
        system_msg = (
            "You are assisting a user within a project. The user has provided a local shared folder path for this project. "
            "When the user requests generation of a file, produce only the file content wrapped in the following exact markers so the client can save it:\n"
            "<<<FILE:filename.rtf>>>\n<file content here>\n<<<END_FILE>>>\n"
            "Do NOT include additional commentary outside the markers. If a filename is not suggested by the user, choose a sensible filename."
        )
        openai_messages.insert(0, {"role": "system", "content": system_msg})

    # call OpenAI using new client in thread
    import asyncio, os
    # fallback to older openai.ChatCompletion API to avoid new client proxy issue
    os.environ.setdefault('OPENAI_API_KEY', settings.openai_api_key)
    import openai as _openai
    _openai.api_key = settings.openai_api_key
    def call_chat():
        return _openai.ChatCompletion.create(model=settings.openai_model, messages=openai_messages, max_tokens=512)
    completion = await asyncio.to_thread(call_chat)
    # extract reply
    reply_text = ''
    if isinstance(completion, dict) and completion.get('choices'):
        # legacy dict response
        reply_text = completion['choices'][0]['message']['content']
    else:
        try:
            reply_text = completion.choices[0].message.content
        except Exception:
            reply_text = str(completion)

    # store assistant message
    await db.execute(
        insert(ChatMessage).values(
            conversation_id=conv_id,
            user_id=current_user.id,
            role='assistant',
            content=reply_text,
        )
    )
    await db.commit()

    return ChatResponse(reply=reply_text, conversation_id=conv_id)


@router.get('/conversations')
async def list_conversations(db: DbSession, current_user: User = Depends(get_current_user)):
    # list conversations the user participated in or project-less owned
    q = select(Conversation).join(ChatMessage, ChatMessage.conversation_id == Conversation.id).where(ChatMessage.user_id == current_user.id)
    res = await db.execute(q)
    convs = res.scalars().all()
    return convs


@router.get('/conversations/{conv_id}')
async def get_conversation(conv_id: int, db: DbSession, current_user: User = Depends(get_current_user)):
    res = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = res.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail='Not found')
    # if tied to project, check permission
    if conv.project_id is not None:
        result = await db.execute(select(Project).where(Project.id == conv.project_id))
        proj = result.scalar_one_or_none()
        from app.services.permissions import has_project_permission
        allowed = await has_project_permission(db, current_user, proj, PermissionLevel.READ)
        if not allowed:
            raise HTTPException(status_code=403, detail='Forbidden')
    # fetch messages
    msgs = await db.execute(select(ChatMessage).where(ChatMessage.conversation_id == conv_id).order_by(ChatMessage.created_at))
    return { 'conversation': conv, 'messages': msgs.scalars().all() }


@router.delete('/conversations/{conv_id}')
async def delete_conversation(conv_id: int, db: DbSession, current_user: User = Depends(get_current_user)):
    # only allow deletion if user has participated or admin
    msgs = await db.execute(select(ChatMessage).where(ChatMessage.conversation_id == conv_id))
    msgs = msgs.scalars().all()
    if not msgs:
        raise HTTPException(status_code=404, detail='Not found')
    participant_ids = set(m.user_id for m in msgs)
    if current_user.role != UserRole.ADMIN and current_user.id not in participant_ids:
        raise HTTPException(status_code=403, detail='Forbidden')
    await db.execute(ChatMessage.__table__.delete().where(ChatMessage.conversation_id == conv_id))
    await db.execute(Conversation.__table__.delete().where(Conversation.id == conv_id))
    await db.commit()
    return {'ok': True}
