"""
bd:deps-2026-09 iter2 (CHRIS-16/Q-10) — live-ASGI-server integration test
for the proxy-header-trust boundary `TestClient`-based tests structurally
cannot see: uvicorn/gunicorn's OWN `forwarded_allow_ips` (not this app's
`TRUSTED_PROXIES` allowlist) rewrites `request.client.host` from a spoofed
`X-Forwarded-For` BEFORE the application layer ever runs. `gunicorn.conf.py`
derives `forwarded_allow_ips` from `TRUSTED_PROXIES` (same var
`core/config.py` reads) — this test boots a real `gunicorn` + UvicornWorker
subprocess (matching prod/ghcr compose) with `TRUSTED_PROXIES` unset and
proves 6 distinct spoofed XFF values collapse to ONE bucket (the real
loopback peer), 6th request = 429 in the standard error envelope.

Rightmost-untrusted-hop parsing is unit-covered by
`test_rightmost_untrusted_hop_unit.py`; this file only re-proves the
ASGI-server boundary itself (CHRIS-16/Q-10's original miss).

Marked `integration` (deselected by `backend/pytest.ini`'s default
`-m "not integration"`). Run explicitly:
    pytest backend/tests/test_rate_limit_proxy_boundary_live.py -m integration -v
"""
import os
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import pytest
import redis as redis_sync

pytestmark = pytest.mark.integration

BACKEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
LOGIN_PATH = "/api/v1/auth/google"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(port: int, proc: subprocess.Popen, logfile, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            logfile.seek(0)
            raise RuntimeError(f"gunicorn exited early (rc={proc.returncode}):\n{logfile.read().decode(errors='replace')}")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=5.0, trust_env=False).status_code < 500:
                return
        except Exception:  # noqa: BLE001 - readiness poll, retry
            pass
        time.sleep(0.25)
    raise RuntimeError(f"gunicorn did not become ready within {timeout}s")


def test_trusted_proxies_unset_spoofed_xff_collapses_to_one_bucket():
    """TRUSTED_PROXIES unset (default) -> gunicorn.conf.py derives
    forwarded_allow_ips="" -> uvicorn trusts nothing, including the real
    loopback peer -> 6 requests with 6 DIFFERENT spoofed XFF values must
    all resolve to the real peer's identity (127.0.0.1) -> ONE bucket ->
    6th request is 429 in the standard {data:null,meta:{error}} envelope."""
    port = _free_port()
    r = redis_sync.Redis.from_url(REDIS_URL)
    r.delete("rate:login:127.0.0.1")
    for i in range(1, 7):
        r.delete(f"rate:login:10.77.77.{i}")

    env = {**os.environ, "JWT_SECRET_KEY": "dev-only-secret-key-0123456789abcdef"}
    env.pop("TRUSTED_PROXIES", None)
    logfile = tempfile.TemporaryFile(mode="w+b")
    proc = subprocess.Popen(
        [sys.executable, "-m", "gunicorn", "main:app", "-w", "1", "-k", "uvicorn.workers.UvicornWorker",
         "--bind", f"127.0.0.1:{port}"],
        cwd=BACKEND_DIR, env=env, stdout=logfile, stderr=subprocess.STDOUT,
    )
    try:
        _wait_ready(port, proc, logfile)
        statuses, bodies = [], []
        for i in range(1, 7):
            resp = httpx.post(
                f"http://127.0.0.1:{port}{LOGIN_PATH}",
                json={"credential": "not-a-real-token"},
                headers={"X-Forwarded-For": f"10.77.77.{i}"},
                timeout=10, trust_env=False,
            )
            statuses.append(resp.status_code)
            bodies.append(resp.json())
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        logfile.close()

    assert statuses[-1] == 429, f"6th request should be rate-limited (all 6 spoofed XFF collapse to peer) — {statuses}"
    assert bodies[-1]["data"] is None and "error" in bodies[-1]["meta"], f"429 must use the standard envelope — {bodies[-1]}"
    buckets_touched = sum(1 for i in range(1, 7) if r.exists(f"rate:login:10.77.77.{i}"))
    assert buckets_touched == 0, f"expected zero per-spoofed-IP buckets — {buckets_touched}/6 created (CHRIS-16/Q-10 regression)"
    assert r.get("rate:login:127.0.0.1") is not None, "shared real-peer bucket should exist"
