from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ConversationMemory(Base):
    __tablename__ = "ai_conversation_memories"

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("hippoai.ai_conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    facts_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
