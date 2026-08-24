from pydantic import BaseModel, ConfigDict


class PermissionCreate(BaseModel):
    user_id: int
    project_id: int
    level: str


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    project_id: int
    level: str
    is_active: bool
