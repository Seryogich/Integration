#!/usr/bin/env bash
# Acceptance tests T1, T2, T4-T10, T12 against the running stack.
#   docker compose up -d --build
#   ./scripts/verify.sh            (output is also written to logs/verify.log)
# T3 and T11 change/remove secrets, so they live in scripts/experiments.sh
# (Experiment 2 = T3, Experiment 1 = T11).
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
exec > >(tee logs/verify.log) 2>&1

set -a; [[ -f .env ]] && . ./.env; set +a
BASE="http://localhost:${ORDERS_PORT:-8000}"
BODY="$(mktemp)"; HDRS="$(mktemp)"
trap 'rm -f "$BODY" "$HDRS"' EXIT

PASS=0; FAIL=0
ok()   { echo "PASS  $1  $2"; PASS=$((PASS+1)); }
bad()  { echo "FAIL  $1  $2"; FAIL=$((FAIL+1)); }
check() { # check ID "description" <command...>
  local id="$1" desc="$2"; shift 2
  if "$@"; then ok "$id" "$desc"; else bad "$id" "$desc"; fi
}
code() { curl -s -o "$BODY" -w '%{http_code}' "$@"; }
jget() { python3 -c 'import sys,json; v=json.load(sys.stdin)[sys.argv[1]]; print("null" if v is None else v)' "$1" < "$BODY"; }
wait_http() { # wait_http URL seconds
  local i; for ((i=0;i<$2;i++)); do [[ "$(curl -s -o /dev/null -w '%{http_code}' "$1")" == "200" ]] && return 0; sleep 1; done; return 1
}

echo "=== verification started $(date -Is) against $BASE ==="
wait_http "$BASE/health" 60 || { echo "Orders API is not reachable at $BASE - is the stack up?"; exit 2; }

DB_PW="$(cat secrets/db_password)"; JWT_KEY="$(cat secrets/jwt_secret_key)"

# ---- T1: docker compose config --------------------------------------------
CFG="$(docker compose config 2>&1)"
t1_values()  { ! grep -qF -e "$DB_PW" -e "$JWT_KEY" <<<"$CFG"; }
t1_paths()   { grep -q "secrets/db_password" <<<"$CFG" && grep -q "secrets/jwt_secret_key" <<<"$CFG"; }
t1_noports() { docker compose config --format json | python3 -c 'import sys,json; s=json.load(sys.stdin)["services"]; sys.exit(0 if "ports" not in s["forecast-api"] else 1)'; }
check T1 "compose config: no secret values"                t1_values
check T1 "compose config: secret file paths present"       t1_paths
check T1 "compose config: forecast-api has no ports"       t1_noports

# ---- T2: environment of containers -----------------------------------------
t2() { local svc="$1"; ! docker compose exec -T "$svc" env 2>/dev/null | grep -qF -e "$DB_PW" -e "$JWT_KEY"; }
check T2 "orders-api env contains no secret values"        t2 orders-api
check T2 "postgres env contains no secret values"          t2 postgres
t2_files() { docker compose exec -T orders-api sh -c 'test -r /run/secrets/db_password && test -r /run/secrets/jwt_secret_key'; }
check T2 "secrets are available as files in /run/secrets"  t2_files

