"""AI Chat assistant — powered by Ollama (local LLM) with portfolio context injection."""
from __future__ import annotations
import asyncio
import json
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx
from pydantic import BaseModel

from core.config import settings
from core.database import get_db
from core.logger import get_logger
from models.user import User
from models.portfolio import Transaction
from models.watchlist import WatchlistItem
from api.middleware.auth import get_current_user_optional
from services import stock_service

router = APIRouter(prefix="/api/ai", tags=["ai"])
logger = get_logger(__name__)

OLLAMA_MODEL = "llama3.2"  # fast, good for analysis; user can override


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    symbol: str | None = None          # current chart symbol (for context)
    include_portfolio: bool = True
    model: str = OLLAMA_MODEL
    stream: bool = True


# ── Context builder helpers ───────────────────────────────────────────────

async def _fetch_quote_context(symbol: str | None) -> str:
    """Fetch and format stock quote for LLM context.

    Args:
        symbol: Stock symbol (must not be None)

    Returns:
        Formatted quote text, or empty string if unavailable
    """
    if not symbol:
        return ""

    try:
        from core import cache_keys
        import json as _json
        r = await stock_service.get_redis()

        # Try quote from cache first (sub-ms)
        cached_quote = await r.get(cache_keys.quote(symbol))
        if not cached_quote:
            # Cache miss: trigger background fetch (non-blocking)
            asyncio.create_task(stock_service._cache_quote_background(symbol))
            return ""

        quote_data = _json.loads(cached_quote)
        return (
            f"\nข้อมูลหุ้น {symbol} ณ ปัจจุบัน:"
            f"\n  ราคา: {quote_data.get('price', 0):.2f}  เปลี่ยนแปลง: {quote_data.get('change', 0):+.2f} ({quote_data.get('change_pct', 0):+.2f}%)"
            f"\n  Open: {quote_data.get('open')}  High: {quote_data.get('high')}  Low: {quote_data.get('low')}  Volume: {quote_data.get('volume', 0):,}"
        )
    except Exception:
        return ""


async def _fetch_fundamentals_context(symbol: str | None) -> str:
    """Fetch and format stock fundamentals for LLM context.

    Args:
        symbol: Stock symbol (must not be None)

    Returns:
        Formatted fundamentals text, or empty string if unavailable
    """
    if not symbol:
        return ""

    try:
        from core import cache_keys
        import json as _json
        from models.schemas import StockFundamentals

        r = await stock_service.get_redis()

        # Try fundamentals from cache first (sub-ms)
        cached_fund = await r.get(cache_keys.fundamentals(symbol))
        if cached_fund:
            fundamentals = StockFundamentals(**_json.loads(cached_fund))
        else:
            # Fallback to 3s capped fetch
            try:
                fundamentals = await asyncio.wait_for(
                    stock_service.fetch_stock_fundamentals(symbol), timeout=3.0
                )
            except (asyncio.TimeoutError, Exception):
                return ""

        if not fundamentals:
            return ""

        f_parts = []
        if fundamentals.pe_ratio:
            f_parts.append(f"P/E={fundamentals.pe_ratio:.1f}")
        if fundamentals.pb_ratio:
            f_parts.append(f"P/B={fundamentals.pb_ratio:.1f}")
        if fundamentals.eps:
            f_parts.append(f"EPS={fundamentals.eps:.2f}")
        if fundamentals.dividend_yield:
            f_parts.append(f"Div={fundamentals.dividend_yield:.2f}%")
        if fundamentals.market_cap:
            cap = fundamentals.market_cap
            cap_str = f"{cap/1e12:.2f}T" if cap > 1e12 else f"{cap/1e9:.1f}B" if cap > 1e9 else f"{cap/1e6:.0f}M"
            f_parts.append(f"Mkt Cap={cap_str}")

        return f"  Fundamentals: {', '.join(f_parts)}" if f_parts else ""
    except Exception:
        return ""


