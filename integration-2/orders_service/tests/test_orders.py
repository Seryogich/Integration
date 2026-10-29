from app.routers import orders as orders_router
from tests.conftest import ORDER


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_access_policy_for_anonymous(client):
    """R2.6 access matrix, anonymous column."""
    for method, path, kwargs in [
        ("get", "/orders", {}),
        ("get", "/orders/1", {}),
        ("post", "/orders", {"json": ORDER}),
        ("patch", "/orders/1", {"json": {"status": "confirmed"}}),
        ("delete", "/orders/1", {}),
        ("get", "/auth/me", {}),
    ]:
        r = getattr(client, method)(path, **kwargs)
        assert r.status_code == 401, (method, path, r.status_code)
        assert r.headers["www-authenticate"] == "Bearer"


def test_create_order_with_forecast(client, auth_headers):
    r = client.post("/orders", json=ORDER, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["predicted_price"] == 80000.0


def test_create_order_graceful_degradation(client, auth_headers, forecast_down):
    """T12 / R3.5: Forecast API down -> 201 with predicted_price null."""
    r = client.post("/orders", json=ORDER, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["predicted_price"] is None


def test_patch_property_params_re_requests_forecast(client, auth_headers):
    """T9: changing property parameters re-requests the forecast."""
    created = client.post("/orders", json=ORDER, headers=auth_headers).json()
    r = client.patch(f"/orders/{created['id']}", json={"area_sqm": 120}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["predicted_price"] == 120000.0


def test_patch_status_only_keeps_forecast(client, auth_headers):
    created = client.post("/orders", json=ORDER, headers=auth_headers).json()
    r = client.patch(f"/orders/{created['id']}", json={"status": "confirmed"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"
    assert r.json()["predicted_price"] == created["predicted_price"]


def test_patch_with_forecast_down_clears_stale_price(client, auth_headers, monkeypatch):
    created = client.post("/orders", json=ORDER, headers=auth_headers).json()
    assert created["predicted_price"] == 80000.0

    monkeypatch.setattr(orders_router, "fetch_forecast", lambda *args: None)  # service goes down
    r = client.patch(f"/orders/{created['id']}", json={"bedrooms": 4}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["predicted_price"] is None


def test_patch_null_field_is_422(client, auth_headers):
    created = client.post("/orders", json=ORDER, headers=auth_headers).json()
    r = client.patch(f"/orders/{created['id']}", json={"area_sqm": None}, headers=auth_headers)
    assert r.status_code == 422


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
