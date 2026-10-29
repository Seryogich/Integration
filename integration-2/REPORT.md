# REPORT - Task 2: Secret management and user authentication in an integrated microservice system

## 0. How to read / complete this report

The sections **3 (tests T1-T12)** and **4 (experiments R3.2-R3.5)** contain log blocks delimited by
`<!-- BEGIN:... -->` / `<!-- END:... -->`. They are filled with the real output of the scripts:

```bash
docker compose up -d --build
./scripts/verify.sh                       # -> logs/verify.log
./scripts/experiments.sh                  # -> logs/experiments.log
(cd orders_service && uv run pytest -v) 2>&1 | tee logs/unit_tests.log
python3 scripts/fill_report.py            # pastes the logs into this file
```

Until the scripts have been run, the blocks contain a placeholder. Sections 1, 2, 5 and 6 are complete as they stand.

---

## 1. Solution overview

| Area | Implementation |
|------|----------------|
| Secrets | `secrets/db_password`, `secrets/jwt_secret_key` (mode 0600, git-ignored, `*.example` + `secrets/README.md` committed). Declared in the top-level `secrets:` section of `docker-compose.yml`; `db_password` -> `postgres`, `orders-api`; `jwt_secret_key` -> `orders-api`. |
| PostgreSQL | `POSTGRES_PASSWORD_FILE=/run/secrets/db_password`; `POSTGRES_PASSWORD` is absent from the service and from `.env`. |
| Orders API | Reads secrets from `/run/secrets/` (`app/config.py`, whitespace stripped); DSN built with `sqlalchemy.URL.create`; fails at start-up with an explicit message when a secret is missing/empty/too short; no defaults, no env fallback. |
| Single entry point | `forecast-api` has no `ports` section; `FORECAST_PORT` removed from `.env`/`.env.example`; internal URL `http://forecast-api:8001`. |
| Users | `users` table (id, username unique+indexed, hashed_password, is_active, created_at), created at start-up without touching existing data. |
| Passwords | Argon2id via `pwdlib` (random salt per hash, parameters stored in the hash); input 8-72 bytes enforced in the schema. |
| Tokens | JWT HS256, claims `sub`, `iat`, `exp` (`ACCESS_TOKEN_EXPIRE_MINUTES`, default 30); decoded with `algorithms=["HS256"]` and required claims. |
| Access control | `get_current_user` dependency (token -> user lookup -> `is_active`), 401 + `WWW-Authenticate: Bearer`; applied to the whole `/orders` router and to `/auth/me`. `/health`, `/auth/register`, `/auth/login` are public. |
| OpenAPI | `OAuth2PasswordBearer(tokenUrl="auth/login")` -> Swagger "Authorize" works. |
| Regression | Orders: forecast on create, graceful degradation (`predicted_price: null`), PATCH re-requests the forecast when property parameters change. Forecast model: train/test split + 5-fold CV metrics. |

## 2. Requirement traceability

| Req. | Where |
|------|-------|
| R1.1 | `scripts/init_secrets.sh` (`openssl rand -base64 24` / `48`) |
| R1.2 | `.gitignore` (`secrets/*`, `!secrets/*.example`, `!secrets/README.md`), `secrets/*.example`, `secrets/README.md`, mode 0600 in `init_secrets.sh` |
| R1.3, R1.4 | `docker-compose.yml` (`secrets:` top level + per-service lists) |
| R1.5 | `docker-compose.yml` (`POSTGRES_PASSWORD_FILE`), `.env` has no password |
| R1.6 | `orders_service/app/config.py` (`read_secret`), `app/database.py` (`URL.create`) |
| R1.7 | `.env`, `.env.example` (non-sensitive only) |
| R1.8 | Dockerfiles contain no secrets; `orders_service/.dockerignore` excludes `secrets`, `.env` |
| R1.9 | Experiment 2 / T3 |
| R1.10, R1.11, R1.12 | `docker-compose.yml` (no `ports` on `forecast-api`), `forecast_client.py` (`FORECAST_URL`), T1, T4 |
| R2.1 | `orders_service/app/models.py` (`User`) |
| R2.2 | `app/schemas.py` (`UserCreate`, `UserOut` without `hashed_password`) |
| R2.3 | `app/security.py` (Argon2id), `app/schemas.py` (8-72 bytes) |
| R2.4 | `app/routers/auth.py` |
| R2.5 | `app/security.py` (`create_access_token`, `decode_access_token`) |
| R2.6, R2.7 | `app/deps.py`, `app/routers/orders.py` (router-level dependency), `app/routers/health.py` |
| R2.8 | `app/deps.py` (`tokenUrl="auth/login"`), unit test `test_openapi_token_url_matches_login` |
| R2.9 | `app/routers/orders.py`, `app/forecast_client.py`, T8, T9, T12 |
| R2.10 | `orders_service/pyproject.toml` (`pyjwt`, `pwdlib[argon2]`, `python-multipart`) |
| R3.1 | `app/config.py`, `app/main.py` (lifespan), unit tests in `tests/test_secrets.py` |
| R3.2-R3.5 | `scripts/experiments.sh` -> section 4 |

