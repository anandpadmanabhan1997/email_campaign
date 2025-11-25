"""
app/core/alembic_runner.py

Programmatic Alembic runner that applies migrations (alembic upgrade head)
using the application's Settings (DATABASE_URL). Safe to call on process startup.

This is intentionally idempotent and will raise on failure so the process fails-fast
if migrations cannot be applied.
"""
import os
import logging
from alembic.config import Config
from alembic import command

from .config import get_settings

logger = logging.getLogger(__name__)


def run_migrations():
    """
    Run 'alembic upgrade head' programmatically using the project's alembic.ini.
    Looks for alembic.ini at the repository root (two levels above this module).
    """
    settings = get_settings()

    # repo root is two levels up from app/core/
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    alembic_ini = os.path.join(repo_root, "alembic.ini")
    if not os.path.exists(alembic_ini):
        # fallback: current working dir
        alembic_ini = os.path.join(os.getcwd(), "alembic.ini")

    if not os.path.exists(alembic_ini):
        logger.error("alembic.ini not found (expected at %s)", alembic_ini)
        raise FileNotFoundError(f"alembic.ini not found at {alembic_ini}")

    cfg = Config(alembic_ini)
    # ensure the alembic runner uses the same DB URL as the application
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

    logger.info("Applying alembic migrations (upgrade head) against %s", settings.DATABASE_URL)
    try:
        command.upgrade(cfg, "head")
        logger.info("Alembic migrations applied successfully")
    except Exception as exc:
        logger.exception("Alembic migration failed: %s", exc)
        # Re-raise so callers (startup) fail-fast
        raise