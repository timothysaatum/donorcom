#!/usr/bin/env python3
"""
Database Migration Runner Script

This script safely runs Alembic migrations against your database.
It can be run locally or in CI/CD pipelines.

Usage:
    python run_migrations.py              # Run migrations
    python run_migrations.py --check      # Check pending migrations
    python run_migrations.py --rollback   # Rollback one revision
"""

import sys
import os
import argparse
from pathlib import Path
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_database_url():
    """Get database URL from environment with validation and conversion"""
    # Check for migration-specific URL first, then fall back to app URL
    db_url = os.getenv('MIGRATION_DATABASE_URL') or os.getenv('DATABASE_URL')
    
    if not db_url:
        logger.error("DATABASE_URL environment variable is not set")
        sys.exit(1)
    
    original_url = db_url
    
    # Convert async driver to sync for migrations
    if 'postgresql+asyncpg://' in db_url:
        db_url = db_url.replace('postgresql+asyncpg://', 'postgresql://')
        logger.info("Converted asyncpg to psycopg2 for migrations")
    
    # Fix postgres:// to postgresql:// (common with Heroku/Railway)
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
        logger.info("Converted postgres:// to postgresql://")
    
    # Remove pooler for direct connection (Neon, Supabase)
    if '-pooler' in db_url:
        db_url = db_url.replace('-pooler', '')
        logger.info("Using direct connection (removed pooler)")
    
    # Ensure SSL is required for Neon
    if 'neon.tech' in db_url and 'sslmode' not in db_url:
        separator = '&' if '?' in db_url else '?'
        db_url = f"{db_url}{separator}sslmode=require"
        logger.info("Added SSL requirement for Neon")
    
    # Ensure SSL for Supabase
    if 'supabase.co' in db_url and 'sslmode' not in db_url:
        separator = '&' if '?' in db_url else '?'
        db_url = f"{db_url}{separator}sslmode=require"
        logger.info("Added SSL requirement for Supabase")
    
    if db_url != original_url:
        logger.info(f"Transformed URL for migration compatibility")
    
    return db_url


def get_alembic_config():
    """Get Alembic configuration"""
    # Find alembic.ini - check current directory and parent
    alembic_ini = None
    for path in [Path('.'), Path('..')]:
        candidate = path / 'alembic.ini'
        if candidate.exists():
            alembic_ini = str(candidate)
            break
    
    if not alembic_ini:
        logger.error("alembic.ini not found in current or parent directory")
        sys.exit(1)
    
    logger.info(f"Using config: {alembic_ini}")
    config = Config(alembic_ini)
    
    # Override sqlalchemy.url with environment variable
    db_url = get_database_url()
    config.set_main_option('sqlalchemy.url', db_url)
    
    return config


def test_connection(db_url):
    """Test database connection before running migrations"""
    logger.info("Testing database connection...")
    try:
        # Create engine with short timeout for connection test
        engine = create_engine(
            db_url, 
            echo=False,
            pool_pre_ping=True,
            connect_args={
                'connect_timeout': 10
            }
        )
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        engine.dispose()
        logger.info("Database connection successful")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


def get_current_revision(config):
    """Get current database revision"""
    try:
        db_url = config.get_main_option('sqlalchemy.url')
        engine = create_engine(db_url, echo=False)
        
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current = context.get_current_revision()
        
        engine.dispose()
        return current
    except Exception as e:
        logger.error(f"Failed to get current revision: {e}")
        return None


def get_head_revision(config):
    """Get the head revision from migration scripts"""
    try:
        script = ScriptDirectory.from_config(config)
        head = script.get_current_head()
        return head
    except Exception as e:
        logger.error(f"Failed to get head revision: {e}")
        return None


def check_pending_migrations(config):
    """Check if there are pending migrations"""
    current = get_current_revision(config)
    head = get_head_revision(config)
    
    if current is None:
        logger.warning("No migration history found. Database may be uninitialized.")
        logger.info("Run 'alembic stamp head' if this is a fresh database with schema already created")
        return True
    
    if current == head:
        logger.info(f"Database is up to date (revision: {current})")
        return False
    else:
        logger.info(f"Pending migrations detected:")
        logger.info(f"  Current revision: {current}")
        logger.info(f"  Target revision:  {head}")
        return True