async def _fetch_portfolio_context(user: User | None, db: AsyncSession) -> str:
    """Fetch and format user portfolio for LLM context.

    Args:
        user: Current user (may be None)
        db: Database session

    Returns:
        Formatted portfolio text, or empty string if no portfolio
    """
    if not user:
        return ""

    try:
        result = await db.execute(
            select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.date)
        )
        txns = result.scalars().all()
        if not txns:
            return ""

        holdings: dict[str, float] = {}
        for t in txns:
            mult = 1 if t.type.value == "BUY" else -1
            holdings[t.symbol] = holdings.get(t.symbol, 0) + t.qty * mult

        active = {s: q for s, q in holdings.items() if q > 0.001}
        if not active:
            return ""

        ctx_lines = [f"\nพอร์ตปัจจุบันของผู้ใช้ ({len(active)} หลักทรัพย์):"]
        for sym, qty in list(active.items())[:10]:
            ctx_lines.append(f"  {sym}: {qty:,.0f} หน่วย")

        return "\n".join(ctx_lines)
    except Exception:
        return ""


async def _fetch_watchlist_context(user: User | None, db: AsyncSession) -> str:
    """Fetch and format user watchlist for LLM context.

    Args:
        user: Current user (may be None)
        db: Database session

    Returns:
        Formatted watchlist text, or empty string if no watchlist
    """
    if not user:
        return ""

    try:
        wres = await db.execute(
            select(WatchlistItem.symbol).where(WatchlistItem.user_id == user.id).limit(10)
        )
        wsyms = [r[0] for r in wres.all()]
        if not wsyms:
            return ""
        return f"\nWatchlist: {', '.join(wsyms)}"
    except Exception:
        return ""


async def _build_context(
    user: User | None,
    symbol: str | None,
    db: AsyncSession,
) -> str:
    """Build rich context string for the LLM system prompt.

    Fetches quote, fundamentals, portfolio, and watchlist data.
    Uses cache-only reads to avoid blocking chat responses.

    Args:
        user: Current user (may be None for guests)
        symbol: Current chart symbol (optional)
        db: Database session

    Returns:
        Complete context string for LLM system prompt
    """
    ctx_parts = [
        "คุณคือผู้ช่วยการลงทุนส่วนตัว สำหรับตลาดหุ้นไทย (SET) และสหรัฐฯ (US).",
        "ตอบเป็นภาษาไทยหรืออังกฤษตามที่ผู้ใช้ถาม ใช้ภาษากระชับ ชัดเจน และไม่ต้องมีคำนำยาวๆ",
        "ห้ามแนะนำการซื้อ/ขายหลักทรัพย์โดยตรง แต่สามารถวิเคราะห์ข้อมูลและอธิบาย indicator ได้",
        f"วันที่ปัจจุบัน: {date.today().isoformat()}",
    ]

    # Fetch stock quote and fundamentals (cache-first, non-blocking)
    quote_ctx = await _fetch_quote_context(symbol)
    if quote_ctx:
        ctx_parts.append(quote_ctx)

    fund_ctx = await _fetch_fundamentals_context(symbol)
    if fund_ctx:
        ctx_parts.append(fund_ctx)

    # Fetch user portfolio and watchlist
    portfolio_ctx = await _fetch_portfolio_context(user, db)
    if portfolio_ctx:
        ctx_parts.append(portfolio_ctx)

    watchlist_ctx = await _fetch_watchlist_context(user, db)
    if watchlist_ctx:
        ctx_parts.append(watchlist_ctx)

    return "\n".join(ctx_parts)


# ── Streaming chat endpoint ────────────────────────────────────────────────

