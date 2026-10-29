"""Password hashing (Argon2id via pwdlib) and JWT (HS256) helpers."""

from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from .config import get_settings

ALGORITHM = "HS256"

# PasswordHash.recommended() = Argon2id with a random per-hash salt and
# OWASP-aligned work-factor parameters; the parameters are stored in the hash.
_password_hash = PasswordHash.recommended()

# Verified against when the username is unknown, so that "unknown user" and
# "wrong password" take comparable time (no timing-based user enumeration).
_DUMMY_HASH = _password_hash.hash("dummy-password-for-timing-equalisation")


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return _password_hash.verify(password, hashed_password)
    except Exception:  # malformed hash etc. -> treat as failure
        return False


def verify_against_dummy(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def create_access_token(username: str) -> str:
    settings = get_settings()
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=settings.access_token_expire_minutes)
    claims = {"sub": username, "iat": issued_at, "exp": expires_at}
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Return the username (sub) of a valid token, or None.

    The accepted algorithm is fixed to HS256 (whitelist). The `alg` value in the
    token header is never trusted, which blocks `alg: none` and algorithm
    confusion attacks (R2.5).
    """
    try:
        claims = jwt.decode(
            token,
            get_settings().jwt_secret_key,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    subject = claims.get("sub")
    return subject if isinstance(subject, str) and subject else None
