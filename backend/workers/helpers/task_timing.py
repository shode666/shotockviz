"""Shared helper: timed task execution with standardized logging.

Extracts the common try/except/timing/retry pattern found in every
Celery worker into a reusable decorator.
"""
from __future__ import annotations

import time
from functools import wraps

from core.logger import get_logger

logger = get_logger(__name__)


def timed_task(task_name: str | None = None):
    """Decorator that wraps a Celery task with timing + error logging.

    Usage:
        @shared_task(bind=True, max_retries=3, default_retry_delay=30)
        @timed_task("fetch_set_prices")
        def fetch_set_prices(self):
            # ... only the happy path logic ...

    The decorator handles:
      - Start timer
      - Try/except around the function body
      - Log elapsed time on success or failure
      - Call self.retry(exc=exc) on failure

    Args:
        task_name: Label for log messages. Defaults to function name.
    """
    def decorator(func):
        name = task_name or func.__name__

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            start = time.time()
            try:
                result = func(self, *args, **kwargs)
                elapsed = time.time() - start
                logger.info(f"{name} complete", elapsed_sec=f"{elapsed:.2f}")
                return result
            except Exception as exc:
                elapsed = time.time() - start
                logger.error(f"{name} failed", error=str(exc), elapsed_sec=f"{elapsed:.2f}")
                raise self.retry(exc=exc)

        return wrapper
    return decorator
