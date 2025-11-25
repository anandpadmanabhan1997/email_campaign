"""
Alembic environment script that uses application settings from app.config.get_settings()
and configures the migration context accordingly. Enables SQLite batch mode for safe
ALTER operations when using SQLite.
"""
from logging.config import fileConfig
import os
import sys

from alembic import context

# Add project root to sys.path so we can import app
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# this is the Alembic Config object, which provides access to the values within the .ini file
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import application settings and metadata
from app.config import get_settings  # noqa: E402
from app.db import Base  # noqa: E402
from app import models  # noqa: E402  (ensure models are imported so metadata is populated)

settings = get_settings()

# Override sqlalchemy.url from our settings (so alembic uses same DB as app)
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode."""
    from sqlalchemy import create_engine  # local import

    database_url = config.get_main_option("sqlalchemy.url")
    connectable = create_engine(database_url)

    with connectable.connect() as connection:
        # Enable render_as_batch for SQLite to support ALTER operations safely.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()