"""Alembic Environment Configuration."""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ── Add backend root to path so imports resolve ──────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# ── Import all models so Alembic can detect schema changes ───────────────────
from core.config import settings
from core.database import Base  # noqa: F401 — Base must be imported first

import models.user              # noqa: F401
import models.stock             # noqa: F401
import models.watchlist         # noqa: F401
import models.portfolio         # noqa: F401
import models.alert             # noqa: F401
import models.drawing           # noqa: F401
import models.symbol_mapping    # noqa: F401  — V2: symbol provider mapping
import models.corporate_action  # noqa: F401  — V2: dividend/split events
import models.financial_history # noqa: F401  — V2: 10-year financial scorecard
import models.earnings_event    # noqa: F401  — V2: EPS surprise tracker
import models.sr_level          # noqa: F401  — bd:features-2026-09: S/R levels

# ── Alembic Config ────────────────────────────────────────────────────────────
config = context.config

# Override sqlalchemy.url with value from settings (reads .env automatically)
config.set_main_option("sqlalchemy.url", settings.sync_database_url)

# Set up Python logging from alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Provide target metadata for --autogenerate support
target_metadata = Base.metadata


# ── Offline migration (generate SQL script without DB connection) ─────────────
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL and not an Engine; calls to
    context.execute() emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ── Online migration (run against live DB) ────────────────────────────────────
def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates an Engine and associates a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
