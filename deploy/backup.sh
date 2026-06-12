#!/usr/bin/env bash
# =============================================================================
# backup.sh — автоматический бэкап PostgreSQL + Qdrant
# Запуск: ./deploy/backup.sh
# Cron:   0 3 * * * /root/DS-25001-VectorSearch/deploy/backup.sh
# =============================================================================

set -euo pipefail

# === Config ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${BACKUP_DIR:-${PROJECT_ROOT}/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"

# Postgres credentials (from env or .env)
PG_USER="${POSTGRES_USER:-ksr}"
PG_DB="${POSTGRES_DB:-ksr}"

mkdir -p "$BACKUP_DIR"

echo "🗄️  Starting backup at $TIMESTAMP"

# === 1. PostgreSQL dump ===
echo "📦 Backing up PostgreSQL..."
PGPASSWORD="${POSTGRES_PASSWORD}" $COMPOSE_CMD \
    -f "$PROJECT_ROOT/docker-compose.yml" \
    exec -T postgres \
    pg_dump -U "$PG_USER" "$PG_DB" | gzip > "$BACKUP_DIR/postgres_${TIMESTAMP}.sql.gz"

PG_SIZE=$(du -h "$BACKUP_DIR/postgres_${TIMESTAMP}.sql.gz" | cut -f1)
echo "✅ PostgreSQL backup: $PG_SIZE"

# === 2. Qdrant snapshot ===
echo "📦 Creating Qdrant snapshot..."
$COMPOSE_CMD \
    -f "$PROJECT_ROOT/docker-compose.yml" \
    exec -T qdrant \
    curl -X POST http://localhost:6333/snapshots

# Copy snapshot out of container
$COMPOSE_CMD \
    -f "$PROJECT_ROOT/docker-compose.yml" \
    cp qdrant:/qdrant/snapshots "$BACKUP_DIR/qdrant_${TIMESTAMP}/" 2>/dev/null || true

echo "✅ Qdrant snapshot saved"

# === 3. Cleanup old backups ===
echo "🧹 Cleaning up backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
find "$BACKUP_DIR" -type d -name "qdrant_*" -mtime +$RETENTION_DAYS -exec rm -rf {} + 2>/dev/null || true

# === 4. Summary ===
echo ""
echo "✅ Backup completed!"
echo "   📁 Location: $BACKUP_DIR"
echo "   📊 Files:"
ls -lah "$BACKUP_DIR" | tail -n +2

# === 5. Optional: upload to S3 ===
if [ -n "${S3_BUCKET:-}" ]; then
    echo "☁️  Uploading to S3..."
    aws s3 cp "$BACKUP_DIR/postgres_${TIMESTAMP}.sql.gz" "s3://${S3_BUCKET}/postgres/" || true
    aws s3 cp --recursive "$BACKUP_DIR/qdrant_${TIMESTAMP}/" "s3://${S3_BUCKET}/qdrant/${TIMESTAMP}/" || true
fi
