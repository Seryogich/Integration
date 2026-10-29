import asyncio

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user, get_http_client
from ..models import Order
from ..schemas import BatchResponse, OrderCreate, OrderOut, OrderUpdate

# Every /orders route requires an authenticated user (Practice 2, R2.6) - also /orders/batch.
router = APIRouter(
    prefix="/orders",
    tags=["orders"],
    dependencies=[Depends(get_current_user)],
)

PROPERTY_FIELDS = {"area_sqm", "bedrooms", "bathrooms", "year_built"}


def _get_or_404(db: Session, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


def _request_new_forecast(order: Order) -> None:
    """Mark the order as waiting for a (new) forecast; the caller commits and schedules the task."""
    order.status = "pending"
    order.predicted_price = None
    order.forecast_version += 1


# ----------------------------------------------------------------------------- Task 1
@router.post("/batch", response_model=BatchResponse, response_model_exclude_none=True)
async def create_batch(
    items: list[OrderCreate],
    client: httpx.AsyncClient | None = Depends(get_http_client),
    db: Session = Depends(get_db),
):
    """Create many orders at once; forecasts are requested CONCURRENTLY (asyncio.gather).

    The endpoint stays synchronous from the client's point of view: the response contains
    the outcome of every element. A schema violation in any element -> 422 for the whole
    request; a failed forecast for one element does not affect the others.
    """
    limit = get_settings().batch_max_items
    if not items:
        raise HTTPException(status_code=422, detail="Batch must contain at least one order")
    if len(items) > limit:
        raise HTTPException(
            status_code=422, detail=f"Too many orders in the batch: {len(items)} > BATCH_MAX_ITEMS={limit}"
        )

    # 1) every valid order is stored first, regardless of the forecast outcome
    snapshot = await run_in_threadpool(services.create_pending_orders, db, items)

    # 2) concurrent forecasts: total wait ~ the slowest request instead of the sum
    outcomes = await asyncio.gather(
        *(services.request_forecast(client, params) for _, _, params in snapshot)
    )

    # 3) store each result separately
    results = await run_in_threadpool(services.store_batch_results, db, snapshot, outcomes)
    return BatchResponse(total=len(results), results=results)


# ----------------------------------------------------------------------------- Task 2
@router.get("", response_model=list[OrderOut])
def list_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return db.scalars(select(Order).order_by(Order.id).offset(skip).limit(limit)).all()


@router.post("", response_model=OrderOut, status_code=status.HTTP_202_ACCEPTED)
def create_order(
    payload: OrderCreate,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
):
    """Save the order as `pending` and return at once; the forecast is computed after the response."""
    order = Order(**payload.model_dump(), status="pending", predicted_price=None)
    db.add(order)
    db.commit()
    db.refresh(order)

    background_tasks.add_task(services.run_forecast_task, order.id, order.forecast_version)
    response.headers["Location"] = f"/orders/{order.id}"
    return order


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, order_id)


# ----------------------------------------------------------------------------- Task 3
@router.patch("/{order_id}", response_model=OrderOut)
def update_order(
    order_id: int,
    payload: OrderUpdate,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
):
    order = _get_or_404(db, order_id)
    updates = payload.model_dump(exclude_unset=True)

    for name, value in updates.items():
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Field '{name}' cannot be null",
            )
        setattr(order, name, value)

    # Property parameters changed -> the old forecast is stale: pending + clear price + new task.
    # Only client/business data changed -> no recomputation.
    reprice = bool(PROPERTY_FIELDS & updates.keys())
    if reprice:
        _request_new_forecast(order)

    db.commit()
    db.refresh(order)

    if reprice:
        background_tasks.add_task(services.run_forecast_task, order.id, order.forecast_version)
        response.status_code = status.HTTP_202_ACCEPTED
    return order


@router.post("/{order_id}/forecast", response_model=OrderOut, status_code=status.HTTP_202_ACCEPTED)
def rerun_forecast(
    order_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Re-run the forecast of an existing order (also used after the Forecast API recovers).

    Idempotent: the SAME order row is updated, no duplicate is ever created.
    """
    order = _get_or_404(db, order_id)
    _request_new_forecast(order)
    db.commit()
    db.refresh(order)
    background_tasks.add_task(services.run_forecast_task, order.id, order.forecast_version)
    return order


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: int, db: Session = Depends(get_db)):
    order = _get_or_404(db, order_id)
    db.delete(order)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
