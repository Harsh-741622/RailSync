import os
os.environ.setdefault("RAILSYNC_DATABASE_URL", "sqlite://")
os.environ.setdefault("RAILSYNC_AUTH_MODE", "demo")
import pytest
from backend.database import Base, SessionLocal, engine
from backend.seed import seed_database


@pytest.fixture(autouse=True)
def isolated_test_database():
    """Every test receives a seeded in-memory database, never railsync.db."""
    # SQLite test connections have foreign-key enforcement disabled by default.
    # Drop explicitly to avoid SQLAlchemy's harmless cycle-sort warning caused by
    # proposal <-> timetable-version audit references.
    for table in reversed(list(Base.metadata.tables.values())):
        table.drop(bind=engine, checkfirst=True)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
    yield
    for table in reversed(list(Base.metadata.tables.values())):
        table.drop(bind=engine, checkfirst=True)
