#!/usr/bin/env bash
# Contract: the snappymail php-fpm image ships the php-gnupg extension
# (server-side OpenPGP for the webmail) and the gpg binary that gpgme
# execs at runtime.
#
# Usage: tests/snappymail-gnupg.sh IMAGE
set -uo pipefail

IMAGE="${1:?usage: $0 IMAGE}"
PASS=0
FAIL=0

_pass() { PASS=$((PASS + 1)); echo "  PASS  $1"; }
_fail() { FAIL=$((FAIL + 1)); echo "  FAIL  $1: $2"; }

echo "==> SnappyMail php-gnupg contract"

if docker run --rm --pull=never --entrypoint /usr/sbin/php-fpm "${IMAGE}" -m 2>/dev/null \
        | grep -qi '^gnupg$'; then
    _pass "${IMAGE}_php_gnupg_module"
else
    _fail "${IMAGE}_php_gnupg_module" "php-fpm -m does not list gnupg"
fi

if docker run --rm --pull=never --entrypoint /usr/bin/gpg "${IMAGE}" --version > /dev/null 2>&1; then
    _pass "${IMAGE}_gpg_binary"
else
    _fail "${IMAGE}_gpg_binary" "/usr/bin/gpg missing or unrunnable (gpgme needs it)"
fi

echo ""
echo "==> SnappyMail php-gnupg results: ${PASS} passed, ${FAIL} failed"
[[ ${FAIL} -eq 0 ]] || exit 1
