import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import pool

# Ensure the app directory is in the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# Import metadata from your Base
from app.db.base import Base  # Your declarative Base
from app.models import user, health_facility, blood_bank  # Ensure all models are imported here

# Alembic Config
config = context.config
fileConfig(config.config_file_name)
target_metadata = Base.metadata

# Get the database URL from the config file
db_url = config.get_main_option("sqlalchemy.url")


async def run_async_migrations():
    """Run migrations in 'online' mode using async engine."""

    connectable = create_async_engine(db_url, poolclass=pool.NullPool)

    async with connectable.connect() as connection:

        def do_migrations(sync_connection):
            context.configure(
                connection=sync_connection,
                target_metadata=target_metadata,
                compare_type=True,         # Detect type changes
                render_as_batch=True       # Important for SQLite
            )
            context.run_migrations()

        await connection.run_sync(do_migrations)


def run_migrations_online():
    """Entry point for Alembic command."""
    asyncio.run(run_async_migrations())


# Entry point that Alembic calls
run_migrations_online()
