"""
app/db/session.py

SQLAlchemy engine / session / Base helpers.

This module exposes:
- engine: SQLAlchemy Engine
- SessionLocal: session factory (scoped/sessionmaker)
- Base: declarative base for models
- init_db(): create tables using models' metadata
- get_db(): FastAPI dependency that yields a session
"""
from typing import Generator
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base

from app.core.config import get_settings

settings = get_settings()
DATABASE_URL = settings.DATABASE_URL

# SQLite-specific connect args for multi-threaded usage (dev)
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

# Engine and session factory
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True))

# Declarative base for models
Base = declarative_base()

def init_db() -> None:
    """
    Create tables for all models registered on Base.metadata.
    This is a simple replacement for migrations (use with care in production).
    """
    # Import models so they register on Base.metadata
    try:
        # adjust import path if your models are elsewhere
        from app.db import models  # noqa: F401
    except Exception:
        # If models module isn't present or import fails, raise so the caller sees the issue
        raise

    Base.metadata.create_all(bind=engine)

def get_db() -> Generator:
    """
    FastAPI dependency that yields a SQLAlchemy session and ensures it's closed.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()