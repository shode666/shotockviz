# Celery Monitoring Implementation — Quick Reference

**Date:** 2026-03-03
**Project:** ShotockViz v0.1.3 BETA
**Status:** All backend changes complete; CQRS architecture with 10 Celery workers

---

## What Was Changed

### 1. Signal Handlers for Task Metrics

**File:** `/backend/workers/__init__.py` (NEW)

```python
from celery.signals import task_success, task_failure, task_prerun

# Registered at import time
@task_prerun.connect
def task_prerun_handler(task_id, task, *args, **kwargs):
    _task_start_times[task_id] = time.time()

@task_success.connect
def task_success_handler(sender, task_id, **kwargs):
    # Increments celery:stats:success
    # Sets celery:stats:last_success_at
    # Records elapsed time

@task_failure.connect
def task_failure_handler(sender, task_id, exception, **kwargs):
    # Increments celery:stats:failure
    # Sets celery:stats:last_failure_at
    # Stores exception message
```

### 2. API Endpoint for Monitoring

**File:** `/backend/api/routes/system.py`
**Route:** `GET /api/system/celery-stats`

```python
@router.get("/system/celery-stats")
async def get_celery_stats():
    """Returns Celery task success/failure stats from Redis."""
    return {
        "success_count": int(success or 0),
        "failure_count": int(failure or 0),
        "last_success_at": last_success.decode(),
        "last_failure_at": last_failure.decode(),
        "last_error": last_error.decode(),
        "last_success_elapsed": last_elapsed.decode(),
    }
```

### 3. Enhanced Task Logging

**File:** `/backend/workers/price_fetcher.py`

The unified round-robin `fetch_prices` function (and backup `fetch_overview_prices`) now include:

```python
start = time.time()
try:
    # ... task execution ...
    elapsed = time.time() - start
    logger.info("Task complete", elapsed_sec=f'{elapsed:.2f}')
except Exception as exc:
    elapsed = time.time() - start
    logger.error("Task failed", error=str(exc), elapsed_sec=f'{elapsed:.2f}')
```

### 4. Flower UI Service

**File:** `/docker-compose.dev.yml`

```yaml
flower:
  image: mher/flower:2.0
  command: celery --broker=redis://redis:6379/0 flower --port=5555
  ports:
    - "5555:5555"
  depends_on:
    - redis
  networks:
    - stockviz-net
```

**File:** `/caddy/Caddyfile.dev`

```
@flower path /flower*
reverse_proxy @flower flower:5555
```

---

## How to Use

### Check Task Statistics (JSON)

```bash
curl https://localhost/api/system/celery-stats | jq .
```

Sample output:
```json
{
  "success_count": 156,
  "failure_count": 2,
  "last_success_at": "2026-03-02T15:34:12.567890+00:00",
  "last_failure_at": "2026-03-02T14:20:00.123456+00:00",
  "last_error": "ConnectionError: Failed to fetch NVDA from yfinance",
  "last_success_elapsed": "2.45"
}
```

### Monitor Live Tasks (Web UI)

1. Open browser: `https://localhost/flower`
2. Observe:
   - Active task count
   - Worker status
   - Task history with execution time
   - Retry attempts and backoff

### Check Backend Logs

```bash
docker-compose -f docker-compose.dev.yml logs -f backend

# Look for lines like:
# [slot=SET] Round-robin price fetch: 12 symbols fetched, elapsed_sec=2.34
# [slot=US] Round-robin price fetch: 8 symbols fetched, elapsed_sec=1.89
# [slot=Asia] Round-robin price fetch: 20 symbols fetched, elapsed_sec=3.12
```

### Check Celery Worker Logs

```bash
docker-compose -f docker-compose.dev.yml logs -f celery-worker

# Look for successful task execution and signal handler activity
```

---

## Architecture Decisions

### Why Signals Instead of Task Decorators?

- **Non-intrusive:** Don't modify task code
- **Centralized:** All monitoring logic in one module
- **Maintainable:** Easy to add metrics without touching 100+ task functions

### Why Redis (Not a Database)?

- **Fast:** Sub-millisecond lookups
- **Ephemeral:** Automatic cleanup via TTL
- **Scalable:** No need for table maintenance
- **Simple:** No schema migrations

### Why 7-Day TTL?

- **Window:** Covers a full week of operations
- **Storage:** Prevents unbounded Redis growth
- **Cost:** Negligible memory overhead
- **Insight:** Enough history to spot patterns

### Why Sync Redis in Signal Handlers?

- **Signals are synchronous:** Can't await in handler
- **No choice:** Celery doesn't await signals
- **Safe:** Error-handling is silent; won't crash tasks

---

## Monitoring Best Practices

### Check Daily

```bash
# Verify success count is growing
curl https://localhost/api/system/celery-stats | jq .success_count

# Should increase every minute during market hours
```

### Alert on Failures

```bash
# Parse failure_count; alert if > 0
curl https://localhost/api/system/celery-stats | jq '.failure_count'

# Check last_error for troubleshooting
curl https://localhost/api/system/celery-stats | jq '.last_error'
```

### Track Performance

```bash
# Monitor average execution time
curl https://localhost/api/system/celery-stats | jq '.last_success_elapsed'

# Should be ~1-5 seconds depending on network
# If > 10s, investigate yfinance rate limiting or network latency
```

---

## Deployment Checklist

- [ ] Docker images rebuilt
- [ ] `docker-compose up -d` executed
- [ ] `docker-compose logs celery-worker` shows no errors
- [ ] Celery stats endpoint responds: `curl https://localhost/api/system/celery-stats`
- [ ] Flower UI loads: `https://localhost/flower`
- [ ] Price fetchers executed (check logs): `success_count > 0`
- [ ] No task failures visible in Flower UI

---

## Troubleshooting

### Endpoint returns 0 success_count

**Cause:** Tasks haven't run yet (market hours only)  
**Fix:** Wait for market open, or trigger manually via Celery Beat schedule

### Flower shows 0 workers connected

**Cause:** Celery worker not started or Redis unreachable  
**Fix:** Check `docker-compose ps` and `docker-compose logs celery-worker`

### Signal handlers throwing errors

**These are silenced by design.** Check Docker logs:
```bash
docker-compose logs backend | grep "celery:stats"
```

### Redis unavailable during signal handler

**Also silenced by design.** The handler will:
1. Catch the exception
2. Log nothing (silent failure)
3. Continue task execution

This is intentional to prevent Celery tasks from crashing if Redis is temporarily down.

---

## Further Reading

- [Celery Signals Documentation](https://docs.celeryproject.org/en/stable/userguide/signals.html)
- [Flower Documentation](https://flower.readthedocs.io/)
- [ShotockViz Architecture Guide](./CLAUDE.md)
- [ShotockViz Changelog](./changelog.md)
