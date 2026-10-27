from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    chat_bot_id: str = Field(min_length=1, max_length=120)
    description: str | None = None
    memory_notes: str | None = None
    system_prompt: str | None = None
    memory_namespace: str | None = Field(default=None, max_length=120)
    share_scope: str = Field(default="private", max_length=20)
    model_provider: str | None = Field(default=None, max_length=40)
    model_name: str | None = Field(default=None, max_length=120)
    allow_shared_skills: bool = True
    allow_shared_tools: bool = True
    is_active: bool = True
    project_id: int | None = None


class ChatProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    chat_bot_id: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    memory_notes: str | None = None
    system_prompt: str | None = None
    memory_namespace: str | None = Field(default=None, max_length=120)
    share_scope: str | None = Field(default=None, max_length=20)
    model_provider: str | None = Field(default=None, max_length=40)
    model_name: str | None = Field(default=None, max_length=120)
    allow_shared_skills: bool | None = None
    allow_shared_tools: bool | None = None
    is_active: bool | None = None


class ChatProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    project_id: int | None
    name: str
    chat_bot_id: str
    description: str | None
    memory_notes: str | None
    system_prompt: str | None
    memory_namespace: str | None
    share_scope: str
    model_provider: str | None
    model_name: str | None
    allow_shared_skills: bool
    allow_shared_tools: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
