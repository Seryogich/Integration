# REPORT - Practice 3: Asynchronous and concurrent interaction in an integrated microservice system

Student: Protsak Serhii, group FEI-41 · Variant **A** (FastAPI `BackgroundTasks`)

> Fill the two log blocks with `python scripts/fill_report.py` (see README), then read sections 3-4 and
> adapt the wording / numbers to what you actually measured.

## 1. What was implemented

| Task | Implementation |
|---|---|
| 1. Concurrent batch | `POST /orders/batch` (`routers/orders.py`): stores all valid orders, requests forecasts with `asyncio.gather` over one shared `httpx.AsyncClient` (created in `lifespan`), per-request timeout, `BATCH_MAX_ITEMS` limit (422), per-element result, authentication kept |
| 2. Deferred forecast | `POST /orders` stores the order as `pending` (`predicted_price = NULL`) and returns **202 + Location**; `services.run_forecast_task` runs after the response, opens its own DB session and HTTP client, sets `priced`/`failed`, writes `order_events`, ends cleanly if the order was deleted |
| 3. PATCH | property fields -> `pending`, price cleared, new background task (202); client/business data only -> no recomputation (200) |
| 4. Reliability | `scripts/verify.py`, unit tests in `orders_service/tests` |

Design decisions

* **`status` vs `order_status`.** Practice 2 already had a business column `status` (`new|confirmed|completed|cancelled`).
  The task requires `status` to be the forecast state (`pending|priced|failed`), so the old column was renamed to
  `order_status` (data preserved by `migrate_db`, which also applies the SQL from the task description to existing rows).
* **Synchronous DB layer kept.** The Practice 2 code uses SQLAlchemy + psycopg2. Instead of rewriting it, every DB call
  made from async code runs in a worker thread (`run_in_threadpool`), so the event loop is never blocked; HTTP calls are fully async.
* **Idempotency + stale results.** A result is written by `UPDATE ... WHERE id=? AND forecast_version=?`, so a repeated run
  updates the existing order (no duplicates), and a result is discarded if the order was deleted or modified while the
  forecast was being computed.
* **Forecast latency.** `forecast-api` got `FORECAST_DELAY_SEC` (default 1.0 in Compose) so that the effect of concurrency is measurable.

## 2. Requirement traceability

| Requirement | Where |
|---|---|
| Concurrent requests (`asyncio.gather`) | `routers/orders.py::create_batch` |
| Shared `httpx.AsyncClient` | `main.py::lifespan` -> `app.state.http_client`, `deps.get_http_client` |
| `BATCH_MAX_ITEMS` (default 50) -> 422 | `config.py`, `create_batch`, `docker-compose.yml` |
| Timeout of every Forecast request | `forecast_client.fetch_forecast` (`FORECAST_TIMEOUT`, hard `asyncio.timeout`) |
| Each valid order saved regardless of forecast | `services.create_pending_orders` runs before any HTTP request |
| Per-element result with status/price or error | `BatchItemResult` (`priced`+price / `failed`+error code) |
| Authentication on the new endpoint | router-level `Depends(get_current_user)` |
| 422 on a schema violation | Pydantic (`extra="forbid"`), `list[OrderCreate]` |
| 202 + representation + `Location` | `create_order` |
| `pending` -> `priced`/`failed` | `services.finalize_order` |
| Event log: order id, result, timestamp | table `order_events`, `GET /events` |
| `status` in `GET /orders`, `GET /orders/{id}` | `OrderOut` |
| Order deleted before/while processing | `services._prepare` / `finalize_order` -> event `skipped`, no exception |
| Migration `ALTER TABLE ... status` | `database.migrate_db` |
| PATCH logic | `update_order` |
| Re-run does not duplicate | `UPDATE` instead of `INSERT`, `POST /orders/{id}/forecast` |
| Forecast API not published | `docker-compose.yml` (no `ports`) |

## 3. Why the batch endpoint stays synchronous

