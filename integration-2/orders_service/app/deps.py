from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .security import decode_access_token

# tokenUrl matches the login route (R2.8) -> Swagger UI "Authorize" works.
# auto_error=False: we raise the 401 ourselves so the behaviour is explicit.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Validate the bearer token, load the user, check is_active (R2.6)."""
    if not token:
        raise _unauthorized()
    username = decode_access_token(token)
    if username is None:
        raise _unauthorized("Invalid or expired token")
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active:
        raise _unauthorized("Invalid or expired token")
    return user