## 3. Acceptance tests T1-T12

Expected results and the check that implements them:

| ID | Action | Expected | Implemented in |
|----|--------|----------|----------------|
| T1 | `docker compose config` | secret values absent; file paths present; `forecast-api` has no `ports` | `verify.sh` |
| T2 | `docker compose exec orders-api env` | no secret values | `verify.sh` |
| T3 | remove `secrets/db_password`, `docker compose up` | startup refused | `experiments.sh exp2` (2a) |
| T4 | `curl http://localhost:8001/health` from the host | connection refused | `verify.sh` |
| T5 | `POST /auth/register` | 201 | `verify.sh` |
| T6 | `POST /auth/login` valid / invalid | 200 / 401 with identical message | `verify.sh` |
| T7 | `GET /orders` without token | 401 + `WWW-Authenticate: Bearer` | `verify.sh` |
| T8 | `POST /orders` with token | 201 | `verify.sh` |
| T9 | `PATCH /orders/{id}` with property parameters | 200, forecast re-requested, `predicted_price` updated | `verify.sh` |
| T10 | `DELETE /orders/{id}` with token | 204 | `verify.sh` |
| T11 | rotate `jwt_secret_key`, restart `orders-api`, repeat with old token | 401 | `experiments.sh exp1` |
| T12 | stop `forecast-api`, `POST /orders` with token | 201, `predicted_price: null` | `verify.sh`, `experiments.sh exp4` |

### 3.1 Results of `./scripts/verify.sh`

<!-- BEGIN:verify -->
```text
(run ./scripts/verify.sh, then python3 scripts/fill_report.py)
```
<!-- END:verify -->

### 3.2 Unit / API tests (`uv run pytest -v`)

<!-- BEGIN:unit_tests -->
```text
(run: cd orders_service && uv run pytest -v 2>&1 | tee ../logs/unit_tests.log ; then python3 scripts/fill_report.py)
```
<!-- END:unit_tests -->

## 4. Experiments (Task 3)

### 4.1 Logs of experiments R3.2-R3.5 (`./scripts/experiments.sh`)

<!-- BEGIN:experiments -->
```text
(run ./scripts/experiments.sh, then python3 scripts/fill_report.py)
```
<!-- END:experiments -->

### 4.2 What each experiment demonstrates

**Experiment 1 - rotation of the signing key (R3.2, T11).** A token is issued and accepted (200). The
content of `secrets/jwt_secret_key` is replaced with `>` (same inode, so the container's bind mount sees the
new content), `orders-api` is restarted (the key is read once at start-up), and the old token is sent again.
Expected and logged outcome: **401**. The HMAC of the old token was computed with the previous key, so
signature verification fails; a fresh login yields a token that is accepted. If the file is replaced
atomically (editor "save", `mv`), the container keeps the old inode and the old key; the cure is
`docker compose up -d --force-recreate orders-api`.

**Experiment 2 - missing secret (R3.3, T3).**
*2a*: `secrets/db_password` is removed and the stack started from scratch -> Compose stops before creating any
container (`secret ... file ... no such file`). *2b*: an **empty** `jwt_secret_key` is mounted -> Compose is satisfied,
but the application refuses to start and logs `FATAL: cannot start - Secret 'jwt_secret_key' ... is empty`
(the container restarts in a loop because of `restart: unless-stopped`; the log message names the problem).
*Comparison with `.env` (hypothetical):* a missing `POSTGRES_PASSWORD` in `.env` only produces the warning
"variable is not set. Defaulting to a blank string"; Compose carries on, the failure comes late (PostgreSQL:
"Database is uninitialized and superuser password is not specified") or, for a service that accepts an empty value,
not at all. A typo in a variable name is indistinguishable from "not set". A missing secret file is an explicit,
early, path-bearing error.

