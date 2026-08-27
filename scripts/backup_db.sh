#!/usr/bin/env bash
# STORY-055: local Docker Compose Postgres backup. Local-development,
# manually-invoked only -- no cron/scheduling, no off-host storage. See
# README.md's "Backups" section for the full documented procedure,
# including the paired scripts/restore_db.sh validation script.
#
# pg_dump runs *inside* the postgres container via `docker compose exec`,
# connecting over its local unix socket -- the same trust auth the existing
# `pg_isready` healthcheck (docker-compose.yml) already relies on. This
# script never reads or passes POSTGRES_PASSWORD.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -f .env ]; then
  echo "Missing .env (copy .env.example to .env first)." >&2
  exit 1
fi

# Plain identifiers, not secrets -- read only these two lines out of .env
# rather than sourcing the whole file, so POSTGRES_PASSWORD is never loaded
# into this script's environment at all.
POSTGRES_USER="$(grep -E '^POSTGRES_USER=' .env | tail -n1 | cut -d= -f2-)"
POSTGRES_DB="$(grep -E '^POSTGRES_DB=' .env | tail -n1 | cut -d= -f2-)"
: "${POSTGRES_USER:?POSTGRES_USER not set in .env}"
: "${POSTGRES_DB:?POSTGRES_DB not set in .env}"

BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backups}"
mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_PATH="$BACKUP_DIR/${TIMESTAMP}.dump"

cleanup_on_failure() {
  local status=$?
  if [ "$status" -ne 0 ] && [ -f "$DUMP_PATH" ]; then
    rm -f "$DUMP_PATH"
  fi
}
trap cleanup_on_failure EXIT

docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom > "$DUMP_PATH"

if [ ! -s "$DUMP_PATH" ]; then
  echo "Backup failed: $DUMP_PATH was not created or is empty." >&2
  exit 1
fi

echo "Backup created: $DUMP_PATH"