@router.post("/chat")
async def chat(
    body: ChatRequest,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Chat with AI assistant. Streams response via SSE."""
    if not settings.ollama_url:
        raise HTTPException(
            status_code=503,
            detail="AI assistant ยังไม่พร้อมใช้งาน กรุณาตั้งค่า OLLAMA_URL ใน .env"
        )

    context = await _build_context(user, body.symbol, db)

    # Build message list with system prompt
    messages = [{"role": "system", "content": context}]
    messages += [{"role": m.role, "content": m.content} for m in body.messages]

    ollama_payload = {
        "model": body.model,
        "messages": messages,
        "stream": body.stream,
        "options": {
            "num_predict": 600,    # cap response length → faster completion
            "temperature": 0.7,
            "num_ctx": 4096,       # context window
        },
    }

    if not body.stream:
        # Non-streaming: return full response
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=120.0, write=15.0, pool=5.0)
            ) as client:
                resp = await client.post(
                    f"{settings.ollama_url}/api/chat",
                    json=ollama_payload,
                )
                if resp.status_code != 200:
                    raise HTTPException(status_code=502, detail="Ollama request failed")
                data = resp.json()
                return {"content": data.get("message", {}).get("content", "")}
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="Ollama ยังไม่พร้อม — กำลังโหลดโมเดลอยู่ กรุณารอสักครู่")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Ollama ตอบช้าเกินไป (timeout 120s)")

    # Streaming: proxy Ollama stream as Server-Sent Events
    async def stream_ollama():
        # ① Flush headers immediately — browser gets HTTP 200 + content-type
        #    right away instead of waiting for the first Ollama token.
        yield f"data: {json.dumps({'content': '', 'done': False})}\n\n"

        # ② Large read timeout: Ollama may spend 30-120s loading the model
        #    into RAM on first request. Per-chunk timeout (read) is 300 s.
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=5.0)
        ) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{settings.ollama_url}/api/chat",
                    json=ollama_payload,
                ) as resp:
                    if resp.status_code != 200:
                        yield f"data: {json.dumps({'error': f'Ollama error {resp.status_code}', 'done': True})}\n\n"
                        return

                    # ③ Keepalive heartbeat: if Ollama hasn't sent a token in
                    #    15 s (model still loading), send an SSE comment so the
                    #    connection doesn't time out at Caddy/browser level.
                    aiter = resp.aiter_lines().__aiter__()
                    while True:
                        try:
                            line = await asyncio.wait_for(
                                aiter.__anext__(), timeout=15.0
                            )
                        except asyncio.TimeoutError:
                            # Not a data event — just keeps TCP alive
                            yield ": keepalive\n\n"
                            continue
                        except StopAsyncIteration:
                            break

                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            content = chunk.get("message", {}).get("content", "")
                            done = chunk.get("done", False)
                            yield f"data: {json.dumps({'content': content, 'done': done})}\n\n"
                            if done:
                                break
                        except json.JSONDecodeError:
                            continue

            except httpx.ConnectError:
                yield f"data: {json.dumps({'error': 'Ollama ยังไม่พร้อม — กำลังโหลดโมเดลอยู่ กรุณารอสักครู่', 'done': True})}\n\n"
            except httpx.TimeoutException:
                yield f"data: {json.dumps({'error': 'Ollama ใช้เวลานานเกินไป — กรุณาลองใหม่', 'done': True})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

    return StreamingResponse(
        stream_ollama(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Available models endpoint ──────────────────────────────────────────────

@router.get("/models")
async def list_models():
    """List available Ollama models."""
    if not settings.ollama_url:
        return {"models": [], "available": False}
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.ollama_url}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m["name"] for m in data.get("models", [])]
                return {"models": models, "available": True}
    except Exception:
        pass
    return {"models": [], "available": False}


# ── Quick analysis endpoint (non-streaming) ────────────────────────────────

@router.post("/analyze/{symbol}")
async def analyze_stock(
    symbol: str,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Get quick AI analysis of a stock symbol."""
    if not settings.ollama_url:
        raise HTTPException(status_code=503, detail="Ollama not configured")

    context = await _build_context(user, symbol.upper(), db)
    prompt = (
        f"วิเคราะห์หุ้น {symbol.upper()} แบบสั้นๆ จากข้อมูลที่มี "
        "ครอบคลุม: แนวโน้มราคา, ระดับ valuation, จุดเสี่ยง และมุมมองเบื้องต้น "
        "ตอบภายใน 3-4 ประโยค"
    )

    messages = [
        {"role": "system", "content": context},
        {"role": "user", "content": prompt},
    ]

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=15.0, read=120.0, write=15.0, pool=5.0)
    ) as client:
        resp = await client.post(
            f"{settings.ollama_url}/api/chat",
            json={"model": OLLAMA_MODEL, "messages": messages, "stream": False},
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Ollama error")
        data = resp.json()
        return {"symbol": symbol.upper(), "analysis": data.get("message", {}).get("content", "")}
