import base64
import json
import time
from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings
from tests.conftest import CREDENTIALS


def _b64(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_register_ok_and_never_leaks_hash(client):
    r = client.post("/auth/register", json=CREDENTIALS)
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "alice" and body["is_active"] is True
    assert "hashed_password" not in body and "password" not in body


def test_register_duplicate_is_409(client):
    assert client.post("/auth/register", json=CREDENTIALS).status_code == 201
    assert client.post("/auth/register", json=CREDENTIALS).status_code == 409


def test_register_validation_422(client):
    too_short = {"username": "bob", "password": "short"}
    too_long = {"username": "bob", "password": "x" * 73}
    multibyte_over_72 = {"username": "bob", "password": "я" * 40}  # 80 bytes in UTF-8
    for payload in (too_short, too_long, multibyte_over_72):
        assert client.post("/auth/register", json=payload).status_code == 422


def test_register_rejects_privilege_fields(client):
    payload = {**CREDENTIALS, "is_active": False, "is_admin": True}
    assert client.post("/auth/register", json=payload).status_code == 422


def test_login_ok_returns_bearer_token(client):
    client.post("/auth/register", json=CREDENTIALS)
    r = client.post("/auth/login", data=CREDENTIALS)
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["access_token"]


def test_login_requires_form_encoding(client):
    client.post("/auth/register", json=CREDENTIALS)
    assert client.post("/auth/login", json=CREDENTIALS).status_code == 422


def test_login_errors_are_identical(client):
    client.post("/auth/register", json=CREDENTIALS)
    wrong_pw = client.post("/auth/login", data={"username": "alice", "password": "nope-nope-nope"})
    unknown = client.post("/auth/login", data={"username": "ghost", "password": "nope-nope-nope"})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()
    assert wrong_pw.headers["www-authenticate"] == "Bearer"


def test_me_requires_token(client):
    r = client.get("/auth/me")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_me_with_token(client, auth_headers):
    r = client.get("/auth/me", headers=auth_headers)
    assert r.status_code == 200 and r.json()["username"] == "alice"


def test_token_claims_and_algorithm(client):
    client.post("/auth/register", json=CREDENTIALS)
    token = client.post("/auth/login", data=CREDENTIALS).json()["access_token"]
    assert jwt.get_unverified_header(token)["alg"] == "HS256"
    settings = get_settings()
    claims = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
    assert claims["sub"] == "alice"
    assert claims["exp"] - claims["iat"] == settings.access_token_expire_minutes * 60


def test_token_signed_with_other_key_rejected(client, auth_headers):
    """Simulates key rotation: a token from the old key must be refused (T11)."""
    now = datetime.now(timezone.utc)
    old = jwt.encode(
        {"sub": "alice", "iat": now, "exp": now + timedelta(minutes=5)},
        "an-old-rotated-key-0123456789-abcdefghijklmnopqrstuv",
        algorithm="HS256",
    )
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {old}"})
    assert r.status_code == 401


def test_expired_token_rejected(client, auth_headers):
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {"sub": "alice", "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
        get_settings().jwt_secret_key,
        algorithm="HS256",
    )
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


def test_alg_none_token_rejected(client, auth_headers):
    now = int(time.time())
    forged = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64({'sub': 'alice', 'iat': now, 'exp': now + 600})}."
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_tampered_payload_rejected(client, auth_headers):
    token = auth_headers["Authorization"].split()[1]
    header, _payload, signature = token.split(".")
    now = int(time.time())
    forged_payload = _b64({"sub": "admin", "iat": now, "exp": now + 600})
    tampered = f"{header}.{forged_payload}.{signature}"
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert r.status_code == 401


def test_token_without_exp_rejected(client, auth_headers):
    no_exp = jwt.encode({"sub": "alice"}, get_settings().jwt_secret_key, algorithm="HS256")
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {no_exp}"})
    assert r.status_code == 401


def test_openapi_token_url_matches_login(client):
    schema = client.get("/openapi.json").json()
    flows = schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"]
    assert flows["password"]["tokenUrl"] == "auth/login"
