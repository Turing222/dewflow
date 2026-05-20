"""Document chunk ORM model.

职责：保存知识文件和历史消息切片，以及用于检索的向量和元数据。
边界：本模块不负责切片生成、向量化或召回排序。
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.orm.base import Base, BaseIdModel

if TYPE_CHECKING:
    from backend.models.orm.chat import ChatMessage
    from backend.models.orm.knowledge import File


class ChunkSourceType(StrEnum):
    FILE = "file"
    CHAT_MESSAGE = "chat_message"


class DocumentChunk(Base, BaseIdModel):
    """可被 RAG 检索的文本切片。"""

    __tablename__ = "document_chunks"

    source_type: Mapped[ChunkSourceType] = mapped_column(
        String(20), index=True, server_default=ChunkSourceType.FILE
    )

    # 多外键保留数据库约束，配合 check constraint 保证来源唯一。
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_files.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )

    content: Mapped[str] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text, server_default="")
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_count: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunking_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
    )
    meta_info: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))

    embedding: Mapped[Vector] = mapped_column(Vector(768))

    __table_args__ = (
        Index(
            "hnsw_idx_document_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        CheckConstraint(
            "(file_id IS NOT NULL)::int + (message_id IS NOT NULL)::int = 1",
            name="ck_chunk_exactly_one_source",
        ),
        Index(
            "ix_document_chunks_file_content_hash",
            "file_id",
            "content_hash",
        ),
        Index(
            "ix_document_chunks_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
    )

    file: Mapped[File | None] = relationship(back_populates="chunks")
    message: Mapped[ChatMessage | None] = relationship(back_populates="chunks")
