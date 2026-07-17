#!/usr/bin/env bash
# Image-level test for the opendkim init: with several DOMAINS it must generate
# a key per domain and print the DNS TXT record banner for each one. Runs
# BEFORE the e2e stack starts, because the pytest suite runs inside the
# test-runner container, which has no docker socket and cannot inspect a
# container's startup log.
#
# Usage: tests/opendkim-multidomain.sh [IMAGE]   (default: e2e-opendkim)

set -uo pipefail

IMAGE="${1:-e2e-opendkim}"
NAME="opendkim-contract-multidomain-$$"

echo "==> opendkim multi-domain init"

docker rm -f "${NAME}" > /dev/null 2>&1
docker run -d --name "${NAME}" -e DOMAINS="alpha.local beta.local" "${IMAGE}" > /dev/null

# init prints the banners on stdout; wait a moment for both keys to be
# generated (2048-bit RSA × 2 domains ~ 1-3s)
sleep 5

LOG="$(docker logs "${NAME}" 2>&1)"
docker rm -f "${NAME}" > /dev/null 2>&1

if echo "${LOG}" | grep -q "add this DNS TXT record to alpha.local" \
   && echo "${LOG}" | grep -q "add this DNS TXT record to beta.local"; then
    echo "  PASS  opendkim_multi_domain_banners"
    exit 0
fi

echo "  FAIL  opendkim_multi_domain_banners: expected both alpha.local and beta.local DNS-record banners in log"
echo "----- container log -----"
echo "${LOG}"
echo "-------------------------"
exit 1
