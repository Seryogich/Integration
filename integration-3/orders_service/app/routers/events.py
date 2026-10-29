from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import OrderEvent
from ..schemas import EventOut

router = APIRouter(
    prefix="/events",
    tags=["events"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[EventOut])
def list_events(
    order_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Event log of forecast computations: order id, result and timestamp (newest first)."""
    query = select(OrderEvent).order_by(OrderEvent.id.desc()).limit(limit)
    if order_id is not None:
        query = query.where(OrderEvent.order_id == order_id)
    return db.scalars(query).all()
