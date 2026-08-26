from pydantic import BaseModel, ConfigDict
from typing import List


class ChatAttachment(BaseModel):
    filename: str
    mime_type: str | None = None
    data_url: str | None = None
    ocr_text: str | None = None


class ChatMessageCreate(BaseModel):
    conversation_id: int | None = None
    message: str
    attachments: List[ChatAttachment] | None = None


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: str


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str | None
    created_at: str
    messages: List[ChatMessageResponse] | None = None
