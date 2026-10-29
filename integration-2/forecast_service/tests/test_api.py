from fastapi.testclient import TestClient

from app.main import app


def test_predict_and_health():
    with TestClient(app) as client:  # runs lifespan (model training)
        r = client.get("/health")
        assert r.status_code == 200 and r.json()["status"] == "ok"

        r = client.post(
            "/predict",
            json={"area_sqm": 80, "bedrooms": 3, "bathrooms": 2, "year_built": 2010},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["predicted_price"] > 0
        assert "model_version" in body

        r = client.get("/model/info")
        assert r.status_code == 200
        assert "test_r2" in r.json()["metrics"]


def test_predict_validation():
    with TestClient(app) as client:
        r = client.post("/predict", json={"area_sqm": -1, "bedrooms": 3, "bathrooms": 2, "year_built": 2010})
        assert r.status_code == 422
