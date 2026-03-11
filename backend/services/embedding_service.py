"""Embedding service for RAG-powered AI chat.

Generates embeddings via Ollama (nomic-embed-text) and performs
vector similarity search against PostgreSQL + pgvector.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)

EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768  # nomic-embed-text output dimension


@dataclass
class SimilarDocument:
    """A document retrieved by semantic similarity search."""
    content: str
    symbol: str | None
    source: str
    source_url: str | None
    similarity: float


async def generate_embedding(text: str) -> list[float] | None:
    """Generate embedding vector for a text chunk using Ollama.

    Args:
        text: Input text to embed (will be truncated to ~8192 tokens by model)

    Returns:
        768-dimensional float vector, or None on failure
    """
    if not settings.ollama_url:
        return None

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=5.0)
        ) as client:
            resp = await client.post(
                f"{settings.ollama_url}/api/embed",
                json={"model": EMBED_MODEL, "input": text},
            )
            if resp.status_code != 200:
                logger.warning("Ollama embed failed", status=resp.status_code)
                return None

            data = resp.json()
            # Ollama /api/embed returns {"embeddings": [[...]], "model": "..."}
            embeddings = data.get("embeddings")
            if embeddings and len(embeddings) > 0:
                return embeddings[0]

            return None

    except httpx.ConnectError:
        logger.debug("Ollama not reachable for embedding")
        return None
    except Exception as e:
        logger.warning("Embedding generation failed", error=str(e))
        return None


def generate_embedding_sync(text: str) -> list[float] | None:
    """Synchronous version of generate_embedding for Celery workers.

    Args:
        text: Input text to embed

    Returns:
        768-dimensional float vector, or None on failure
    """
    if not settings.ollama_url:
        return None

    try:
        with httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=5.0)
        ) as client:
            resp = client.post(
                f"{settings.ollama_url}/api/embed",
                json={"model": EMBED_MODEL, "input": text},
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            embeddings = data.get("embeddings")
            if embeddings and len(embeddings) > 0:
                return embeddings[0]

            return None

    except Exception as e:
        logger.debug("Sync embedding failed", error=str(e))
        return None


async def search_similar(
    query: str,
    symbol: str | None = None,
    k: int = 3,
) -> list[SimilarDocument]:
    """Search for documents semantically similar to the query.

    Uses pgvector cosine similarity (1 - cosine_distance).

    Args:
        query: User's question/query text
        symbol: Filter by symbol (None = search all)
        k: Number of results to return

    Returns:
        List of similar documents sorted by similarity (desc)
    """
    # Generate embedding for the query
    query_embedding = await generate_embedding(query)
    if query_embedding is None:
        return []

    try:
        from sqlalchemy import text
        from core.database import async_engine

        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        # Build query with optional symbol filter
        where_clause = ""
        params: dict = {"embedding": embedding_str, "k": k}

        if symbol:
            where_clause = "WHERE symbol = :symbol OR symbol IS NULL"
            params["symbol"] = symbol.upper()

        sql = text(f"""
            SELECT content, symbol, source, source_url,
                   1 - (embedding <=> :embedding::vector) AS similarity
            FROM document_embeddings
            {where_clause}
            ORDER BY embedding <=> :embedding::vector
            LIMIT :k
        """)

        from sqlalchemy.ext.asyncio import create_async_engine
        async with async_engine.connect() as conn:
            result = await conn.execute(sql, params)
            rows = result.fetchall()

        return [
            SimilarDocument(
                content=row[0],
                symbol=row[1],
                source=row[2],
                source_url=row[3],
                similarity=float(row[4]) if row[4] else 0.0,
            )
            for row in rows
        ]

    except Exception as e:
        logger.warning("RAG search failed", error=str(e))
        return []


async def store_embedding(
    content: str,
    embedding: list[float],
    symbol: str | None = None,
    source: str = "news",
    source_url: str | None = None,
) -> bool:
    """Store a document with its embedding in the database.

    Args:
        content: Document text
        embedding: Pre-computed embedding vector
        symbol: Associated stock symbol (None for general)
        source: Content source type (news, financials, earnings)
        source_url: URL to original content

    Returns:
        True if stored successfully
    """
    try:
        from sqlalchemy import text
        from core.database import async_engine

        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

        sql = text("""
            INSERT INTO document_embeddings (symbol, content, embedding, source, source_url)
            VALUES (:symbol, :content, :embedding::vector, :source, :source_url)
        """)

        async with async_engine.begin() as conn:
            await conn.execute(sql, {
                "symbol": symbol.upper() if symbol else None,
                "content": content,
                "embedding": embedding_str,
                "source": source,
                "source_url": source_url,
            })

        return True

    except Exception as e:
        logger.warning("Store embedding failed", error=str(e))
        return False
