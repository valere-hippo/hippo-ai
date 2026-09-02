from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectSkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    instructions: str = Field(min_length=1)
    is_enabled: bool = True


class ProjectSkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    instructions: str | None = Field(default=None, min_length=1)
    is_enabled: bool | None = None


class ProjectSkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    description: str | None
    instructions: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
