"""
Application entrypoint.

"""
import logging
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
from fastapi.staticfiles import StaticFiles
from app import ui 

# configure logging 
LOG_LEVEL = os.getenv("APP_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("app.main")

from app.core.config import get_settings

settings = get_settings()


def _import_v1_routers():
    """
    Import the v1 routers; allow ImportError to propagate if something is missing.
    """
    logger.info("Importing API v1 routers: recipients, campaigns, reports")
    from app.api.v1 import recipients, campaigns, reports  # noqa: E402

    logger.info("Successfully imported v1 routers")
    return recipients.router, campaigns.router, reports.router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan handler: ensure resources exist and initialize DB (no alembic).
    """
    logger.info("LIFESPAN STARTUP: creating reports dir and initializing DB")

    # Ensure reports dir exists
    try:
        reports_dir = settings.REPORTS_DIR
        logger.info("Ensuring reports directory exists at %s", reports_dir)
        os.makedirs(reports_dir, exist_ok=True)
        logger.info("Reports directory present: %s", reports_dir)
    except Exception as exc:
        logger.exception("Failed to create/verify reports dir %s: %s", settings.REPORTS_DIR, exc)
        raise

    # Initialize DB tables as a fallback (SQLAlchemy create_all)
    try:
        from app.db import init_db

        logger.info("Calling init_db() to ensure tables exist")
        init_db()
        logger.info("init_db() completed")
    except Exception as exc:
        logger.exception("init_db() raised an exception during startup: %s", exc)
        raise

    logger.info("LIFESPAN STARTUP: completed successfully")
    try:
        yield
    finally:
        logger.info("LIFESPAN SHUTDOWN: cleaning up")


def create_app() -> FastAPI:
    logger.info("Creating FastAPI app instance")
    app = FastAPI(title="Bulk Mail", lifespan=lifespan)

    # Import routers (will raise if any are missing)
    recipients_router, campaigns_router, reports_router = _import_v1_routers()

    app.include_router(recipients_router, prefix="/recipients", tags=["recipients"])
    app.include_router(campaigns_router, prefix="/campaigns", tags=["campaigns"])
    app.include_router(reports_router, prefix="/reports", tags=["reports"])
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(ui.router)
    logger.info("Routers included: /recipients, /campaigns, /reports")
    return app


# ASGI app
app = create_app()


if __name__ == "__main__":
    logging.getLogger("uvicorn.error").setLevel(logging.DEBUG)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("DEV_RELOAD", "true").lower() in ("1", "true", "yes")

    logger.info("Starting uvicorn with host=%s port=%s reload=%s", host, port, reload)
    uvicorn.run("app.main:app", host=host, port=port, reload=reload, log_level="info")