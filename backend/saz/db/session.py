"""Database session management."""

import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

# Database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./saz.db")

# Create engine
engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    # SQLite specific
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session() -> Generator[Session, None, None]:
    """Get database session (dependency injection)."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
