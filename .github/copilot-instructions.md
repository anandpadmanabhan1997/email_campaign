**Repository Overview**

This repo is a small bulk-mail service composed of a FastAPI web app, SQLAlchemy DB layer, Celery background workers, and Alembic migrations. Key components:
- **Web app**: `app/main.py` (mounts static, includes UI router) and root `main.py` (verbose startup, guarded migrations/timeouts).
- **DB layer**: `app/db/session.py`, `app/db/models.py`, `app/db/repositories.py` (repository helpers and bulk-insert logic).
- **Migrations**: `app/core/alembic_runner.py` uses `alembic.ini` (repo root) and is invoked automatically by several processes.
- **Celery**: worker instance(s) live under `app/tasks/celery_app.py` (`celery_app`) and `app/celery_app.py` (legacy-style module that runs migrations on import).
- **Email**: `app/emailer.py` contains an async `send_email_async` (aiosmtplib) and sync `send_email` wrapper used by tasks.

**How the pieces fit (big picture)**
- Incoming HTTP requests are handled by FastAPI routers in `app/api/v1/*` (see `campaigns.py`, `recipients.py`, `reports.py`).
- Routers call repository helpers in `app/db/repositories.py` which use `SessionLocal` from `app/db/session.py`.
- Background work (sending, report generation) is enqueued via Celery. The web code uses the Celery instance from `app/tasks/celery_app.py` (or `app.celery_app` in some places).
- Migrations are applied programmatically by `app/core/alembic_runner.run_migrations()`; root `main.py` runs it with a timeout, `app/celery_app.py` runs it on import (worker startup).

**Developer workflows / commands**
- Run the app (recommended — runs migrations by default):
  - `python main.py`  # root entrypoint runs alembic (uses env vars below)
- Quick dev server (no guarded migration timeout; still runs `init_db()`):
  - `uvicorn app.main:app --reload` or `python -m uvicorn app.main:app --reload`
- Apply migrations manually (uses `alembic.ini` at repo root):
  - `alembic upgrade head`
- Run Celery worker (uses `app.tasks.celery_app:celery_app`):
  - `celery -A app.tasks.celery_app.celery_app worker --loglevel=info`
- Common env vars used at runtime (see `app/core/config.py`):
  - `DATABASE_URL`, `REPORTS_DIR`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `SMTP_*`, `SKIP_MIGRATIONS`, `MIGRATION_TIMEOUT_SECONDS`, `DEV_RELOAD`.

**Project-specific conventions & patterns**
- Settings: always call `get_settings()` from `app.core.config` (it's cached via `lru_cache`). Avoid re-instantiating settings.
- DB session: use the `get_db` FastAPI dependency from `app/db/session.py` to ensure sessions are closed.
- Repositories: mutate and commit in repository helpers (e.g., `create_campaign`, `update_campaign_status`). Many repository functions return refreshed model instances.
- Bulk inserts (recipients): implemented in `app/db/repositories.py` using SQLite `INSERT OR IGNORE` with a dedupe pre-pass — follow that pattern if adding other bulk operations.
- Timezones: endpoints (e.g., `app/api/v1/campaigns.py`) normalize client datetimes to UTC (naive datetimes are treated as UTC). Maintain this approach when reading or writing `scheduled_at` values.
- Reports directory: `REPORTS_DIR` is created on startup (see `main.py` and `app/main.py`), so code assumes this path exists and is writable.

**Integration points & gotchas (things an AI should pay attention to)**
- Migrations run automatically in multiple places: root `main.py` and `app/celery_app.py`. If DB/migrations fail, processes will raise and exit — be careful when editing `app/core/alembic_runner.py` behavior.
- There are two Celery-related modules: `app/celery_app.py` (runs migrations on import) and `app/tasks/celery_app.py` (task registration and the `celery_app` instance used by code). Confirm which one your change must affect.
- Task registration: `app/tasks/celery_app.py` attempts to import `app.tasks.tasks` to register decorated tasks. If you add tasks, register them under `app/tasks/*` and ensure the Celery import path matches the worker invocation.
- Logging: root `main.py` intentionally logs safe env values (but avoids printing `SMTP_PASSWORD`). Preserve that behavior when adding startup logging.

**Files to reference for examples**
- HTTP routing & validation: `app/api/v1/campaigns.py` (timezone handling, enqueueing tasks), `app/api/v1/recipients.py` (bulk CSV handling).
- DB utilities: `app/db/repositories.py` (bulk insert & repository patterns), `app/db/session.py` (engine/session setup), `app/db/models.py` (schema).
- Migrations runner: `app/core/alembic_runner.py` and `alembic.ini` (repo root).
- Celery wiring: `app/tasks/celery_app.py`, `app/celery_app.py`.
- Mail sending: `app/emailer.py` (async + sync wrapper).

If anything above is unclear or you'd like me to emphasize different examples (e.g., show the exact `celery` CLI to use in Docker, or include a minimal `.env` example), tell me what to expand and I'll iterate.
