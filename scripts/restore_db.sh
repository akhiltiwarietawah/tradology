#!/usr/bin/env bash
# ==============================================================================
# Tradology PostgreSQL Database Restore Script
# ==============================================================================
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <path_to_backup_file.sql.gz>"
    exit 1
fi

BACKUP_FILE="$1"
CONTAINER_NAME="${CONTAINER_NAME:-crypto_trading_postgres}"
DB_NAME="${POSTGRES_DB:-crypto_trading}"
DB_USER="${POSTGRES_USER:-postgres}"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ Error: Backup file '$BACKUP_FILE' does not exist."
    exit 1
fi

echo "⚠️  WARNING: Restoring will overwrite existing data in '${DB_NAME}'."
read -p "Are you sure you want to proceed with restore from '$BACKUP_FILE'? (y/N): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Restore aborted by user."
    exit 0
fi

echo "🔄 Restoring database '${DB_NAME}' from '${BACKUP_FILE}'..."

if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    gunzip -c "$BACKUP_FILE" | docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME"
else
    gunzip -c "$BACKUP_FILE" | psql -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME"
fi

echo "✅ Database restore successfully completed."
