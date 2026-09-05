"""Tests for DatabaseManager connection, healthcheck, and graceful failure handling."""

import pytest
from src.config.settings import Settings
from src.persistence.db import DatabaseManager


@pytest.mark.asyncio
async def test_database_manager_connect_and_healthcheck(test_settings):
    """Verify DatabaseManager connects to running PostgreSQL and returns HEALTHY status."""
    db_mgr = DatabaseManager(settings=test_settings)
    connected = await db_mgr.connect()
    assert connected is True
    assert db_mgr.is_connected is True

    health = await db_mgr.healthcheck()
    assert health["status"] == "HEALTHY"
    assert health["connected"] is True
    assert health["database"] == test_settings.postgres_db

    # Test session execution
    async with db_mgr.get_session() as session:
        from sqlalchemy import text
        res = await session.execute(text("SELECT 1 AS num"))
        row = res.scalar()
        assert row == 1

    await db_mgr.disconnect()
    assert db_mgr.is_connected is False


@pytest.mark.asyncio
async def test_database_manager_disabled_mode(test_settings):
    """Verify DatabaseManager handles DB_ENABLED=false gracefully."""
    disabled_settings = test_settings.model_copy(update={"db_enabled": False})
    db_mgr = DatabaseManager(settings=disabled_settings)
    
    connected = await db_mgr.connect()
    assert connected is False
    assert db_mgr.is_connected is False

    health = await db_mgr.healthcheck()
    assert health["status"] == "UNAVAILABLE"
    assert health["connected"] is False


@pytest.mark.asyncio
async def test_database_manager_unreachable_host_graceful_handling(test_settings):
    """Verify DatabaseManager handles unreachable host without raising unhandled exceptions."""
    unreachable_settings = test_settings.model_copy(
        update={
            "postgres_host": "127.0.0.1",
            "postgres_port": 59999,  # Non-existent port
            "db_timeout_seconds": 1.0,
        }
    )
    db_mgr = DatabaseManager(settings=unreachable_settings)
    
    connected = await db_mgr.connect()
    assert connected is False
    assert db_mgr.is_connected is False

    health = await db_mgr.healthcheck()
    assert health["status"] == "UNAVAILABLE"
    assert health["connected"] is False
