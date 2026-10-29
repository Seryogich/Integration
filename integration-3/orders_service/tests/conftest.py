"""Test fixtures: temporary secret files + in-memory SQLite, no Docker needed.

SECRETS_DIR is redirected to a temp directory *before* the application is
imported (the application otherwise reads /run/secrets).
"""

import os
import tempfile
from pathlib import Path

_SECRETS = Path(tempfile.mkdtemp(prefix="test-secrets-"))
(_SECRETS / "db_password").write_text("test/db+pass=word\n")
(_SECRETS / "jwt_secret_key").write_text("unit-test-signing-key-0123456789-abcdefghijklmnop\n")
os.environ["SECRETS_DIR"] = str(_SECRETS)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import database, models, services  # noqa: E402,F401
from app.database import Base, get_db  # noqa: E402
from app.forecast_client import ForecastError  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def session_factory(monkeypatch):
    """In-memory SQLite shared by the request handlers AND by background tasks.

    Background tasks open their own session through database.get_session_factory(),
    so that function is redirected to the same SQLite database.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "get_session_factory", lambda: Session)
    return Session


@pytest.fixture()
def client(session_factory, monkeypatch):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Forecast API "up": deterministic price derived from the area.
    async def fake_fetch(http_client, params):
        return round(params["area_sqm"] * 1000.0, 2)

    monkeypatch.setattr(services, "fetch_forecast", fake_fetch)
    # TestClient without a `with` block does not run the lifespan (no real DB needed).
    # Starlette's TestClient runs background tasks before the call returns, so after
    # `client.post("/orders")` the forecast has already been computed.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def forecast_down(client, monkeypatch):
    async def down(http_client, params):
        raise ForecastError()

    monkeypatch.setattr(services, "fetch_forecast", down)


CREDENTIALS = {"username": "alice", "password": "correct horse battery"}


@pytest.fixture()
def auth_headers(client):
    assert client.post("/auth/register", json=CREDENTIALS).status_code == 201
    token = client.post("/auth/login", data=CREDENTIALS).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


ORDER = {
    "customer_name": "ACME Ltd",
    "area_sqm": 80,
    "bedrooms": 3,
    "bathrooms": 2,
    "year_built": 2010,
}
