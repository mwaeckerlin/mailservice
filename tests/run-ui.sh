#!/usr/bin/env bash
# Run the frontend UI test suite (PostfixAdmin + SnappyMail via Playwright).
# Usage: bash tests/run-ui.sh [pytest-args...]
set -euo pipefail

BASE="tests/e2e/docker-compose.yml"
OVERLAY="tests/e2e/docker-compose.ui.yml"
cd "$(dirname "$0")/.."

cleanup() {
    docker compose -f "$BASE" -f "$OVERLAY" down -v --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

echo "==> Building UI test stack..."
docker compose -f "$BASE" -f "$OVERLAY" build --quiet

echo "==> Starting services..."
docker compose -f "$BASE" -f "$OVERLAY" up -d --remove-orphans \
    postfix dovecot postgrey opendkim dns db fake-smtp \
    postfixadmin-db postfixadmin postfixadmin-proxy \
    snappymail snappymail-proxy

echo "==> Running UI tests..."
docker compose -f "$BASE" -f "$OVERLAY" run --rm ui-test-runner "$@"
EXIT=$?

echo "==> Collecting logs on failure..."
if [[ $EXIT -ne 0 ]]; then
    docker compose -f "$BASE" -f "$OVERLAY" logs postfix dovecot postfixadmin snappymail 2>&1 | tail -150
fi

exit $EXIT
