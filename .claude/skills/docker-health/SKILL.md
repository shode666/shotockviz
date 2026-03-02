---
name: docker-health
description: Check health of all ShotockViz Docker containers — shows status, recent errors, Redis cache hits, and Celery worker activity. Use when diagnosing Docker/container issues, services being down, or "check the stack".
allowed-tools: Bash
---

# ShotockViz Docker Stack Health Check

## Steps

1. Show container statuses
2. Check for recent errors in backend logs
3. Check Redis connectivity and cache stats
4. Check Celery worker activity
5. Summarize any issues

## Commands to run

```bash
echo "=== Container Status ==="
docker compose -f /Users/shode/development/ShotockViz/docker-compose.dev.yml ps 2>&1

echo ""
echo "=== Recent Backend Errors ==="
docker logs shotockviz-backend-1 --tail 50 2>&1 | grep -E "ERROR|CRITICAL|Exception|Traceback" | tail -10 || echo "(none)"

echo ""
echo "=== Backend Recent Activity ==="
docker logs shotockviz-backend-1 --tail 20 2>&1 | grep -v "connect_tcp\|start_tls\|send_request\|receive_response\|response_closed\|close\." | tail -15

echo ""
echo "=== Redis Cache Stats ==="
docker exec shotockviz-redis-1 redis-cli info keyspace 2>&1 || echo "(redis not accessible)"
docker exec shotockviz-redis-1 redis-cli dbsize 2>&1

echo ""
echo "=== Celery Worker Recent Tasks ==="
docker logs shotockviz-celery-worker-1 --tail 10 2>&1

echo ""
echo "=== Celery Beat Recent Schedule ==="
docker logs shotockviz-celery-beat-1 --tail 5 2>&1
```

Report findings and highlight any containers that are unhealthy or have errors.
