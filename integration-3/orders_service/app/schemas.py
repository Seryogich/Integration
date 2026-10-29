from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PASSWORD_MIN_BYTES = 8
PASSWORD_MAX_BYTES = 72  # bcrypt input limit; kept for every hash for a uniform policy


# ---------------------------------------------------------------- users / auth
class UserCreate(BaseModel):
    """Registration input. Unknown fields (is_active, is_admin, ...) are rejected
    with 422, so privilege-related fields can never be supplied (R2.4)."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str

    @field_validator("password")
    @classmethod
    def password_length_in_bytes(cls, value: str) -> str:
        size = len(value.encode("utf-8"))
        if not PASSWORD_MIN_BYTES <= size <= PASSWORD_MAX_BYTES:
            raise ValueError(
                f"password must be {PASSWORD_MIN_BYTES}-{PASSWORD_MAX_BYTES} bytes (UTF-8)"
            )
        return value


class UserOut(BaseModel):
    """Public representation. hashed_password is deliberately absent (R2.2)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --------------------------------------------------------------------- orders
OrderStatus = Literal["new", "confirmed", "completed", "cancelled"]


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_name: str = Field(min_length=1, max_length=128)
    area_sqm: float = Field(gt=0, le=5000)
    bedrooms: int = Field(ge=0, le=20)
    bathrooms: int = Field(ge=0, le=20)
    year_built: int = Field(ge=1800, le=2100)


class OrderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_name: str | None = Field(default=None, min_length=1, max_length=128)
    area_sqm: float | None = Field(default=None, gt=0, le=5000)
    bedrooms: int | None = Field(default=None, ge=0, le=20)
    bathrooms: int | None = Field(default=None, ge=0, le=20)
    year_built: int | None = Field(default=None, ge=1800, le=2100)
    order_status: OrderStatus | None = None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_name: str
    area_sqm: float
    bedrooms: int
    bathrooms: int
    year_built: int
    order_status: str  # business status: new | confirmed | completed | cancelled
    status: str  # forecast state: pending | priced | failed
    predicted_price: float | None
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------- batch / events
class BatchItemResult(BaseModel):
    index: int
    order_id: int
    status: str  # priced | failed
    predicted_price: float | None = None
    error: str | None = None


class BatchResponse(BaseModel):
    total: int
    results: list[BatchItemResult]


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    event: str
    result: str
    details: str | None
    created_at: datetime
