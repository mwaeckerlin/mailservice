#!/usr/bin/env bash
# Compose contract: settings the production compose file must declare.
#
# Queue persistence: postfix answers 250 as soon as a mail is fsync'ed
# into its queue — from then on the server owns delivery and the sender
# never retries. A deferred mail must therefore survive any container
# recreate / image update: every postfix-based service needs
# /var/spool/postfix on a NAMED volume. `docker compose config` is used
# so the check sees the same normalized configuration docker uses.
#
# Usage: tests/compose-contract.sh

set -uo pipefail

cd "$(dirname "$0")/.."

PASS=0
FAIL=0
declare -a FAILED_NAMES

_pass() { PASS=$((PASS + 1)); echo "  PASS  $1"; }
_fail() { FAIL=$((FAIL + 1)); FAILED_NAMES+=("$1"); echo "  FAIL  $1: $2"; }

_queue_volume() {
    local svc="$1"
    local cfg
    if ! cfg=$(docker compose -f docker-compose.yml config "${svc}" 2>/dev/null); then
        _fail "${svc}_queue_volume" "service not found in docker-compose.yml"
        return
    fi
    if ! grep -q "target: /var/spool/postfix" <<<"${cfg}"; then
        _fail "${svc}_queue_volume" \
            "/var/spool/postfix is not a volume — a deferred mail vanishes on container recreate"
        return
    fi
    # a named volume has a `source:`; an anonymous one (bare target)
    # does not survive `docker compose down`
    if ! grep -B3 "target: /var/spool/postfix" <<<"${cfg}" | grep -q "source:"; then
        _fail "${svc}_queue_volume" "queue volume is anonymous — use a named volume"
        return
    fi
    _pass "${svc}_queue_volume"
}

_db_data_volume() {
    local cfg
    if ! cfg=$(docker compose -f docker-compose.yml config postfixadmin-db 2>/dev/null); then
        _fail "db_data_volume" "service postfixadmin-db not found"
        return
    fi
    # mariadb/mysql store their data in /var/lib/mysql — a volume on
    # any other path (e.g. /usr/lib/mysql) silently persists NOTHING:
    # every recreate drops all accounts and password hashes
    if ! grep -q "target: /var/lib/mysql" <<<"${cfg}"; then
        _fail "db_data_volume" \
            "postfixadmin-db has no volume on /var/lib/mysql — account data is lost on recreate"
        return
    fi
    if ! grep -B3 "target: /var/lib/mysql" <<<"${cfg}" | grep -q "source:"; then
        _fail "db_data_volume" "db data volume is anonymous — use a named volume"
        return
    fi
    _pass "db_data_volume"
}

_db_image() {
    local cfg
    cfg=$(docker compose -f docker-compose.yml config postfixadmin-db 2>/dev/null)
    # the stack requires MariaDB 11+ (dovecot 2.4 TLS, see README); a
    # rolling `mysql` image also breaks on 8.4 where the
    # --default-authentication-plugin switch was removed
    if grep -q "image: mariadb:11" <<<"${cfg}"; then
        _pass "db_image_mariadb"
    else
        _fail "db_image_mariadb" \
            "postfixadmin-db must run mariadb:11 (see README), not a rolling mysql image"
    fi
}

_loopback_only() {
    local svc="$1" port="$2"
    local cfg
    cfg=$(docker compose -f docker-compose.yml config "${svc}" 2>/dev/null)
    # published: "0.0.0.0" would expose the unencrypted admin UI on
    # every interface — the production stack puts a TLS reverse proxy
    # in front and publishes only on loopback (README «Trade-off»)
    if grep -B3 -A3 "published: \"${port}\"" <<<"${cfg}" | grep -q "host_ip: 127.0.0.1"; then
        _pass "${svc}_loopback_only"
    else
        _fail "${svc}_loopback_only" \
            "${svc} publishes ${port} on all interfaces — bind it to 127.0.0.1 (TLS proxy in front)"
    fi
}

echo "==> Compose contract: persistent mail queues"

for svc in postfix mailforward; do
    _queue_volume "${svc}"
done

echo "==> Compose contract: database persistence and engine"

_db_data_volume
_db_image

echo "==> Compose contract: unencrypted admin UI stays on loopback"

_loopback_only postfixadmin-proxy 8080

# Self-test of the detection: a service WITHOUT a queue volume
# (dovecot) must not match — guards against `docker compose config
# SERVICE` ever ignoring the service filter, which would turn the
# checks above vacuously green.
if docker compose -f docker-compose.yml config dovecot 2>/dev/null \
        | grep -q "target: /var/spool/postfix"; then
    _fail "selftest_negative_detection" \
        "dovecot appears to have a postfix queue volume — service filter broken?"
else
    _pass "selftest_negative_detection"
fi

echo ""
echo "==> Compose contract results: ${PASS} passed, ${FAIL} failed"
if [[ ${FAIL} -gt 0 ]]; then
    echo "==> Failed contracts: ${FAILED_NAMES[*]}"
    exit 1
fi
