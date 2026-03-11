"""Fear & Greed Index fetcher — CNN Business.

Fetches the CNN Fear & Greed Index every 30 minutes and caches in Redis.
CQRS write-side: sole data ingester for FGI data.
"""
import json
import logging

import httpx
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)

CNN_FGI_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CACHE_KEY = "fgi:current"
CACHE_TTL = 3600  # 1 hour


def _fgi_label(score: float) -> str:
    """Map FGI score (0-100) to human-readable label."""
    if score <= 25:
        return "Extreme Fear"
    elif score <= 45:
        return "Fear"
    elif score <= 55:
        return "Neutral"
    elif score <= 75:
        return "Greed"
    else:
        return "Extreme Greed"


@celery_app.task(name="workers.fgi_fetcher.fetch_fear_greed", bind=True, max_retries=2)
def fetch_fear_greed(self):
    """Fetch CNN Fear & Greed Index and cache the result."""
    import redis as sync_redis
    from core.config import settings

    try:
        resp = httpx.get(
            CNN_FGI_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://edition.cnn.com/markets/fear-and-greed",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

        # CNN API returns: { "fear_and_greed": { "score": 38.5, "rating": "Fear", ... }, ... }
        fng = data.get("fear_and_greed", {})
        score = fng.get("score")
        if score is None:
            logger.warning("FGI: no score in response")
            return

        score = round(float(score), 1)
        rating = fng.get("rating", _fgi_label(score))
        previous_close = fng.get("previous_close", None)
        change = round(score - previous_close, 1) if previous_close is not None else None

        result = {
            "score": score,
            "label": rating,
            "previous_close": round(float(previous_close), 1) if previous_close else None,
            "change": change,
        }

        r = sync_redis.from_url(settings.redis_url, decode_responses=True)
        r.set(CACHE_KEY, json.dumps(result), ex=CACHE_TTL)
        logger.info(f"FGI cached: {score} ({rating})")

    except Exception as exc:
        logger.error(f"FGI fetch failed: {exc}")
        raise self.retry(exc=exc, countdown=120)
