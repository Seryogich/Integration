import asyncio
import time
from dataclasses import replace

from app import services
from app.forecast_client import ForecastTimeout
from app.routers import orders as orders_router
from tests.conftest import ORDER


def _items(n, **override):
    return [{**ORDER, "customer_name": f"client-{i}", "area_sqm": 50 + i, **override} for i in range(n)]


def test_batch_requires_token(client):
    assert client.post("/orders/batch", json=_items(1)).status_code == 401


def test_batch_returns_result_for_every_item_and_saves_all(client, auth_headers):
    r = client.post("/orders/batch", json=_items(3), headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert [x["index"] for x in body["results"]] == [0, 1, 2]
    assert all(x["status"] == "priced" and "error" not in x for x in body["results"])
    assert body["results"][0]["predicted_price"] == 50000.0

    stored = client.get("/orders", headers=auth_headers).json()
    assert len(stored) == 3 and all(o["status"] == "priced" for o in stored)
    assert [x["order_id"] for x in body["results"]] == [o["id"] for o in stored]


def test_batch_over_limit_is_422(client, auth_headers, monkeypatch):
    settings = replace(orders_router.get_settings(), batch_max_items=2)
    monkeypatch.setattr(orders_router, "get_settings", lambda: settings)
    assert client.post("/orders/batch", json=_items(2), headers=auth_headers).status_code == 200
    r = client.post("/orders/batch", json=_items(3), headers=auth_headers)
    assert r.status_code == 422
    assert len(client.get("/orders", headers=auth_headers).json()) == 2  # nothing from the rejected batch


def test_batch_default_limit_is_50(client, auth_headers):
    assert client.post("/orders/batch", json=_items(51), headers=auth_headers).status_code == 422


def test_batch_empty_or_invalid_structure_is_422_and_saves_nothing(client, auth_headers):
    assert client.post("/orders/batch", json=[], headers=auth_headers).status_code == 422
    bad = _items(2) + [{"customer_name": "broken"}]
    assert client.post("/orders/batch", json=bad, headers=auth_headers).status_code == 422
    assert client.post("/orders/batch", json={"orders": _items(1)}, headers=auth_headers).status_code == 422
    assert client.get("/orders", headers=auth_headers).json() == []


def test_one_failed_forecast_does_not_break_the_others(client, auth_headers, monkeypatch):
    async def flaky(http_client, params):
        if params["area_sqm"] == 51:
            raise ForecastTimeout()
        return params["area_sqm"] * 1000.0

    monkeypatch.setattr(services, "fetch_forecast", flaky)
    r = client.post("/orders/batch", json=_items(3), headers=auth_headers)
    assert r.status_code == 200
    results = r.json()["results"]
    assert [x["status"] for x in results] == ["priced", "failed", "priced"]
    assert results[1]["error"] == "ForecastTimeout" and "predicted_price" not in results[1]
    # every valid order is stored, also the one without a forecast
    stored = client.get("/orders", headers=auth_headers).json()
    assert [o["status"] for o in stored] == ["priced", "failed", "priced"]
    assert stored[1]["predicted_price"] is None


def test_batch_with_forecast_down_still_saves_orders(client, auth_headers, forecast_down):
    r = client.post("/orders/batch", json=_items(4), headers=auth_headers)
    assert r.status_code == 200
    results = r.json()["results"]
    assert all(x["status"] == "failed" and x["error"] == "ForecastUnavailable" for x in results)
    assert len(client.get("/orders", headers=auth_headers).json()) == 4


def test_batch_requests_run_concurrently(client, auth_headers, monkeypatch):
    """10 forecasts of 0.3 s each: sequential would need >= 3 s, concurrent ~0.3 s."""

    async def slow(http_client, params):
        await asyncio.sleep(0.3)
        return 1.0

    monkeypatch.setattr(services, "fetch_forecast", slow)
    started = time.perf_counter()
    r = client.post("/orders/batch", json=_items(10), headers=auth_headers)
    elapsed = time.perf_counter() - started
    assert r.status_code == 200 and r.json()["total"] == 10
    assert elapsed < 1.5, f"batch took {elapsed:.2f}s - requests are not concurrent"


def test_batch_events_are_logged(client, auth_headers):
    r = client.post("/orders/batch", json=_items(2), headers=auth_headers)
    order_id = r.json()["results"][0]["order_id"]
    events = client.get(f"/events?order_id={order_id}", headers=auth_headers).json()
    assert [e["result"] for e in events] == ["priced"]
