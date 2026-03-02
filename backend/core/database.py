from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from core.config import settings


engine = create_async_engine(
    settings.database_url,
    pool_size=20,
    max_overflow=10,        # allow a bit more headroom during burst traffic
    pool_pre_ping=True,
    pool_timeout=5,         # fail fast (default 30 s was too long, cascading failures)
    pool_recycle=1800,      # recycle connections every 30 min to avoid stale sockets
    pool_use_lifo=True,     # prefer recently used connections → fewer idle sockets open
    echo=settings.debug,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    """Dependency that provides an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables():
    """Create all tables (for development/initial setup)."""
    # Import models so they are registered with Base
    from models import user, stock, watchlist, portfolio, alert, drawing, ohlcv  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables():
    """Drop all tables (use with caution)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