def run_migrations(config, dry_run=False):
    """Run database migrations"""
    try:
        # Check connection first
        db_url = config.get_main_option('sqlalchemy.url')
        if not test_connection(db_url):
            logger.error("Cannot proceed with migrations - database connection failed")
            sys.exit(1)
        
        # Check current state
        current = get_current_revision(config)
        head = get_head_revision(config)
        
        if current == head:
            logger.info("No migrations to run - database is up to date")
            return True
        
        if dry_run:
            logger.info(f"DRY RUN: Would upgrade from {current} to {head}")
            return True
        
        logger.info(f"Running migrations: {current} -> {head}")
        
        # Run the upgrade
        command.upgrade(config, "head")
        
        logger.info("Migrations completed successfully")
        
        # Verify
        new_revision = get_current_revision(config)
        if new_revision == head:
            logger.info(f"Verified: Database is now at revision {new_revision}")
            return True
        else:
            logger.error(f"Migration verification failed. Expected {head}, got {new_revision}")
            return False
            
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return False


def rollback_migration(config, steps=1):
    """Rollback migrations"""
    try:
        current = get_current_revision(config)
        logger.warning(f"Rolling back {steps} revision(s) from {current}")
        
        # Confirm in interactive mode
        if sys.stdin.isatty():
            response = input("Are you sure you want to rollback? (yes/no): ")
            if response.lower() != 'yes':
                logger.info("Rollback cancelled")
                return False
        
        revision = f"-{steps}"
        command.downgrade(config, revision)
        
        new_revision = get_current_revision(config)
        logger.info(f"Rolled back to revision {new_revision}")
        return True
        
    except Exception as e:
        logger.error(f"Rollback failed: {e}", exc_info=True)
        return False


def show_migration_history(config):
    """Show migration history"""
    try:
        logger.info("Migration History:")
        command.history(config, verbose=True)
    except Exception as e:
        logger.error(f"Failed to show history: {e}")


def show_current_status(config):
    """Show current migration status"""
    try:
        current = get_current_revision(config)
        head = get_head_revision(config)
        
        logger.info("Current Migration Status:")
        logger.info(f"  Database revision: {current or 'None (empty database)'}")
        logger.info(f"  Latest revision:   {head}")
        logger.info(f"  Status:            {'Up to date' if current == head else 'Migrations pending'}")
        
        return current == head
    except Exception as e:
        logger.error(f"Failed to show status: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Run database migrations safely',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_migrations.py                    # Run pending migrations
  python run_migrations.py --check            # Check for pending migrations
  python run_migrations.py --dry-run          # Simulate migration run
  python run_migrations.py --rollback         # Rollback last migration
  python run_migrations.py --rollback -n 2    # Rollback 2 migrations
  python run_migrations.py --history          # Show migration history
  python run_migrations.py --status           # Show current status
        """
    )
    
    parser.add_argument(
        '--check',
        action='store_true',
        help='Check for pending migrations without running them'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate migration run without making changes'
    )
    
    parser.add_argument(
        '--rollback',
        action='store_true',
        help='Rollback migrations'
    )
    
    parser.add_argument(
        '-n', '--steps',
        type=int,
        default=1,
        help='Number of migrations to rollback (default: 1)'
    )
    
    parser.add_argument(
        '--history',
        action='store_true',
        help='Show migration history'
    )
    
    parser.add_argument(
        '--status',
        action='store_true',
        help='Show current migration status'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Get configuration
    try:
        config = get_alembic_config()
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)
    
    # Execute requested action
    if args.status:
        is_current = show_current_status(config)
        sys.exit(0 if is_current else 1)
    
    if args.history:
        show_migration_history(config)
        sys.exit(0)
    
    if args.check:
        has_pending = check_pending_migrations(config)
        sys.exit(0 if not has_pending else 1)
    
    if args.rollback:
        success = rollback_migration(config, args.steps)
        sys.exit(0 if success else 1)
    
    # Default action: run migrations
    success = run_migrations(config, dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()