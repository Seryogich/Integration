#!/usr/bin/env bash
# Experiments of Task 3 (R3.2 - R3.5). Output is appended to logs/experiments.log.
#
#   ./scripts/experiments.sh            # exp1 exp2 exp3 exp4 (non-destructive for data)
#   ./scripts/experiments.sh exp1       # signing-key rotation          (R3.2, T11)
#   ./scripts/experiments.sh exp2       # missing secret                (R3.3, T3)
#   ./scripts/experiments.sh exp3       # database password rotation    (R3.4)
#   ./scripts/experiments.sh exp3-dev   # dev-environment procedure: DESTROYS the pgdata volume
#   ./scripts/experiments.sh exp4       # functional regression         (R3.5, T12)
#
# Secret VALUES are never printed to the log (only lengths / HTTP codes).
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
WHAT="${1:-all}"
LOG=logs/experiments.log
[[ "$WHAT" == "all" ]] && : > "$LOG"
exec > >(tee -a "$LOG") 2>&1

set -a; [[ -f .env ]] && . ./.env; set +a
BASE="http://localhost:${ORDERS_PORT:-8000}"
EXP_USER="experiment_user"
EXP_PASS="Experiment-pass-12345"

# ------------------------------------------------------------------ helpers
say()  { echo; echo "### $*"; }
run()  { echo "\$ $*"; "$@"; echo "[exit code: $?]"; }
inode() { ls -i "$1" | awk '{print $1}'; }

wait_health() { # wait_health [seconds]
  local i max="${1:-120}"
  for ((i=0;i<max;i++)); do
    [[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health")" == "200" ]] && { echo "orders-api healthy after ${i}s"; return 0; }
    sleep 1
  done
  echo "orders-api NOT healthy after ${max}s"; return 1
}

ensure_user() {
  curl -s -o /dev/null -X POST "$BASE/auth/register" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$EXP_USER\",\"password\":\"$EXP_PASS\"}"   # 201 first time, 409 afterwards
}

login_token() {
  curl -s -X POST "$BASE/auth/login" --data-urlencode "username=$EXP_USER" --data-urlencode "password=$EXP_PASS" \
    | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("access_token",""))
except Exception: print("")'
}

http_with_token() { # http_with_token TOKEN PATH -> HTTP status
  curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $1" "$BASE$2"
}

backup_secret()  { cp -p "secrets/$1" "secrets/$1.bak"; }
restore_secret() { cat "secrets/$1.bak" > "secrets/$1"; rm -f "secrets/$1.bak"; }  # in place: same inode

# psql from a one-off container of the postgres image, connecting over the
# Compose network (TCP -> password is really checked). Prints no password.
psql_with_password() { # psql_with_password PASSWORD LABEL
  local out
  out="$(docker compose run --rm --no-deps -T -e PGPASSWORD="$1" --entrypoint psql postgres \
         -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc 'select 1' 2>&1)"
  echo "psql with $2 -> exit $? :: $(echo "$out" | tr '\n' ' ' | cut -c1-160)"
}

echo "=== experiments started $(date -Is) (target: $WHAT) ==="

# ===================================================================
exp1() {
say "Experiment 1 - rotation of the signing key (R3.2 / T11)"
wait_health 60 || return 1
ensure_user
local old_token new_token
old_token="$(login_token)"
echo "old token issued: ${old_token:0:24}... (${#old_token} chars)"
echo "GET /auth/me with old token BEFORE rotation -> HTTP $(http_with_token "$old_token" /auth/me)   (expected 200)"

backup_secret jwt_secret_key
echo "inode of secrets/jwt_secret_key before: $(inode secrets/jwt_secret_key)"
printf '%s' "$(openssl rand -base64 48)" > secrets/jwt_secret_key      # in-place write
echo "inode of secrets/jwt_secret_key after : $(inode secrets/jwt_secret_key)   (same inode => mount stays valid)"
rm -f secrets/jwt_secret_key.bak     # do not leave the old key lying around

run docker compose restart orders-api
wait_health 90

echo "GET /auth/me with OLD token AFTER rotation -> HTTP $(http_with_token "$old_token" /auth/me)   (expected 401)"
new_token="$(login_token)"
echo "new token issued: ${new_token:0:24}..."
echo "GET /auth/me with NEW token -> HTTP $(http_with_token "$new_token" /auth/me)   (expected 200)"
echo "RESULT: tokens signed with the previous key are rejected after rotation; users must log in again."
}