# ---- T4: forecast-api not published -----------------------------------------
t4() { ! curl -s --max-time 5 -o /dev/null http://localhost:8001/health; }
check T4 "curl localhost:8001 from host: connection refused" t4

# ---- public endpoints -------------------------------------------------------
check R2.7 "GET /health is public (200)" test "$(code "$BASE/health")" = "200"

# ---- T5: register ------------------------------------------------------------
USER="verify_$RANDOM$RANDOM"; PW="Passw0rd-$RANDOM-ok"
c="$(code -X POST "$BASE/auth/register" -H 'Content-Type: application/json' -d "{\"username\":\"$USER\",\"password\":\"$PW\"}")"
check T5 "POST /auth/register -> 201 (got $c)" test "$c" = "201"
check T5 "response has no hashed_password"     bash -c "! grep -q hashed_password '$BODY'"
c="$(code -X POST "$BASE/auth/register" -H 'Content-Type: application/json' -d "{\"username\":\"$USER\",\"password\":\"$PW\"}")"
check T5 "duplicate username -> 409 (got $c)"  test "$c" = "409"
c="$(code -X POST "$BASE/auth/register" -H 'Content-Type: application/json' -d "{\"username\":\"short_$RANDOM\",\"password\":\"abc\"}")"
check T5 "password too short -> 422 (got $c)"  test "$c" = "422"

# ---- T6: login -----------------------------------------------------------------
c="$(code -X POST "$BASE/auth/login" -d "username=$USER" --data-urlencode "password=$PW")"
check T6 "valid credentials -> 200 (got $c)" test "$c" = "200"
TOKEN="$(jget access_token)"
c1="$(code -X POST "$BASE/auth/login" -d "username=$USER&password=wrong-password")"; B1="$(cat "$BODY")"
c2="$(code -X POST "$BASE/auth/login" -d "username=nobody_$RANDOM&password=wrong-password")"; B2="$(cat "$BODY")"
check T6 "wrong password -> 401 (got $c1)"   test "$c1" = "401"
check T6 "unknown user   -> 401 (got $c2)"   test "$c2" = "401"
check T6 "identical error message"           test "$B1" = "$B2"
AUTH=(-H "Authorization: Bearer $TOKEN")
check T6 "GET /auth/me with token -> 200"    test "$(code "$BASE/auth/me" "${AUTH[@]}")" = "200"

# ---- T7: anonymous access ---------------------------------------------------------
curl -s -D "$HDRS" -o /dev/null "$BASE/orders"
check T7 "GET /orders without token -> 401"  grep -q '^HTTP/.* 401' "$HDRS"
check T7 "WWW-Authenticate: Bearer present"  grep -qi '^www-authenticate: bearer' "$HDRS"
check T7 "GET /auth/me without token -> 401" test "$(code "$BASE/auth/me")" = "401"
check T7 "POST /orders without token -> 401" test "$(code -X POST "$BASE/orders" -H 'Content-Type: application/json' -d '{}')" = "401"

# ---- T8: create order -----------------------------------------------------------------
ORDER='{"customer_name":"ACME Ltd","area_sqm":80,"bedrooms":3,"bathrooms":2,"year_built":2010}'
c="$(code -X POST "$BASE/orders" "${AUTH[@]}" -H 'Content-Type: application/json' -d "$ORDER")"
check T8 "POST /orders with token -> 201 (got $c)" test "$c" = "201"
OID="$(jget id)"; PRICE1="$(jget predicted_price)"
check T8 "predicted_price is set (got $PRICE1)"    test "$PRICE1" != "null"
check T8 "GET /orders and /orders/{id} -> 200"     bash -c "[[ \$(curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer $TOKEN' $BASE/orders) == 200 && \$(curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer $TOKEN' $BASE/orders/$OID) == 200 ]]"

# ---- T9: PATCH re-requests the forecast ----------------------------------------------------
c="$(code -X PATCH "$BASE/orders/$OID" "${AUTH[@]}" -H 'Content-Type: application/json' -d '{"area_sqm":200,"bedrooms":5}')"
PRICE2="$(jget predicted_price)"
check T9 "PATCH with property params -> 200 (got $c)"             test "$c" = "200"
check T9 "predicted_price updated ($PRICE1 -> $PRICE2)"           bash -c "[[ '$PRICE2' != 'null' && '$PRICE2' != '$PRICE1' ]]"

# ---- T10: delete --------------------------------------------------------------------------------
check T10 "DELETE /orders/{id} -> 204"  test "$(code -X DELETE "$BASE/orders/$OID" "${AUTH[@]}")" = "204"
check T10 "deleted order is gone (404)" test "$(code "$BASE/orders/$OID" "${AUTH[@]}")" = "404"

# ---- T12: forecast-api stopped ----------------------------------------------------------------------
docker compose stop forecast-api >/dev/null 2>&1
c="$(code -X POST "$BASE/orders" "${AUTH[@]}" -H 'Content-Type: application/json' -d "$ORDER")"
check T12 "forecast-api stopped: POST /orders -> 201 (got $c)"   test "$c" = "201"
check T12 "predicted_price is null"                              test "$(jget predicted_price)" = "null"
docker compose start forecast-api >/dev/null 2>&1
echo "(forecast-api restarted)"

echo "=== summary: $PASS passed, $FAIL failed ==="
echo "T3 and T11 are covered by scripts/experiments.sh (Experiment 2 and Experiment 1)."
[[ $FAIL -eq 0 ]]
