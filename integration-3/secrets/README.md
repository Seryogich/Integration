# Secret provisioning

Two secrets are required. Real secret files are **not** in the repository
(`.gitignore` excludes everything in this directory except `*.example` and this file).
Docker Compose refuses to start if either file is missing (fail-fast, R1.9).

| File             | Consumed by            | Mounted at                    | Purpose                    |
|------------------|------------------------|-------------------------------|----------------------------|
| `db_password`    | `postgres`, `orders-api` | `/run/secrets/db_password`    | PostgreSQL password        |
| `jwt_secret_key` | `orders-api`           | `/run/secrets/jwt_secret_key` | HS256 access-token key     |

## Quick way

```bash
./scripts/init_secrets.sh          # creates both files with random values, mode 0600
./scripts/init_secrets.sh --force  # overwrite existing files (rotation)
```

## Manual way

```bash
mkdir -p secrets
umask 077
printf '%s' "$(openssl rand -base64 24)" > secrets/db_password
printf '%s' "$(openssl rand -base64 48)" > secrets/jwt_secret_key
chmod 600 secrets/db_password secrets/jwt_secret_key
```

## Rules

* Never put secret values into `.env`, a Dockerfile, an image layer or source code.
* Replace a secret file **in place** (shell redirection `>`), or recreate the service
  (`docker compose up -d --force-recreate orders-api`). Editors that save atomically create a
  new inode and the running container keeps seeing the old content (bind-mount behaviour).
* Changing `db_password` does **not** change the password of an already initialised PostgreSQL
  volume. See "Experiment 3" in `REPORT.md` for the safe rotation procedure.
