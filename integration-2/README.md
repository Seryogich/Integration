# Integration of Information Systems - Task 2
## Secret management and user authentication in an integrated microservice system

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
  init_secrets.sh           generate secret files (random, mode 0600)
  verify.sh                 acceptance tests T1, T2, T4-T10, T12  -> logs/verify.log
  experiments.sh            experiments R3.2-R3.5 (T3, T11 included) -> logs/experiments.log
  fill_report.py            paste the logs into REPORT.md
REPORT.md                   experiment logs, test results T1-T12, answers to the 12 control questions
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
| `POST /orders`                    | 401       | 201           | forecast requested; `predicted_price: null` if Forecast API is down |
| `PATCH /orders/{id}`              | 401       | 200 / 404     | changing area/bedrooms/bathrooms/year_built re-requests the forecast |
| `DELETE /orders/{id}`             | 401       | 204 / 404     | |

Failed or missing authentication -> `401 Unauthorized` with `WWW-Authenticate: Bearer`.
There is a single authorization level (any authenticated user), so `403` is not used.

Access tokens: JWT, HS256, claims `sub` (username), `iat`, `exp = iat + ACCESS_TOKEN_EXPIRE_MINUTES`
(default 30). Decoding always uses `algorithms=["HS256"]`.

### Order fields

`customer_name`, `area_sqm`, `bedrooms`, `bathrooms`, `year_built`, `status`
(`new|confirmed|completed|cancelled`), `predicted_price` (nullable), `created_at`, `updated_at`.

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

### Acceptance tests T1-T12 against the running stack

```bash
docker compose up -d --build
./scripts/verify.sh          # T1, T2, T4-T10, T12   (also logs/verify.log)
./scripts/experiments.sh     # Experiments 1-4 = T11, T3, R3.4, T12 (also logs/experiments.log)
```

| ID  | Covered by |
|-----|------------|
| T1  | `verify.sh` |
| T2  | `verify.sh` |
| T3  | `experiments.sh exp2` (2a) |
| T4  | `verify.sh` |
| T5-T10 | `verify.sh` |
| T11 | `experiments.sh exp1` |
| T12 | `verify.sh` and `experiments.sh exp4` |

Manual versions of the commands:

```bash
docker compose config | grep -E 'secrets|ports'          # T1: only file paths, no ports for forecast-api
docker compose exec orders-api env                       # T2: no secret values
curl -v http://localhost:8001/health                     # T4: connection refused
```

When everything has run, fill the report:

```bash
(cd orders_service && uv run pytest -v) 2>&1 | tee logs/unit_tests.log
python3 scripts/fill_report.py
```

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
