#!/usr/bin/env bash
# Config-level test for the DKIM_DMARC single-knob env. For each of the
# four modes (off/log/permissive/reject) start opendkim (or opendmarc)
# briefly, dump the runtime config it composed into /run/, and assert
# the expected directives are present or absent.
#
# Runs BEFORE the e2e stack because pytest inside the test-runner has no
# docker socket and cannot inspect a container's runtime files.

set -uo pipefail

PASS=0
FAIL=0
declare -a FAILED

_pass() { PASS=$((PASS + 1)); echo "  PASS  $1"; }
_fail() { FAIL=$((FAIL + 1)); FAILED+=("$1"); echo "  FAIL  $1: $2"; }

# ------------------------------------------------- helpers -----------------

_run_and_dump() {
    # $1=container-name  $2=image  $3=path-in-container  $@=env-args
    local name="$1" image="$2" runtime_path="$3"; shift 3
    docker rm -f "${name}" > /dev/null 2>&1
    docker run -d --name "${name}" "$@" "${image}" > /dev/null
    # init.cpp writes the runtime config and then exec's the daemon —
    # a tiny grace period lets it happen before we copy the file out.
    sleep 2
    docker cp "${name}:${runtime_path}" - 2>/dev/null | tar -xO
    docker rm -f "${name}" > /dev/null 2>&1
}

_assert_grep()   { echo "$1" | grep -q -- "$2"    && _pass "$3" || _fail "$3" "expected: $2"; }
_assert_no()     { echo "$1" | grep -q -- "$2"    && _fail "$3" "unexpected: $2" || _pass "$3"; }

# --------------------------------------------- opendkim modes --------------

echo "==> DKIM_DMARC modes on e2e-opendkim"

for mode in off log permissive reject; do
    conf="$(_run_and_dump "dkim-mode-${mode}-$$" e2e-opendkim \
        /run/opendkim/opendkim.conf \
        -e DOMAINS=alpha.local -e DKIM_DMARC="${mode}")"

    case "${mode}" in
        off)
            _assert_grep "${conf}" "^Mode *s$"                 "opendkim_${mode}_mode_s"
            _assert_no   "${conf}" "^On-BadSignature"          "opendkim_${mode}_no_on_badsig"
            _assert_no   "${conf}" "^On-KeyNotFound"           "opendkim_${mode}_no_on_keynotfound"
            _assert_no   "${conf}" "^On-NoSignature"           "opendkim_${mode}_no_on_nosig"
            ;;
        log)
            _assert_grep "${conf}" "^Mode *sv$"                "opendkim_${mode}_mode_sv"
            _assert_grep "${conf}" "^AlwaysAddARHeader *true$" "opendkim_${mode}_always_ar_header"
            _assert_no   "${conf}" "^On-BadSignature"          "opendkim_${mode}_no_on_badsig"
            _assert_no   "${conf}" "^On-KeyNotFound"           "opendkim_${mode}_no_on_keynotfound"
            _assert_no   "${conf}" "^On-NoSignature"           "opendkim_${mode}_no_on_nosig"
            ;;
        permissive)
            _assert_grep "${conf}" "^Mode *sv$"                "opendkim_${mode}_mode_sv"
            _assert_grep "${conf}" "^On-BadSignature *reject"  "opendkim_${mode}_badsig_reject"
            _assert_grep "${conf}" "^On-KeyNotFound *reject"   "opendkim_${mode}_keynotfound_reject"
            _assert_no   "${conf}" "^On-NoSignature"           "opendkim_${mode}_no_on_nosig"
            ;;
        reject)
            _assert_grep "${conf}" "^Mode *sv$"                "opendkim_${mode}_mode_sv"
            _assert_grep "${conf}" "^On-BadSignature *reject"  "opendkim_${mode}_badsig_reject"
            _assert_grep "${conf}" "^On-KeyNotFound *reject"   "opendkim_${mode}_keynotfound_reject"
            _assert_grep "${conf}" "^On-NoSignature *reject"   "opendkim_${mode}_nosig_reject"
            ;;
    esac
done

# DKIM_KEYERROR_ACTION=tempfail lowers the two reject actions to tempfail.
conf="$(_run_and_dump "dkim-mode-tempfail-$$" e2e-opendkim \
    /run/opendkim/opendkim.conf \
    -e DOMAINS=alpha.local -e DKIM_DMARC=permissive -e DKIM_KEYERROR_ACTION=tempfail)"
_assert_grep "${conf}" "^On-BadSignature *tempfail" "opendkim_keyerror_tempfail_badsig"
_assert_grep "${conf}" "^On-KeyNotFound *tempfail"  "opendkim_keyerror_tempfail_keynotfound"

# --------------------------------------------- opendmarc modes -------------

echo "==> DKIM_DMARC modes on e2e-opendmarc"

for mode in off log permissive reject; do
    conf="$(_run_and_dump "dmarc-mode-${mode}-$$" e2e-opendmarc \
        /run/opendmarc/opendmarc.conf \
        -e DKIM_DMARC="${mode}")"

    case "${mode}" in
        off|log)
            _assert_grep "${conf}" "^RejectFailures *false" "opendmarc_${mode}_reject_false"
            ;;
        permissive|reject)
            _assert_grep "${conf}" "^RejectFailures *true"  "opendmarc_${mode}_reject_true"
            ;;
    esac
done

# --------------------------------------------- summary --------------------

echo ""
echo "==> DKIM_DMARC mode results: ${PASS} passed, ${FAIL} failed"
if [[ ${FAIL} -gt 0 ]]; then
    echo "==> Failed checks: ${FAILED[*]}"
    exit 1
fi
