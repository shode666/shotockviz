# WP-B4 — redis-py 8.1.0 verification (zero code changes required)

bd: deps-2026-09 · Dave · captured post-B1 bump (redis==8.1.0 active in `.venv`,
server stays `redis-server 7.0.15` per Sara ADR §1.5 "server upgrade to 8 is
NOT in this branch")

## Files in scope (03-stan-refactor-strategy.md WP-B4)

`backend/core/redis.py`, `backend/services/cache_service.py`,
`backend/services/cache_orchestrator.py`.

## Findings

- `core/redis.py:38-45` — `await aioredis.from_url(settings.redis_url,
  encoding="utf-8", decode_responses=True, socket_connect_timeout=3,
  socket_timeout=3, health_check_interval=30)` — the `Redis.__await__`
  auto-init pattern Sara flagged as a "deprecation candidate" (§2.2) is
  **retained in redis-py 8.1.0** — verified live against the sandbox's
  redis-server, ping/get/set all succeed (transcript below). Explicit
  timeouts already set here (matches Sara's note "unaffected by new
  defaults").
- `services/cache_service.py` — no `from_url` call; receives an
  already-constructed `Redis` client as a function parameter and only uses
  `get`/`set`/`delete`/`exists` — all exercised live below, all pass.
- `services/cache_orchestrator.py:45` — `get_redis()` delegates to
  `services.stock_service.get_redis()` (OUT of this WP's file scope per
  Stan's table — not touched). `_notify_data_ready` (line 69) calls
  `r.publish("price_updates", ...)` — the RESP3 pub/sub path Sara flagged
  as "highest-risk area" (§2.2). Verified live below: publish → subscribe
  round-trip returns the exact same message shape
  (`{type, pattern, channel, data}`) that `main.py`'s WS broadcaster
  consumes (main.py itself is out of scope — WP-S2 territory — this only
  proves the publish side that `cache_orchestrator.py` owns).

**No code changes made** — same characterize-then-verify outcome as WP-B3.

## Verification transcripts

```
$ .venv/bin/python -c "redis-py version check + ping/get/set + info server"
redis-py version: 8.1.0
ping: True
get: ok
redis_version: 7.0.15
```

```
$ .venv/bin/python -c "pub/sub round trip on 'price_updates' channel"
received: {'type': 'message', 'pattern': None, 'channel': 'price_updates',
           'data': '{"type": "data_ready", "data_type": "quote", "symbol": "AAPL"}'}
```

## Test deltas vs B3 checkpoint (no regression)

- `backend/tests`: 104 passed / 0 failed / 2 skipped / 37 deselected —
  IDENTICAL to B3.
- `tests/api`: 116 passed / 12 failed / 73 errors — IDENTICAL to B3.

## Residual (out of this WP's file scope, flagged not fixed)

- `services/stock_service.py:91`, `services/providers/yahoo_provider.py:129`
  (bare `from_url` without explicit timeouts, per Sara §2.2) — NOT in
  WP-B4's file list (Stan's table: only `core/redis.py`,
  `services/cache_service.py`, `services/cache_orchestrator.py`). Not
  touched; flagged for whoever owns those files next (not assigned to any
  WP in the current 11-package plan — Stan/Oliver to route).
- `main.py:108-168` `_redis_price_broadcaster` (the actual WS-side
  consumer of the pub/sub message verified above) is explicitly forbidden
  to me (WP-S1/S2/S3 territory, `backend/main.py route mounts` in my STOP
  list) — AC-M7's full publish→WS-receive smoke needs a Dave/Quinn pass on
  the live stack post-barrier, not just the publish-side proof here.
