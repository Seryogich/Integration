"""Configuration and secrets.

Non-sensitive settings come from environment variables (filled from .env by
Docker Compose). Secrets are read exclusively from files under /run/secrets/
(R1.6, R3.1): there are no defaults and no fallbacks to environment variables.
"""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

MIN_JWT_KEY_LENGTH = 32  # characters; HS256 expects at least 256 bits of key material


class SecretError(RuntimeError):
    """A required secret is missing, unreadable, empty or unusable."""


def _secrets_dir() -> Path:
    # The directory (not a secret value) can be redirected, which the unit tests use.
    return Path(os.environ.get("SECRETS_DIR", "/run/secrets"))


def read_secret(name: str) -> str:
    """Read /run/secrets/<name>, stripping surrounding whitespace/newlines."""
    path = _secrets_dir() / name
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise SecretError(
            f"Required secret '{name}' was not found at {path}. "
            f"Create secrets/{name} on the host and declare it in docker-compose.yml "
            f"(see secrets/README.md)."
        ) from None
    except OSError as exc:
        raise SecretError(f"Secret '{name}' at {path} could not be read: {exc}") from exc
    if not value:
        raise SecretError(f"Secret '{name}' at {path} is empty.")
    return value


@dataclass(frozen=True)
class Settings:
    postgres_user: str
    postgres_db: str
    postgres_host: str
    postgres_port: int
    forecast_url: str
    forecast_timeout: float
    batch_max_items: int
    access_token_expire_minutes: int
    db_password: str = field(repr=False)
    jwt_secret_key: str = field(repr=False)


@lru_cache
def get_settings() -> Settings:
    """Load settings once. Raises SecretError if a secret is unavailable."""
    db_password = read_secret("db_password")
    jwt_secret_key = read_secret("jwt_secret_key")
    if len(jwt_secret_key) < MIN_JWT_KEY_LENGTH:
        raise SecretError(
            f"Secret 'jwt_secret_key' is too short ({len(jwt_secret_key)} characters, "
            f"minimum {MIN_JWT_KEY_LENGTH}). Generate it with: openssl rand -base64 48"
        )

    return Settings(
        postgres_user=os.environ.get("POSTGRES_USER", "orders"),
        postgres_db=os.environ.get("POSTGRES_DB", "orders"),
        postgres_host=os.environ.get("POSTGRES_HOST", "postgres"),
        postgres_port=int(os.environ.get("POSTGRES_PORT", "5432")),
        forecast_url=os.environ.get("FORECAST_URL", "http://forecast-api:8001").rstrip("/"),
        forecast_timeout=float(os.environ.get("FORECAST_TIMEOUT", "3")),
        batch_max_items=int(os.environ.get("BATCH_MAX_ITEMS", "50")),
        access_token_expire_minutes=int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30")),
        db_password=db_password,
        jwt_secret_key=jwt_secret_key,
    )
