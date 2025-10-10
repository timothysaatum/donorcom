#!/bin/bash
# CI/CD Migration Script for PostgreSQL
# This script runs during deployment to apply database migrations

set -e  # Exit on error

echo "🚀 Starting PostgreSQL Migration..."
echo "=================================="

# Check if DATABASE_URL is set
if [ -z "$DATABASE_URL" ]; then
    echo "❌ ERROR: DATABASE_URL environment variable is not set"
    exit 1
fi

# Verify it's PostgreSQL (not SQLite)
if [[ $DATABASE_URL == *"sqlite"* ]]; then
    echo "❌ ERROR: DATABASE_URL points to SQLite, not PostgreSQL"
    echo "   Expected: postgresql+asyncpg://..."
    echo "   Got: $DATABASE_URL"
    exit 1
fi

echo "✅ Database URL configured (PostgreSQL)"

# Check if alembic is installed
if ! command -v alembic &> /dev/null; then
    echo "❌ ERROR: Alembic is not installed"
    echo "   Run: pip install alembic"
    exit 1
fi

echo "✅ Alembic is installed"

# Check current migration version
echo ""
echo "📊 Checking current database version..."
CURRENT_VERSION=$(alembic current 2>&1 | grep -oP '(?<=\s)[a-f0-9]{12}(?=\s|$)' || echo "none")

if [ "$CURRENT_VERSION" = "none" ]; then
    echo "⚠️  Database has no migration version (new database or not migrated)"
else
    echo "✅ Current version: $CURRENT_VERSION"
fi

# Run migrations
echo ""
echo "🔄 Running migrations..."
alembic upgrade head

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Migrations completed successfully!"
    
    # Check final version
    FINAL_VERSION=$(alembic current 2>&1 | grep -oP '(?<=\s)[a-f0-9]{12}(?=\s|$)' || echo "unknown")
    echo "✅ Database is now at version: $FINAL_VERSION"
else
    echo ""
    echo "❌ Migration failed!"
    exit 1
fi

echo ""
echo "=================================="
echo "✅ PostgreSQL Migration Complete!"
echo "=================================="
