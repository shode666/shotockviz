"""Celery worker: generate embeddings for news articles and financial events.

Triggered after news_fetcher completes (via Celery signal or explicit call).
Embeds new documents that don't yet have embeddings for RAG-powered AI chat.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from celery import shared_task
from core.logger import get_logger

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=1, default_retry_delay=120)
def embed_new_documents(self):
    """Generate embeddings for unembedded documents.

    Scans news cache + earnings/financials tables for content
    that hasn't been embedded yet, generates vectors via Ollama,
    and stores them in document_embeddings table.
    """
    start = time.time()

    try:
        import redis as redis_lib
        from sqlalchemy import create_engine, text
        from core.config import settings
        from services.embedding_service import generate_embedding_sync

        redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

        total_embedded = 0
        errors = 0

        # ── 1. Embed news articles from Redis cache ──────────────────────
        news_count = _embed_cached_news(engine, redis_client)
        total_embedded += news_count

        # ── 2. Embed earnings events not yet embedded ─────────────────────
        try:
            earnings_count = _embed_earnings_events(engine)
            total_embedded += earnings_count
        except Exception as e:
            errors += 1
            logger.debug("Earnings embedding failed", error=str(e))

        # ── 3. Embed financial history summaries ──────────────────────────
        try:
            fin_count = _embed_financial_summaries(engine)
            total_embedded += fin_count
        except Exception as e:
            errors += 1
            logger.debug("Financial embedding failed", error=str(e))

        elapsed = time.time() - start
        logger.info(
            "Embedding worker completed",
            total_embedded=total_embedded,
            errors=errors,
            elapsed_sec=f"{elapsed:.2f}",
        )

        redis_client.set(
            "worker:embedding:last_success_at",
            datetime.now(timezone.utc).isoformat(),
        )

    except Exception as exc:
        logger.error("embed_new_documents failed", error=str(exc))
        raise self.retry(exc=exc)


def _embed_cached_news(engine, redis_client) -> int:
    """Embed news articles stored in Redis news cache."""
    import json
    from services.embedding_service import generate_embedding_sync
    from sqlalchemy import text

    embedded = 0

    # Scan Redis for news:* keys
    cursor = 0
    news_keys = []
    while True:
        cursor, keys = redis_client.scan(cursor, match="news:*", count=100)
        news_keys.extend(keys)
        if cursor == 0:
            break

    for key in news_keys:
        try:
            raw = redis_client.get(key)
            if not raw:
                continue

            articles = json.loads(raw)
            if not isinstance(articles, list):
                continue

            symbol = key.split(":", 1)[1] if ":" in key else None

            for article in articles:
                title = article.get("title", "")
                summary = article.get("summary", "")
                url = article.get("url", "")

                if not title:
                    continue

                # Check if already embedded (by source_url)
                if url and _is_already_embedded(engine, url):
                    continue

                # Combine title + summary for embedding
                content = f"{title}\n{summary}" if summary else title

                # Truncate to ~2000 chars for embedding efficiency
                if len(content) > 2000:
                    content = content[:2000]

                embedding = generate_embedding_sync(content)
                if embedding is None:
                    continue

                _store_embedding_sync(
                    engine,
                    content=content,
                    embedding=embedding,
                    symbol=symbol.upper() if symbol else None,
                    source="news",
                    source_url=url or None,
                )
                embedded += 1

        except Exception as e:
            logger.debug("News embedding error", key=key, error=str(e))
            continue

    return embedded


def _embed_earnings_events(engine) -> int:
    """Embed earnings events that haven't been embedded yet."""
    from services.embedding_service import generate_embedding_sync
    from sqlalchemy import text

    embedded = 0

    with engine.connect() as conn:
        # Find earnings events not yet in document_embeddings
        result = conn.execute(text("""
            SELECT e.symbol, e.report_date, e.estimated_eps, e.actual_eps,
                   e.surprise_pct, e.price_impact_pct
            FROM earnings_events e
            WHERE NOT EXISTS (
                SELECT 1 FROM document_embeddings d
                WHERE d.source = 'earnings'
                AND d.symbol = e.symbol
                AND d.content LIKE '%' || e.report_date::text || '%'
            )
            ORDER BY e.report_date DESC
            LIMIT 50
        """))
        rows = result.fetchall()

    for row in rows:
        symbol, report_date, est_eps, act_eps, surprise, impact = row

        content = (
            f"Earnings Report: {symbol} on {report_date}. "
            f"EPS estimate: {est_eps}, actual: {act_eps}. "
        )
        if surprise is not None:
            content += f"Surprise: {surprise:+.1f}%. "
        if impact is not None:
            content += f"Price impact: {impact:+.1f}%."

        embedding = generate_embedding_sync(content)
        if embedding is None:
            continue

        _store_embedding_sync(
            engine,
            content=content,
            embedding=embedding,
            symbol=symbol,
            source="earnings",
            source_url=None,
        )
        embedded += 1

    return embedded


