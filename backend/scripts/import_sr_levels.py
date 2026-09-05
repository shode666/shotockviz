"""Import Support/Resistance levels from a manually-exported JSON file.

bd:features-2026-09 slice 1 (DB + import only — Telegram/alerts/gold/crypto are
OUT of scope for this script, see outputs/features-2026-09/00-sara-sr-schema.md).

Expected source shape (per symbol):
    {
      "SYMBOL": {
        "lines": [
          {"tag": str, "price": float, "type": "support"|"resistance", "color": "#hex",
           "startX": ..., "startY": ..., "endX": ..., "endY": ...},
          ...
        ],
        "supportTags": [...],
        "resistanceTags": [...]
      },
      ...
    }
Only `symbol`, `price`, `type`, `tag`, `color` are stored — pixel coordinates
(startX/startY/endX/endY) and the top-level *Tags arrays are dropped on import
(user-confirmed decision: chart draws lines from `price` alone, coords are a
dead artifact of the export screen).

Known defect: the raw file has been observed with a stray `"` immediately
before the file's final closing `}` (breaks naive json.loads). This script
attempts exactly one targeted fix — strip that specific stray quote — and
re-parses. Anything else that still fails to parse aborts loudly; no other
silent fix is attempted (a different defect shape means the file changed and
needs a human to look at it).

Re-run semantics: idempotent. In one transaction, deletes only rows with
source='manual_import' then bulk-inserts the freshly parsed rows — rows with
source='auto_pivot' or 'user_created' are never touched (user-confirmed
decision, outputs/features-2026-09/00-sara-sr-schema.md §4.1).

Usage (inside backend container, cwd /app — precedent: scripts/seed_history.py):
    python -m scripts.import_sr_levels
    python -m scripts.import_sr_levels --path /app/data/sr_levels/buy-sale-line.json

Expected file location: place the exported JSON at
    backend/data/sr_levels/buy-sale-line.json
on the host. The whole `backend/` directory is bind-mounted to `/app` in the
backend container (docker-compose.dev.yml `backend.volumes: ./backend:/app`),
so the file becomes visible in-container with no new volume mount needed.
Use --path to point at a different location.
"""
import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, insert

from core.database import AsyncSessionLocal
from models.sr_level import SRLevel

SOURCE = "manual_import"
VALID_TYPES = {"support", "resistance"}

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "sr_levels", "buy-sale-line.json",
)

# Matches a `"` that sits directly before the file's very last `}` — i.e.
# only whitespace (if any) separates the quote from a closing brace, and that
# brace is the end of the entire string. Does not match any other quote in
# the document (every other quote is followed by real JSON content, not just
# trailing whitespace + EOF).
_TRAILING_DEFECT_RE = re.compile(r'"(?=\s*\}\s*\Z)')


def strip_json_defect(raw: str) -> str:
    """Remove the known stray-quote defect from the tail of the raw file.

    No-op (returns `raw` unchanged) if the pattern isn't present.
    """
    return _TRAILING_DEFECT_RE.sub("", raw, count=1)


def parse_sr_json(raw: str) -> dict:
    """Parse raw file content, applying the known trailing-quote defect fix once if needed."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as first_err:
        fixed = strip_json_defect(raw)
        if fixed == raw:
            raise ValueError(
                "buy-sale-line.json failed to parse and no known defect pattern "
                f"matched (json error: {first_err})"
            ) from first_err
        try:
            return json.loads(fixed)
        except json.JSONDecodeError as second_err:
            raise ValueError(
                "buy-sale-line.json still failed to parse after stripping the "
                f"known trailing-quote defect (json error: {second_err}). File "
                "shape may have changed — inspect manually before re-running."
            ) from second_err


@dataclass
class ImportStats:
    symbols_seen: int = 0
    rows_valid: int = 0
    rows_skipped: int = 0
    skipped_examples: list[str] = field(default_factory=list)


def _invalid_line_reason(line: object) -> str | None:
    """Return why a raw `lines[]` entry is invalid, or None if it's fine."""
    if not isinstance(line, dict):
        return "not an object"
    price = line.get("price")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return f"price invalid ({price!r})"
    level_type = line.get("type")
    if level_type not in VALID_TYPES:
        return f"type invalid ({level_type!r})"
    return None


def validate_and_flatten(data: dict) -> tuple[list[dict], ImportStats]:
    """Flatten the {symbol: {lines: [...]}} shape into row dicts, skipping bad rows.

    Never raises on a single bad row — logs + skips it and keeps going
    (per spec: "invalid → log + skip + สรุปจำนวนตอนจบ (ไม่ abort ทั้ง batch)").
    Only raises if the top-level shape itself isn't a dict.
    """
    if not isinstance(data, dict):
        raise ValueError(f"top-level JSON must be an object, got {type(data).__name__}")

    stats = ImportStats()
    rows: list[dict] = []

    for symbol, payload in data.items():
        stats.symbols_seen += 1
        lines = payload.get("lines") if isinstance(payload, dict) else None
        if not isinstance(lines, list):
            stats.rows_skipped += 1
            if len(stats.skipped_examples) < 20:
                stats.skipped_examples.append(f"{symbol}: missing/invalid 'lines' list")
            continue

        for i, line in enumerate(lines):
            reason = _invalid_line_reason(line)
            if reason:
                stats.rows_skipped += 1
                if len(stats.skipped_examples) < 20:
                    stats.skipped_examples.append(f"{symbol}[{i}]: {reason}")
                continue

            rows.append({
                "symbol": symbol,
                "price": float(line["price"]),
                "level_type": line["type"],
                "tag": line.get("tag"),
                "color": line.get("color"),
                "source": SOURCE,
            })
            stats.rows_valid += 1

    return rows, stats


async def import_rows(rows: list[dict]) -> None:
    """Wipe existing manual_import rows + bulk-insert new ones, in one transaction."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(delete(SRLevel).where(SRLevel.source == SOURCE))
            if rows:
                await session.execute(insert(SRLevel), rows)


async def run(path: str) -> None:
    print(f"Reading {path}")
    with open(path, encoding="utf-8") as f:
        raw = f.read()

    data = parse_sr_json(raw)
    rows, stats = validate_and_flatten(data)

    print(f"Symbols seen: {stats.symbols_seen}")
    print(f"Rows valid:   {stats.rows_valid}")
    print(f"Rows skipped: {stats.rows_skipped}")
    if stats.skipped_examples:
        print("Skipped examples (up to 20):")
        for ex in stats.skipped_examples:
            print(f"  - {ex}")

    await import_rows(rows)
    print(
        f"✅ Imported {stats.rows_valid} sr_levels rows (source='{SOURCE}') "
        f"across {stats.symbols_seen} symbols"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import S/R levels from a manually-exported JSON file "
                     "(wipes+reloads source='manual_import' rows only)"
    )
    parser.add_argument(
        "--path", default=DEFAULT_PATH,
        help=f"Path to buy-sale-line.json (default: {DEFAULT_PATH})",
    )
    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"❌ File not found: {args.path}")
        print("   Place the exported JSON there, or pass --path <file>.")
        sys.exit(1)

    asyncio.run(run(args.path))


if __name__ == "__main__":
    main()