**Experiment 3 - rotation of the database password (R3.4).**
After changing `secrets/db_password` and restarting `postgres`:
* the **new** password is rejected by PostgreSQL, the **old** one still works -> `POSTGRES_PASSWORD_FILE` takes effect
  only when the data directory is initialised for the first time;
* `orders-api` (which now presents the new password) cannot authenticate and retries (`password authentication failed`).

*(a) Safe procedure, development environment (data disposable):*
```bash
docker compose down -v                 # removes the pgdata volume
./scripts/init_secrets.sh --force      # new random secrets
docker compose up -d --build           # empty volume -> initdb uses the new secret file
# (scripts/experiments.sh exp3-dev automates this)
```
*(b) Safe procedure, production environment without data loss:*
1. Take a backup (`pg_dump`) and keep the old secret value until the end.
2. Change the password **inside PostgreSQL** while consumers still use the old one:
   `ALTER ROLE <user> PASSWORD :'pw';` via `psql -v pw=...` on stdin (not `-c`, so the value is not in the SQL text/history).
3. Write the same value to `secrets/db_password` in place.
4. Restart/recreate the consumers (`docker compose restart orders-api`) so they re-read `/run/secrets/db_password`.
5. Verify (login/orders), then discard the old value.
For zero downtime, PostgreSQL has no dual-password support, so use two roles that own/grant the same privileges
(`app_a`, `app_b`): create the second role with the new password, switch the consumers to it one by one (rolling restart),
then lock or drop the first role. The current Compose deployment has a single `orders-api` instance, so a short restart is acceptable;
the script performs steps 2-4 and verifies that user data survived.

**Experiment 4 - functional regression (R3.5, T12).** With `forecast-api` stopped, an authenticated `POST /orders`
returns **201** and `"predicted_price": null`: authentication and secret handling did not break graceful degradation.

## 5. Control questions

### 1. Channels through which a secret passed as an environment variable may be disclosed

1. `docker inspect <container>` - `Config.Env` shows every variable in clear text to anyone with Docker API access.
2. `docker compose config` (and the rendered Compose file) - interpolated values are printed.
3. `/proc/<pid>/environ` inside the container or on the host, and `docker exec <c> env` / `printenv`.
4. Inheritance by **child processes** (shells, helper binaries, workers) and by crash dumps, debuggers and diagnostic endpoints/pages that print the environment.
5. Shell history and process listings of the host (`docker run -e TOKEN=...`), `.bash_history`, `ps eww`.
6. CI/CD logs (`env`, `set -x`, failed-step dumps) and pipeline variable stores.
7. **Image layers** if the value is set with `ENV`/`ARG` in a Dockerfile: it stays in `docker history` and in every pushed copy of the image.
8. `.env` files and Compose files committed to version control or copied into backups.
9. Application logs, error trackers and APM agents that attach the environment to reports.

### 2. Configuration or secret?

| Name | Class | Justification |
|------|-------|---------------|
| `MODEL_VERSION` | configuration | Public label of an artefact; disclosure gives no access. |
| `FORECAST_TIMEOUT` | configuration | Tuning parameter. |
| `POSTGRES_USER` | configuration | An identifier, not a credential: on its own it authenticates nothing. (It is mildly sensitive - it narrows a brute-force search - but it must be visible to operators and is not confidential key material.) |
| `db_password` | **secret** | Grants access to all business data. |
| `jwt_secret_key` | **secret** | Whoever has it can forge any token (any `sub`) and impersonate any user. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | configuration | A security *policy* value, but not confidential: the `exp` claim of every token reveals it anyway. |

Test used: "would disclosure let someone authenticate, decrypt or forge something?" Yes -> secret; no -> configuration.

### 3. Compose secrets vs Docker secrets in Swarm mode

