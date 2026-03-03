"""
Celery task signal handlers for monitoring.

Registers handlers for task_success, task_failure, and task_prerun events
to track Celery health metrics in Redis.
"""
import time
from celery.signals import task_success, task_failure, task_prerun

# Global dict to track task start times
_task_start_times = {}


@task_prerun.connect
def task_prerun_handler(task_id, task, *args, **kwargs):
    """Record task start time before execution."""
    _task_start_times[task_id] = time.time()


@task_success.connect
def task_success_handler(sender=None, **kwargs):
    """Track successful task completion in Redis."""
    try:
        from datetime import datetime, timezone
        import redis
        import os

        task_id = kwargs.get("task_id", "")
        elapsed = time.time() - _task_start_times.pop(task_id, time.time())

        # Use sync Redis for signal handler (signals are synchronous)
        redis_url = os.getenv('REDIS_URL', 'redis://redis:6379/0')
        r = redis.from_url(redis_url)

        r.incr('celery:stats:success')
        r.set('celery:stats:last_success_at', datetime.now(timezone.utc).isoformat())
        r.set(f'celery:task:last_success_elapsed', f'{elapsed:.2f}')
        r.expire('celery:stats:success', 86400 * 7)  # 7 days TTL
    except Exception:
        # Silently ignore monitoring errors — don't crash task handler
        pass


@task_failure.connect
def task_failure_handler(sender=None, **kwargs):
    """Track failed task completion in Redis."""
    try:
        from datetime import datetime, timezone
        import redis
        import os

        task_id = kwargs.get("task_id", "")
        exception = kwargs.get("exception", "unknown")
        _task_start_times.pop(task_id, None)

        redis_url = os.getenv('REDIS_URL', 'redis://redis:6379/0')
        r = redis.from_url(redis_url)

        r.incr('celery:stats:failure')
        r.set('celery:stats:last_failure_at', datetime.now(timezone.utc).isoformat())
        r.set('celery:stats:last_error', str(exception)[:500])
        r.expire('celery:stats:failure', 86400 * 7)  # 7 days TTL
    except Exception:
        # Silently ignore monitoring errors — don't crash task handler
        pass
