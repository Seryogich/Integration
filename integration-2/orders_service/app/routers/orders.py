from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..forecast_client import fetch_forecast
from ..models import Order
from ..schemas import OrderCreate, OrderOut, OrderUpdate

# Every /orders route requires an authenticated user (R2.6).
router = APIRouter(
    prefix="/orders",
    tags=["orders"],
    dependencies=[Depends(get_current_user)],
)

PROPERTY_FIELDS = {"area_sqm", "bedrooms", "bathrooms", "year_built"}


def _forecast_for(order: Order) -> float | None:
    return fetch_forecast(order.area_sqm, order.bedrooms, order.bathrooms, order.year_built)


def _get_or_404(db: Session, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@router.get("", response_model=list[OrderOut])
def list_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return db.scalars(select(Order).order_by(Order.id).offset(skip).limit(limit)).all()


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, db: Session = Depends(get_db)):
    order = Order(**payload.model_dump())
    # Graceful degradation: if the Forecast API is down the order is still
    # created, with predicted_price = null.
    order.predicted_price = _forecast_for(order)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, order_id)


@router.patch("/{order_id}", response_model=OrderOut)
def update_order(order_id: int, payload: OrderUpdate, db: Session = Depends(get_db)):
    order = _get_or_404(db, order_id)
    updates = payload.model_dump(exclude_unset=True)

    for name, value in updates.items():
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Field '{name}' cannot be null",
            )
        setattr(order, name, value)

    # Property parameters changed -> the old forecast is stale: re-request it.
    # If the Forecast API is unavailable the stale value is cleared (null)
    # rather than leaving a price that no longer matches the order.
    if PROPERTY_FIELDS & updates.keys():
        order.predicted_price = _forecast_for(order)

    db.commit()
    db.refresh(order)
    return order


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: int, db: Session = Depends(get_db)):
    order = _get_or_404(db, order_id)
    db.delete(order)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
