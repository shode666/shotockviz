---
name: bench-api
description: Benchmark all ShotockViz API endpoints — measures response time, HTTP status, and size for every endpoint. Use when the user asks about API performance, slow responses, or "monitor the API". Requires the Docker stack to be running at https://localhost.
allowed-tools: Bash
argument-hint: "[symbol]"
---

# ShotockViz API Performance Benchmark

Benchmark all API endpoints and report results. Symbol defaults to NVDA if not specified.

## Steps

1. Get a fresh auth token (register test user if needed)
2. Run sequential timing against all core endpoints
3. Flag anything over 1000ms as slow, over 3000ms as critical
4. Check Docker backend logs for errors
5. Report a clean summary table

## Script to run

```bash
SYMBOL="${ARGUMENTS:-NVDA}"

# Get token
TOKEN=$(curl -sk -X POST https://localhost/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"bench@example.com","password":"BenchPass1!"}' \
  --max-time 10 | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null)

if [ -z "$TOKEN" ]; then
  curl -sk -X POST https://localhost/api/auth/register \
    -H "Content-Type: application/json" \
    -d '{"email":"bench@example.com","password":"BenchPass1!","display_name":"Bench"}' --max-time 10 > /dev/null 2>&1
  TOKEN=$(curl -sk -X POST https://localhost/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"bench@example.com","password":"BenchPass1!"}' \
    --max-time 10 | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null)
fi

python3 - "$TOKEN" "$SYMBOL" << 'PYEOF'
import subprocess, sys, time

TOKEN, SYM = sys.argv[1], sys.argv[2]
endpoints = [
    f"/api/system/ready",
    f"/api/auth/me",
    f"/api/stocks/{SYM}/quote",
    f"/api/stocks/{SYM}/history?tf=1D",
    f"/api/stocks/{SYM}/fundamentals",
    f"/api/stocks/{SYM}/news",
    f"/api/watchlists",
    f"/api/stocks/%5EGSPC/quote",
    f"/api/stocks/%5ESET/quote",
]

print(f"\nAPI Performance Benchmark  [symbol={SYM}]")
print("=" * 72)
print(f"{'Endpoint':<47} {'HTTP':>5} {'Time':>8} {'Size':>8}  Status")
print("-" * 72)

issues = []
for ep in endpoints:
    t0 = time.time()
    r = subprocess.run(
        ["curl", "-sk", "--max-time", "20",
         "-w", "%{http_code}|%{size_download}",
         "-o", "/dev/null",
         "-H", f"Authorization: Bearer {TOKEN}",
         f"https://localhost{ep}"],
        capture_output=True, text=True
    )
    elapsed = time.time() - t0
    out = r.stdout.strip()
    code, size = out.split("|") if "|" in out else (out or "???", "0")
    ms = elapsed * 1000
    if ms > 3000 or code == "000":
        flag = "❌ CRITICAL"
        issues.append(f"{ep}: {code} {ms:.0f}ms")
    elif ms > 1000:
        flag = "⚠️  SLOW"
        issues.append(f"{ep}: {code} {ms:.0f}ms")
    else:
        flag = "✅"
    print(f"  {ep:<45}  {code:>5}  {ms:>6.0f}ms  {int(size):>6}b  {flag}")

print("-" * 72)
if issues:
    print(f"\n⚠️  {len(issues)} issue(s) found:")
    for i in issues:
        print(f"   • {i}")
else:
    print("\n✅ All endpoints healthy")
PYEOF
```

After running the benchmark, also show the last 5 lines of backend logs for errors:
```bash
docker logs shotockviz-backend-1 --tail 20 2>&1 | grep -E "ERROR|WARNING|Exception|Traceback" | tail -5 || echo "(no errors in recent logs)"
```

Report the complete results to the user with analysis and recommendations.
