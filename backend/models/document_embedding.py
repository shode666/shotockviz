"""Document embedding model for RAG-powered AI chat.

Stores text chunks with vector embeddings for semantic search.
Uses pgvector extension with nomic-embed-text (768 dimensions).
"""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class DocumentEmbedding(Base):
    """Vector-embedded document chunk for RAG context injection."""

    __tablename__ = "document_embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # embedding column is created via raw SQL migration (pgvector vector(768))
    # SQLAlchemy doesn't natively support pgvector types, so we use raw SQL for queries
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # news, financials, earnings
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_doc_embed_symbol_source", "symbol", "source"),
    )

    def __repr__(self) -> str:
        return f"<DocumentEmbedding id={self.id} symbol={self.symbol} source={self.source}>"