(Answer to the question in task 1.) A batch import is an operation where the client wants one consolidated answer:
which elements were accepted, which got a price and which failed. A synchronous response gives all of that in a single
round trip, without polling dozens of order resources and without the client having to correlate asynchronous results.
The latency problem is solved by **concurrency** (`asyncio.gather`), not by deferral: the total wait approaches the duration
of the slowest request instead of the sum of all. Creating a single order, in contrast, is deferred, because the user only
needs a quick confirmation that the order was stored; the forecast may take long or fail.

## 4. Results of the experiments

### 4.1 Automated checks (`python scripts/verify.py --with-docker --restart-experiment`)

<!-- BEGIN:verify -->
```text
(run scripts/verify.py and then scripts/fill_report.py)
```
<!-- END:verify -->

### 4.2 Unit / API tests (`uv run pytest -v` in `orders_service` and `forecast_service`)

<!-- BEGIN:unit_tests -->
```text
(run the tests and then scripts/fill_report.py)
```
<!-- END:unit_tests -->

### 4.3 Experiment 1 - processing time

| Scenario | Time, s |
|---|---|
| 1 batch request with 10 orders | _from the TIMINGS table above_ |
| 10 batch requests with 1 order each | _from the TIMINGS table above_ |

Sequential execution takes about the sum of the durations (10 x ~1 s). In the batch the 10 requests to the Forecast API
are in flight at the same time (`asyncio.gather`), so the wait is about the duration of the slowest one (~1 s plus overhead).
The event loop does not idle while it waits for a response, it serves the other requests.

### 4.4 Experiment 2 - Forecast API unavailable

The Forecast API is stopped (`docker compose stop forecast-api`). `POST /orders` still answers **202** immediately (the request does
not wait for the forecast); the order is saved, the background task gets a connection error right away and the order ends
as `failed` (event `ForecastUnavailable`). In a batch every element is saved and reports `status: failed` + `error`.

### 4.5 Experiment 3 - restart of the component that runs the tasks

* In **variant A** the task lives in the memory of the `orders-api` process. If `orders-api` is restarted while a forecast
  is in progress, the task is lost and the order stays `pending` forever (shown by `--restart-experiment`). It can be
  recovered manually with `POST /orders/{id}/forecast`.
* In **variant B** (Celery/ARQ + Redis/RabbitMQ) the task is stored in the broker; a separate worker takes it after a restart;
  retries, persistence and independent scaling of workers are available, at the price of extra infrastructure to run and monitor.
* After the Forecast API is restored, a failed order is recomputed by re-running the task (`failed` -> `priced`).

### 4.6 Experiment 4 - repeated execution

`POST /orders/{id}/forecast` repeated several times updates the same row: the number of orders does not change, the state is
`priced` with the same price, and every run adds a line to the event log. (Variant B only: retries after a temporary
failure are not implemented in variant A.)

## 5. Verification of the scenarios from section 5 of the task

| # | Scenario | Expected | Covered by |
|---|---|---|---|
| 1 | Docker Compose start | all services up | `verify.py` (health) |
| 2 | Create order | 202, `pending` | `verify.py`, `test_orders.py` |
| 3 | Get order | `priced` after processing | `verify.py`, `test_orders.py` |
| 4 | Batch of 10 | results for all | `verify.py`, `test_batch.py` |
| 5 | Batch over the limit | 422 | `verify.py`, `test_batch.py` |
| 6 | Forecast API down | order saved, error handled | `verify.py --with-docker`, `test_batch.py` |
| 7 | PATCH of property params | new forecast | `verify.py`, `test_orders.py` |
| 8 | PATCH of client data only | no new forecast | `verify.py`, `test_orders.py` |
| 9 | No token | 401 | `verify.py`, `test_orders.py` |
| 10 | Repeated task | no duplicates | `verify.py`, `test_services.py` |

## 6. Limitations

* The code was written and statically checked without the ability to start Docker in the authoring environment; run
  `python scripts/verify.py` and the unit tests on your machine and attach the logs.
* Variant A does not retry failed forecasts automatically and loses pending tasks on restart (by design, see 4.5).
