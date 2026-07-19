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
# Persistent cache for the ClamAV signature DB (~300 MB): declared
# `external` in the compose file so `down -v` keeps it and only the
# very first run pays the freshclam download.
docker volume create mailservice-e2e-clamav-db >/dev/null
# The e2e compose BUILDS the mailservice-own images (postfix, dovecot,
# rspamd, clamav, postfixadmin, snappymail …) so this run also verifies
# those images build correctly. Foreign images (mwaeckerlin/redis,
# mwaeckerlin/fake-smtp) come via `image:` — built and tested in their
# own repositories; a locally built image wins, otherwise Docker pulls
# from the hub at `up` time.
docker compose -f "$COMPOSE" build --quiet

echo "==> Running image contract tests..."
# Every own image in the stack is headless — a compiled init is the
# entrypoint, no shell, no busybox, no perl. (redis is foreign — its
# headless contract is verified in the mwaeckerlin/redis repository,
# not here.)
bash tests/image-contract.sh \
    e2e-rspamd e2e-rspamd-strict e2e-rspamd-log \
    e2e-clamav \
    e2e-postfix e2e-postfix-strict e2e-postfix-log e2e-postfix-nocert \
    e2e-dovecot \
    e2e-smtp-relay e2e-smtp-relay-tls e2e-mailforward \
    e2e-postfixadmin e2e-postfixadmin-proxy e2e-snappymail e2e-snappymail-proxy
bash tests/snappymail-gnupg.sh e2e-snappymail

echo "==> Starting services..."
docker compose -f "$COMPOSE" up -d --remove-orphans \
    redis clamav \
    rspamd rspamd-strict rspamd-log \
    postfix postfix-strict postfix-log postfix-nocert \
    dovecot dns fake-smtp \
    smtp-relay smtp-relay-tls mailforward \
    postfixadmin-db postfixadmin postfixadmin-proxy \
    snappymail snappymail-proxy

echo "==> Running tests..."
EXIT=0
# `compose run` with arguments REPLACES the service command entirely —
# prepend the pytest invocation so `bash tests/run-e2e.sh -k foo`
# actually selects tests instead of exec'ing "-k" as the entrypoint.
docker compose -f "$COMPOSE" run --rm test-runner pytest -v --tb=short "$@" || EXIT=$?

echo "==> Collecting logs on failure..."
if [[ $EXIT -ne 0 ]]; then
    # per-service tail — a shared tail lets the chattiest service
    # (dovecot) crowd out the decision logs of the others
    for svc in postfix postfix-strict postfix-log \
               rspamd rspamd-strict rspamd-log \
               redis clamav dovecot \
               smtp-relay smtp-relay-tls mailforward; do
        echo "---- ${svc} ----"
        docker compose -f "$COMPOSE" logs --tail 120 "$svc" 2>&1
    done
fi

exit $EXIT
