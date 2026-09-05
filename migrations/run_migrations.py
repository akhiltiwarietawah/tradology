#!/usr/bin/env python3
"""Run database migrations idempotently against PostgreSQL."""

import asyncio
import sys
import logging
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.settings import get_settings
from src.persistence.db import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


async def main():
    settings = get_settings()
    db = DatabaseManager(settings=settings)
    connected = await db.connect()
    if not connected:
        logging.error("Failed to connect to PostgreSQL. Verify container/database is running.")
        sys.exit(1)

    logging.info("Applying pending migrations from migrations/ ...")
    applied = await db.run_migrations("migrations")
    if applied:
        logging.info(f"✅ Successfully applied {len(applied)} migration(s): {applied}")
    else:
        logging.info("✅ Database schema is already up to date. No new migrations.")

    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
