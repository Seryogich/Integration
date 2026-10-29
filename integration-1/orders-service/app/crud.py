from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, schemas


def create_order(
    db: Session,
    data: schemas.OrderCreate,
    price: float | None,
) -> models.Order:
    """Create a new order and persist it to the database."""
    order = models.Order(
        **data.model_dump(),
        predicted_price=price,
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    return order


def get_order(db: Session, oid: int) -> models.Order | None:
    """Retrieve an order by its ID."""
    return db.get(models.Order, oid)


def list_orders(
    db: Session,
    limit: int = 20,
    offset: int = 0,
) -> list[models.Order]:
    """Return orders sorted by ID in descending order."""
    return list(
        db.scalars(
            select(models.Order)
            .order_by(models.Order.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def update_order(
    db: Session,
    order: models.Order,
    data: schemas.OrderUpdate,
    *,
    reprice: bool = False,
    price: float | None = None,
) -> models.Order:
    """Update the provided fields of an existing order.

    If ``reprice`` is True, ``predicted_price`` is overwritten with
    ``price`` in the same transaction. ``price=None`` means the new
    prediction could not be obtained, so the stale value is cleared
    instead of being left next to changed property parameters.
    """
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(order, key, value)

    if reprice:
        order.predicted_price = price

    db.commit()
    db.refresh(order)

    return order


def delete_order(db: Session, order: models.Order) -> None:
    """Delete an existing order from the database."""
    db.delete(order)
    db.commit()
