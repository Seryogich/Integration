import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from .config import SecretError, get_settings
from .database import init_db
from .routers import auth, health, orders

log = logging.getLogger("uvicorn.error")


def init_db_with_retry(attempts: int = 30, delay: float = 2.0) -> None:
    """PostgreSQL may need a few seconds after its healthcheck turns green."""
    for attempt in range(1, attempts + 1):
        try:
            init_db()
            return
        except OperationalError as exc:
            if attempt == attempts:
                raise
            log.warning("Database not ready (attempt %d/%d): %s", attempt, attempts, exc.orig)
            time.sleep(delay)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast (R1.9, R3.1): without secrets the application must not start.
    try:
        settings = get_settings()
    except SecretError as exc:
        log.critical("FATAL: cannot start - %s", exc)
        raise
    log.info(
        "Secrets loaded from /run/secrets; token lifetime %d min; forecast service at %s",
        settings.access_token_expire_minutes,
        settings.forecast_url,
    )
    init_db_with_retry()
    yield


app = FastAPI(
    title="Orders API",
    version="0.2.0",
    description="Order management with house price forecasts. Single external entry point; "
    "all /orders routes require a Bearer JWT obtained from POST /auth/login.",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(orders.router)
