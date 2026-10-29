from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func, true
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    area_sqm: Mapped[float] = mapped_column(Float, nullable=False)
    bedrooms: Mapped[int] = mapped_column(Integer, nullable=False)
    bathrooms: Mapped[int] = mapped_column(Integer, nullable=False)
    year_built: Mapped[int] = mapped_column(Integer, nullable=False)
    # Business status of the order (was `status` in Practice 2).
    order_status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    # Practice 3: state of the (deferred) forecast computation: pending | priced | failed.
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    predicted_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Incremented whenever a new forecast is requested. A background task only writes its
    # result if the version is still the one it started with (stale results are discarded).
    forecast_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class OrderEvent(Base):
    """Event log of forecast computations.

    `order_id` deliberately has no FOREIGN KEY: the log must survive deletion of the order
    (a task for a deleted order is recorded as "skipped").
    """

    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)  # priced | failed | skipped
    details: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
