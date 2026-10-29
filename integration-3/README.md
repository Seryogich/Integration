# Integration of Information Systems - Practice 3
## Asynchronous and concurrent interaction in an integrated microservice system

Built on top of Practice 2 (secrets via Docker Compose, JWT authentication, Orders API + Forecast API + PostgreSQL).
Practice 3 adds, using **variant A (FastAPI `BackgroundTasks`)**:

* `POST /orders/batch` - concurrent forecasts for a group of orders (`asyncio.gather`, shared `httpx.AsyncClient`, `BATCH_MAX_ITEMS`);
* deferred forecast: `POST /orders` -> **202 Accepted** + `Location`, order `status`: `pending` -> `priced` | `failed`;
* `PATCH /orders/{id}` re-computes the forecast only when property parameters change;
* event log of forecast computations (`GET /events`), idempotent re-runs (`POST /orders/{id}/forecast`).

See **"Practice 3 - how to verify"** below; the report template is `REPORT.md`.

---

## Practice 2 documentation (still valid)

Orders API + Forecast API + PostgreSQL, deployed with Docker Compose.

* Secrets (`db_password`, `jwt_secret_key`) are delivered as **files** under `/run/secrets/`
  (Docker Compose secrets), never as environment variables.
* The **Orders API is the single external entry point**; the Forecast API is not published to the host.
* User registration / login (OAuth2 password flow, JWT HS256, Argon2id password hashes).

```
Client --Bearer JWT--> Orders API :8000 --SQL--------> PostgreSQL (+ users table)
                         /auth/register /auth/login   |
                         /auth/me   /orders CRUD      '--HTTP (internal network only)--> Forecast API (not published)

secrets/db_password     -> postgres, orders-api      (/run/secrets/db_password)
secrets/jwt_secret_key  -> orders-api                (/run/secrets/jwt_secret_key)
```

## Repository layout

```
docker-compose.yml          services, secrets, healthchecks
.env / .env.example         NON-sensitive configuration only
secrets/                    real secrets (git-ignored) + *.example + README.md
orders_service/             Orders API (FastAPI, SQLAlchemy, PyJWT, pwdlib/Argon2id) + tests
forecast_service/           Forecast API (FastAPI, scikit-learn) + tests
scripts/
  init_secrets.sh           generate secret files (random, mode 0600) - the files are already in secrets/
  verify.py                 Practice 3 acceptance checks + timings (cross-platform)  -> logs/verify.log
  fill_report.py            paste the logs into REPORT.md
REPORT.md                   Practice 3 report (traceability, answers, experiments)
```

## Prerequisites

Docker + Docker Compose v2, `uv`, `curl`, `openssl`, `python3` (used by the scripts to parse JSON).

## Run

```bash
# 1. secrets (required; Compose refuses to start without them)
./scripts/init_secrets.sh

# 2. configuration (non-sensitive)
cp .env.example .env          # already present; edit ports/timeouts if needed

# 3. optional but recommended: pin dependency versions once, then commit the lock files
(cd orders_service   && uv lock)
(cd forecast_service && uv lock)

# 4. build and start
docker compose up -d --build
docker compose ps
```

Swagger UI: <http://localhost:8000/docs> - click **Authorize**, enter username/password
(the dialog calls `POST /auth/login` and stores the token).

### Quick manual walk-through

```bash
curl -s -X POST localhost:8000/auth/register -H 'Content-Type: application/json' \
     -d '{"username":"alice","password":"correct horse battery"}'

TOKEN=$(curl -s -X POST localhost:8000/auth/login \
     -d 'username=alice' --data-urlencode 'password=correct horse battery' \
     | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s localhost:8000/auth/me -H "Authorization: Bearer $TOKEN"

curl -s -X POST localhost:8000/orders -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"customer_name":"ACME","area_sqm":80,"bedrooms":3,"bathrooms":2,"year_built":2010}'
```

## Endpoints and access policy

