"""SQLAlchemy engine/session setup, backed by SQL Server (see settings.py)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .settings import DATABASE_URL

# Sized for real production load, not just dev: every *enabled* camera has
# its own worker thread holding a DB session for its whole lifetime (see
# camera_manager._CameraWorker._run), on top of one short-lived session per
# HTTP/WS request (auth check, status polls, event writes, heatmap flushes).
# The SQLAlchemy default (pool_size=5, max_overflow=10 -- 15 connections
# total) is easily exhausted by a handful of cameras plus a couple of people
# viewing the dashboard at once, which surfaces as
# "QueuePool limit ... connection timed out" 500s under exactly that load.
# pool_pre_ping avoids handing out a connection SQL Server has silently
# dropped (this instance has shown flaky/slow connects before);
# pool_recycle avoids reusing one that's been idle long enough to go stale.
engine = create_engine(
    DATABASE_URL, fast_executemany=True,
    pool_size=30, max_overflow=30, pool_pre_ping=True, pool_recycle=1800,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
