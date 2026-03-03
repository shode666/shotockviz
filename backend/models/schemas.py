"""Pydantic schemas for request/response validation."""
from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, EmailStr, field_validator


# ─── Auth ──────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class GoogleAuthRequest(BaseModel):
    credential: str  # Google ID token from frontend


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Stock ─────────────────────────────────────────────────────────────────

class StockSearchResult(BaseModel):
    symbol: str
    name: str
    name_th: Optional[str] = None
    market: str


class StockQuote(BaseModel):
    symbol: str
    price: float
    open: float
    high: float
    low: float
    prev_close: float
    change: float
    change_pct: float
    volume: int
    timestamp: datetime


class OHLCVBar(BaseModel):
    time: int | str  # Unix timestamp (seconds) for intraday; "YYYY-MM-DD" for daily+
    open: float
    high: float
    low: float
    close: float
    volume: int


class StockHistory(BaseModel):
    symbol: str
    timeframe: str
    bars: List[OHLCVBar]
    is_fund: bool = False  # True for Thai mutual funds — no chart data available


class StockFundamentals(BaseModel):
    symbol: str
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    eps: Optional[float] = None
    dividend_yield: Optional[float] = None
    market_cap: Optional[float] = None
    beta: Optional[float] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    avg_volume: Optional[float] = None


# ─── Watchlist ─────────────────────────────────────────────────────────────

class WatchlistCreate(BaseModel):
    name: str


class WatchlistUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None


class WatchlistItemAdd(BaseModel):
    symbol: str


class WatchlistItemOrder(BaseModel):
    symbol: str
    sort_order: int


class WatchlistReorderRequest(BaseModel):
    items: List[WatchlistItemOrder]


class WatchlistItemResponse(BaseModel):
    id: int
    symbol: str
    sort_order: int
    added_at: datetime
    # Enriched fields from live data
    price: Optional[float] = None
    change_pct: Optional[float] = None

    class Config:
        from_attributes = True


class WatchlistResponse(BaseModel):
    id: int
    name: str
    sort_order: int
    created_at: datetime
    items: List[WatchlistItemResponse] = []

    class Config:
        from_attributes = True


# ─── Portfolio ─────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    symbol: str
    type: str  # BUY or SELL
    qty: float
    price: float
    fee: float = 0.0
    currency: str = "THB"  # THB or USD
    date: date
    note: Optional[str] = None


class TransactionUpdate(BaseModel):
    qty: Optional[float] = None
    price: Optional[float] = None
    fee: Optional[float] = None
    currency: Optional[str] = None
    date: Optional[date] = None
    note: Optional[str] = None


class TransactionResponse(BaseModel):
    id: int
    symbol: str
    type: str
    qty: float
    price: float
    fee: float
    currency: str
    date: date
    note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class HoldingResponse(BaseModel):
    symbol: str
    qty: float
    avg_cost: float
    currency: str = "THB"
    current_price: Optional[float] = None
    current_value: Optional[float] = None
    unrealized_pl: Optional[float] = None
    unrealized_pl_pct: Optional[float] = None


class PortfolioAnalytics(BaseModel):
    total_value: float
    total_cost: float
    unrealized_pl: float
    unrealized_pl_pct: float
    day_change: Optional[float] = None
    holdings: List[HoldingResponse]
    has_pending_prices: bool = False


# ─── Alert ─────────────────────────────────────────────────────────────────

class AlertCreate(BaseModel):
    symbol: str
    alert_type: str
    condition: str
    value: Optional[float] = None
    channel: str = "TELEGRAM"


class AlertUpdate(BaseModel):
    condition: Optional[str] = None
    value: Optional[float] = None
    channel: Optional[str] = None


class AlertResponse(BaseModel):
    id: int
    symbol: str
    alert_type: str
    condition: str
    value: Optional[float] = None
    is_active: bool
    status: str
    channel: str
    triggered_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Drawing ───────────────────────────────────────────────────────────────

class DrawingCreate(BaseModel):
    tool_type: str
    data_json: dict
    style_json: dict


class DrawingUpdate(BaseModel):
    data_json: Optional[dict] = None
    style_json: Optional[dict] = None


class DrawingResponse(BaseModel):
    id: int
    symbol: str
    timeframe: str
    tool_type: str
    data_json: dict
    style_json: dict
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ─── News ──────────────────────────────────────────────────────────────────

class NewsItem(BaseModel):
    title: str
    url: str
    source: str
    published_at: Optional[datetime] = None
    summary: Optional[str] = None
    sentiment: Optional[str] = None  # positive, negative, neutral
    related_symbols: List[str] = []