| Endpoint                          | Anonymous | Authenticated | Notes |
|-----------------------------------|-----------|---------------|-------|
| `GET /health`                     | 200       | 200           | public liveness probe |
| `POST /auth/register`             | 201 / 409 / 422 | -       | body: `username`, `password` (8-72 bytes); unknown fields rejected |
| `POST /auth/login`                | 200 / 401 / 422 | 200     | form-encoded (`OAuth2PasswordRequestForm`); identical 401 message for unknown user and wrong password |
| `GET /auth/me`                    | 401       | 200           | |
| `GET /orders`, `GET /orders/{id}` | 401       | 200 / 404     | |
| `POST /orders`                    | 401       | **202**       | order saved as `pending`, `Location` header, forecast computed in the background |
| `POST /orders/batch`              | 401       | 200 / 422     | **new:** array of orders; concurrent forecasts; max `BATCH_MAX_ITEMS` (50) |
| `PATCH /orders/{id}`              | 401       | 200 / **202** / 404 | property fields -> 202 + new background forecast; other fields -> 200, no recomputation |
| `POST /orders/{id}/forecast`      | 401       | 202 / 404     | **new:** re-run the forecast of an existing order (no duplicates) |
| `GET /events?order_id=`           | 401       | 200           | **new:** event log (order id, result, timestamp) |
| `DELETE /orders/{id}`             | 401       | 204 / 404     | |

Failed or missing authentication -> `401 Unauthorized` with `WWW-Authenticate: Bearer`.
There is a single authorization level (any authenticated user), so `403` is not used.

Access tokens: JWT, HS256, claims `sub` (username), `iat`, `exp = iat + ACCESS_TOKEN_EXPIRE_MINUTES`
(default 30). Decoding always uses `algorithms=["HS256"]`.

### Order fields

`customer_name`, `area_sqm`, `bedrooms`, `bathrooms`, `year_built`, `order_status`
(`new|confirmed|completed|cancelled`, was `status` in Practice 2), **`status`** (forecast state:
`pending|priced|failed`), `predicted_price` (nullable), `created_at`, `updated_at`.

## Secret provisioning

See [`secrets/README.md`](secrets/README.md). Summary:

```bash
./scripts/init_secrets.sh            # create (mode 0600, random values)
./scripts/init_secrets.sh --force    # rotate (see Experiments 1 and 3 in REPORT.md before doing this on a live system)
```

Rules: no secret in `.env`, Dockerfiles, images or source; replace secret files **in place**
(`>` redirection) or recreate the service; the application reads secrets only from `/run/secrets/`
and exits at start-up with an explicit message if one is missing, empty or (for the JWT key) shorter than 32 characters.

## Tests

### Unit / API tests (no Docker needed)

```bash
(cd orders_service   && uv run pytest -v)    # SQLite in memory, temp secret files, forecast mocked
(cd forecast_service && uv run pytest -v)
```

### Acceptance checks against the running stack

See **Practice 3 - how to verify** below (`python scripts/verify.py`).

## Notes and assumptions

