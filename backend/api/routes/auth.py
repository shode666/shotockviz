import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from core.security import create_access_token, decode_access_token
from core.config import settings
from models.user import User
from models.schemas import TokenResponse, UserResponse, GoogleAuthRequest
from api.middleware.auth import bearer_scheme
from fastapi.security import HTTPAuthorizationCredentials
from core.logger import get_logger
from schemas.envelope import EnvelopingAPIRoute

logger = get_logger(__name__)

# bd:deps-2026-09 S2 (ADR-001 r3) — prefix lifted /api/auth -> /auth,
# mounted under /api/v1 in main.py. route_class = envelope wrap (ADR-002).
router = APIRouter(prefix="/auth", tags=["auth"], route_class=EnvelopingAPIRoute)

# bd:deps-2026-09 S1 (ADR-007) — POST /register, POST /login, POST /refresh,
# POST /logout removed (dead code: no frontend caller for register/login;
# refresh/logout only served the client-side token-refresh lifecycle that
# CLAUDE.md rule 5 explicitly prohibits — "NO custom token management on
# frontend"). Google One Tap (auth.py below) + the 8h access-token TTL
# (core/config.py) are the sole session mechanism now. RefreshToken model
# + table are left in place (dropping = DB schema change, out of scope);
# rows simply stop being written.


@router.post("/google", response_model=TokenResponse)
async def google_auth(body: GoogleAuthRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate with Google ID token. Auto-creates user on first login."""
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
    from google.auth import exceptions as google_exceptions

    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth not configured (GOOGLE_CLIENT_ID missing)",
        )

    try:
        # verify_oauth2_token uses a synchronous HTTP client to fetch Google's
        # public keys — run it in a thread pool so it doesn't block the event loop.
        # Cap at 5s to respect our <5s SLA; Google keys are usually cached.
        loop = asyncio.get_event_loop()
        idinfo = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: id_token.verify_oauth2_token(
                    body.credential,
                    google_requests.Request(),
                    settings.google_client_id,
                    clock_skew_in_seconds=60,
                ),
            ),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        logger.warning("Google token verification timed out")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Google authentication timed out — please try again",
        )
    except (ValueError, google_exceptions.GoogleAuthError, google_exceptions.TransportError) as e:
        logger.warning(
            "Google token verification failed",
            error=str(e),
            client_id_prefix=settings.google_client_id[:20] if settings.google_client_id else "NOT SET",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google token verification failed — please try again",
        )

    # ── Validate required claims ──────────────────────────────────────────
    email = idinfo.get("email")
    if not email or not idinfo.get("email_verified"):
        logger.warning("Google token missing verified email", claims=list(idinfo.keys()))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account must have a verified email",
        )

    name = idinfo.get("name", email.split("@")[0])

    # Find or create user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            email=email,
            password_hash="GOOGLE_OAUTH",  # No password for Google users
            display_name=name,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    access_token = create_access_token({
        "sub": str(user.id), "role": user.role.value,
        "email": user.email, "display_name": user.display_name,
        "created_at": user.created_at.isoformat(),
    })
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def get_me(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Get current authenticated user info — reads from JWT payload, no DB query."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fast path: return from JWT payload (no DB query)
    if payload.get("email") and payload.get("display_name"):
        created_at_raw = payload.get("created_at")
        created_at = datetime.fromisoformat(created_at_raw) if created_at_raw else datetime.now(timezone.utc)
        return UserResponse(
            id=int(payload["sub"]),
            email=payload["email"],
            display_name=payload["display_name"],
            role=payload["role"],
            created_at=created_at,
        )

    # Fallback for tokens issued before this change (DB lookup)
    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == int(user_id), User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


@router.get("/config")
async def get_auth_config():
    """Return public authentication configuration."""
    return {
        "google_client_id": settings.google_client_id,
    }

