#!/usr/bin/env bash
# Run the end-to-end suite of the version-1 line against the PUBLISHED
# images. Usage: bash tests/run-v1.sh [pytest-args...]
set -euo pipefail

COMPOSE="tests/v1/docker-compose.yml"
cd "$(dirname "$0")/.."

cleanup() {
    docker compose -f "$COMPOSE" down -v --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

# A killed previous run skips the EXIT trap and leaves a warm stack
# behind; its greylist and mailbox state would produce phantom results.
cleanup

echo "==> Pulling the published images of the 1 line..."
# Only the test-runner and the resolver are built here. Every
# mailservice image is pulled, because the subject of this suite is what
# the hub serves, not what this working tree would build.
docker compose -f "$COMPOSE" pull --quiet \
    postfixadmin postfixadmin-proxy postgrey dovecot postfix \
    snappymail snappymail-proxy fake-smtp postfixadmin-db

echo "==> Building the test runner..."
docker compose -f "$COMPOSE" build --quiet test-runner dns snappymail-init

echo "==> Starting services..."
if ! docker compose -f "$COMPOSE" up -d --remove-orphans \
    dns fake-smtp postfixadmin-db postfixadmin postfixadmin-proxy \
    postgrey dovecot postfix snappymail snappymail-proxy; then
    echo "==> Startup failed — one-shot service logs:"
    for svc in certs-init snappymail-init; do
        echo "---- ${svc} ----"
        docker compose -f "$COMPOSE" logs --tail 120 "$svc" 2>&1
    done
    exit 1
fi

echo "==> Running tests..."
EXIT=0
docker compose -f "$COMPOSE" run --rm test-runner pytest -v --tb=short "$@" || EXIT=$?

if [[ $EXIT -ne 0 ]]; then
    # Branch 1 logs auth debug by default, which floods the tail of the
    # dovecot log and buries the delivery error. Pull the lines that
    # matter out of the whole log first.
    echo "---- dovecot: errors and sieve ----"
    docker compose -f "$COMPOSE" logs --no-color dovecot 2>&1 \
        | grep -iE 'error|fatal|warning|sieve|lmtp' | tail -80 || true

    echo "==> Collecting logs on failure..."
    for svc in postfix dovecot postgrey postfixadmin postfixadmin-proxy \
               snappymail snappymail-proxy fake-smtp dns certs-init \
               snappymail-init; do
        echo "---- ${svc} ----"
        docker compose -f "$COMPOSE" logs --tail 120 "$svc" 2>&1
    done
fi

exit $EXIT
