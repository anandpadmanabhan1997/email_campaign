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
    print("[DEBUG] set_sqlite_pragma event triggered", flush=True)
    
    # Only apply to SQLite
    if DATABASE_URL.startswith("sqlite"):
        print("[DEBUG] Applying SQLite PRAGMAs", flush=True)
        cursor = dbapi_conn.cursor()
        print("[DEBUG] Cursor created", flush=True)
        
        try:
            # Set busy timeout FIRST - before any other operations
            # This prevents "database is locked" on subsequent PRAGMAs
            print("[DEBUG] Setting PRAGMA busy_timeout=10000 FIRST (before other PRAGMAs)", flush=True)
            cursor.execute("PRAGMA busy_timeout=10000")
            print("[DEBUG] PRAGMA busy_timeout=10000 set", flush=True)
            
            # Write-Ahead Logging - improves concurrency
            print("[DEBUG] Setting PRAGMA journal_mode=WAL", flush=True)
            cursor.execute("PRAGMA journal_mode=WAL")
            result = cursor.fetchone()
            print(f"[DEBUG] PRAGMA journal_mode result: {result}", flush=True)
            
            # Balance between safety and performance
            print("[DEBUG] Setting PRAGMA synchronous=NORMAL", flush=True)
            cursor.execute("PRAGMA synchronous=NORMAL")
            print("[DEBUG] PRAGMA synchronous=NORMAL set", flush=True)
            
            # Increase cache size to 64MB
            print("[DEBUG] Setting PRAGMA cache_size=-64000", flush=True)
            cursor.execute("PRAGMA cache_size=-64000")
            print("[DEBUG] PRAGMA cache_size=-64000 set", flush=True)
            
            # Use memory for temporary tables
            print("[DEBUG] Setting PRAGMA temp_store=MEMORY", flush=True)
            cursor.execute("PRAGMA temp_store=MEMORY")
            print("[DEBUG] PRAGMA temp_store=MEMORY set", flush=True)
            
            # Foreign keys support
            print("[DEBUG] Setting PRAGMA foreign_keys=ON", flush=True)
            cursor.execute("PRAGMA foreign_keys=ON")
            print("[DEBUG] PRAGMA foreign_keys=ON set", flush=True)
            
            print("[DEBUG] Committing all PRAGMAs", flush=True)
            dbapi_conn.commit()
            print("[DEBUG] All PRAGMAs committed successfully", flush=True)
            
        except Exception as e:
            print(f"[WARN] Failed to set SQLite PRAGMAs (may retry on next connection): {type(e).__name__}: {e}", flush=True)
            # Don't raise - let the connection proceed anyway
            # PRAGMAs will be retried on next connection
        finally:
            cursor.close()
            print("[DEBUG] Cursor closed", flush=True)
    else:
        print(f"[DEBUG] Not SQLite, skipping PRAGMAs for: {DATABASE_URL}", flush=True)


print("[DEBUG] Creating SessionLocal (scoped_session)", flush=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True))
print("[DEBUG] SessionLocal created successfully", flush=True)

# Declarative base for models
print("[DEBUG] Creating declarative Base", flush=True)
Base = declarative_base()
print("[DEBUG] Base created successfully", flush=True)


def init_db() -> None:
    """
    Create tables for all models registered on Base.metadata.
    This is a simple replacement for migrations (use with care in production).
    """
    print("[DEBUG] init_db() called", flush=True)
    
    # Import models so they register on Base.metadata
    try:
        print("[DEBUG] Importing models module", flush=True)
        # adjust import path if your models are elsewhere
        from app.db import models  # noqa: F401
        print("[DEBUG] Models imported successfully", flush=True)
    except Exception as e:
        print(f"[ERROR] Failed to import models: {type(e).__name__}: {e}", flush=True)
        # If models module isn't present or import fails, raise so the caller sees the issue
        raise
    
    print("[DEBUG] Creating all tables using Base.metadata.create_all()", flush=True)
    Base.metadata.create_all(bind=engine)
    print("[DEBUG] All tables created successfully", flush=True)


def get_db() -> Generator:
    """
    FastAPI dependency that yields a SQLAlchemy session and ensures it's closed.
    """
    print("[DEBUG] get_db() called - creating new session", flush=True)
    db = SessionLocal()
    print("[DEBUG] Session created", flush=True)
    
    try:
        yield db
        print("[DEBUG] Session yielded to caller", flush=True)
    finally:
        print("[DEBUG] get_db() finally block - closing session", flush=True)
        db.close()
        print("[DEBUG] Session closed", flush=True)