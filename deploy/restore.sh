#!/usr/bin/env bash
# =============================================================================
# restore.sh — восстановление PostgreSQL из дампа
# Использование: ./deploy/restore.sh <file.sql.gz>
# =============================================================================

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <backup.sql.gz>"
    echo "Example: $0 backups/postgres_20260101_030000.sql.gz"
    exit 1
fi

BACKUP_FILE="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"
PG_USER="${POSTGRES_USER:-ksr}"
PG_DB="${POSTGRES_DB:-ksr}"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ File not found: $BACKUP_FILE"
    exit 1
fi

echo "⚠️  WARNING: This will OVERWRITE the database $PG_DB!"
echo "📁 Restoring from: $BACKUP_FILE"
read -p "Continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Cancelled."
    exit 0
fi

# Decompress if .gz
if [[ "$BACKUP_FILE" == *.gz ]]; then
    echo "📦 Decompressing..."
    gunzip -c "$BACKUP_FILE" > /tmp/restore.sql
    SQL_FILE="/tmp/restore.sql"
else
    SQL_FILE="$BACKUP_FILE"
fi

echo "🔄 Restoring..."
$COMPOSE_CMD -f "$PROJECT_ROOT/docker-compose.yml" \
    exec -T postgres \
    psql -U "$PG_USER" -d "$PG_DB" < "$SQL_FILE"

echo "✅ Database restored from $BACKUP_FILE"

# Cleanup
[ -f /tmp/restore.sql ] && rm /tmp/restore.sql
