from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkflowTaskDependencySpec(BaseModel):
    task_key: str = Field(min_length=1, max_length=80)


class WorkflowTaskCreatePreview(BaseModel):
    task_key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1)
    model_tag: str = Field(min_length=1, max_length=40)
    input_kind: str = Field(min_length=1, max_length=30)
    execution_mode: str = Field(min_length=1, max_length=20)
    depends_on: list[str] = Field(default_factory=list)
    sort_order: int = 0


class WorkflowPlanRequest(BaseModel):
    source_message: str = Field(min_length=1)
    conversation_id: int | None = None
    project_id: int | None = None
    final_model_tag: str | None = Field(default=None, max_length=40)


class WorkflowCreateRequest(WorkflowPlanRequest):
    metadata: dict | None = None


class WorkflowTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    task_key: str
    title: str
    instruction: str
    model_tag: str
    input_kind: str
    execution_mode: str
    depends_on: list[str] | None
    status: str
    result_text: str | None
    result_json: dict | None
    result_files: list | None
    error_text: str | None
    sort_order: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    conversation_id: int | None
    project_id: int | None
    created_by_user_id: int
    source_message: str
    status: str
    final_model_tag: str | None
    metadata: dict | None = Field(default=None, validation_alias="workflow_metadata")
    created_at: datetime
    updated_at: datetime
    tasks: list[WorkflowTaskResponse] = Field(default_factory=list)


class WorkflowPlanResponse(BaseModel):
    workflow: WorkflowResponse | None = None
    tasks: list[WorkflowTaskCreatePreview] = Field(default_factory=list)