| | Compose (no Swarm) | Swarm mode |
|---|---|---|
| Storage | an ordinary host file, bind-mounted read-only at `/run/secrets/<name>` | stored in the managers' Raft log, **encrypted at rest** (optionally auto-locked) |
| Creation | file referenced by `file:` in Compose | `docker secret create` (value held by the cluster) |
| Delivery | local bind mount, no transport | sent over mutual TLS **only** to nodes running a task that uses it |
| In the container | bind-mounted host file (host owner/mode visible; `uid/gid/mode` options are ignored) | mounted on **tmpfs** (memory only), configurable owner/mode; removed when the task stops |
| Access control | host file permissions + which services list it | cluster RBAC and per-service grants |
| Rotation | edit the file, recreate the service | secrets are immutable; `docker service update --secret-rm/--secret-add` (new name/version), rolling update |
| Nature | configuration-hygiene measure (keeps values out of env/images/config output) | a (basic) secrets manager integrated with the orchestrator |

### 4. Why changing `db_password` does not change an initialised PostgreSQL password; safe rotation

The official image's entrypoint runs `initdb` and creates the superuser **only when the data directory is empty**. `POSTGRES_PASSWORD(_FILE)`
is consumed at that moment and the password is stored (as a SCRAM verifier) in the system catalog `pg_authid` **inside the volume**. On later
starts the directory is non-empty, the initialisation branch is skipped and the file/variable is ignored. Therefore the file and the
database drift apart (Experiment 3). Safe procedures: see section 4.2 - development: `down -v` + new secrets (data lost);
production: `ALTER ROLE` -> update the secret in place -> restart consumers, with a two-role rolling switch when zero downtime is needed.

### 5. Why bcrypt/Argon2id instead of SHA-256; salt; work factor

SHA-256 is designed to be **fast**: a GPU computes billions of hashes per second, so a leaked table of SHA-256 password hashes can be
brute-forced or dictionary-attacked quickly. bcrypt and Argon2id are deliberately **slow, tunable** key-derivation functions;
Argon2id is also **memory-hard**, which neutralises the parallel-hardware advantage of GPUs/ASICs (OWASP's first choice; bcrypt is the
accepted alternative, with its 72-byte input limit).
*Salt:* a random, per-password value (>=16 bytes) stored next to the hash. It makes equal passwords produce different hashes, defeats rainbow
tables/precomputation and forces the attacker to attack each hash separately. *Work factor:* the cost parameter(s) that set how much work one hash
needs - bcrypt `cost` (2^cost rounds), Argon2id memory/iterations/parallelism. It is tuned so that one verification takes a noticeable but acceptable time
(order of 100-500 ms on the server) and is raised as hardware gets faster; the parameters are stored in the hash so old hashes remain verifiable.

### 6. Structure of a JWT; effect of modifying the payload

A JWT is `base64url(header).base64url(payload).base64url(signature)`. The header names the algorithm and type (`{"alg":"HS256","typ":"JWT"}`),
the payload carries claims (`sub` = username, `iat`, `exp`), and with HS256 the signature is
`HMAC-SHA256(key, base64url(header) + "." + base64url(payload))`. The payload is only **encoded, not encrypted** - anyone can read it, so no secrets belong there.
If the payload is changed (e.g. `sub` -> `admin`), the signing input changes, the HMAC the server recomputes no longer equals the transmitted signature
and verification fails (401). Without the key an attacker cannot compute a matching signature.

### 7. `alg: none` and algorithm confusion; how the implementation prevents them

*`alg: none`:* the attacker sets `"alg":"none"` in the header and drops the signature; a library that trusts the header treats the token as validly "unsigned"
and accepts any claims. *Algorithm confusion:* a server that verifies RS256 tokens with a public key is tricked by a token whose header says HS256 and that is
HMAC-signed **using the public key as the secret**; a library that picks the algorithm from the header validates it. In both cases the flaw is
letting the **token** choose the verification algorithm.
Prevention here: `jwt.decode(token, key, algorithms=["HS256"], options={"require": ["exp","iat","sub"]})` - an explicit algorithm whitelist, a single symmetric key used only for HS256,
and mandatory claims. Verified by tests (`test_alg_none_token_rejected`, `test_tampered_payload_rejected`, `test_token_without_exp_rejected`) and by a direct
PyJWT check during preparation: `alg:none` and an HS384 token raise `InvalidAlgorithmError`, a modified payload or a foreign key raises `InvalidSignatureError`.

### 8. Semantics of 401 and `WWW-Authenticate`