# ===================================================================
exp2() {
say "Experiment 2 - missing secret (R3.3 / T3)"
echo "--- 2a: secrets/db_password removed, system started from scratch"
backup_secret db_password
run docker compose down
rm -f secrets/db_password
run docker compose up -d
echo "RESULT 2a: Compose refuses to start (fail-fast) - see the error above; no container was created."
docker compose ps --all
cat "secrets/db_password.bak" > secrets/db_password; rm -f secrets/db_password.bak
chmod 600 secrets/db_password

echo
echo "--- 2b: jwt_secret_key present but EMPTY -> the application itself must refuse to start (R3.1)"
backup_secret jwt_secret_key
: > secrets/jwt_secret_key
run docker compose up -d
sleep 12
echo "\$ docker compose logs --tail 8 orders-api"
docker compose logs --tail 8 orders-api
docker compose ps --all orders-api
restore_secret jwt_secret_key
run docker compose up -d --force-recreate orders-api
wait_health 120

cat <<'TXT'

--- 2c: comparison with a password passed through .env (hypothetical, not executed)
If the database password were passed as POSTGRES_PASSWORD=${POSTGRES_PASSWORD} and the
line were missing from .env, Compose would only print
"The POSTGRES_PASSWORD variable is not set. Defaulting to a blank string." and continue.
The failure is late (postgres: "Database is uninitialized and superuser password is not
specified") or, worse, silent for services that treat an empty value as valid, and a
typo in a variable name is indistinguishable from "not set". A secret FILE that is absent
stops Compose before anything is created, with an explicit path in the message.
TXT
}

# ===================================================================
exp3() {
say "Experiment 3 - rotation of the database password (R3.4)"
wait_health 60 || return 1
ensure_user

local old_pw new_pw
old_pw="$(cat secrets/db_password)"
new_pw="$(openssl rand -base64 24)"
echo "(secret values are not logged; old=${#old_pw} chars, new=${#new_pw} chars)"

echo "--- 3a: baseline - the initialised database accepts the current password"
psql_with_password "$old_pw" "OLD password (baseline)"

echo "--- 3b: change secrets/db_password and restart postgres"
printf '%s' "$new_pw" > secrets/db_password
run docker compose restart postgres
for i in $(seq 1 30); do
  [[ "$(docker compose ps --format '{{.Health}}' postgres)" == "healthy" ]] && break; sleep 2
done
psql_with_password "$new_pw" "NEW password (value of POSTGRES_PASSWORD_FILE)"
psql_with_password "$old_pw" "OLD password"
echo "RESULT 3b: the NEW password is rejected, the OLD one still works. POSTGRES_PASSWORD_FILE is read only"
echo "           when the data directory is initialised for the first time; afterwards the role's"
echo "           password lives inside the volume (pg_authid), not in the file."

echo "--- 3c: orders-api now presents the new password -> cannot authenticate"
run docker compose restart orders-api
sleep 15
echo "\$ docker compose logs --tail 6 orders-api"
docker compose logs --tail 6 orders-api | sed -E 's/(password=)[^ ]+/\1***/'

echo "--- 3d: safe rotation for a running environment WITHOUT data loss"
echo "    (1) change the password inside PostgreSQL, (2) make sure the secret file holds the same value,"
echo "    (3) restart the consumers so they re-read /run/secrets/db_password"
printf "ALTER ROLE %s PASSWORD :'pw';\n" "$POSTGRES_USER" \
  | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v pw="$new_pw"
echo "[exit code: $?]"
run docker compose restart orders-api
wait_health 120
echo "GET /health -> HTTP $(curl -s -o /dev/null -w '%{http_code}' "$BASE/health")"
login_ok="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/auth/login" --data-urlencode "username=$EXP_USER" --data-urlencode "password=$EXP_PASS")"
echo "POST /auth/login (needs the database) -> HTTP $login_ok   (expected 200; existing user data survived)"
psql_with_password "$new_pw" "NEW password (after ALTER ROLE)"
psql_with_password "$old_pw" "OLD password (must now fail)"
echo "RESULT 3d: secret file, database role and application agree again; no data was lost."
}

exp3_dev() {
say "Experiment 3 (dev procedure) - DESTROYS the pgdata volume and all data"
run docker compose down -v
./scripts/init_secrets.sh --force
run docker compose up -d --build
wait_health 180
echo "RESULT: with an empty volume PostgreSQL initialises itself from the NEW secret file."
}

# ===================================================================
exp4() {
say "Experiment 4 - functional regression, Forecast API stopped (R3.5 / T12)"
wait_health 60 || return 1
ensure_user
local token
token="$(login_token)"
run docker compose stop forecast-api
echo "\$ POST /orders (authenticated, forecast-api is down)"
curl -s -i -X POST "$BASE/orders" -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  -d '{"customer_name":"Regression Test","area_sqm":75,"bedrooms":2,"bathrooms":1,"year_built":2005}' \
  | sed -n '1p;/^{/p;/^\[/p' | cut -c1-400
echo
run docker compose start forecast-api
echo "RESULT: HTTP 201 with \"predicted_price\": null - graceful degradation is preserved."
}

case "$WHAT" in
  all)      exp1; exp2; exp3; exp4 ;;
  exp1)     exp1 ;;
  exp2)     exp2 ;;
  exp3)     exp3 ;;
  exp3-dev) exp3_dev ;;
  exp4)     exp4 ;;
  *) echo "unknown target: $WHAT"; exit 1 ;;
esac
echo; echo "=== experiments finished $(date -Is) ==="
