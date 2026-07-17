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

echo "==> Running image contract tests..."
# postfix, dovecot, postgrey, smtp-relay(-tls) and mailforward still boot via a
# shell script and therefore still ship a shell — they join the contract once
# their entrypoint is a binary, like opendkim's.
bash tests/image-contract.sh \
    e2e-opendkim e2e-opendmarc \
    e2e-postfixadmin e2e-postfixadmin-proxy e2e-snappymail e2e-snappymail-proxy
bash tests/opendkim-multidomain.sh
bash tests/dkim-dmarc-mode.sh

echo "==> Starting services..."
docker compose -f "$COMPOSE" up -d --remove-orphans \
    postfix postfix-strict postfix-log \
    opendkim opendkim-strict opendkim-log \
    opendmarc opendmarc-log \
    dovecot postgrey dns fake-smtp \
    postfixadmin-db postfixadmin postfixadmin-proxy \
    snappymail snappymail-proxy

echo "==> Running tests..."
EXIT=0
docker compose -f "$COMPOSE" run --rm test-runner "$@" || EXIT=$?

echo "==> Collecting logs on failure..."
if [[ $EXIT -ne 0 ]]; then
    docker compose -f "$COMPOSE" logs postfix postfix-strict opendkim-strict dovecot postgrey 2>&1 | tail -200
fi

exit $EXIT
