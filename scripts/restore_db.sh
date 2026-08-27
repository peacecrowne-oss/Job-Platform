#!/usr/bin/env bash
# STORY-055: restore-validation script. SAFE BY DEFAULT -- restores into a
# dedicated, disposable scratch database that this script itself creates
# and drops. Never touches the primary application database; refuses to
# run at all if the requested scratch name collides with it or with a
# Postgres-reserved database name. See README.md's "Backups" section.
#
# Usage: scripts/restore_db.sh <dump-file> [scratch-db-name]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ $# -lt 1 ]; then
  echo "Usage: $0 <dump-file> [scratch-db-name]" >&2
  exit 1
fi

DUMP_PATH="$1"
SCRATCH_DB="${2:-job_platform_restore_scratch}"

if [ ! -s "$DUMP_PATH" ]; then
  echo "Dump file missing or empty: $DUMP_PATH" >&2
  exit 1
fi

# SQL-injection guard: SCRATCH_DB is also passed through psql's `:"var"`
# substitution below (which quotes it safely as an identifier), but this
# charset check is an independent second line of defense -- reject
# anything that isn't a plain identifier before it ever reaches psql.
if ! [[ "$SCRATCH_DB" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "Invalid scratch database name (must match ^[A-Za-z_][A-Za-z0-9_]*\$): $SCRATCH_DB" >&2
  exit 1
fi

if [ ! -f .env ]; then
  echo "Missing .env (copy .env.example to .env first)." >&2
  exit 1
fi

# Plain identifiers, not secrets -- read only these two lines out of .env
# rather than sourcing the whole file, so POSTGRES_PASSWORD is never loaded
# into this script's environment at all. psql/pg_restore below run *inside*
# the postgres container via `docker compose exec`, connecting over its
# local unix socket under the same trust auth the existing `pg_isready`
# healthcheck (docker-compose.yml) already relies on.
POSTGRES_USER="$(grep -E '^POSTGRES_USER=' .env | tail -n1 | cut -d= -f2-)"
POSTGRES_DB="$(grep -E '^POSTGRES_DB=' .env | tail -n1 | cut -d= -f2-)"
: "${POSTGRES_USER:?POSTGRES_USER not set in .env}"
: "${POSTGRES_DB:?POSTGRES_DB not set in .env}"

for reserved in "$POSTGRES_DB" postgres template0 template1; do
  if [ "$SCRATCH_DB" = "$reserved" ]; then
    echo "Refusing to use '$SCRATCH_DB' as the restore-validation target (primary application database or Postgres-reserved name)." >&2
    exit 1
  fi
done

cleanup() {
  echo "Dropping scratch database: $SCRATCH_DB"
  docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
    -v scratch="$SCRATCH_DB" >/dev/null <<'SQL'
DROP DATABASE IF EXISTS :"scratch";
SQL
}
trap cleanup EXIT

# psql's `:"var"` identifier substitution is only applied when reading a
# script (stdin/-f), not for -c strings -- hence the heredocs here and below
# rather than -c.
echo "Creating scratch database: $SCRATCH_DB"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -v scratch="$SCRATCH_DB" >/dev/null <<'SQL'
DROP DATABASE IF EXISTS :"scratch";
CREATE DATABASE :"scratch";
SQL

echo "Restoring $DUMP_PATH into scratch database: $SCRATCH_DB"
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$SCRATCH_DB" --no-owner < "$DUMP_PATH"

echo "Tables restored into $SCRATCH_DB:"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$SCRATCH_DB" -t -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';"

echo "Restore validation succeeded (scratch database will be dropped on exit)."