* **Practice 1 base system.** The `integration-1` repository was not available when this work was
  prepared, so the Orders API / Forecast API were re-created from the description in the task
  (orders CRUD, price forecast on create and on PATCH, graceful degradation, out-of-sample model
  evaluation exposed at the Forecast API's internal `GET /model/info`). If your Practice 1 code differs, copy
  the `app/security.py`, `app/deps.py`, `app/routers/auth.py`, `app/config.py` pieces and the
  compose/secrets changes into it; they are independent of the order fields.
* **Secrets file permissions.** Compose (without Swarm) bind-mounts the host file, so the container
  sees the host file's owner and mode (0600). The Orders API container therefore runs as root so it can
  read the file regardless of the host user's uid; PostgreSQL reads `POSTGRES_PASSWORD_FILE` in its
  entrypoint, which also starts as root.
* **`SECRETS_DIR`** (default `/run/secrets`) only redirects the *directory*, which the unit tests use. There is no
  environment-variable fallback for secret *values* (R3.1).
* The Dockerfiles use `uv sync` and honour `uv.lock` when present. Generate and commit the lock files
  (`uv lock`) for reproducible builds.

---

# Practice 3 - how to verify

## What changed compared with Practice 2

| Area | Change |
|---|---|
| `orders_service/app/routers/orders.py` | `POST /orders` -> 202; new `POST /orders/batch`, `POST /orders/{id}/forecast`; PATCH logic |
| `orders_service/app/services.py` (new) | background task, `finalize_order`, batch helpers |
| `orders_service/app/forecast_client.py` | async client with error codes (`ForecastUnavailable`, `ForecastTimeout`, `ForecastBadResponse`) |
| `orders_service/app/models.py`, `database.py` | `status` (forecast state), `forecast_version`, `order_events`; **`status` -> `order_status` rename** + `migrate_db()` |
| `orders_service/app/main.py` | shared `httpx.AsyncClient` in `lifespan`, `/events` router |
| `forecast_service/app/main.py` | `FORECAST_DELAY_SEC` (artificial latency, default 1.0 in Compose), async `/predict` |
| `docker-compose.yml`, `.env` | `BATCH_MAX_ITEMS`, `FORECAST_DELAY_SEC` |

> **Naming note.** Practice 2 had a business field `status` (`new|confirmed|...`). Practice 3 requires `status` to be the
> forecast state (`pending|priced|failed`), so the old field is now **`order_status`**. Existing databases are migrated
> automatically at start-up (data kept; rows with a stored price become `priced`, others `failed`).

## 1. Start

```powershell
docker compose up -d --build
docker compose ps                      # postgres (healthy), forecast-api, orders-api: Up
```
Secrets are already in `secrets/` (same as in Practice 2). To regenerate them without bash/openssl:
```powershell
python -c "import secrets,pathlib; pathlib.Path('secrets/db_password').write_text(secrets.token_urlsafe(24)); pathlib.Path('secrets/jwt_secret_key').write_text(secrets.token_urlsafe(48))"
docker compose down -v    # a new db_password requires a fresh database volume
```

## 2. Unit / API tests (no Docker needed)

```powershell
cd orders_service;   uv run pytest -v; cd ..
cd forecast_service; uv run pytest -v; cd ..
```

## 3. Automated acceptance checks

```powershell
python scripts/verify.py                         # scenarios 1-10 + timing of batch vs sequential
python scripts/verify.py --with-docker           # + stops/starts forecast-api (experiments 2, 4)
python scripts/verify.py --restart-experiment    # + restarts orders-api while a task is pending (experiment 3)
python scripts/fill_report.py                    # paste logs/verify.log into REPORT.md
```

## 4. Manual walk-through (Swagger: <http://localhost:8000/docs>)

1. `POST /auth/register`, then **Authorize** (username/password).
2. `POST /orders` -> **202**, `status: "pending"`, `Location: /orders/{id}`.
3. `GET /orders/{id}` after ~1 s -> `status: "priced"`, `predicted_price` filled.
4. `POST /orders/batch` with an array of 10 orders -> 10 results in one response (~1 s); 51 orders -> **422**.
5. `PATCH /orders/{id}` `{"area_sqm": 200}` -> 202, `pending`, then `priced` with a new price;
   `PATCH` `{"customer_name": "X"}` -> 200, no recomputation.
6. `docker compose stop forecast-api` -> create an order: 202 at once, shortly `status: "failed"`;
   `docker compose start forecast-api`, then `POST /orders/{id}/forecast` -> `priced`.
7. `GET /events?order_id={id}` -> the log of every computation (`priced` / `failed` / `skipped`).
8. Request without a token -> **401**.

## Configuration

| Variable (`.env`) | Default | Meaning |
|---|---|---|
| `FORECAST_DELAY_SEC` | 1.0 | artificial latency of `/predict` (set `0` for production-like speed) |
| `FORECAST_TIMEOUT` | 3 | timeout of one Forecast request, seconds |
| `BATCH_MAX_ITEMS` | 50 | max orders in one batch |
