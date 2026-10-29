import pytest

from app import config
from app.config import SecretError, get_settings, read_secret
from app.database import build_database_url


@pytest.fixture()
def secrets_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRETS_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_read_secret_strips_trailing_whitespace(secrets_dir):
    (secrets_dir / "x").write_text("  value\n\n")
    assert read_secret("x") == "value"


def test_missing_secret_fails_with_explicit_message(secrets_dir):
    with pytest.raises(SecretError, match="jwt_secret_key"):
        read_secret("jwt_secret_key")


def test_empty_secret_fails(secrets_dir):
    (secrets_dir / "jwt_secret_key").write_text("\n")
    with pytest.raises(SecretError, match="empty"):
        read_secret("jwt_secret_key")


def test_settings_fail_fast_without_jwt_key(secrets_dir):
    (secrets_dir / "db_password").write_text("pw")
    with pytest.raises(SecretError, match="jwt_secret_key"):
        get_settings()


def test_settings_reject_short_jwt_key(secrets_dir):
    (secrets_dir / "db_password").write_text("pw")
    (secrets_dir / "jwt_secret_key").write_text("short")
    with pytest.raises(SecretError, match="too short"):
        get_settings()


def test_no_environment_fallback_for_jwt_key(secrets_dir, monkeypatch):
    (secrets_dir / "db_password").write_text("pw")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 64)
    with pytest.raises(SecretError):
        get_settings()


def test_dsn_escapes_special_characters(secrets_dir):
    (secrets_dir / "db_password").write_text("p@ss/w+rd=:#\n")
    (secrets_dir / "jwt_secret_key").write_text("k" * 48)
    url = build_database_url(get_settings())
    assert url.password == "p@ss/w+rd=:#"
    rendered = url.render_as_string(hide_password=False)
    assert "p@ss/w+rd=:#" not in rendered  # escaped in the string form
    assert "%40" in rendered  # '@' percent-encoded


def test_settings_repr_does_not_leak_secrets(secrets_dir):
    (secrets_dir / "db_password").write_text("super-secret-db-pass")
    (secrets_dir / "jwt_secret_key").write_text("k" * 48)
    text = repr(get_settings())
    assert "super-secret-db-pass" not in text and "k" * 48 not in text
    assert config.MIN_JWT_KEY_LENGTH == 32
