# House Price Forecast & Orders API

A small microservices application for creating property orders and predicting house sale prices using the **Ames Housing** dataset.

The project consists of two FastAPI services and a PostgreSQL database:

- **Forecast API** — trains a Ridge regression model and exposes house-price predictions
- **Orders API** — manages orders and requests price predictions from the Forecast API
- **PostgreSQL** — stores orders
- **uv** — manages Python dependencies and the lockfile
- **Docker Compose** — runs the complete application locally

---

## Table of Contents

- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Dataset](#dataset)
- [Environment Variables](#environment-variables)
- [Running with Docker Compose](#running-with-docker-compose)
- [Forecast API](#forecast-api)
- [Orders API](#orders-api)
- [Swagger UI](#swagger-ui)
- [Validation](#validation)
- [End-to-End Test](#end-to-end-test)
- [Local Development with uv](#local-development-with-uv)
- [Docker Configuration](#docker-configuration)
- [Model Training](#model-training)
- [Database](#database)
- [Graceful Forecast Failure](#graceful-forecast-failure)
- [Rebuilding After Code Changes](#rebuilding-after-code-changes)
- [Troubleshooting](#troubleshooting)
- [API Summary](#api-summary)
- [Technology Stack](#technology-stack)
- [Quick Start](#quick-start)

---

## Architecture

```text
                         ┌───────────────────────┐
                         │     Client / curl      │
                         └───────────┬───────────┘
                                     │ HTTP :8000
                                     ▼
                         ┌───────────────────────┐
                         │       Orders API       │
                         │        FastAPI         │
                         └──────┬────────────┬────┘
                                │            │
                        SQL     │            │ HTTP :8001
                                │            ▼
                                │   ┌───────────────────┐
                                │   │    Forecast API    │
                                │   │      FastAPI       │
                                │   │    Ridge model      │
                                │   └───────────────────┘
                                ▼
                         ┌───────────────────────┐
                         │       PostgreSQL       │
                         └───────────────────────┘
```

**Order creation flow:**

1. The client sends property information to the **Orders API**.
2. The Orders API sends the property features to the **Forecast API**.
3. The Forecast API returns the predicted sale price.
4. The Orders API stores the order and predicted price in **PostgreSQL**.
5. The created order is returned to the client.

> If the Forecast API is temporarily unavailable, the order can still be created without a predicted price.

---

## Project Structure

```text
.
├── .env
├── .gitignore
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
│
├── forecast_service/
│   ├── Dockerfile
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── model.py
│   │   ├── schemas.py
│   │   └── train.py
│   └── data/
│       └── ames_train.csv
│
└── orders_service/
    ├── Dockerfile
    └── app/
        ├── __init__.py
        ├── crud.py
        ├── database.py
        ├── main.py
        ├── models.py
        └── schemas.py
```

The project uses a single `pyproject.toml` and `uv.lock` located in the repository root.

---

## Requirements

You need:

- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/)
- [uv](https://docs.astral.sh/uv/) for local development

Check your installation:

```bash
docker --version
docker compose version
uv --version
```

---

## Dataset

The Forecast API uses the **Ames Housing** dataset from the Kaggle competition [House Prices: Advanced Regression Techniques](https://www.kaggle.com/competitions/house-prices-advanced-regression-techniques/data).

Place the training dataset at:

```text
forecast_service/data/ames_train.csv
```

The application expects the following columns:

| Column | Description |
|---|---|
| `GrLivArea` | Above-ground living area |
| `TotalBsmtSF` | Total basement area |
| `GarageArea` | Garage area |
| `YearBuilt` | Original construction year |
| `OverallQual` | Overall material and finish quality |
| `MSZoning` | General zoning classification |
| `SalePrice` | Target sale price |

The dataset uses these columns directly — no renaming or transformation is required before training.

---

## Environment Variables

Create a `.env` file in the project root:

```env
POSTGRES_USER=orders
POSTGRES_PASSWORD=orders
POSTGRES_DB=orders

MODEL_VERSION=v0.1.0
FORECAST_TIMEOUT=3.0

ORDERS_PORT=8000
FORECAST_PORT=8001
```

The `.env` file should **not** be committed to Git. Add it to `.gitignore`:

```gitignore
.env
```

Docker Compose automatically reads `.env` from the project root. Verify the resolved configuration with:

```bash
docker compose config
```

---

## Running with Docker Compose

### Build and Start

From the project root:

```bash
docker compose up --build
```

For a completely clean rebuild:

```bash
docker compose down
docker compose build --no-cache
docker compose up
```

The services will be available at:

| Service | URL |
|---|---|
| Orders API | http://localhost:8000 |
| Orders Swagger UI | http://localhost:8000/docs |
| Orders OpenAPI | http://localhost:8000/openapi.json |
| Forecast API | http://localhost:8001 |
| Forecast Swagger UI | http://localhost:8001/docs |
| Forecast OpenAPI | http://localhost:8001/openapi.json |

> The Forecast API port is published to the host for **local development and debugging convenience**. Orders API still talks to it internally over the Docker network at `http://forecast-api:8001`, regardless of the host port mapping. PostgreSQL remains unpublished and reachable only through the Docker network.

### Check Container Status

```bash
docker compose ps
```

You should see:

- `postgres`
- `forecast-api`
- `orders-api`

### Logs

```bash
# All services
docker compose logs

# Individual services
docker compose logs forecast-api
docker compose logs orders-api
docker compose logs postgres

# Follow in real time
docker compose logs -f
```

---

## Forecast API

The Forecast API is responsible for house-price prediction. It uses a scikit-learn pipeline:

```text
Numerical features ──▶ Median imputation ──▶ StandardScaler ─┐
                                                                ├──▶ Ridge regression ──▶ Predicted SalePrice
Categorical features ──▶ Most-frequent imputation ──▶ One-hot encoding ─┘
```

**Input features:**

- `GrLivArea`
- `TotalBsmtSF`
- `GarageArea`
- `YearBuilt`
- `OverallQual`
- `MSZoning`

**Predicts:** `SalePrice`

The trained model is generated during the Docker image build and stored as `/app/artifacts/model.pkl`.

### Health Check

```bash
curl http://localhost:8001/health
```

```json
{
  "status": "ok",
  "model_version": "v0.1.0"
}
```

### Make a Prediction

```bash
curl -X POST http://localhost:8001/predict \
  -H "Content-Type: application/json" \
  -d '{
    "gr_liv_area": 1800,
    "total_bsmt_sf": 1000,
    "garage_area": 500,
    "year_built": 2005,
    "overall_qual": 7,
    "ms_zoning": "RL"
  }'
```

```json
{
  "predicted_price": 187543.42,
  "currency": "USD",
  "model_version": "v0.1.0",
  "latency_ms": 2.31
}
```

> The exact predicted price depends on the dataset and trained model.

---

## Orders API

The Orders API provides CRUD operations for property orders.

### Health Check

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok"
}
```

### Create an Order

```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "John Smith",
    "gr_liv_area": 1800,
    "total_bsmt_sf": 1000,
    "garage_area": 500,
    "year_built": 2005,
    "overall_qual": 7,
    "ms_zoning": "RL"
  }'
```

The Orders API internally calls `POST http://forecast-api:8001/predict` and stores the returned prediction in PostgreSQL.

```json
{
  "id": 1,
  "client_name": "John Smith",
  "gr_liv_area": 1800.0,
  "total_bsmt_sf": 1000.0,
  "garage_area": 500.0,
  "year_built": 2005,
  "overall_qual": 7,
  "ms_zoning": "RL",
  "predicted_price": 187543.42,
  "created_at": "2026-08-26T09:30:00Z"
}
```

### List Orders

```bash
curl http://localhost:8000/orders
```

With pagination:

```bash
curl "http://localhost:8000/orders?limit=10&offset=0"
```

### Get an Order

```bash
curl http://localhost:8000/orders/1
```

If the order does not exist: `404 Not Found`

### Update an Order

Only fields provided in the request are updated:

```bash
curl -X PATCH http://localhost:8000/orders/1 \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "Jane Smith"
  }'
```

### Delete an Order

```bash
curl -X DELETE http://localhost:8000/orders/1
```

Successful deletion returns: `204 No Content`

---

## Swagger UI

Both services expose interactive Swagger documentation. Click **Try it out**, enter the request data, and click **Execute**.

### Orders API — http://localhost:8000/docs

| Method | Endpoint |
|---|---|
| GET | `/health` |
| POST | `/orders` |
| GET | `/orders` |
| GET | `/orders/{oid}` |
| PATCH | `/orders/{oid}` |
| DELETE | `/orders/{oid}` |

### Forecast API — http://localhost:8001/docs

| Method | Endpoint |
|---|---|
| GET | `/health` |
| POST | `/predict` |

> Swagger can also be used to test Pydantic validation rules.

---

## Validation

Incoming requests are validated using Pydantic. For example, the following request is rejected because `gr_liv_area` must be greater than `0`:

```json
{
  "gr_liv_area": -100,
  "total_bsmt_sf": 1000,
  "garage_area": 500,
  "year_built": 2005,
  "overall_qual": 7,
  "ms_zoning": "RL"
}
```

**Validation constraints:**

| Field | Constraint |
|---|---|
| `gr_liv_area` | `0 < value <= 10000` |
| `total_bsmt_sf` | `0 <= value <= 10000` |
| `garage_area` | `0 <= value <= 2000` |
| `year_built` | `1872 <= value <= 2010` |
| `overall_qual` | `1 <= value <= 10` |
| `ms_zoning` | 1–10 characters |
| `client_name` | 2–120 characters |

Invalid requests return `422 Unprocessable Entity`.

---

## End-to-End Test

A complete request flow can be tested using curl:

```bash
# 1. Check Forecast API
curl http://localhost:8001/health

# 2. Check Orders API
curl http://localhost:8000/health

# 3. Create an Order
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "Alice Brown",
    "gr_liv_area": 2000,
    "total_bsmt_sf": 1200,
    "garage_area": 550,
    "year_built": 2000,
    "overall_qual": 8,
    "ms_zoning": "RL"
  }'

# 4. Retrieve the Order
curl http://localhost:8000/orders/1

# 5. List All Orders
curl http://localhost:8000/orders

# 6. Update the Order
curl -X PATCH http://localhost:8000/orders/1 \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "Alice Cooper"
  }'

# 7. Delete the Order
curl -X DELETE http://localhost:8000/orders/1
```

---

## Local Development with uv

The project uses [uv](https://docs.astral.sh/uv/) for Python dependency management.

Install dependencies from the lockfile:

```bash
uv sync --frozen
```

Check the installed environment:

```bash
uv run python --version
```

Run the Forecast API:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001
```

Run the Orders API:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> The exact working directory/module path should match the service being run.

Train the Forecast model manually:

```bash
uv run python -m app.train
```

> The Docker image automatically trains the model during the image build.

---

## Docker Configuration

### Forecast API

Listens on port `8001` inside its container:

```dockerfile
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

For local development and debugging, this port is published to the host via Docker Compose:

```yaml
ports:
  - "${FORECAST_PORT:-8001}:8001"
```

Even with the port published, the Orders API still reaches it through the internal Docker network at:

```text
http://forecast-api:8001
```

> If you prefer to keep the Forecast API fully internal (e.g. for a production-like setup), simply remove the `ports:` entry for `forecast-api` from `docker-compose.yml`. Nothing else needs to change — the Orders API connection is unaffected either way.

### Orders API

Listens on port `8000`:

```dockerfile
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Docker Compose publishes it to the host:

```yaml
ports:
  - "${ORDERS_PORT:-8000}:8000"
```

Therefore it is available externally at `http://localhost:8000`.

---

## Model Training

Training is executed during the Forecast API image build:

```bash
uv run python -m app.train
```

**The training process:**

1. Loads `ames_train.csv`
2. Selects the required features
3. Removes rows without `SalePrice`
4. Builds the preprocessing pipeline
5. Trains the Ridge regression model
6. Calculates in-sample R²
7. Calculates in-sample MAE
8. Saves the trained model to `artifacts/model.pkl`

Example build output:

```text
[train] Ames in-sample: R2=0.78, MAE=25000 USD
[train] artifact persisted: /app/artifacts/model.pkl
```

> ⚠️ The reported metrics are **in-sample** metrics and should not be interpreted as a proper estimate of production generalization performance. A hold-out set or cross-validation should be used for a proper evaluation.

---

## Database

PostgreSQL runs as a separate Docker Compose service. The Orders API connects using:

```text
postgresql+psycopg://USER:PASSWORD@postgres:5432/DATABASE
```

The hostname is `postgres`, because `postgres` is the Docker Compose service name.

PostgreSQL data is persisted in the named volume `pgdata`. List Docker volumes:

```bash
docker volume ls
```

Stop the application **without** deleting database data:

```bash
docker compose down
```

Stop the application **and delete** the database volume:

```bash
docker compose down -v
```

> ⚠️ **Warning:** `docker compose down -v` deletes the PostgreSQL data stored in the Docker volume.

---

## Graceful Forecast Failure

The Orders API is designed to avoid losing an order when the Forecast API is temporarily unavailable.

The forecasting request has a configurable timeout:

```env
FORECAST_TIMEOUT=3.0
```

If the prediction request fails, the order is still stored with:

```json
{
  "predicted_price": null
}
```

This allows the Orders API to continue accepting orders even when the ML service is unavailable.

---

## Rebuilding After Code Changes

For normal development:

```bash
docker compose up --build
```

Rebuild only the Forecast API:

```bash
docker compose build forecast-api
docker compose up
```

Rebuild only the Orders API:

```bash
docker compose build orders-api
docker compose up
```

For a completely fresh rebuild:

```bash
docker compose down
docker compose build --no-cache
docker compose up
```

---

## Troubleshooting

```bash
# Check all containers
docker compose ps

# Check Forecast API logs
docker compose logs --tail=100 forecast-api

# Check Orders API logs
docker compose logs --tail=100 orders-api

# Check PostgreSQL logs
docker compose logs --tail=100 postgres

# Follow logs
docker compose logs -f

# Check Compose environment variables
docker compose config
```

If you see:

```text
The "POSTGRES_USER" variable is not set.
```

make sure that `.env` exists in the project root, next to `docker-compose.yml`.

If `http://localhost:8001/docs` doesn't open, check that the `forecast-api` service in `docker-compose.yml` has a `ports:` entry (see [Docker Configuration](#docker-configuration)) and that nothing else on your machine is already using port `8001`.

---

## API Summary

### Forecast API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/predict` | Predict house sale price |
| GET | `/docs` | Swagger UI |
| GET | `/openapi.json` | OpenAPI specification |

### Orders API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/orders` | Create an order |
| GET | `/orders` | List orders |
| GET | `/orders/{oid}` | Get an order |
| PATCH | `/orders/{oid}` | Update an order |
| DELETE | `/orders/{oid}` | Delete an order |
| GET | `/docs` | Swagger UI |
| GET | `/openapi.json` | OpenAPI specification |

---

## Technology Stack

- Python 3.14
- FastAPI
- Pydantic
- SQLAlchemy
- PostgreSQL 16
- Psycopg 3
- scikit-learn
- pandas
- Ridge Regression
- HTTPX
- Tenacity
- Docker
- Docker Compose
- uv

---

## Quick Start

For the shortest path to a running application:

```bash
# 1. Create .env
cat > .env <<'EOF'
POSTGRES_USER=orders
POSTGRES_PASSWORD=orders
POSTGRES_DB=orders
MODEL_VERSION=v0.1.0
FORECAST_TIMEOUT=3.0
ORDERS_PORT=8000
FORECAST_PORT=8001
EOF

# 2. Make sure the dataset exists
ls forecast_service/data/ames_train.csv

# 3. Build and start everything
docker compose up --build
```

Then open:

- Orders API: http://localhost:8000/docs
- Forecast API: http://localhost:8001/docs

Or test from the command line:

```bash
curl http://localhost:8000/health
curl http://localhost:8001/health
```

Create the first order:

```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "John Smith",
    "gr_liv_area": 1800,
    "total_bsmt_sf": 1000,
    "garage_area": 500,
    "year_built": 2005,
    "overall_qual": 7,
    "ms_zoning": "RL"
  }'
```

## Завдання

Розширити та вдосконалити існуючу мікросервісну систему прогнозування вартості нерухомості.

### 1. Дослідження та виправлення архітектурної проблеми

Проаналізувати взаємодію між `orders-service` та `forecast-service`, зокрема механізм запуску сервісів у `docker-compose.yml` та обробку ситуації, коли `forecast-service` є недоступним.

Виявити архітектурну проблему, пов'язану із залежністю `orders-service` від `forecast-service`, та пояснити, чому поточна реалізація може суперечити принципу graceful degradation, передбаченому в системі.

**Необхідно:**

* експериментально перевірити поведінку системи при недоступному `forecast-service`;
* визначити причину проблеми;
* запропонувати варіант її вирішення;
* внести необхідні зміни до конфігурації та/або коду;
* продемонструвати, що після внесених змін `orders-service` може працювати навіть за недоступності `forecast-service`.

### 2. Розширення операції PATCH

Розширити функціональність оновлення замовлення.

Зараз за допомогою `PATCH /orders/{id}` можна змінювати лише дані клієнта. Необхідно реалізувати можливість оновлення параметрів нерухомості, які використовуються для прогнозування її вартості.

При зміні параметрів нерухомості система повинна повторно звертатися до `forecast-service` та отримувати актуальний прогноз.

**Необхідно:**

* розширити модель даних для `PATCH`;
* додати можливість зміни параметрів нерухомості;
* реалізувати повторний запит до `forecast-service`;
* оновлювати `predicted_price` після успішного отримання нового прогнозу;
* передбачити коректну обробку ситуації, коли `forecast-service` недоступний;
* перевірити роботу оновленого endpoint за допомогою Swagger або HTTP-запитів.

### 3. Коректна оцінка ML-моделі

У поточній реалізації метрики якості моделі (`R²`, `MAE`) обчислюються на тих самих даних, на яких модель навчалася (in-sample evaluation). Така оцінка не дозволяє коректно визначити, наскільки добре модель працюватиме на нових даних.

Необхідно змінити процес навчання та оцінювання моделі у `forecast-service`.

Реалізувати один із підходів:

* **train/test split**, або
* **крос-валідацію (cross-validation)**.

Порівняти отримані результати з поточними значеннями `R²` та `MAE`.

**У результаті необхідно:**

* змінити `train.py`;
* розділити дані на навчальну та тестову вибірки або використати крос-валідацію;
* навчити модель на навчальних даних;
* обчислити `R²` та `MAE` на даних, які не використовувалися для навчання;
* порівняти отримані результати з початковими метриками;
* зробити висновок щодо якості моделі та можливого перенавчання (overfitting).

### Результат роботи

Після виконання завдання система повинна:

1. коректно працювати при недоступності `forecast-service`;
2. дозволяти змінювати параметри нерухомості через `PATCH`;
3. автоматично оновлювати прогноз після зміни параметрів;
4. містити коректну оцінку ML-моделі на даних, які не використовувалися під час навчання.
