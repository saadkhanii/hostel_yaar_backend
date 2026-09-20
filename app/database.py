from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

# `connect_args` is only needed for SQLite (allows use across threads).
# When you switch DATABASE_URL to Postgres later, this is ignored automatically.
connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)
engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    # Verify connections are alive before handing them out — protects
    # against Neon serverless suspending idle connections.
    pool_pre_ping=True,
    # Recycle connections every 5 minutes (matches Neon's idle suspend).
    pool_recycle=300,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: gives each request its own DB session, always closed after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
