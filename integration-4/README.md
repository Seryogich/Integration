# Integration of Information Systems — Practice 4

## The Model as a Managed Component: Experiment Tracking, Registry, and Delivery

Continuation of Practice 3 (`integration-3`). Order creation remains deferred (202 Accepted + BackgroundTasks). The ML component is fully separated from the serving image:

- training runs in a dedicated `trainer` service (compose profile `train`);
- models are tracked and versioned in MLflow;
- the Forecast API loads `models:/house-price@prod` at startup;
- every priced order stores the `model_version` that produced the prediction.

### Architecture

```
Client -- Bearer JWT --> Orders API :8000 -- SQL --> PostgreSQL
                              |
                              | BackgroundTasks
                              v
                         Forecast API (internal)
                              |
                              | loads models:/house-price@prod
                              v
                         MLflow :5000 (UI for operator)
                              |
                              +-- backend: PostgreSQL database "mlflow"
                              +-- artifacts: volume mlartifacts

docker compose --profile train run --rm trainer
  data → descriptive stats → Optuna (≥20 trials, nested runs)
  → final run → register house-price → set alias @prod
```

### Prerequisites

- Docker + Docker Compose v2
- `uv` (optional, for local development)
- Secrets already present in `./secrets/` (or run `./scripts/init_secrets.sh`)

### First-time start (fresh volume)

```bash
# 1. Secrets
./scripts/init_secrets.sh

# 2. Start infrastructure + APIs (trainer is NOT started)
docker compose up -d --build

# 3. Wait until mlflow is up, then train & register the first model
docker compose --profile train run --rm trainer

# 4. Restart forecast so it picks up @prod
docker compose up -d --force-recreate forecast-api

# 5. Check
docker compose exec forecast-api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health').read())"
```

### MLflow database note (R1.2)

The init script `postgres-init/01-create-mlflow-db.sql` creates the `mlflow` database **only on a fresh PostgreSQL volume**.  
If the volume already exists:

```bash
docker compose exec postgres psql -U orders -c "CREATE DATABASE mlflow;"
docker compose restart mlflow
```

### Model promotion / rollback (R3.4, R3.5)

1. Train a new version: `docker compose --profile train run --rm trainer`
2. In MLflow UI (http://localhost:5000) or via client, set the `@prod` alias to the desired version.
3. Restart forecast: `docker compose up -d --force-recreate forecast-api`
4. `/health` reports the new version; subsequent orders carry the new `model_version`.

Rollback = re-assign `@prod` to the previous version + restart forecast.

### Key endpoints

| Endpoint | Service | Notes |
|----------|---------|-------|
| `GET /health` | forecast (internal) | returns real registry version |
| `GET /model/data-stats` | forecast (internal) | stats of the currently served model |
| `POST /predict` | forecast (internal) | returns `predicted_price` + `model_version` |
| `POST /orders` | orders :8000 | 202 + `model_version` after pricing |
| `GET /orders/{id}` | orders :8000 | includes `model_version` |

### Acceptance tests (see REPORT.md / T1–T19)

```bash
# Config sanity
docker compose config

# Trainer not started by default
docker compose up -d
docker compose ps   # trainer absent

# Train
docker compose --profile train run --rm trainer

# Health & data-stats from inside the network
docker compose exec orders-api curl -s http://forecast-api:8001/health
docker compose exec orders-api curl -s http://forecast-api:8001/model/data-stats

# Full flow (register + create order + wait)
# … use the same JWT flow as Practice 3
```

### Single external entry point

Only the Orders API is published to the host.  
MLflow UI is published for the **operator** (not a client-facing API), which does not violate the principle.

### Deliverables

- This repository
- `README.md` (this file)
- `REPORT.md` (baseline vs final metrics, trainer log excerpt, rollback timeline, T1–T19 results)
