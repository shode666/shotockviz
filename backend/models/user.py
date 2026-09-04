from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import String, DateTime, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


class UserRole(str, PyEnum):
    guest = "guest"
    user = "user"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), default=UserRole.user, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    # bd:features-2026-09 slice 3 (Sara ADR-T2) — nullable, String(32) not
    # BigInteger: Telegram chat ids are int64 (negative for groups); the UI
    # field is a text input and we never do arithmetic on it, so string
    # avoids int64->JSON precision hazards.
    #
    # Deviation from Sara's spec (04-sara-telegram-spec.md §4): spec proposes
    # a DB-level `CheckConstraint("telegram_chat_id ~ '...'")` mirrored in
    # both the ORM model and the migration (the sr_levels precedent,
    # models/sr_level.py). `~` is Postgres's regex-match operator with NO
    # SQLite equivalent — `Base.metadata.create_all()` (backend/tests/
    # conftest.py's `test_db` fixture, in-memory SQLite) would raise
    # `sqlite3.OperationalError: near "~": syntax error` while creating the
    # `users` table, breaking every single test in the suite, not just
    # telegram ones (verified: `sqlite3.connect(':memory:').execute(...)`
    # with this exact CHECK raises that error). The regex CHECK is kept at
    # the migration layer only (Postgres-only DDL, §migration below) where
    # the real prod/dev DB is Postgres; numeric-shape validation for actual
    # writes is enforced at the Pydantic layer instead
    # (`models/schemas.py` `UserSettingsUpdate`, `pattern=r"^-?\d{1,20}$"`) —
    # the sole write path (`PATCH /api/v1/auth/settings`) already validates
    # before this column is ever set, so the invariant is not weakened.
    telegram_chat_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    watchlists: Mapped[list] = relationship("Watchlist", back_populates="user", cascade="all, delete-orphan")
    transactions: Mapped[list] = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    alerts: Mapped[list] = relationship("Alert", back_populates="user", cascade="all, delete-orphan")
    drawings: Mapped[list] = relationship("Drawing", back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    @property
    def is_valid(self) -> bool:
        from datetime import timezone
        return self.revoked_at is None and self.expires_at > datetime.now(timezone.utc)
