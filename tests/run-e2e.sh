#!/usr/bin/env bash
# Run the full mailservice e2e test suite.
# Usage: bash tests/run-e2e.sh [pytest-args...]
set -euo pipefail

COMPOSE="tests/e2e/docker-compose.yml"
cd "$(dirname "$0")/.."

cleanup() {
    docker compose -f "$COMPOSE" down -v --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

echo "==> Building test stack..."
docker compose -f "$COMPOSE" build --quiet

echo "==> Starting services..."
docker compose -f "$COMPOSE" up -d --remove-orphans \
    postfix dovecot postgrey opendkim dns db fake-smtp \
    postfixadmin-db postfixadmin postfixadmin-proxy \
    snappymail snappymail-proxy

echo "==> Running tests..."
docker compose -f "$COMPOSE" run --rm test-runner "$@"
EXIT=$?

echo "==> Collecting logs on failure..."
if [[ $EXIT -ne 0 ]]; then
    docker compose -f "$COMPOSE" logs postfix dovecot postgrey 2>&1 | tail -100
fi

exit $EXIT
