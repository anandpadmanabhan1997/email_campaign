"""
app/db package initializer.

Expose engine, SessionLocal, Base, init_db and get_db at app.db for convenient imports.
Import models to ensure metadata is registered.
"""
from .session import engine, SessionLocal, Base, init_db, get_db  # noqa: F401
# Import models so that Base.metadata is populated when app.db is imported.
from . import models  # noqa: F401