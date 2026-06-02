#!/bin/bash
# Create Alembic migration with Django-style sequential numbering

if [ -z "$1" ]; then
  echo "Usage: ./scripts/make_migration.sh <message>"
  exit 1
fi

MESSAGE="$1"

# Find next migration number
LATEST=$(ls -1 alembic/versions/*.py 2>/dev/null | grep -oE '^[0-9]+' | sort -n | tail -1)
NEXT=$((${LATEST:-0} + 1))
NEXT_NUM=$(printf "%04d" $NEXT)

# Generate migration
alembic revision -m "$MESSAGE"

# Find the generated migration (latest by mtime)
GENERATED=$(ls -1t alembic/versions/*.py 2>/dev/null | grep -v __pycache__ | head -1)

# Rename to sequential format
if [ -n "$GENERATED" ]; then
  BASE=$(basename "$GENERATED")
  NEW_NAME="${NEXT_NUM}_$(echo "$MESSAGE" | tr ' ' '_').py"
  NEW_PATH="alembic/versions/$NEW_NAME"

  mv "$GENERATED" "$NEW_PATH"
  echo "✓ Migration created: $NEW_NAME"
else
  echo "✗ Failed to create migration"
  exit 1
fi
