from __future__ import annotations
import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

def _database_url() -> str:
    """Use an explicitly configured database, including Vercel Marketplace Postgres."""
    configured = os.getenv("RAILSYNC_DATABASE_URL") or os.getenv("POSTGRES_URL")
    if not configured:
        if os.getenv("VERCEL"):
            raise RuntimeError("Vercel deployments require RAILSYNC_DATABASE_URL or POSTGRES_URL; SQLite is not durable on Vercel.")
        return "sqlite:///./railsync.db"
    # Marketplace providers commonly expose libpq's postgres:// form. SQLAlchemy
    # needs the installed psycopg 3 driver named explicitly.
    if configured.startswith("postgres://"):
        return "postgresql+psycopg://" + configured.removeprefix("postgres://")
    if configured.startswith("postgresql://"):
        return "postgresql+psycopg://" + configured.removeprefix("postgresql://")
    return configured


DATABASE_URL = _database_url()
_engine_kwargs = {"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {}
if DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}:
    _engine_kwargs["poolclass"] = StaticPool
engine = create_engine(DATABASE_URL, future=True, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    # Import models to register all metadata before create_all.
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
