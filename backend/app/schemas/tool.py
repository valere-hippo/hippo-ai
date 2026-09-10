from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AIToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    instructions: str = Field(min_length=1)
    tool_type: str = Field(default="workflow", min_length=1, max_length=40)
    command: str | None = None
    arguments: str | None = None
    working_directory: str | None = None
    endpoint: str | None = None
    method: str | None = Field(default=None, max_length=16)
    platform: str | None = Field(default=None, max_length=20)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86400)
    requires_confirmation: bool = False
    parameters: dict | None = None
    is_enabled: bool = True


class AIToolUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    instructions: str | None = Field(default=None, min_length=1)
    tool_type: str | None = Field(default=None, min_length=1, max_length=40)
    command: str | None = None
    arguments: str | None = None
    working_directory: str | None = None
    endpoint: str | None = None
    method: str | None = Field(default=None, max_length=16)
    platform: str | None = Field(default=None, max_length=20)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86400)
    requires_confirmation: bool | None = None
    parameters: dict | None = None
    is_enabled: bool | None = None


class AIToolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    instructions: str
    tool_type: str
    command: str | None
    arguments: str | None
    working_directory: str | None
    endpoint: str | None
    method: str | None
    platform: str | None
    timeout_seconds: int | None
    requires_confirmation: bool
    parameters: dict | None
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
