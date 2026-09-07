from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ModelRegistry(Base):
    __tablename__ = "ai_model_registry"
    __table_args__ = (
        UniqueConstraint("provider", "source_url", "model_id", name="uq_ai_model_registry_provider_source_model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    capability: Mapped[str] = mapped_column(String(50), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ok", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
