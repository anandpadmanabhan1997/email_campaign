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
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base
from sqlalchemy.pool import Pool
from app.core.config import get_settings

print("[DEBUG] Importing session.py module", flush=True)

settings = get_settings()
print(f"[DEBUG] Settings loaded, DATABASE_URL: {settings.DATABASE_URL}", flush=True)

DATABASE_URL = settings.DATABASE_URL
print(f"[DEBUG] DATABASE_URL set to: {DATABASE_URL}", flush=True)

# SQLite-specific connect args for multi-threaded usage (dev)
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    print("[DEBUG] SQLite detected, setting connect_args", flush=True)
    connect_args = {"check_same_thread": False}
    print(f"[DEBUG] connect_args: {connect_args}", flush=True)

# Engine and session factory
print("[DEBUG] Creating SQLAlchemy engine", flush=True)
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
print("[DEBUG] Engine created successfully", flush=True)

# Add PRAGMA configuration for SQLite
@event.listens_for(Pool, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """
    Configure SQLite PRAGMAs for better performance and concurrency.
    This is called every time a new connection is established.
    """
    
    # Only apply to SQLite
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.execute("PRAGMA journal_mode=WAL")
            result = cursor.fetchone()
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA foreign_keys=ON")
            dbapi_conn.commit()
            
        except Exception as e:
            print(f"[WARN] Failed to set SQLite PRAGMAs (may retry on next connection): {type(e).__name__}: {e}", flush=True)
        finally:
            cursor.close()
    else:
        print(f"[DEBUG] Not SQLite, skipping PRAGMAs for: {DATABASE_URL}", flush=True)


SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True))

Base = declarative_base()


def init_db() -> None:
    """
    Create tables for all models registered on Base.metadata.
    This is a simple replacement for migrations (use with care in production).
    """
    
    try:
        from app.db import models  
    except Exception as e:
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
