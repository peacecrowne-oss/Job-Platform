#!/usr/bin/env bash
# STORY-054: the fast, no-Docker-required validation path -- what STORY-053
# (CI/CD, not yet built) can invoke later. Does NOT run backend/Redis/
# Postgres integration tests or the frontend E2E suite, both of which
# require the Docker Compose stack already running with seeded fixtures
# (see README.md's "Tests" section for those commands).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== backend: fast (non-integration) suite =="
(cd "$REPO_ROOT/backend" && python -m pytest -m "not integration")

echo "== frontend: unit/component suite =="
(cd "$REPO_ROOT/frontend" && npm test)

echo "== frontend: production build + type-check =="
(cd "$REPO_ROOT/frontend" && npm run build)

echo "All fast checks passed."
