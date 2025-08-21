# import asyncio
# import os
# import sys
# from logging.config import fileConfig

# from alembic import context
# from sqlalchemy.ext.asyncio import create_async_engine
# from sqlalchemy import pool

# # Ensure the app directory is in the Python path
# sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# # Import metadata from your Base
# from app.db.base import Base  # Your declarative Base
# from app.models import user, health_facility, blood_bank  # Ensure all models are imported here

# # Alembic Config
# config = context.config
# fileConfig(config.config_file_name)
# target_metadata = Base.metadata

# # Get the database URL from the config file
# db_url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")

# # Ensure we have the async format for PostgreSQL
# if db_url and db_url.startswith("postgresql://"):
#     db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")


# async def run_async_migrations():
#     """Run migrations in 'online' mode using async engine."""

#     # Create async engine with better connection parameters
#     connectable = create_async_engine(
#         db_url,
#         echo=True,  # log SQL for debugging, disable in prod
#         pool_size=5,         # number of connections in pool
#         max_overflow=10,     # extra connections allowed
#         pool_recycle=1800,   # recycle connections every 30 mins
#         pool_pre_ping=True,  # check if connection is alive before use
#         connect_args={
#             "server_settings": {
#                 "application_name": "alembic_migration",
#             },
#             "command_timeout": 60,  # asyncpg timeout in seconds
#         },
#     )

#     try:
#         async with connectable.connect() as connection:
            
#             async with connection.begin():
#                 def do_migrations(sync_connection):
#                     context.configure(
#                         connection=sync_connection,
#                         target_metadata=target_metadata,
#                         compare_type=True,
#                         render_as_batch=True
#                     )
#                     context.run_migrations()

#                 await connection.run_sync(do_migrations)
#                 # Transaction will be committed automatically when exiting the context
#     finally:
#         await connectable.dispose()


# def run_migrations_offline():
#     """Run migrations in 'offline' mode."""
#     # Convert async URL to sync for offline mode
#     offline_url = db_url
#     if offline_url and "+asyncpg" in offline_url:
#         offline_url = offline_url.replace("+asyncpg", "")

#     elif offline_url and "+psycopg" in offline_url:
#         offline_url = offline_url.replace("+psycopg", "")

#     context.configure(
#         url=offline_url,
#         target_metadata=target_metadata,
#         literal_binds=True,
#         dialect_opts={"paramstyle": "named"},
#     )

#     with context.begin_transaction():
#         context.run_migrations()


# def run_migrations_online():
#     """Entry point for Alembic command."""
#     try:
#         asyncio.run(run_async_migrations())
#     except Exception as e:
#         print(f"Migration failed with error: {e}")
#         print("\nThis is likely a network connectivity issue to your RDS instance.")
#         print("Check your AWS security group settings to allow connections on port 5432")
#         print("from your Elastic Beanstalk environment's security group.")
#         print(f"\nDatabase URL being used: {db_url}")
#         raise

# if context.is_offline_mode():
#     run_migrations_offline()

# else:
#     run_migrations_online()
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

# Get the database URL from the config file or env
db_url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")

# Ensure async format for PostgreSQL
if db_url and db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

# Conditionally set connect_args
connect_args = {}
if db_url.startswith("postgresql+asyncpg://"):
    connect_args = {
        "server_settings": {
            "application_name": "alembic_migration",
        },
        "command_timeout": 60,
    }

async def run_async_migrations():
    """Run migrations in 'online' mode using async engine."""
    connectable = create_async_engine(
        db_url,
        echo=True,  # log SQL for debugging
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
        pool_pre_ping=True,
        connect_args=connect_args,  # safe for both PostgreSQL and SQLite
    )

    try:
        async with connectable.connect() as connection:
            async with connection.begin():
                def do_migrations(sync_connection):
                    context.configure(
                        connection=sync_connection,
                        target_metadata=target_metadata,
                        compare_type=True,
                        render_as_batch=True
                    )
                    context.run_migrations()

                await connection.run_sync(do_migrations)
    finally:
        await connectable.dispose()


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    offline_url = db_url
    if offline_url and "+asyncpg" in offline_url:
        offline_url = offline_url.replace("+asyncpg", "")
    elif offline_url and "+psycopg" in offline_url:
        offline_url = offline_url.replace("+psycopg", "")

    context.configure(
        url=offline_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Entry point for Alembic command."""
    try:
        asyncio.run(run_async_migrations())
    except Exception as e:
        print(f"Migration failed with error: {e}")
        print("\nCheck your DB connectivity and security settings.")
        print(f"Database URL being used: {db_url}")
        raise


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()