"""Database connection, session management, and health checking using SQLAlchemy Async Engine."""

import asyncio
import logging
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
    AsyncEngine,
)
from sqlalchemy import text

from src.config.settings import Settings, get_settings


class DatabaseManager:
    """Manages PostgreSQL connection pool, sessions, and connectivity health checks."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.settings = settings or get_settings()
        self.logger = logger or logging.getLogger("database_manager")
        self.engine: Optional[AsyncEngine] = None
        self.session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    async def connect(self) -> bool:
        """Initialize async engine and test connection."""
        if not self.settings.db_enabled:
            self.logger.info("Database persistence is disabled in settings (DB_ENABLED=false).")
            self._is_connected = False
            return False

        try:
            self.engine = create_async_engine(
                self.settings.async_db_url,
                pool_size=self.settings.db_pool_size,
                max_overflow=self.settings.db_max_overflow,
                pool_timeout=self.settings.db_timeout_seconds,
                pool_pre_ping=True,
                echo=False,
            )
            self.session_factory = async_sessionmaker(
                bind=self.engine,
                expire_on_commit=False,
                class_=AsyncSession,
            )

            # Test connection with timeout
            async with asyncio.timeout(self.settings.db_timeout_seconds):
                async with self.engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            
            self._is_connected = True
            self.logger.info(
                f"✅ Connected to PostgreSQL at {self.settings.postgres_host}:{self.settings.postgres_port}/{self.settings.postgres_db}"
            )
            return True
        except Exception as e:
            self._is_connected = False
            self.logger.warning(
                f"⚠️ PostgreSQL unavailable at {self.settings.postgres_host}:{self.settings.postgres_port}/{self.settings.postgres_db}: {e}. "
                "Trading engine will continue in file-only persistence mode."
            )
            return False

    async def disconnect(self) -> None:
        """Dispose of the database engine and close pool."""
        if self.engine:
            try:
                await self.engine.dispose()
                self._is_connected = False
                self.logger.info("Disconnected from PostgreSQL.")
            except Exception as e:
                self.logger.warning(f"Error disconnecting from PostgreSQL: {e}")

    async def healthcheck(self) -> dict:
        """Execute a healthcheck query against PostgreSQL."""
        if not self._is_connected or not self.engine:
            return {
                "status": "UNAVAILABLE",
                "connected": False,
                "host": self.settings.postgres_host,
                "port": self.settings.postgres_port,
                "database": self.settings.postgres_db,
            }

        try:
            async with asyncio.timeout(self.settings.db_timeout_seconds):
                async with self.engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            return {
                "status": "HEALTHY",
                "connected": True,
                "host": self.settings.postgres_host,
                "port": self.settings.postgres_port,
                "database": self.settings.postgres_db,
            }
        except Exception as e:
            self._is_connected = False
            self.logger.warning(f"PostgreSQL healthcheck failed: {e}")
            return {
                "status": "UNHEALTHY",
                "connected": False,
                "error": str(e),
                "host": self.settings.postgres_host,
                "port": self.settings.postgres_port,
                "database": self.settings.postgres_db,
            }

    async def run_migrations(self, migrations_dir: str = "migrations") -> list[str]:
        """Apply pending SQL migrations in alphabetical order."""
        if not self._is_connected or not self.engine:
            raise RuntimeError("Cannot run migrations: DatabaseManager is not connected.")

        from pathlib import Path
        mig_path = Path(migrations_dir)
        if not mig_path.exists():
            self.logger.warning(f"Migrations directory '{migrations_dir}' not found. Skipping.")
            return []

        applied = []
        async with self.engine.begin() as conn:
            # 1. Ensure migrations table exists
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """))

            # 2. Get already applied migrations
            res = await conn.execute(text("SELECT filename FROM schema_migrations;"))
            already_applied = {row[0] for row in res.fetchall()}

            # 3. Read and execute pending migration files
            sql_files = sorted(mig_path.glob("*.sql"))
            for sql_file in sql_files:
                fname = sql_file.name
                if fname not in already_applied:
                    self.logger.info(f"Applying migration: {fname}...")
                    sql_content = sql_file.read_text(encoding="utf-8")
                    
                    # Split into individual statements for asyncpg compatibility
                    statements = [s.strip() for s in sql_content.split(";") if s.strip()]
                    for stmt in statements:
                        await conn.execute(text(stmt))

                    await conn.execute(
                        text("INSERT INTO schema_migrations (filename) VALUES (:fname);"),
                        {"fname": fname},
                    )
                    applied.append(fname)
                    self.logger.info(f"✅ Migration applied: {fname}")

        return applied

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Async context manager yielding a database session."""
        if not self.session_factory:
            raise RuntimeError("DatabaseManager is not connected. Cannot create session.")

        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