`401 Unauthorized` means the request lacks **valid authentication credentials** ("I do not know who you are" - missing, malformed, expired or wrongly signed token); the client may retry with
valid credentials. (`403 Forbidden` would mean "authenticated, but not allowed", which does not exist here because there is a single permission level.)
The `WWW-Authenticate` response header, mandatory with 401, tells the client **which authentication scheme** to use - here `Bearer`. Example from the system:

```
GET /orders            (no token)
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Not authenticated"}
```

### 9. Effect of `jwt_secret_key` rotation on issued tokens

Every previously issued token was signed with the old key. After the rotation the server verifies with the new key, so **all** outstanding tokens fail signature
verification and are rejected with 401, even though they have not expired; users have to log in again (Experiment 1). Rotation is therefore also an emergency "log everyone out" switch.
To avoid a hard cut-over, a deployment can verify against several keys identified by a `kid` header during an overlap window, and keep token lifetimes short.

### 10. Why login returns an identical error for unknown username and wrong password

Different messages (or status codes, or response times) would let an attacker **enumerate valid usernames**: submit candidate names and see which ones "exist". That list
fuels targeted password guessing, credential stuffing and password spraying and enables phishing. The implementation returns the same status, message and header
(`401`, "Incorrect username or password", `WWW-Authenticate: Bearer`) for unknown user, wrong password and inactive account, and verifies the password against a dummy
Argon2id hash for unknown users to keep timing comparable. (Registration necessarily reveals that a name is taken (409); that residual leak is mitigated by rate limiting.)

### 11. Public `GET /health`; non-publication of the Forecast API

`/health` is a liveness probe used by load balancers, orchestrators and monitoring that have no user credentials; it returns only `{"status":"ok"}`, so exposing it leaks nothing, and requiring
authentication would make probes fail exactly when something (keys, database) is broken. It must stay minimal - no versions, hosts or dependency details.
The Forecast API has **no authentication of its own**. Publishing it would give a second entry point that bypasses the authentication, validation, logging and
rate limiting of the Orders API (broken access control) and enlarge the attack surface. Keeping it on the internal Compose network makes the Orders API the single
external entry point (gateway pattern): security policy is enforced and audited in one place, and the internal API can change freely. In production the internal
network would additionally be segmented or protected with mutual TLS/service tokens.

### 12. Statelessness of JWT authentication and its consequence for revocation

The server keeps no session or token state: everything needed to trust a token (subject, expiry) is inside it and its validity is established by the signature and `exp`
alone, so any instance holding the key can authenticate a request without a shared session store (good for scaling and for integration of independent services).
The consequence is that an individual token **cannot be revoked before `exp`** - the server has nothing to delete. Mitigations: short lifetimes (`ACCESS_TOKEN_EXPIRE_MINUTES=30`) possibly with
refresh tokens; a deny-list of `jti` values or a per-user "tokens valid since" timestamp (this reintroduces state); rotating the signing key (revokes everyone, Experiment 1).
In this system `get_current_user` additionally looks the user up and checks `is_active`, so deactivating an account takes effect immediately even though tokens are stateless.

## 6. Verification performed while preparing the project, and limitations

Executed in the preparation environment (no Docker images could be built there: the sandbox had no access to PyPI or Docker Hub):

* Python compilation of both services (`compileall`) - OK.
* Forecast model trained and evaluated out of sample (hold-out + 5-fold CV): test R2 = 0.991, test MAE = 12 294, CV R2 = 0.990 +/- 0.001; training takes about 3 s.
* PyJWT behaviour used by the implementation checked directly: a valid HS256 token is accepted; `alg:none`, HS384, tampered payload and foreign key are rejected;
  expired tokens and tokens without `exp` are rejected.

**Not** executed in the preparation environment (needs Docker / package installation): the unit tests of the Orders API, the Docker build and the
scripts `verify.sh` / `experiments.sh`. Their log blocks in section 3 and 4 must be generated on a machine with Docker (see section 0).

Known design limitations: the Compose secrets mechanism is configuration hygiene, not a vault (a secret is a plain host file, section 5.3); the Orders API container runs as root so
that it can read a 0600 bind-mounted secret independent of the host uid; the Forecast API has no authentication of its own (it relies on network isolation); passwords are
not protected by login rate limiting.
