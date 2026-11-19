#!/usr/bin/env bash
# End-to-end auth smoke test against a running backend (local or deployed).
#
#   BASE_URL=https://driveradar-api.onrender.com ORIGIN=http://localhost:5173 \
#   INVITE_CODE=... bash scripts/smoke_auth.sh
#
# Creates one throwaway account (smoke-<timestamp>@example.com), then runs
# register -> login -> save profile -> /me -> logout -> /me and checks each status code.
# The invite code comes from the environment so it never lands in shell history or Git.
set -euo pipefail

: "${BASE_URL:?set BASE_URL}" "${ORIGIN:?set ORIGIN (must be in ALLOWED_ORIGINS)}"
: "${INVITE_CODE:?set INVITE_CODE}"

JAR="$(mktemp)"; BODY="$(mktemp)"
trap 'rm -f "$JAR" "$BODY"' EXIT
EMAIL="smoke-$(date +%s)@example.com"
PASSWORD="smoke-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"
FAILED=0

check() {  # check <expected status> <label> <curl args...>
  local expected="$1" label="$2"; shift 2
  local status
  status="$(curl -sS -b "$JAR" -c "$JAR" -o "$BODY" -w '%{http_code}' -H "Origin: $ORIGIN" "$@")"
  if [[ "$status" == "$expected" ]]; then
    printf 'ok    %-22s %s\n' "$label" "$status"
  else
    printf 'FAIL  %-22s got %s, expected %s: %s\n' "$label" "$status" "$expected" "$(cat "$BODY")"
    FAILED=1
  fi
}

json=(-H "Content-Type: application/json")
# Render's free plan sleeps when idle; the first request can take up to a minute.
check 200 "healthz (wakes server)" --max-time 90 "$BASE_URL/healthz"
check 200 "readyz (DB reachable)" "$BASE_URL/readyz"
check 201 "register" -X POST "${json[@]}" "$BASE_URL/auth/register" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"name\":\"Smoke Test\",\"invite_code\":\"$INVITE_CODE\"}"
check 401 "me before login" "$BASE_URL/me"
check 200 "login" -X POST "${json[@]}" "$BASE_URL/auth/login" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
check 200 "save profile" -X PUT "${json[@]}" "$BASE_URL/me/profile" \
  -d '{"branch_code":"CSE","cgpa":8.0,"active_backlogs":0,"grad_year":2027}'
check 200 "me with profile" "$BASE_URL/me"
check 204 "logout" -X POST "$BASE_URL/auth/logout"
check 401 "me after logout" "$BASE_URL/me"

if [[ "$FAILED" == 0 ]]; then echo "ALL PASSED ($EMAIL)"; else echo "SOME CHECKS FAILED"; exit 1; fi
