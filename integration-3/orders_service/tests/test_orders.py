from tests.conftest import ORDER


def _get(client, headers, order_id):
    r = client.get(f"/orders/{order_id}", headers=headers)
    assert r.status_code == 200
    return r.json()


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_access_policy_for_anonymous(client):
    """Practice 2 access matrix, anonymous column (now incl. the Practice 3 endpoints)."""
    for method, path, kwargs in [
        ("get", "/orders", {}),
        ("get", "/orders/1", {}),
        ("post", "/orders", {"json": ORDER}),
        ("post", "/orders/batch", {"json": [ORDER]}),
        ("post", "/orders/1/forecast", {}),
        ("patch", "/orders/1", {"json": {"order_status": "confirmed"}}),
        ("delete", "/orders/1", {}),
        ("get", "/events", {}),
        ("get", "/auth/me", {}),
    ]:
        r = getattr(client, method)(path, **kwargs)
        assert r.status_code == 401, (method, path, r.status_code)
        assert r.headers["www-authenticate"] == "Bearer"


def test_create_returns_202_pending_and_location(client, auth_headers):
    r = client.post("/orders", json=ORDER, headers=auth_headers)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending"  # the response is built BEFORE the forecast runs
    assert body["predicted_price"] is None
    assert body["order_status"] == "new"
    assert r.headers["location"] == f"/orders/{body['id']}"


def test_forecast_is_computed_after_the_response(client, auth_headers):
    order_id = client.post("/orders", json=ORDER, headers=auth_headers).json()["id"]
    stored = _get(client, auth_headers, order_id)
    assert stored["status"] == "priced"
    assert stored["predicted_price"] == 80000.0
    assert client.get("/orders", headers=auth_headers).json()[0]["status"] == "priced"


def test_create_order_graceful_degradation(client, auth_headers, forecast_down):
    """T12: Forecast API down -> order is still created (202), later status=failed, price null."""
    r = client.post("/orders", json=ORDER, headers=auth_headers)
    assert r.status_code == 202
    stored = _get(client, auth_headers, r.json()["id"])
    assert stored["status"] == "failed"
    assert stored["predicted_price"] is None


def test_event_log_records_results(client, auth_headers, monkeypatch):
    order_id = client.post("/orders", json=ORDER, headers=auth_headers).json()["id"]
    events = client.get(f"/events?order_id={order_id}", headers=auth_headers).json()
    assert [e["result"] for e in events] == ["priced"]
    assert events[0]["order_id"] == order_id and events[0]["created_at"]


def test_patch_property_params_requests_new_forecast(client, auth_headers):
    created = client.post("/orders", json=ORDER, headers=auth_headers).json()
    r = client.patch(f"/orders/{created['id']}", json={"area_sqm": 120}, headers=auth_headers)
    assert r.status_code == 202
    assert r.json()["status"] == "pending" and r.json()["predicted_price"] is None
    stored = _get(client, auth_headers, created["id"])
    assert stored["status"] == "priced" and stored["predicted_price"] == 120000.0


def test_patch_non_property_data_does_not_recompute(client, auth_headers):
    created = client.post("/orders", json=ORDER, headers=auth_headers).json()
    before = _get(client, auth_headers, created["id"])
    r = client.patch(
        f"/orders/{created['id']}",
        json={"customer_name": "Renamed", "order_status": "confirmed"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["customer_name"] == "Renamed" and body["order_status"] == "confirmed"
    assert body["status"] == "priced" and body["predicted_price"] == before["predicted_price"]
    events = client.get(f"/events?order_id={created['id']}", headers=auth_headers).json()
    assert len(events) == 1  # no new computation


def test_patch_with_forecast_down_ends_failed_without_stale_price(
    client, auth_headers, monkeypatch
):
    created = client.post("/orders", json=ORDER, headers=auth_headers).json()
    assert _get(client, auth_headers, created["id"])["predicted_price"] == 80000.0

    from app import services
    from app.forecast_client import ForecastTimeout

    async def down(http_client, params):
        raise ForecastTimeout()

    monkeypatch.setattr(services, "fetch_forecast", down)
    r = client.patch(f"/orders/{created['id']}", json={"bedrooms": 4}, headers=auth_headers)
    assert r.status_code == 202
    stored = _get(client, auth_headers, created["id"])
    assert stored["status"] == "failed" and stored["predicted_price"] is None
    events = client.get(f"/events?order_id={created['id']}", headers=auth_headers).json()
    assert events[0]["result"] == "failed" and events[0]["details"] == "ForecastTimeout"


def test_old_status_field_is_no_longer_writable(client, auth_headers):
    """`status` is now the computed forecast state; the business status is `order_status`."""
    created = client.post("/orders", json=ORDER, headers=auth_headers).json()
    r = client.patch(f"/orders/{created['id']}", json={"status": "priced"}, headers=auth_headers)
    assert r.status_code == 422


def test_patch_null_field_is_422(client, auth_headers):
    created = client.post("/orders", json=ORDER, headers=auth_headers).json()
    r = client.patch(f"/orders/{created['id']}", json={"area_sqm": None}, headers=auth_headers)
    assert r.status_code == 422


def test_rerun_forecast_updates_same_order_without_duplicates(client, auth_headers):
    created = client.post("/orders", json=ORDER, headers=auth_headers).json()
    for _ in range(3):
        r = client.post(f"/orders/{created['id']}/forecast", headers=auth_headers)
        assert r.status_code == 202 and r.json()["status"] == "pending"
    assert len(client.get("/orders", headers=auth_headers).json()) == 1
    stored = _get(client, auth_headers, created["id"])
    assert stored["status"] == "priced" and stored["predicted_price"] == 80000.0
    assert client.post("/orders/999/forecast", headers=auth_headers).status_code == 404


def test_list_get_delete(client, auth_headers):
    created = client.post("/orders", json=ORDER, headers=auth_headers).json()
    oid = created["id"]

    assert client.get("/orders", headers=auth_headers).status_code == 200
    assert len(client.get("/orders", headers=auth_headers).json()) == 1
    assert client.get(f"/orders/{oid}", headers=auth_headers).status_code == 200

    assert client.delete(f"/orders/{oid}", headers=auth_headers).status_code == 204
    assert client.get(f"/orders/{oid}", headers=auth_headers).status_code == 404


def test_invalid_order_is_422(client, auth_headers):
    r = client.post("/orders", json={**ORDER, "area_sqm": -5}, headers=auth_headers)
    assert r.status_code == 422