def _embed_financial_summaries(engine) -> int:
    """Embed financial history summaries that haven't been embedded yet."""
    from services.embedding_service import generate_embedding_sync
    from sqlalchemy import text

    embedded = 0

    with engine.connect() as conn:
        # Find financials not yet embedded (latest year per symbol)
        result = conn.execute(text("""
            SELECT f.symbol, f.fiscal_year, f.revenue, f.net_profit,
                   f.roe, f.debt_equity, f.gross_margin, f.operating_margin
            FROM financial_history f
            WHERE NOT EXISTS (
                SELECT 1 FROM document_embeddings d
                WHERE d.source = 'financials'
                AND d.symbol = f.symbol
                AND d.content LIKE '%FY' || f.fiscal_year::text || '%'
            )
            ORDER BY f.fiscal_year DESC
            LIMIT 50
        """))
        rows = result.fetchall()

    for row in rows:
        symbol, fy, revenue, net_profit, roe, de, gm, om = row

        parts = [f"Financial Summary: {symbol} FY{fy}."]
        if revenue:
            rev_str = f"{revenue/1e9:.1f}B" if revenue > 1e9 else f"{revenue/1e6:.0f}M"
            parts.append(f"Revenue: {rev_str}.")
        if net_profit:
            np_str = f"{net_profit/1e9:.1f}B" if abs(net_profit) > 1e9 else f"{net_profit/1e6:.0f}M"
            parts.append(f"Net Profit: {np_str}.")
        if roe is not None:
            parts.append(f"ROE: {roe:.1f}%.")
        if de is not None:
            parts.append(f"D/E: {de:.2f}.")
        if gm is not None:
            parts.append(f"Gross Margin: {gm:.1f}%.")
        if om is not None:
            parts.append(f"Operating Margin: {om:.1f}%.")

        content = " ".join(parts)

        embedding = generate_embedding_sync(content)
        if embedding is None:
            continue

        _store_embedding_sync(
            engine,
            content=content,
            embedding=embedding,
            symbol=symbol,
            source="financials",
            source_url=None,
        )
        embedded += 1

    return embedded


def _is_already_embedded(engine, source_url: str) -> bool:
    """Check if a document with this source_url is already embedded."""
    from sqlalchemy import text

    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM document_embeddings WHERE source_url = :url LIMIT 1"),
            {"url": source_url},
        )
        return result.fetchone() is not None


def _store_embedding_sync(
    engine,
    content: str,
    embedding: list[float],
    symbol: str | None,
    source: str,
    source_url: str | None,
) -> None:
    """Store embedding synchronously (for Celery workers)."""
    from sqlalchemy import text

    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO document_embeddings (symbol, content, embedding, source, source_url)
            VALUES (:symbol, :content, :embedding::vector, :source, :source_url)
        """), {
            "symbol": symbol,
            "content": content,
            "embedding": embedding_str,
            "source": source,
            "source_url": source_url,
        })
        conn.commit()
