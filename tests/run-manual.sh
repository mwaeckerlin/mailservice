#!/usr/bin/env bash
# Bring up the isolated e2e test stack for MANUAL testing in a browser.
#
# Same stack as `npm test` (domain test.local), with the web UIs and mail ports
# published to the host and left running. One shared database — accounts you
# create in PostfixAdmin are the ones the webmail uses. Host ports are fixed but
# uncommon (478xx) so collisions are unlikely — see
# tests/e2e/docker-compose.manual.yml to change them. Fully isolated: the
# bundled DNS server runs no-resolv, so no mail can ever reach the internet.
#
# Stop with:  npm run test:manual:stop   (preserves data)
#             add  -v  to also wipe the volumes.
set -euo pipefail

cd "$(dirname "$0")/.."
FILES=(-f tests/e2e/docker-compose.yml -f tests/e2e/docker-compose.manual.yml)

echo "==> Building stack..."
docker compose "${FILES[@]}" build

echo "==> Starting services (without the automated test-runner)..."
docker compose "${FILES[@]}" up -d --remove-orphans \
    postfix dovecot postgrey opendkim dns fake-smtp \
    postfixadmin-db postfixadmin postfixadmin-proxy \
    snappymail snappymail-proxy

# PostfixAdmin creates its database schema on the first hit to setup.php.
# Without this, every other page (login.php, …) returns HTTP 500 until the
# admin happens to open setup.php first. Prime it so the UI works right away.
echo "==> Initialising PostfixAdmin database (priming setup.php)..."
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://localhost:47808/setup.php"; then break; fi
    sleep 1
done

cat <<'EOF'

================================================================
  Manual test stack is UP — fully isolated, no internet mail.
----------------------------------------------------------------
  PostfixAdmin         http://localhost:47808/setup.php  (setup: test123)
  SnappyMail admin     http://localhost:47880/?admin     (admin / 12345)
  SnappyMail webmail   http://localhost:47880/

  One shared database — manage accounts in PostfixAdmin, use them in the webmail.
  First-time setup, in order:
    1. PostfixAdmin → /setup.php : enter setup password, create an admin.
    2. PostfixAdmin → log in, add the domain "test.local",
       then add mailboxes, e.g. alice@test.local and bob@test.local
       (passwords need >=5 chars, >=3 letters, >=2 digits, e.g. alicepass12).
    3. SnappyMail admin → add domain "test.local":
         IMAP host: dovecot  port 143
         SMTP host: postfix  port 25
       (internal container ports; persists in the volume; only needed once)
    4. SnappyMail webmail → log in with the addresses you created in step 2.

  Host mail ports:  SMTP localhost:47825   IMAP localhost:47843   POP3 localhost:47810
  List outbound mail caught by the trap (never sent out):
      docker compose -f tests/e2e/docker-compose.yml \
        -f tests/e2e/docker-compose.manual.yml exec fake-smtp ls /mails

  Stop:  npm run test:manual:stop
================================================================
EOF
