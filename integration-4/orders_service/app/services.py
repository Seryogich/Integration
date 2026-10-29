"""Deferred forecast computation (Practice 3/4, variant A: FastAPI BackgroundTasks).

Practice 4: also stores the model_version returned by the Forecast API.
"""

from __future__ import annotations

import logging

import httpx
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import update
from sqlalchemy.orm import Session

from . import database
from .config import get_settings
from .forecast_client import ForecastError, fetch_forecast
from .models import Order, OrderEvent
from .schemas import BatchItemResult, OrderCreate

log = logging.getLogger("uvicorn.error")


def order_params(order: Order) -> dict:
    return {
        "area_sqm": order.area_sqm,
        "bedrooms": order.bedrooms,
        "bathrooms": order.bathrooms,
        "year_built": order.year_built,
    }


def record_event(db: Session, order_id: int, result: str, details: str | None = None) -> None:
    db.add(OrderEvent(order_id=order_id, event="forecast", result=result, details=details))


async def request_forecast(
    client: httpx.AsyncClient, params: dict
) -> tuple[float | None, str | None, str | None]:
    """Returns (price, model_version, None) or (None, None, error_code)."""
    try:
        price, model_version = await fetch_forecast(client, params)
        return price, model_version, None
    except ForecastError as exc:
        log.warning("Forecast API: %s", exc.code)
        return None, None, exc.code
    except Exception:
        log.exception("unexpected error while requesting a forecast")
        return None, None, "InternalError"


def finalize_order(
    db: Session,
    order_id: int,
    version: int,
    price: float | None,
    model_version: str | None,
    error: str | None,
) -> bool:
    """Store the outcome in the existing order and log it. Returns True if it was applied."""
    status = "priced" if error is None else "failed"
    values = {"status": status, "predicted_price": price, "model_version": model_version}
    result = db.execute(
        update(Order)
        .where(Order.id == order_id, Order.forecast_version == version)
        .values(**values)
    )
    if result.rowcount:
        record_event(db, order_id, status, error)
        applied = True
    else:
        record_event(
            db,
            order_id,
            "skipped",
            "order deleted or modified while the forecast was in progress",
        )
        applied = False
    db.commit()
    return applied


def create_pending_orders(db: Session, items: list[OrderCreate]) -> list[tuple[int, int, dict]]:
    orders = [
        Order(**item.model_dump(), status="pending", predicted_price=None, model_version=None)
        for item in items
    ]
    db.add_all(orders)
    db.commit()
    return [(o.id, o.forecast_version, order_params(o)) for o in orders]


def store_batch_results(
    db: Session,
    snapshot: list[tuple[int, int, dict]],
    outcomes: list[tuple[float | None, str | None, str | None]],
) -> list[BatchItemResult]:
    results: list[BatchItemResult] = []
    for index, ((order_id, version, _), (price, model_version, error)) in enumerate(
        zip(snapshot, outcomes)
    ):
        try:
            applied = finalize_order(db, order_id, version, price, model_version, error)
        except Exception:
            log.exception("could not store the forecast of order %s", order_id)
            db.rollback()
            results.append(
                BatchItemResult(index=index, order_id=order_id, status="failed", error="StorageError")
            )
            continue
        if not applied:
            results.append(
                BatchItemResult(index=index, order_id=order_id, status="failed", error="OrderChanged")
            )
        elif error is None:
            results.append(
                BatchItemResult(
                    index=index,
                    order_id=order_id,
                    status="priced",
                    predicted_price=price,
                    model_version=model_version,
                )
            )
        else:
            results.append(
                BatchItemResult(index=index, order_id=order_id, status="failed", error=error)
            )
    return results


def _prepare(order_id: int, version: int) -> dict | None:
    with database.get_session_factory()() as db:
        order = db.get(Order, order_id)
        if order is None:
            record_event(db, order_id, "skipped", "order deleted before processing")
            db.commit()
            return None
        if order.forecast_version != version:
            record_event(db, order_id, "skipped", "outdated task: the order was modified")
            db.commit()
            return None
        return order_params(order)


def _finish(
    order_id: int,
    version: int,
    price: float | None,
    model_version: str | None,
    error: str | None,
) -> None:
    with database.get_session_factory()() as db:
        finalize_order(db, order_id, version, price, model_version, error)


async def run_forecast_task(order_id: int, version: int) -> None:
    try:
        params = await run_in_threadpool(_prepare, order_id, version)
        if params is None:
            return
        settings = get_settings()
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.forecast_timeout)) as client:
            price, model_version, error = await request_forecast(client, params)
        await run_in_threadpool(_finish, order_id, version, price, model_version, error)
    except Exception:
        log.exception("forecast task for order %s crashed", order_id)
        try:
            await run_in_threadpool(_finish, order_id, version, None, None, "InternalError")
        except Exception:
            log.exception("could not mark order %s as failed", order_id)
