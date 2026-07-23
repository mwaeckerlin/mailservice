#!/usr/bin/env bash
# Queue persistence end-to-end (F4/F15): an accepted-but-undelivered
# mail survives the DESTRUCTION and recreation of its container and is
# delivered afterwards — the migration guarantee «once the server said
# 250, the mail can no longer be lost».
#
# Choreography:
#   1. start dns + mailforward, target MX (fake-smtp) stays DOWN
#   2. submit a mail for the mapped alias → 250, delivery defers
#   3. prove the store is still empty (the test would otherwise be void)
#   4. DESTROY the mailforward container, recreate it (same named volume)
#   5. start the target MX, flush the queue
#   6. the mail arrives in the target store — nothing was lost
#
# Usage: tests/queue-persistence.sh

set -euo pipefail

COMPOSE="tests/queue-persistence/docker-compose.yml"
cd "$(dirname "$0")/.."

cleanup() {
    docker compose -f "$COMPOSE" down -v --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

_diag() {
    echo "---- docker compose ps ----"
    docker compose -f "$COMPOSE" ps
    echo "---- mailforward log tail ----"
    docker compose -f "$COMPOSE" logs --tail 80 mailforward 2>&1
    echo "---- dns log tail ----"
    docker compose -f "$COMPOSE" logs --tail 20 dns 2>&1
}

SUBJECT="queue-persist-$$-${RANDOM}${RANDOM}"

echo "==> Queue persistence: building and starting (target MX stays down)..."
cleanup
docker compose -f "$COMPOSE" build --quiet dns mailforward
docker compose -f "$COMPOSE" up -d dns mailforward

echo "==> Waiting for mailforward SMTP..."
# the check must see the SMTP BANNER, not just a TCP connect — the
# docker proxy accepts connections before smtpd listens. curl's smtp://
# «connection phase» covers banner + EHLO, so a generous timeout is the
# correct readiness probe.
for i in $(seq 1 60); do
    if curl -s --connect-timeout 8 --max-time 10 \
            smtp://127.0.0.1:47925 >/dev/null 2>&1; then
        break
    fi
    if [[ $i -eq 60 ]]; then
        echo "FAIL: mailforward did not come up"
        _diag
        exit 1
    fi
    sleep 1
done

echo "==> Submitting mail (subject ${SUBJECT})..."
MAILFILE=$(mktemp)
printf 'From: sender@fwd.local\r\nTo: forward@fwd.local\r\nSubject: %s\r\n\r\nqueue persistence probe\r\n' \
    "$SUBJECT" > "$MAILFILE"
if ! curl -s --max-time 60 \
        smtp://127.0.0.1:47925 \
        --mail-from sender@fwd.local \
        --mail-rcpt forward@fwd.local \
        --upload-file "$MAILFILE"; then
    rm -f "$MAILFILE"
    echo "FAIL: mailforward did not accept the mail (no 250) — nothing to persist"
    _diag
    exit 1
fi
rm -f "$MAILFILE"
echo "    accepted (250) — server now owns delivery"

echo "==> Verifying the mail is NOT yet delivered (target MX is down)..."
if docker compose -f "$COMPOSE" run --rm -e SUBJECT="$SUBJECT" verify >/dev/null 2>&1; then
    echo "FAIL: mail already in the target store — the deferred state was never reached"
    exit 1
fi

echo "==> Destroying and recreating the mailforward container..."
docker compose -f "$COMPOSE" rm -sf mailforward
docker compose -f "$COMPOSE" up -d mailforward

echo "==> Starting the target MX and flushing the queue..."
docker compose -f "$COMPOSE" up -d fake-smtp
for i in $(seq 1 30); do
    if curl -s --connect-timeout 8 --max-time 10 \
            smtp://127.0.0.1:47925 >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

echo "==> Waiting for delivery of the queued mail..."
DELIVERED=0
for i in $(seq 1 45); do
    # deferred-queue retry intervals are minutes — flush on every poll
    # so the recreated postfix retries immediately
    docker compose -f "$COMPOSE" exec mailforward /usr/sbin/postqueue -f >/dev/null 2>&1 || true
    if docker compose -f "$COMPOSE" run --rm -e SUBJECT="$SUBJECT" verify >/dev/null 2>&1; then
        DELIVERED=1
        break
    fi
    sleep 2
done

if [[ $DELIVERED -ne 1 ]]; then
    echo "FAIL: queued mail was NOT delivered after the container recreate —"
    echo "      an accepted mail was lost; the queue volume contract is broken."
    echo "---- mailforward log tail ----"
    docker compose -f "$COMPOSE" logs --tail 80 mailforward
    exit 1
fi

echo ""
echo "==> PASS: accepted mail survived the container recreate and was delivered."
