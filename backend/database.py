"""Database configuration with flag-based PostgreSQL/MySQL selection."""

import logging
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from typing import Literal

logger = logging.getLogger(__name__)

# Create base for models
Base = declarative_base()

# Database type selection from environment
DB_TYPE = os.getenv("DATABASE_TYPE", "json").lower()  # Options: "postgresql", "mysql", "json"

# Get database connection strings from environment
POSTGRESQL_URL = os.getenv("POSTGRESQL_URL", "postgresql://user:password@localhost:5432/llmcouncil")
MYSQL_URL = os.getenv("MYSQL_URL", "mysql+pymysql://user:password@localhost:3306/llmcouncil")


def get_database_url() -> str:
    """
    Get database URL based on DATABASE_TYPE flag.

    Returns:
        Database connection URL

    Raises:
        ValueError: If DATABASE_TYPE is invalid
    """
    if DB_TYPE == "postgresql":
        return POSTGRESQL_URL
    elif DB_TYPE == "mysql":
        return MYSQL_URL
    elif DB_TYPE == "json":
        # Return None for JSON file storage (backward compatible)
        return None
    else:
        raise ValueError(
            f"Invalid DATABASE_TYPE: {DB_TYPE}. "
            "Must be 'postgresql', 'mysql', or 'json'"
        )


def create_database_engine():
    """
    Create SQLAlchemy engine based on database type.

    Returns:
        SQLAlchemy engine or None if using JSON storage
    """
    database_url = get_database_url()

    if database_url is None:
        # JSON file storage mode
        return None

    # Create engine based on database type
    if DB_TYPE == "postgresql":
        engine = create_engine(
            database_url,
            pool_pre_ping=True,  # Verify connections before using
            echo=False,  # Set to True for SQL debugging
        )
    elif DB_TYPE == "mysql":
        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            echo=False,
            pool_recycle=3600,  # Recycle connections after 1 hour
        )
    else:
        raise ValueError(f"Unsupported database type: {DB_TYPE}")

    return engine


# Create engine and session factory
engine = create_database_engine()

if engine is not None:
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
else:
    SessionLocal = None


def get_db():
    """
    Dependency for FastAPI to get database session.

    Yields:
        Database session
    """
    if SessionLocal is None:
        raise RuntimeError("Database not configured. Set DATABASE_TYPE in .env")

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_database():
    """
    Initialize database tables.
    Call this on application startup.
    """
    if engine is None:
        logger.info("Using JSON file storage (DATABASE_TYPE=json)")
        return

    logger.info("Initializing %s database...", DB_TYPE.upper())

    # Import models to register them
    from . import models

    # Create all tables
    Base.metadata.create_all(bind=engine)

    logger.info("%s database initialized successfully!", DB_TYPE.upper())


def get_storage_type() -> Literal["postgresql", "mysql", "json"]:
    """Get the current storage type."""
    return DB_TYPE


def is_using_database() -> bool:
    """Check if using database (PostgreSQL/MySQL) or JSON files."""
    return DB_TYPE in ["postgresql", "mysql"]
