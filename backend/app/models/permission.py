from enum import Enum as PyEnum
from sqlalchemy import Integer, ForeignKey, Enum, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PermissionLevel(PyEnum):
    READ = "READ"
    WRITE = "WRITE"
    ADMIN = "ADMIN"


class ProjectPermission(Base):
    __tablename__ = "project_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    level: Mapped[PermissionLevel] = mapped_column(Enum(PermissionLevel, name="permission_level"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
