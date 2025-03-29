from logging.config import fileConfig
from sqlalchemy import create_engine
from alembic import context
import sys
import os

# Add your project directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import your Base after path modification
from app.db.base import Base  # noqa

config = context.config
fileConfig(config.config_file_name)
target_metadata = Base.metadata

def run_migrations_online():
    connectable = create_engine(config.get_main_option("sqlalchemy.url"))
    
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()