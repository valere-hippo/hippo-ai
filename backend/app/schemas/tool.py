from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AIToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    instructions: str = Field(min_length=1)
    tool_type: str = Field(default="workflow", min_length=1, max_length=40)
    command: str | None = None
    endpoint: str | None = None
    method: str | None = Field(default=None, max_length=16)
    parameters: dict | None = None
    is_enabled: bool = True


class AIToolUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    instructions: str | None = Field(default=None, min_length=1)
    tool_type: str | None = Field(default=None, min_length=1, max_length=40)
    command: str | None = None
    endpoint: str | None = None
    method: str | None = Field(default=None, max_length=16)
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
    endpoint: str | None
    method: str | None
    parameters: dict | None
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
