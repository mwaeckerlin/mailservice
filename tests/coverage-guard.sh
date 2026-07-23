#!/usr/bin/env bash
# Coverage guard: FEATURES.md and TESTS.md must stay consistent.
#
# Fails when
#   1. a feature number is assigned twice in FEATURES.md,
#   2. a numbered feature has no single test referencing it in TESTS.md,
#   3. TESTS.md references a feature number that does not exist.
#
# This is the coverage that matters — every user-visible feature keeps
# at least one registered, executed test — rather than a percentage of
# code lines. Usage: tests/coverage-guard.sh

set -uo pipefail

cd "$(dirname "$0")/.."

PASS=0
FAIL=0
declare -a FAILED_NAMES

_pass() { PASS=$((PASS + 1)); echo "  PASS  $1"; }
_fail() { FAIL=$((FAIL + 1)); FAILED_NAMES+=("$1"); echo "  FAIL  $1: $2"; }

echo "==> Coverage guard: FEATURES.md vs TESTS.md"

if [[ ! -f FEATURES.md || ! -f TESTS.md ]]; then
    _fail "files_present" "FEATURES.md or TESTS.md missing"
    echo "==> Coverage guard results: ${PASS} passed, ${FAIL} failed"
    exit 1
fi

# feature numbers are declared as list items: "- **F<n> — ..."
mapfile -t FEATURES < <(grep -oE '^\- \*\*F[0-9]+' FEATURES.md | grep -oE 'F[0-9]+')
# every F<n> word in TESTS.md counts as a reference
mapfile -t REFS < <(grep -oE '\bF[0-9]+\b' TESTS.md | sort -u)

if [[ ${#FEATURES[@]} -eq 0 ]]; then
    _fail "features_numbered" "no numbered features found in FEATURES.md"
else
    _pass "features_numbered (${#FEATURES[@]} features)"
fi

# 1. duplicate feature numbers
DUPES=$(printf '%s\n' "${FEATURES[@]}" | sort | uniq -d)
if [[ -n "${DUPES}" ]]; then
    _fail "unique_feature_numbers" "assigned more than once: ${DUPES//$'\n'/ }"
else
    _pass "unique_feature_numbers"
fi

# 2. every feature has at least one test reference
MISSING=""
for f in "${FEATURES[@]}"; do
    if ! printf '%s\n' "${REFS[@]}" | grep -qx "${f}"; then
        MISSING="${MISSING} ${f}"
    fi
done
if [[ -n "${MISSING}" ]]; then
    _fail "every_feature_tested" "no test registered for:${MISSING}"
else
    _pass "every_feature_tested"
fi

# 3. no dangling references
DANGLING=""
for r in "${REFS[@]}"; do
    if ! printf '%s\n' "${FEATURES[@]}" | grep -qx "${r}"; then
        DANGLING="${DANGLING} ${r}"
    fi
done
if [[ -n "${DANGLING}" ]]; then
    _fail "no_dangling_references" "TESTS.md references unknown feature:${DANGLING}"
else
    _pass "no_dangling_references"
fi

echo ""
echo "==> Coverage guard results: ${PASS} passed, ${FAIL} failed"
if [[ ${FAIL} -gt 0 ]]; then
    echo "==> Failed checks: ${FAILED_NAMES[*]}"
    exit 1
fi
