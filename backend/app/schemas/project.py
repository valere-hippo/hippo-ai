from pydantic import BaseModel, Field
from pydantic import ConfigDict
from datetime import datetime


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    watched_folder: str | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    owner_id: int
    is_active: bool
    watched_folder: str | None = None
    created_at: datetime
