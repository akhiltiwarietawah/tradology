#!/usr/bin/env bash
# ==============================================================================
# Tradology PostgreSQL Automated Database Backup Script
# ==============================================================================
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-data/backups}"
CONTAINER_NAME="${CONTAINER_NAME:-crypto_trading_postgres}"
DB_NAME="${POSTGRES_DB:-crypto_trading}"
DB_USER="${POSTGRES_USER:-postgres}"
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/crypto_trading_${TIMESTAMP}.sql.gz"

echo "📦 Starting PostgreSQL backup for database '${DB_NAME}'..."

if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    docker exec -t "$CONTAINER_NAME" pg_dump -U "$DB_USER" -d "$DB_NAME" | gzip > "$BACKUP_FILE"
else
    # Fallback to local pg_dump
    pg_dump -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME" | gzip > "$BACKUP_FILE"
fi

if [ -s "$BACKUP_FILE" ]; then
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "✅ Backup successfully created: ${BACKUP_FILE} (${SIZE})"
else
    echo "❌ Backup failed or produced empty file!"
    rm -f "$BACKUP_FILE"
    exit 1
fi

# Clean up backups older than RETENTION_DAYS
echo "🧹 Pruning backups older than ${RETENTION_DAYS} days..."
find "$BACKUP_DIR" -name "crypto_trading_*.sql.gz" -type f -mtime +"$RETENTION_DAYS" -exec rm -f {} +
echo "✅ Backup workflow complete."
